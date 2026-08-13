"""HTML capturado por fora, entregue pelo Firestore.

POR QUE ISTO EXISTE
-------------------
O coletor roda no GitHub Actions, de IP de datacenter (Azure), e sem navegador.
Isso derruba duas classes de loja:

  bloqueio    a Pichau devolve 403; a Amazon serve página sem produto quando o
              User-Agent não é de navegador
  JavaScript  Mercado Livre e Shopee entregam um shell sem preço nenhum; medido,
              38 KB e 152 KB com ZERO ocorrências de "R$"

Um n8n rodando com navegador, de uma rede residencial, resolve as duas — ele tem
o IP e tem o motor de render. O que falta é o caminho entre ele e o coletor, e é
esse caminho que este módulo define.

O FORMATO, E POR QUE gzip+base64
--------------------------------
Documento do Firestore tem teto de 1 MiB e a Amazon são 1,2 MB de HTML: **não
cabe cru**. Comprimido cabe com folga — medido em 2026-08-12 nos cinco templates:

    Amazon        1.209 KB  ->  358 KB   (o único que não caberia cru)
    Mercado Livre   977 KB  ->  365 KB
    Shopee          925 KB  ->  255 KB
    Pichau          402 KB  ->   83 KB
    Terabyte        298 KB  ->   53 KB

O documento é uma CAIXA DE CORREIO, não um acervo: o id é o da fonte, então cada
captura sobrescreve a anterior e o total fica em ~7 documentos para sempre. Não
há limpeza a fazer, e é de propósito — rotina de limpeza é mais uma coisa que
pode falhar em silêncio.

A ARMADILHA QUE ESTE MÓDULO EXISTE PARA EVITAR
----------------------------------------------
Se o n8n parar, o documento continua lá. Sem checagem de idade, o coletor leria a
mesma página velha a cada ciclo e gravaria o mesmo preço como se fosse leitura
nova — série histórica inventada, alerta que nunca dispara, e nada no log. Daí
`ERRO_CAPTURA_VENCIDA`, e daí ele ser erro de TRANSPORTE: a URL está boa, quem
parou foi o mensageiro.
"""

import base64
import binascii
import gzip
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Fora de ERROS_DE_PARSE (ver parser.py): nenhum destes diz que a PÁGINA é
# ilegível, então nenhum pode condenar a fonte.
ERRO_SEM_CAPTURA = "sem_captura"
ERRO_CAPTURA_VENCIDA = "captura_vencida"
ERRO_CAPTURA_ILEGIVEL = "captura_ilegivel"
ERRO_CAPTURA_DE_OUTRA_URL = "captura_de_outra_url"
ERRO_CAPTURA_ESCAPADA = "captura_escapada"

ERROS_DE_CAPTURA = frozenset(
    {ERRO_SEM_CAPTURA, ERRO_CAPTURA_VENCIDA, ERRO_CAPTURA_ILEGIVEL,
     ERRO_CAPTURA_DE_OUTRA_URL, ERRO_CAPTURA_ESCAPADA}
)

# Quanto tempo uma captura vale. O padrão é o dobro do intervalo de coleta (3h),
# o que tolera UMA execução perdida do n8n sem tolerar página de ontem.
HORAS_DE_VALIDADE_PADRAO = 6

CODIFICACAO_PADRAO = "gzip+base64"


@dataclass(frozen=True)
class Captura:
    html: str
    capturado_em: datetime
    url: str | None = None
    bytes_brutos: int | None = None


def compactar(html: str) -> str:
    """HTML -> gzip -> base64. É o que o n8n precisa produzir."""
    return base64.b64encode(gzip.compress(html.encode("utf-8"), 6)).decode("ascii")


def descompactar(conteudo: str, codificacao: str = CODIFICACAO_PADRAO) -> str | None:
    """Desfaz `compactar`, ou None se o conteúdo não for o que diz ser.

    `codificacao="texto"` aceita HTML cru, para uma captura pequena que o n8n
    entregue sem comprimir. Explícito em vez de adivinhado: tentar detectar o
    formato daria diagnóstico ambíguo no dia em que a captura vier corrompida.
    """
    if not conteudo:
        return None
    if codificacao == "texto":
        return conteudo
    try:
        return gzip.decompress(base64.b64decode(conteudo, validate=True)).decode(
            "utf-8", errors="replace"
        )
    except (binascii.Error, OSError, EOFError, ValueError) as erro:
        logger.warning("captura ilegível (%s): %s", codificacao, erro)
        return None


