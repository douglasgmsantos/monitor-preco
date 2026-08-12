"""Fase 2 — repositório, contra o EMULADOR do Firestore.

Nenhum teste toca o Firestore de produção: o projeto é `demo-monitor` e o
emulador é apagado antes de cada teste.

Para rodar:
    firebase emulators:start --only firestore --project demo-monitor
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 pytest tests/test_repositorio.py
"""

import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from coletor.parser import ItemDeLista, ResultadoExtracao
from coletor.repositorio import (
    STATUS_INVALIDA,
    STATUS_OK,
    STATUS_PENDENTE,
    Repositorio,
    chave_dia,
    chave_mes,
    inicializar,
)

ENDERECO = os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
PROJETO = "demo-monitor"

URL_DE_LIMPEZA = (
    f"http://{ENDERECO}/emulator/v1/projects/{PROJETO}/databases/(default)/documents"
)


def _emulador_no_ar() -> bool:
    """True só quando quem atende em ENDERECO é REALMENTE o emulador.

    Antes esta função aceitava qualquer resposta em `GET /`, e isso custou uma
    hora de depuração: um `python -m http.server 8080` (o comando documentado
    para servir o front antigo!) fazia o probe passar, os testes deixavam de
    ser pulados, e o cliente do Firestore ficava pendurado em gRPC contra um
    servidor de arquivos — sem erro, sem timeout, sem pista.

    O discriminador é o endpoint de limpeza, que só o emulador implementa: ele
    responde 200, e um servidor HTTP comum responde 501 (verificado em
    2026-08-12). É o mesmo endpoint que `limpar_emulador` usa.
    """
    try:
        return httpx.delete(URL_DE_LIMPEZA, timeout=2.0).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _emulador_no_ar(),
    reason=f"emulador do Firestore não responde em {ENDERECO}",
)


def sucesso(centavos: int, origem: str = "j", disponivel: bool = True):
    return ResultadoExtracao(centavos, "BRL", disponivel, origem, None)


def falha(erro: str = "sem_jsonld"):
    return ResultadoExtracao(None, None, False, None, erro)


# --- infraestrutura ---------------------------------------------------------


@pytest.fixture(scope="session")
def repositorio():
    os.environ["GCLOUD_PROJECT"] = PROJETO
    inicializar(project_id=PROJETO)
    return Repositorio()


@pytest.fixture(autouse=True)
def limpar_emulador():
    httpx.delete(URL_DE_LIMPEZA, timeout=10.0)
    yield


@pytest.fixture
def cenario(repositorio):
    """Cria usuário, produto e fonte, e devolve a fonte carregada."""

    def criar(
        uid="u1",
        produto_id="p1",
        fonte_id="f1",
        status=STATUS_OK,
        com_erro=False,
        produto_ativo=True,
        falhas_seguidas=0,
        ultimo_preco_centavos=None,
    ):
        db = repositorio._db
        produto_ref = (
            db.collection("usuarios").document(uid).collection("produtos").document(produto_id)
        )
        produto_ref.set(
            {
                "nome": "Produto de teste",
                "precoAlvoCentavos": 100_000,
                "toleranciaPct": 10,
                "precoGatilhoCentavos": 110_000,
                "estado": "ACIMA",
                "ultimoAlertaEm": None,
                "ultimoPrecoAlertadoCentavos": None,
                "ativo": produto_ativo,
            }
        )
        fonte_ref = produto_ref.collection("fontes").document(fonte_id)
        fonte_ref.set(
            {
                "loja": "Loja Teste",
                "url": f"https://loja.example/{fonte_id}",
                "status": status,
                "motivoInvalida": None,
                "falhasSeguidas": falhas_seguidas,
                "comErro": com_erro,
                "ultimoPrecoCentavos": ultimo_preco_centavos,
                "ultimaColetaEm": None,
            }
        )
        return repositorio._fonte_de_snapshot(fonte_ref.get())

    return criar


def ler_historico(repositorio, fonte, instante):
    doc = (
        fonte.produto_ref.collection("historico")
        .document(f"{fonte.id}_{chave_mes(instante)}")
        .get()
    )
    return doc.to_dict() if doc.exists else None


def ler_diario(repositorio, fonte, ano):
    doc = fonte.produto_ref.collection("diario").document(f"{fonte.id}_{ano}").get()
    return doc.to_dict() if doc.exists else None


# --- bucket novo e append ---------------------------------------------------


