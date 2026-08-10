"""Tabela de normalização da seção 7.5 da spec, linha por linha."""

import pytest

from coletor.parser import TETO_CENTAVOS, normalizar_para_centavos

# Cada linha aqui é uma linha da tabela da spec, na mesma ordem.
CASOS_DA_TABELA = [
    ("1299.90", 129990),
    ("1.299,90", 129990),
    ("1,299.90", 129990),
    ("R$ 1.299,90", 129990),
    ("R$ 1.299,90", 129990),
    # "1.234.567,89" foi retirado desta tabela por conflito interno da spec.
    # Está coberto por test_conflito_da_spec_milhar_acima_do_teto, abaixo.
    ("1.299", 129900),
    ("1,299", 129900),
    ("12,5", 1250),
    ("12.5", 1250),
    ("1299", 129900),
    (1299.9, 129990),
    ("0", None),
    ("-10,00", None),
    ("", None),
    ("consulte", None),
    ("2.000.000,00", None),
]


@pytest.mark.parametrize("bruto, esperado", CASOS_DA_TABELA)
def test_tabela_da_spec(bruto, esperado):
    assert normalizar_para_centavos(bruto) == esperado


# --- Consequências diretas do algoritmo, não cobertas pela tabela -----------


@pytest.mark.parametrize(
    "bruto, esperado",
    [
        (1299, 129900),  # int puro
        ("BRL 1.299,90", 129990),  # prefixo alfabético de moeda
        ("  1.299,90  ", 129990),  # espaços nas bordas
        ("1.234,5", 123450),  # uma casa decimal com milhar
        ("1,234.5", 123450),  # o mesmo em en-US
    ],
)
def test_variacoes_de_formato(bruto, esperado):
    assert normalizar_para_centavos(bruto) == esperado


@pytest.mark.parametrize(
    "bruto",
    [
        "1.2345",  # 4 dígitos depois do separador: inválido pelo passo 4
        "12,34567",
        None,
        True,  # bool é subclasse de int, mas não é preço
        [],
        {},
        "R$",
        "-1.299,90",
        "−10,00",  # sinal de menos tipográfico
    ],
)
def test_entradas_invalidas(bruto):
    assert normalizar_para_centavos(bruto) is None


def test_trunca_em_dois_digitos_sem_arredondar():
    # Passo 3 escolhe o "." como decimal; o passo 6 trunca "5678" em "56".
    assert normalizar_para_centavos("1,234.5678") == 123456


def test_conflito_da_spec_milhar_acima_do_teto():
    """A tabela 7.5 espera 123456789 para "1.234.567,89", mas o passo 7 da
    mesma seção rejeita tudo acima de TETO_CENTAVOS (R$ 1.000.000,00) — e a
    própria tabela manda rejeitar "2.000.000,00" por esse motivo. As duas
    linhas não podem valer ao mesmo tempo.

    Decisão: o teto prevalece. Ele existe para barrar lixo de parse, e um
    produto de R$ 1,2 milhão num monitor de e-commerce de consumo é lixo de
    parse. A linha da tabela só informa sobre SEPARADORES, então é isso que
    verificamos nela — com o teto afastado.
    """
    # a leitura dos separadores está correta
    assert normalizar_para_centavos("1.234.567,89", teto_centavos=10**12) == 123456789
    # e o teto padrão continua barrando o valor
    assert normalizar_para_centavos("1.234.567,89") is None


def test_limite_do_teto_e_inclusivo():
    assert normalizar_para_centavos("1.000.000,00") == TETO_CENTAVOS
    assert normalizar_para_centavos("1.000.000,01") is None


def test_teto_configuravel():
    assert normalizar_para_centavos("500,00", teto_centavos=50_000) == 50_000
    assert normalizar_para_centavos("500,01", teto_centavos=50_000) is None


def test_nao_usa_float_para_obter_centavos():
    # int(float("1299.90") * 100) devolve 129989 em algumas plataformas.
    assert normalizar_para_centavos("1299.90") == 129990
    assert normalizar_para_centavos("0.29") == 29
    assert normalizar_para_centavos("1.15") == 115
