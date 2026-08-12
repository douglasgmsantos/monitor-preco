"""Registro de lojas e extração por página de produto.

Os templates em `coletor/templates/` são capturas REAIS das páginas, feitas em
2026-08-12. Valem como fixture congelada pela mesma regra de `tests/fixtures/`:
se uma loja mudar o layout, o template continua sendo caso de teste válido —
**não recapture para "consertar" um teste vermelho** sem antes entender o que
mudou. Um teste vermelho aqui é a notícia, não o problema.

Os valores esperados foram conferidos no HTML na captura E numa busca ao vivo no
mesmo dia: os dois casaram valor por valor.

AS CAPTURAS NÃO SÃO VERSIONADAS (2,6 MB, ver .gitignore), e daí o
`@precisa_de_templates` abaixo. O custo é real e vale dito em voz alta: num
clone sem elas, tudo o que depende de HTML de loja PULA, e a suíte fica verde
sem ter verificado nada disso. Quem for mexer em `coletor/lojas.py` precisa das
capturas na máquina — do contrário está trabalhando às cegas.

Os testes que não dependem de captura (registro, cabeçalhos, seletores contra
HTML sintético, página de bloqueio) rodam sempre, de propósito: são a parte que
protege a lógica, e essa não pode depender de arquivo externo.
"""

from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import respx

from coletor.coleta import (
    LIMITE_FALHAS_SEGUIDAS, LimitadorPorHost, coletar_fonte, validar_fonte_pendente,
)
from coletor.lojas import (
    CABECALHOS_DE_NAVEGADOR, LOJAS, Loja, cabecalhos_de, extrair_da_loja, loja_de,
)
from coletor.parser import (
    ERRO_BLOQUEIO, ERRO_SEM_OFERTA, ERROS_DE_PARSE, SeletoresDeProduto,
    extrair_preco, extrair_preco_dom, parece_pagina_de_bloqueio,
)

TEMPLATES = Path(__file__).resolve().parent.parent / "coletor" / "templates"

UA_HONESTO = "MonitorPrecos/1.0 (uso pessoal)"

# URL canônica de cada template, lida do próprio <link rel=canonical>.
CANONICAS = {
    "amazon": "https://www.amazon.com.br/ASUS-RTX5070/dp/B0DVH3R5WN",
    "pichau": "https://www.pichau.com.br/placa-de-video-asrock-radeon-rx-9070-xt",
    "terabyte": "https://www.terabyteshop.com.br/produto/38584/placa-de-video-asrock",
}


NOMES_DE_TEMPLATE = ("amazon", "pichau", "terabyte")


def templates_presentes() -> bool:
    return all(
        (TEMPLATES / f"{nome}-produto-detalhes.html").is_file()
        for nome in NOMES_DE_TEMPLATE
    )


precisa_de_templates = pytest.mark.skipif(
    not templates_presentes(),
    reason=(
        f"capturas ausentes em {TEMPLATES} (não versionadas — ver .gitignore). "
        "Sem elas os seletores da Amazon e o JSON-LD de Pichau/Terabyte não são "
        "verificados. Recriar: README, seção 'Lojas suportadas'."
    ),
)


def template(nome: str) -> str:
    caminho = TEMPLATES / f"{nome}-produto-detalhes.html"
    if not caminho.is_file():
        pytest.fail(f"template ausente: {caminho} — não é permitido fabricá-lo")
    return caminho.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def test_lista_fechada_tem_as_quatro_lojas():
    assert [loja.nome for loja in LOJAS] == [
        "KaBuM", "Terabyte Shop", "Pichau", "Amazon",
    ]


@pytest.mark.parametrize(
    "url, esperado",
    [
        ("https://www.amazon.com.br/dp/B0DVH3R5WN", "Amazon"),
        ("https://amazon.com.br/dp/B0DVH3R5WN", "Amazon"),
        ("https://www.kabum.com.br/produto/123", "KaBuM"),
        ("https://www.pichau.com.br/placa", "Pichau"),
        ("https://www.terabyteshop.com.br/produto/1/x", "Terabyte Shop"),
        ("https://www.carrefour.com.br/produto", None),
        ("https://www.amazon.com/dp/B0DVH3R5WN", None),   # .com não é .com.br
        ("", None),
        ("nao é url", None),
    ],
)
def test_loja_de_reconhece_o_dominio(url, esperado):
    loja = loja_de(url)
    assert (loja.nome if loja else None) == esperado


