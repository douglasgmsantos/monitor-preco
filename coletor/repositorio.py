"""Único módulo do projeto que fala com o Firestore.

Nenhum outro módulo importa `firebase_admin`. Quem precisa de persistência
recebe uma instância de `Repositorio` por injeção.

Dinheiro é sempre inteiro de centavos, na entrada e na saída. Não existe
divisão por 100 aqui — só na formatação de exibição.
"""

import base64
import binascii
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import firebase_admin
import google.auth.credentials
from firebase_admin import credentials, firestore

logger = logging.getLogger(__name__)

COLECAO_USUARIOS = "usuarios"
COLECAO_PRODUTOS = "produtos"
COLECAO_FONTES = "fontes"
COLECAO_HISTORICO = "historico"
COLECAO_DIARIO = "diario"
# Decisão A: o controle de cadência é GLOBAL, em coleção raiz. O intervalo de
# coleta pertence ao coletor, não a cada usuário.
COLECAO_SISTEMA = "sistema"
DOC_CONTROLE = "controle"
DOC_CONTROLE_RASPAGEM = "controle_raspagem"

# Catálogo: global, não por usuário. Escrito só pelo Admin SDK, lido por
# qualquer usuário autenticado. Guarda apenas o INSTANTÂNEO — o preço da
# listagem é o "de" (tabela), 10% a 31% acima do preço real da página do
# produto, então ele não serve para histórico nem para alerta. A série de
# verdade começa quando o usuário favorita, e vem da página do produto.
# Caixa de correio do n8n: HTML capturado por fora, um documento por fonte.
#
# Coleção RAIZ e sem regra em firestore.rules — o catch-all nega tudo, e é assim
# que tem de ficar. Só o Admin SDK escreve e lê. O id é o da fonte, então cada
# captura sobrescreve a anterior: são ~7 documentos para sempre, sem rotina de
# limpeza para falhar em silêncio. Ver `coletor/captura.py`.
COLECAO_PAGINAS = "paginas"

COLECAO_CATALOGO = "catalogo"
COLECAO_ITENS = "itens"
COLECAO_INDICE = "indice"

LIMITE_DO_LOTE = 450  # o Firestore aceita 500 operações; margem de segurança

# Quantos dias um item sobrevive na vitrine sem ser visto de novo.
#
# Existe porque a renderização das listagens é INSTÁVEL: a mesma categoria do
# Terabyte devolveu 47 itens numa requisição e 25 na seguinte. Reescrever a
# vitrine com o que veio agora apagaria produtos que continuam à venda. Então a
# vitrine ACUMULA, e um item só sai depois de sumir por vários dias seguidos —
# que é o sinal de que ele foi mesmo descontinuado.
DIAS_NA_VITRINE = 7

STATUS_PENDENTE = "pendente"
STATUS_OK = "ok"
STATUS_INVALIDA = "invalida"

DIAS_DA_MEDIA = 30


# ----------------------------------------------------------------------------
# Modelos
# ----------------------------------------------------------------------------


@dataclass
class Fonte:
    """Uma URL rastreada. Campos em snake_case; no Firestore são camelCase."""

    id: str
    ref: Any
    produto_ref: Any
    loja: str
    url: str
    status: str
    motivo_invalida: str | None
    falhas_seguidas: int
    com_erro: bool
    ultimo_preco_centavos: int | None
    ultima_coleta_em: datetime | None


@dataclass
class Produto:
    id: str
    ref: Any
    nome: str
    preco_alvo_centavos: int
    tolerancia_pct: int
    preco_gatilho_centavos: int
    estado: str
    ultimo_alerta_em: datetime | None
    ultimo_preco_alertado_centavos: int | None
    ativo: bool


# ----------------------------------------------------------------------------
# Chaves de bucket
# ----------------------------------------------------------------------------


def chave_mes(instante: datetime) -> str:
    """"2026-08" — sufixo do documento de histórico bruto."""
    return instante.strftime("%Y-%m")


def chave_ano(instante: datetime) -> str:
    return instante.strftime("%Y")


def chave_dia(instante: datetime) -> str:
    """"d20260810" — sem hífens, com prefixo.

    Field path do Firestore com caractere especial exige escaping por crase, e
    isso é fonte silenciosa de bug em update aninhado. O `d` também garante que
    a chave nunca comece com dígito.
    """
    return "d" + instante.strftime("%Y%m%d")


def id_bucket_historico(fonte_id: str, instante: datetime) -> str:
    return f"{fonte_id}_{chave_mes(instante)}"


