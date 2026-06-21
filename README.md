# 🏠 Imóveis Watchdog

Watchdog de oportunidades de compra e venda de imóveis em portais brasileiros.

Monitora anúncios no OLX para cidades selecionadas (São Paulo, Rio de Janeiro,
Belo Horizonte) e faixas de preço, detectando novas oportunidades, anúncios
removidos e mudanças de preço.

## Funcionalidades

- ✅ Busca automatizada em múltiplas cidades e faixas de preço
- ✅ Detecção de novos anúncios, removidos e mudanças de preço
- ✅ Notificação via Telegram com resumo das mudanças
- ✅ Execução periódica via cron (a cada 6h)
- ✅ Pipeline idempotente — não notifica se nada mudou

## Como usar

### Dependências

```bash
pip install cloudscraper pyyaml
```

### Configuração

Edite `watchdog.yaml` para configurar cidades, bairros e faixas de preço.

### Execução

```bash
# Execução normal
python watchdog_pipeline.py

# Forçar notificação mesmo sem mudanças
python watchdog_pipeline.py --force

# Dry run (não executa nem notifica)
python watchdog_pipeline.py --dry-run

# Reset do estado anterior
python watchdog_pipeline.py --reset
```

### Ambiente

Para notificações Telegram, defina:
- `TELEGRAM_BOT_TOKEN` — token do bot
- `TELEGRAM_CHAT_ID` — chat/destino das notificações

## Estrutura

```
imoveis-watchdog/
├── .github/workflows/
│   └── watchdog-ci.yml    # CI workflow
├── tests/
│   ├── test_data.json      # Dados mockados para testes
│   └── test_extraction.py  # Script de extração de teste
├── watchdog.yaml           # Configuração de busca
├── watchdog_config.py      # Leitor de configuração
├── watchdog_pipeline.py    # Pipeline principal
├── imoveis_watchdog.sh     # Wrapper para cron
└── README.md
```

## Licença

MIT
