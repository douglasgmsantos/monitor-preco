"""Extração de preço a partir do HTML de uma página de produto.

Módulo PURO: não faz rede, não toca o Firestore, não lê nem escreve disco.
Recebe uma string de HTML e devolve um `ResultadoExtracao`. Essa pureza é o
que permite testar o módulo inteiro contra as fixtures.

Todo valor monetário sai daqui como INTEIRO DE CENTAVOS. Não existe `float`
em nenhum ponto do caminho do preço — ver `normalizar_para_centavos`.
"""

import html as entidades_html
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

logger = logging.getLogger(__name__)

TETO_CENTAVOS = 100_000_000

# Comparação em caixa baixa: lojas publicam "Product" e "product".
TIPOS_PRODUTO = frozenset({"product", "individualproduct", "productmodel"})

DISPONIBILIDADE_DISPONIVEL = frozenset(
    {"instock", "limitedavailability", "onlineonly", "preorder", "instoreonly"}
)
DISPONIBILIDADE_INDISPONIVEL = frozenset(
    {"outofstock", "soldout", "discontinued", "backorder"}
)

MOEDA_ACEITA = "BRL"

# Erros que dizem algo sobre a PÁGINA: repetir a requisição não muda o
# resultado. Qualquer outro motivo (http_403, timeout, erro_rede) é de
# TRANSPORTE e pode ser transitório — quem valida fonte precisa distinguir os
# dois, senão condena uma URL boa porque a loja bloqueou o IP do runner.
ERROS_DE_PARSE = frozenset(
    {"sem_jsonld", "sem_product", "sem_offers", "preco_invalido", "moeda_nao_suportada",
     "sem_preco_no_dom", "sem_preco_avista"}
)

# `pagina_de_bloqueio` fica DE FORA de ERROS_DE_PARSE de propósito. A página é
# sintaticamente perfeita e não tem preço — parece erro de parse, mas é
# transporte: a loja serviu um desafio anti-bot em vez do produto. Classificar
# como parse condenaria uma URL boa depois de 5 ciclos; como transporte, a fonte
# sobrevive até a loja voltar a responder.
ERRO_BLOQUEIO = "pagina_de_bloqueio"

# Também fora de ERROS_DE_PARSE, e por um motivo diferente: a página está
# perfeita e a URL está certa — o produto é que não tem vendedor neste instante.
# Condenar a fonte por isso seria punir o usuário por uma decisão do mercado. A
# fonte segue viva e volta a ler sozinha quando alguém voltar a vender.
ERRO_SEM_OFERTA = "sem_oferta_ativa"

SELETOR_JSONLD = 'script[type="application/ld+json"]'

# Assinaturas de página de desafio anti-bot. Medidas em 2026-08-12 buscando as
# três lojas de fixture a partir desta máquina:
#
#   Terabyte  HTTP 403, 6 KB, <title>Just a moment...</title>   (Cloudflare)
#   Pichau    HTTP 403, 121 KB, página de bloqueio própria
#   Amazon    HTTP 200 (!), 221 KB, sem NENHUMA marcação de produto — servida
#             quando o User-Agent não é de navegador. É o caso perigoso: 200 com
#             corpo grande passaria por página legítima sem esta checagem.
MARCAS_DE_BLOQUEIO = (
    "just a moment",
    "checking your browser",
    "enable javascript and cookies to continue",
    "digite os caracteres",
    "type the characters you see",
    "sorry, we just need to make sure you're not a robot",
    "request blocked",
    "access denied",
)


def parece_pagina_de_bloqueio(html: str) -> bool:
    """True quando o corpo é um desafio anti-bot em vez da página do produto.

    Olha só o começo do documento: as marcas moram no `<title>` e no topo do
    corpo, e varrer 1,2 MB de HTML legítimo atrás de uma frase seria caro para
    nada.
    """
    inicio = (html or "")[:4000].lower()
    return any(marca in inicio for marca in MARCAS_DE_BLOQUEIO)


@dataclass(frozen=True)
class ResultadoExtracao:
    preco_centavos: int | None
    moeda: str | None
    disponivel: bool
    # j jsonld · g opengraph · m microdata · d seletores de DOM ·
    # e estado JSON embutido na página
    origem: Literal["j", "g", "m", "d", "e"] | None
    erro: str | None  # preenchido apenas quando preco_centavos is None


