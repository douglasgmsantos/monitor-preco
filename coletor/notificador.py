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
    def enviar(self, mensagem: str, imagem: str | None = None) -> None: ...


class NotificadorTelegram:
    """API `sendMessage` do bot do Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    def enviar(self, mensagem: str, imagem: str | None = None) -> None:
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
            return

        if imagem and len(mensagem) <= LIMITE_DA_LEGENDA:
            if self._chamar("sendPhoto", {
                "chat_id": self._chat_id,
                "photo": imagem,
                "caption": mensagem,
            }):
                return
            # A imagem pode estar fora do ar, ser grande demais ou ter um
            # formato que o Telegram recusa. Perder o alerta por causa da foto
            # seria trocar o essencial pelo enfeite.
            logger.warning("sendPhoto falhou; reenviando como texto")

        self._chamar("sendMessage", {
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
        except httpx.HTTPError:
            # Uma notificação perdida não pode derrubar o ciclo de coleta.
            logger.warning("falha em %s do Telegram", metodo, exc_info=True)
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

    def enviar(self, mensagem: str, imagem: str | None = None) -> None:
        self.mensagens.append(mensagem)
        self.imagens.append(imagem)
