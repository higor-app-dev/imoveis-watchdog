# imoveis-watchdog — Agent Guide

> Instruções para agentes de IA (Hermes, Claude Code, etc.) trabalharem neste repositório.

## Required Tools

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.11+ | Core extraction, pipeline, parsers |
| pip | (any) | Install Python dependencies |
| git | (any) | Version control |
| Node.js | 18+ | Playwright-based scraping (Loft portal) |
| npm | (any) | Install Playwright + browser deps |
| Playwright | latest | Browser automation (Loft scraper) |

Optional but used in CI:
- GitHub CLI (`gh`) — for PRs and CI operations
- Hermes Agent — for cron jobs and skill management

## Setup

```bash
# 1. Python dependencies
pip install -r requirements.txt

# 2. Node dependencies for Playwright scrapers
cd scrapers/loft && npm install && cd ../..

# 3. Copy env template
cp .env.example .env   # edit with your tokens
```

## Project Layout

| Path | Descrição |
|------|-----------|
| `.hermes-skills/` | Hermes Agent skills versionadas |
| `config/` | Alvos de busca configuráveis (YAML/JSON) |
| `data/` | Resultados das execuções (JSON) |
| `mcp/` | Configurações MCP versionadas |
| `scrapers/` | Scrapers especializados (Loft com Playwright + stealth) |
| `scripts/` | Scripts auxiliares |
| `skills/` | Skills de extração (Sodré Santoro, Zuk, QuintoAndar, Loft, etc.) |
| `tests/` | Testes |

## Workflow: Adding a New Portal Skill

1. **Create skill directory** — `skills/<portal-name>/`
2. **Write the parser** — Python script that normalizes listings to the unified schema
3. **Add SKILL.md** — Describe extraction approach, API endpoints, known quirks
4. **Register in `config/portals.yaml`** — Add portal entry under `portals:`
5. **Register in `config/targets.yaml`** — Add search targets
6. **Write tests** — At minimum add unit tests in `skills/<portal>/test_*.py`
7. **Commit** — Use conventional commit format: `feat: add <portal> parser and integration`

## Running Tests

```bash
# Individual portal parser tests
python skills/sodre_santoro/test_sodre_santoro_parser.py
python skills/quinto-andar/test_quintoandar_parser.py

# All tests
python -m pytest tests/ skills/*/test_*.py
```

## Running the Pipeline

```bash
# Full pipeline
python watchdog_pipeline.py

# Force notification (even without changes)
python watchdog_pipeline.py --force

# Dry run (no state persistence, no notification)
python watchdog_pipeline.py --dry-run

# Reset state (full rescan)
python watchdog_pipeline.py --reset
```

## Conventions

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short description>

Types:
  feat:     New feature (parser, skill, integration)
  fix:      Bug fix
  docs:     Documentation only
  refactor: Code change with no functional change
  test:     Adding or fixing tests
  chore:    Build, CI, tooling
```

Examples:
- `feat: implement QuintoAndar data parser`
- `docs: rewrite README with accurate project overview`
- `fix: handle optional fields in QuintoAndar parser`

### Skills Versioning

- Hermes Agent skills used by the project are **copied** into `.hermes-skills/` for versioning
- MCP server configs are versioned in `mcp/`
- Portal-specific Python parsers live in `skills/<portal>/` (these are the project's own skills, not Hermes skills)
- Never add `.hermes-skills/` to `.gitignore`

### Code Style

- Python: PEP 8, 4-space indentation
- Type hints preferred for function signatures
- Import Hermes tools with `from hermes_tools import ...` when running from Hermes Agent
- Results go to `data/results/` with UTC timestamps in filenames (`%Y%m%d_%H%M%S_%f`)
- Configuration in YAML (`config/targets.yaml`, `watchdog.yaml`)

### Hermes Agent Details

When working via Hermes Agent:
- Load the relevant portal skill: `skill_view(name='quinto-andar')` or similar
- JSON outputs at `data/results/` can be read with `read_file(path)`
- For web searches use Jina AI MCP (`mcp_jina_search_web`)
- kanban tasks are the primary workflow unit for multi-step changes

### Data Schema

All portals normalize to this unified listing schema:

```python
{
    "list_id": str | int,       # Unique ID from source
    "title": str,                # Listing title
    "url": str,                  # Full URL to listing
    "price_raw": str,            # Raw price text (e.g. "R$ 450.000")
    "price": float | None,       # Parsed numeric price
    "category": str,             # "compra" or "aluguel"
    "neighbourhood": str,        # Bairro
    "municipality": str,         # Cidade
    "uf": str,                   # Estado (e.g. "SP")
    "area_m2": int | None,       # Area in m²
    "rooms": int | None,         # Number of bedrooms
    "bathrooms": int | None,     # Number of bathrooms
}
```