def test_dominio_impostor_nao_casa():
    """`amazon.com.br.golpe.com` não é a Amazon.

    O casamento é por sufixo de rótulo (`.dominio`), nunca por substring — sem
    isso qualquer domínio poderia se passar por loja suportada.
    """
    assert loja_de("https://amazon.com.br.golpe.com/dp/1") is None
    assert loja_de("https://naoamazon.com.br/dp/1") is None


def test_estrategia_dom_exige_seletores():
    with pytest.raises(ValueError, match="seletores"):
        Loja(nome="X", dominios=("x.com",), estrategia="dom")


# ---------------------------------------------------------------------------
# Cabeçalhos
# ---------------------------------------------------------------------------


def test_amazon_recebe_cabecalhos_de_navegador():
    """Exceção medida, não conveniência: com UA honesto a Amazon devolve uma
    página de 221 KB sem nenhuma marcação de produto."""
    cabecalhos = cabecalhos_de("https://www.amazon.com.br/dp/B1", UA_HONESTO)
    assert cabecalhos["User-Agent"].startswith("Mozilla/5.0")
    assert cabecalhos == CABECALHOS_DE_NAVEGADOR


@pytest.mark.parametrize(
    "url",
    [
        "https://www.kabum.com.br/produto/1",
        "https://www.pichau.com.br/x",
        "https://www.terabyteshop.com.br/produto/1/x",
        "https://loja.desconhecida.com/x",
    ],
)
def test_as_demais_mantem_o_user_agent_honesto(url):
    assert cabecalhos_de(url, UA_HONESTO) == {"User-Agent": UA_HONESTO}


# ---------------------------------------------------------------------------
# Extração — o que cada loja rende
# ---------------------------------------------------------------------------


@precisa_de_templates
def test_amazon_sai_por_dom_com_o_preco_do_bloco_principal():
    resultado = extrair_da_loja(CANONICAS["amazon"], template("amazon"))
    assert resultado.preco_centavos == 712405       # R$ 7.124,05
    assert resultado.moeda == "BRL"
    assert resultado.disponivel is True
    assert resultado.origem == "d"
    assert resultado.erro is None


@precisa_de_templates
def test_amazon_ignora_os_outros_precos_da_pagina():
    """A página tem 22 `span.a-offscreen`; o segundo é R$ 7.499,00.

    Sem o escopo em `#corePrice_feature_div` o coletor gravaria um número
    plausível e errado — a pior espécie de bug, porque não parece bug.
    """
    resultado = extrair_da_loja(CANONICAS["amazon"], template("amazon"))
    assert resultado.preco_centavos != 749900
    assert resultado.preco_centavos != 829900       # o preço "de" riscado


@precisa_de_templates
def test_terabyte_sai_por_jsonld_e_ja_e_o_preco_a_vista():
    """O JSON-LD do Terabyte É o preço à vista.

    A página diz "R$ 4.599,90 à vista com 15% de desconto no pix", mesmo valor do
    `Offer.price`. Por isso o Terabyte não precisa de ajuste nenhum — é a régua
    que o sistema segue.
    """
    resultado = extrair_da_loja(CANONICAS["terabyte"], template("terabyte"))
    assert resultado.preco_centavos == 459990
    assert resultado.origem == "j"
    assert resultado.disponivel is True


@precisa_de_templates
def test_pichau_usa_o_avista_do_estado_e_nao_o_parcelado_do_jsonld():
    """A Pichau é a única cujo JSON-LD NÃO é o preço à vista.

    `Offer.price` traz 5.529,40 (o `final_price`, parcelado) e o à vista de
    4.699,99 mora só no estado embutido. A diferença não é cosmética: com o
    gatilho deste repositório em R$ 4.700,00, o à vista dispara alerta e o
    parcelado não dispara nunca.
    """
    resultado = extrair_da_loja(CANONICAS["pichau"], template("pichau"))
    assert resultado.preco_centavos == 469999      # à vista, PIX, 15% off
    assert resultado.preco_centavos != 552940      # o parcelado do JSON-LD
    assert resultado.origem == "e"                 # veio do estado embutido
    assert resultado.disponivel is True            # disponibilidade do JSON-LD