@dataclass(frozen=True)
class ItemDeLista:
    """Um produto encontrado numa página de LISTAGEM (categoria ou busca).

    `disponivel` é `None` de propósito: listagens não publicam `availability`.
    Afirmar True seria inventar estoque — quem precisa dessa informação abre a
    página do produto.
    """

    sku: str | None
    nome: str | None
    url: str | None
    preco_centavos: int | None
    disponivel: bool | None
    # Preço "de" riscado, quando a vitrine publica os dois. A KaBuM publica só
    # um valor no JSON-LD (que é o de tabela); o Terabyte publica os dois no
    # HTML, e aí `preco_centavos` é o de venda de verdade.
    preco_tabela_centavos: int | None = None
    imagem: str | None = None


@dataclass(frozen=True)
class SeletoresDeProduto:
    """Onde achar preço e estoque na PÁGINA DE PRODUTO de uma loja sem JSON-LD.

    Irmão de `SeletoresDeListagem`, e pela mesma razão: seletor é DADO. Quando a
    loja mexe no layout, o conserto é editar a tabela em `coletor/lojas.py` e o
    teste contra o template congelado avisa alto.

    `prova_de_produto` é o campo que impede o pior modo de falha. A Amazon
    responde **HTTP 200 com 221 KB** quando o User-Agent não é de navegador — um
    corpo grande, bem-formado, e sem nenhuma marcação de produto. Sem uma prova
    positiva de que a página do produto chegou, isso viraria "não achei preço",
    a fonte acumularia 5 falhas e seria desativada como se a URL fosse ruim.
    Com a prova, o erro é `pagina_de_bloqueio` e a fonte sobrevive.
    """

    # Vários seletores, tentados em ordem: a Amazon tem mais de um layout de
    # bloco de preço, e o primeiro que casar vale.
    preco: tuple[str, ...]
    prova_de_produto: str
    # Marcador de "produto existe, ninguém vendendo". Quando ele está presente e
    # não há preço, o resultado é ERRO_SEM_OFERTA em vez de erro de parse — a
    # diferença entre "a página mudou" e "o produto está sem vendedor".
    marcador_sem_oferta: str | None = None
    preco_tabela: str | None = None
    disponibilidade: str | None = None
    # Presença do botão de compra é sinal POSITIVO de estoque. Vale mais que o
    # texto: o texto varia por região e por campanha, o botão some quando acaba.
    botao_de_compra: str | None = None
    marcadores_indisponivel: tuple[str, ...] = (
        "indisponível", "indisponivel", "esgotado", "sem estoque",
        "fora de estoque", "temporariamente sem", "avise-me",
        "currently unavailable", "out of stock",
    )
    # Símbolos que provam que o número é em real. Um preço em dólar tem a mesma
    # forma e passaria pelo normalizador como se fosse BRL.
    marcadores_de_moeda: tuple[str, ...] = ("r$",)


@dataclass(frozen=True)
class SeletoresDeListagem:
    """Onde achar cada campo no HTML de uma loja.

    Seletores são DADOS, não código: quando a loja mexe no layout, o conserto é
    editar esta tabela, e o teste com fixture congelada avisa alto que ela
    mudou. É o preço de trabalhar com lojas que não publicam JSON-LD.
    """

    item: str
    nome: str
    url: str
    preco: str
    preco_tabela: str | None = None
    nome_atributo: str | None = None   # ex.: title, quando o texto é truncado
    imagem: str | None = None
    # Lojas que escrevem "Indisponível" no lugar do preço estão informando
    # estoque de graça — algo que o JSON-LD da listagem não dá.
    marcadores_indisponivel: tuple[str, ...] = (
        "indisponível", "indisponivel", "esgotado", "sem estoque", "avise-me",
    )


# ----------------------------------------------------------------------------
# Normalização do valor monetário
# ----------------------------------------------------------------------------


