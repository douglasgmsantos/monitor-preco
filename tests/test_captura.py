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

from coletor import captura, coleta, parser
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
def disparos_por_dia() -> int:
    """Quantas vezes o n8n roda por dia, seja qual for a forma do gatilho.

    Conta em disparos/dia em vez de horas porque o gatilho já foi por hora
    (`hoursInterval`) e agora é por cron, e a pergunta que importa é sempre a
    mesma: com que frequência isto bate nas lojas.

    `hoursInterval` some do JSON quando vale 1 — o n8n não exporta o padrão.
    """
    gatilho = next(n for n in _fluxo()["nodes"] if n["type"].endswith("scheduleTrigger"))
    total = 0
    for intervalo in gatilho["parameters"]["rule"]["interval"]:
        campo = intervalo.get("field")
        if campo == "hours":
            total += 24 // intervalo.get("hoursInterval", 1)
        elif campo == "minutes":
            total += (24 * 60) // intervalo.get("minutesInterval", 1)
        elif campo == "cronExpression":
            minuto, hora = intervalo["expression"].split()[:2]
            total += len(minuto.split(",")) * len(hora.split(","))
        else:
            raise AssertionError(f"campo de gatilho não previsto: {intervalo}")
    return total


def horas_entre_capturas() -> float:
    return 24 / disparos_por_dia()


def _nome_do_no_por_tipo(sufixo: str) -> str:
    """Acha um nó pelo TIPO e devolve o nome dele.

    Nunca fixe o nome: o n8n renomeia ao reimportar ("Uma fonte por vez" virou
    "Uma fonte por vez1" e depois voltou), e um teste preso ao nome quebra por
    motivo errado — ou pior, some num `KeyError` que parece bug do workflow.
    """
    achados = [n for n in _fluxo()["nodes"] if n["type"].endswith(sufixo)]
    assert len(achados) == 1, f"esperava 1 nó do tipo {sufixo}, achei {len(achados)}"
    return achados[0]["name"]