def test_cria_bucket_novo(repositorio, cenario):
    fonte = cenario()
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(178_999), False, agora=quando)

    hist = ler_historico(repositorio, fonte, quando)
    assert hist["fonteId"] == "f1"
    assert hist["mes"] == "2026-08"
    assert len(hist["leituras"]) == 1
    entrada = hist["leituras"][0]
    assert entrada["p"] == 178_999
    assert entrada["d"] is True
    assert entrada["s"] is False
    assert entrada["o"] == "j"


def test_append_em_bucket_existente(repositorio, cenario):
    fonte = cenario()
    base = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(178_999), False, agora=base)
    repositorio.registrar_leitura(
        fonte, sucesso(175_000), False, agora=base + timedelta(hours=6)
    )

    hist = ler_historico(repositorio, fonte, base)
    assert len(hist["leituras"]) == 2
    assert {e["p"] for e in hist["leituras"]} == {178_999, 175_000}


def test_virada_de_mes_cria_bucket_separado(repositorio, cenario):
    fonte = cenario()
    julho = datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)
    agosto = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(100_000), False, agora=julho)
    repositorio.registrar_leitura(fonte, sucesso(101_000), False, agora=agosto)

    assert len(ler_historico(repositorio, fonte, julho)["leituras"]) == 1
    assert len(ler_historico(repositorio, fonte, agosto)["leituras"]) == 1
    assert ler_historico(repositorio, fonte, julho)["mes"] == "2026-07"
    assert ler_historico(repositorio, fonte, agosto)["mes"] == "2026-08"


def test_virada_de_ano_cria_rollup_separado(repositorio, cenario):
    fonte = cenario()
    dezembro = datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)
    janeiro = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(100_000), False, agora=dezembro)
    repositorio.registrar_leitura(fonte, sucesso(90_000), False, agora=janeiro)

    d2025 = ler_diario(repositorio, fonte, "2025")
    d2026 = ler_diario(repositorio, fonte, "2026")
    assert d2025["ano"] == 2025
    assert d2026["ano"] == 2026
    assert chave_dia(dezembro) in d2025["dias"]
    assert chave_dia(janeiro) in d2026["dias"]
    assert chave_dia(janeiro) not in d2025["dias"]


# --- rollup diário ----------------------------------------------------------


def test_rollup_recalcula_min_max_soma_n_e_fechamento(repositorio, cenario):
    fonte = cenario()
    dia = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)

    for hora, preco in ((6, 120_000), (12, 100_000), (18, 110_000)):
        repositorio.registrar_leitura(
            fonte, sucesso(preco), False, agora=dia.replace(hour=hora)
        )

    valores = ler_diario(repositorio, fonte, "2026")["dias"][chave_dia(dia)]
    assert valores["min"] == 100_000
    assert valores["max"] == 120_000
    assert valores["soma"] == 330_000
    assert valores["n"] == 3
    assert valores["fech"] == 110_000  # última coleta do dia
    # média incremental sem perder precisão
    assert valores["soma"] // valores["n"] == 110_000


def test_dias_diferentes_nao_se_misturam(repositorio, cenario):
    fonte = cenario()
    dia1 = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    dia2 = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(100_000), False, agora=dia1)
    repositorio.registrar_leitura(fonte, sucesso(200_000), False, agora=dia2)

    dias = ler_diario(repositorio, fonte, "2026")["dias"]
    assert dias[chave_dia(dia1)]["n"] == 1
    assert dias[chave_dia(dia2)]["n"] == 1
    assert dias[chave_dia(dia1)]["fech"] == 100_000
    assert dias[chave_dia(dia2)]["fech"] == 200_000


def test_chave_do_dia_nao_tem_hifen(repositorio, cenario):
    fonte = cenario()
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    repositorio.registrar_leitura(fonte, sucesso(100_000), False, agora=quando)

    (chave,) = ler_diario(repositorio, fonte, "2026")["dias"].keys()
    assert chave == "d20260810"
    assert "-" not in chave
    assert not chave[0].isdigit()


# --- leitura inválida e suspeita não poluem o rollup ------------------------


def test_falha_entra_no_historico_mas_nao_no_rollup(repositorio, cenario):
    fonte = cenario()
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, falha("timeout"), False, agora=quando)

    hist = ler_historico(repositorio, fonte, quando)
    assert len(hist["leituras"]) == 1
    entrada = hist["leituras"][0]
    assert entrada["p"] is None
    assert entrada["d"] is False
    assert entrada["e"] == "timeout"  # motivo gravado
    assert ler_diario(repositorio, fonte, "2026") is None


