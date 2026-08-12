"""Registro das lojas suportadas na PÁGINA DE PRODUTO.

Fonte única de verdade para três perguntas que antes estavam espalhadas:

    1. que lojas o cadastro aceita?
    2. como buscar a página de cada uma?
    3. como extrair o preço dela?

O espelho desta tabela no front é `frontend/src/lojas.js`. As duas listas
precisam concordar: o front recusa a URL antes de gravar, o coletor recusa
depois de buscar. Mudou aqui, muda lá.

NÃO CONFUNDIR com `raspagem.LOJAS`, que é outra coisa: aquela tabela é sobre
páginas de LISTAGEM (categoria), para montar o catálogo. Esta é sobre a página
de um produto, para medir preço. A mesma loja pode estar em uma e não na outra.

DUAS ESTRATÉGIAS DE EXTRAÇÃO
----------------------------
`jsonld`  a loja publica `application/ld+json` com Product + Offer. Contrato
          schema.org: estável, versionado, e a loja tem interesse próprio em
          manter (é o que alimenta o Google Shopping). É o caminho preferido, e
          três das quatro lojas usam.

`dom`     seletores de CSS na marra. Só quando não há JSON-LD, porque depende do
          layout e quebra sem aviso. Hoje: apenas Amazon.

O QUE FOI MEDIDO EM 2026-08-12
------------------------------
Rodando `extrair_preco` contra os templates em `coletor/templates/`:

    Pichau     R$ 5.529,40  InStock   origem=j     ← JSON-LD, zero código novo
    Terabyte   R$ 4.599,90  InStock   origem=j     ← JSON-LD, zero código novo
    Amazon     sem_jsonld                          ← precisou de DOM

E buscando as três ao vivo, desta máquina:

    Amazon     HTTP 200 com UA de navegador (1,25 MB, tudo no lugar)
               HTTP 200 com UA honesto      (221 KB, NENHUMA marcação de produto)
    Pichau     HTTP 403 nos dois casos — página de bloqueio própria
    Terabyte   HTTP 403 nos dois casos — "Just a moment..." (Cloudflare)

O 403 de Pichau e Terabyte foi medido DESTA máquina, e não vale como veredito de
produção: reputação de IP é por IP, e a raspagem do Terabyte funciona hoje a
partir do runner. Só a produção decide. Ver README, seção de lojas.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from coletor.parser import (
    TETO_CENTAVOS, ResultadoExtracao, SeletoresDeProduto, extrair_preco,
    extrair_preco_dom,
)

# ---------------------------------------------------------------------------
# Cabeçalhos
# ---------------------------------------------------------------------------
#
# O projeto se identifica com User-Agent honesto (`MonitorPrecos/1.0`) e essa é
# a posição padrão. A Amazon é a exceção, e é uma exceção MEDIDA, não uma
# conveniência: com o UA honesto ela responde 200 com 221 KB e nenhuma marcação
# de produto — sem título, sem preço, sem botão. Não existe versão "honesta" da
# página para ler. A escolha real é buscar como navegador ou não suportar a
# loja.
#
# Registrado explicitamente para que a próxima pessoa saiba que isto foi uma
# decisão, não descuido.

CABECALHOS_DE_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
}


# ---------------------------------------------------------------------------
# Seletores por loja
# ---------------------------------------------------------------------------

# Verificados contra `coletor/templates/amazon-produto-detalhes.html` E contra
# uma busca ao vivo em 2026-08-12: os dois casaram valor por valor.
#
# O escopo em `#corePrice_feature_div` é o detalhe que importa. Um
# `span.a-offscreen` solto casa 22 nós na página, e o segundo deles é
# R$ 7.499,00 — outro preço, de outro bloco. Sem o escopo, o coletor gravaria
# um número plausível e errado, que é a pior espécie de bug.
SELETORES_AMAZON = SeletoresDeProduto(
    preco="#corePrice_feature_div span.a-offscreen",
    prova_de_produto="#productTitle",
    preco_tabela=".basisPrice .a-offscreen",
    disponibilidade="#availability",
    botao_de_compra="#add-to-cart-button",
)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Loja:
    nome: str
    dominios: tuple[str, ...]
    estrategia: str                      # "jsonld" | "dom"
    seletores: SeletoresDeProduto | None = None
    cabecalhos: dict[str, str] = field(default_factory=dict)
    # Anotação honesta do que se sabe sobre buscar esta loja de fora. Aparece no
    # log quando a coleta falha, para o motivo não virar adivinhação.
    observacao: str = ""

    def __post_init__(self) -> None:
        if self.estrategia == "dom" and self.seletores is None:
            raise ValueError(f"{self.nome}: estratégia dom exige seletores")


LOJAS: tuple[Loja, ...] = (
    Loja(
        nome="KaBuM",
        dominios=("kabum.com.br",),
        estrategia="jsonld",
        observacao="em produção desde o início; único caso confirmado no runner",
    ),
    Loja(
        nome="Terabyte Shop",
        dominios=("terabyteshop.com.br",),
        estrategia="jsonld",
        observacao=(
            "JSON-LD verificado no template (R$ 4.599,90). Cloudflare recusou "
            "esta máquina em 2026-08-12; a raspagem de listagem funciona no runner"
        ),
    ),
    Loja(
        nome="Pichau",
        dominios=("pichau.com.br",),
        estrategia="jsonld",
        observacao=(
            "JSON-LD verificado no template (R$ 5.529,40). Já recusou o runner "
            "com 403 em produção uma vez — reabilitada a pedido, o parsing nunca "
            "foi o problema"
        ),
    ),
    Loja(
        nome="Amazon",
        dominios=("amazon.com.br",),
        estrategia="dom",
        seletores=SELETORES_AMAZON,
        cabecalhos=CABECALHOS_DE_NAVEGADOR,
        observacao=(
            "sem JSON-LD; DOM verificado no template e ao vivo. EXIGE cabeçalhos "
            "de navegador: com UA honesto a página vem sem marcação de produto"
        ),
    ),
)


def loja_de(url_ou_host: str) -> Loja | None:
    """Loja suportada para uma URL (ou host), ou None se não é suportada."""
    host = _host(url_ou_host)
    if not host:
        return None
    for loja in LOJAS:
        if any(host == d or host.endswith("." + d) for d in loja.dominios):
            return loja
    return None


def _host(url_ou_host: str) -> str:
    bruto = (url_ou_host or "").strip().lower()
    if not bruto:
        return ""
    if "//" in bruto:
        bruto = urlsplit(bruto).netloc
    return bruto.split("@")[-1].split(":")[0].removeprefix("www.")


def extrair_da_loja(
    url: str, html: str, *, teto_centavos: int = TETO_CENTAVOS
) -> ResultadoExtracao:
    """Extrai o preço com a estratégia registrada para a loja da URL.

    Loja fora do registro cai no caminho JSON-LD. Isso é rede de segurança para
    fonte antiga: o cadastro só oferece lojas do registro, mas fontes gravadas
    antes desta tabela existir continuam no banco, e recusá-las aqui apagaria
    histórico de gente que não fez nada de errado.
    """
    loja = loja_de(url)
    if loja is not None and loja.estrategia == "dom":
        return extrair_preco_dom(
            html, loja.seletores, teto_centavos=teto_centavos
        )
    return extrair_preco(html, teto_centavos=teto_centavos)


def cabecalhos_de(url: str, user_agent_padrao: str) -> dict[str, str]:
    """Cabeçalhos para buscar esta URL.

    O padrão é o User-Agent honesto configurado. Só quem está no registro com
    cabeçalhos próprios recebe outro tratamento — e hoje é só a Amazon.
    """
    loja = loja_de(url)
    if loja is not None and loja.cabecalhos:
        return dict(loja.cabecalhos)
    return {"User-Agent": user_agent_padrao}
