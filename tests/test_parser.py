"""Testes do parser: regras da spec em HTML inline + gabarito das fixtures."""

import pytest

from coletor.parser import ResultadoExtracao, extrair_preco, normalizar_para_centavos
from conftest import carregar_gabarito, gabarito_disponivel, ler_fixture


def pagina(*blocos_jsonld: str, corpo: str = "") -> str:
    """Monta uma página mínima com os blocos ld+json informados."""
    scripts = "".join(
        f'<script type="application/ld+json">{bloco}</script>'
        for bloco in blocos_jsonld
    )
    return f"<html><head>{scripts}</head><body>{corpo}</body></html>"


PRODUTO_SIMPLES = """
{"@context":"https://schema.org","@type":"Product","name":"Fone",
 "offers":{"@type":"Offer","price":"1.299,90","priceCurrency":"BRL",
           "availability":"https://schema.org/InStock"}}
"""


# --- Caminho feliz ----------------------------------------------------------


def test_produto_no_objeto_raiz():
    resultado = extrair_preco(pagina(PRODUTO_SIMPLES))
    assert resultado == ResultadoExtracao(129990, "BRL", True, "j", None)


# --- 7.3 Localização do nó Product -----------------------------------------


@pytest.mark.parametrize(
    "bloco",
    [
        # array na raiz
        '[{"@type":"WebSite"},{"@type":"Product",'
        '"offers":{"@type":"Offer","price":"10,00","priceCurrency":"BRL"}}]',
        # envelope @graph, produto fora do índice zero
        '{"@graph":[{"@type":"Organization"},{"@type":"BreadcrumbList"},'
        '{"@type":"Product","offers":{"@type":"Offer","price":"10,00",'
        '"priceCurrency":"BRL"}}]}',
        # aninhado em mainEntity
        '{"@type":"WebPage","mainEntity":{"@type":"Product",'
        '"offers":{"@type":"Offer","price":"10,00","priceCurrency":"BRL"}}}',
        # aninhado em itemListElement[].item
        '{"@type":"ItemList","itemListElement":[{"@type":"ListItem",'
        '"item":{"@type":"Product","offers":{"@type":"Offer",'
        '"price":"10,00","priceCurrency":"BRL"}}}]}',
    ],
    ids=["array_raiz", "graph", "mainEntity", "itemListElement"],
)
def test_encontra_produto_em_qualquer_posicao(bloco):
    assert extrair_preco(pagina(bloco)).preco_centavos == 1000


