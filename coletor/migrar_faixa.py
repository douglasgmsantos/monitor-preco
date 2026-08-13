"""Migra os produtos de preço-alvo + tolerância para valor mínimo + máximo.

    set -a; source .env; set +a
    python -m coletor.migrar_faixa --simular    # mostra o que faria
    python -m coletor.migrar_faixa              # aplica

O DE-PARA
---------
    valorMinCentavos = precoAlvoCentavos          (o preço que você queria pagar)
    valorMaxCentavos = precoAlvoCentavos * 1,10   (10% acima, como pedido)

e apaga `precoAlvoCentavos`, `toleranciaPct` e `precoGatilhoCentavos`.

O QUE ISSO MUDA NO ALERTA — leia antes de aplicar
-------------------------------------------------
O gatilho passa a ser o `valorMaxCentavos`, que é 10% MAIOR que o alvo antigo
(quando a tolerância era 0, que é o caso de todos os produtos hoje). Ou seja: o
sistema fica mais sensível, e produto que estava calado pode notificar no
primeiro ciclo depois da migração.

`--simular` diz exatamente quais. Rode isso primeiro.

A `toleranciaPct` some porque virou redundante: ela existia para afrouxar o
alvo, e é literalmente o que a distância entre mínimo e máximo faz agora.
"""

import argparse
import os
import sys

from coletor import config
from coletor.repositorio import COLECAO_PRODUTOS, Repositorio, inicializar

CAMPOS_ANTIGOS = ("precoAlvoCentavos", "toleranciaPct", "precoGatilhoCentavos")

# Quanto o máximo fica acima do alvo antigo. Inteiro e multiplicação antes da
# divisão: nenhum float encosta no dinheiro.
MARGEM_NUM = 110
MARGEM_DEN = 100


def reais(centavos: int | None) -> str:
    if centavos is None:
        return "—"
    return f"R$ {centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def principal(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--simular", action="store_true",
        help="mostra o de-para e quem passaria a alertar, sem gravar nada",
    )
    opcoes = analisador.parse_args(argumentos)

    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        print(
            "FIRESTORE_EMULATOR_HOST está definida — a migração precisa ir para "
            "produção.\nRode com: env -u FIRESTORE_EMULATOR_HOST ...",
            file=sys.stderr,
        )
        return 1

    cfg = config.carregar()
    if not cfg.firebase_sa_base64:
        print("FIREBASE_SA_BASE64 vazia. Exporte o .env.", file=sys.stderr)
        return 1

    inicializar(cfg.firebase_sa_base64)
    repositorio = Repositorio()

    # Menor preço atual por produto, para prever quem passa a alertar.
    menor_por_produto: dict[str, int] = {}
    for fonte in repositorio.listar_fontes_ativas():
        preco = fonte.ultimo_preco_centavos
        if preco is None:
            continue
        caminho = fonte.produto_ref.path
        if caminho not in menor_por_produto or preco < menor_por_produto[caminho]:
            menor_por_produto[caminho] = preco

    migrados = 0
    ja_migrados = 0
    passam_a_alertar = []

    for snapshot in repositorio._db.collection_group(COLECAO_PRODUTOS).stream():
        dados = snapshot.to_dict() or {}
        if "valorMaxCentavos" in dados:
            ja_migrados += 1
            continue
        alvo = dados.get("precoAlvoCentavos")
        if not isinstance(alvo, int) or alvo <= 0:
            print(f"  PULADO (sem alvo válido): {dados.get('nome', snapshot.id)}")
            continue

        tolerancia = dados.get("toleranciaPct", 0) or 0
        gatilho_antigo = (alvo * (100 + tolerancia)) // 100
        novo_min = alvo
        novo_max = (alvo * MARGEM_NUM) // MARGEM_DEN

        menor = menor_por_produto.get(snapshot.reference.path)
        vira_alerta = (
            menor is not None
            and menor > gatilho_antigo
            and menor <= novo_max
            and dados.get("estado") == "ACIMA"
        )
        if vira_alerta:
            passam_a_alertar.append((dados.get("nome", "?"), menor, novo_max))

        print(
            f"  {dados.get('nome', '?')[:38]:40} "
            f"alvo {reais(alvo)} tol {tolerancia}%  ->  "
            f"min {reais(novo_min)}  max {reais(novo_max)}"
            + ("   *** passa a alertar ***" if vira_alerta else "")
        )

        if not opcoes.simular:
            from firebase_admin import firestore

            atualizacao = {
                "valorMinCentavos": novo_min,
                "valorMaxCentavos": novo_max,
            }
            for campo in CAMPOS_ANTIGOS:
                atualizacao[campo] = firestore.DELETE_FIELD
            snapshot.reference.update(atualizacao)
        migrados += 1

    print()
    if ja_migrados:
        print(f"{ja_migrados} produto(s) já estavam migrados — não tocados.")
    if opcoes.simular:
        print(f"SIMULAÇÃO: {migrados} produto(s) seriam migrados. Nada foi gravado.")
    else:
        print(f"{migrados} produto(s) migrados.")

    if passam_a_alertar:
        print()
        print("ATENÇÃO — vão notificar no próximo ciclo (o gatilho subiu 10%):")
        for nome, menor, maximo in passam_a_alertar:
            print(f"  {nome[:44]:46} {reais(menor)} <= {reais(maximo)}")
        print()
        print("Se não quiser essas mensagens, ajuste o valor máximo desses")
        print("produtos no front ANTES de rodar o próximo ciclo do coletor.")

    return 0


if __name__ == "__main__":
    sys.exit(principal())
