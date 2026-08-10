"""Extração de preço a partir do HTML de uma página de produto.

Módulo PURO: não faz rede, não toca o Firestore, não lê nem escreve disco.
Recebe uma string de HTML e devolve um `ResultadoExtracao`. Essa pureza é o
que permite testar o módulo inteiro contra as fixtures.

Todo valor monetário sai daqui como INTEIRO DE CENTAVOS. Não existe `float`
em nenhum ponto do caminho do preço — ver `normalizar_para_centavos`.
"""

import html as entidades_html
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

TETO_CENTAVOS = 100_000_000

# Comparação em caixa baixa: lojas publicam "Product" e "product".
TIPOS_PRODUTO = frozenset({"product", "individualproduct", "productmodel"})

DISPONIBILIDADE_DISPONIVEL = frozenset(
    {"instock", "limitedavailability", "onlineonly", "preorder", "instoreonly"}
)
DISPONIBILIDADE_INDISPONIVEL = frozenset(
    {"outofstock", "soldout", "discontinued", "backorder"}
)

MOEDA_ACEITA = "BRL"

SELETOR_JSONLD = 'script[type="application/ld+json"]'


@dataclass(frozen=True)
class ResultadoExtracao:
    preco_centavos: int | None
    moeda: str | None
    disponivel: bool
    origem: Literal["j", "g", "m"] | None
    erro: str | None  # preenchido apenas quando preco_centavos is None


# ----------------------------------------------------------------------------
# Normalização do valor monetário
# ----------------------------------------------------------------------------


def normalizar_para_centavos(
    bruto: str | int | float, *, teto_centavos: int = TETO_CENTAVOS
) -> int | None:
    """Converte um preço bruto em inteiro de centavos, ou None se inválido.

    Aceita número (`1299.9`), string pt-BR (`"1.299,90"`) e string en-US
    (`"1299.90"`). O algoritmo está na seção 7.5 da spec e é seguido passo a
    passo — a ordem das decisões sobre os separadores é o ponto inteiro deste
    módulo existir.
    """
    # Passo 1 — número vira string, sem notação científica.
    if isinstance(bruto, bool):
        # bool é subclasse de int em Python; não é preço.
        return None
    if isinstance(bruto, int):
        texto = str(bruto)
    elif isinstance(bruto, float):
        # Decimal(repr(x)) preserva os dígitos que o repr já arredondou e o
        # format "f" desfaz o "1e+20". Sem aritmética com float em momento algum.
        try:
            texto = format(Decimal(repr(bruto)), "f")
        except InvalidOperation:
            return None
    elif isinstance(bruto, str):
        texto = bruto
    else:
        return None

    # O passo 2 apaga qualquer caractere que não seja dígito ou separador, o
    # que inclui o sinal de menos. Se o negativo não for detectado ANTES,
    # "-10,00" vira 1000 e passa pelo teste do passo 7. Ver relatório de
    # ambiguidades: a spec rejeita "-10,00" na tabela mas o passo 2 destruiria
    # o sinal.
    if _tem_sinal_negativo(texto):
        return None

    # Passo 2 — sobram apenas dígitos, vírgulas e pontos.
    limpo = "".join(c for c in texto if c.isdigit() or c in ",.")

    tem_virgula = "," in limpo
    tem_ponto = "." in limpo

    if tem_virgula and tem_ponto:
        # Passo 3 — o separador mais à direita é o decimal.
        if limpo.rfind(",") > limpo.rfind("."):
            limpo = limpo.replace(".", "").replace(",", ".")
        else:
            limpo = limpo.replace(",", "")
    elif tem_virgula or tem_ponto:
        # Passo 4 — um único tipo de separador.
        separador = "," if tem_virgula else "."
        if limpo.count(separador) > 1:
            limpo = limpo.replace(separador, "")
        else:
            digitos_depois = len(limpo) - limpo.index(separador) - 1
            if digitos_depois in (1, 2):
                limpo = limpo.replace(separador, ".")
            elif digitos_depois == 3:
                limpo = limpo.replace(separador, "")
            else:
                return None
    # Passo 5 — sem separador: usar como está.

    # Passo 6 — para centavos pela string, jamais multiplicando float por 100.
    if not limpo:
        return None
    if "." in limpo:
        parte_inteira, _, parte_fracionaria = limpo.partition(".")
    else:
        parte_inteira, parte_fracionaria = limpo, ""

    parte_inteira = parte_inteira or "0"
    # completa à direita e trunca em dois dígitos
    parte_fracionaria = (parte_fracionaria + "00")[:2]

    if not parte_inteira.isdigit() or not parte_fracionaria.isdigit():
        return None

    centavos = int(parte_inteira) * 100 + int(parte_fracionaria)

    # Passo 7 — faixa aceitável.
    if centavos <= 0 or centavos > teto_centavos:
        return None
    return centavos


