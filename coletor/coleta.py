"""Busca HTTP e orquestração de um ciclo de coleta.

Zero lógica de parsing aqui: este módulo baixa o HTML, chama `extrair_preco` e
decide o que persistir. Quem entende de schema.org é o `parser`.

A persistência entra por injeção de dependência (`RepositorioDeColeta`), não
por import direto do `repositorio`. É isso que permite testar a fase inteira
com `respx` e um repositório de mentira, sem Firestore e sem emulador.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from coletor.lojas import cabecalhos_de, extrair_da_loja
from coletor.parser import ERROS_DE_PARSE, ResultadoExtracao

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 15.0
TENTATIVAS_EXTRA = 2  # 1 tentativa original + 2 retentativas
ESPERA_INICIAL_SEGUNDOS = 1.0
INTERVALO_MINIMO_POR_HOST_SEGUNDOS = 2.0
LIMITE_FALHAS_SEGUIDAS = 5


class Fonte(Protocol):
    """O que a coleta precisa saber de uma fonte.

    Tipagem estrutural: o `repositorio` da fase 2 devolve objetos com estes
    atributos. Campos em snake_case aqui, camelCase no Firestore — a tradução
    é responsabilidade do repositório.
    """

    id: str
    loja: str
    url: str
    falhas_seguidas: int
    ultimo_preco_centavos: int | None


class RepositorioDeColeta(Protocol):
    """A fatia do repositório que a coleta consome."""

    def registrar_leitura(
        self, fonte: Fonte, resultado: ResultadoExtracao, suspeito: bool
    ) -> None: ...

    def marcar_fonte_valida(
        self, fonte: Fonte, preco_centavos: int, origem: str
    ) -> None: ...

    def marcar_fonte_invalida(self, fonte: Fonte, motivo: str) -> None: ...

    def registrar_tentativa_de_validacao(self, fonte: Fonte, motivo: str) -> None: ...

    def marcar_fonte_com_erro(self, fonte: Fonte) -> None: ...


class Notificador(Protocol):
    def enviar(self, mensagem: str) -> None: ...


@dataclass(frozen=True)
class ResultadoColeta:
    fonte_id: str
    resultado: ResultadoExtracao
    suspeito: bool
    fonte: Fonte | None = None


# ----------------------------------------------------------------------------
# Limitação de taxa por host
# ----------------------------------------------------------------------------


class LimitadorPorHost:
    """Uma requisição por vez por domínio, com espaçamento mínimo entre elas.

    O relógio e o `sleep` entram por parâmetro para que os testes não gastem
    dois segundos de verdade a cada requisição.
    """

    def __init__(
        self,
        intervalo_segundos: float = INTERVALO_MINIMO_POR_HOST_SEGUNDOS,
        dormir=asyncio.sleep,
        relogio=None,
    ) -> None:
        import time

        self._intervalo = intervalo_segundos
        self._dormir = dormir
        self._relogio = relogio or time.monotonic
        self._travas: dict[str, asyncio.Lock] = {}
        self._ultimo_acesso: dict[str, float] = {}

    @asynccontextmanager
    async def aguardar(self, url: str):
        host = urlsplit(url).netloc.lower()
        trava = self._travas.setdefault(host, asyncio.Lock())
        async with trava:
            anterior = self._ultimo_acesso.get(host)
            if anterior is not None:
                falta = self._intervalo - (self._relogio() - anterior)
                if falta > 0:
                    await self._dormir(falta)
            try:
                yield
            finally:
                self._ultimo_acesso[host] = self._relogio()


# ----------------------------------------------------------------------------
# Busca HTTP
# ----------------------------------------------------------------------------


def _eh_5xx(status: int) -> bool:
    return 500 <= status <= 599


async def buscar_html(
    cliente: httpx.AsyncClient,
    url: str,
    *,
    user_agent: str,
    dormir=asyncio.sleep,
    tentativas_extra: int = TENTATIVAS_EXTRA,
    cabecalhos: dict[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """Baixa a página. Devolve (html, erro) — exatamente um dos dois é None.

    Retenta apenas em erro de rede e 5xx. Um 404 é resposta definitiva do
    servidor: retentar só gasta o orçamento de requisições da loja.

    `cabecalhos` substitui o par padrão quando a loja exige mais que um
    User-Agent. Quem decide é `lojas.cabecalhos_de`, e hoje só a Amazon precisa:
    com o UA honesto ela devolve 200 com uma página sem marcação de produto.
    """
    espera = ESPERA_INICIAL_SEGUNDOS
    ultimo_erro = "erro_desconhecido"
    cabecalhos = cabecalhos or {"User-Agent": user_agent}

    for tentativa in range(tentativas_extra + 1):
        try:
            resposta = await cliente.get(
                url,
                headers=cabecalhos,
                timeout=TIMEOUT_SEGUNDOS,
                follow_redirects=True,
            )
        except httpx.TimeoutException:
            ultimo_erro = "timeout"
        except httpx.HTTPError:
            ultimo_erro = "erro_rede"
        else:
            if resposta.status_code == 200:
                return resposta.text, None
            if _eh_5xx(resposta.status_code):
                ultimo_erro = f"http_{resposta.status_code}"
            else:
                # 4xx não se resolve com insistência
                return None, f"http_{resposta.status_code}"

        if tentativa < tentativas_extra:
            await dormir(espera)
            espera *= 2

    return None, ultimo_erro


# ----------------------------------------------------------------------------
# Guarda de sanidade
# ----------------------------------------------------------------------------


def avaliar_suspeito(
    novo_centavos: int, ultimo_centavos: int | None, limiar: str
) -> bool:
    """True quando o novo preço diverge do anterior além do limiar.

    Comparação em inteiros: o limiar "0.70" vira 700 milésimos e a divisão
    nunca acontece. `|novo - ultimo| / ultimo > limiar` reescrito como
    `|novo - ultimo| * 1000 > ultimo * limiar_milesimos`.
    """
    if ultimo_centavos is None or ultimo_centavos <= 0:
        return False
    try:
        limiar_milesimos = int(Decimal(str(limiar)) * 1000)
    except (InvalidOperation, ValueError):
        logger.warning("LIMIAR_SANIDADE inválido: %r — guarda desligada", limiar)
        return False
    diferenca = abs(novo_centavos - ultimo_centavos)
    return diferenca * 1000 > ultimo_centavos * limiar_milesimos


# ----------------------------------------------------------------------------
# Ciclo de coleta
# ----------------------------------------------------------------------------


async def coletar_fonte(
    fonte: Fonte,
    cliente: httpx.AsyncClient,
    repositorio: RepositorioDeColeta,
    *,
    user_agent: str,
    limiar_sanidade: str,
    teto_centavos: int,
    limitador: LimitadorPorHost,
    notificador: Notificador | None = None,
    dormir=asyncio.sleep,
) -> ResultadoColeta:
    """Coleta uma fonte e grava exatamente uma leitura, dando certo ou errado."""
    async with limitador.aguardar(fonte.url):
        html, erro_http = await buscar_html(
            cliente,
            fonte.url,
            user_agent=user_agent,
            dormir=dormir,
            cabecalhos=cabecalhos_de(fonte.url, user_agent),
        )

    if erro_http is not None:
        resultado = ResultadoExtracao(None, None, False, None, erro_http)
    else:
        resultado = extrair_da_loja(
            fonte.url, html or "", teto_centavos=teto_centavos
        )

    suspeito = False
    if resultado.preco_centavos is not None:
        suspeito = avaliar_suspeito(
            resultado.preco_centavos, fonte.ultimo_preco_centavos, limiar_sanidade
        )

    # Uma leitura por coleta, sempre — inclusive na falha, com preço nulo.
    repositorio.registrar_leitura(fonte, resultado, suspeito)

    if resultado.preco_centavos is None:
        _tratar_falha(fonte, repositorio, resultado, notificador)
    # No sucesso não há escrita extra: `registrar_leitura` já gravou
    # ultimoPrecoCentavos, ultimaColetaEm e zerou falhasSeguidas na mesma
    # transação. Chamar `marcar_fonte_valida` aqui seria uma quarta escrita,
    # contra as três que a seção 8.1 orça por coleta.

    return ResultadoColeta(fonte.id, resultado, suspeito, fonte)


def _tratar_falha(
    fonte: Fonte,
    repositorio: RepositorioDeColeta,
    resultado: ResultadoExtracao,
    notificador: Notificador | None,
) -> None:
    """Contabiliza a falha e desliga a fonte na quinta seguida."""
    # `registrar_leitura` já incrementou o contador no armazenamento; aqui
    # usamos o valor projetado para decidir o desligamento.
    falhas = fonte.falhas_seguidas + 1
    if falhas < LIMITE_FALHAS_SEGUIDAS:
        return

    repositorio.marcar_fonte_com_erro(fonte)
    if notificador is not None:
        notificador.enviar(
            f"⚠️ Fonte desativada após {falhas} falhas seguidas\n\n"
            f"{fonte.loja}\n{fonte.url}\n\nÚltimo motivo: {resultado.erro}"
        )


async def coletar_fontes(
    fontes: list[Fonte],
    repositorio: RepositorioDeColeta,
    *,
    user_agent: str,
    limiar_sanidade: str,
    teto_centavos: int,
    cliente: httpx.AsyncClient | None = None,
    notificador: Notificador | None = None,
    limitador: LimitadorPorHost | None = None,
    dormir=asyncio.sleep,
) -> list[ResultadoColeta]:
    """Coleta todas as fontes. Falha em uma nunca derruba as demais."""
    limitador = limitador or LimitadorPorHost(dormir=dormir)
    proprio = cliente is None
    cliente = cliente or httpx.AsyncClient(follow_redirects=True)

    async def uma(fonte: Fonte) -> ResultadoColeta | None:
        try:
            return await coletar_fonte(
                fonte,
                cliente,
                repositorio,
                user_agent=user_agent,
                limiar_sanidade=limiar_sanidade,
                teto_centavos=teto_centavos,
                limitador=limitador,
                notificador=notificador,
                dormir=dormir,
            )
        except Exception:
            logger.exception("falha inesperada coletando %s", fonte.url)
            return None

    try:
        coletados = await asyncio.gather(*(uma(fonte) for fonte in fontes))
    finally:
        if proprio:
            await cliente.aclose()

    return [item for item in coletados if item is not None]


async def validar_fonte_pendente(
    fonte: Fonte,
    cliente: httpx.AsyncClient,
    repositorio: RepositorioDeColeta,
    *,
    user_agent: str,
    teto_centavos: int,
    limitador: LimitadorPorHost,
    dormir=asyncio.sleep,
) -> ResultadoExtracao:
    """Fila por status: promove a fonte a `ok` ou a reprova com o motivo.

    É o substituto assíncrono da validação síncrona que existiria se houvesse
    um servidor de API.
    """
    async with limitador.aguardar(fonte.url):
        html, erro_http = await buscar_html(
            cliente,
            fonte.url,
            user_agent=user_agent,
            dormir=dormir,
            cabecalhos=cabecalhos_de(fonte.url, user_agent),
        )

    if erro_http is not None:
        resultado = ResultadoExtracao(None, None, False, None, erro_http)
    else:
        resultado = extrair_da_loja(
            fonte.url, html or "", teto_centavos=teto_centavos
        )

    if resultado.preco_centavos is None:
        motivo = resultado.erro or "preco_invalido"
        if motivo in ERROS_DE_PARSE:
            # A página é ilegível: insistir não muda nada.
            repositorio.marcar_fonte_invalida(fonte, motivo)
        else:
            # Transporte (403, timeout, rede): a URL pode estar boa e a loja ter
            # bloqueado o IP do runner. Mantém pendente e tenta de novo, até o
            # limite — só então condena.
            tentativas = fonte.falhas_seguidas + 1
            if tentativas >= LIMITE_FALHAS_SEGUIDAS:
                repositorio.marcar_fonte_invalida(fonte, motivo)
            else:
                repositorio.registrar_tentativa_de_validacao(fonte, motivo)
    else:
        repositorio.marcar_fonte_valida(
            fonte, resultado.preco_centavos, resultado.origem or "j"
        )
    return resultado
