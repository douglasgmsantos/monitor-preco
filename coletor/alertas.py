"""Máquina de estados do alerta.

A decisão é uma função pura (`avaliar`): recebe o produto, as leituras do
ciclo e o instante, devolve o que fazer. Os efeitos ficam em `processar`.
Essa separação é o que permite testar a tabela de estados inteira sem rede,
sem Firestore e sem relógio de verdade.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

logger = logging.getLogger(__name__)

ESTADO_ACIMA = "ACIMA"
ESTADO_EM_ALERTA = "EM_ALERTA"

COOLDOWN_HORAS = 24
# Renotifica só se o preço caiu pelo menos 5% em relação ao último alertado.
# Escrito como preco * 100 <= ultimo * 95: aritmética inteira, sem float.
NUMERADOR_QUEDA = 95
DENOMINADOR_QUEDA = 100

DIAS_DA_MEDIA = 30


def calcular_gatilho(preco_alvo_centavos: int, tolerancia_pct: int) -> int:
    """Preço a partir do qual o alerta dispara.

    Único lugar do projeto onde esta fórmula existe. Multiplicação antes da
    divisão e divisão inteira: nenhum float encosta no valor.
    """
    return (preco_alvo_centavos * (100 + tolerancia_pct)) // 100


class Produto(Protocol):
    id: str
    nome: str
    preco_alvo_centavos: int
    tolerancia_pct: int
    preco_gatilho_centavos: int
    estado: str
    ultimo_alerta_em: datetime | None
    ultimo_preco_alertado_centavos: int | None
    ativo: bool


class Leitura(Protocol):
    """Uma leitura de uma fonte neste ciclo."""

    loja: str
    url: str
    preco_centavos: int | None
    disponivel: bool
    suspeito: bool


@dataclass(frozen=True)
class Decisao:
    notificar: bool
    novo_estado: str
    motivo: str
    preco_centavos: int | None = None
    leitura: Leitura | None = None


def leituras_validas(leituras) -> list:
    """Descarta o que a tabela manda silenciar: sem preço, indisponível, suspeito."""
    return [
        leitura
        for leitura in leituras
        if leitura.preco_centavos is not None
        and leitura.disponivel
        and not leitura.suspeito
    ]


def avaliar(produto: Produto, leituras, agora: datetime) -> Decisao:
    """Aplica a tabela de estados da seção 10.1, e só depois o cooldown."""
    validas = leituras_validas(leituras)
    if not validas:
        return Decisao(False, produto.estado, "sem_leitura_valida")

    melhor = min(validas, key=lambda leitura: leitura.preco_centavos)
    preco = melhor.preco_centavos
    gatilho = produto.preco_gatilho_centavos

    if produto.estado == ESTADO_ACIMA:
        if preco <= gatilho:
            decisao = Decisao(True, ESTADO_EM_ALERTA, "atingiu_alvo", preco, melhor)
        else:
            return Decisao(False, ESTADO_ACIMA, "acima_do_gatilho", preco, melhor)
    else:  # EM_ALERTA
        if preco > gatilho:
            # Rearma em silêncio: o próximo mergulho volta a notificar.
            return Decisao(False, ESTADO_ACIMA, "rearmou", preco, melhor)

        ultimo = produto.ultimo_preco_alertado_centavos
        caiu_o_bastante = (
            ultimo is not None
            and preco * DENOMINADOR_QUEDA <= ultimo * NUMERADOR_QUEDA
        )
        if caiu_o_bastante:
            decisao = Decisao(True, ESTADO_EM_ALERTA, "queda_de_5pct", preco, melhor)
        else:
            return Decisao(False, ESTADO_EM_ALERTA, "sem_queda", preco, melhor)

    # Cooldown global, verificado DEPOIS das regras acima.
    if _em_cooldown(produto, agora):
        # DECISÃO (ambiguidade da spec): o cooldown cala a mensagem, mas o
        # estado avança. Se o estado não avançasse, o produto tentaria
        # notificar a cada ciclo e dispararia sozinho no instante em que o
        # cooldown expirasse, mesmo sem novidade no preço.
        # `ultimo_preco_alertado` NÃO é atualizado: ele registra o último
        # preço efetivamente comunicado, e a regra dos 5% depende disso.
        return Decisao(False, decisao.novo_estado, "cooldown", preco, melhor)

    return decisao


def _em_cooldown(produto: Produto, agora: datetime) -> bool:
    if produto.ultimo_alerta_em is None:
        return False
    return agora - produto.ultimo_alerta_em < timedelta(hours=COOLDOWN_HORAS)


# ----------------------------------------------------------------------------
# Formatação da mensagem
# ----------------------------------------------------------------------------


def formatar_reais(centavos: int) -> str:
    """Centavos -> "1.789,99". Só divmod, nunca float."""
    sinal = "-" if centavos < 0 else ""
    inteiros, resto = divmod(abs(centavos), 100)
    return f"{sinal}{inteiros:,}".replace(",", ".") + f",{resto:02d}"


def _variacao_vs_media(preco_centavos: int, media_centavos: int | None) -> str | None:
    """Ex.: "-12%". Devolve None quando não há 30 dias de histórico.

    Trunca em direção ao zero, e não para baixo como o `//` faria: -12,5% vira
    -12%, não -13%. A mensagem nunca deve fazer o desconto parecer maior do que
    é — errar para o lado conservador é a única opção defensável aqui.
    """
    if not media_centavos:
        return None
    diferenca = (preco_centavos - media_centavos) * 100
    variacao = abs(diferenca) // media_centavos
    if diferenca < 0:
        variacao = -variacao
    return f"{variacao:+d}%"


def montar_mensagem(
    produto: Produto, leitura: Leitura, media_30_dias_centavos: int | None = None
) -> str:
    """Mensagem do alerta. Sem 30 dias de histórico, o trecho da média some."""
    preco = leitura.preco_centavos
    linha_loja = f"Loja: {leitura.loja}"
    variacao = _variacao_vs_media(preco, media_30_dias_centavos)
    if variacao is not None:
        linha_loja += f"  ·  {variacao} vs. média de 30 dias"

    return (
        "🔻 Preço atingido\n"
        "\n"
        f"{produto.nome}\n"
        f"R$ {formatar_reais(preco)}  "
        f"(alvo: R$ {formatar_reais(produto.preco_alvo_centavos)})\n"
        f"{linha_loja}\n"
        "\n"
        f"{leitura.url}"
    )


# ----------------------------------------------------------------------------
# Efeitos
# ----------------------------------------------------------------------------


class RepositorioDeAlertas(Protocol):
    def atualizar_estado_alerta(
        self,
        produto: Produto,
        estado: str,
        preco_centavos: int | None,
        alertado_em: datetime | None,
    ) -> None: ...

    def media_30_dias_centavos(self, produto: Produto) -> int | None: ...


class Notificador(Protocol):
    def enviar(self, mensagem: str) -> None: ...


def processar(
    produto: Produto,
    leituras,
    agora: datetime,
    repositorio: RepositorioDeAlertas,
    notificador: Notificador,
) -> Decisao:
    """Avalia e aplica: notifica e persiste o estado na mesma passagem."""
    decisao = avaliar(produto, leituras, agora)

    if decisao.notificar:
        media = repositorio.media_30_dias_centavos(produto)
        notificador.enviar(montar_mensagem(produto, decisao.leitura, media))
        repositorio.atualizar_estado_alerta(
            produto, decisao.novo_estado, decisao.preco_centavos, agora
        )
    elif decisao.novo_estado != produto.estado:
        # Transição silenciosa (rearme ou cooldown): não mexe em
        # ultimo_alerta_em nem em ultimo_preco_alertado.
        repositorio.atualizar_estado_alerta(produto, decisao.novo_estado, None, None)

    return decisao
