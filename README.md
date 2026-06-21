# 🏠 Imóveis Watchdog

Sistema para monitorar anúncios de imóveis à venda, extraindo dados do **QuintoAndar** e **Loft**, detectando mudanças (novos anúncios, removidos, alterações de preço) e enviando notificações.

## Índice

- [Visão Geral](#visão-geral)
- [Funcionalidades](#funcionalidades)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Pré-requisitos](#pré-requisitos)
- [Configuração](#configuração)
- [Como Usar](#como-usar)
- [Alvos Monitorados](#alvos-monitorados)
- [Pipeline](#pipeline)
- [Hospedagem e Automação](#hospedagem-e-automação)
- [Licença](#licença)

## Visão Geral

O **Imóveis Watchdog** é uma ferramenta automatizada que coleta listagens de imóveis de portais brasileiros, compara com o estado anterior e notifica o usuário sobre mudanças. Ele foi projetado para rodar periodicamente via cron ou CI, de forma idempotente — notifica apenas quando há mudanças detectadas.

Originalmente focado em OLX, o projeto foi expandido para suportar múltiplos portais via uma arquitetura modular baseada em **skills** (scripts de extração específicos por fonte). Atualmente cobre **QuintoAndar** e **Loft**, com suporte para adicionar novas fontes.

## Funcionalidades

- ✅ Extração de dados via scraping e/ou API dos portais
- ✅ Detecção de novos anúncios, anúncios removidos e mudanças de preço
- ✅ Notificação via Telegram com resumo das mudanças
- ✅ Execução periódica via cron ou GitHub Actions
- ✅ Pipeline idempotente — não notifica se nada mudou
- ✅ Arquitetura modular — skills separadas para cada portal
- ✅ Modo dry-run e force para testes
- ✅ Suporte a múltiplos alvos por portal

## Estrutura do Projeto

```
imoveis-watchdog/
├── .github/workflows/
│   └── watchdog-ci.yml        # CI workflow (GitHub Actions)
├── .hermes-skills/             # Skills do Hermes Agent versionadas
│   ├── browser-automation/
│   ├── devops/
│   ├── github/
│   ├── software-development/
│   └── turso-db/
├── config/
│   └── targets.yaml            # Configuração de alvos por portal
├── data/
│   └── .gitkeep                # Dados extraídos (gitignorado)
├── mcp/
│   ├── context7-mcp.json       # Config MCP Context7
│   └── jina-mcp.json           # Config MCP Jina AI
├── scrapers/                   # Scripts de scraping por portal
│   └── loft/
│       ├── scrape-loft.js      # Scraper Playwright + Landscape API
│       └── loft_parser.py      # Parsing e unificação de dados
├── skills/                     # Skills Python dos portais
│   ├── quinto-andar/
│   │   ├── SKILL.md
│   │   ├── quintoandar_parser.py
│   │   ├── sample_quintoandar.json
│   │   └── test_quintoandar_parser.py
│   ├── loft/
│   │   ├── SKILL.md
│   │   └── loft_parser.py
│   └── watchdog/
│       ├── SKILL.md
│       └── watchdog_pipeline.py
├── tests/
│   ├── test_data.json          # Dados mockados para testes
│   └── test_extraction.py      # Testes de extração
├── AGENTS.md                   # Instruções para agentes de IA
├── imoveis_watchdog.sh         # Wrapper para cron
├── requirements.txt            # Dependências Python
├── watchdog.yaml               # Configuração principal
├── watchdog_config.py          # Leitor de configuração YAML
└── watchdog_pipeline.py        # Pipeline principal (execução)
```

## Pré-requisitos

- Python 3.10+
- Node.js 18+ (para scraping via Playwright no portal Loft)
- `pip` e `npm` para instalação de dependências
- (Opcional) Token do Telegram para notificações

> **Nota**: Instruções detalhadas de instalação serão adicionadas conforme o projeto amadurece.

## Configuração

> **Em desenvolvimento** — instruções completas de setup serão documentadas aqui.

### Variáveis de Ambiente

| Variável | Descrição | Obrigatório |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot do Telegram | Para notificações |
| `TELEGRAM_CHAT_ID` | Chat/grupo de destino | Para notificações |
| `GH_TOKEN` | Token GitHub (para CI) | Para CI/CD |

### Alvos

Edite `config/targets.yaml` para configurar as URLs e filtros de cada portal monitorado.

## Como Usar

```bash
# Instalar dependências Python
pip install -r requirements.txt

# Execução normal (pipeline completo)
python watchdog_pipeline.py

# Forçar notificação mesmo sem mudanças
python watchdog_pipeline.py --force

# Dry run (não persiste estado nem notifica)
python watchdog_pipeline.py --dry-run

# Reset do estado anterior (reescan completo)
python watchdog_pipeline.py --reset
```

### Scrapers Individuais

```bash
# Scraper Loft (Playwright + API)
cd scrapers/loft
node scrape-loft.js
```

## Alvos Monitorados

| Portal | Abordagem | Dados |
|---|---|---|
| **QuintoAndar** | Parser de estrutura conhecida | Imóveis à venda com preço, área, quartos, localização |
| **Loft** | Playwright + Landscape API (fetch direto) | ~10.000 listings de SP via API V3 |

## Pipeline

O pipeline principal (`watchdog_pipeline.py`) segue estas etapas:

1. **Carregar configuração** — lê `watchdog.yaml`
2. **Extrair dados** — executa as skills dos portais configurados
3. **Comparar com estado anterior** — detecta novos, removidos e alterações de preço
4. **Gerar notificação** — se houver mudanças, monta resumo e envia
5. **Persistir estado** — salva o snapshot atual como referência futura

## Hospedagem e Automação

- **Cron local**: via `imoveis_watchdog.sh` (wrapper para execução periódica)
- **CI**: via GitHub Actions (`.github/workflows/watchdog-ci.yml`)
- **Hermes Agent**: skills versionadas em `.hermes-skills/` para manutenção assistida por IA

## Licença

MIT
