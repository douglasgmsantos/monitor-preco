"""Raspagem de catálogo. HTTP mockado com respx; o parser roda de verdade.

Arquivo fora da lista da seção 3 — que é anterior a esta funcionalidade.
"""

from dataclasses import dataclass, field

import httpx
import pytest
import respx

from coletor.coleta import LimitadorPorHost
from coletor.raspagem import (
    Categoria, raspar, raspar_categoria, total_declarado, url_da_pagina,
)
from conftest import ler_fixture

URL_CATEGORIA = "https://loja.example/hardware/placa-de-video"
UA = "MonitorPrecos/1.0 (uso pessoal)"
TETO = 100_000_000


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


@dataclass
class RepositorioFalso:
    salvos: list = field(default_factory=list)

    def salvar_catalogo(self, loja, categoria, itens, agora=None):
        self.salvos.append((loja, categoria, list(itens)))
        return {"novos": len(itens), "alterados": 0, "inalterados": 0, "sem_sku": 0}


def pagina_com(*skus: str) -> str:
    """Página de listagem sintética, no formato que a KaBuM publica."""
    itens = ",".join(
        f'{{"@type":"Product","sku":"{sku}","name":"Item {sku}",'
        f'"offers":{{"@type":"Offer","url":"https://loja.example/produto/{sku}/x",'
        f'"price":"10,00","priceCurrency":"BRL"}}}}'
        for sku in skus
    )
    return (
        '<html><head><script type="application/ld+json">'
        f"[{itens}]"
        "</script></head><body></body></html>"
    )


# --- montagem de URL ---------------------------------------------------------


@pytest.mark.parametrize(
    "url, pagina, esperado",
    [
        (URL_CATEGORIA, 1, URL_CATEGORIA),
        (URL_CATEGORIA, 2, URL_CATEGORIA + "?page_number=2"),
        (URL_CATEGORIA + "?str=placa", 3, URL_CATEGORIA + "?str=placa&page_number=3"),
        # não duplica o parâmetro se ele já veio na URL
        (URL_CATEGORIA + "?page_number=9", 2, URL_CATEGORIA + "?page_number=2"),
    ],
)
def test_url_da_pagina(url, pagina, esperado):
    assert url_da_pagina(url, pagina) == esperado


def test_categoria_derivada_da_url():
    c = Categoria.da_url("https://www.kabum.com.br/hardware/placa-de-video-vga")
    assert c.loja == "kabum.com.br"
    assert c.nome == "placa-de-video-vga"


# --- varredura ---------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_percorre_paginas_ate_parar_de_aparecer_sku_novo(limitador):
    # respx casa URL sem query com QUALQUER query: as rotas específicas
    # precisam vir antes da genérica, senão a página 1 responde por todas.
    respx.get(URL_CATEGORIA, params={"page_number": "2"}).mock(
        return_value=httpx.Response(200, text=pagina_com("3", "4"))
    )
    # a loja devolve a última página de novo em vez de 404
    respx.get(URL_CATEGORIA, params={"page_number": "3"}).mock(
        return_value=httpx.Response(200, text=pagina_com("3", "4"))
    )
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text=pagina_com("1", "2"))
    )

    async with httpx.AsyncClient() as cliente:
        itens = await raspar_categoria(
            Categoria.da_url(URL_CATEGORIA), cliente,
            user_agent=UA, teto_centavos=TETO, limitador=limitador,
        )

    assert [i.sku for i in itens] == ["1", "2", "3", "4"]


@pytest.mark.asyncio
@respx.mock
async def test_para_na_primeira_pagina_vazia(limitador):
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text="<html><body>nada</body></html>")
    )
    async with httpx.AsyncClient() as cliente:
        itens = await raspar_categoria(
            Categoria.da_url(URL_CATEGORIA), cliente,
            user_agent=UA, teto_centavos=TETO, limitador=limitador,
        )
    assert itens == []


@pytest.mark.asyncio
@respx.mock
async def test_erro_http_interrompe_sem_perder_o_que_ja_veio(limitador):
    respx.get(URL_CATEGORIA, params={"page_number": "2"}).mock(
        return_value=httpx.Response(403)
    )
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text=pagina_com("1", "2"))
    )

    async with httpx.AsyncClient() as cliente:
        itens = await raspar_categoria(
            Categoria.da_url(URL_CATEGORIA), cliente,
            user_agent=UA, teto_centavos=TETO, limitador=limitador,
        )

    assert [i.sku for i in itens] == ["1", "2"]