def test_leitura_suspeita_entra_no_historico_mas_nao_no_rollup(repositorio, cenario):
    fonte = cenario()
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(10), True, agora=quando)

    hist = ler_historico(repositorio, fonte, quando)
    assert hist["leituras"][0]["s"] is True
    assert ler_diario(repositorio, fonte, "2026") is None


def test_suspeita_nao_contamina_rollup_existente(repositorio, cenario):
    fonte = cenario()
    dia = datetime(2026, 8, 10, 6, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(100_000), False, agora=dia)
    repositorio.registrar_leitura(
        fonte, sucesso(1), True, agora=dia.replace(hour=12)
    )

    valores = ler_diario(repositorio, fonte, "2026")["dias"][chave_dia(dia)]
    assert valores["n"] == 1
    assert valores["min"] == 100_000
    assert valores["fech"] == 100_000


def test_nunca_grava_preco_zero_na_falha(repositorio, cenario):
    fonte = cenario()
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
    repositorio.registrar_leitura(fonte, falha("preco_invalido"), False, agora=quando)

    assert ler_historico(repositorio, fonte, quando)["leituras"][0]["p"] is None


# --- contador de falhas -----------------------------------------------------


def test_falha_incrementa_contador(repositorio, cenario):
    fonte = cenario(falhas_seguidas=2)
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, falha(), False, agora=quando)

    assert fonte.ref.get().to_dict()["falhasSeguidas"] == 3


def test_sucesso_zera_contador_e_grava_preco(repositorio, cenario):
    fonte = cenario(falhas_seguidas=4)
    quando = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

    repositorio.registrar_leitura(fonte, sucesso(178_999), False, agora=quando)

    dados = fonte.ref.get().to_dict()
    assert dados["falhasSeguidas"] == 0
    assert dados["ultimoPrecoCentavos"] == 178_999
    assert isinstance(dados["ultimoPrecoCentavos"], int)  # nunca float
    assert dados["ultimaColetaEm"] is not None


# --- consultas de fonte -----------------------------------------------------


def test_listar_fontes_pendentes(repositorio, cenario):
    cenario(fonte_id="pendente1", status=STATUS_PENDENTE)
    cenario(fonte_id="ok1", status=STATUS_OK)

    pendentes = repositorio.listar_fontes_pendentes()

    assert [f.id for f in pendentes] == ["pendente1"]


def test_listar_fontes_ativas_filtra_erro_e_produto_inativo(repositorio, cenario):
    cenario(produto_id="pA", fonte_id="boa", status=STATUS_OK)
    cenario(produto_id="pA", fonte_id="comErro", status=STATUS_OK, com_erro=True)
    cenario(produto_id="pA", fonte_id="pendente", status=STATUS_PENDENTE)
    cenario(produto_id="pB", fonte_id="deInativo", status=STATUS_OK, produto_ativo=False)

    ativas = {f.id for f in repositorio.listar_fontes_ativas()}

    assert ativas == {"boa"}


def test_marcar_fonte_valida_promove_e_grava_preco(repositorio, cenario):
    fonte = cenario(fonte_id="f1", status=STATUS_PENDENTE)

    repositorio.marcar_fonte_valida(fonte, 129_990, "g")

    dados = fonte.ref.get().to_dict()
    assert dados["status"] == STATUS_OK
    assert dados["ultimoPrecoCentavos"] == 129_990
    assert dados["ultimaOrigem"] == "g"
    assert dados["motivoInvalida"] is None


def test_marcar_fonte_invalida_grava_motivo(repositorio, cenario):
    fonte = cenario(fonte_id="f1", status=STATUS_PENDENTE)

    repositorio.marcar_fonte_invalida(fonte, "sem_jsonld")

    dados = fonte.ref.get().to_dict()
    assert dados["status"] == STATUS_INVALIDA
    assert dados["motivoInvalida"] == "sem_jsonld"


def test_marcar_fonte_com_erro(repositorio, cenario):
    fonte = cenario()
    repositorio.marcar_fonte_com_erro(fonte)
    assert fonte.ref.get().to_dict()["comErro"] is True


# --- produto e estado do alerta --------------------------------------------


def test_carregar_produto(repositorio, cenario):
    fonte = cenario()
    produto = repositorio.carregar_produto(fonte.produto_ref)

    assert produto.nome == "Produto de teste"
    assert produto.preco_alvo_centavos == 100_000
    assert produto.preco_gatilho_centavos == 110_000
    assert produto.ativo is True


