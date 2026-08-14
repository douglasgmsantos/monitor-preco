"""O acumulador do rollup diário, sem Firestore.

`_dia_atualizado` é uma função pura no meio de uma transação do Firestore. Até
2026-08-14 ela só era exercitada pelos testes do emulador, que exigem Java e
por isso ficam pulados na máquina de desenvolvimento — foi assim que a função
chegou a ser APAGADA num refactor sem nenhum teste ficar vermelho.

Pura, ela se testa direto. É o que este arquivo faz.
"""

from coletor.repositorio import _dia_atualizado


def test_primeira_leitura_do_dia_abre_todos_os_campos():
    assert _dia_atualizado(None, 1990) == {
        "min": 1990, "max": 1990, "soma": 1990, "n": 1, "fech": 1990,
    }


def test_segunda_leitura_acumula_sem_perder_a_primeira():
    dia = _dia_atualizado({"min": 1990, "max": 1990, "soma": 1990, "n": 1, "fech": 1990}, 1500)
    assert dia == {"min": 1500, "max": 1990, "soma": 3490, "n": 2, "fech": 1500}


def test_fechamento_e_sempre_a_leitura_mais_recente():
    """`fech` é o último preço do dia, não o menor: é o que o gráfico desenha."""
    dia = _dia_atualizado({"min": 1000, "max": 2000, "soma": 3000, "n": 2, "fech": 1000}, 1800)
    assert dia["fech"] == 1800
    assert dia["min"] == 1000          # a mínima do dia continua sendo a mínima


def test_soma_e_n_permitem_media_ponderada_exata():
    """`soma`/`n` em vez de média já dividida.

    Guardar a média pronta obrigaria a média do mês a ser média de médias, que
    erra sempre que os dias têm contagens diferentes de leitura.
    """
    dia = None
    for preco in (1000, 1000, 4000):
        dia = _dia_atualizado(dia, preco)
    assert dia["soma"] // dia["n"] == 2000


def test_dia_anterior_incompleto_nao_derruba_a_atualizacao():
    """Documento gravado por uma versão antiga, sem `min`/`max`/`soma`/`n`.

    Vale porque o rollup é acumulativo: um documento de meses atrás sobrevive a
    mudanças de formato, e a atualização não pode explodir ao encontrá-lo.

    Os campos que faltam nascem do preço de agora — inclusive `max`, que NÃO é
    derivado do `fech` de 1200 que está lá. Fechamento não é máxima; usá-lo
    como tal inventaria uma máxima que talvez nunca tenha existido.
    """
    dia = _dia_atualizado({"fech": 1200}, 900)
    assert dia == {"min": 900, "max": 900, "soma": 900, "n": 1, "fech": 900}
