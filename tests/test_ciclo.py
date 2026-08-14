"""O portão de cadência de `executar_ciclo`, sem Firestore e sem rede.

Este arquivo cobre a decisão "roda ou não roda agora", que até 2026-08-14 não
tinha teste nenhum — nem com o emulador. É também onde vive a coleta FORÇADA,
usada para conferir os produtos na hora, sem esperar a janela de 30 minutos.

Sem fontes ativas, `executar_ciclo` não faz uma única requisição HTTP: o que se
mede aqui é só o portão.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from coletor import config
from coletor.main import executar_ciclo

AGORA = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@dataclass
class RepositorioFalso:
    ultima_coleta: datetime | None = None
    ultima_raspagem: datetime | None = None
    gravou_controle: list = field(default_factory=list)
    gravou_raspagem: list = field(default_factory=list)
    pediu_fontes_ativas: int = 0

    def listar_fontes_pendentes(self):
        return []

    def ler_controle(self):
        return self.ultima_coleta

    def gravar_controle(self, quando):
        self.gravou_controle.append(quando)

    def ler_controle_raspagem(self):
        return self.ultima_raspagem

    def gravar_controle_raspagem(self, quando):
        self.gravou_raspagem.append(quando)

    def listar_fontes_ativas(self):
        self.pediu_fontes_ativas += 1
        return []


def cfg(**extras) -> config.Config:
    base = dict(
        firebase_sa_base64="", telegram_bot_token="", telegram_chat_id="",
        intervalo_coleta_minutos=30, limiar_sanidade="0.70",
        teto_centavos=100_000_000, user_agent="teste",
        intervalo_raspagem_horas=24,
        # Sem categorias a raspagem nem é tentada. Os testes que medem o portão
        # da raspagem passam a lista explicitamente.
        categorias_raspagem=(),
    )
    base.update(extras)
    return config.Config(**base)


# --- portão normal ----------------------------------------------------------


@pytest.mark.asyncio
async def test_fora_da_janela_nao_coleta():
    repo = RepositorioFalso(ultima_coleta=AGORA - timedelta(minutes=5))
    resumo = await executar_ciclo(repo, notificador=object(), cfg=cfg(), agora=AGORA)

    assert resumo["coletou"] is False
    assert repo.pediu_fontes_ativas == 0
    assert repo.gravou_controle == []


@pytest.mark.asyncio
async def test_dentro_da_janela_coleta_e_marca_o_relogio():
    repo = RepositorioFalso(ultima_coleta=AGORA - timedelta(minutes=31))
    resumo = await executar_ciclo(repo, notificador=object(), cfg=cfg(), agora=AGORA)

    assert resumo["coletou"] is True
    assert resumo["forcada"] is False
    assert repo.gravou_controle == [AGORA]


# --- coleta forçada ---------------------------------------------------------


@pytest.mark.asyncio
async def test_forcar_coleta_roda_fora_da_janela():
    repo = RepositorioFalso(ultima_coleta=AGORA - timedelta(minutes=5))
    resumo = await executar_ciclo(
        repo, notificador=object(), cfg=cfg(forcar_coleta=True), agora=AGORA
    )

    assert resumo["coletou"] is True
    assert resumo["forcada"] is True
    assert repo.pediu_fontes_ativas == 1


@pytest.mark.asyncio
async def test_forcar_fora_da_janela_nao_desloca_a_cadencia():
    """O ponto mais importante do modo forçado.

    Gravar `sistema/controle` numa execução manual às 12h05 empurraria a
    próxima automática de 12h30 para 12h35 — um teste manual passaria a mexer
    no agendamento de produção. Forçar lê os preços; não mexe no relógio.
    """
    repo = RepositorioFalso(ultima_coleta=AGORA - timedelta(minutes=5))
    await executar_ciclo(
        repo, notificador=object(), cfg=cfg(forcar_coleta=True), agora=AGORA
    )

    assert repo.gravou_controle == []
    assert repo.ultima_coleta == AGORA - timedelta(minutes=5)


@pytest.mark.asyncio
async def test_forcar_dentro_da_janela_marca_o_relogio_normalmente():
    """Dentro da janela a coleta ia acontecer de qualquer jeito.

    Não gravar aqui faria a próxima execução coletar de novo em 15 minutos, o
    dobro da cadência combinada — forçar não pode virar atalho para coletar
    mais vezes do que o desenhado.
    """
    repo = RepositorioFalso(ultima_coleta=AGORA - timedelta(minutes=31))
    resumo = await executar_ciclo(
        repo, notificador=object(), cfg=cfg(forcar_coleta=True), agora=AGORA
    )

    assert repo.gravou_controle == [AGORA]
    assert resumo["forcada"] is False


@pytest.mark.asyncio
async def test_forcar_coleta_nao_forca_a_raspagem():
    """O pedido explícito: forçar é para os produtos, não para o catálogo.

    A raspagem varre dezenas de páginas de listagem nas lojas; disparar isso a
    cada conferência manual gastaria requisição sem informação nova, já que a
    composição da vitrine muda em dias.
    """
    repo = RepositorioFalso(
        ultima_coleta=AGORA - timedelta(minutes=5),
        ultima_raspagem=AGORA - timedelta(hours=1),      # longe das 24h
    )
    resumo = await executar_ciclo(
        repo, notificador=object(),
        cfg=cfg(forcar_coleta=True,
                categorias_raspagem=("https://www.kabum.com.br/hardware",)),
        agora=AGORA,
    )

    assert resumo["coletou"] is True          # os produtos, sim
    assert resumo["catalogo"] is None         # o catálogo, não
    assert repo.gravou_raspagem == []


# --- leitura do ambiente ----------------------------------------------------


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("true", True), ("TRUE", True), ("1", True), ("sim", True), (" true ", True),
        # A armadilha: `workflow_dispatch` do GitHub entrega STRING, e
        # `bool("false")` é True. Uma execução agendada mandaria "false" e se
        # comportaria como manual.
        ("false", False), ("0", False), ("", False), (None, False),
    ],
)
def test_forcar_coleta_vem_do_ambiente_como_texto(monkeypatch, texto, esperado):
    if texto is None:
        monkeypatch.delenv("FORCAR_COLETA", raising=False)
    else:
        monkeypatch.setenv("FORCAR_COLETA", texto)
    assert config.carregar().forcar_coleta is esperado
