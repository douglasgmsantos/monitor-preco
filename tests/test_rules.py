"""Security rules, contra o EMULADOR.

Desvio consciente da lista de arquivos da seção 3: ela não prevê este arquivo,
mas a seção 17 exige "Security rules testadas" e "cliente não consegue escrever
em historico, diario, sistema, nem alterar estado". Sem um teste, esse item da
definição de pronto não é reexecutável.

O Admin SDK ignora rules, então aqui NÃO se usa o repositório para as
verificações: fala-se com a API REST do emulador carregando um JWT sem
assinatura, que é a forma suportada de encarnar um usuário autenticado.

Para rodar:
    firebase emulators:start --only firestore --project demo-monitor
    FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 pytest tests/test_rules.py
"""

import base64
import json
import os
import time

import httpx
import pytest

from coletor.repositorio import Repositorio, inicializar

ENDERECO = os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
PROJETO = "demo-monitor"
BASE = f"http://{ENDERECO}/v1/projects/{PROJETO}/databases/(default)/documents"

CAMINHO_FONTE = "usuarios/u1/produtos/p1/fontes/f1"
CAMINHO_PRODUTO = "usuarios/u1/produtos/p1"

RETENTATIVA = {
    "status": {"stringValue": "pendente"},
    "motivoInvalida": {"nullValue": None},
    "falhasSeguidas": {"integerValue": "0"},
    "comErro": {"booleanValue": False},
}


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


def token(uid: str) -> str:
    """JWT sem assinatura. O emulador aceita, e é assim que se testa rules."""
    codificar = lambda objeto: (  # noqa: E731
        base64.urlsafe_b64encode(json.dumps(objeto).encode()).rstrip(b"=").decode()
    )
    agora = int(time.time())
    return ".".join(
        [
            codificar({"alg": "none", "typ": "JWT"}),
            codificar(
                {
                    "iss": f"https://securetoken.google.com/{PROJETO}",
                    "aud": PROJETO,
                    "sub": uid,
                    "user_id": uid,
                    "email": f"{uid}@example.com",
                    "email_verified": True,
                    "iat": agora,
                    "exp": agora + 3600,
                    "firebase": {"identities": {}, "sign_in_provider": "password"},
                }
            ),
            "assinatura-ignorada",
        ]
    )


def escrever(uid: str, caminho: str, campos: dict) -> httpx.Response:
    mascara = "&".join(f"updateMask.fieldPaths={chave}" for chave in campos)
    return httpx.patch(
        f"{BASE}/{caminho}?{mascara}",
        headers={"Authorization": f"Bearer {token(uid)}"},
        json={"fields": campos},
        timeout=15,
    )


def apagar(uid: str, caminho: str) -> httpx.Response:
    return httpx.delete(
        f"{BASE}/{caminho}",
        headers={"Authorization": f"Bearer {token(uid)}"},
        timeout=15,
    )


def ler(uid: str, caminho: str) -> httpx.Response:
    return httpx.get(
        f"{BASE}/{caminho}",
        headers={"Authorization": f"Bearer {token(uid)}"},
        timeout=15,
    )


def permitido(resposta: httpx.Response) -> bool:
    return 200 <= resposta.status_code < 300


@pytest.fixture
def cenario():
    """Semeia produto e fonte com o Admin SDK, que ignora as rules."""
    httpx.delete(
        f"http://{ENDERECO}/emulator/v1/projects/{PROJETO}/databases/(default)/documents",
        timeout=10,
    )
    os.environ["GCLOUD_PROJECT"] = PROJETO
    inicializar(project_id=PROJETO)
    repositorio = Repositorio()

    produto_ref = (
        repositorio._db.collection("usuarios").document("u1")
        .collection("produtos").document("p1")
    )
    produto_ref.set({
        "nome": "Produto", "precoAlvoCentavos": 1000, "toleranciaPct": 0,
        "precoGatilhoCentavos": 1000, "estado": "ACIMA", "ultimoAlertaEm": None,
        "ultimoPrecoAlertadoCentavos": None, "ativo": True,
    })
    fonte_ref = produto_ref.collection("fontes").document("f1")
    fonte_ref.set({
        "loja": "KaBuM", "url": "https://kabum.com.br/p/1", "status": "invalida",
        "motivoInvalida": "http_403", "falhasSeguidas": 5, "comErro": False,
        "ultimoPrecoCentavos": None, "ultimaColetaEm": None,
    })
    return fonte_ref


# --- isolamento entre usuários ---------------------------------------------


def test_outro_usuario_nao_le_produto(cenario):
    assert not permitido(ler("u2", CAMINHO_PRODUTO))


def test_outro_usuario_nao_le_fonte(cenario):
    assert not permitido(ler("u2", CAMINHO_FONTE))


def test_outro_usuario_nao_escreve_fonte(cenario):
    assert not permitido(escrever("u2", CAMINHO_FONTE, RETENTATIVA))


def test_dono_le_a_propria_fonte(cenario):
    assert permitido(ler("u1", CAMINHO_FONTE))


# --- território exclusivo do coletor ---------------------------------------


