"""Rede de segurança contra nome indefinido — sem Firestore, sem Java, sem rede.

POR QUE ISTO EXISTE: em 2026-08-14 a coleta em produção quebrou em TODAS as 9
fontes com `NameError: name '_dia_atualizado' is not defined`. A função tinha
sido apagada num refactor junto com a média de 30 dias, mas `registrar_leitura`
continuava chamando. A suíte estava verde — 266 passed — porque o único teste
que exercita esse caminho é o do emulador do Firestore, e o emulador precisa de
Java, que não existe na máquina de desenvolvimento. 85 testes pulados parecem
inofensivos num resumo do pytest.

Python só resolve nome global na hora de EXECUTAR a linha. Enquanto o caminho
não roda, o arquivo importa, o módulo carrega e nada denuncia. Um analisador
estático resolve na hora de LER — é o que fecha exatamente essa lacuna, e roda
em milissegundos em qualquer máquina.

Escopo de propósito estreito: só as classes de erro que quebram em execução
(F821 nome indefinido, F811 redefinição) e lixo de import. Isto não é um
linter de estilo, e não deve virar um.
"""

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent

pyflakes = pytest.importorskip(
    "pyflakes",
    reason="pyflakes não instalado — `pip install -r requirements.txt`",
)


def _analisar(*alvos: str) -> list[str]:
    processo = subprocess.run(
        [sys.executable, "-m", "pyflakes", *alvos],
        cwd=RAIZ, capture_output=True, text=True,
    )
    return [linha for linha in processo.stdout.splitlines() if linha.strip()]


def test_coletor_e_testes_sem_nome_indefinido():
    """O caso do `_dia_atualizado`: chamada que nenhum teste local executa."""
    achados = [linha for linha in _analisar("coletor", "tests")
               if "undefined name" in linha]
    assert not achados, "nome usado mas nunca definido:\n" + "\n".join(achados)


def test_coletor_e_testes_sem_avisos_de_pyflakes():
    """Zero avisos, não "poucos".

    Uma lista de exceções toleradas é onde um F821 de verdade se esconde: com
    três avisos aceitos no arquivo, o quarto passa despercebido na leitura.
    """
    achados = _analisar("coletor", "tests")
    assert not achados, "pyflakes reclamou:\n" + "\n".join(achados)