@pytest.mark.asyncio
@respx.mock
async def test_respeita_o_teto_de_paginas(limitador):
    # toda página traz SKUs novos: sem o teto, isso seria um laço infinito
    contador = {"n": 0}

    def responder(request):
        contador["n"] += 1
        return httpx.Response(200, text=pagina_com(f"s{contador['n']}"))

    respx.get(url__startswith=URL_CATEGORIA).mock(side_effect=responder)

    async with httpx.AsyncClient() as cliente:
        itens = await raspar_categoria(
            Categoria.da_url(URL_CATEGORIA), cliente,
            user_agent=UA, teto_centavos=TETO, limitador=limitador,
            paginas_maximas=5,
        )

    assert len(itens) == 5


@pytest.mark.asyncio
@respx.mock
async def test_fixture_real_da_kabum_alimenta_o_catalogo(limitador):
    """A listagem real capturada tem 10 itens; a página 2 repete e encerra."""
    respx.get(URL_CATEGORIA, params={"page_number": "2"}).mock(
        return_value=httpx.Response(200, text=ler_fixture("listagem_a.html"))
    )
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text=ler_fixture("listagem_a.html"))
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        total = await raspar(
            [Categoria.da_url(URL_CATEGORIA)], repositorio,
            user_agent=UA, teto_centavos=TETO, cliente=cliente, limitador=limitador,
        )

    assert total["itens"] == 10
    (loja, categoria, itens), = repositorio.salvos
    assert loja == "loja.example"
    assert categoria == "placa-de-video"
    assert len({i.sku for i in itens}) == 10
    assert all(i.preco_centavos and i.url for i in itens)
    # listagem não informa estoque
    assert all(i.disponivel is None for i in itens)


@pytest.mark.asyncio
@respx.mock
async def test_categoria_que_falha_nao_derruba_as_outras(limitador):
    outra = "https://loja.example/hardware/processador"
    respx.get(URL_CATEGORIA).mock(side_effect=httpx.ConnectError("caiu"))
    respx.get(outra, params={"page_number": "2"}).mock(
        return_value=httpx.Response(200, text=pagina_com("9"))
    )
    respx.get(outra).mock(return_value=httpx.Response(200, text=pagina_com("9")))
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        total = await raspar(
            [Categoria.da_url(URL_CATEGORIA), Categoria.da_url(outra)],
            repositorio, user_agent=UA, teto_centavos=TETO,
            cliente=cliente, limitador=limitador,
        )

    assert total["categorias"] == 1
    assert total["itens"] == 1


# --- aviso de truncamento ----------------------------------------------------


def pagina_com_total(total, *skus):
    """Página que declara ter `total` produtos mas rende só os `skus`."""
    return pagina_com(*skus).replace(
        "<body>", f'<body><script>var estado = {{"total":{total}}};</script>'
    )


@pytest.mark.parametrize(
    "html, esperado",
    [
        ('{"total":426}', 426),
        ('{"total": 152 }', 152),
        ('{"outro":1}', None),
        ("", None),
        ('{"total":"abc"}', None),
    ],
)
def test_total_declarado(html, esperado):
    assert total_declarado(html) == esperado


@pytest.mark.asyncio
@respx.mock
async def test_avisa_quando_a_pagina_rende_menos_do_que_declara(limitador, caplog):
    """/gabinetes declarava 1274 e renderizava 25 — 2%."""
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text=pagina_com_total(1274, "1", "2"))
    )
    async with httpx.AsyncClient() as cliente:
        with caplog.at_level("WARNING"):
            await raspar_categoria(
                Categoria.da_url(URL_CATEGORIA), cliente,
                user_agent=UA, teto_centavos=TETO, limitador=limitador,
            )

    assert any("TRUNCADA" in m for m in caplog.messages)


@pytest.mark.asyncio
@respx.mock
async def test_nao_avisa_quando_a_pagina_rende_o_que_declara(limitador, caplog):
    respx.get(URL_CATEGORIA, params={"page_number": "2"}).mock(
        return_value=httpx.Response(200, text=pagina_com_total(2, "1", "2"))
    )
    respx.get(URL_CATEGORIA).mock(
        return_value=httpx.Response(200, text=pagina_com_total(2, "1", "2"))
    )
    async with httpx.AsyncClient() as cliente:
        with caplog.at_level("WARNING"):
            await raspar_categoria(
                Categoria.da_url(URL_CATEGORIA), cliente,
                user_agent=UA, teto_centavos=TETO, limitador=limitador,
            )

    assert not any("TRUNCADA" in m for m in caplog.messages)


