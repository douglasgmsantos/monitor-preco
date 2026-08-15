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
from google.api_core.exceptions import FailedPrecondition, PermissionDenied

from coletor import alertas, config
from coletor.coleta import LimitadorPorHost, coletar_fontes, validar_fonte_pendente
from coletor.notificador import NotificadorTelegram, notificador_do_usuario
from coletor.raspagem import Categoria, raspar
from coletor.repositorio import Repositorio, inicializar, uid_do_produto

logger = logging.getLogger("coletor")


@dataclass(frozen=True)
class LeituraDoCiclo:
    """Adapta um `ResultadoColeta` ao que a máquina de estados espera."""

    loja: str
    url: str
    preco_centavos: int | None
    disponivel: bool
    suspeito: bool
    imagem: str | None = None
    # Motivo da ausência de preço. `alertas.esgotada` usa isto para separar
    # "a loja disse que acabou" de "não conseguimos ler" — sem ele, um n8n
    # fora do ar viraria "esgotou" em todos os produtos de uma vez.
    erro: str | None = None


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
    repositorio: Repositorio, notificador, coletas, agora: datetime,
    margem_media_pct: int = 10,
    repetir_no_range: bool = alertas.REPETIR_NO_RANGE_PADRAO,
) -> int:
    """Agrupa as leituras por produto e roda a máquina de estados em cada um."""
    por_produto = defaultdict(list)
    for coleta in coletas:
        if coleta.fonte is not None:
            por_produto[coleta.fonte.produto_ref.path].append(coleta)

    notificados = 0
    # Um notificador por USUÁRIO, resolvido uma vez e reaproveitado: sem o
    # cache, cada produto do mesmo dono custaria uma leitura da config.
    notificadores: dict[str, object] = {}

    def notificador_para(produto_ref):
        uid = uid_do_produto(produto_ref)
        if uid is None:
            return notificador
        if uid not in notificadores:
            notificadores[uid] = notificador_do_usuario(
                repositorio.ler_config_telegram(uid), notificador
            )
        return notificadores[uid]

    for itens in por_produto.values():
        produto_ref = itens[0].fonte.produto_ref
        try:
            produto = repositorio.carregar_produto(produto_ref)
            if produto is None or not produto.ativo:
                continue

            # Não há gatilho a corrigir: ele É o `valorMaxCentavos` que o
            # usuário gravou, e as rules já garantem que é inteiro > 0. O campo
            # derivado que existia aqui era fonte de divergência, não de
            # segurança.

            leituras = [
                LeituraDoCiclo(
                    loja=item.fonte.loja,
                    url=item.fonte.url,
                    preco_centavos=item.resultado.preco_centavos,
                    disponivel=item.resultado.disponivel,
                    suspeito=item.suspeito,
                    imagem=item.resultado.imagem,
                    erro=item.resultado.erro,
                )
                for item in itens
            ]
            decisao = alertas.processar(
                produto, leituras, agora, repositorio,
                notificador_para(produto_ref),
                margem_media_pct=margem_media_pct,
                repetir_no_range=repetir_no_range,
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


async def _raspar_se_for_hora(
    repositorio: Repositorio,
    cliente: httpx.AsyncClient,
    limitador: LimitadorPorHost,
    cfg: config.Config,
    agora: datetime,
) -> dict | None:
    """Raspa o catálogo quando o intervalo próprio já passou.

    Portão separado do da coleta: o catálogo muda de composição em dias, o
    preço muda em horas. Raspar junto com a coleta gastaria requisições nas
    lojas sem informação nova.
    """
    if not cfg.categorias_raspagem:
        return None

    ultima = repositorio.ler_controle_raspagem()
    if not esta_na_hora(ultima, agora, cfg.intervalo_raspagem_horas):
        logger.info("fora da janela de raspagem (última em %s)", ultima)
        return None

    categorias = [Categoria.da_url(url) for url in cfg.categorias_raspagem]
    logger.info("raspando %d categoria(s)", len(categorias))
    try:
        total = await raspar(
            categorias,
            repositorio,
            user_agent=cfg.user_agent,
            teto_centavos=cfg.teto_centavos,
            cliente=cliente,
            limitador=limitador,
        )
    except Exception:
        logger.exception("raspagem abortada; a coleta segue normalmente")
        return None

    repositorio.gravar_controle_raspagem(agora)
    logger.info(
        "catálogo: %d categoria(s), %d itens (%d novos, %d alterados, %d iguais)",
        total["categorias"], total["itens"],
        total["novos"], total["alterados"], total["inalterados"],
    )
    return total


def esta_na_hora(
    ultima: datetime | None, agora: datetime, intervalo_horas: int
) -> bool:
    """True quando o intervalo real já passou. `None` significa primeira vez."""
    return _ja_passou(ultima, agora, timedelta(hours=intervalo_horas))


def esta_no_minuto(
    ultima: datetime | None, agora: datetime, intervalo_minutos: int
) -> bool:
    """Idem, para a coleta — que é medida em minutos desde que passou a 30 min."""
    return _ja_passou(ultima, agora, timedelta(minutes=intervalo_minutos))


def _ja_passou(ultima: datetime | None, agora: datetime, intervalo: timedelta) -> bool:
    if ultima is None:
        return True
    if ultima.tzinfo is None:
        ultima = ultima.replace(tzinfo=timezone.utc)
    return (agora - ultima) >= intervalo


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

    resumo = {"pendentes": 0, "coletadas": 0, "notificados": 0,
              "coletou": False, "forcada": False, "catalogo": None}
    limitador = LimitadorPorHost()

    async with httpx.AsyncClient(follow_redirects=True) as cliente:
        # Passo 2 — pendentes SEMPRE.
        resumo["pendentes"] = await processar_pendentes(
            repositorio, cliente, limitador, cfg
        )

        # Raspagem de catálogo — cadência própria, bem mais lenta que a coleta.
        # Descobrir que produtos existem muda devagar; o preço deles, não.
        resumo["catalogo"] = await _raspar_se_for_hora(
            repositorio, cliente, limitador, cfg, agora
        )

        # Passos 3 e 4 — a cadência vem de sistema/controle, nunca do cron.
        ultima = repositorio.ler_controle()
        na_janela = esta_no_minuto(ultima, agora, cfg.intervalo_coleta_minutos)
        if not na_janela and not cfg.forcar_coleta:
            proxima = ultima + timedelta(minutes=cfg.intervalo_coleta_minutos)
            logger.info(
                "fora da janela de coleta (última em %s, próxima a partir de %s)",
                ultima, proxima,
            )
            return resumo
        if not na_janela:
            logger.info("coleta FORÇADA: fora da janela, rodando a pedido")

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
                repositorio, notificador, coletas, agora, cfg.margem_media_pct,
                cfg.alerta_repete_no_range,
            )

        # Coleta forçada FORA da janela não mexe no relógio.
        #
        # `sistema/controle` é o que define a cadência real. Uma execução manual
        # às 12h05 que gravasse ali empurraria a próxima automática para 12h35,
        # deslocando o agendamento inteiro — um teste passaria a ter efeito
        # colateral sobre a produção. Forçar dentro da janela grava normalmente:
        # ali a coleta ia acontecer de qualquer jeito.
        if na_janela:
            repositorio.gravar_controle(agora)
        else:
            logger.info("coleta forçada: relógio de cadência preservado")
        resumo["coletou"] = True
        resumo["forcada"] = not na_janela

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
    except FailedPrecondition as erro:
        mensagem = str(erro)
        if "currently building" in mensagem:
            # Transitório: o índice existe e está sendo construído. A próxima
            # execução do cron (15 min) passa. Não é motivo para job vermelho.
            logger.warning(
                "índice ainda em construção; nada a fazer além de esperar. "
                "A próxima execução do cron resolve."
            )
            return 0
        logger.error(
            "consulta sem índice. Publique com "
            "`firebase deploy --only firestore:indexes`.\nDetalhe: %s", mensagem
        )
        return 1
    except PermissionDenied:
        # O Admin SDK ignora as security rules, então isto NUNCA é problema de
        # firestore.rules — é IAM. A service account autenticou (o token foi
        # emitido) mas não tem papel de acesso ao Firestore.
        logger.error(
            "PERMISSION_DENIED no Firestore. O Admin SDK ignora as security "
            "rules, então o problema é IAM, não firestore.rules.\n"
            "Conserto: em console.cloud.google.com/iam-admin/iam conceda à "
            "service account registrada acima o papel 'Cloud Datastore User' "
            "(roles/datastore.user). A linha 'service account: …' no início "
            "deste log diz qual conta precisa do papel."
        )
        return 1
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
