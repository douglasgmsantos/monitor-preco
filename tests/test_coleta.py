"""Fase 3 — coleta. HTTP mockado com respx; o parser roda de verdade."""

from dataclasses import dataclass, field

import httpx
import pytest
import respx

from coletor.coleta import (
    LIMITE_FALHAS_SEGUIDAS,
    LimitadorPorHost,
    avaliar_suspeito,
    buscar_html,
    coletar_fonte,
    coletar_fontes,
    validar_fonte_pendente,
)
from conftest import ler_fixture

URL_A = "https://loja-a.example/produto/1"
URL_B = "https://loja-b.example/produto/2"
LIMIAR = "0.70"
TETO = 100_000_000
UA = "MonitorPrecos/1.0 (uso pessoal)"


# --- dublês ------------------------------------------------------------------


@dataclass
class FonteFalsa:
    id: str = "f1"
    loja: str = "Loja A"
    url: str = URL_A
    falhas_seguidas: int = 0
    ultimo_preco_centavos: int | None = None


@dataclass
class RepositorioFalso:
    leituras: list = field(default_factory=list)
    validas: list = field(default_factory=list)
    invalidas: list = field(default_factory=list)
    com_erro: list = field(default_factory=list)

    def registrar_leitura(self, fonte, resultado, suspeito):
        self.leituras.append((fonte.id, resultado, suspeito))

    def marcar_fonte_valida(self, fonte, preco_centavos, origem):
        self.validas.append((fonte.id, preco_centavos, origem))

    def marcar_fonte_invalida(self, fonte, motivo):
        self.invalidas.append((fonte.id, motivo))

    def marcar_fonte_com_erro(self, fonte):
        self.com_erro.append(fonte.id)


@dataclass
class NotificadorFalso:
    mensagens: list = field(default_factory=list)

    def enviar(self, mensagem):
        self.mensagens.append(mensagem)


class RelogioFalso:
    """Relógio que só anda quando alguém dorme. Nenhum teste espera de verdade."""

    def __init__(self):
        self.agora = 0.0
        self.dormidas = []

    def monotonic(self):
        return self.agora

    async def dormir(self, segundos):
        self.dormidas.append(segundos)
        self.agora += segundos


@pytest.fixture
def relogio():
    return RelogioFalso()


@pytest.fixture
def limitador(relogio):
    return LimitadorPorHost(dormir=relogio.dormir, relogio=relogio.monotonic)


async def _coletar(fonte, repositorio, limitador, relogio, notificador=None):
    async with httpx.AsyncClient() as cliente:
        return await coletar_fonte(
            fonte,
            cliente,
            repositorio,
            user_agent=UA,
            limiar_sanidade=LIMIAR,
            teto_centavos=TETO,
            limitador=limitador,
            notificador=notificador,
            dormir=relogio.dormir,
        )


# --- 1. sucesso --------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sucesso_grava_uma_leitura(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_b_produto.html"))
    )
    repositorio = RepositorioFalso()

    coleta = await _coletar(FonteFalsa(), repositorio, limitador, relogio)

    assert coleta.resultado.preco_centavos == 178999
    assert coleta.suspeito is False
    assert len(repositorio.leituras) == 1
    assert repositorio.validas == [("f1", 178999, "j")]
    assert repositorio.com_erro == []


# --- 2. timeout --------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_timeout_retenta_e_grava_falha(limitador, relogio):
    rota = respx.get(URL_A).mock(side_effect=httpx.TimeoutException("estourou"))
    repositorio = RepositorioFalso()

    coleta = await _coletar(FonteFalsa(), repositorio, limitador, relogio)

    assert rota.call_count == 3  # 1 tentativa + 2 retentativas
    assert coleta.resultado.erro == "timeout"
    assert coleta.resultado.preco_centavos is None
    assert coleta.resultado.disponivel is False
    assert len(repositorio.leituras) == 1
    # backoff exponencial
    assert relogio.dormidas[:2] == [1.0, 2.0]


