#!/usr/bin/env bash
# imoveis_watchdog.sh — Wrapper do pipeline watchdog de imóveis para cron.
#
# Carrega env vars do Hermes, executa o pipeline e loga erros.
# Usa HERMES_WATCHDOG_CONFIG se definido, senão ~/.hermes/watchdog.yaml.
#
# Exit codes:
#   0 — Execução normal (pode ou não ter novidades)
#   1 — Erro de configuração ou dependência
#   2 — Falha na execução do pipeline

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo "===== Watchdog Pipeline — $(date --iso-8601=seconds) =====" | tee "$LOG_FILE"
echo "Config: $CONFIG" | tee -a "$LOG_FILE"

# Verifica dependências
if [ ! -f "$PIPELINE" ]; then
    echo "ERRO: Pipeline não encontrado em $PIPELINE" | tee -a "$LOG_FILE"
    exit 1
fi

if [ ! -f "$CONFIG" ]; then
    echo "ERRO: Config não encontrada em $CONFIG" | tee -a "$LOG_FILE"
    exit 1
fi

# Verifica se o bot token está disponível (warning, não erro — script já trata)
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    echo "AVISO: TELEGRAM_BOT_TOKEN não definido — notificações desabilitadas" | tee -a "$LOG_FILE"
fi

# Executa o pipeline
cd "$SCRIPT_DIR"
python3 watchdog_pipeline.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "ERRO: Pipeline falhou com exit code $EXIT_CODE" | tee -a "$LOG_FILE"
    exit 2
fi

echo "Pipeline concluída com sucesso." | tee -a "$LOG_FILE"

# Limpa logs com mais de 30 dias
find "$LOG_DIR" -name "cron_*.log" -mtime +30 -delete 2>/dev/null

exit 0