def _tem_sinal_negativo(texto: str) -> bool:
    """Detecta preço negativo antes da limpeza apagar o sinal."""
    for caractere in texto:
        if caractere.isdigit():
            return False
        if caractere in "-−":  # hífen comum e sinal de menos tipográfico
            return True
    return False


# ----------------------------------------------------------------------------
# Extração
# ----------------------------------------------------------------------------


def extrair_preco(
    html: str, *, teto_centavos: int = TETO_CENTAVOS
) -> ResultadoExtracao:
    """Extrai preço, moeda e disponibilidade do HTML de uma página de produto."""
    arvore = HTMLParser(html or "")

    documentos = _documentos_jsonld(arvore)
    if not documentos:
        return _fallback(arvore, "sem_jsonld", teto_centavos)

    produto = None
    for documento in documentos:
        produto = _primeiro_produto(documento)
        if produto is not None:
            break
    if produto is None:
        return _fallback(arvore, "sem_product", teto_centavos)

    ofertas = _ofertas_do_produto(produto)
    if not ofertas:
        return _fallback(arvore, "sem_offers", teto_centavos)

    candidatos = []
    for oferta in ofertas:
        centavos, moeda = _valor_da_oferta(oferta, teto_centavos)
        if centavos is not None:
            candidatos.append((centavos, moeda, oferta))

    if not candidatos:
        return _fallback(arvore, "preco_invalido", teto_centavos)

    # Lista de ofertas: vale a menor. Oferta única: é a própria.
    centavos, moeda, oferta_escolhida = min(candidatos, key=lambda item: item[0])

    if moeda is not None and moeda.strip().upper() != MOEDA_ACEITA:
        # Não cai para o fallback: o fallback leria o mesmo número em moeda
        # estrangeira e o gravaria como se fosse real. Ver relatório.
        return ResultadoExtracao(None, moeda, False, None, "moeda_nao_suportada")

    return ResultadoExtracao(
        preco_centavos=centavos,
        moeda=MOEDA_ACEITA,
        disponivel=_disponibilidade(oferta_escolhida, produto),
        origem="j",
        erro=None,
    )


def _documentos_jsonld(arvore: HTMLParser) -> list[Any]:
    """Todos os blocos ld+json que fizeram parse, na ordem do documento.

    Cada bloco é decodificado isoladamente: um JSON malformado no meio da
    página não pode impedir a leitura dos demais.
    """
    documentos: list[Any] = []
    for no in arvore.css(SELETOR_JSONLD):
        bruto = no.text(deep=True, strip=False)
        if not bruto or not bruto.strip():
            continue
        try:
            documentos.append(json.loads(_limpar_bloco(bruto)))
        except (ValueError, RecursionError):
            logger.warning("bloco ld+json ignorado por erro de parse")
            continue
    return documentos


def _limpar_bloco(bruto: str) -> str:
    """Remove envelopes e sujeira que impedem o `json.loads`."""
    texto = bruto.strip()

    # Envelope de comentário HTML e CDATA, com o "//" que alguns CMS colocam.
    for marcador in ("<!--", "-->", "<![CDATA[", "]]>", "/*<![CDATA[*/", "/*]]>*/"):
        texto = texto.replace(marcador, "")
    texto = texto.strip()
    if texto.startswith("//"):
        texto = texto[2:].strip()

    texto = entidades_html.unescape(texto)
    return _remover_virgulas_penduradas(texto)


def _remover_virgulas_penduradas(texto: str) -> str:
    """Apaga a vírgula que antecede `}` ou `]`.

    Percorre caractere a caractere respeitando strings JSON: uma vírgula
    dentro de `"descrição, }"` não pode ser tocada.
    """
    saida: list[str] = []
    dentro_de_texto = False
    escapado = False

    for caractere in texto:
        if dentro_de_texto:
            saida.append(caractere)
            if escapado:
                escapado = False
            elif caractere == "\\":
                escapado = True
            elif caractere == '"':
                dentro_de_texto = False
            continue

        if caractere == '"':
            dentro_de_texto = True
            saida.append(caractere)
            continue

        if caractere in "}]":
            indice = len(saida) - 1
            while indice >= 0 and saida[indice].isspace():
                indice -= 1
            if indice >= 0 and saida[indice] == ",":
                del saida[indice:]

        saida.append(caractere)

    return "".join(saida)


def _tipos(no: dict) -> list[str]:
    """`@type` normalizado para lista. Pode chegar como string ou como lista."""
    tipo = no.get("@type")
    if isinstance(tipo, str):
        return [tipo]
    if isinstance(tipo, list):
        return [item for item in tipo if isinstance(item, str)]
    return []


def _eh_do_tipo(no: Any, tipos_aceitos: frozenset[str]) -> bool:
    """Pertencimento, nunca igualdade: `@type` pode ser lista."""
    if not isinstance(no, dict):
        return False
    return any(tipo.strip().lower() in tipos_aceitos for tipo in _tipos(no))


