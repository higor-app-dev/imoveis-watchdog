# imoveis-watchdog — Agent Guide

Watchdog de oportunidades de compra e venda de imóveis em portais brasileiros.

## Stack
- **Python 3.11+** (core extraction scripts)
- **Playwright** (browser automation for QuintoAndar, Loft)
- **Hermes Agent** (cron jobs, notifications, skill system)
- **SQLite / Turso** (data storage for listings)
- **GitHub Actions** (CI, scheduled extraction validation)

## Skills Versionadas (.hermes-skills/)

Skills do Hermes Agent copiadas para versionamento:

### Core
- `browser-automation/` — Playwright automation patterns, portal fallback chain, Cloudflare bypass
- `turso-db/` — Database operations

### Suporte
- `github-repo-management.md` — GitHub repo operations
- `github-pr-workflow.md` — PR workflow
- `cron-job-organization.md` — Organizar jobs cron
- `hermes-server-lock.md` — Port locking
- `dotenv-management.md` — .env file management
- `systematic-debugging.md` — Debugging methodology

## MCPs Versionados (mcp/)

Configurações dos MCP servers usados pelo projeto no Hermes:
- `jina-mcp.json` — Web search, read URLs, image search
- `context7-mcp.json` — Documentation queries
- `hermes-dash-canvas.json` — Canvas management

## Diretórios

| Path | Descrição |
|------|-----------|
| `skills/` | Skills específicas do projeto (QuintoAndar, Loft, Watchdog) |
| `config/` | Alvos de busca configuráveis (YAML/JSON) |
| `data/` | Resultados das execuções (JSON) |
| `scripts/` | Scripts auxiliares |
| `mcp/` | Configurações MCP versionadas |
| `tests/` | Testes |

## Conventions
- Skills ficam em `.hermes-skills/` (Hermes) e `skills/` (projeto)
- Resultados de execução em `data/results/` com timestamp
- Config de busca em `config/targets.yaml`
- Tool calls com `from hermes_tools import ...`