def test_carregar_produto_inexistente(repositorio, cenario):
    fonte = cenario()
    ausente = fonte.produto_ref.parent.document("nao-existe")
    assert repositorio.carregar_produto(ausente) is None


def test_atualizar_estado_com_notificacao(repositorio, cenario):
    fonte = cenario()
    produto = repositorio.carregar_produto(fonte.produto_ref)
    quando = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    repositorio.atualizar_estado_alerta(produto, "EM_ALERTA", 95_000, quando)

    dados = produto.ref.get().to_dict()
    assert dados["estado"] == "EM_ALERTA"
    assert dados["ultimoPrecoAlertadoCentavos"] == 95_000
    assert dados["ultimoAlertaEm"] is not None


def test_transicao_silenciosa_nao_mexe_no_ultimo_alerta(repositorio, cenario):
    fonte = cenario()
    produto = repositorio.carregar_produto(fonte.produto_ref)

    repositorio.atualizar_estado_alerta(produto, "ACIMA", None, None)

    dados = produto.ref.get().to_dict()
    assert dados["estado"] == "ACIMA"
    assert dados["ultimoAlertaEm"] is None
    assert dados["ultimoPrecoAlertadoCentavos"] is None


def test_corrigir_gatilho_reescreve_valor_do_cliente(repositorio, cenario):
    fonte = cenario()
    produto = repositorio.carregar_produto(fonte.produto_ref)
    produto.ref.update({"precoGatilhoCentavos": 999_999})  # cliente mentiu
    produto = repositorio.carregar_produto(fonte.produto_ref)

    repositorio.corrigir_gatilho(produto, 110_000)

    assert produto.ref.get().to_dict()["precoGatilhoCentavos"] == 110_000


# --- controle de cadência ---------------------------------------------------


def test_controle_ausente_devolve_none(repositorio):
    assert repositorio.ler_controle() is None


def test_gravar_e_ler_controle(repositorio):
    quando = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    repositorio.gravar_controle(quando)

    lido = repositorio.ler_controle()
    assert lido is not None
    assert abs((lido - quando).total_seconds()) < 1


# --- média de 30 dias -------------------------------------------------------


def test_media_sem_30_dias_devolve_none(repositorio, cenario):
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    for deslocamento in range(5):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )

    produto = repositorio.carregar_produto(fonte.produto_ref)
    assert repositorio.media_30_dias_centavos(produto) is None


def test_media_com_30_dias_de_historico(repositorio, cenario):
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    for deslocamento in range(30):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )

    produto = repositorio.carregar_produto(fonte.produto_ref)
    assert repositorio.media_30_dias_centavos(produto) == 100_000


def test_media_historica_exige_30_dias(repositorio, cenario):
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    for deslocamento in range(29):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )
    produto = repositorio.carregar_produto(fonte.produto_ref)
    assert repositorio.media_historica_centavos(produto) is None

    repositorio.registrar_leitura(
        fonte, sucesso(100_000), False, agora=hoje - timedelta(days=29)
    )
    assert repositorio.media_historica_centavos(produto) == 100_000


def test_media_historica_cobre_alem_de_30_dias(repositorio, cenario):
    """Diferente da média de 30 dias, esta olha TODO o histórico."""
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    # 40 dias a 100.000 e mais 40 dias antigos a 200.000
    for deslocamento in range(40):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )
    for deslocamento in range(40, 80):
        repositorio.registrar_leitura(
            fonte, sucesso(200_000), False, agora=hoje - timedelta(days=deslocamento)
        )

    produto = repositorio.carregar_produto(fonte.produto_ref)
    historica = repositorio.media_historica_centavos(produto)
    trinta_dias = repositorio.media_30_dias_centavos(produto)

    assert trinta_dias == 100_000                       # só a janela recente
    assert historica == (40 * 100_000 + 40 * 200_000) // 80
    assert historica == 150_000


def test_media_historica_ignora_suspeitas_e_falhas(repositorio, cenario):
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    for deslocamento in range(30):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )
    # lixo que não pode entrar no rollup
    repositorio.registrar_leitura(fonte, sucesso(1), True, agora=hoje)
    repositorio.registrar_leitura(fonte, falha(), False, agora=hoje)

    produto = repositorio.carregar_produto(fonte.produto_ref)
    assert repositorio.media_historica_centavos(produto) == 100_000


