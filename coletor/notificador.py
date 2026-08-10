"""Envio de notificações.

`NotificadorTelegram` para produção, `NotificadorMemoria` para os testes.
Token e chat_id vêm do ambiente (GitHub Secrets) — nunca de código.
"""

import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SEGUNDOS = 15.0


class Notificador(Protocol):
    def enviar(self, mensagem: str) -> None: ...


class NotificadorTelegram:
    """API `sendMessage` do bot do Telegram."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id

    def enviar(self, mensagem: str) -> None:
        if not self._token or not self._chat_id:
            logger.warning("Telegram não configurado — notificação descartada")
            return
        try:
            resposta = httpx.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": mensagem,
                    "disable_web_page_preview": False,
                },
                timeout=TIMEOUT_SEGUNDOS,
            )
            resposta.raise_for_status()
        except httpx.HTTPError:
            # Uma notificação perdida não pode derrubar o ciclo de coleta.
            logger.exception("falha ao enviar notificação pelo Telegram")


class NotificadorMemoria:
    """Acumula mensagens numa lista. Usado nos testes, sem rede."""

    def __init__(self) -> None:
        self.mensagens: list[str] = []

    def enviar(self, mensagem: str) -> None:
        self.mensagens.append(mensagem)