def normalizar_para_centavos(
    bruto: str | int | float, *, teto_centavos: int = TETO_CENTAVOS
) -> int | None:
    """Converte um preço bruto em inteiro de centavos, ou None se inválido.

    Aceita número (`1299.9`), string pt-BR (`"1.299,90"`) e string en-US
    (`"1299.90"`). O algoritmo está na seção 7.5 da spec e é seguido passo a
    passo — a ordem das decisões sobre os separadores é o ponto inteiro deste
    módulo existir.
    """
    # Passo 1 — número vira string, sem notação científica.
    if isinstance(bruto, bool):
        # bool é subclasse de int em Python; não é preço.
        return None
    if isinstance(bruto, int):
        texto = str(bruto)
    elif isinstance(bruto, float):
        # Decimal(repr(x)) preserva os dígitos que o repr já arredondou e o
        # format "f" desfaz o "1e+20". Sem aritmética com float em momento algum.
        try:
            texto = format(Decimal(repr(bruto)), "f")
        except InvalidOperation:
            return None
    elif isinstance(bruto, str):
        texto = bruto
    else:
        return None

    # O passo 2 apaga qualquer caractere que não seja dígito ou separador, o
    # que inclui o sinal de menos. Se o negativo não for detectado ANTES,
    # "-10,00" vira 1000 e passa pelo teste do passo 7. Ver relatório de
    # ambiguidades: a spec rejeita "-10,00" na tabela mas o passo 2 destruiria
    # o sinal.
    if _tem_sinal_negativo(texto):
        return None

    # Passo 2 — sobram apenas dígitos, vírgulas e pontos.
    limpo = "".join(c for c in texto if c.isdigit() or c in ",.")

    tem_virgula = "," in limpo
    tem_ponto = "." in limpo

    if tem_virgula and tem_ponto:
        # Passo 3 — o separador mais à direita é o decimal.
        if limpo.rfind(",") > limpo.rfind("."):
            limpo = limpo.replace(".", "").replace(",", ".")
        else:
            limpo = limpo.replace(",", "")
    elif tem_virgula or tem_ponto:
        # Passo 4 — um único tipo de separador.
        separador = "," if tem_virgula else "."
        if limpo.count(separador) > 1:
            limpo = limpo.replace(separador, "")
        else:
            digitos_depois = len(limpo) - limpo.index(separador) - 1
            if digitos_depois in (1, 2):
                limpo = limpo.replace(separador, ".")
            elif digitos_depois == 3:
                limpo = limpo.replace(separador, "")
            else:
                return None
    # Passo 5 — sem separador: usar como está.

    # Passo 6 — para centavos pela string, jamais multiplicando float por 100.
    if not limpo:
        return None
    if "." in limpo:
        parte_inteira, _, parte_fracionaria = limpo.partition(".")
    else:
        parte_inteira, parte_fracionaria = limpo, ""

    parte_inteira = parte_inteira or "0"
    # completa à direita e trunca em dois dígitos
    parte_fracionaria = (parte_fracionaria + "00")[:2]

    if not parte_inteira.isdigit() or not parte_fracionaria.isdigit():
        return None

    centavos = int(parte_inteira) * 100 + int(parte_fracionaria)

    # Passo 7 — faixa aceitável.
    if centavos <= 0 or centavos > teto_centavos:
        return None
    return centavos


def _tem_sinal_negativo(texto: str) -> bool:
    """Detecta preço negativo antes da limpeza apagar o sinal."""
    for caractere in texto:
        if caractere.isdigit():
            return False
        if caractere in "-−":  # hífen comum e sinal de menos tipográfico
            return True
    return False


# ----------------------------------------------------------------------------
# Extração
# ----------------------------------------------------------------------------


def extrair_preco(
    html: str, *, teto_centavos: int = TETO_CENTAVOS
) -> ResultadoExtracao:
    """Extrai preço, moeda e disponibilidade do HTML de uma página de produto."""
    arvore = HTMLParser(html or "")

    documentos = _documentos_jsonld(arvore)
    if not documentos:
        return _fallback(arvore, "sem_jsonld", teto_centavos)

    produto = None
    for documento in documentos:
        produto = _primeiro_produto(documento)
        if produto is not None:
            break
    if produto is None:
        return _fallback(arvore, "sem_product", teto_centavos)

    ofertas = _ofertas_do_produto(produto)
    if not ofertas:
        return _fallback(arvore, "sem_offers", teto_centavos)

    candidatos = []
    for oferta in ofertas:
        centavos, moeda = _valor_da_oferta(oferta, teto_centavos)
        if centavos is not None:
            candidatos.append((centavos, moeda, oferta))

    if not candidatos:
        return _fallback(arvore, "preco_invalido", teto_centavos)

    # Lista de ofertas: vale a menor. Oferta única: é a própria.
    centavos, moeda, oferta_escolhida = min(candidatos, key=lambda item: item[0])

    if moeda is not None and moeda.strip().upper() != MOEDA_ACEITA:
        # Não cai para o fallback: o fallback leria o mesmo número em moeda
        # estrangeira e o gravaria como se fosse real. Ver relatório.
        return ResultadoExtracao(None, moeda, False, None, "moeda_nao_suportada")

    return ResultadoExtracao(
        preco_centavos=centavos,
        moeda=MOEDA_ACEITA,
        disponivel=_disponibilidade(oferta_escolhida, produto),
        origem="j",
        erro=None,
    )


