"""Entrypoint do ciclo de coleta, executado pelo GitHub Actions.

O cron dispara de 15 em 15 minutos, mas a coleta pesada só acontece quando
`sistema/controle.ultimaColetaEm` mostra que o intervalo real já passou. É isso
que torna o sistema imune ao agendador do GitHub, que atrasa e pula execuções
sob carga: a cadência efetiva vira "pelo menos a cada 6h" em vez de "exatamente
às 00h, 06h, 12h, 18h", que o GitHub não garante.

O tempo decorrido NUNCA é calculado a partir do horário agendado — só a partir
de `sistema/controle`.
"""

import asyncio
import logging
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from coletor import alertas, config
from coletor.coleta import LimitadorPorHost, coletar_fontes, validar_fonte_pendente
from coletor.notificador import NotificadorTelegram
from coletor.repositorio import Repositorio, inicializar

logger = logging.getLogger("coletor")


@dataclass(frozen=True)
class LeituraDoCiclo:
    """Adapta um `ResultadoColeta` ao que a máquina de estados espera."""

    loja: str
    url: str
    preco_centavos: int | None
    disponivel: bool
    suspeito: bool


async def processar_pendentes(
    repositorio: Repositorio,
    cliente: httpx.AsyncClient,
    limitador: LimitadorPorHost,
    cfg: config.Config,
) -> int:
    """Fila por status: valida as fontes recém-cadastradas pelo front.

    Roda em TODA execução, independente do intervalo — é o que faz o cadastro
    responder em até 15 minutos em vez de até 6 horas.
    """
    pendentes = repositorio.listar_fontes_pendentes()
    if not pendentes:
        return 0

    logger.info("validando %d fonte(s) pendente(s)", len(pendentes))
    for fonte in pendentes:
        try:
            resultado = await validar_fonte_pendente(
                fonte,
                cliente,
                repositorio,
                user_agent=cfg.user_agent,
                teto_centavos=cfg.teto_centavos,
                limitador=limitador,
            )
            if resultado.preco_centavos is None:
                logger.warning("fonte %s reprovada: %s", fonte.url, resultado.erro)
            else:
                logger.info(
                    "fonte %s aprovada: %d centavos (%s)",
                    fonte.url, resultado.preco_centavos, resultado.origem,
                )
        except Exception:
            # Uma fonte problemática não pode impedir a validação das outras.
            logger.exception("erro ao validar %s", fonte.url)
    return len(pendentes)


def avaliar_alertas(
    repositorio: Repositorio, notificador, coletas, agora: datetime
) -> int:
    """Agrupa as leituras por produto e roda a máquina de estados em cada um."""
    por_produto = defaultdict(list)
    for coleta in coletas:
        if coleta.fonte is not None:
            por_produto[coleta.fonte.produto_ref.path].append(coleta)

    notificados = 0
    for itens in por_produto.values():
        produto_ref = itens[0].fonte.produto_ref
        try:
            produto = repositorio.carregar_produto(produto_ref)
            if produto is None or not produto.ativo:
                continue

            # O coletor é a autoridade sobre o gatilho: as rules aceitam
            # qualquer inteiro >= alvo vindo do cliente.
            repositorio.corrigir_gatilho(
                produto,
                alertas.calcular_gatilho(
                    produto.preco_alvo_centavos, produto.tolerancia_pct
                ),
            )

            leituras = [
                LeituraDoCiclo(
                    loja=item.fonte.loja,
                    url=item.fonte.url,
                    preco_centavos=item.resultado.preco_centavos,
                    disponivel=item.resultado.disponivel,
                    suspeito=item.suspeito,
                )
                for item in itens
            ]
            decisao = alertas.processar(
                produto, leituras, agora, repositorio, notificador
            )
            logger.info(
                "produto %s: %s -> %s%s",
                produto.nome, decisao.motivo, decisao.novo_estado,
                " (notificado)" if decisao.notificar else "",
            )
            if decisao.notificar:
                notificados += 1
        except Exception:
            logger.exception("erro ao avaliar alerta de %s", produto_ref.path)
    return notificados


def esta_na_hora(
    ultima: datetime | None, agora: datetime, intervalo_horas: int
) -> bool:
    """True quando o intervalo real já passou. `None` significa primeira vez."""
    if ultima is None:
        return True
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return (agora - ultima) >= timedelta(hours=intervalo_horas)


async def executar_ciclo(
    repositorio: Repositorio | None = None,
    notificador=None,
    cfg: config.Config | None = None,
    agora: datetime | None = None,
) -> dict:
    """Um ciclo completo. Devolve um resumo do que aconteceu."""
    cfg = cfg or config.carregar()
    agora = agora or datetime.now(timezone.utc)
    repositorio = repositorio or Repositorio()
    if notificador is None:
        notificador = NotificadorTelegram(cfg.telegram_bot_token, cfg.telegram_chat_id)

    resumo = {"pendentes": 0, "coletadas": 0, "notificados": 0, "coletou": False}
    limitador = LimitadorPorHost()

    async with httpx.AsyncClient(follow_redirects=True) as cliente:
        # Passo 2 — pendentes SEMPRE.
        resumo["pendentes"] = await processar_pendentes(
            repositorio, cliente, limitador, cfg
        )

        # Passos 3 e 4 — a cadência vem de sistema/controle, nunca do cron.
        ultima = repositorio.ler_controle()
        if not esta_na_hora(ultima, agora, cfg.intervalo_coleta_horas):
            proxima = ultima + timedelta(hours=cfg.intervalo_coleta_horas)
            logger.info(
                "fora da janela de coleta (última em %s, próxima a partir de %s)",
                ultima, proxima,
            )
            return resumo

        fontes = repositorio.listar_fontes_ativas()
        logger.info("coletando %d fonte(s) ativa(s)", len(fontes))
        if fontes:
            coletas = await coletar_fontes(
                fontes,
                repositorio,
                user_agent=cfg.user_agent,
                limiar_sanidade=cfg.limiar_sanidade,
                teto_centavos=cfg.teto_centavos,
                cliente=cliente,
                notificador=notificador,
                limitador=limitador,
            )
            resumo["coletadas"] = len(coletas)
            resumo["notificados"] = avaliar_alertas(
                repositorio, notificador, coletas, agora
            )

        repositorio.gravar_controle(agora)
        resumo["coletou"] = True

    return resumo


def principal() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    cfg = config.carregar()

    try:
        inicializar(cfg.firebase_sa_base64)
    except Exception:
        # DECISÃO: a seção 11.2 manda sair com 0, mas isso vale para falha de
        # COLETA. Credencial inválida sairia verde para sempre e o sistema
        # morreria em silêncio, então erro de inicialização sai vermelho.
        logger.exception("falha ao inicializar o Admin SDK")
        return 1

    try:
        resumo = asyncio.run(executar_ciclo(cfg=cfg))
    except Exception:
        logger.exception("ciclo abortado por erro inesperado")
        return 1

    logger.info(
        "fim do ciclo: %d pendente(s), %d coleta(s), %d notificação(ões), coletou=%s",
        resumo["pendentes"], resumo["coletadas"],
        resumo["notificados"], resumo["coletou"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(principal())
