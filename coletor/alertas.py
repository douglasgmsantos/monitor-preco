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

from coletor.lojas import condicao_de_pagamento_de

logger = logging.getLogger(__name__)

ESTADO_ACIMA = "ACIMA"
ESTADO_EM_ALERTA = "EM_ALERTA"

COOLDOWN_HORAS = 24
# Renotifica só se o preço caiu pelo menos 5% em relação ao último alertado.
# Escrito como preco * 100 <= ultimo * 95: aritmética inteira, sem float.
NUMERADOR_QUEDA = 95
DENOMINADOR_QUEDA = 100

# AVISA A CADA CICLO ENQUANTO O PREÇO ESTIVER DENTRO DA FAIXA.
#
# Ligado, ignora as DUAS travas que calam um produto já alertado: a regra dos
# 5% e o cooldown de 24h. Quem pediu sabe o custo — com ciclo de 30 minutos são
# até 48 mensagens por dia POR PRODUTO em faixa.
#
# Por que existiam as travas: um produto que ficou barato continua barato no
# ciclo seguinte, e no seguinte. Sem freio, a notificação deixa de ser "isto
# mudou" e vira um relógio — e um alerta que chega o tempo todo é um alerta que
# ninguém lê, que é a mesma coisa que não alertar.
#
# Desligar é trocar `ALERTA_REPETE_NO_RANGE` para `false` no workflow. Aí volta
# a valer: um alerta por oferta, repetido só se cair mais 5%.
REPETIR_NO_RANGE_PADRAO = True

# ...E PAUSA DEPOIS DE 3 MENSAGENS NO MESMO PREÇO.
#
# É o freio da repetição. Sem ele, um produto parado em R$ 4.899,99 por uma
# semana renderia ~340 mensagens idênticas — e a terceira já não informa nada
# que a primeira não tenha informado.
#
# A pausa é POR PREÇO, não por tempo: qualquer centavo de diferença zera a
# contagem e libera outras 3. Preço novo é informação nova; preço repetido não
# é. Sair da faixa (rearme) também zera — voltar a cair depois de subir é notícia.
#
# Este número é a única fonte da verdade: os testes o importam em vez de repetir
# o literal, então mudá-lo aqui muda o comportamento e as asserções juntos.
LIMITE_DE_REPETICOES = 3

DIAS_DA_MEDIA = 30

# Segundo gatilho: preço notavelmente abaixo da média histórica.
# A margem existe porque "abaixo da média" sem margem dispara em ~metade das
# leituras — preço oscila em torno da própria média por definição.
MARGEM_MEDIA_PCT_PADRAO = 10

GATILHO_ALVO = "alvo"
GATILHO_MEDIA = "media"

# Convite no rodapé de toda mensagem. Trocar de bot é trocar esta linha.
LINK_DO_GRUPO = "https://t.me/douglas_preco_bot"

# O GATILHO É O VALOR MÁXIMO, direto. Não existe fórmula.
#
# Antes havia `preco_alvo` + `tolerancia_pct`, e um `preco_gatilho` derivado que
# o cliente gravava e o coletor precisava recalcular e corrigir a cada ciclo —
# porque as rules aceitam qualquer inteiro e não dá para confiar no que o front
# escreveu. Com `valor_max_centavos` o gatilho é o próprio campo: nada a derivar,
# nada a corrigir, nada que possa divergir.
#
# `valor_min_centavos` NÃO participa da decisão. É referência do usuário — o
# preço que ele considera ideal — e existe para a tela mostrar o quanto falta.
# Fazer dele um piso do alerta significaria engolir a melhor oferta possível.


class Produto(Protocol):
    id: str
    nome: str
    valor_min_centavos: int
    valor_max_centavos: int
    estado: str
    ultimo_alerta_em: datetime | None
    ultimo_preco_alertado_centavos: int | None
    ativo: bool
    # Quantas mensagens já saíram com `ultimo_preco_alertado_centavos`.
    repeticoes_no_mesmo_preco: int