# Quanto do começo do documento basta olhar para decidir se está escapado.
AMOSTRA_DE_ESCAPE = 100_000
# Acima disto, as aspas do documento estão escapadas. Medido nos cinco
# templates em 2026-08-13: o capturado com escape deu razão 1,00 (TODA aspa
# escapada); os limpos deram 0,00, e o pior deles 0,007 — que é JavaScript
# legítimo com string dentro de string. A margem entre 0,007 e 0,50 é grande o
# bastante para não haver falso positivo.
LIMIAR_DE_ESCAPE = 0.5


def parece_html_escapado(html: str) -> bool:
    """True quando o HTML passou por `JSON.stringify` e não foi desescapado.

    É O ERRO MAIS PROVÁVEL DA INTEGRAÇÃO COM O n8n, e o mais traiçoeiro: o
    conteúdo chega inteiro, o arquivo abre, o tamanho parece certo — e nada
    casa, porque `type=\\"application/ld+json\\"` não é o mesmo atributo que
    `type="application/ld+json"`.

    Aconteceu de verdade em 2026-08-13, com uma captura do Terabyte: 4.312 aspas,
    todas escapadas, e o parser reportou `sem_jsonld` como se a loja tivesse
    parado de publicar. Pior ainda, é IRRECUPERÁVEL depois do fato — o bloco
    `Product` tinha `\\r\\n` numa avaliação de cliente, e desfazer escape sobre
    escape é ambíguo. O conserto é sempre a montante: o n8n precisa entregar o
    HTML cru.
    """
    amostra = (html or "")[:AMOSTRA_DE_ESCAPE]
    aspas = amostra.count('"')
    if not aspas:
        return False
    return amostra.count('\\"') / aspas >= LIMIAR_DE_ESCAPE


def _instante(valor) -> datetime | None:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    return None


def ler(
    documento: dict | None,
    *,
    url_esperada: str | None = None,
    agora: datetime | None = None,
    horas_de_validade: int = HORAS_DE_VALIDADE_PADRAO,
) -> tuple[Captura | None, str | None]:
    """Valida e decodifica o documento de captura. Devolve (captura, erro).

    A ordem das checagens segue o custo de diagnóstico: primeiro o que é óbvio
    (não existe), depois o que engana (existe mas é velha), por último o que só
    aparece ao decodificar.
    """
    agora = agora or datetime.now(timezone.utc)

    if not documento:
        return None, ERRO_SEM_CAPTURA

    capturado_em = _instante(documento.get("capturadoEm"))
    if capturado_em is None:
        # Sem carimbo não dá para saber se é de agora ou de ontem, e o benefício
        # da dúvida aqui grava preço velho como se fosse novo.
        return None, ERRO_CAPTURA_VENCIDA
    if agora - capturado_em > timedelta(hours=horas_de_validade):
        idade = agora - capturado_em
        logger.warning(
            "captura com %.1f h (teto %d h) — o n8n parou de escrever?",
            idade.total_seconds() / 3600, horas_de_validade,
        )
        return None, ERRO_CAPTURA_VENCIDA

    url_gravada = documento.get("url")
    if url_esperada and url_gravada and url_gravada != url_esperada:
        # Fonte editada: o n8n ainda não buscou a URL nova. Usar a captura antiga
        # gravaria o preço do produto ERRADO no histórico do produto certo.
        logger.warning(
            "captura é de outra URL (%s), não da fonte (%s)", url_gravada, url_esperada
        )
        return None, ERRO_CAPTURA_DE_OUTRA_URL

    html = descompactar(
        documento.get("html") or "",
        documento.get("codificacao") or CODIFICACAO_PADRAO,
    )
    if not html:
        return None, ERRO_CAPTURA_ILEGIVEL

    if parece_html_escapado(html):
        logger.error(
            "captura com aspas escapadas: o n8n está entregando o HTML dentro de "
            "uma string JSON. Nada vai casar, e desescapar depois é ambíguo. "
            "Conserto no n8n: entregue o campo cru (ex.: {{ $json.data }}), sem "
            "re-serializar."
        )
        return None, ERRO_CAPTURA_ESCAPADA

    return (
        Captura(
            html=html,
            capturado_em=capturado_em,
            url=url_gravada,
            bytes_brutos=documento.get("bytes"),
        ),
        None,
    )


def documento(html: str, url: str, agora: datetime | None = None) -> dict:
    """O documento que o n8n deve escrever. Serve de contrato e de teste.

    Existe em Python para o teste poder afirmar sobre a MESMA estrutura que o n8n
    produz — se o formato mudar aqui, o teste quebra e a documentação do n8n
    (README) fica visivelmente desatualizada.
    """
    return {
        "url": url,
        "html": compactar(html),
        "bytes": len(html.encode("utf-8")),
        "codificacao": CODIFICACAO_PADRAO,
        "capturadoEm": agora or datetime.now(timezone.utc),
    }
