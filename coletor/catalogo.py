"""Entrypoint da RASPAGEM DE CATÁLOGO. Separado do ciclo de coleta.

Antes isto rodava dentro de `executar_ciclo`, com portão próprio de 24h. Saiu
de lá em 2026-08-15 por dois motivos:

1. **São trabalhos diferentes.** A coleta lê ~10 páginas de produto a cada 2h e
   é o que dispara alerta; a raspagem varre 10 categorias com paginação, uma vez
   por dia, e só alimenta a vitrine. Juntas, a lenta atrasava a rápida — e uma
   exceção na raspagem enchia o log do ciclo que importa.

2. **Ampliar o catálogo além da KaBuM exige outro IP.** Terabyte, Amazon e
   Pichau recusam o datacenter do runner; só respondem para o n8n. Com a
   raspagem colada ao ciclo, esse caminho não existia. Separada e disparável por
   `workflow_dispatch`, o n8n pode capturar as listagens e chamar isto.

O PARSER CONTINUA EM PYTHON, de propósito. A tentação é portar a raspagem para
um nó de Code do n8n e "migrar de vez", mas `raspagem.py` tem paginação que para
por repetição de SKU, normalização de preço em centavos e a regra dos 7 dias na
vitrine — tudo coberto por testes. Reescrever em JavaScript dentro de um nó
seria trocar código testado por código sem teste, num sandbox onde nem `require`
funciona. O n8n manda executar; quem interpreta continua aqui.
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone

import httpx
from google.api_core.exceptions import FailedPrecondition, PermissionDenied

from coletor import config
from coletor.coleta import LimitadorPorHost
from coletor.raspagem import Categoria, raspar
from coletor.repositorio import Repositorio, inicializar

logger = logging.getLogger("coletor.catalogo")


def esta_na_hora(ultima, agora, intervalo_horas: int) -> bool:
    """True quando o intervalo real já passou. `None` significa primeira vez.

    Mesma regra do ciclo de coleta: o tempo decorrido vem de `sistema/`, nunca
    do horário agendado — o GitHub atrasa e pula execuções.
    """
    if ultima is None:
        return True
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return (agora - ultima).total_seconds() >= intervalo_horas * 3600


async def raspar_catalogo(
    repositorio: Repositorio | None = None,
    cfg: config.Config | None = None,
    agora: datetime | None = None,
    forcar: bool = False,
) -> dict | None:
    """Uma varredura completa. Devolve o resumo, ou None se não era hora."""
    cfg = cfg or config.carregar()
    agora = agora or datetime.now(timezone.utc)
    repositorio = repositorio or Repositorio()

    if not cfg.categorias_raspagem:
        logger.info("CATEGORIAS_RASPAGEM vazio — nada a raspar")
        return None

    ultima = repositorio.ler_controle_raspagem()
    if not forcar and not esta_na_hora(ultima, agora, cfg.intervalo_raspagem_horas):
        logger.info("fora da janela de raspagem (última em %s)", ultima)
        return None
    if forcar and ultima is not None:
        logger.info("raspagem FORÇADA (última em %s)", ultima)

    categorias = [Categoria.da_url(url) for url in cfg.categorias_raspagem]
    logger.info("raspando %d categoria(s)", len(categorias))

    limitador = LimitadorPorHost()
    async with httpx.AsyncClient(follow_redirects=True) as cliente:
        total = await raspar(
            categorias,
            repositorio,
            user_agent=cfg.user_agent,
            teto_centavos=cfg.teto_centavos,
            cliente=cliente,
            limitador=limitador,
        )

    repositorio.gravar_controle_raspagem(agora)
    logger.info(
        "catálogo: %d categoria(s), %d itens (%d novos, %d alterados, %d iguais)",
        total["categorias"], total["itens"],
        total["novos"], total["alterados"], total["inalterados"],
    )
    return total


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
        # Mesma regra do coletor: falha de COLETA sai verde, falha de
        # CREDENCIAL sai vermelha. Credencial inválida em silêncio mataria o
        # catálogo sem ninguém notar.
        logger.exception("falha ao inicializar o Admin SDK")
        return 1

    try:
        asyncio.run(raspar_catalogo(cfg=cfg, forcar=cfg.forcar_raspagem))
    except FailedPrecondition as erro:
        logger.error("consulta sem índice: %s", erro)
        return 1
    except PermissionDenied:
        logger.error(
            "PERMISSION_DENIED no Firestore. O Admin SDK ignora as security "
            "rules, então é IAM: conceda 'Cloud Datastore User' à service "
            "account registrada no início deste log."
        )
        return 1
    except Exception:
        # A raspagem NÃO pode derrubar nada além dela mesma. Antes ela morava no
        # ciclo de coleta e um erro aqui enchia o log do que importa; agora ela
        # falha sozinha, no próprio workflow.
        logger.exception("raspagem abortada")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(principal())
