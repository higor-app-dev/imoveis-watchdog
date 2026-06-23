# Loft Scraper (Playwright + Stealth)

Extrator de listings da Loft (loft.com.br) usando Playwright com stealth para bypassar CloudFront.

## Como funciona

1. O script Node.js (`scrape-loft.js`) abre um Chromium headless com `playwright-extra` + `puppeteer-extra-plugin-stealth`
2. A página SSR da Loft carrega via Next.js com dados completos no `__NEXT_DATA__` (185KB)
3. Para paginação, a **Landscape API** (`landscape-api.loft.com.br`) é chamada via `page.evaluate()` com `fetch()`
4. Os dados são mapeados para o schema Imovel unificado do projeto

## Pré-requisitos

```bash
cd scrapers/loft
npm install
```

Node.js 18+ com Playwright. O Chromium é baixado automaticamente pelo Playwright.

## Uso direto (Node.js)

```bash
# 1 página (default)
node scrape-loft.js

# 3 páginas
node scrape-loft.js --pages 3

# Todas as páginas disponíveis (264 páginas = ~10.000 listings)
node scrape-loft.js --all

# Modo com GUI (headed)
node scrape-loft.js --headed

# URL customizada (bairro específico)
node scrape-loft.js --url "https://loft.com.br/venda/apartamentos/sp/sao-paulo/bela-vista"
```

## Uso via Python (recomendado)

```python
from skills.loft.loft_parser import run_scraper, from_loft_payload

# Extrair listings
imoveis = run_scraper(pages=3)  # Returns list[dict]

# Parsear JSON já extraído
with open('listings.json') as f:
    imoveis = from_loft_payload(json.load(f))
```

Ou via CLI:

```bash
python3 -m skills.loft.loft_parser run --pages 3 --output /tmp/imoveis.json
python3 -m skills.loft.loft_parser parse data/results/loft_results_2026-06-21.json
```

## Estrutura dos dados

Cada listing retorna (no schema Imovel):

| Campo | Exemplo | Descrição |
|-------|---------|-----------|
| `id` | `1fdwpn8` | ID do anúncio na Loft |
| `preco_venda` | 2600000 | Preço de venda (R$) |
| `preco_anterior` | 2800000 | Preço anterior (para detectar redução) |
| `percentual_reducao` | 7.14 | % de redução se houver |
| `area` | 233 | Área em m² |
| `quartos` | 2 | Quartos |
| `suites` | 2 | Suítes |
| `banheiros` | 2 | Banheiros |
| `vagas` | 2 | Vagas de garagem |
| `condominio` | 3467 | Condomínio (R$) |
| `iptu` | 938.50 | IPTU (R$) |
| `bairro` | Vila Madalena | Bairro |
| `latitude` / `longitude` | -23.552 / -46.693 | Geolocalização |
| `endereco` | Rua Fidalga | Logradouro |
| `agencia` | Foxter Imobiliária | Imobiliária anunciante |
| `imagens` | [...] | URLs das fotos |

## Descobertas técnicas

- **CloudFront bypass**: O Playwright local com stealth (`--disable-blink-features=AutomationControlled` + `addInitScript` com override de `navigator.webdriver`, `plugins`, `languages`) bypassa o CloudFront da Loft
- **`--disable-web-security` QUEBRA a API**: Essa flag faz o CloudFront da Landscape API retornar 403. **NUNCA use** essa flag no scraping da Loft
- **Landscape API**: `landscape-api.loft.com.br/listing/v3/search` — retorna JSON com listings, paginação (page 0-based, hitsPerPage=38, totalPages=264, totalListings=240K+)
- **Dual SSR shape**: O `__NEXT_DATA__` pode vir em dois formatos:
  - Nested: `{listing: {...}}` (com `listingsCount`, `groupedListings`)
  - Flat: `{id: ..., price: ..., ...}` (diretamente o objeto listing)
  - O parser aceita ambos

## Observações

- Cada página = 38 listings
- Total em SP: ~240.673 listings, ~264 páginas
- Leva ~30s por página (SSR + 300ms delay)
- 264 páginas levariam ~2h para completar
