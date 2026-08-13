"""Registro das lojas suportadas na PÁGINA DE PRODUTO.

Fonte única de verdade para três perguntas que antes estavam espalhadas:

    1. que lojas o cadastro aceita?
    2. como buscar a página de cada uma?
    3. como extrair o preço dela?

O espelho desta tabela no front é `frontend/src/lojas.js`. As duas listas
precisam concordar: o front recusa a URL antes de gravar, o coletor recusa
depois de buscar. Mudou aqui, muda lá.

NÃO CONFUNDIR com `raspagem.LOJAS`, que é outra coisa: aquela tabela é sobre
páginas de LISTAGEM (categoria), para montar o catálogo. Esta é sobre a página
de um produto, para medir preço. A mesma loja pode estar em uma e não na outra.

DUAS ESTRATÉGIAS DE EXTRAÇÃO
----------------------------
`jsonld`  a loja publica `application/ld+json` com Product + Offer. Contrato
          schema.org: estável, versionado, e a loja tem interesse próprio em
          manter (é o que alimenta o Google Shopping). É o caminho preferido, e
          três das quatro lojas usam.

`dom`     seletores de CSS na marra. Só quando não há JSON-LD, porque depende do
          layout e quebra sem aviso. Hoje: apenas Amazon.

DE ONDE VEM O HTML (campo `busca`)
----------------------------------
Medido em produção, 2026-08-13. O runner do GitHub é IP de datacenter e leva 403
de três das quatro lojas; as MESMAS URLs respondem de rede residencial. Daí o
caminho `capturada`, em que um n8n busca e grava em `paginas/{fonteId}`:

    KaBuM      direta      única que o runner alcança. Fica direta de propósito:
                           depender do n8n para ela seria trocar o que funciona
    Terabyte   capturada   403 no runner; pelo n8n leu R$ 3.399,99 e R$ 1.349,99
    Amazon     capturada   pelo n8n leu R$ 3.798,83 (origem d)
    Pichau     capturada   NÃO FUNCIONA NEM ASSIM — ver a observação dela

Ver `coletor/captura.py` e o README, seção "HTML capturado por fora (n8n)".
"""