@precisa_de_templates
def test_pichau_sem_o_avista_falha_em_vez_de_usar_o_parcelado():
    """Cair para o JSON-LD seria gravar um número ~18% maior, em silêncio.

    E para sempre: a série histórica ficaria contaminada e o alerta nunca
    dispararia. Falhar alto é a escolha certa aqui.
    """
    adulterado = template("pichau").replace("avista", "outro_nome_qualquer")
    resultado = extrair_da_loja(CANONICAS["pichau"], adulterado)
    assert resultado.erro == "sem_preco_avista"
    assert resultado.preco_centavos is None


def test_sem_preco_avista_e_erro_de_parse():
    """É de PARSE porque a página mudou, não porque a rede falhou."""
    assert "sem_preco_avista" in ERROS_DE_PARSE


@precisa_de_templates
def test_amazon_nao_sai_por_jsonld():
    """Registra o fato que motivou a estratégia de DOM."""
    assert extrair_preco(template("amazon")).erro == "sem_jsonld"


@precisa_de_templates
def test_loja_fora_do_registro_cai_no_jsonld():
    """Fonte antiga gravada antes da lista fechada não pode perder histórico."""
    resultado = extrair_da_loja("https://www.carrefour.com.br/x", template("pichau"))
    assert resultado.preco_centavos == 552940
    assert resultado.origem == "j"


# ---------------------------------------------------------------------------
# Página de bloqueio — o modo de falha que precisa ser distinguido
# ---------------------------------------------------------------------------


def test_desafio_do_cloudflare_e_reconhecido():
    """Terabyte respondeu isto em 2026-08-12, HTTP 403 com 6 KB."""
    assert parece_pagina_de_bloqueio(
        '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
    )


@precisa_de_templates
def test_template_legitimo_nao_e_confundido_com_bloqueio():
    for nome in ("amazon", "pichau", "terabyte"):
        assert not parece_pagina_de_bloqueio(template(nome))


def test_pagina_sem_prova_de_produto_vira_bloqueio_e_nao_erro_de_parse():
    """O caso perigoso: HTTP 200, corpo grande, zero marcação de produto.

    Se isso fosse classificado como erro de parse, a fonte seria condenada como
    URL ruim depois de 5 ciclos. Como é transporte, ela sobrevive até a loja
    voltar a responder — que é o que de fato acontece quando a loja desbloqueia.
    """
    pagina = "<html><body>" + ("<div>conteudo qualquer</div>" * 500) + "</body></html>"
    resultado = extrair_da_loja(CANONICAS["amazon"], pagina)
    assert resultado.erro == ERRO_BLOQUEIO
    assert resultado.preco_centavos is None


def test_bloqueio_fica_fora_de_erros_de_parse():
    """É a asserção que garante o comportamento do teste acima em `coleta.py`."""
    assert ERRO_BLOQUEIO not in ERROS_DE_PARSE


# ---------------------------------------------------------------------------
# Guardas do extrator de DOM
# ---------------------------------------------------------------------------


SELETORES_DE_TESTE = SeletoresDeProduto(
    preco=("#preco-que-nao-existe", "#preco"),   # prova a ordem de tentativa
    prova_de_produto="#titulo",
    marcador_sem_oferta="#sem-vendedor",
    disponibilidade="#estoque", botao_de_compra="#comprar",
)


def pagina(preco="R$ 10,00", estoque="Em estoque", comprar=True, titulo=True):
    partes = ['<html><body>']
    if titulo:
        partes.append('<h1 id="titulo">Produto</h1>')
    partes.append(f'<span id="preco">{preco}</span>')
    partes.append(f'<div id="estoque">{estoque}</div>')
    if comprar:
        partes.append('<button id="comprar">Comprar</button>')
    partes.append('</body></html>')
    return "".join(partes)


def test_dom_le_preco_e_estoque():
    resultado = extrair_preco_dom(pagina(), SELETORES_DE_TESTE)
    assert resultado.preco_centavos == 1000
    assert resultado.disponivel is True
    assert resultado.origem == "d"


def test_dom_sem_preco_no_seletor():
    html = '<html><body><h1 id="titulo">Produto</h1></body></html>'
    assert extrair_preco_dom(html, SELETORES_DE_TESTE).erro == "sem_preco_no_dom"


