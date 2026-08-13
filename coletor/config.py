"""Leitura das variáveis de ambiente.

Nenhum segredo mora em código. Em produção os valores vêm de GitHub Secrets;
localmente, do arquivo apontado por `.env.exemplo` exportado no shell.
"""

import os
from dataclasses import dataclass

# Valores padrão em um lugar só, para que testes e produção não divirjam.
TETO_CENTAVOS_PADRAO = 100_000_000
# Em MINUTOS, não horas: a coleta passou a rodar de 30 em 30 min e um campo em
# horas não expressa isso. A raspagem de catálogo continua em horas — ela mede
# composição de vitrine, que muda em dias.
INTERVALO_COLETA_MINUTOS_PADRAO = 30
LIMIAR_SANIDADE_PADRAO = "0.70"
USER_AGENT_PADRAO = "MonitorPrecos/1.0 (uso pessoal)"
MARGEM_MEDIA_PCT_PADRAO = 10
INTERVALO_RASPAGEM_HORAS_PADRAO = 24
# Só a KaBuM publica preço por produto na listagem. Ver README.
CATEGORIAS_RASPAGEM_PADRAO = "https://www.kabum.com.br/hardware/placa-de-video-vga"


@dataclass(frozen=True)
class Config:
    firebase_sa_base64: str
    telegram_bot_token: str
    telegram_chat_id: str
    intervalo_coleta_minutos: int
    limiar_sanidade: str
    teto_centavos: int
    user_agent: str
    margem_media_pct: int = MARGEM_MEDIA_PCT_PADRAO
    intervalo_raspagem_horas: int = INTERVALO_RASPAGEM_HORAS_PADRAO
    categorias_raspagem: tuple[str, ...] = ()


def carregar() -> Config:
    """Monta a configuração a partir do ambiente."""
    return Config(
        firebase_sa_base64=os.environ.get("FIREBASE_SA_BASE64", ""),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        intervalo_coleta_minutos=int(
            os.environ.get("INTERVALO_COLETA_MINUTOS", INTERVALO_COLETA_MINUTOS_PADRAO)
        ),
        # mantido como string: quem usa converte para Decimal, nunca para float
        limiar_sanidade=os.environ.get("LIMIAR_SANIDADE", LIMIAR_SANIDADE_PADRAO),
        teto_centavos=int(os.environ.get("TETO_CENTAVOS", TETO_CENTAVOS_PADRAO)),
        user_agent=os.environ.get("USER_AGENT", USER_AGENT_PADRAO),
        margem_media_pct=int(
            os.environ.get("MARGEM_MEDIA_PCT", MARGEM_MEDIA_PCT_PADRAO)
        ),
        intervalo_raspagem_horas=int(
            os.environ.get("INTERVALO_RASPAGEM_HORAS", INTERVALO_RASPAGEM_HORAS_PADRAO)
        ),
        # lista de URLs de listagem separadas por vírgula
        categorias_raspagem=tuple(
            url.strip()
            for url in os.environ.get(
                "CATEGORIAS_RASPAGEM", CATEGORIAS_RASPAGEM_PADRAO
            ).split(",")
            if url.strip()
        ),
    )