def test_media_e_inteira_e_ponderada_pelas_amostras(repositorio, cenario):
    fonte = cenario()
    hoje = datetime.now(timezone.utc)
    # 29 dias a 100.000 e o dia de hoje com duas amostras
    for deslocamento in range(1, 30):
        repositorio.registrar_leitura(
            fonte, sucesso(100_000), False, agora=hoje - timedelta(days=deslocamento)
        )
    repositorio.registrar_leitura(fonte, sucesso(200_000), False, agora=hoje)
    repositorio.registrar_leitura(
        fonte, sucesso(200_000), False, agora=hoje - timedelta(minutes=5)
    )

    produto = repositorio.carregar_produto(fonte.produto_ref)
    media = repositorio.media_30_dias_centavos(produto)

    assert media == (29 * 100_000 + 2 * 200_000) // 31
    assert isinstance(media, int)


# --- catálogo ---------------------------------------------------------------


def item(sku, centavos, nome=None):
    return ItemDeLista(
        sku=sku, nome=nome or f"Item {sku}",
        url=f"https://loja.example/produto/{sku}/x",
        preco_centavos=centavos, disponivel=None,
    )


def test_salvar_catalogo_cria_itens_e_indice(repositorio):
    resumo = repositorio.salvar_catalogo(
        "kabum.com.br", "placas", [item("1", 100_000), item("2", 200_000)]
    )

    assert resumo["novos"] == 2
    assert resumo["alterados"] == 0
    indice = repositorio.ler_indice_do_catalogo("kabum.com.br", "placas")
    assert indice == {"1": (100_000, None), "2": (200_000, None)}

    itens = {i["sku"]: i for i in repositorio.listar_catalogo("kabum.com.br", "placas")}
    assert itens["1"]["precoCentavos"] == 100_000
    assert isinstance(itens["1"]["precoCentavos"], int)   # nunca float
    assert itens["1"]["categoria"] == "placas"


def test_preco_igual_nao_reescreve(repositorio):
    itens = [item("1", 100_000), item("2", 200_000)]
    repositorio.salvar_catalogo("kabum.com.br", "placas", itens)

    resumo = repositorio.salvar_catalogo("kabum.com.br", "placas", itens)

    assert resumo["novos"] == 0
    assert resumo["alterados"] == 0
    assert resumo["inalterados"] == 2


def test_preco_alterado_e_contabilizado(repositorio):
    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])

    resumo = repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 90_000)])

    assert resumo["alterados"] == 1
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"1": (90_000, None)}


def test_item_sem_sku_ou_sem_preco_e_descartado(repositorio):
    resumo = repositorio.salvar_catalogo(
        "kabum.com.br", "placas",
        [item(None, 100_000), item("2", None), item("3", 300_000)],
    )

    assert resumo["sem_sku"] == 2
    assert resumo["novos"] == 1
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"3": (300_000, None)}


def test_item_que_sumiu_de_uma_raspagem_permanece(repositorio):
    """Comportamento DELIBERADO, trocado depois de medir instabilidade nas
    listagens: sumir de uma raspagem não é sinal de que o produto acabou."""
    repositorio.salvar_catalogo(
        "kabum.com.br", "placas", [item("1", 100_000), item("2", 200_000)]
    )

    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])

    assert set(repositorio.ler_indice_do_catalogo("kabum.com.br", "placas")) == {"1", "2"}
    assert {i["sku"] for i in repositorio.listar_catalogo("kabum.com.br", "placas")} == {"1", "2"}


def test_categorias_diferentes_nao_se_misturam(repositorio):
    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])
    repositorio.salvar_catalogo("kabum.com.br", "processadores", [item("9", 50_000)])

    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"1": (100_000, None)}
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "processadores") == {"9": (50_000, None)}
    assert len(repositorio.listar_catalogo("kabum.com.br")) == 2


def test_indice_inexistente_devolve_vazio(repositorio):
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "nao-existe") == {}


def test_controle_de_raspagem_separado_do_de_coleta(repositorio):
    quando = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    repositorio.gravar_controle_raspagem(quando)

    assert repositorio.ler_controle_raspagem() is not None
    # o portão da coleta é outro documento e continua vazio
    assert repositorio.ler_controle() is None


def test_vitrine_serve_o_catalogo_em_uma_leitura(repositorio):
    repositorio.salvar_catalogo(
        "kabum.com.br", "placas",
        [item("1", 100_000, "Placa Um"), item("2", 200_000, "Placa Dois")],
    )

    vitrine = repositorio.ler_vitrine("kabum.com.br", "placas")

    assert set(vitrine) == {"1", "2"}
    assert vitrine["1"]["n"] == "Placa Um"
    assert vitrine["1"]["p"] == 100_000
    assert vitrine["1"]["u"].startswith("https://")
    # chaves curtas: o nome do campo é cobrado em cada entrada
    assert set(vitrine["1"]) == {"n", "u", "p", "d", "t", "img", "vt"}