def extrair_preco_dom(
    html: str,
    seletores: SeletoresDeProduto,
    *,
    teto_centavos: int = TETO_CENTAVOS,
) -> ResultadoExtracao:
    """Extrai preço de uma página de produto por seletores de DOM.

    Caminho para lojas que não publicam JSON-LD. Hoje só a Amazon — as outras
    três lojas suportadas publicam, e para elas `extrair_preco` continua sendo o
    caminho certo (contrato schema.org é estável; seletor de DOM não é).

    A ordem das checagens é deliberada: bloqueio ANTES de preço. Uma página de
    desafio anti-bot não tem preço, e diagnosticar isso como "sem preço" manda o
    operador procurar defeito no lugar errado.
    """
    if parece_pagina_de_bloqueio(html):
        return ResultadoExtracao(None, None, False, None, ERRO_BLOQUEIO)

    arvore = HTMLParser(html or "")

    # Prova positiva de que a página do produto chegou. Ver SeletoresDeProduto.
    if arvore.css_first(seletores.prova_de_produto) is None:
        return ResultadoExtracao(None, None, False, None, ERRO_BLOQUEIO)

    bruto = None
    for seletor in seletores.preco:
        bruto = _texto_do_seletor(arvore, seletor, None)
        if bruto:
            break

    if not bruto:
        # Sem preço: antes de culpar o layout, checar se a loja está dizendo que
        # não há oferta. São diagnósticos opostos e só um condena a fonte.
        if seletores.marcador_sem_oferta and arvore.css_first(
            seletores.marcador_sem_oferta
        ) is not None:
            return ResultadoExtracao(None, None, False, None, ERRO_SEM_OFERTA)
        return ResultadoExtracao(None, None, False, None, "sem_preco_no_dom")

    if not _confere_moeda(bruto, seletores.marcadores_de_moeda):
        # Mesmo motivo do caminho JSON-LD: gravar um número em moeda
        # estrangeira como se fosse real é pior do que não gravar nada.
        return ResultadoExtracao(None, None, False, None, "moeda_nao_suportada")

    centavos = normalizar_para_centavos(
        _primeiro_valor_monetario(bruto), teto_centavos=teto_centavos
    )
    if centavos is None:
        return ResultadoExtracao(None, None, False, None, "preco_invalido")

    return ResultadoExtracao(
        preco_centavos=centavos,
        moeda=MOEDA_ACEITA,
        disponivel=_disponibilidade_dom(arvore, seletores),
        origem="d",
        erro=None,
    )


def extrair_preco_do_estado(
    html: str, padrao: str, *, teto_centavos: int = TETO_CENTAVOS
) -> int | None:
    """Preço a partir do estado JSON que a página embute, por expressão regular.

    Terceiro caminho, e o mais estreito dos três. Existe porque a Pichau publica
    o preço à vista APENAS no estado serializado — ele não chega ao DOM
    renderizado, então não há seletor de CSS que o alcance, e o JSON-LD dela traz
    outro número (o parcelado).

    Regex e não `json.loads` de propósito: o estado vem escapado dentro de uma
    string JSON (`\\"avista\\":4699.99`), aninhado em vários níveis de uma árvore
    de framework. Desserializar tudo para chegar a uma chave seria caro e frágil
    de um jeito diferente; casar a CHAVE pelo nome é frágil de um jeito honesto e
    fácil de consertar.

    `padrao` precisa ter exatamente um grupo de captura, com o número.
    """
    achado = re.search(padrao, html or "")
    if achado is None:
        return None
    return normalizar_para_centavos(achado.group(1), teto_centavos=teto_centavos)


def _confere_moeda(texto: str, marcadores: tuple[str, ...]) -> bool:
    """True quando o texto do preço prova que o valor é em real.

    Sem marcador configurado a checagem é dispensada — a loja pode publicar o
    número puro, e nesse caso quem garante a moeda é o domínio da loja.
    """
    if not marcadores:
        return True
    minusculo = texto.lower()
    return any(marca in minusculo for marca in marcadores)


