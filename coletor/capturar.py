"""Grava uma captura de página na caixa de correio, a partir de um arquivo.

    set -a; source .env; set +a
    python -m coletor.capturar --fonte <fonteId> --arquivo pagina.html

Serve a dois propósitos, e o segundo é o mais útil:

  1. testar o formato do documento sem depender do n8n estar pronto;
  2. **destravar uma loja hoje**, salvando a página do navegador e subindo à mão.
     É trabalhoso e não escala, mas prova o caminho inteiro de ponta a ponta
     antes de você investir no n8n.

Use `--listar` para ver os ids das fontes que esperam captura.
"""

import argparse
import os
import sys
from pathlib import Path

from coletor import captura, config
from coletor.lojas import busca_de
from coletor.repositorio import Repositorio, inicializar


def _abrir_repositorio(cfg: config.Config) -> Repositorio:
    if os.environ.get("FIRESTORE_EMULATOR_HOST"):
        raise SystemExit(
            "FIRESTORE_EMULATOR_HOST está definida. A captura precisa ir para o "
            "Firestore de produção.\nRode com: env -u FIRESTORE_EMULATOR_HOST ..."
        )
    if not cfg.firebase_sa_base64:
        raise SystemExit(
            "FIREBASE_SA_BASE64 vazia. Exporte o .env:\n  set -a; source .env; set +a"
        )
    inicializar(cfg.firebase_sa_base64)
    return Repositorio()


def listar(repositorio: Repositorio) -> int:
    fontes = repositorio.listar_fontes_ativas() + repositorio.listar_fontes_pendentes()
    if not fontes:
        print("nenhuma fonte cadastrada")
        return 0
    print(f"{'fonteId':24} {'busca':11} {'loja':16} url")
    for fonte in fontes:
        print(f"{fonte.id:24} {busca_de(fonte.url):11} {fonte.loja:16} {fonte.url[:70]}")
    print("\nSó as fontes com busca=capturada leem da caixa de correio.")
    return 0


def principal(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--listar", action="store_true",
                            help="mostra os ids das fontes e como cada uma busca")
    analisador.add_argument("--fonte", help="id da fonte (ver --listar)")
    analisador.add_argument("--arquivo", help="HTML salvo do navegador")
    analisador.add_argument("--url", help="URL capturada; padrão é a da fonte")
    opcoes = analisador.parse_args(argumentos)

    cfg = config.carregar()
    repositorio = _abrir_repositorio(cfg)

    if opcoes.listar:
        return listar(repositorio)

    if not opcoes.fonte or not opcoes.arquivo:
        analisador.error("--fonte e --arquivo são obrigatórios (ou use --listar)")

    caminho = Path(opcoes.arquivo)
    if not caminho.is_file():
        raise SystemExit(f"arquivo não encontrado: {caminho}")
    html = caminho.read_text(encoding="utf-8", errors="replace")

    # Recusa antes de gravar: subir uma captura escapada é gastar o esforço para
    # produzir um `sem_jsonld` que aponta para a loja errada.
    if captura.parece_html_escapado(html):
        raise SystemExit(
            f"{caminho.name} está com as aspas ESCAPADAS — passou por "
            "JSON.stringify e não foi desescapado.\nNada vai casar. Salve o HTML "
            "cru do navegador (Salvar como -> Página da Web, somente HTML)."
        )

    url = opcoes.url
    if not url:
        todas = repositorio.listar_fontes_ativas() + repositorio.listar_fontes_pendentes()
        achada = next((f for f in todas if f.id == opcoes.fonte), None)
        if achada is None:
            raise SystemExit(
                f"fonte {opcoes.fonte} não encontrada. Use --listar, ou passe --url."
            )
        url = achada.url
        if busca_de(url) != "capturada":
            print(
                "AVISO: a loja desta fonte busca DIRETA, então o coletor vai "
                "ignorar esta captura.\n       Para usá-la, mude `busca` da loja "
                "em coletor/lojas.py.",
                file=sys.stderr,
            )

    documento = captura.documento(html, url)
    repositorio.gravar_pagina_capturada(opcoes.fonte, documento)
    print(
        f"gravado em paginas/{opcoes.fonte}\n"
        f"  url   : {url}\n"
        f"  bruto : {documento['bytes'] / 1024:,.0f} KB\n"
        f"  no doc: {len(documento['html']) / 1024:,.0f} KB (gzip+base64)\n"
        f"  vale por {captura.HORAS_DE_VALIDADE_PADRAO} h"
    )
    return 0


if __name__ == "__main__":
    sys.exit(principal())