# --- 3. 404 ------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_404_nao_retenta(limitador, relogio):
    rota = respx.get(URL_A).mock(return_value=httpx.Response(404))
    repositorio = RepositorioFalso()

    coleta = await _coletar(FonteFalsa(), repositorio, limitador, relogio)

    assert rota.call_count == 1
    assert coleta.resultado.erro == "http_404"
    assert len(repositorio.leituras) == 1
    assert repositorio.validas == []


@pytest.mark.asyncio
@respx.mock
async def test_500_retenta(limitador, relogio):
    rota = respx.get(URL_A).mock(return_value=httpx.Response(503))
    repositorio = RepositorioFalso()

    coleta = await _coletar(FonteFalsa(), repositorio, limitador, relogio)

    assert rota.call_count == 3
    assert coleta.resultado.erro == "http_503"


# --- 4. HTML sem JSON-LD -----------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_html_sem_jsonld(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text="<html><body>oi</body></html>")
    )
    repositorio = RepositorioFalso()

    coleta = await _coletar(FonteFalsa(), repositorio, limitador, relogio)

    assert coleta.resultado.erro == "sem_jsonld"
    assert coleta.resultado.preco_centavos is None
    assert len(repositorio.leituras) == 1
    # falha é preço nulo com motivo, nunca zero
    assert repositorio.leituras[0][1].preco_centavos is None


# --- 5. valor suspeito -------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_valor_suspeito_marcado(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_b_produto.html"))
    )
    repositorio = RepositorioFalso()
    # último preço 10x menor que os R$ 1.789,99 da fixture
    fonte = FonteFalsa(ultimo_preco_centavos=17_899)

    coleta = await _coletar(fonte, repositorio, limitador, relogio)

    assert coleta.resultado.preco_centavos == 178999
    assert coleta.suspeito is True
    assert repositorio.leituras[0][2] is True


@pytest.mark.asyncio
@respx.mock
async def test_variacao_pequena_nao_e_suspeita(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_b_produto.html"))
    )
    repositorio = RepositorioFalso()
    fonte = FonteFalsa(ultimo_preco_centavos=180_000)

    coleta = await _coletar(fonte, repositorio, limitador, relogio)

    assert coleta.suspeito is False


@pytest.mark.parametrize(
    "novo, ultimo, esperado",
    [
        (100_00, None, False),  # sem histórico não há como julgar
        (100_00, 0, False),
        (100_00, 100_00, False),
        (170_00, 100_00, False),  # +70% exatos: no limite, não estoura
        (170_01, 100_00, True),  # um centavo além, para cima
        (30_00, 100_00, False),  # -70% exatos: mesmo limite, do outro lado
        (29_99, 100_00, True),  # um centavo além, para baixo
        (31_00, 100_00, False),
    ],
)
def test_guarda_de_sanidade(novo, ultimo, esperado):
    assert avaliar_suspeito(novo, ultimo, LIMIAR) is esperado


# --- 6. quinta falha consecutiva ---------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_quinta_falha_desativa_a_fonte_e_notifica(limitador, relogio):
    respx.get(URL_A).mock(return_value=httpx.Response(404))
    repositorio = RepositorioFalso()
    notificador = NotificadorFalso()
    fonte = FonteFalsa(falhas_seguidas=LIMITE_FALHAS_SEGUIDAS - 1)

    await _coletar(fonte, repositorio, limitador, relogio, notificador)

    assert repositorio.com_erro == ["f1"]
    assert len(notificador.mensagens) == 1
    assert "5 falhas seguidas" in notificador.mensagens[0]


@pytest.mark.asyncio
@respx.mock
async def test_quarta_falha_nao_desativa(limitador, relogio):
    respx.get(URL_A).mock(return_value=httpx.Response(404))
    repositorio = RepositorioFalso()
    notificador = NotificadorFalso()
    fonte = FonteFalsa(falhas_seguidas=LIMITE_FALHAS_SEGUIDAS - 2)

    await _coletar(fonte, repositorio, limitador, relogio, notificador)

    assert repositorio.com_erro == []
    assert notificador.mensagens == []