def _disponibilidade_dom(arvore: HTMLParser, seletores: SeletoresDeProduto) -> bool:
    """Estoque a partir do DOM.

    O texto manda quando é explícito sobre falta ("Temporariamente sem
    estoque"), porque negação é afirmação forte. Na ausência dele, vale o botão
    de compra: ele some quando o produto acaba, e não depende de redação.

    Sem nenhum dos dois sinais, devolve True — chegamos aqui com um preço
    válido lido da página, e afirmar indisponível contra essa evidência seria
    inventar o oposto do que a página mostra.
    """
    if seletores.disponibilidade:
        texto = _texto_do_seletor(arvore, seletores.disponibilidade, None)
        if texto:
            minusculo = texto.lower()
            if any(m in minusculo for m in seletores.marcadores_indisponivel):
                return False

    if seletores.botao_de_compra:
        return arvore.css_first(seletores.botao_de_compra) is not None

    return True


def _documentos_jsonld(arvore: HTMLParser) -> list[Any]:
    """Todos os blocos ld+json que fizeram parse, na ordem do documento.

    Cada bloco é decodificado isoladamente: um JSON malformado no meio da
    página não pode impedir a leitura dos demais.
    """
    documentos: list[Any] = []
    for no in arvore.css(SELETOR_JSONLD):
        bruto = no.text(deep=True, strip=False)
        if not bruto or not bruto.strip():
            continue
        try:
            documentos.append(json.loads(_limpar_bloco(bruto)))
        except (ValueError, RecursionError):
            logger.warning("bloco ld+json ignorado por erro de parse")
            continue
    return documentos


def _limpar_bloco(bruto: str) -> str:
    """Remove envelopes e sujeira que impedem o `json.loads`."""
    texto = bruto.strip()

    # Envelope de comentário HTML e CDATA, com o "//" que alguns CMS colocam.
    for marcador in ("<!--", "-->", "<![CDATA[", "]]>", "/*<![CDATA[*/", "/*]]>*/"):
        texto = texto.replace(marcador, "")
    texto = texto.strip()
    if texto.startswith("//"):
        texto = texto[2:].strip()

    texto = entidades_html.unescape(texto)
    return _remover_virgulas_penduradas(texto)


def _remover_virgulas_penduradas(texto: str) -> str:
    """Apaga a vírgula que antecede `}` ou `]`.

    Percorre caractere a caractere respeitando strings JSON: uma vírgula
    dentro de `"descrição, }"` não pode ser tocada.
    """
    saida: list[str] = []
    dentro_de_texto = False
    escapado = False

    for caractere in texto:
        if dentro_de_texto:
            saida.append(caractere)
            if escapado:
                escapado = False
            elif caractere == "\\":
                escapado = True
            elif caractere == '"':
                dentro_de_texto = False
            continue

        if caractere == '"':
            dentro_de_texto = True
            saida.append(caractere)
            continue

        if caractere in "}]":
            indice = len(saida) - 1
            while indice >= 0 and saida[indice].isspace():
                indice -= 1
            if indice >= 0 and saida[indice] == ",":
                del saida[indice:]

        saida.append(caractere)

    return "".join(saida)


def _tipos(no: dict) -> list[str]:
    """`@type` normalizado para lista. Pode chegar como string ou como lista."""
    tipo = no.get("@type")
    if isinstance(tipo, str):
        return [tipo]
    if isinstance(tipo, list):
        return [item for item in tipo if isinstance(item, str)]
    return []


def _eh_do_tipo(no: Any, tipos_aceitos: frozenset[str]) -> bool:
    """Pertencimento, nunca igualdade: `@type` pode ser lista."""
    if not isinstance(no, dict):
        return False
    return any(tipo.strip().lower() in tipos_aceitos for tipo in _tipos(no))


def _primeiro_produto(documento: Any) -> dict | None:
    """Busca recursiva pelo primeiro nó de produto na ordem do documento.

    Cobre de uma vez objeto raiz, array raiz, envelope `@graph`, `mainEntity`
    e `itemListElement[].item` — sem código específico para cada forma.
    """
    if isinstance(documento, dict):
        if _eh_do_tipo(documento, TIPOS_PRODUTO):
            return documento
        for valor in documento.values():
            achado = _primeiro_produto(valor)
            if achado is not None:
                return achado
    elif isinstance(documento, list):
        for item in documento:
            achado = _primeiro_produto(item)
            if achado is not None:
                return achado
    return None