# --- histórico de preço do catálogo ------------------------------------------
#
# Guardado DENTRO do item da vitrine, em janela rolante de 7 dias. O documento
# da categoria já está em 38% do teto de 1 MiB com 856 itens; série infinita ali
# estouraria e derrubaria a categoria inteira. Ver DIAS_DE_HISTORICO_DO_CATALOGO.

from datetime import datetime, timedelta, timezone
from coletor.repositorio import (
    DIAS_DE_HISTORICO_DO_CATALOGO, chave_dia, historico_do_item,
)

QUANDO = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)


def test_primeiro_dia_abre_historico_e_minima():
    r = historico_do_item(None, 129_999, QUANDO)
    assert r["h"] == {chave_dia(QUANDO): 129_999}
    assert r["min"] == 129_999
    assert r["minD"] == chave_dia(QUANDO)


def test_dias_seguintes_acumulam():
    estado = None
    for i, preco in enumerate([130_000, 125_000, 128_000]):
        estado = historico_do_item(estado, preco, QUANDO + timedelta(days=i))
    assert len(estado["h"]) == 3
    assert estado["min"] == 125_000
    assert estado["minD"] == chave_dia(QUANDO + timedelta(days=1))


def test_janela_poda_em_sete_dias():
    estado = None
    for i in range(20):
        estado = historico_do_item(estado, 100_000 + i, QUANDO + timedelta(days=i))
    assert len(estado["h"]) == DIAS_DE_HISTORICO_DO_CATALOGO


def test_minima_sobrevive_a_poda_da_janela():
    """O selo é de menor preço HISTÓRICO, não da semana.

    Podar a mínima junto com a janela faria o recorde de duas semanas atrás
    sumir, e o selo passaria a dizer "menor preço" para o menor dos últimos 7
    dias — que é outra afirmação, e mais fraca.
    """
    estado = historico_do_item(None, 50_000, QUANDO)          # pechincha
    for i in range(1, 15):
        estado = historico_do_item(estado, 130_000, QUANDO + timedelta(days=i))

    assert chave_dia(QUANDO) not in estado["h"]   # saiu da janela
    assert estado["min"] == 50_000                # mas a mínima ficou
    assert estado["minD"] == chave_dia(QUANDO)


def test_esgotado_nao_entra_no_historico():
    """Ausência de preço não é preço baixo.

    Gravar zero afundaria a média da semana e faria o selo de menor preço
    disparar num produto que ninguém pode comprar.
    """
    estado = historico_do_item(None, 130_000, QUANDO)
    depois = historico_do_item(estado, None, QUANDO + timedelta(days=1))

    assert len(depois["h"]) == 1
    assert depois["min"] == 130_000


def test_duas_raspagens_no_mesmo_dia_nao_duplicam():
    """Chave por dia: a segunda leitura substitui, não acrescenta ponto."""
    estado = historico_do_item(None, 130_000, QUANDO)
    estado = historico_do_item(estado, 128_000, QUANDO.replace(hour=23))

    assert estado["h"] == {chave_dia(QUANDO): 128_000}
    assert estado["min"] == 128_000


def test_item_sem_preco_nenhum_nunca_ganha_minima():
    r = historico_do_item(None, None, QUANDO)
    assert r["h"] == {}
    assert "min" not in r


def test_espaco_por_item_cabe_no_orcamento():
    """O documento maior tem 856 itens e 384 KB (38% do teto de 1 MiB).

    Este teste é o que impede alguém de aumentar a janela sem fazer a conta: com
    ~175 bytes por item o pior documento vai a ~51%; dobrar a janela o levaria
    a perto do limite, e estourar derruba a CATEGORIA INTEIRA.
    """
    import json
    estado = None
    for i in range(DIAS_DE_HISTORICO_DO_CATALOGO):
        estado = historico_do_item(estado, 1_299_999, QUANDO + timedelta(days=i))

    bytes_por_item = len(json.dumps(estado).encode())
    assert bytes_por_item < 220, f"{bytes_por_item} bytes por item — refaça a conta"
    assert 856 * bytes_por_item < 200_000   # < 200 KB somados ao documento