import logging
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from coletor.parser import (
    ERRO_BLOQUEIO, TETO_CENTAVOS, ResultadoExtracao, SeletoresDeProduto,
    extrair_preco, extrair_preco_do_estado, extrair_preco_dom,
    parece_pagina_de_bloqueio,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cabeçalhos
# ---------------------------------------------------------------------------
#
# O projeto se identifica com User-Agent honesto (`MonitorPrecos/1.0`) e essa é
# a posição padrão. A Amazon é a exceção, e é uma exceção MEDIDA, não uma
# conveniência: com o UA honesto ela responde 200 com 221 KB e nenhuma marcação
# de produto — sem título, sem preço, sem botão. Não existe versão "honesta" da
# página para ler. A escolha real é buscar como navegador ou não suportar a
# loja.
#
# Registrado explicitamente para que a próxima pessoa saiba que isto foi uma
# decisão, não descuido.

CABECALHOS_DE_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


# ---------------------------------------------------------------------------
# Seletores por loja
# ---------------------------------------------------------------------------

# Verificados contra `coletor/templates/amazon-produto-detalhes.html` E contra
# uma busca ao vivo em 2026-08-12: os dois casaram valor por valor.
#
# O escopo em `#corePrice_feature_div` é o detalhe que importa. Um
# `span.a-offscreen` solto casa 22 nós na página, e o segundo deles é
# R$ 7.499,00 — outro preço, de outro bloco. Sem o escopo, o coletor gravaria
# um número plausível e errado, que é a pior espécie de bug.
SELETORES_AMAZON = SeletoresDeProduto(
    # Em ordem de confiança. A Amazon varia o bloco de preço por layout de
    # página, e um produto com preço sempre casa um destes. O ESCOPO é o que
    # importa em todos: `span.a-offscreen` solto casa 22 nós na página, sendo o
    # segundo um preço de outro bloco.
    preco=(
        "#corePrice_feature_div span.a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-offscreen",
        "#price_inside_buybox",
        "span.priceToPay span.a-offscreen",
        "#apex_offerDisplay_desktop span.a-offscreen",
    ),
    prova_de_produto="#productTitle",
    # `#unqualifiedBuyBox` é como a Amazon diz "este produto existe e ninguém
    # está vendendo". Verificado em 2026-08-12 numa URL real do usuário: página
    # completa de 1,1 MB, título presente, ZERO bloco de preço, e este marcador.
    # Sem ele, esse estado virava `sem_preco_no_dom` — erro de parse — e a fonte
    # era condenada como se a URL estivesse errada.
    marcador_sem_oferta="#unqualifiedBuyBox",
    preco_tabela=".basisPrice .a-offscreen",
    disponibilidade="#availability",
    botao_de_compra="#add-to-cart-button",
)

# ---------------------------------------------------------------------------
# Preço à vista: qual número o monitor deve seguir
# ---------------------------------------------------------------------------
#
# Medido em 2026-08-12, no mesmo produto (ASRock RX 9070 XT) nas quatro lojas:
#
#   KaBuM      JSON-LD 5.199,99  =  "À vista no PIX com 15% de desconto"   ✅
#   Terabyte   JSON-LD 4.599,90  =  "à vista com 15% de desconto no pix"   ✅
#   Pichau     JSON-LD 5.529,40  =  `final_price` (parcelado). O à vista é
#                                   4.699,99, e mora SÓ no estado embutido    ❌
#   Amazon     DOM     5.830,53  =  preço normal. Há "5% off à vista no Pix",
#                                   mas como BADGE de percentual — a loja não
#                                   publica o valor absoluto em lugar nenhum    ❌
#
# Duas de três já entregam o preço com desconto no JSON-LD, então o alvo do
# sistema é o PREÇO À VISTA: é o que se paga de fato, e é o que a maioria das
# lojas já reporta. A Pichau ganha o ajuste abaixo para entrar nessa régua.
#
# A Amazon fica 5% acima da própria régua, e isso é DESVIO CONHECIDO E LIMITADO,
# não bug: não existe número para ler. Consequência prática: numa disputa
# apertada entre Amazon e outra loja, a Amazon parece até 5% mais cara do que é.
#
# POR QUE FALHAR EM VEZ DE CAIR PARA O JSON-LD: se a chave `avista` sumir, usar o
# preço do JSON-LD da Pichau significaria gravar um número ~18% mais alto na
# série histórica, para sempre e em silêncio. No caso deste repositório isso já
# tem consequência medida: com gatilho em R$ 4.700,00, o à vista de R$ 4.699,99
# dispara alerta e o parcelado de R$ 5.529,40 não dispara nunca. Preferimos a
# fonte falhar alto — `sem_preco_avista` está em ERROS_DE_PARSE.

# Uma captura só, e os três valores do bloco conferidos:
#   {"avista":4699.99,"avista_discount":15,"avista_method":"PIX",
#    "base_price":7058.81,"final_price":5529.4,...}
# O estado vem escapado (`\"avista\":`), daí o `\\?` antes de cada aspa.
PADRAO_AVISTA_PICHAU = r'\\?"avista\\?"\s*:\s*([0-9]+\.?[0-9]*)'


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Loja:
    nome: str
    dominios: tuple[str, ...]
    estrategia: str                      # "jsonld" | "dom"
    # De onde vem o HTML:
    #   "direta"     o coletor busca por HTTP. É o padrão, e continua sendo o
    #                caminho de quem já funciona — trocar KaBuM por um n8n que
    #                pode estar fora do ar seria piorar o que está de pé.
    #   "capturada"  outro processo (n8n com navegador) buscou e gravou em
    #                `paginas/{fonteId}`. Ver `coletor/captura.py`.
    busca: str = "direta"
    seletores: SeletoresDeProduto | None = None
    # Só têm efeito quando busca="direta" — quem busca no caminho capturado é o
    # n8n, e nada desta tabela chega até ele. Ficam registrados mesmo assim:
    # são o que se sabe sobre como a loja precisa ser buscada, valem se ela
    # voltar para "direta", e o nó do n8n usa exatamente estes mesmos valores.
    cabecalhos: dict[str, str] = field(default_factory=dict)
    # Regex de um grupo que captura o preço à vista no estado embutido. Quando
    # presente, VENCE o preço da estratégia — e a ausência dele na página é erro,
    # não motivo para cair no número errado. Ver o bloco acima.
    padrao_preco_avista: str | None = None
    # Anotação honesta do que se sabe sobre buscar esta loja de fora. Aparece no
    # log quando a coleta falha, para o motivo não virar adivinhação.
    observacao: str = ""

    def __post_init__(self) -> None:
        if self.estrategia == "dom" and self.seletores is None:
            raise ValueError(f"{self.nome}: estratégia dom exige seletores")
        if self.busca not in ("direta", "capturada"):
            raise ValueError(f"{self.nome}: busca inválida ({self.busca!r})")


LOJAS: tuple[Loja, ...] = (
    Loja(
        nome="KaBuM",
        dominios=("kabum.com.br",),
        estrategia="jsonld",
        # Fica em "direta" de propósito: é a única que responde ao runner, e
        # fazê-la depender do n8n seria trocar o que funciona pelo que talvez.
        observacao="em produção desde o início; único caso confirmado no runner",
    ),
    Loja(
        nome="Terabyte Shop",
        dominios=("terabyteshop.com.br",),
        estrategia="jsonld",
        busca="capturada",
        observacao=(
            "JSON-LD verificado. O runner toma http_403; pelo n8n, de rede "
            "residencial, leu R$ 3.399,99 e R$ 1.349,99 em 2026-08-13"
        ),
    ),
    Loja(
        nome="Pichau",
        dominios=("pichau.com.br",),
        estrategia="jsonld",
        busca="capturada",
        # O JSON-LD dela dá o parcelado; o preço que interessa vem do estado.
        padrao_preco_avista=PADRAO_AVISTA_PICHAU,
        observacao=(
            "PROBLEMÁTICA. Única loja cujo JSON-LD não é o preço à vista (traz o "
            "final_price; o à vista mora no estado embutido). E bloqueia de "
            "TODO lugar: 403 do runner, e pelo n8n de rede residencial devolve "
            "HTTP 200 com 'Site em Manutenção' e zero preço (2026-08-13). Ligada "
            "em 'capturada' a pedido; enquanto ela recusar, acumula "
            "pagina_de_bloqueio — que é transporte e não condena a fonte"
        ),
    ),
    Loja(
        nome="Amazon",
        dominios=("amazon.com.br",),
        estrategia="dom",
        busca="capturada",
        seletores=SELETORES_AMAZON,
        cabecalhos=CABECALHOS_DE_NAVEGADOR,
        observacao=(
            "sem JSON-LD; DOM verificado no template, ao vivo e por captura "
            "(R$ 3.798,83 em 2026-08-13). EXIGE cabeçalhos de navegador — com UA "
            "honesto a página vem sem marcação de produto — e o nó do n8n manda "
            "exatamente os mesmos"
        ),
    ),
)


def busca_de(url: str) -> str:
    """Como o HTML desta URL chega: "direta" (HTTP no coletor) ou "capturada".

    Loja fora do registro busca direto — é o comportamento que sempre existiu, e
    fonte antiga não pode parar de ser coletada por causa de uma tabela nova.
    """
    loja = loja_de(url)
    return loja.busca if loja is not None else "direta"


def loja_de(url_ou_host: str) -> Loja | None:
    """Loja suportada para uma URL (ou host), ou None se não é suportada."""
    host = _host(url_ou_host)
    if not host:
        return None
    for loja in LOJAS:
        if any(host == d or host.endswith("." + d) for d in loja.dominios):
            return loja
    return None


def _host(url_ou_host: str) -> str:
    bruto = (url_ou_host or "").strip().lower()
    if not bruto:
        return ""
    if "//" in bruto:
        bruto = urlsplit(bruto).netloc
    return bruto.split("@")[-1].split(":")[0].removeprefix("www.")


def extrair_da_loja(
    url: str, html: str, *, teto_centavos: int = TETO_CENTAVOS
) -> ResultadoExtracao:
    """Extrai o preço com a estratégia registrada para a loja da URL.

    Loja fora do registro cai no caminho JSON-LD. Isso é rede de segurança para
    fonte antiga: o cadastro só oferece lojas do registro, mas fontes gravadas
    antes desta tabela existir continuam no banco, e recusá-las aqui apagaria
    histórico de gente que não fez nada de errado.
    """
    loja = loja_de(url)

    # Bloqueio primeiro, e para QUALQUER estratégia. `extrair_preco_dom` já
    # checava, mas o caminho JSON-LD não — e é justamente o Terabyte que serve
    # "Just a moment..." do Cloudflare. Sem esta linha, esse desafio viraria
    # `sem_jsonld`, que é erro de PARSE e condena a fonte em 5 ciclos por um
    # problema de TRANSPORTE.
    if parece_pagina_de_bloqueio(html):
        return ResultadoExtracao(None, None, False, None, ERRO_BLOQUEIO)

    if loja is not None and loja.estrategia == "dom":
        resultado = extrair_preco_dom(
            html, loja.seletores, teto_centavos=teto_centavos
        )
    else:
        resultado = extrair_preco(html, teto_centavos=teto_centavos)

    if loja is not None and loja.padrao_preco_avista:
        resultado = _com_preco_avista(resultado, html, loja, teto_centavos)
    return resultado


def _com_preco_avista(
    resultado: ResultadoExtracao, html: str, loja: Loja, teto_centavos: int
) -> ResultadoExtracao:
    """Troca o preço pelo à vista da loja, ou falha alto se ele não estiver lá.

    A ordem importa: um erro que já existia (bloqueio, página ilegível) passa
    intacto. Não faz sentido reclamar de "sem preço à vista" numa página que o
    servidor nem entregou.
    """
    if resultado.erro is not None:
        return resultado

    centavos = extrair_preco_do_estado(
        html, loja.padrao_preco_avista, teto_centavos=teto_centavos
    )
    if centavos is None:
        logger.warning(
            "%s: preço à vista não encontrado no estado da página. O preço da "
            "estratégia %s (%s centavos) NÃO será usado, porque nesta loja ele é "
            "o parcelado — gravá-lo contaminaria a série histórica.",
            loja.nome, loja.estrategia, resultado.preco_centavos,
        )
        return ResultadoExtracao(
            None, None, resultado.disponivel, None, "sem_preco_avista"
        )

    return ResultadoExtracao(
        preco_centavos=centavos,
        moeda=resultado.moeda or "BRL",
        # Disponibilidade continua vindo da estratégia: o JSON-LD da Pichau é
        # confiável nisso, e o estado não é mais claro a respeito.
        disponivel=resultado.disponivel,
        origem="e",
        erro=None,
    )


def cabecalhos_de(url: str, user_agent_padrao: str) -> dict[str, str]:
    """Cabeçalhos para buscar esta URL.

    O padrão é o User-Agent honesto configurado. Só quem está no registro com
    cabeçalhos próprios recebe outro tratamento — e hoje é só a Amazon.
    """
    loja = loja_de(url)
    if loja is not None and loja.cabecalhos:
        return dict(loja.cabecalhos)
    return {"User-Agent": user_agent_padrao}