# --- Limitação de taxa -------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_espaca_requisicoes_ao_mesmo_host(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_b_produto.html"))
    )
    repositorio = RepositorioFalso()

    await _coletar(FonteFalsa(id="f1"), repositorio, limitador, relogio)
    await _coletar(FonteFalsa(id="f2"), repositorio, limitador, relogio)

    assert 2.0 in relogio.dormidas


@pytest.mark.asyncio
@respx.mock
async def test_hosts_diferentes_nao_esperam(limitador, relogio):
    html = ler_fixture("loja_b_produto.html")
    respx.get(URL_A).mock(return_value=httpx.Response(200, text=html))
    respx.get(URL_B).mock(return_value=httpx.Response(200, text=html))
    repositorio = RepositorioFalso()

    await _coletar(FonteFalsa(id="f1", url=URL_A), repositorio, limitador, relogio)
    await _coletar(FonteFalsa(id="f2", url=URL_B), repositorio, limitador, relogio)

    assert relogio.dormidas == []


# --- Ciclo completo ----------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_falha_em_uma_fonte_nao_derruba_as_outras(limitador, relogio):
    respx.get(URL_A).mock(side_effect=httpx.ConnectError("caiu"))
    respx.get(URL_B).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_d_produto.html"))
    )
    repositorio = RepositorioFalso()

    coletas = await coletar_fontes(
        [FonteFalsa(id="f1", url=URL_A), FonteFalsa(id="f2", url=URL_B)],
        repositorio,
        user_agent=UA,
        limiar_sanidade=LIMIAR,
        teto_centavos=TETO,
        limitador=limitador,
        dormir=relogio.dormir,
    )

    assert len(coletas) == 2
    assert len(repositorio.leituras) == 2
    precos = {c.fonte_id: c.resultado.preco_centavos for c in coletas}
    assert precos == {"f1": None, "f2": 999000}


@pytest.mark.asyncio
@respx.mock
async def test_user_agent_configurado_vai_na_requisicao(limitador, relogio):
    rota = respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_d_produto.html"))
    )
    await _coletar(FonteFalsa(), RepositorioFalso(), limitador, relogio)
    assert rota.calls[0].request.headers["user-agent"] == UA


# --- Fila por status (validação de fonte pendente) ---------------------------


@pytest.mark.asyncio
@respx.mock
async def test_fonte_pendente_valida_vira_ok(limitador, relogio):
    respx.get(URL_A).mock(
        return_value=httpx.Response(200, text=ler_fixture("loja_c_produto.html"))
    )
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        resultado = await validar_fonte_pendente(
            FonteFalsa(),
            cliente,
            repositorio,
            user_agent=UA,
            teto_centavos=TETO,
            limitador=limitador,
            dormir=relogio.dormir,
        )

    assert resultado.preco_centavos == 3411764
    assert repositorio.validas == [("f1", 3411764, "j")]
    assert repositorio.invalidas == []


@pytest.mark.asyncio
@respx.mock
async def test_fonte_pendente_impossivel_de_ler_vira_invalida(limitador, relogio):
    respx.get(URL_A).mock(return_value=httpx.Response(200, text="<html></html>"))
    repositorio = RepositorioFalso()

    async with httpx.AsyncClient() as cliente:
        await validar_fonte_pendente(
            FonteFalsa(),
            cliente,
            repositorio,
            user_agent=UA,
            teto_centavos=TETO,
            limitador=limitador,
            dormir=relogio.dormir,
        )

    assert repositorio.invalidas == [("f1", "sem_jsonld")]
    assert repositorio.validas == []


# --- buscar_html isolado -----------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_buscar_html_devolve_erro_ou_html_nunca_os_dois(relogio):
    respx.get(URL_A).mock(return_value=httpx.Response(200, text="<html>ok</html>"))
    async with httpx.AsyncClient() as cliente:
        html, erro = await buscar_html(
            cliente, URL_A, user_agent=UA, dormir=relogio.dormir
        )
    assert erro is None and html == "<html>ok</html>"