def test_documento_da_loja_permite_descobrir_lojas(repositorio):
    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])

    doc = repositorio._db.collection("catalogo").document("kabum.com.br").get()
    assert doc.exists
    assert doc.to_dict()["loja"] == "kabum.com.br"


def esgotado(sku):
    return ItemDeLista(
        sku=sku, nome=f"Item {sku}", url=f"https://loja.example/produto/{sku}/x",
        preco_centavos=None, disponivel=False, preco_tabela_centavos=None,
    )


def test_produto_esgotado_entra_no_catalogo(repositorio):
    """Saber que existe e está esgotado é informação — sumir não é."""
    resumo = repositorio.salvar_catalogo(
        "terabyteshop.com.br", "placas", [item("1", 100_000), esgotado("2")]
    )

    assert resumo["esgotados"] == 1
    assert resumo["sem_sku"] == 0
    vitrine = repositorio.ler_vitrine("terabyteshop.com.br", "placas")
    assert vitrine["2"]["p"] is None
    assert vitrine["2"]["d"] is False


def test_sair_de_estoque_conta_como_alteracao(repositorio):
    """Preço igual mas estoque diferente ainda é mudança."""
    repositorio.salvar_catalogo("terabyteshop.com.br", "placas", [item("1", 100_000)])

    resumo = repositorio.salvar_catalogo("terabyteshop.com.br", "placas", [esgotado("1")])

    assert resumo["alterados"] == 1
    assert resumo["inalterados"] == 0


def test_preco_de_tabela_e_guardado_separado(repositorio):
    com_dois = ItemDeLista(
        sku="1", nome="X", url="https://loja.example/produto/1/x",
        preco_centavos=58_990, disponivel=True, preco_tabela_centavos=69_400,
    )
    repositorio.salvar_catalogo("terabyteshop.com.br", "placas", [com_dois])

    vitrine = repositorio.ler_vitrine("terabyteshop.com.br", "placas")
    assert vitrine["1"]["p"] == 58_990   # o de venda
    assert vitrine["1"]["t"] == 69_400   # o "de" riscado


def test_raspagem_curta_nao_apaga_o_catalogo(repositorio):
    """A renderização das listagens é instável: a mesma categoria devolveu 47
    itens numa requisição e 25 na seguinte. Reescrever com o que veio agora
    apagaria produtos que continuam à venda."""
    repositorio.salvar_catalogo(
        "terabyteshop.com.br", "ssd",
        [item("1", 100_000), item("2", 200_000), item("3", 300_000)],
    )

    resumo = repositorio.salvar_catalogo("terabyteshop.com.br", "ssd", [item("1", 100_000)])

    assert resumo["mantidos"] == 2      # os dois que não vieram
    assert resumo["expirados"] == 0
    assert set(repositorio.ler_vitrine("terabyteshop.com.br", "ssd")) == {"1", "2", "3"}


def test_item_sumido_por_tempo_demais_sai_da_vitrine(repositorio):
    antigo = datetime.now(timezone.utc) - timedelta(days=10)
    repositorio.salvar_catalogo(
        "terabyteshop.com.br", "ssd", [item("1", 100_000), item("2", 200_000)],
        agora=antigo,
    )

    resumo = repositorio.salvar_catalogo("terabyteshop.com.br", "ssd", [item("1", 100_000)])

    assert resumo["expirados"] == 1
    assert set(repositorio.ler_vitrine("terabyteshop.com.br", "ssd")) == {"1"}


def test_item_visto_de_novo_renova_o_prazo(repositorio):
    antigo = datetime.now(timezone.utc) - timedelta(days=10)
    repositorio.salvar_catalogo(
        "terabyteshop.com.br", "ssd", [item("1", 100_000), item("2", 200_000)],
        agora=antigo,
    )

    # ambos aparecem de novo: nenhum expira
    resumo = repositorio.salvar_catalogo(
        "terabyteshop.com.br", "ssd", [item("1", 100_000), item("2", 200_000)]
    )

    assert resumo["expirados"] == 0
    assert set(repositorio.ler_vitrine("terabyteshop.com.br", "ssd")) == {"1", "2"}
