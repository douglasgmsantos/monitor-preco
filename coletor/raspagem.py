"""Raspagem de catálogo: varre páginas de listagem e alimenta o catálogo.

Processo SEPARADO do de verificação de preço, e com propósito diferente:

  raspagem  -> descobrir quais produtos existem e quanto custam "de tabela"
  coleta    -> preço real, histórico e alerta dos produtos que o usuário segue

A separação não é organizacional, é factual. O preço da LISTAGEM é o preço de
tabela: medido em 2026-08-10, ficava de 10% a 31% ACIMA do preço da página do
produto na mesma loja e no mesmo instante. Usar o preço do catálogo para
disparar alerta faria o gatilho comparar contra um número inflado, e o alerta
simplesmente nunca dispararia — falha silenciosa, sem erro em log nenhum.

Por isso o catálogo guarda apenas o instantâneo. A série histórica começa
quando o usuário favorita, e vem da página do produto, pelo caminho que já
existe (`produto` + `fonte` + `coleta.py`).
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

import httpx

from coletor.coleta import LimitadorPorHost, buscar_html
from coletor.parser import (
    ItemDeLista, SeletoresDeListagem, extrair_lista, extrair_lista_dom,
)

logger = logging.getLogger(__name__)

# A KaBuM ignora page_size e devolve 10 por página. Não há como pedir mais.
PAGINAS_MAXIMAS = 40
PARAMETRO_DE_PAGINA = "page_number"

# ---------------------------------------------------------------------------
# Registro de lojas
#
# Duas estratégias de extração, escolhidas por medição e não por preferência:
#
#   JSON-LD  — contrato estável (schema.org), mas a loja precisa publicar.
#   DOM      — funciona onde não há JSON-LD, ao custo de depender do layout.
#              Os seletores são DADOS: quando a loja muda o HTML, conserta-se
#              esta tabela e o teste com fixture congelada avisa alto.
#
# `preco_confiavel` registra um fato medido em 2026-08-10: o preço da listagem
# da KaBuM é o de TABELA, de 10% a 31% acima do preço da página do produto. O
# do Terabyte é o de venda, porque a loja publica os dois.
# ---------------------------------------------------------------------------

SELETORES_TERABYTE = SeletoresDeListagem(
    item="div.product-item",
    nome="a.product-item__name",
    nome_atributo="title",
    url="a.product-item__name",
    preco=".product-item__new-price span",
    preco_tabela=".product-item__old-price del span",
    imagem="img.image-thumbnail",
)


@dataclass(frozen=True)
class Loja:
    host: str
    seletores: SeletoresDeListagem | None   # None = extrair do JSON-LD
    preco_confiavel: bool
    itens_por_pagina: int


LOJAS = {
    "kabum.com.br": Loja("kabum.com.br", None, preco_confiavel=False, itens_por_pagina=10),
    "terabyteshop.com.br": Loja(
        "terabyteshop.com.br", SELETORES_TERABYTE,
        preco_confiavel=True, itens_por_pagina=300,
    ),
}


def loja_de(host: str) -> Loja | None:
    host = host.lower().replace("www.", "")
    for chave, loja in LOJAS.items():
        if host == chave or host.endswith("." + chave):
            return loja
    return None


@dataclass(frozen=True)
class Categoria:
    """Uma listagem a raspar."""

    loja: str
    nome: str
    url: str

    @staticmethod
    def da_url(url: str) -> "Categoria":
        """Deriva loja e categoria da própria URL, para a configuração ser só
        uma lista de endereços."""
        partes = urlsplit(url)
        loja = partes.netloc.lower().replace("www.", "")
        trechos = [t for t in partes.path.split("/") if t]
        nome = trechos[-1] if trechos else (partes.query or "raiz")
        return Categoria(loja=loja, nome=nome, url=url)


def url_da_pagina(url: str, pagina: int) -> str:
    """Acrescenta `page_number` preservando o que já existe na query."""
    if pagina <= 1:
        return url
    partes = urlsplit(url)
    consulta = [p for p in partes.query.split("&") if p and not p.startswith(f"{PARAMETRO_DE_PAGINA}=")]
    consulta.append(f"{PARAMETRO_DE_PAGINA}={pagina}")
    return urlunsplit(
        (partes.scheme, partes.netloc, partes.path, "&".join(consulta), partes.fragment)
    )


FRACAO_MINIMA_ACEITAVEL = 80   # por cento do total declarado


def total_declarado(html: str) -> int | None:
    """Total de produtos que a página diz ter, quando ela diz.

    Heurística deliberada e best-effort: procura `"total":N` no estado que a
    página embute. Não é contrato de ninguém — serve só para diagnóstico, e por
    isso um valor ausente ou estranho não é erro.
    """
    marca = '"total":'
    posicao = html.find(marca)
    if posicao == -1:
        return None
    digitos = ""
    for caractere in html[posicao + len(marca):]:
        if caractere.isdigit():
            digitos += caractere
        elif digitos or not caractere.isspace():
            break
    return int(digitos) if digitos.isdigit() and digitos else None


def _avisar_se_truncado(categoria: "Categoria", html: str, extraidos: int) -> None:
    """Grita quando a página rende bem menos do que declara ter.

    Página com scroll infinito entrega uma fração dos produtos e a varredura
    termina achando que acabou. Sem este aviso, o catálogo fica incompleto em
    silêncio — que é a pior forma de ficar incompleto.
    """
    total = total_declarado(html)
    if not total or not extraidos:
        return
    if extraidos * 100 < total * FRACAO_MINIMA_ACEITAVEL:
        logger.warning(
            "categoria %s TRUNCADA: %d de %d produtos (%.0f%%). A página carrega "
            "o resto por scroll e a URL não pagina — prefira subcategorias "
            "menores que o teto de renderização.",
            categoria.nome, extraidos, total, 100 * extraidos / total,
        )


async def raspar_categoria(
    categoria: Categoria,
    cliente: httpx.AsyncClient,
    *,
    user_agent: str,
    teto_centavos: int,
    limitador: LimitadorPorHost,
    paginas_maximas: int = PAGINAS_MAXIMAS,
) -> list[ItemDeLista]:
    """Percorre as páginas até parar de aparecer SKU novo.

    Parar por repetição, e não por um número fixo de páginas, é o que faz a
    varredura terminar sozinha quando a categoria acaba — lojas costumam
    devolver a última página indefinidamente em vez de 404.
    """
    vistos: set[str] = set()
    itens: list[ItemDeLista] = []

    for pagina in range(1, paginas_maximas + 1):
        endereco = url_da_pagina(categoria.url, pagina)
        async with limitador.aguardar(endereco):
            html, erro = await buscar_html(cliente, endereco, user_agent=user_agent)

        if erro is not None:
            logger.warning("página %d de %s falhou: %s", pagina, categoria.nome, erro)
            break

        loja = loja_de(categoria.loja)
        if loja is not None and loja.seletores is not None:
            achados = extrair_lista_dom(
                html or "", loja.seletores,
                base_url=endereco, teto_centavos=teto_centavos,
            )
        else:
            achados = extrair_lista(html or "", teto_centavos=teto_centavos)

        if pagina == 1:
            _avisar_se_truncado(categoria, html or "", len(achados))

        novos = [i for i in achados if i.sku and i.sku not in vistos]
        if not novos:
            logger.info(
                "categoria %s terminou na página %d (%d itens)",
                categoria.nome, pagina, len(itens),
            )
            break

        vistos.update(item.sku for item in novos)
        itens.extend(novos)
    else:
        logger.warning(
            "categoria %s atingiu o teto de %d páginas — pode haver mais itens",
            categoria.nome, paginas_maximas,
        )

    return itens


async def raspar(
    categorias: list[Categoria],
    repositorio,
    *,
    user_agent: str,
    teto_centavos: int,
    cliente: httpx.AsyncClient | None = None,
    limitador: LimitadorPorHost | None = None,
) -> dict:
    """Raspa todas as categorias e grava o catálogo. Falha em uma não derruba
    as demais."""
    limitador = limitador or LimitadorPorHost()
    proprio = cliente is None
    cliente = cliente or httpx.AsyncClient(follow_redirects=True)

    total = {"categorias": 0, "itens": 0, "novos": 0, "alterados": 0, "inalterados": 0}
    try:
        for categoria in categorias:
            try:
                itens = await raspar_categoria(
                    categoria,
                    cliente,
                    user_agent=user_agent,
                    teto_centavos=teto_centavos,
                    limitador=limitador,
                )
                if not itens:
                    logger.warning("categoria %s não devolveu itens", categoria.nome)
                    continue
                resumo = repositorio.salvar_catalogo(
                    categoria.loja, categoria.nome, itens
                )
                total["categorias"] += 1
                total["itens"] += len(itens)
                for chave in ("novos", "alterados", "inalterados"):
                    total[chave] += resumo[chave]
                logger.info(
                    "categoria %s: %d itens (%d novos, %d alterados, %d iguais)",
                    categoria.nome, len(itens),
                    resumo["novos"], resumo["alterados"], resumo["inalterados"],
                )
            except Exception:
                logger.exception("falha ao raspar a categoria %s", categoria.nome)
    finally:
        if proprio:
            await cliente.aclose()

    return total