def test_workflow_avisa_o_actions_uma_vez_so():
    """O disparo pende da saída `done` do loop, não da saída por item.

    A saída 1 do splitInBatches roda UMA VEZ POR FONTE. Ligar o disparo ali
    renderia 9 chamadas por captura — e como o workflow do coletor usa
    `concurrency: coletor` com `cancel-in-progress: false`, as outras 8 ficariam
    enfileiradas rodando ciclos idênticos. A saída 0 emite uma vez, no fim.
    """
    laco = _fluxo()["connections"][_nome_do_no_por_tipo("splitInBatches")]["main"]
    destinos_done = {s["node"] for s in (laco[0] or [])}
    destinos_loop = {s["node"] for s in (laco[1] or [])}

    assert "Avisar o GitHub Actions" in destinos_done
    assert "Avisar o GitHub Actions" not in destinos_loop


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_disparo_nao_manda_inputs_e_depende_do_default_do_workflow():
    """O corpo é só `{ref}`.

    O input `forcar` é do tipo boolean, e mandar `"true"` (string) pela API do
    GitHub esbarra na validação de tipo. Omitir faz valer o `default: true`
    declarado em coletor.yml — que é justamente o comportamento desejado.
    """
    parametros = _no("Avisar o GitHub Actions")["parameters"]
    assert "inputs" not in parametros["jsonBody"]
    assert "ref" in parametros["jsonBody"]
    assert parametros["method"] == "POST"
    assert parametros["url"].endswith("/actions/workflows/coletor.yml/dispatches")


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_o_default_do_forcar_existe_e_e_verdadeiro():
    """Amarra o JSON do n8n ao YAML do Actions.

    O teste acima só faz sentido se o default existir mesmo. Se alguém trocar
    `default: true` no workflow, a chamada do n8n passaria a rodar SEM forçar e
    a coleta ficaria esperando a janela de 30 min — em silêncio, sem erro.
    """
    yaml = pytest.importorskip("yaml")
    caminho = Path(__file__).resolve().parent.parent / ".github/workflows/coletor.yml"
    gatilhos = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    # YAML 1.1 lê a chave `on` como booleano True.
    entradas = (gatilhos.get("on") or gatilhos.get(True))["workflow_dispatch"]["inputs"]
    assert entradas["forcar"]["default"] is True


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_nenhum_segredo_versionado_no_workflow():
    """O repositório é PÚBLICO. Token no JSON é vazamento, não configuração.

    O PAT mora numa credencial 'Header Auth' do n8n, que fica no n8n. Este teste
    é o que impede um export descuidado de publicar o token junto.
    """
    texto = WORKFLOW.read_text(encoding="utf-8")
    for marca in ("ghp_", "github_pat_", "-----BEGIN", "AAAAB3Nza"):
        assert marca not in texto, f"possível segredo versionado: {marca}"


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_workflow_captura_com_folga_antes_de_vencer():
    """A cadência do n8n precisa ser menor que a validade da captura, senão ela
    vence antes de o coletor ler e o sistema não coleta nunca."""
    assert horas_entre_capturas() < captura.HORAS_DE_VALIDADE_PADRAO


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_cada_captura_dispara_uma_coleta_forcada():
    """Cadência da captura = cadência dos disparos forçados.

    Cada execução do n8n termina chamando o `workflow_dispatch`, e disparo
    forçado NÃO grava `sistema/controle` — logo não deduplica: são coletas reais
    somadas às agendadas, cada uma batendo em todas as fontes ativas.

    O teto existe porque foi assim que a Terabyte bloqueou o IP do n8n: a
    cadência subiu de 3h para 1h e as capturas viraram desafio do Cloudflare.
    """
    assert disparos_por_dia() <= 24, (
        f"{disparos_por_dia()} coletas forçadas por dia — a captura ficou "
        "frequente demais para disparar coleta a cada execução"
    )


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_gatilho_por_minuto_nao_passa_de_59():
    """A armadilha do campo "Minutes" do n8n.

    Ele vira o cron `*/N * * * *`, e o campo de minutos do cron só vai até 59.
    Com N=90 a expressão é ACEITA e resolve como de hora em hora — sem erro,
    sem aviso (medido em 2026-08-15). Intervalo acima de 1h precisa ser cron.
    """
    gatilho = next(n for n in _fluxo()["nodes"] if n["type"].endswith("scheduleTrigger"))
    for intervalo in gatilho["parameters"]["rule"]["interval"]:
        if intervalo.get("field") == "minutes":
            assert intervalo.get("minutesInterval", 1) <= 59, (
                "intervalo em minutos acima de 59 vira `*/N` inválido e o n8n "
                "silenciosamente dispara de hora em hora — use cronExpression"
            )


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_marcas_de_bloqueio_do_n8n_batem_com_as_do_parser():
    """A lista de bloqueio existe nos dois lados e precisa continuar igual.

    O n8n recusa a captura na origem (não sobrescreve a boa por uma página de
    desafio); o parser recusa na leitura. Se as listas divergirem, uma página
    passa por um e é barrada pelo outro — e a que passa vira `sem_jsonld`, que
    é erro de PARSE e condena a fonte em 5 ciclos por problema de transporte.
    """
    codigo = _no("Comprimir")["parameters"]["jsCode"]
    trecho = codigo.split("MARCAS_DE_BLOQUEIO = [", 1)[1].split("]", 1)[0]
    no_n8n = {
        linha.strip().strip(",").strip("'\"")
        for linha in trecho.splitlines()
        if linha.strip() and not linha.strip().startswith("//")
    }
    assert no_n8n == set(parser.MARCAS_DE_BLOQUEIO), (
        f"só no n8n: {no_n8n - set(parser.MARCAS_DE_BLOQUEIO)}\n"
        f"só no parser: {set(parser.MARCAS_DE_BLOQUEIO) - no_n8n}"
    )


@pytest.mark.skipif(WORKFLOW is None, reason="workflow do n8n ausente")
def test_piso_de_tamanho_recusa_o_desafio_do_cloudflare():
    """1 KB com `<html lang="en-US">` é desafio, não produto.

    Em 15/08 as três capturas da Terabyte vieram assim, passaram pelo piso
    antigo de 500 chars e foram gravadas como conteúdo — o coletor gastou 4
    falhas seguidas em cada fonte. Na quinta, a fonte é desativada.
    """
    codigo = _no("Comprimir")["parameters"]["jsCode"]
    piso = int(codigo.split("MINIMO_DE_PAGINA_REAL = ", 1)[1].split(";", 1)[0])
    # Acima do 1 KB que chegou, e MUITO abaixo da menor página real medida
    # (Terabyte, 196 KB) — o piso não pode encostar em página legítima.
    assert 1024 < piso < 100_000


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
