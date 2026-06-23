#!/usr/bin/env bash
# imoveis_watchdog.sh — Wrapper do pipeline watchdog de imóveis para cron.
#
# Suporta duas pipelines:
#   1. OLX (padrão via watchdog_pipeline.py) — legado
#   2. Multi-Portal (via scripts/pipeline_multi_portal.py) — QuintoAndar + Loft + Zap
#
# Uso:
#   ./imoveis_watchdog.sh                 # OLX pipeline (legado)
#   ./imoveis_watchdog.sh --multi-portal  # Multi-Portal pipeline
#   ./imoveis_watchdog.sh --dry-run       # Dry-run OLX
#   ./imoveis_watchdog.sh --list-portais  # Lista portais ativos e sai
#
# Exit codes:
#   0 — Execução normal (pode ou não ter novidades)
#   1 — Erro de configuração ou dependência
#   2 — Falha na execução do pipeline

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MULTI_PIPELINE="${SCRIPT_DIR}/scripts/pipeline_multi_portal.py"
PIPELINE="${SCRIPT_DIR}/watchdog_pipeline.py"
CONFIG="${HERMES_WATCHDOG_CONFIG:-$HOME/.hermes/watchdog.yaml}"
STATE_DIR="$HOME/.hermes/watchdog"
LOG_DIR="${STATE_DIR}/history"

# Garante diretórios de log
mkdir -p "$LOG_DIR"

LOG_FILE="${LOG_DIR}/cron_$(date +%Y%m%d_%H%M%S).log"

# Carrega env vars do Hermes
if [ -f "$HOME/.hermes/.env" ]; then
    set -a
    source "$HOME/.hermes/.env"
    set +a
fi

# Pipeline espera TELEGRAM_CHAT_ID; mapeia de TELEGRAM_HOME_CHANNEL se não definido
if [ -z "${TELEGRAM_CHAT_ID:-}" ] && [ -n "${TELEGRAM_HOME_CHANNEL:-}" ]; then
    export TELEGRAM_CHAT_ID="$TELEGRAM_HOME_CHANNEL"
fi

# ── Parse de argumentos ───────────────────────────────────────────────────
MULTI_PORTAL=false
EXTRA_ARGS=""

for arg in "$@"; do
    case "$arg" in
        --multi-portal)
            MULTI_PORTAL=true
            ;;
        --list-portais)
            EXTRA_ARGS="$EXTRA_ARGS --list-portais"
            ;;
        --dry-run)
            EXTRA_ARGS="$EXTRA_ARGS --dry-run"
            ;;
        --no-notify)
            EXTRA_ARGS="$EXTRA_ARGS --no-notify"
            ;;
        --force)
            EXTRA_ARGS="$EXTRA_ARGS --force"
            ;;
        --reset)
            EXTRA_ARGS="$EXTRA_ARGS --reset"
            ;;
        --save-only)
            EXTRA_ARGS="$EXTRA_ARGS --save-only"
            ;;
        *)
            EXTRA_ARGS="$EXTRA_ARGS $arg"
            ;;
    esac
done

# ── Multi-Portal pipeline ──────────────────────────────────────────────────
if [ "$MULTI_PORTAL" = true ]; then
    echo "===== Watchdog Multi-Portal Pipeline — $(date --iso-8601=seconds) =====" | tee "$LOG_FILE"

    if [ ! -f "$MULTI_PIPELINE" ]; then
        echo "ERRO: Multi-Portal pipeline não encontrado em $MULTI_PIPELINE" | tee -a "$LOG_FILE"
        exit 1
    fi

    if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
        echo "AVISO: TELEGRAM_BOT_TOKEN não definido — notificações desabilitadas" | tee -a "$LOG_FILE"
    fi

    cd "$SCRIPT_DIR"
    # shellcheck disable=SC2086
    python3 scripts/pipeline_multi_portal.py $EXTRA_ARGS 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo "ERRO: Multi-Portal pipeline falhou com exit code $EXIT_CODE" | tee -a "$LOG_FILE"
        exit 2
    fi

    echo "Multi-Portal pipeline concluída com sucesso." | tee -a "$LOG_FILE"
else
    # ── OLX pipeline (legado) ──────────────────────────────────────────────
    echo "===== Watchdog Pipeline (OLX) — $(date --iso-8601=seconds) =====" | tee "$LOG_FILE"
    echo "Config: $CONFIG" | tee -a "$LOG_FILE"

    if [ ! -f "$PIPELINE" ]; then
        echo "ERRO: Pipeline OLX não encontrado em $PIPELINE" | tee -a "$LOG_FILE"
        exit 1
    fi

    if [ ! -f "$CONFIG" ]; then
        echo "ERRO: Config não encontrada em $CONFIG" | tee -a "$LOG_FILE"
        exit 1
    fi

    if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
        echo "AVISO: TELEGRAM_BOT_TOKEN não definido — notificações desabilitadas" | tee -a "$LOG_FILE"
    fi

    cd "$SCRIPT_DIR"
    # shellcheck disable=SC2086
    python3 watchdog_pipeline.py $EXTRA_ARGS 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=$?

    if [ $EXIT_CODE -ne 0 ]; then
        echo "ERRO: Pipeline OLX falhou com exit code $EXIT_CODE" | tee -a "$LOG_FILE"
        exit 2
    fi

    echo "Pipeline OLX concluída com sucesso." | tee -a "$LOG_FILE"
fi

# Limpa logs com mais de 30 dias
find "$LOG_DIR" -name "cron_*.log" -mtime +30 -delete 2>/dev/null

exit 0
