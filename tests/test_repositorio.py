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


def _emulador_no_ar() -> bool:
    try:
        httpx.get(f"http://{ENDERECO}/", timeout=2.0)
        return True
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
    httpx.delete(
        f"http://{ENDERECO}/emulator/v1/projects/{PROJETO}/databases/(default)/documents",
        timeout=10.0,
    )
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
    assert indice == {"1": 100_000, "2": 200_000}

    itens = {i["sku"]: i for i in repositorio.listar_catalogo("kabum.com.br", "placas")}
    assert itens["1"]["precoTabelaCentavos"] == 100_000
    assert isinstance(itens["1"]["precoTabelaCentavos"], int)   # nunca float
    assert itens["1"]["categoria"] == "placas"


def test_preco_igual_nao_reescreve(repositorio):
    itens = [item("1", 100_000), item("2", 200_000)]
    repositorio.salvar_catalogo("kabum.com.br", "placas", itens)

    resumo = repositorio.salvar_catalogo("kabum.com.br", "placas", itens)

    assert resumo == {"novos": 0, "alterados": 0, "inalterados": 2, "sem_sku": 0}


def test_preco_alterado_e_contabilizado(repositorio):
    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])

    resumo = repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 90_000)])

    assert resumo["alterados"] == 1
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"1": 90_000}


def test_item_sem_sku_ou_sem_preco_e_descartado(repositorio):
    resumo = repositorio.salvar_catalogo(
        "kabum.com.br", "placas",
        [item(None, 100_000), item("2", None), item("3", 300_000)],
    )

    assert resumo["sem_sku"] == 2
    assert resumo["novos"] == 1
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"3": 300_000}


def test_item_que_sumiu_da_listagem_sai_do_indice(repositorio):
    repositorio.salvar_catalogo(
        "kabum.com.br", "placas", [item("1", 100_000), item("2", 200_000)]
    )

    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])

    # o índice reflete a listagem atual...
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"1": 100_000}
    # ...mas o documento do item sai de circulação sem ser apagado, para não
    # quebrar quem já favoritou o produto
    assert {i["sku"] for i in repositorio.listar_catalogo("kabum.com.br", "placas")} == {"1", "2"}


def test_categorias_diferentes_nao_se_misturam(repositorio):
    repositorio.salvar_catalogo("kabum.com.br", "placas", [item("1", 100_000)])
    repositorio.salvar_catalogo("kabum.com.br", "processadores", [item("9", 50_000)])

    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "placas") == {"1": 100_000}
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "processadores") == {"9": 50_000}
    assert len(repositorio.listar_catalogo("kabum.com.br")) == 2


def test_indice_inexistente_devolve_vazio(repositorio):
    assert repositorio.ler_indice_do_catalogo("kabum.com.br", "nao-existe") == {}


def test_controle_de_raspagem_separado_do_de_coleta(repositorio):
    quando = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    repositorio.gravar_controle_raspagem(quando)

    assert repositorio.ler_controle_raspagem() is not None
    # o portão da coleta é outro documento e continua vazio
    assert repositorio.ler_controle() is None