def _todos_os_produtos(documento: Any, achados: list[dict] | None = None) -> list[dict]:
    """Todos os nós de produto, na ordem do documento.

    Irmão de `_primeiro_produto`: a página de produto quer o primeiro, a de
    listagem quer todos.
    """
    if achados is None:
        achados = []
    if isinstance(documento, dict):
        if _eh_do_tipo(documento, TIPOS_PRODUTO):
            achados.append(documento)
        for valor in documento.values():
            _todos_os_produtos(valor, achados)
    elif isinstance(documento, list):
        for item in documento:
            _todos_os_produtos(item, achados)
    return achados


def _sku_do_item(produto: dict, url: str | None) -> str | None:
    """Identificador estável do item.

    Prefere o `sku` declarado; sem ele, usa o último trecho numérico da URL,
    que é o padrão de loja brasileira (`/produto/725947/slug`).
    """
    for campo in ("sku", "mpn", "productID"):
        valor = produto.get(campo)
        if isinstance(valor, (str, int)) and str(valor).strip():
            return str(valor).strip()
    if not url:
        return None
    trechos = [t for t in urlsplit(url).path.split("/") if t]
    for trecho in reversed(trechos):
        if trecho.isdigit():
            return trecho
    return trechos[-1] if trechos else None


def extrair_lista(html: str, *, teto_centavos: int = TETO_CENTAVOS) -> list[ItemDeLista]:
    """Extrai todos os produtos de uma página de listagem.

    Função pura, como `extrair_preco`. Itens sem preço legível ou em moeda
    diferente de BRL são descartados — um catálogo com preço errado é pior que
    um catálogo incompleto.
    """
    arvore = HTMLParser(html or "")
    itens: list[ItemDeLista] = []
    vistos: set[str] = set()

    for documento in _documentos_jsonld(arvore):
        for produto in _todos_os_produtos(documento):
            ofertas = _ofertas_do_produto(produto)
            if not ofertas:
                continue

            candidatos = []
            for oferta in ofertas:
                centavos, moeda = _valor_da_oferta(oferta, teto_centavos)
                if centavos is not None:
                    candidatos.append((centavos, moeda, oferta))
            if not candidatos:
                continue

            centavos, moeda, oferta = min(candidatos, key=lambda item: item[0])
            if moeda is not None and moeda.strip().upper() != MOEDA_ACEITA:
                logger.warning("item de listagem em moeda %r ignorado", moeda)
                continue

            url = oferta.get("url") or produto.get("url")
            url = url.strip() if isinstance(url, str) else None
            sku = _sku_do_item(produto, url)

            chave = sku or url or ""
            if chave and chave in vistos:
                continue      # a mesma página costuma repetir o item em carrosséis
            if chave:
                vistos.add(chave)

            nome = produto.get("name")
            itens.append(
                ItemDeLista(
                    imagem=_primeira_imagem(produto.get("image")),
                    sku=sku,
                    nome=entidades_html.unescape(nome.strip()) if isinstance(nome, str) else None,
                    url=url,
                    preco_centavos=centavos,
                    # listagem não publica availability: desconhecido, não True
                    disponivel=_disponibilidade_opcional(oferta),
                )
            )
    return itens


def extrair_lista_dom(
    html: str,
    seletores: SeletoresDeListagem,
    *,
    base_url: str = "",
    teto_centavos: int = TETO_CENTAVOS,
) -> list[ItemDeLista]:
    """Extrai produtos de uma listagem que NÃO publica JSON-LD.

    Função pura, como as demais. Usa o parser de DOM — nunca regex sobre HTML.
    O contrato aqui é o layout da loja, não o schema.org: mais frágil por
    natureza, e por isso testado contra fixture congelada.
    """
    arvore = HTMLParser(html or "")
    itens: list[ItemDeLista] = []
    vistos: set[str] = set()

    for cartao in arvore.css(seletores.item):
        no_url = cartao.css_first(seletores.url)
        url = _absolutizar(no_url.attributes.get("href") if no_url else None, base_url)
        if not url:
            continue

        bruto = _texto_do_seletor(cartao, seletores.preco, None) or ""
        esgotado = any(
            marcador in bruto.lower() for marcador in seletores.marcadores_indisponivel
        )
        centavos = (
            None if esgotado
            else _centavos_do_seletor(cartao, seletores.preco, teto_centavos)
        )
        if centavos is None and not esgotado:
            continue   # nem preço nem sinal de esgotado: cartão que não é produto

        sku = _sku_da_url(url)
        chave = sku or url
        if chave in vistos:
            continue
        vistos.add(chave)

        itens.append(
            ItemDeLista(
                sku=sku,
                nome=_texto_do_seletor(cartao, seletores.nome, seletores.nome_atributo),
                url=url,
                preco_centavos=centavos,
                # Aqui a listagem INFORMA estoque: preço legível significa
                # comprável; o marcador significa esgotado.
                disponivel=not esgotado,
                preco_tabela_centavos=(
                    None if esgotado
                    else _centavos_do_seletor(
                        cartao, seletores.preco_tabela, teto_centavos
                    )
                ),
                imagem=_imagem_do_seletor(cartao, seletores.imagem, base_url),
            )
        )
    return itens