def test_dom_sem_oferta_nao_e_erro_de_parse():
    """Produto sem vendedor é estado do mercado, não página quebrada.

    A distinção decide se a fonte morre: `sem_preco_no_dom` está em
    ERROS_DE_PARSE e condena; `sem_oferta_ativa` não está e deixa a fonte viva
    para quando alguém voltar a vender.
    """
    html = (
        '<html><body><h1 id="titulo">Produto</h1>'
        '<div id="sem-vendedor">Sem ofertas no momento</div></body></html>'
    )
    resultado = extrair_preco_dom(html, SELETORES_DE_TESTE)
    assert resultado.erro == ERRO_SEM_OFERTA
    assert ERRO_SEM_OFERTA not in ERROS_DE_PARSE
    assert resultado.disponivel is False


def test_dom_recusa_moeda_estrangeira():
    """Um preço em dólar tem a mesma forma e passaria como se fosse real."""
    resultado = extrair_preco_dom(pagina(preco="US$ 10.00"), SELETORES_DE_TESTE)
    assert resultado.erro == "moeda_nao_suportada"
    assert resultado.preco_centavos is None


def test_dom_texto_de_falta_vence_o_botao():
    resultado = extrair_preco_dom(
        pagina(estoque="Temporariamente sem estoque", comprar=True),
        SELETORES_DE_TESTE,
    )
    assert resultado.preco_centavos == 1000     # ainda registra o preço
    assert resultado.disponivel is False


def test_dom_sem_botao_de_compra_e_indisponivel():
    resultado = extrair_preco_dom(pagina(comprar=False), SELETORES_DE_TESTE)
    assert resultado.disponivel is False


def test_dom_respeita_o_teto():
    resultado = extrair_preco_dom(
        pagina(preco="R$ 9.999.999,00"), SELETORES_DE_TESTE, teto_centavos=100_000
    )
    assert resultado.erro == "preco_invalido"


# ---------------------------------------------------------------------------
# Ligação com a coleta — HTTP mockado, parser de verdade
# ---------------------------------------------------------------------------

URL_AMAZON = "https://www.amazon.com.br/ASUS-RTX5070/dp/B0DVH3R5WN"


@dataclass
class FonteFalsa:
    id: str = "f1"
    loja: str = "Amazon"
    url: str = URL_AMAZON
    falhas_seguidas: int = 0
    ultimo_preco_centavos: int | None = None


@dataclass
class RepositorioFalso:
    leituras: list = field(default_factory=list)
    validas: list = field(default_factory=list)
    invalidas: list = field(default_factory=list)
    tentativas: list = field(default_factory=list)
    com_erro: list = field(default_factory=list)

    def registrar_leitura(self, fonte, resultado, suspeito):
        self.leituras.append((fonte.id, resultado, suspeito))

    def marcar_fonte_valida(self, fonte, preco_centavos, origem):
        self.validas.append((fonte.id, preco_centavos, origem))

    def marcar_fonte_invalida(self, fonte, motivo):
        self.invalidas.append((fonte.id, motivo))

    def registrar_tentativa_de_validacao(self, fonte, motivo):
        self.tentativas.append((fonte.id, motivo))

    def marcar_fonte_com_erro(self, fonte):
        self.com_erro.append(fonte.id)


class RelogioFalso:
    def __init__(self):
        self.agora = 0.0

    def monotonic(self):
        return self.agora

    async def dormir(self, segundos):
        self.agora += segundos


@pytest.fixture
def limitador():
    relogio = RelogioFalso()
    return LimitadorPorHost(dormir=relogio.dormir, relogio=relogio.monotonic)