def id_bucket_diario(fonte_id: str, instante: datetime) -> str:
    return f"{fonte_id}_{chave_ano(instante)}"


# ----------------------------------------------------------------------------
# Inicialização
# ----------------------------------------------------------------------------


class _CredencialEmulador(credentials.Base):
    """Credencial anônima: o emulador não valida token."""

    def get_credential(self):
        return google.auth.credentials.AnonymousCredentials()


def _credencial_de_base64(sa_base64: str) -> tuple[credentials.Certificate, dict]:
    """Decodifica a service account em memória. Nunca toca o disco.

    Devolve também os metadados NÃO sigilosos (client_email, project_id), que
    são o que permite diagnosticar erro de IAM sem expor a chave.
    """
    try:
        bruto = base64.b64decode(sa_base64, validate=False)
        dados = json.loads(bruto)
    except (binascii.Error, ValueError) as erro:
        raise ValueError("FIREBASE_SA_BASE64 inválida") from erro
    metadados = {
        "client_email": dados.get("client_email"),
        "project_id": dados.get("project_id"),
        "private_key_id": (dados.get("private_key_id") or "")[:8],
    }
    return credentials.Certificate(dados), metadados


def inicializar(
    sa_base64: str | None = None, project_id: str | None = None
) -> firebase_admin.App:
    """Inicializa o Admin SDK. Usa credencial anônima se o emulador estiver ativo."""
    usando_emulador = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))

    if usando_emulador:
        credencial = _CredencialEmulador()
        projeto = project_id or os.environ.get("GCLOUD_PROJECT") or "demo-monitor"
        logger.info("usando o emulador do Firestore em %s", os.environ["FIRESTORE_EMULATOR_HOST"])
    else:
        if not sa_base64:
            raise ValueError("FIREBASE_SA_BASE64 ausente e emulador não configurado")
        credencial, metadados = _credencial_de_base64(sa_base64)
        projeto = project_id or metadados["project_id"]
        # client_email e project_id não são segredo, e sem eles é impossível
        # diagnosticar PERMISSION_DENIED sem abrir a chave.
        logger.info(
            "service account: %s · projeto: %s · chave: %s…",
            metadados["client_email"], metadados["project_id"],
            metadados["private_key_id"],
        )

    opcoes = {"projectId": projeto} if projeto else None
    try:
        return firebase_admin.initialize_app(credencial, opcoes)
    except ValueError:
        # já inicializado neste processo
        return firebase_admin.get_app()


# ----------------------------------------------------------------------------
# Repositório
# ----------------------------------------------------------------------------