class Leitura(Protocol):
    """Uma leitura de uma fonte neste ciclo."""

    # Imagem do produto na página, quando o parser conseguiu extrair. Faz o
    # alerta sair como foto no Telegram em vez de texto com prévio de link.
    imagem: str | None

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
    # Quanto o contador vale DEPOIS desta decisão. Calculado aqui, na função
    # pura, para `processar` só persistir — a contagem é regra, não efeito.
    repeticoes_no_mesmo_preco: int = 0


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
    repetir_no_range: bool = REPETIR_NO_RANGE_PADRAO,
) -> Decisao:
    """Aplica a tabela de estados da seção 10.1, e só depois o cooldown.

    Há dois gatilhos independentes: o valor máximo do produto e o preço
    notavelmente abaixo da média histórica. Como a condição é
    `preco <= maximo OU preco <= limite_da_media`, o gatilho efetivo é o MAIOR
    dos dois — o que também deixa a regra de rearme correta de graça.

    Com `repetir_no_range`, tudo que existe para CALAR um produto que continua
    dentro da faixa é ignorado: a regra dos 5% e o cooldown. Ver a constante.
    """
    validas = leituras_validas(leituras)
    if not validas:
        return Decisao(False, produto.estado, "sem_leitura_valida")

    melhor = min(validas, key=lambda leitura: leitura.preco_centavos)
    preco = melhor.preco_centavos

    gatilho_alvo = produto.valor_max_centavos
    limite_media = limite_pela_media(media_historica_centavos, margem_media_pct)

    if limite_media is not None and limite_media > gatilho_alvo:
        gatilho, gatilho_usado = limite_media, GATILHO_MEDIA
    else:
        gatilho, gatilho_usado = gatilho_alvo, GATILHO_ALVO

    # Contador de repetições: quantas mensagens já saíram com ESTE preço.
    # Preço diferente do último alertado zera — inclusive um preço mais alto
    # dentro da faixa, que também é informação nova.
    ja_enviadas = (
        produto.repeticoes_no_mesmo_preco
        if preco == produto.ultimo_preco_alertado_centavos
        else 0
    )

    def resultado(notificar, estado, motivo):
        return Decisao(
            notificar, estado, motivo, preco, melhor,
            gatilho_usado, limite_media, media_historica_centavos,
            # Só uma notificação de verdade avança a contagem. Silêncio a
            # preserva: rearme e cooldown não gastam repetição.
            ja_enviadas + 1 if notificar else ja_enviadas,
        )

    if produto.estado == ESTADO_ACIMA:
        if preco <= gatilho:
            motivo = "atingiu_alvo" if gatilho_usado == GATILHO_ALVO else "abaixo_da_media"
            decisao = resultado(True, ESTADO_EM_ALERTA, motivo)
        else:
            return resultado(False, ESTADO_ACIMA, "acima_do_gatilho")
    else:  # EM_ALERTA
        if preco > gatilho:
            # Rearma em silêncio: o próximo mergulho volta a notificar. Zera a
            # contagem — sair da faixa e voltar é notícia, não repetição.
            return Decisao(
                False, ESTADO_ACIMA, "rearmou", preco, melhor,
                gatilho_usado, limite_media, media_historica_centavos, 0,
            )

        if repetir_no_range:
            # A PAUSA. Cinco mensagens no mesmo preço bastam; da sexta em
            # diante o produto cala até o preço mudar ou sair da faixa.
            if ja_enviadas >= LIMITE_DE_REPETICOES:
                return resultado(False, ESTADO_EM_ALERTA, "repeticoes_esgotadas")
            decisao = resultado(True, ESTADO_EM_ALERTA, "ainda_no_range")
        else:
            ultimo = produto.ultimo_preco_alertado_centavos
            caiu_o_bastante = (
                ultimo is not None
                and preco * DENOMINADOR_QUEDA <= ultimo * NUMERADOR_QUEDA
            )
            if caiu_o_bastante:
                decisao = resultado(True, ESTADO_EM_ALERTA, "queda_de_5pct")
            else:
                return resultado(False, ESTADO_EM_ALERTA, "sem_queda")

    # Cooldown global, verificado DEPOIS das regras acima — e sem efeito quando
    # a repetição está ligada, senão ele sozinho seguraria tudo por 24h.
    if not repetir_no_range and _em_cooldown(produto, agora):
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