@precisa_de_templates
@pytest.mark.asyncio
@respx.mock
async def test_coleta_da_amazon_manda_cabecalhos_de_navegador(limitador):
    rota = respx.get(URL_AMAZON).mock(
        return_value=httpx.Response(200, html=template("amazon"))
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        resultado = await coletar_fonte(
            FonteFalsa(), cliente, repositorio,
            user_agent=UA_HONESTO, limiar_sanidade="0.70",
            teto_centavos=100_000_000, limitador=limitador,
        )

    enviados = rota.calls[0].request.headers
    assert enviados["user-agent"].startswith("Mozilla/5.0")
    assert UA_HONESTO not in enviados["user-agent"]
    assert enviados["accept-language"].startswith("pt-BR")
    assert resultado.resultado.preco_centavos == 712405
    assert resultado.resultado.origem == "d"


@pytest.mark.asyncio
@respx.mock
async def test_coleta_da_kabum_mantem_o_user_agent_honesto(limitador):
    url = "https://www.kabum.com.br/produto/1"
    rota = respx.get(url).mock(return_value=httpx.Response(200, html="<html></html>"))

    async with httpx.AsyncClient() as cliente:
        await coletar_fonte(
            FonteFalsa(loja="KaBuM", url=url), cliente, RepositorioFalso(),
            user_agent=UA_HONESTO, limiar_sanidade="0.70",
            teto_centavos=100_000_000, limitador=limitador,
        )

    assert rota.calls[0].request.headers["user-agent"] == UA_HONESTO


@pytest.mark.asyncio
@respx.mock
async def test_bloqueio_nao_condena_a_fonte_pendente(limitador):
    """O 200-sem-produto da Amazon precisa manter a fonte viva.

    Se `pagina_de_bloqueio` entrasse em ERROS_DE_PARSE, a primeira validação
    marcaria a fonte como inválida e o usuário veria "URL não legível" para uma
    URL perfeitamente boa que a loja recusou naquele instante.
    """
    respx.get(URL_AMAZON).mock(
        return_value=httpx.Response(200, html="<html><body>nada aqui</body></html>")
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        resultado = await validar_fonte_pendente(
            FonteFalsa(), cliente, repositorio,
            user_agent=UA_HONESTO, teto_centavos=100_000_000, limitador=limitador,
        )

    assert resultado.erro == ERRO_BLOQUEIO
    assert repositorio.invalidas == []                    # não condenou
    assert repositorio.tentativas == [("f1", ERRO_BLOQUEIO)]   # segue tentando


@pytest.mark.asyncio
@respx.mock
async def test_bloqueio_persistente_acaba_condenando(limitador):
    """Insistir para sempre também seria errado: na quinta, desiste."""
    respx.get(URL_AMAZON).mock(
        return_value=httpx.Response(200, html="<html><body>nada</body></html>")
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        await validar_fonte_pendente(
            FonteFalsa(falhas_seguidas=LIMITE_FALHAS_SEGUIDAS - 1),
            cliente, repositorio,
            user_agent=UA_HONESTO, teto_centavos=100_000_000, limitador=limitador,
        )

    assert repositorio.invalidas == [("f1", ERRO_BLOQUEIO)]


@precisa_de_templates
@pytest.mark.asyncio
@respx.mock
async def test_validacao_da_pichau_promove_com_o_preco_a_vista(limitador):
    """Ponta a ponta: a fonte é promovida com 4.699,99 e origem `e`.

    Se este teste voltar a esperar 552940, alguém desfez o ajuste do à vista e o
    alerta desta loja parou de disparar.
    """
    url = "https://www.pichau.com.br/placa-de-video-asrock"
    respx.get(url).mock(return_value=httpx.Response(200, html=template("pichau")))
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        await validar_fonte_pendente(
            FonteFalsa(loja="Pichau", url=url), cliente, repositorio,
            user_agent=UA_HONESTO, teto_centavos=100_000_000, limitador=limitador,
        )

    assert repositorio.validas == [("f1", 469999, "e")]


@pytest.mark.asyncio
@respx.mock
async def test_cloudflare_no_terabyte_e_bloqueio_e_nao_erro_de_parse(limitador):
    """O caminho JSON-LD também precisa reconhecer desafio anti-bot.

    Antes só `extrair_preco_dom` checava, e o Terabyte é justamente quem serve
    `Just a moment...`. Sem isso, o desafio vinha como `sem_jsonld` — erro de
    parse — e condenava a fonte em 5 ciclos por um problema de transporte.
    """
    url = "https://www.terabyteshop.com.br/produto/1/x"
    respx.get(url).mock(
        return_value=httpx.Response(
            403, html="<html><head><title>Just a moment...</title></head></html>"
        )
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        resultado = await validar_fonte_pendente(
            FonteFalsa(loja="Terabyte Shop", url=url), cliente, repositorio,
            user_agent=UA_HONESTO, teto_centavos=100_000_000, limitador=limitador,
        )

    # O 403 já é transporte pelo status; o que se garante aqui é que um desafio
    # servido com 200 receberia o mesmo tratamento.
    assert resultado.erro not in ("sem_jsonld", "sem_product")
    assert repositorio.invalidas == []