def _primeiro_produto(documento: Any) -> dict | None:
    """Busca recursiva pelo primeiro nó de produto na ordem do documento.

    Cobre de uma vez objeto raiz, array raiz, envelope `@graph`, `mainEntity`
    e `itemListElement[].item` — sem código específico para cada forma.
    """
    if isinstance(documento, dict):
        if _eh_do_tipo(documento, TIPOS_PRODUTO):
            return documento
        for valor in documento.values():
            achado = _primeiro_produto(valor)
            if achado is not None:
                return achado
    elif isinstance(documento, list):
        for item in documento:
            achado = _primeiro_produto(item)
            if achado is not None:
                return achado
    return None


def _ofertas_do_produto(produto: dict) -> list[dict]:
    """Normaliza `offers` para uma lista de dicionários."""
    ofertas = produto.get("offers")
    if isinstance(ofertas, dict):
        return [ofertas]
    if isinstance(ofertas, list):
        return [item for item in ofertas if isinstance(item, dict)]
    return []


def _especificacao(oferta: dict) -> dict | None:
    """`priceSpecification`, que às vezes vem embrulhado em lista."""
    especificacao = oferta.get("priceSpecification")
    if isinstance(especificacao, list):
        especificacao = next(
            (item for item in especificacao if isinstance(item, dict)), None
        )
    return especificacao if isinstance(especificacao, dict) else None


def _valor_da_oferta(
    oferta: dict, teto_centavos: int
) -> tuple[int | None, str | None]:
    """Preço em centavos e moeda declarada de uma única oferta."""
    especificacao = _especificacao(oferta)

    if _eh_do_tipo(oferta, frozenset({"aggregateoffer"})):
        bruto = oferta.get("lowPrice")
        if bruto is None:
            bruto = oferta.get("price")
    else:
        bruto = oferta.get("price")
        if bruto is None and especificacao is not None:
            bruto = especificacao.get("price")

    moeda = oferta.get("priceCurrency")
    if moeda is None and especificacao is not None:
        moeda = especificacao.get("priceCurrency")
    if not isinstance(moeda, str):
        moeda = None

    if not isinstance(bruto, (str, int, float)):
        return None, moeda
    return normalizar_para_centavos(bruto, teto_centavos=teto_centavos), moeda


def _disponibilidade(oferta: dict, produto: dict) -> bool:
    """Traduz `availability` para booleano.

    Campo ausente significa disponível: a maioria das lojas só publica o campo
    quando o produto acabou.
    """
    bruto = oferta.get("availability")
    if bruto is None:
        especificacao = _especificacao(oferta)
        if especificacao is not None:
            bruto = especificacao.get("availability")
    if bruto is None:
        bruto = produto.get("availability")
    if not isinstance(bruto, str) or not bruto.strip():
        return True

    termo = bruto.strip().rstrip("/").rsplit("/", 1)[-1].strip().lower()
    if termo in DISPONIBILIDADE_DISPONIVEL:
        return True
    if termo in DISPONIBILIDADE_INDISPONIVEL:
        return False

    logger.warning("availability desconhecida: %r — assumindo disponível", bruto)
    return True


# ----------------------------------------------------------------------------
# Fallback
# ----------------------------------------------------------------------------


def _fallback(
    arvore: HTMLParser, erro: str, teto_centavos: int
) -> ResultadoExtracao:
    """Open Graph e microdata, nessa ordem, quando o JSON-LD não serviu."""
    tentativas = (
        ("g", 'meta[property="product:price:amount"]', "content", _moeda_opengraph),
        ("m", '[itemprop="price"]', "content", _moeda_microdata),
    )

    for origem, seletor, atributo, ler_moeda in tentativas:
        no = arvore.css_first(seletor)
        if no is None:
            continue

        bruto = no.attributes.get(atributo)
        if bruto is None:
            bruto = no.text(deep=True, strip=True)
        if not bruto:
            continue

        centavos = normalizar_para_centavos(bruto, teto_centavos=teto_centavos)
        if centavos is None:
            continue

        moeda = ler_moeda(arvore)
        if moeda is not None and moeda.strip().upper() != MOEDA_ACEITA:
            return ResultadoExtracao(None, moeda, False, None, "moeda_nao_suportada")

        return ResultadoExtracao(centavos, MOEDA_ACEITA, True, origem, None)

    return ResultadoExtracao(None, None, False, None, erro)


def _moeda_opengraph(arvore: HTMLParser) -> str | None:
    no = arvore.css_first('meta[property="product:price:currency"]')
    return no.attributes.get("content") if no is not None else None


def _moeda_microdata(arvore: HTMLParser) -> str | None:
    no = arvore.css_first('[itemprop="priceCurrency"]')
    if no is None:
        return None
    return no.attributes.get("content") or no.text(deep=True, strip=True) or None