def montar_mensagem(produto: Produto, leitura: Leitura) -> str:
    """A mensagem do alerta, no formato de canal de ofertas.

    Cinco blocos: produto, preço, link, e o convite. Sem título de "por que
    disparou" — o formato não afirma motivo, e é isso que o torna seguro: a
    versão anterior escrevia "(alvo: R$ X)" e precisava de uma variante para não
    mentir quando quem disparou foi a média.

    A CONDIÇÃO DE PAGAMENTO só aparece quando a loja de fato pratica aquele
    preço à vista. Ver `condicao_de_pagamento` em `coletor/lojas.py`: a Amazon
    fica sem, porque o preço que se lê dela é o normal.
    """
    preco = f"R$ {formatar_reais(leitura.preco_centavos)}"
    condicao = condicao_de_pagamento_de(leitura.url)
    linha_preco = f"✅ {preco} {condicao}".rstrip()

    return (
        f"🔥🙏🏻 {produto.nome}\n"
        "\n"
        f"{linha_preco}\n"
        "\n"
        f"Link -> : {leitura.url}\n"
        "\n"
        "Grupos Exclusivos 👍\n"
        f"{LINK_DO_GRUPO}"
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
        repeticoes_no_mesmo_preco: int = 0,
    ) -> None: ...

    def media_historica_centavos(self, produto: Produto) -> int | None: ...

    def registrar_notificacao(self, produto: Produto, dados: dict) -> None: ...


class Notificador(Protocol):
    def enviar(self, mensagem: str, imagem: str | None = None) -> None: ...


def processar(
    produto: Produto,
    leituras,
    agora: datetime,
    repositorio: RepositorioDeAlertas,
    notificador: Notificador,
    *,
    margem_media_pct: int = MARGEM_MEDIA_PCT_PADRAO,
    repetir_no_range: bool = REPETIR_NO_RANGE_PADRAO,
) -> Decisao:
    """Avalia e aplica: notifica e persiste o estado na mesma passagem."""
    media_historica = repositorio.media_historica_centavos(produto)
    decisao = avaliar(
        produto, leituras, agora,
        media_historica_centavos=media_historica,
        margem_media_pct=margem_media_pct,
        repetir_no_range=repetir_no_range,
    )

    if decisao.notificar:
        # A mensagem não mostra mais a média, então o `media_30_dias_centavos`
        # que rodava aqui sumiu junto — era uma varredura do rollup diário por
        # notificação enviada, para um número que ninguém lê.
        mensagem = montar_mensagem(produto, decisao.leitura)
        imagem = getattr(decisao.leitura, "imagem", None)

        # ENVIO FALHO NÃO CONTA COMO ALERTA.
        #
        # Marcar o estado depois de um envio que não chegou é o pior desfecho
        # possível: o produto entra em EM_ALERTA com `ultimoPrecoAlertado`
        # preenchido, e a regra dos 5% o cala INDEFINIDAMENTE — não por 24h,
        # mas até o preço cair mais 5% ou subir acima do máximo. O sistema fica
        # convencido de que avisou, e o usuário nunca recebeu nada.
        #
        # Não marcando, o próximo ciclo tenta de novo em 30 minutos. Uma queda
        # temporária do Telegram custa um atraso, não um alerta perdido.
        if not notificador.enviar(mensagem, imagem):
            logger.error(
                "alerta de %s NÃO foi entregue; estado preservado para nova "
                "tentativa no próximo ciclo", produto.nome,
            )
            return Decisao(
                False, produto.estado, "falha_no_envio",
                decisao.preco_centavos, decisao.leitura,
                decisao.gatilho_usado, decisao.limite_da_media_centavos,
                decisao.media_historica_centavos,
            )

        repositorio.atualizar_estado_alerta(
            produto, decisao.novo_estado, decisao.preco_centavos, agora,
            decisao.repeticoes_no_mesmo_preco,
        )
        # O diário guarda a MENSAGEM como saiu. Ver `registrar_notificacao`.
        repositorio.registrar_notificacao(produto, {
            "produtoId": produto.id,
            "nome": produto.nome,
            "precoCentavos": decisao.preco_centavos,
            "loja": decisao.leitura.loja,
            "url": decisao.leitura.url,
            "imagem": imagem,
            "mensagem": mensagem,
            "motivo": decisao.motivo,
            "enviadaEm": agora,
        })
    elif decisao.novo_estado != produto.estado:
        # Transição silenciosa (rearme ou cooldown): não mexe em
        # ultimo_alerta_em nem em ultimo_preco_alertado. O contador vai junto
        # porque o rearme precisa zerá-lo — é a transição que o libera.
        repositorio.atualizar_estado_alerta(
            produto, decisao.novo_estado, None, None,
            decisao.repeticoes_no_mesmo_preco,
        )

    return decisao