@pytest.mark.parametrize(
    "tipo",
    ['"Product"', '["Product","Thing"]', '"IndividualProduct"', '"ProductModel"'],
)
def test_tipo_como_string_ou_lista(tipo):
    bloco = (
        f'{{"@type":{tipo},"offers":{{"@type":"Offer",'
        '"price":"10,00","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 1000


def test_usa_o_primeiro_produto_na_ordem_do_documento():
    principal = (
        '{"@type":"Product","name":"principal","offers":'
        '{"@type":"Offer","price":"100,00","priceCurrency":"BRL"}}'
    )
    relacionado = (
        '{"@type":"Product","name":"relacionado","offers":'
        '{"@type":"Offer","price":"5,00","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(principal, relacionado)).preco_centavos == 10000


# --- 7.2 Robustez dos blocos ------------------------------------------------


def test_bloco_malformado_nao_impede_os_demais():
    resultado = extrair_preco(pagina("{isso não é json", PRODUTO_SIMPLES))
    assert resultado.preco_centavos == 129990


def test_envelope_de_comentario_e_cdata():
    for envelope in (
        f"<!--{PRODUTO_SIMPLES}-->",
        f"<![CDATA[{PRODUTO_SIMPLES}]]>",
    ):
        assert extrair_preco(pagina(envelope)).preco_centavos == 129990


def test_virgula_pendurada():
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","price":"10,00",'
        '"priceCurrency":"BRL",},}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 1000


def test_virgula_dentro_de_string_e_preservada():
    bloco = (
        '{"@type":"Product","name":"cabo, } especial",'
        '"offers":{"@type":"Offer","price":"10,00","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 1000


def test_entidades_html_decodificadas():
    bloco = (
        '{"@type":"Product","name":"A &amp; B","offers":'
        '{"@type":"Offer","price":"10,00","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 1000


# --- 7.4 Extração da oferta -------------------------------------------------


def test_preco_em_price_specification():
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","priceSpecification":'
        '{"@type":"UnitPriceSpecification","price":"1.299,90",'
        '"priceCurrency":"BRL"}}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 129990


def test_lista_de_ofertas_usa_a_menor():
    bloco = (
        '{"@type":"Product","offers":['
        '{"@type":"Offer","price":"1.500,00","priceCurrency":"BRL"},'
        '{"@type":"Offer","price":"1.299,90","priceCurrency":"BRL"},'
        '{"@type":"Offer","price":"1.800,00","priceCurrency":"BRL"}]}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 129990


def test_aggregate_offer_usa_low_price():
    bloco = (
        '{"@type":"Product","offers":{"@type":"AggregateOffer",'
        '"lowPrice":"1.299,90","highPrice":"1.800,00","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 129990


def test_aggregate_offer_sem_low_price_usa_price():
    bloco = (
        '{"@type":"Product","offers":{"@type":"AggregateOffer",'
        '"price":"1.299,90","priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).preco_centavos == 129990


# --- 7.6 Moeda e disponibilidade -------------------------------------------


@pytest.mark.parametrize(
    "availability, esperado",
    [
        ("https://schema.org/InStock", True),
        ("http://schema.org/InStock", True),
        ("InStock", True),
        ("https://schema.org/LimitedAvailability", True),
        ("https://schema.org/OnlineOnly", True),
        ("https://schema.org/PreOrder", True),
        ("https://schema.org/InStoreOnly", True),
        ("https://schema.org/OutOfStock", False),
        ("https://schema.org/SoldOut", False),
        ("https://schema.org/Discontinued", False),
        ("https://schema.org/BackOrder", False),
    ],
)
def test_disponibilidade(availability, esperado):
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","price":"10,00",'
        f'"priceCurrency":"BRL","availability":"{availability}"}}}}'
    )
    assert extrair_preco(pagina(bloco)).disponivel is esperado


def test_availability_ausente_assume_disponivel():
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","price":"10,00",'
        '"priceCurrency":"BRL"}}'
    )
    assert extrair_preco(pagina(bloco)).disponivel is True


def test_availability_desconhecida_assume_disponivel():
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","price":"10,00",'
        '"priceCurrency":"BRL","availability":"https://schema.org/Sei-la"}}'
    )
    assert extrair_preco(pagina(bloco)).disponivel is True


def test_moeda_estrangeira_e_falha_sem_conversao():
    bloco = (
        '{"@type":"Product","offers":{"@type":"Offer","price":"199.90",'
        '"priceCurrency":"USD"}}'
    )
    resultado = extrair_preco(pagina(bloco))
    assert resultado.preco_centavos is None
    assert resultado.erro == "moeda_nao_suportada"


# --- 7.7 Fallback -----------------------------------------------------------


def test_fallback_opengraph():
    html = (
        '<html><head><meta property="product:price:amount" content="1299.90">'
        "</head><body></body></html>"
    )
    resultado = extrair_preco(html)
    assert (resultado.preco_centavos, resultado.origem) == (129990, "g")


def test_fallback_microdata_por_atributo_content():
    html = '<html><body><span itemprop="price" content="1.299,90"></span></body></html>'
    resultado = extrair_preco(html)
    assert (resultado.preco_centavos, resultado.origem) == (129990, "m")


def test_fallback_microdata_por_texto():
    html = '<html><body><span itemprop="price">R$ 1.299,90</span></body></html>'
    resultado = extrair_preco(html)
    assert (resultado.preco_centavos, resultado.origem) == (129990, "m")


def test_opengraph_tem_prioridade_sobre_microdata():
    html = (
        '<html><head><meta property="product:price:amount" content="10.00"></head>'
        '<body><span itemprop="price" content="20,00"></span></body></html>'
    )
    resultado = extrair_preco(html)
    assert (resultado.preco_centavos, resultado.origem) == (1000, "g")


@pytest.mark.parametrize(
    "html, erro",
    [
        ("<html><body>nada aqui</body></html>", "sem_jsonld"),
        (pagina('{"@type":"Organization","name":"Loja"}'), "sem_product"),
        (pagina('{"@type":"Product","name":"sem oferta"}'), "sem_offers"),
        (
            pagina(
                '{"@type":"Product","offers":{"@type":"Offer",'
                '"price":"consulte","priceCurrency":"BRL"}}'
            ),
            "preco_invalido",
        ),
    ],
    ids=["sem_jsonld", "sem_product", "sem_offers", "preco_invalido"],
)
def test_motivos_de_falha(html, erro):
    resultado = extrair_preco(html)
    assert resultado.preco_centavos is None
    assert resultado.origem is None
    assert resultado.erro == erro


def test_falha_nunca_devolve_preco_zero():
    resultado = extrair_preco("<html></html>")
    assert resultado.preco_centavos is None


def test_jsonld_invalido_cai_para_o_fallback():
    html = (
        '<html><head><script type="application/ld+json">{"@type":"Product"}</script>'
        '<meta property="product:price:amount" content="1299.90"></head></html>'
    )
    resultado = extrair_preco(html)
    assert (resultado.preco_centavos, resultado.origem) == (129990, "g")


# --- Pureza -----------------------------------------------------------------


def test_parser_nao_importa_rede_nem_firestore():
    import coletor.parser as modulo

    fonte = open(modulo.__file__, encoding="utf-8").read()
    for proibido in ("httpx", "firebase_admin", "requests", "urllib.request"):
        assert proibido not in fonte, f"{proibido} não pode aparecer no parser"


# --- Gabarito das fixtures (portão da fase 1) -------------------------------


def _casos_do_gabarito():
    """Achata `esperado.json` em uma lista de (arquivo, esperado).

    Aceita as duas formas possíveis de gabarito — mapa por nome de arquivo ou
    lista de objetos — porque o schema não veio documentado. Chaves que não
    terminam em `.html` são metadados e ficam de fora.
    """
    gabarito = carregar_gabarito()
    if isinstance(gabarito, dict):
        itens = sorted(gabarito.items())
    else:
        itens = [(item["arquivo"], item) for item in gabarito]
    return [(nome, dados) for nome, dados in itens if nome.endswith(".html")]


@pytest.mark.skipif(
    gabarito_disponivel(),
    reason="gabarito presente: os testes reais rodam abaixo",
)
def test_fixtures_ausentes():
    pytest.fail(
        "tests/fixtures/ está vazio: as 4 páginas e o esperado.json não foram "
        "entregues com a tarefa. A spec proíbe fabricá-las (regra 2), então o "
        "portão da fase 1 fica ABERTO até os arquivos chegarem."
    )


@pytest.mark.skipif(not gabarito_disponivel(), reason="gabarito não fornecido")
@pytest.mark.parametrize("arquivo, esperado", _casos_do_gabarito() if gabarito_disponivel() else [])
def test_fixture_bate_com_o_gabarito(arquivo, esperado):
    resultado = extrair_preco(ler_fixture(arquivo))

    if "preco_centavos" in esperado:
        centavos = esperado["preco_centavos"]
    elif esperado.get("preco") is not None:
        centavos = normalizar_para_centavos(esperado["preco"])
    else:
        centavos = None

    assert resultado.preco_centavos == centavos
    if "disponivel" in esperado:
        assert resultado.disponivel is esperado["disponivel"]
    if "origem" in esperado:
        assert resultado.origem == esperado["origem"]