def test_cliente_nao_altera_estado_do_alerta(cenario):
    resposta = escrever("u1", CAMINHO_PRODUTO, {"estado": {"stringValue": "EM_ALERTA"}})
    assert not permitido(resposta)


def test_cliente_nao_escreve_no_historico(cenario):
    resposta = escrever(
        "u1", "usuarios/u1/produtos/p1/historico/f1_2026-08",
        {"fonteId": {"stringValue": "x"}},
    )
    assert not permitido(resposta)


def test_cliente_nao_escreve_no_rollup_diario(cenario):
    resposta = escrever(
        "u1", "usuarios/u1/produtos/p1/diario/f1_2026",
        {"fonteId": {"stringValue": "x"}},
    )
    assert not permitido(resposta)


def test_dono_apaga_o_proprio_historico(cenario):
    """Necessário porque o Firestore não faz cascata: sem delete, excluir um
    produto deixaria histórico órfão para sempre. Poder apagar não é poder
    forjar — a criação e a alteração seguem bloqueadas."""
    caminho = "usuarios/u1/produtos/p1/historico/f1_2026-08"
    rep = Repositorio()
    rep._db.document(caminho).set({"fonteId": "f1", "mes": "2026-08", "leituras": []})

    assert permitido(apagar("u1", caminho))


def test_dono_apaga_o_proprio_rollup(cenario):
    caminho = "usuarios/u1/produtos/p1/diario/f1_2026"
    rep = Repositorio()
    rep._db.document(caminho).set({"fonteId": "f1", "ano": 2026, "dias": {}})

    assert permitido(apagar("u1", caminho))


def test_outro_usuario_nao_apaga_historico(cenario):
    caminho = "usuarios/u1/produtos/p1/historico/f1_2026-08"
    rep = Repositorio()
    rep._db.document(caminho).set({"fonteId": "f1", "mes": "2026-08", "leituras": []})

    assert not permitido(apagar("u2", caminho))


def test_dono_apaga_fonte_e_produto(cenario):
    assert permitido(apagar("u1", CAMINHO_FONTE))
    assert permitido(apagar("u1", CAMINHO_PRODUTO))


def test_outro_usuario_nao_apaga_produto(cenario):
    assert not permitido(apagar("u2", CAMINHO_PRODUTO))


def test_cliente_nao_escreve_no_controle(cenario):
    resposta = escrever("u1", "usuarios/u1/sistema/controle",
                        {"ultimaColetaEm": {"stringValue": "x"}})
    assert not permitido(resposta)


# --- o que o cliente PODE fazer -------------------------------------------


def test_dono_pausa_o_produto(cenario):
    assert permitido(
        escrever("u1", CAMINHO_PRODUTO, {"ativo": {"booleanValue": False}})
    )


def test_dono_reenfileira_fonte_quebrada(cenario):
    assert permitido(escrever("u1", CAMINHO_FONTE, RETENTATIVA))
    dados = cenario.get().to_dict()
    assert dados["status"] == "pendente"
    assert dados["motivoInvalida"] is None
    assert dados["falhasSeguidas"] == 0
    assert dados["url"] == "https://kabum.com.br/p/1"   # intocada


def test_retentativa_nao_promove_para_ok(cenario):
    resposta = escrever("u1", CAMINHO_FONTE, {"status": {"stringValue": "ok"}})
    assert not permitido(resposta)


def test_dono_edita_a_url_da_fonte(cenario):
    """Editar link é reenfileirar com URL nova — mesma transição."""
    resposta = escrever(
        "u1", CAMINHO_FONTE,
        dict(RETENTATIVA, url={"stringValue": "https://kabum.com.br/p/999"}),
    )
    assert permitido(resposta)
    assert cenario.get().to_dict()["url"] == "https://kabum.com.br/p/999"


def test_edicao_exige_https(cenario):
    resposta = escrever(
        "u1", CAMINHO_FONTE,
        dict(RETENTATIVA, url={"stringValue": "http://kabum.com.br/p/999"}),
    )
    assert not permitido(resposta)


def test_edicao_nao_aceita_loja_vazia(cenario):
    resposta = escrever(
        "u1", CAMINHO_FONTE, dict(RETENTATIVA, loja={"stringValue": ""})
    )
    assert not permitido(resposta)


def test_reenfileiramento_nao_injeta_preco(cenario):
    resposta = escrever(
        "u1", CAMINHO_FONTE,
        dict(RETENTATIVA, ultimoPrecoCentavos={"integerValue": "1"}),
    )
    assert not permitido(resposta)


def test_fonte_saudavel_pode_ser_reenfileirada(cenario):
    """Editar o link de uma fonte que FUNCIONA é caso de uso legítimo.

    Antes a regra exigia fonte quebrada; foi afrouxado de propósito para
    permitir corrigir um link bom. O custo é uma revalidação extra, e promover
    para 'ok' continua sendo exclusividade do coletor.
    """
    cenario.update({"status": "ok", "motivoInvalida": None, "comErro": False})
    assert permitido(escrever("u1", CAMINHO_FONTE, RETENTATIVA))
