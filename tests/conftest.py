"""Utilitários compartilhados pelos testes.

O diretório `tests/fixtures/` é SOMENTE LEITURA. Nenhum teste, nem este
arquivo, pode criar, editar ou completar arquivo algum lá dentro.
"""

import json
from pathlib import Path

import pytest

DIRETORIO_FIXTURES = Path(__file__).parent / "fixtures"
ARQUIVO_GABARITO = DIRETORIO_FIXTURES / "esperado.json"


def gabarito_disponivel() -> bool:
    """Indica se o gabarito fornecido com a tarefa está presente."""
    return ARQUIVO_GABARITO.is_file()


def carregar_gabarito() -> dict:
    """Lê `esperado.json`, o gabarito de preço e disponibilidade das fixtures."""
    return json.loads(ARQUIVO_GABARITO.read_text(encoding="utf-8"))


def ler_fixture(nome: str) -> str:
    """Lê uma fixture HTML pelo nome do arquivo."""
    caminho = DIRETORIO_FIXTURES / nome
    if not caminho.is_file():
        pytest.fail(f"fixture ausente: {caminho} — não é permitido fabricá-la")
    return caminho.read_text(encoding="utf-8")
