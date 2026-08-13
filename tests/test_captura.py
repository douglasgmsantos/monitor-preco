"""HTML capturado por fora (n8n) e entregue pelo Firestore.

O que se protege aqui não é o codec — gzip e base64 não quebram. É o conjunto de
modos de falha em que o coletor gravaria preço errado ACHANDO que está certo:
captura velha, captura de outra URL, captura escapada.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from coletor import captura, coleta
from coletor.parser import ERROS_DE_PARSE

AGORA = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
HTML = '<html><head><title>Produto</title></head><body>R$ 10,00</body></html>'
URL = "https://www.terabyteshop.com.br/produto/1/x"


# ---------------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------------


def test_ida_e_volta():
    assert captura.descompactar(captura.compactar(HTML)) == HTML


def test_comprime_de_verdade():
    """Se não comprimisse, a Amazon (1,2 MB) não caberia no documento."""
    grande = HTML * 3000
    compactado = captura.compactar(grande)
    assert len(compactado) < len(grande) / 5


def test_documento_tem_o_formato_que_o_n8n_precisa_produzir():
    doc = captura.documento(HTML, URL, agora=AGORA)
    assert set(doc) == {"url", "html", "bytes", "codificacao", "capturadoEm"}
    assert doc["codificacao"] == "gzip+base64"
    assert doc["bytes"] == len(HTML.encode("utf-8"))
    assert captura.descompactar(doc["html"]) == HTML


def test_texto_cru_e_aceito_quando_declarado():
    assert captura.descompactar(HTML, "texto") == HTML


@pytest.mark.parametrize("lixo", ["", "não é base64!!", "YWJj"])   # YWJj = "abc"
def test_conteudo_invalido_devolve_none(lixo):
    assert captura.descompactar(lixo) is None


# ---------------------------------------------------------------------------
# Aspas escapadas — o erro mais provável da integração
# ---------------------------------------------------------------------------


def test_reconhece_html_escapado():
    escapado = '<!DOCTYPE html>\\n<html lang=\\"pt-br\\">\\n<body class=\\"x\\">'
    assert captura.parece_html_escapado(escapado)


def test_html_limpo_nao_e_confundido():
    assert not captura.parece_html_escapado(
        '<!DOCTYPE html><html lang="pt-br"><body class="x"></body></html>'
    )


def test_javascript_com_string_dentro_de_string_nao_e_confundido():
    """Página real tem escape legítimo em JS. Medido em 2026-08-13: o pior caso
    limpo deu razão 0,007, contra 1,00 do capturado escapado."""
    legitimo = '<html lang="pt"><script>var a = "{\\"k\\":1}";</script>' + '<div class="x"></div>' * 200
    assert not captura.parece_html_escapado(legitimo)


def test_captura_escapada_vira_erro_proprio():
    doc = captura.documento('<html lang=\\"pt\\"><body class=\\"a\\">', URL, agora=AGORA)
    achada, erro = captura.ler(doc, agora=AGORA)
    assert achada is None
    assert erro == captura.ERRO_CAPTURA_ESCAPADA


# ---------------------------------------------------------------------------
# Leitura e validação
# ---------------------------------------------------------------------------


def test_captura_fresca_e_lida():
    doc = captura.documento(HTML, URL, agora=AGORA)
    achada, erro = captura.ler(doc, url_esperada=URL, agora=AGORA)
    assert erro is None
    assert achada.html == HTML
    assert achada.bytes_brutos == len(HTML.encode("utf-8"))


def test_sem_documento():
    assert captura.ler(None)[1] == captura.ERRO_SEM_CAPTURA


def test_captura_velha_e_recusada():
    """A armadilha central: sem isto, o n8n parar significaria gravar o mesmo
    preço para sempre como se fosse leitura nova."""
    doc = captura.documento(HTML, URL, agora=AGORA - timedelta(hours=7))
    achada, erro = captura.ler(doc, agora=AGORA, horas_de_validade=6)
    assert achada is None
    assert erro == captura.ERRO_CAPTURA_VENCIDA


def test_captura_no_limite_da_validade_ainda_serve():
    doc = captura.documento(HTML, URL, agora=AGORA - timedelta(hours=5, minutes=59))
    assert captura.ler(doc, agora=AGORA, horas_de_validade=6)[1] is None


def test_sem_carimbo_de_tempo_conta_como_vencida():
    """Benefício da dúvida aqui gravaria preço de ontem como o de agora."""
    doc = captura.documento(HTML, URL, agora=AGORA)
    del doc["capturadoEm"]
    assert captura.ler(doc, agora=AGORA)[1] == captura.ERRO_CAPTURA_VENCIDA


def test_captura_de_outra_url_e_recusada():
    """Fonte editada e n8n ainda não atualizou: usar a captura antiga gravaria o
    preço do produto ERRADO no histórico do produto certo."""
    doc = captura.documento(HTML, "https://www.terabyteshop.com.br/produto/999/outro",
                            agora=AGORA)
    achada, erro = captura.ler(doc, url_esperada=URL, agora=AGORA)
    assert achada is None
    assert erro == captura.ERRO_CAPTURA_DE_OUTRA_URL


def test_html_corrompido_vira_ilegivel():
    doc = captura.documento(HTML, URL, agora=AGORA)
    doc["html"] = "isto não é gzip"
    assert captura.ler(doc, agora=AGORA)[1] == captura.ERRO_CAPTURA_ILEGIVEL


# ---------------------------------------------------------------------------
# Classificação: nenhum erro de captura pode condenar a fonte
# ---------------------------------------------------------------------------


def test_nenhum_erro_de_captura_e_erro_de_parse():
    """São todos de TRANSPORTE: a URL está boa, quem falhou foi o mensageiro.

    Se algum entrasse em ERROS_DE_PARSE, um n8n fora do ar por meio dia marcaria
    todas as fontes como inválidas — e o usuário veria "URL não legível" para
    URLs perfeitas.
    """
    assert not (captura.ERROS_DE_CAPTURA & ERROS_DE_PARSE)


# ---------------------------------------------------------------------------
# O contrato com o n8n
# ---------------------------------------------------------------------------

def _achar_workflow() -> Path | None:
    """O arquivo do n8n, com o nome que ele exportar.

    O n8n exporta usando o NOME do workflow, com acento e travessão, e é natural
    que o arquivo do repositório passe a ser esse export. Procurar por padrão em
    vez de fixar o nome evita que os testes virem `skip` silencioso quando isso
    acontece — que foi o que aconteceu em 2026-08-13.
    """
    pasta = Path(__file__).resolve().parent.parent / "n8n"
    achados = sorted(pasta.glob("*.json")) if pasta.is_dir() else []
    return achados[0] if achados else None


WORKFLOW = _achar_workflow()


def _fluxo() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def _no(prefixo: str) -> dict:
    """Acha o nó pelo começo do nome: ao reimportar, o n8n acrescenta um sufixo
    numérico (`Comprimir` vira `Comprimir1`)."""
    for no in _fluxo()["nodes"]:
        if no["name"].startswith(prefixo):
            return no
    pytest.fail(f"nó começando com {prefixo!r} não existe em {WORKFLOW.name}")


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_workflow_escreve_os_mesmos_campos_que_o_coletor_le():
    """Amarra os dois lados do contrato.

    O n8n monta o documento em JavaScript e o coletor lê em Python. Nada no
    sistema conecta os dois — se alguém renomear um campo de um lado, o outro só
    descobre em produção, e o sintoma é `sem_captura` num n8n que está rodando
    perfeitamente. Este teste é a costura.
    """
    codigo = _no("Comprimir")["parameters"]["jsCode"]
    for campo in captura.documento(HTML, URL, agora=AGORA):
        assert f"{campo}:" in codigo, (
            f"o campo {campo!r} existe em captura.documento() mas não aparece no "
            f"nó 'Comprimir' de {WORKFLOW.name}"
        )


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_workflow_pede_resposta_em_texto():
    """`responseFormat: text` é o que impede o HTML de voltar escapado — o erro
    que já custou uma captura inteira. Se sumir, a captura vira lixo silencioso."""
    resposta = _no("Buscar a página")["parameters"]["options"]["response"]["response"]
    assert resposta["responseFormat"] == "text"


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_workflow_usa_service_account_e_nao_oauth2():
    """OAuth2 exige tela de consentimento e client no Google Cloud — trabalho à
    toa para máquina falando com máquina, e o n8n só mostra Client ID/Secret
    sem explicar por quê. A credencial certa é a de service account."""
    tipos = {
        no["parameters"]["nodeCredentialType"]
        for no in _fluxo()["nodes"]
        if "nodeCredentialType" in no.get("parameters", {})
    }
    assert tipos == {"googleApi"}, f"esperava só googleApi, veio {tipos}"


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_workflow_captura_com_folga_antes_de_vencer():
    """A cadência do n8n precisa ser menor que a validade da captura, senão ela
    vence antes de o coletor ler e o sistema não coleta nunca."""
    gatilho = next(n for n in _fluxo()["nodes"] if n["type"].endswith("scheduleTrigger"))
    horas = gatilho["parameters"]["rule"]["interval"][0]["hoursInterval"]
    assert horas < captura.HORAS_DE_VALIDADE_PADRAO


# ---------------------------------------------------------------------------
# Ponta a ponta: a coleta usando o caminho capturado
# ---------------------------------------------------------------------------

PAGINA = """
<html><head>
<script type="application/ld+json">
{"@context":"http://schema.org","@type":"Product","name":"Placa",
 "offers":{"@type":"Offer","price":"4599.90","priceCurrency":"BRL",
           "availability":"https://schema.org/InStock"}}
