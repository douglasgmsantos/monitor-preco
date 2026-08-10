"""Leitura das variáveis de ambiente.

Nenhum segredo mora em código. Em produção os valores vêm de GitHub Secrets;
localmente, do arquivo apontado por `.env.exemplo` exportado no shell.
"""

import os
from dataclasses import dataclass

# Valores padrão em um lugar só, para que testes e produção não divirjam.
TETO_CENTAVOS_PADRAO = 100_000_000
INTERVALO_COLETA_HORAS_PADRAO = 6
LIMIAR_SANIDADE_PADRAO = "0.70"
USER_AGENT_PADRAO = "MonitorPrecos/1.0 (uso pessoal)"
MARGEM_MEDIA_PCT_PADRAO = 10


@dataclass(frozen=True)
class Config:
    firebase_sa_base64: str
    telegram_bot_token: str
    telegram_chat_id: str
    intervalo_coleta_horas: int
    limiar_sanidade: str
    teto_centavos: int
    user_agent: str
    margem_media_pct: int = MARGEM_MEDIA_PCT_PADRAO


def carregar() -> Config:
    """Monta a configuração a partir do ambiente."""
    return Config(
        firebase_sa_base64=os.environ.get("FIREBASE_SA_BASE64", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        intervalo_coleta_horas=int(
            os.environ.get("INTERVALO_COLETA_HORAS", INTERVALO_COLETA_HORAS_PADRAO)
        ),
        # mantido como string: quem usa converte para Decimal, nunca para float
        limiar_sanidade=os.environ.get("LIMIAR_SANIDADE", LIMIAR_SANIDADE_PADRAO),
        teto_centavos=int(os.environ.get("TETO_CENTAVOS", TETO_CENTAVOS_PADRAO)),
        user_agent=os.environ.get("USER_AGENT", USER_AGENT_PADRAO),
        margem_media_pct=int(
            os.environ.get("MARGEM_MEDIA_PCT", MARGEM_MEDIA_PCT_PADRAO)
        ),
    )