def _primeira_imagem(bruto) -> str | None:
    """`image` do schema.org vem como string, lista ou objeto ImageObject."""
    if isinstance(bruto, str):
        return _url_de_imagem(bruto)
    if isinstance(bruto, list):
        for candidato in bruto:
            achado = _primeira_imagem(candidato)
            if achado:
                return achado
        return None
    if isinstance(bruto, dict):
        return _primeira_imagem(bruto.get("url") or bruto.get("contentUrl"))
    return None


def _url_de_imagem(bruto: str | None, base_url: str = "") -> str | None:
    """Só aceita https: imagem em http quebraria a página por conteúdo misto."""
    url = _absolutizar(bruto, base_url) if base_url else (bruto or "").strip()
    if not url:
        return None
    return url if url.startswith("https://") else None


def _imagem_do_seletor(cartao, seletor: str | None, base_url: str) -> str | None:
    if not seletor:
        return None
    no = cartao.css_first(seletor)
    if no is None:
        return None
    # lazy-load costuma esconder o endereço real em data-src
    for atributo in ("src", "data-src", "data-original"):
        valor = no.attributes.get(atributo)
        achado = _url_de_imagem(valor, base_url)
        if achado:
            return achado
    return None


def _texto_do_seletor(cartao, seletor: str, atributo: str | None) -> str | None:
    no = cartao.css_first(seletor)
    if no is None:
        return None
    if atributo:
        valor = no.attributes.get(atributo)
        if valor and valor.strip():
            return entidades_html.unescape(valor.strip())
    texto = no.text(deep=True, strip=True)
    return entidades_html.unescape(texto) if texto else None


def _centavos_do_seletor(cartao, seletor: str | None, teto_centavos: int) -> int | None:
    """Lê o primeiro nó do seletor e normaliza o texto para centavos.

    O texto costuma vir sujo — "R$ 589,90à vista no Pix" — e é justamente por
    isso que `normalizar_para_centavos` descarta tudo que não é dígito ou
    separador em vez de tentar casar um padrão.
    """
    if not seletor:
        return None
    no = cartao.css_first(seletor)
    if no is None:
        return None
    bruto = no.text(deep=True, strip=True)
    if not bruto:
        return None
    # "R$ 589,90à vista no Pix" -> corta no primeiro trecho monetário
    corte = _primeiro_valor_monetario(bruto)
    return normalizar_para_centavos(corte, teto_centavos=teto_centavos)


def _primeiro_valor_monetario(texto: str) -> str:
    """Recorta o primeiro número com separador decimal do texto.

    Percorre caractere a caractere: começa no primeiro dígito e para quando o
    número termina. Sem regex, e sem depender do símbolo da moeda.
    """
    inicio = next((i for i, c in enumerate(texto) if c.isdigit()), None)
    if inicio is None:
        return texto
    fim = inicio
    while fim < len(texto) and (texto[fim].isdigit() or texto[fim] in ".,"):
        fim += 1
    # não deixa um separador solto no fim ("589,90à" -> "589,90")
    while fim > inicio and texto[fim - 1] in ".,":
        fim -= 1
    return texto[inicio:fim]