</script>
</head><body></body></html>
"""


@dataclass
class FonteFalsa:
    id: str = "f1"
    loja: str = "Terabyte Shop"
    url: str = URL
    falhas_seguidas: int = 0
    ultimo_preco_centavos: int | None = None


@dataclass
class RepositorioFalso:
    pagina: dict | None = None
    leituras: list = field(default_factory=list)
    invalidas: list = field(default_factory=list)
    com_erro: list = field(default_factory=list)

    def ler_pagina_capturada(self, fonte_id):
        return self.pagina

    def registrar_leitura(self, fonte, resultado, suspeito):
        self.leituras.append((fonte.id, resultado, suspeito))

    def marcar_fonte_valida(self, fonte, preco_centavos, origem): ...
    def marcar_fonte_invalida(self, fonte, motivo):
        self.invalidas.append((fonte.id, motivo))
    def registrar_tentativa_de_validacao(self, fonte, motivo): ...
    def marcar_fonte_com_erro(self, fonte):
        self.com_erro.append(fonte.id)


@pytest.fixture
def terabyte_capturada(monkeypatch):
    """Comuta o Terabyte para busca capturada, sem tocar no registro real."""
    from coletor import lojas
    monkeypatch.setattr(
        lojas, "busca_de",
        lambda url: "capturada" if "terabyteshop" in url else "direta",
    )
    monkeypatch.setattr(
        coleta, "busca_de",
        lambda url: "capturada" if "terabyteshop" in url else "direta",
    )


@pytest.mark.asyncio
@respx.mock
async def test_coleta_le_do_firestore_e_nao_faz_requisicao(terabyte_capturada):
    """A prova de que o caminho novo funciona: preço extraído, zero HTTP."""
    rota = respx.get(URL)
    repositorio = RepositorioFalso(pagina=captura.documento(PAGINA, URL))

    async with httpx.AsyncClient() as cliente:
        resultado = await coleta.coletar_fonte(
            FonteFalsa(), cliente, repositorio,
            user_agent="MonitorPrecos/1.0", limiar_sanidade="0.70",
            teto_centavos=100_000_000, limitador=coleta.LimitadorPorHost(),
        )

    assert resultado.resultado.preco_centavos == 459990
    assert resultado.resultado.origem == "j"
    assert not rota.called          # não tocou na loja


@pytest.mark.asyncio
@respx.mock
async def test_captura_vencida_nao_condena_a_fonte(terabyte_capturada):
    """n8n fora do ar não pode marcar URL boa como inválida."""
    velha = captura.documento(
        PAGINA, URL, agora=datetime.now(timezone.utc) - timedelta(days=1))
    repositorio = RepositorioFalso(pagina=velha)

    async with httpx.AsyncClient() as cliente:
        await coleta.validar_fonte_pendente(
            FonteFalsa(), cliente, repositorio,
            user_agent="MonitorPrecos/1.0", teto_centavos=100_000_000,
            limitador=coleta.LimitadorPorHost(),
        )

    assert repositorio.invalidas == []


@pytest.mark.asyncio
@respx.mock
async def test_sem_captura_registra_leitura_com_o_motivo(terabyte_capturada):
    """Falha também vira leitura: o histórico não pode ter buraco silencioso."""
    repositorio = RepositorioFalso(pagina=None)

    async with httpx.AsyncClient() as cliente:
        await coleta.coletar_fonte(
            FonteFalsa(), cliente, repositorio,
            user_agent="MonitorPrecos/1.0", limiar_sanidade="0.70",
            teto_centavos=100_000_000, limitador=coleta.LimitadorPorHost(),
        )

    assert len(repositorio.leituras) == 1
    assert repositorio.leituras[0][1].erro == captura.ERRO_SEM_CAPTURA
