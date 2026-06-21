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

```
imoveis-watchdog/
├── .hermes-skills/       # Hermes Agent skills versionadas
├── mcp/                  # MCP server configs versionadas
├── config/
│   └── targets.yaml      # Portal search targets
├── data/
│   ├── .gitkeep          # Scraped outputs (gitignored)
│   └── results/          # Execution results with timestamps
├── scrapers/
│   └── loft/             # Playwright-based Loft scraper
├── skills/
│   ├── quinto-andar/     # QuintoAndar parser + tests
│   ├── loft/             # Loft parser
│   └── watchdog/         # Pipeline orchestration
├── tests/
│   ├── test_data.json    # Mock data for CI tests
│   └── test_extraction.py # CI extraction validation
├── watchdog_pipeline.py  # Main pipeline
├── watchdog_config.py    # Config loader
└── watchdog.yaml         # Main config
```

## Workflow: Adding a New Portal Skill

1. **Create skill directory** — `skills/<portal-name>/`
2. **Write the parser** — Python script that normalizes listings to the unified schema (see `skills/quinto-andar/quintoandar_parser.py` for reference schema: `list_id`, `title`, `url`, `price`, `price_raw`, `category`, `neighbourhood`, `municipality`, `uf`, `area_m2`, `rooms`, `bathrooms`)
3. **Add SKILL.md** — Describe the extraction approach, API endpoints used, known quirks
4. **Register in targets.yaml** — Add portal config under its name in `config/targets.yaml`
5. **Update watchdog_config.py** — Wire the new portal into the pipeline's portal registry
6. **Write tests** — At minimum add mock data and a test script in `tests/`
7. **Commit** — Use conventional commit format: `feat: add <portal> parser and integration`

## Running Tests

```bash
# Mock data extraction test (CI-compatible)
python tests/test_extraction.py

# Individual portal parser tests
python skills/quinto-andar/test_quintoandar_parser.py

# Run all tests
python -m pytest tests/
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