def _absolutizar(href: str | None, base_url: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    if not base_url:
        return None
    partes = urlsplit(base_url)
    if not href.startswith("/"):
        href = "/" + href
    return f"{partes.scheme}://{partes.netloc}{href}"


def _sku_da_url(url: str) -> str | None:
    trechos = [t for t in urlsplit(url).path.split("/") if t]
    for trecho in trechos:
        if trecho.isdigit():
            return trecho
    return trechos[-1] if trechos else None


def _disponibilidade_opcional(oferta: dict) -> bool | None:
    """Como `_disponibilidade`, mas devolve None quando o campo não existe."""
    bruto = oferta.get("availability")
    if not isinstance(bruto, str) or not bruto.strip():
        return None
    termo = bruto.strip().rstrip("/").rsplit("/", 1)[-1].strip().lower()
    if termo in DISPONIBILIDADE_DISPONIVEL:
        return True
    if termo in DISPONIBILIDADE_INDISPONIVEL:
        return False
    return None


def _ofertas_do_produto(produto: dict) -> list[dict]:
    """Normaliza `offers` para uma lista de dicionários."""
    ofertas = produto.get("offers")
    if isinstance(ofertas, dict):
        return [ofertas]
    if isinstance(ofertas, list):
        return [item for item in ofertas if isinstance(item, dict)]
    return []


def _especificacao(oferta: dict) -> dict | None:
    """`priceSpecification`, que às vezes vem embrulhado em lista."""
    especificacao = oferta.get("priceSpecification")
    if isinstance(especificacao, list):
        especificacao = next(
            (item for item in especificacao if isinstance(item, dict)), None
        )
    return especificacao if isinstance(especificacao, dict) else None


def _valor_da_oferta(
    oferta: dict, teto_centavos: int
) -> tuple[int | None, str | None]:
    """Preço em centavos e moeda declarada de uma única oferta."""
    especificacao = _especificacao(oferta)

    if _eh_do_tipo(oferta, frozenset({"aggregateoffer"})):
        bruto = oferta.get("lowPrice")
        if bruto is None:
            bruto = oferta.get("price")
    else:
        bruto = oferta.get("price")
        if bruto is None and especificacao is not None:
            bruto = especificacao.get("price")

    moeda = oferta.get("priceCurrency")
    if moeda is None and especificacao is not None:
        moeda = especificacao.get("priceCurrency")
    if not isinstance(moeda, str):
        moeda = None

    if not isinstance(bruto, (str, int, float)):
        return None, moeda
    return normalizar_para_centavos(bruto, teto_centavos=teto_centavos), moeda


def _disponibilidade(oferta: dict, produto: dict) -> bool:
    """Traduz `availability` para booleano.

    Campo ausente significa disponível: a maioria das lojas só publica o campo
    quando o produto acabou.
    """
    bruto = oferta.get("availability")
    if bruto is None:
        especificacao = _especificacao(oferta)
        if especificacao is not None:
            bruto = especificacao.get("availability")
    if bruto is None:
        bruto = produto.get("availability")
    if not isinstance(bruto, str) or not bruto.strip():
        return True

    termo = bruto.strip().rstrip("/").rsplit("/", 1)[-1].strip().lower()
    if termo in DISPONIBILIDADE_DISPONIVEL:
        return True
    if termo in DISPONIBILIDADE_INDISPONIVEL:
        return False

    logger.warning("availability desconhecida: %r — assumindo disponível", bruto)
    return True


# ----------------------------------------------------------------------------
# Fallback
# ----------------------------------------------------------------------------


def _fallback(
    arvore: HTMLParser, erro: str, teto_centavos: int
) -> ResultadoExtracao:
    """Open Graph e microdata, nessa ordem, quando o JSON-LD não serviu."""
    tentativas = (
        ("g", 'meta[property="product:price:amount"]', "content", _moeda_opengraph),
        ("m", '[itemprop="price"]', "content", _moeda_microdata),
    )

    for origem, seletor, atributo, ler_moeda in tentativas:
        no = arvore.css_first(seletor)
        if no is None:
            continue

        bruto = no.attributes.get(atributo)
        if bruto is None:
            bruto = no.text(deep=True, strip=True)
        if not bruto:
            continue

        centavos = normalizar_para_centavos(bruto, teto_centavos=teto_centavos)
        if centavos is None:
            continue

        moeda = ler_moeda(arvore)
        if moeda is not None and moeda.strip().upper() != MOEDA_ACEITA:
            return ResultadoExtracao(None, moeda, False, None, "moeda_nao_suportada")

        return ResultadoExtracao(centavos, MOEDA_ACEITA, True, origem, None)

    return ResultadoExtracao(None, None, False, None, erro)


def _moeda_opengraph(arvore: HTMLParser) -> str | None:
    no = arvore.css_first('meta[property="product:price:currency"]')
    return no.attributes.get("content") if no is not None else None


def _moeda_microdata(arvore: HTMLParser) -> str | None:
    no = arvore.css_first('[itemprop="priceCurrency"]')
    if no is None:
        return None
    return no.attributes.get("content") or no.text(deep=True, strip=True) or None
