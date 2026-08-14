"""Envio de notificações.

`NotificadorTelegram` para produção, `NotificadorMemoria` para os testes.
Token e chat_id vêm do ambiente (GitHub Secrets) — nunca de código.
"""

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 15.0

# Legenda de foto no Telegram tem teto de 1024 caracteres (texto puro vai até
# 4096). A mensagem do alerta é curta, mas nome de produto de marketplace passa
# de 200 caracteres — sem esta checagem, um nome muito longo faria a API recusar
# e o alerta se perderia.
LIMITE_DA_LEGENDA = 1024


class Notificador(Protocol):
    # Devolve True só quando o Telegram ACEITOU a mensagem.
    #
    # O retorno existe porque quem chama precisa dele: `alertas.processar` marca
    # o produto como alertado e o cala por causa da regra dos 5%. Marcar isso
    # depois de um envio que falhou produz o pior resultado possível — o sistema
    # acha que avisou, o usuário não recebeu nada, e o silêncio é permanente
    # enquanto o preço não cair mais 5%.
    def enviar(self, mensagem: str, imagem: str | None = None) -> bool: ...


class NotificadorTelegram:
    """API `sendMessage` do bot do Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    def enviar(self, mensagem: str, imagem: str | None = None) -> bool:
        """Manda o alerta. Com imagem vai como FOTO; sem, como texto.

        POR QUE FOTO: o prévio de link do Telegram é montado pelas tags Open
        Graph da página, e a API não deixa escolher quais campos ele mostra —
        vinha site, título, descrição e imagem, tudo. `sendPhoto` inverte o
        controle: a foto é a que a gente escolheu e o texto é só o nosso.
        Por isso o texto também vai com o prévio DESLIGADO — o link na legenda
        traria a mesma caixa de volta.
        """
        if not self._token or not self._chat_id:
            logger.warning("Telegram não configurado — notificação descartada")
            return False

        if imagem and len(mensagem) <= LIMITE_DA_LEGENDA:
            if self._chamar("sendPhoto", {
                "chat_id": self._chat_id,
                "photo": imagem,
                "caption": mensagem,
            }):
                return True
            # A imagem pode estar fora do ar, ser grande demais ou ter um
            # formato que o Telegram recusa. Perder o alerta por causa da foto
            # seria trocar o essencial pelo enfeite.
            logger.warning("sendPhoto falhou; reenviando como texto")

        return self._chamar("sendMessage", {
            "chat_id": self._chat_id,
            "text": mensagem,
            "link_preview_options": {"is_disabled": True},
        })

    def _chamar(self, metodo: str, corpo: dict) -> bool:
        try:
            resposta = httpx.post(
                f"https://api.telegram.org/bot{self._token}/{metodo}",
                json=corpo,
                timeout=TIMEOUT_SEGUNDOS,
            )
            resposta.raise_for_status()
            return True
        except httpx.HTTPError as erro:
            # Uma notificação perdida não pode derrubar o ciclo de coleta — mas
            # também não pode passar como sucesso. O corpo da resposta traz o
            # `description` do Telegram ("chat not found", "Unauthorized"), que
            # é a diferença entre um log acionável e um "deu erro".
            detalhe = ""
            resposta = getattr(erro, "response", None)
            if resposta is not None:
                detalhe = f" — {resposta.status_code}: {resposta.text[:200]}"
            logger.error("falha em %s do Telegram%s", metodo, detalhe)
            return False


def notificador_do_usuario(
    config_do_usuario: dict | None, padrao: Notificador
) -> Notificador:
    """O bot do usuário quando ele configurou um; o global quando não.

    A queda para o padrão é o que mantém funcionando quem usava o sistema antes
    de o campo existir — e quem configurou errado e apagou os dados.
    """
    if not config_do_usuario:
        return padrao
    return NotificadorTelegram(
        config_do_usuario.get("botToken", ""),
        str(config_do_usuario.get("chatId", "")),
    )


class NotificadorMemoria:
    """Acumula mensagens numa lista. Usado nos testes, sem rede."""

    def __init__(self) -> None:
        self.mensagens: list[str] = []
        self.imagens: list[str | None] = []

    def enviar(self, mensagem: str, imagem: str | None = None) -> bool:
        self.mensagens.append(mensagem)
        self.imagens.append(imagem)
        return True
