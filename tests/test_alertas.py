"""Fase 4 — tabela de estados da seção 10.1, linha por linha. Sem rede."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from coletor.alertas import (
    ESTADO_ACIMA,
    ESTADO_EM_ALERTA,
    avaliar,
    formatar_reais,
    limite_pela_media,
    montar_mensagem,
    processar,
)
from coletor.notificador import NotificadorMemoria

AGORA = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

# O gatilho É o valor máximo, sem fórmula no meio. `MINIMO` existe só para
# provar que ele NÃO influencia a decisão de alerta.
MINIMO = 100_000   # R$ 1.000,00 — referência do usuário
GATILHO = 110_000  # R$ 1.100,00 — valor máximo, o gatilho de verdade


@dataclass
class ProdutoFalso:
    id: str = "p1"
    nome: str = "Placa de vídeo"
    valor_min_centavos: int = MINIMO
    valor_max_centavos: int = GATILHO
    estado: str = ESTADO_ACIMA
    ultimo_alerta_em: datetime | None = None
    ultimo_preco_alertado_centavos: int | None = None
    ativo: bool = True


@dataclass
class LeituraFalsa:
    preco_centavos: int | None = 100_000
    loja: str = "Loja A"
    url: str = "https://loja-a.example/p/1"
    disponivel: bool = True
    suspeito: bool = False


@dataclass
class RepositorioFalso:
    media: int | None = None
    media_hist: int | None = None
    estados: list = field(default_factory=list)

    def atualizar_estado_alerta(self, produto, estado, preco_centavos, alertado_em):
        self.estados.append((produto.id, estado, preco_centavos, alertado_em))

    def media_30_dias_centavos(self, produto):
        return self.media

    def media_historica_centavos(self, produto):
        return self.media_hist


# --- O gatilho é o valor máximo ----------------------------------------------


@pytest.mark.parametrize("minimo", [1, MINIMO, GATILHO])
def test_o_minimo_nao_muda_a_decisao(minimo):
    """O mínimo é referência do usuário, não piso do alerta.

    Se ele participasse, um preço ABAIXO dele não notificaria — a melhor oferta
    possível passaria batida, que é o oposto do que um monitor de preço serve.
    """
    produto = ProdutoFalso(estado=ESTADO_ACIMA, valor_min_centavos=minimo)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=GATILHO)], AGORA)
    assert decisao.notificar


def test_preco_muito_abaixo_do_minimo_ainda_notifica():
    """Metade do mínimo é uma pechincha, não motivo para silêncio."""
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=MINIMO // 2)], AGORA)
    assert decisao.notificar


def test_um_centavo_acima_do_maximo_nao_notifica():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=GATILHO + 1)], AGORA)
    assert not decisao.notificar
    assert decisao.motivo == "acima_do_gatilho"


# --- Tabela de estados -------------------------------------------------------


def test_linha1_acima_atinge_o_alvo_notifica():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=GATILHO)], AGORA)

    assert decisao.notificar is True
    assert decisao.novo_estado == ESTADO_EM_ALERTA
    assert decisao.motivo == "atingiu_alvo"


def test_linha2_em_alerta_com_queda_de_5pct_renotifica():
    produto = ProdutoFalso(
        estado=ESTADO_EM_ALERTA,
        ultimo_preco_alertado_centavos=100_000,
        ultimo_alerta_em=AGORA - timedelta(hours=48),
    )
    # 95.000 é exatamente 5% abaixo de 100.000
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=95_000)], AGORA)

    assert decisao.notificar is True
    assert decisao.novo_estado == ESTADO_EM_ALERTA
    assert decisao.motivo == "queda_de_5pct"


def test_linha3_em_alerta_sem_queda_de_5pct_silencia():
    produto = ProdutoFalso(
        estado=ESTADO_EM_ALERTA,
        ultimo_preco_alertado_centavos=100_000,
        ultimo_alerta_em=AGORA - timedelta(hours=48),
    )
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=96_000)], AGORA)

    assert decisao.notificar is False
    assert decisao.novo_estado == ESTADO_EM_ALERTA
    assert decisao.motivo == "sem_queda"


def test_linha4_em_alerta_acima_do_gatilho_rearma_em_silencio():
    produto = ProdutoFalso(
        estado=ESTADO_EM_ALERTA, ultimo_preco_alertado_centavos=100_000
    )
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=GATILHO + 1)], AGORA)

    assert decisao.notificar is False
    assert decisao.novo_estado == ESTADO_ACIMA
    assert decisao.motivo == "rearmou"


@pytest.mark.parametrize("estado", [ESTADO_ACIMA, ESTADO_EM_ALERTA])
def test_linha5_indisponivel_silencia_e_nao_muda_estado(estado):
    produto = ProdutoFalso(estado=estado, ultimo_preco_alertado_centavos=100_000)
    leitura = LeituraFalsa(preco_centavos=1, disponivel=False)

    decisao = avaliar(produto, [leitura], AGORA)

    assert decisao.notificar is False
    assert decisao.novo_estado == estado
    assert decisao.motivo == "sem_leitura_valida"


@pytest.mark.parametrize("estado", [ESTADO_ACIMA, ESTADO_EM_ALERTA])
def test_linha6_suspeito_silencia_e_nao_muda_estado(estado):
    produto = ProdutoFalso(estado=estado, ultimo_preco_alertado_centavos=100_000)
    leitura = LeituraFalsa(preco_centavos=1, suspeito=True)

    decisao = avaliar(produto, [leitura], AGORA)

    assert decisao.notificar is False
    assert decisao.novo_estado == estado
    assert decisao.motivo == "sem_leitura_valida"


def test_acima_do_gatilho_estando_acima_nao_notifica():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=GATILHO + 1)], AGORA)

    assert decisao.notificar is False
    assert decisao.novo_estado == ESTADO_ACIMA
    assert decisao.motivo == "acima_do_gatilho"


def test_preco_sem_valor_nao_avalia():
    produto = ProdutoFalso()
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=None)], AGORA)
    assert decisao.motivo == "sem_leitura_valida"


# --- Menor preço entre as fontes --------------------------------------------


def test_usa_o_menor_preco_entre_as_fontes_ativas():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    leituras = [
        LeituraFalsa(preco_centavos=120_000, loja="Cara"),
        LeituraFalsa(preco_centavos=105_000, loja="Barata"),
        LeituraFalsa(preco_centavos=115_000, loja="Media"),
    ]
    decisao = avaliar(produto, leituras, AGORA)

    assert decisao.notificar is True
    assert decisao.preco_centavos == 105_000
    assert decisao.leitura.loja == "Barata"


def test_fonte_suspeita_nao_puxa_o_minimo():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    leituras = [
        LeituraFalsa(preco_centavos=1_000, loja="Suspeita", suspeito=True),
        LeituraFalsa(preco_centavos=105_000, loja="Confiavel"),
    ]
    decisao = avaliar(produto, leituras, AGORA)

    assert decisao.preco_centavos == 105_000
    assert decisao.leitura.loja == "Confiavel"


# --- Cooldown ----------------------------------------------------------------


def test_cooldown_cala_a_mensagem_mas_avanca_o_estado():
    produto = ProdutoFalso(
        estado=ESTADO_ACIMA,
        ultimo_alerta_em=AGORA - timedelta(hours=1),
        ultimo_preco_alertado_centavos=100_000,
    )
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=90_000)], AGORA)

    assert decisao.notificar is False
    assert decisao.motivo == "cooldown"
    assert decisao.novo_estado == ESTADO_EM_ALERTA


def test_cooldown_expirado_volta_a_notificar():
    produto = ProdutoFalso(
        estado=ESTADO_ACIMA,
        ultimo_alerta_em=AGORA - timedelta(hours=24, minutes=1),
        ultimo_preco_alertado_centavos=100_000,
    )
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=90_000)], AGORA)

    assert decisao.notificar is True


def test_cooldown_bloqueia_tambem_a_renotificacao():
    produto = ProdutoFalso(
        estado=ESTADO_EM_ALERTA,
        ultimo_preco_alertado_centavos=100_000,
        ultimo_alerta_em=AGORA - timedelta(hours=2),
    )
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=50_000)], AGORA)

    assert decisao.notificar is False
    assert decisao.motivo == "cooldown"


# --- Efeitos -----------------------------------------------------------------


def test_processar_notifica_e_persiste_na_mesma_passagem():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    repositorio = RepositorioFalso()
    notificador = NotificadorMemoria()

    processar(produto, [LeituraFalsa(preco_centavos=105_000)], AGORA, repositorio, notificador)

    assert len(notificador.mensagens) == 1
    assert repositorio.estados == [("p1", ESTADO_EM_ALERTA, 105_000, AGORA)]


def test_processar_em_cooldown_persiste_estado_sem_tocar_no_ultimo_alerta():
    produto = ProdutoFalso(
        estado=ESTADO_ACIMA,
        ultimo_alerta_em=AGORA - timedelta(hours=1),
        ultimo_preco_alertado_centavos=100_000,
    )
    repositorio = RepositorioFalso()
    notificador = NotificadorMemoria()

    processar(produto, [LeituraFalsa(preco_centavos=90_000)], AGORA, repositorio, notificador)

    assert notificador.mensagens == []
    assert repositorio.estados == [("p1", ESTADO_EM_ALERTA, None, None)]


def test_processar_silencio_sem_transicao_nao_escreve():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    repositorio = RepositorioFalso()
    notificador = NotificadorMemoria()

    processar(produto, [LeituraFalsa(preco_centavos=GATILHO + 1)], AGORA, repositorio, notificador)

    assert notificador.mensagens == []
    assert repositorio.estados == []


def test_nao_notifica_vinte_vezes_abaixo_do_alvo():
    """O cenário que o anti-padrão da seção 14 quer impedir."""
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    repositorio = RepositorioFalso()
    notificador = NotificadorMemoria()

    instante = AGORA
    for _ in range(20):
        processar(
            produto, [LeituraFalsa(preco_centavos=105_000)], instante, repositorio, notificador
        )
        # reflete o que o repositório teria gravado
        ultimo = repositorio.estados[-1] if repositorio.estados else None
        if ultimo:
            produto.estado = ultimo[1]
            if ultimo[3] is not None:
                produto.ultimo_alerta_em = ultimo[3]
                produto.ultimo_preco_alertado_centavos = ultimo[2]
        instante += timedelta(hours=1)

    assert len(notificador.mensagens) == 1


# --- Segundo gatilho: abaixo da média histórica ------------------------------


@pytest.mark.parametrize(
    "media, margem, esperado",
    [
        (200_000, 10, 180_000),   # 10% abaixo de 2.000,00
        (200_000, 0, 200_000),    # sem margem, o limite é a própria média
        (100_001, 10, 90_000),    # divisão inteira trunca
        (None, 10, None),         # sem histórico, sem gatilho
        (0, 10, None),
        (200_000, 100, None),     # margem inválida desliga o gatilho
        (200_000, -1, None),
    ],
)
def test_limite_pela_media(media, margem, esperado):
    assert limite_pela_media(media, margem) == esperado


def test_notifica_abaixo_da_media_mesmo_acima_do_alvo():
    """O preço não atingiu o alvo, mas está 10% abaixo da média histórica."""
    produto = ProdutoFalso(estado=ESTADO_ACIMA)   # gatilho = 110.000
    decisao = avaliar(
        produto, [LeituraFalsa(preco_centavos=170_000)], AGORA,
        media_historica_centavos=200_000,          # limite = 180.000
    )

    assert decisao.notificar is True
    assert decisao.motivo == "abaixo_da_media"
    assert decisao.gatilho_usado == "media"
    assert decisao.limite_da_media_centavos == 180_000


def test_nao_notifica_se_a_media_nao_justifica():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(
        produto, [LeituraFalsa(preco_centavos=190_000)], AGORA,
        media_historica_centavos=200_000,          # limite = 180.000
    )

    assert decisao.notificar is False
    assert decisao.motivo == "acima_do_gatilho"


def test_alvo_prevalece_quando_e_mais_generoso():
    """Se o alvo já é mais alto que o limite da média, o gatilho é o alvo."""
    produto = ProdutoFalso(estado=ESTADO_ACIMA)   # gatilho = 110.000
    decisao = avaliar(
        produto, [LeituraFalsa(preco_centavos=105_000)], AGORA,
        media_historica_centavos=100_000,          # limite = 90.000 < 110.000
    )

    assert decisao.notificar is True
    assert decisao.gatilho_usado == "alvo"
    assert decisao.motivo == "atingiu_alvo"


def test_sem_media_o_comportamento_e_o_de_antes():
    produto = ProdutoFalso(estado=ESTADO_ACIMA)
    decisao = avaliar(produto, [LeituraFalsa(preco_centavos=170_000)], AGORA)
    assert decisao.notificar is False
    assert decisao.gatilho_usado == "alvo"


def test_rearma_considerando_o_gatilho_da_media():
    """Rearmar exige subir acima do MAIOR dos dois gatilhos."""
    produto = ProdutoFalso(
        estado=ESTADO_EM_ALERTA, ultimo_preco_alertado_centavos=170_000
    )
    # 175.000 está acima do alvo (110.000) mas ainda abaixo do limite da média
    decisao = avaliar(
        produto, [LeituraFalsa(preco_centavos=175_000)], AGORA,
        media_historica_centavos=200_000,          # limite = 180.000
    )
    assert decisao.novo_estado == ESTADO_EM_ALERTA   # NÃO rearmou
    assert decisao.motivo == "sem_queda"

    # 185.000 passa dos dois
    decisao = avaliar(
        produto, [LeituraFalsa(preco_centavos=185_000)], AGORA,
        media_historica_centavos=200_000,
    )
    assert decisao.novo_estado == ESTADO_ACIMA
    assert decisao.motivo == "rearmou"


def test_mensagem_da_media_nao_mente_sobre_o_alvo():
    produto = ProdutoFalso()
    repositorio = RepositorioFalso(media=None, media_hist=200_000)
    notificador = NotificadorMemoria()

    processar(produto, [LeituraFalsa(preco_centavos=170_000)], AGORA,
              repositorio, notificador)

    (mensagem,) = notificador.mensagens
    assert "Abaixo da média histórica" in mensagem
    assert "Preço atingido" not in mensagem
    assert "(média: R$ 2.000,00)" in mensagem
    assert "alvo:" not in mensagem


def test_mensagem_do_maximo():
    produto = ProdutoFalso()
    repositorio = RepositorioFalso(media=None, media_hist=200_000)
    notificador = NotificadorMemoria()

    # 105.000 atinge o alvo (110.000) E está abaixo do limite da média
    processar(produto, [LeituraFalsa(preco_centavos=105_000)], AGORA,
              repositorio, notificador)

    (mensagem,) = notificador.mensagens
    assert "🔻 Preço atingido" in mensagem
    assert "(máx: R$ 1.100,00)" in mensagem


# --- Formatação --------------------------------------------------------------


@pytest.mark.parametrize(
    "centavos, esperado",
    [
        (129990, "1.299,90"),
        (999000, "9.990,00"),
        (5, "0,05"),
        (100, "1,00"),
        (123456789, "1.234.567,89"),
    ],
)
def test_formatar_reais(centavos, esperado):
    assert formatar_reais(centavos) == esperado


def test_mensagem_sem_historico_omite_a_media():
    produto = ProdutoFalso()
    leitura = LeituraFalsa(preco_centavos=105_000, loja="KaBuM")
    mensagem = montar_mensagem(produto, leitura, media_30_dias_centavos=None)

    assert "média de 30 dias" not in mensagem
    assert "Loja: KaBuM" in mensagem
    assert "R$ 1.050,00" in mensagem
    assert "(máx: R$ 1.100,00)" in mensagem
    assert leitura.url in mensagem


def test_mensagem_com_historico_mostra_a_variacao():
    produto = ProdutoFalso()
    leitura = LeituraFalsa(preco_centavos=105_000)
    mensagem = montar_mensagem(produto, leitura, media_30_dias_centavos=120_000)

    assert "-12% vs. média de 30 dias" in mensagem


def test_notificador_memoria_nao_toca_a_rede():
    notificador = NotificadorMemoria()
    notificador.enviar("oi")
    assert notificador.mensagens == ["oi"]
