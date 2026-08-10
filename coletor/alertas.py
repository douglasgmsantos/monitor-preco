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

# Segundo gatilho: preço notavelmente abaixo da média histórica.
# A margem existe porque "abaixo da média" sem margem dispara em ~metade das
# leituras — preço oscila em torno da própria média por definição.
MARGEM_MEDIA_PCT_PADRAO = 10

GATILHO_ALVO = "alvo"
GATILHO_MEDIA = "media"


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
    gatilho_usado: str = GATILHO_ALVO
    limite_da_media_centavos: int | None = None
    media_historica_centavos: int | None = None


def limite_pela_media(
    media_centavos: int | None, margem_pct: int = MARGEM_MEDIA_PCT_PADRAO
) -> int | None:
    """Preço a partir do qual a média histórica justifica alerta.

    Aritmética inteira: `media * (100 - margem) // 100`. Sem média suficiente,
    devolve None e o gatilho da média simplesmente não existe.
    """
    if not media_centavos or media_centavos <= 0:
        return None
    if margem_pct < 0 or margem_pct >= 100:
        logger.warning("MARGEM_MEDIA_PCT fora de 0..99: %r — gatilho desligado", margem_pct)
        return None
    return media_centavos * (100 - margem_pct) // 100


def leituras_validas(leituras) -> list:
    """Descarta o que a tabela manda silenciar: sem preço, indisponível, suspeito."""
    return [
        leitura
        for leitura in leituras
        if leitura.preco_centavos is not None
        and leitura.disponivel
        and not leitura.suspeito
    ]


def avaliar(
    produto: Produto,
    leituras,
    agora: datetime,
    *,
    media_historica_centavos: int | None = None,
    margem_media_pct: int = MARGEM_MEDIA_PCT_PADRAO,
) -> Decisao:
    """Aplica a tabela de estados da seção 10.1, e só depois o cooldown.

    Há dois gatilhos independentes: o preço-alvo com tolerância, e o preço
    notavelmente abaixo da média histórica. Como a condição é
    `preco <= alvo OU preco <= limite_da_media`, o gatilho efetivo é o MAIOR
    dos dois — o que também deixa a regra de rearme correta de graça.
    """
    validas = leituras_validas(leituras)
    if not validas:
        return Decisao(False, produto.estado, "sem_leitura_valida")

    melhor = min(validas, key=lambda leitura: leitura.preco_centavos)
    preco = melhor.preco_centavos

    gatilho_alvo = produto.preco_gatilho_centavos
    limite_media = limite_pela_media(media_historica_centavos, margem_media_pct)

    if limite_media is not None and limite_media > gatilho_alvo:
        gatilho, gatilho_usado = limite_media, GATILHO_MEDIA
    else:
        gatilho, gatilho_usado = gatilho_alvo, GATILHO_ALVO

    def resultado(notificar, estado, motivo):
        return Decisao(
            notificar, estado, motivo, preco, melhor,
            gatilho_usado, limite_media, media_historica_centavos,
        )

    if produto.estado == ESTADO_ACIMA:
        if preco <= gatilho:
            motivo = "atingiu_alvo" if gatilho_usado == GATILHO_ALVO else "abaixo_da_media"
            decisao = resultado(True, ESTADO_EM_ALERTA, motivo)
        else:
            return resultado(False, ESTADO_ACIMA, "acima_do_gatilho")
    else:  # EM_ALERTA
        if preco > gatilho:
            # Rearma em silêncio: o próximo mergulho volta a notificar.
            return resultado(False, ESTADO_ACIMA, "rearmou")

        ultimo = produto.ultimo_preco_alertado_centavos
        caiu_o_bastante = (
            ultimo is not None
            and preco * DENOMINADOR_QUEDA <= ultimo * NUMERADOR_QUEDA
        )
        if caiu_o_bastante:
            decisao = resultado(True, ESTADO_EM_ALERTA, "queda_de_5pct")
        else:
            return resultado(False, ESTADO_EM_ALERTA, "sem_queda")

    # Cooldown global, verificado DEPOIS das regras acima.
    if _em_cooldown(produto, agora):
        # DECISÃO (ambiguidade da spec): o cooldown cala a mensagem, mas o
        # estado avança. Se o estado não avançasse, o produto tentaria
        # notificar a cada ciclo e dispararia sozinho no instante em que o
        # cooldown expirasse, mesmo sem novidade no preço.
        # `ultimo_preco_alertado` NÃO é atualizado: ele registra o último
        # preço efetivamente comunicado, e a regra dos 5% depende disso.
        return resultado(False, decisao.novo_estado, "cooldown")

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
    produto: Produto,
    leitura: Leitura,
    media_30_dias_centavos: int | None = None,
    *,
    decisao: "Decisao | None" = None,
) -> str:
    """Mensagem do alerta. Sem 30 dias de histórico, o trecho da média some.

    O título e a segunda linha mudam conforme o gatilho: dizer "preço atingido"
    quando o alvo não foi atingido — e só a média justificou o alerta — seria
    mentir para o usuário.
    """
    preco = leitura.preco_centavos
    linha_loja = f"Loja: {leitura.loja}"
    variacao = _variacao_vs_media(preco, media_30_dias_centavos)
    if variacao is not None:
        linha_loja += f"  ·  {variacao} vs. média de 30 dias"

    pela_media = (
        decisao is not None
        and decisao.gatilho_usado == GATILHO_MEDIA
        and preco > produto.preco_gatilho_centavos
    )
    if pela_media:
        titulo = "📉 Abaixo da média histórica"
        referencia = f"(média: R$ {formatar_reais(decisao.media_historica_centavos)})"
    else:
        titulo = "🔻 Preço atingido"
        referencia = f"(alvo: R$ {formatar_reais(produto.preco_alvo_centavos)})"

    return (
        f"{titulo}\n"
        "\n"
        f"{produto.nome}\n"
        f"R$ {formatar_reais(preco)}  {referencia}\n"
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

    def media_historica_centavos(self, produto: Produto) -> int | None: ...


class Notificador(Protocol):
    def enviar(self, mensagem: str) -> None: ...


def processar(
    produto: Produto,
    leituras,
    agora: datetime,
    repositorio: RepositorioDeAlertas,
    notificador: Notificador,
    *,
    margem_media_pct: int = MARGEM_MEDIA_PCT_PADRAO,
) -> Decisao:
    """Avalia e aplica: notifica e persiste o estado na mesma passagem."""
    media_historica = repositorio.media_historica_centavos(produto)
    decisao = avaliar(
        produto, leituras, agora,
        media_historica_centavos=media_historica,
        margem_media_pct=margem_media_pct,
    )

    if decisao.notificar:
        media = repositorio.media_30_dias_centavos(produto)
        notificador.enviar(
            montar_mensagem(produto, decisao.leitura, media, decisao=decisao)
        )
        repositorio.atualizar_estado_alerta(
            produto, decisao.novo_estado, decisao.preco_centavos, agora
        )
    elif decisao.novo_estado != produto.estado:
        # Transição silenciosa (rearme ou cooldown): não mexe em
        # ultimo_alerta_em nem em ultimo_preco_alertado.
        repositorio.atualizar_estado_alerta(produto, decisao.novo_estado, None, None)

    return decisao
