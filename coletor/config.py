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
    # Execução manual: coleta os produtos AGORA, sem esperar a janela de 30 min.
    # Não afeta a raspagem de catálogo, que tem cadência própria de 24h e é a
    # parte cara (dezenas de páginas de listagem nas lojas). Ver `executar_ciclo`.
    forcar_coleta: bool = False
    # Avisa a cada ciclo enquanto o preço estiver na faixa, sem regra dos 5% e
    # sem cooldown. Ver `REPETIR_NO_RANGE_PADRAO` em coletor/alertas.py.
    alerta_repete_no_range: bool = True
    # Execução manual da raspagem: varre AGORA, sem esperar as 24h. Espelha
    # `forcar_coleta`, e é o que o n8n usa ao terminar a captura das listagens.
    forcar_raspagem: bool = False


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
        forcar_coleta=_booleano(os.environ.get("FORCAR_COLETA")),
        # Ausente = ligado. O padrão segue a escolha de quem opera; desligar é
        # explícito, para ninguém perder alerta por esquecer de configurar.
        alerta_repete_no_range=_booleano(
            os.environ.get("ALERTA_REPETE_NO_RANGE", "true")
        ),
        forcar_raspagem=_booleano(os.environ.get("FORCAR_RASPAGEM")),
    )


def _booleano(valor: str | None) -> bool:
    """Aceita o que um `workflow_dispatch` do GitHub entrega.

    A entrada de um workflow chega como a STRING "true"/"false" — nunca como
    booleano. `bool("false")` é True, então converter na mão aqui é o que
    impede uma execução agendada de se comportar como manual.
    """
    return (valor or "").strip().lower() in {"1", "true", "sim", "yes"}