class Repositorio:
    def __init__(self, db=None, app: firebase_admin.App | None = None) -> None:
        self._db = db if db is not None else firestore.client(app)

    # --- leitura de fontes --------------------------------------------------

    def _fonte_de_snapshot(self, snapshot) -> Fonte:
        dados = snapshot.to_dict() or {}
        return Fonte(
            id=snapshot.id,
            ref=snapshot.reference,
            produto_ref=snapshot.reference.parent.parent,
            loja=dados.get("loja", ""),
            url=dados.get("url", ""),
            status=dados.get("status", STATUS_PENDENTE),
            motivo_invalida=dados.get("motivoInvalida"),
            falhas_seguidas=dados.get("falhasSeguidas", 0),
            com_erro=bool(dados.get("comErro", False)),
            ultimo_preco_centavos=dados.get("ultimoPrecoCentavos"),
            ultima_coleta_em=dados.get("ultimaColetaEm"),
        )

    def listar_fontes_pendentes(self) -> list[Fonte]:
        """Fontes recém-cadastradas pelo front, aguardando validação."""
        consulta = self._db.collection_group(COLECAO_FONTES).where(
            filter=firestore.FieldFilter("status", "==", STATUS_PENDENTE)
        )
        return [self._fonte_de_snapshot(s) for s in consulta.stream()]

    def listar_fontes_ativas(self) -> list[Fonte]:
        """Fontes coletáveis: status ok, sem erro e de produto ativo.

        A consulta filtra `status` e `comErro` no servidor — o índice composto
        publicado atende pelo prefixo. O `ativo` do produto é aplicado aqui em
        Python, com um cache por produto: o produto precisa ser lido de todo
        jeito na etapa de alerta, então não custa leitura extra.
        """
        consulta = (
            self._db.collection_group(COLECAO_FONTES)
            .where(filter=firestore.FieldFilter("status", "==", STATUS_OK))
            .where(filter=firestore.FieldFilter("comErro", "==", False))
        )
        fontes = [self._fonte_de_snapshot(s) for s in consulta.stream()]

        ativos: dict[str, bool] = {}
        resultado = []
        for fonte in fontes:
            caminho = fonte.produto_ref.path
            if caminho not in ativos:
                snapshot = fonte.produto_ref.get()
                dados = snapshot.to_dict() or {}
                ativos[caminho] = bool(snapshot.exists and dados.get("ativo", False))
            if ativos[caminho]:
                resultado.append(fonte)
        return resultado

    # --- promoção e reprovação de fonte ------------------------------------

    def marcar_fonte_valida(
        self, fonte: Fonte, preco_centavos: int, origem: str
    ) -> None:
        fonte.ref.update(
            {
                "status": STATUS_OK,
                "motivoInvalida": None,
                "comErro": False,
                "falhasSeguidas": 0,
                "ultimoPrecoCentavos": preco_centavos,
                "ultimaOrigem": origem,
                "ultimaColetaEm": firestore.SERVER_TIMESTAMP,
            }
        )

    def marcar_fonte_invalida(self, fonte: Fonte, motivo: str) -> None:
        fonte.ref.update(
            {
                "status": STATUS_INVALIDA,
                "motivoInvalida": motivo,
                "ultimaColetaEm": firestore.SERVER_TIMESTAMP,
            }
        )

    def registrar_tentativa_de_validacao(self, fonte: Fonte, motivo: str) -> None:
        """Falha de transporte na validação: conta a tentativa e segue pendente.

        Mantém `status: pendente` de propósito — a URL pode estar boa e a loja
        ter recusado o IP do runner. O front mostra "validando fonte…" com o
        último motivo, e a próxima execução tenta de novo.
        """
        fonte.ref.update(
            {
                "falhasSeguidas": firestore.Increment(1),
                "motivoInvalida": motivo,
                "ultimaColetaEm": firestore.SERVER_TIMESTAMP,
            }
        )

    def marcar_fonte_com_erro(self, fonte: Fonte) -> None:
        fonte.ref.update({"comErro": True})

    # --- gravação de leitura ----------------------------------------------

    def registrar_leitura(
        self, fonte: Fonte, resultado, suspeito: bool, agora: datetime | None = None
    ) -> None:
        """Uma transação, três escritas: histórico, rollup diário e a fonte.

        Leitura sem preço ou marcada como suspeita entra apenas no histórico
        bruto — nunca no rollup diário, que alimenta gráfico e média.
        """
        agora = agora or datetime.now(timezone.utc)
        produto_ref = fonte.produto_ref

        ref_hist = produto_ref.collection(COLECAO_HISTORICO).document(
            id_bucket_historico(fonte.id, agora)
        )
        ref_diario = produto_ref.collection(COLECAO_DIARIO).document(
            id_bucket_diario(fonte.id, agora)
        )

        entrada = {
            "t": agora,
            "p": resultado.preco_centavos,
            "d": bool(resultado.disponivel),
            "s": bool(suspeito),
            "o": resultado.origem,
        }
        # A tabela 5.3 não prevê campo para o motivo da falha, mas a seção 9
        # exige gravá-lo. Chave curta `e`, presente só quando houve erro.
        if resultado.erro:
            entrada["e"] = resultado.erro

        entra_no_rollup = resultado.preco_centavos is not None and not suspeito

        @firestore.transactional
        def _gravar(transacao):
            # Todas as leituras antes de qualquer escrita.
            anterior = ref_diario.get(transaction=transacao) if entra_no_rollup else None

            transacao.set(
                ref_hist,
                {
                    "fonteId": fonte.id,
                    "mes": chave_mes(agora),
                    "leituras": firestore.ArrayUnion([entrada]),
                },
                merge=True,
            )

            if entra_no_rollup:
                transacao.set(
                    ref_diario,
                    {
                        "fonteId": fonte.id,
                        "ano": int(chave_ano(agora)),
                        "dias": {
                            chave_dia(agora): _dia_atualizado(
                                (anterior.to_dict() or {}).get("dias", {}).get(
                                    chave_dia(agora)
                                )
                                if anterior is not None and anterior.exists
                                else None,
                                resultado.preco_centavos,
                            )
                        },
                    },
                    merge=True,
                )

            atualizacao: dict[str, Any] = {"ultimaColetaEm": agora}
            if resultado.preco_centavos is None:
                atualizacao["falhasSeguidas"] = firestore.Increment(1)
            else:
                atualizacao["falhasSeguidas"] = 0
                atualizacao["ultimoPrecoCentavos"] = resultado.preco_centavos
                atualizacao["ultimaOrigem"] = resultado.origem
            transacao.update(fonte.ref, atualizacao)

        _gravar(self._db.transaction())

    # --- produtos ----------------------------------------------------------

    def carregar_produto(self, produto_ref) -> Produto | None:
        snapshot = produto_ref.get()
        if not snapshot.exists:
            return None
        dados = snapshot.to_dict() or {}
        return Produto(
            id=snapshot.id,
            ref=snapshot.reference,
            nome=dados.get("nome", ""),
            preco_alvo_centavos=dados.get("precoAlvoCentavos", 0),
            tolerancia_pct=dados.get("toleranciaPct", 0),
            preco_gatilho_centavos=dados.get("precoGatilhoCentavos", 0),
            estado=dados.get("estado", "ACIMA"),
            ultimo_alerta_em=dados.get("ultimoAlertaEm"),
            ultimo_preco_alertado_centavos=dados.get("ultimoPrecoAlertadoCentavos"),
            ativo=bool(dados.get("ativo", False)),
        )

    def corrigir_gatilho(self, produto: Produto, gatilho_centavos: int) -> None:
        """O coletor é a autoridade sobre `precoGatilhoCentavos`.

        As rules aceitam qualquer inteiro >= alvo vindo do cliente; o valor
        correto é reescrito aqui todo ciclo.
        """
        if produto.preco_gatilho_centavos != gatilho_centavos:
            produto.ref.update({"precoGatilhoCentavos": gatilho_centavos})
            produto.preco_gatilho_centavos = gatilho_centavos

    def atualizar_estado_alerta(
        self,
        produto: Produto,
        estado: str,
        preco_centavos: int | None,
        alertado_em: datetime | None,
    ) -> None:
        """Grava estado e, quando houve notificação, os campos do alerta."""
        atualizacao: dict[str, Any] = {"estado": estado}
        if alertado_em is not None:
            atualizacao["ultimoAlertaEm"] = alertado_em
            atualizacao["ultimoPrecoAlertadoCentavos"] = preco_centavos
        produto.ref.update(atualizacao)

    # --- catálogo -----------------------------------------------------------

    def _ref_indice(self, loja: str, categoria: str):
        return (
            self._db.collection(COLECAO_CATALOGO)
            .document(loja)
            .collection(COLECAO_INDICE)
            .document(categoria)
        )

    def ler_vitrine(self, loja: str, categoria: str) -> dict[str, dict]:
        """Mapa {sku: {n: nome, u: url, p: precoTabelaCentavos}}.

        UMA leitura serve a categoria inteira, para o coletor detectar mudança
        e para o front listar o catálogo. Ler item a item custaria uma leitura
        por produto — é a mesma jogada do bucketing do histórico.

        Chaves curtas porque o nome do campo é cobrado em cada entrada: com 400
        itens o documento fica em ~76 KB, contra o limite de 1 MB.
        """
        snapshot = self._ref_indice(loja, categoria).get()
        if not snapshot.exists:
            return {}
        return (snapshot.to_dict() or {}).get("itens") or {}

    def ler_indice_do_catalogo(
        self, loja: str, categoria: str
    ) -> dict[str, tuple[int | None, bool | None]]:
        """Par (preço, disponível) por SKU, para detectar o que mudou.

        O par, e não só o preço: um produto que sai de estoque mudou, mesmo com
        o preço igual.
        """
        return {
            sku: (dados.get("p"), dados.get("d"))
            for sku, dados in self.ler_vitrine(loja, categoria).items()
            if isinstance(dados, dict)
        }

    def salvar_catalogo(
        self, loja: str, categoria: str, itens, agora: datetime | None = None
    ) -> dict:
        """Grava o instantâneo da categoria e devolve o que mudou.

        Só escreve o documento do item quando ele é novo ou o preço mudou —
        reescrever 1.000 itens inalterados a cada ciclo seria puro desperdício
        de cota.
        """
        agora = agora or datetime.now(timezone.utc)
        anterior = self.ler_indice_do_catalogo(loja, categoria)

        colecao = (
            self._db.collection(COLECAO_CATALOGO)
            .document(loja)
            .collection(COLECAO_ITENS)
        )

        resumo = {
            "novos": 0, "alterados": 0, "inalterados": 0,
            "esgotados": 0, "sem_sku": 0, "mantidos": 0, "expirados": 0,
        }
        # Começa do que já existia: a listagem pode ter rendido menos desta vez.
        vitrine: dict[str, dict] = dict(self.ler_vitrine(loja, categoria))
        vistos_agora: set[str] = set()
        pendentes = []

        for item in itens:
            if not item.sku:
                resumo["sem_sku"] += 1
                continue
            if item.preco_centavos is None and item.disponivel is not False:
                # sem preço e sem sinal de esgotado: não dá para catalogar
                resumo["sem_sku"] += 1
                continue
            if item.disponivel is False:
                resumo["esgotados"] += 1

            vitrine[item.sku] = {
                "n": item.nome,
                "u": item.url,
                "p": item.preco_centavos,
                "d": item.disponivel,
                "t": item.preco_tabela_centavos,
                "img": item.imagem,
                "vt": agora,     # visto nesta raspagem
            }
            vistos_agora.add(item.sku)
            antes = anterior.get(item.sku)
            # sair de estoque é mudança tanto quanto mudar de preço
            if antes is not None and antes == (item.preco_centavos, item.disponivel):
                resumo["inalterados"] += 1
                continue
            resumo["novos" if antes is None else "alterados"] += 1
            pendentes.append(
                (
                    colecao.document(item.sku),
                    {
                        "sku": item.sku,
                        "nome": item.nome,
                        "url": item.url,
                        "categoria": categoria,
                        "loja": loja,
                        "precoCentavos": item.preco_centavos,
                        "precoTabelaCentavos": item.preco_tabela_centavos,
                        "disponivel": item.disponivel,
                        "imagem": item.imagem,
                        "atualizadoEm": agora,
                    },
                )
            )

        for inicio in range(0, len(pendentes), LIMITE_DO_LOTE):
            lote = self._db.batch()
            for referencia, dados in pendentes[inicio : inicio + LIMITE_DO_LOTE]:
                lote.set(referencia, dados, merge=True)
            lote.commit()

        # Quem não apareceu agora sobrevive até DIAS_NA_VITRINE sem ser visto.
        limite = agora - timedelta(days=DIAS_NA_VITRINE)
        for sku in [s for s in vitrine if s not in vistos_agora]:
            visto = vitrine[sku].get("vt")
            if visto is None:
                vitrine[sku]["vt"] = agora     # entrada antiga, sem marca de tempo
                resumo["mantidos"] += 1
                continue
            if getattr(visto, "tzinfo", None) is None:
                visto = visto.replace(tzinfo=timezone.utc)
            if visto < limite:
                del vitrine[sku]
                resumo["expirados"] += 1
            else:
                resumo["mantidos"] += 1

        self._ref_indice(loja, categoria).set(
            {
                "categoria": categoria,
                "loja": loja,
                "itens": vitrine,
                "quantidade": len(vitrine),
                "atualizadoEm": agora,
            }
        )
        # Documento da loja: existe para o front descobrir quais lojas há sem
        # precisar de consulta de collection group (que exigiria índice).
        self._db.collection(COLECAO_CATALOGO).document(loja).set(
            {"loja": loja, "atualizadoEm": agora}, merge=True
        )
        return resumo

    def listar_catalogo(self, loja: str, categoria: str | None = None) -> list[dict]:
        """Itens do catálogo. Existe para teste e depuração; o front lê direto."""
        consulta = (
            self._db.collection(COLECAO_CATALOGO)
            .document(loja)
            .collection(COLECAO_ITENS)
        )
        if categoria is not None:
            consulta = consulta.where(
                filter=firestore.FieldFilter("categoria", "==", categoria)
            )
        return [s.to_dict() for s in consulta.stream()]

    # --- controle de cadência ---------------------------------------------

    def ler_controle_raspagem(self) -> datetime | None:
        snapshot = (
            self._db.collection(COLECAO_SISTEMA).document(DOC_CONTROLE_RASPAGEM).get()
        )
        if not snapshot.exists:
            return None
        return (snapshot.to_dict() or {}).get("ultimaRaspagemEm")

    def gravar_controle_raspagem(self, agora: datetime) -> None:
        self._db.collection(COLECAO_SISTEMA).document(DOC_CONTROLE_RASPAGEM).set(
            {"ultimaRaspagemEm": agora}, merge=True
        )

    def ler_controle(self) -> datetime | None:
        snapshot = (
            self._db.collection(COLECAO_SISTEMA).document(DOC_CONTROLE).get()
        )
        if not snapshot.exists:
            return None
        return (snapshot.to_dict() or {}).get("ultimaColetaEm")

    def gravar_controle(self, agora: datetime) -> None:
        self._db.collection(COLECAO_SISTEMA).document(DOC_CONTROLE).set(
            {"ultimaColetaEm": agora}, merge=True
        )

    # --- páginas capturadas por fora (n8n) ----------------------------------

    def ler_pagina_capturada(self, fonte_id: str) -> dict | None:
        snapshot = self._db.collection(COLECAO_PAGINAS).document(fonte_id).get()
        return (snapshot.to_dict() or None) if snapshot.exists else None

    def gravar_pagina_capturada(self, fonte_id: str, documento: dict) -> None:
        """Escrita que normalmente é do n8n. Existe aqui para os testes e para o
        utilitário de captura manual (`python -m coletor.capturar`)."""
        self._db.collection(COLECAO_PAGINAS).document(fonte_id).set(documento)

    # --- média de 30 dias --------------------------------------------------

    def media_historica_centavos(
        self, produto: Produto, fonte_id: str | None = None
    ) -> int | None:
        """Média de TODO o histórico disponível, a partir do rollup `diario`.

        Ponderada por amostra (`soma`/`n` acumulados), nunca média de médias.
        Devolve None enquanto não houver `DIAS_DA_MEDIA` dias distintos: com
        poucos dias a média é praticamente o preço atual, e qualquer gatilho
        baseado nela dispararia por ruído.
        """
        soma_total = 0
        n_total = 0
        dias: set[str] = set()

        for snapshot in produto.ref.collection(COLECAO_DIARIO).stream():
            dados = snapshot.to_dict() or {}
            if fonte_id is not None and dados.get("fonteId") != fonte_id:
                continue
            for chave, valores in (dados.get("dias") or {}).items():
                n = valores.get("n") or 0
                if n <= 0:
                    continue
                soma_total += valores.get("soma") or 0
                n_total += n
                dias.add(f"{dados.get('ano')}{chave}")

        if len(dias) < DIAS_DA_MEDIA or n_total <= 0:
            return None
        return soma_total // n_total

    def media_30_dias_centavos(
        self, produto: Produto, fonte_id: str | None = None
    ) -> int | None:
        """Média dos últimos 30 dias a partir do rollup `diario`.

        Devolve None se não houver 30 dias distintos de histórico — a seção
        10.2 manda omitir o trecho da mensagem em vez de inventar referência.
        Sem `fonte_id`, agrega todas as fontes do produto.
        """
        hoje = datetime.now(timezone.utc)
        chaves = {
            chave_dia(hoje - timedelta(days=deslocamento))
            for deslocamento in range(DIAS_DA_MEDIA)
        }
        anos = {chave_ano(hoje), chave_ano(hoje - timedelta(days=DIAS_DA_MEDIA))}

        soma_total = 0
        n_total = 0
        dias_com_dado: set[str] = set()

        for snapshot in produto.ref.collection(COLECAO_DIARIO).stream():
            dados = snapshot.to_dict() or {}
            if fonte_id is not None and dados.get("fonteId") != fonte_id:
                continue
            if str(dados.get("ano")) not in anos:
                continue
            for chave, valores in (dados.get("dias") or {}).items():
                if chave not in chaves:
                    continue
                n = valores.get("n") or 0
                if n <= 0:
                    continue
                soma_total += valores.get("soma") or 0
                n_total += n
                dias_com_dado.add(chave)

        if len(dias_com_dado) < DIAS_DA_MEDIA or n_total <= 0:
            return None
        return soma_total // n_total


def _dia_atualizado(anterior: dict | None, preco_centavos: int) -> dict:
    """Recalcula a entrada do dia. `soma` e `n` em vez de média, para ser
    incremental sem perder precisão."""
    if not anterior:
        return {
            "min": preco_centavos,
            "max": preco_centavos,
            "soma": preco_centavos,
            "n": 1,
            "fech": preco_centavos,
        }
    return {
        "min": min(anterior.get("min", preco_centavos), preco_centavos),
        "max": max(anterior.get("max", preco_centavos), preco_centavos),
        "soma": (anterior.get("soma") or 0) + preco_centavos,
        "n": (anterior.get("n") or 0) + 1,
        "fech": preco_centavos,
    }
