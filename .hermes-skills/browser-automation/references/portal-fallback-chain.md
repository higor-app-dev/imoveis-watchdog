# Portal Fallback Chain for Brazilian Real Estate

## Multi-Portal Data Collection Strategy

When collecting data from Brazilian real estate portals, most have aggressive Cloudflare protection. Use this fallback chain:

```
1. web_extract(urls=[...])         → works on Viva Real (general pages)
2. Hermes browser tool             → blocked by Cloudflare on most portals
3. Local Playwright (stealth)      → works for OLX (SPA, partial access)
4. Google search (site:domain)     → fallback when direct access fails
```

## Portal-by-Portal Results

| Portal | Method | Status | Notes |
|--------|--------|--------|-------|
| **Loft** (loft.com.br) | Browser tool | ✅ Full | No Cloudflare. Direct URL params work: `?bairros=x~y&vagas=1` |
| **Viva Real** (vivareal.com.br) | web_extract | ✅ Partial | General bairro pages render. Filtered URLs (precoMinimo, vagas) return 404. Extract from summary tables. |
| **QuintoAndar** (quintoandar.com.br) | Browser tool | ✅ City+Type | Next.js SSR with client-side filters. Direct city/type URLs work (no Cloudflare). Structured JSON via `/_next/data/<buildId>/...json`. ~14 listings per SSR page. Bairro/price filters need browser interaction. See full reference below. |
| **OLX** (olx.com.br) | Local Playwright | ⚠️ Partial | Next.js SPA. `sp.olx.com.br` redirects to `www.olx.com.br`. Listings not in initial DOM. Need UI navigation. |
| **ZAP Imóveis** (zapimoveis.com.br) | None | ❌ | Cloudflare blocks everything |
| **SP Imóvel** (spimovel.com.br) | None | ❌ | 403 Forbidden |
| **Stória Imóveis** | None | ❌ | Blocked |
| **Mercado Livre Imóveis** | Browser tool | ❌ | "Hubo un error" page |

## QuintoAndar (quintoandar.com.br) — Deep Reference

QuintoAndar is a Next.js SPA (Server-Side Rendered). The city-level and property-type search pages render full HTML server-side, but neighborhood, price, and advanced filters are client-side SPA navigation.

### URL Patterns

| Pattern | Works? | Notes |
|---------|--------|-------|
| `/comprar/imovel/sao-paulo-sp-brasil` | ✅ | City-level buy search |
| `/comprar/imovel/sao-paulo-sp-brasil/apartamento` | ✅ | + property type filter |
| `/comprar/imovel/sao-paulo-sp-brasil/casa` | ✅ | Houses for sale |
| `/alugar/imovel/sao-paulo-sp-brasil` | ✅ | City-level rent search |
| `/sp-sao-paulo/bela-vista` | ❌ | SPA ignores bairro in URL path |
| `/sp-sao-paulo/centro/apartamento` | ❌ | SPA ignores sub-path filters |

### Structured Data via Next.js Data Route

The most efficient extraction method. After navigating to a search page, the Next.js build ID is available at `window.__NEXT_DATA__.buildId`. The data route returns all SSR state as JSON:

```
/_next/data/<buildId>/pt-BR/comprar/imovel/sao-paulo-sp-brasil.json
/_next/data/<buildId>/pt-BR/comprar/imovel/sao-paulo-sp-brasil/apartamento.json
```

The response contains `pageProps.initialState` with these keys:

```
route, router, progress, login, captcha, supportedCities, inAppMessages,
metaData, appData, visits, houses, favoriteLists, shopWindow, searchBar,
alertRegion, search
```

### House Data Structure (from `initialState.houses`)

Each house keyed by ID, with fields:

```json
{
  "id": "892820623",
  "salePrice": 1000000,
  "rentPrice": 3700,
  "area": 105,
  "bedrooms": 3,
  "bathrooms": 2,
  "parkingSpots": 3,
  "type": "Apartamento",
  "address": { "address": "R. Mal. Hermes da Fonseca", "city": "São Paulo" },
  "neighbourhood": "Santana",
  "regionName": "Santana",
  "condoIptu": { "total": 2412, "condo": 1800, "iptu": 612 },
  "forSale": true,
  "forRent": false,
  "shortSaleDescription": "Apartamento para comprar em Santana com 3 quartos...",
  "amenities": ["piscina", "academia", "portaria 24h", ...],
  "photos": [ { "url": "...", "caption": "..." } ],
  "categories": [],
  "listingTags": [],
  "isPrimaryMarket": false,
  "isFurnished": false,
  "yield": null,
  "yieldStrategy": null,
  "installations": [],
  "banner": null,
  "specialConditions": null
}
```

### Search Region Info (from `initialState.search.region.info`)

```json
{
  "hashId": "41d49u4ekw",
  "name": "São Paulo",
  "lat": -23.55052,
  "lng": -46.633309,
  "type": "REGION_CITY",
  "neighborhood": null,
  "city": "São Paulo",
  "cityHashId": "41d49u4ekw",
  "citySlug": "sao-paulo-sp-brasil",
  "slug": "sao-paulo-sp-brasil",
  "state": "SP",
  "country": "Brasil",
  "viewport": { "north": ..., "south": ..., "east": ..., "west": ... }
}
```

### Filter Choices Available (from `initialState.search.filters.choices`)

| Filter Key | Description |
|-----------|-------------|
| `salePrice` | Price range (`{min, max, selectedMin, selectedMax}`) |
| `bedrooms` | Number of bedrooms (array, e.g. `[2,3,4]`) |
| `bathrooms` | Number of bathrooms |
| `parkingSpaces` | Parking spots |
| `houseTypes` | Property types (e.g. `["Apartamento"]`) |
| `area` | Square meters range |
| `condoIptu` | Condo + IPTU total range |
| `furnished` | Boolean: is furnished |
| `nearSubway` | Boolean: near metro |
| `suites` | Number of suites |
| `acceptsPets` | Boolean: pets allowed |
| `exclusive` | Boolean: exclusive listing |
| `availability` | Availability status |
| `promotions` | Active promotions |
| `buyRented` | Already rented (buy-to-own occupied) |

Sale price range defaults: `{min: 150000, max: 20000000, interval: 10000}`

### Search Form UI Structure

The homepage search form (after clicking "Comprar" tab):

1. **Cidade** — dropdown with pre-populated cities (São Paulo, Rio de Janeiro, Belo Horizonte, Porto Alegre, Brasília, Curitiba)
2. **Bairro** — dropdown populated after city selection (extensive list of SP neighborhoods)
3. **Valor** — price range dropdown (R$ 400k, 800k, 1.2M, 1.6M, 2M, 2.4M, 7.5M, 15M, 22.5M, 30M)
4. **Quartos** — rooms dropdown (1+, 2+, 3+, 4+)
5. **Buscar imóveis** button

### Backend APIs Discovered

| Endpoint | Purpose |
|----------|---------|
| `apigw.prod.quintoandar.com.br/house-listing-search/v1/search/filters` | Available filter options (rent/sale categories, price ranges) |
| `apigw.prod.quintoandar.com.br/house-listing-search/v3/search/count` | Listing count for a search area |
| `identitytoolkit.googleapis.com/v1/accounts:lookup?key=AIzaSyAT-...` | Firebase auth (internal) |

### Browser Interaction Strategy

For filtered searches (neighborhood, price range, specific rooms):

1. Navigate to `https://www.quintoandar.com.br`
2. Click the "Comprar" tab
3. Click the city combobox → select city from dropdown
4. Click the bairro combobox → select neighborhood from dropdown
5. Set price range via value combobox
6. Set rooms via quartos combobox
7. Click "Buscar imóveis" button
8. Wait for SPA to load results
9. Extract data from DOM (listings visible in `<main>` as interactive groups) OR fetch `/_next/data/<buildId>/...json`

### Pagination

Initial SSR load returns ~14 houses. Subsequent pages are loaded client-side via the SPA — intercept network requests or scroll to trigger lazy loading. There is no simple `?page=N` URL parameter.

### Page Counts (São Paulo, June 2026)

| Filter | Count |
|--------|-------|
| All imóveis à venda em SP | ~149,182 |
| Apartamentos à venda em SP | ~87,371 |
| Casas à venda em SP | ~ (check dynamically) |

## Loft URL Parameter Reference

Loft is the most accessible portal. URL structure:

```
https://loft.com.br/venda/apartamentos/sp/sao-paulo/com-preco-500mil/
  ?bairros=bela-vista_sao-paulo_sp~consolacao_sao-paulo_sp
  &vagas=1
```

| Parameter | Format | Example |
|-----------|--------|---------|
| `bairros` | `slug_cidade_estado` separated by `~` | `bela-vista_sao-paulo_sp~consolacao_sao-paulo_sp` |
| `vagas` | integer (min) | `1`, `2` |
| price | via URL path | `/com-preco-500mil/` |

## Viva Real web_extract Pattern

Viva Real general pages render nicely with web_extract. Extract from summary tables:

```python
# Works:
web_extract(["https://www.vivareal.com.br/venda/sp/sao-paulo/centro/<bairro>/apartamento_residencial/"])

# Returns 404:
web_extract(["https://www.vivareal.com.br/venda/sp/sao-paulo/centro/<bairro>/apartamento_residencial/?precoMinimo=250000"])
```

Data is in the page as structured tables and market stats. Extract prices, areas, and counts from the summary section.

## OLX Local Playwright Notes

```python
# Start from homepage and navigate through UI
await page.goto("https://www.olx.com.br", wait_until="domcontentloaded")
await page.wait_for_timeout(3000)

# Click "Imoveis" category
imoveis = await page.query_selector('a[href*="imoveis"]')
await imoveis.click()
await page.wait_for_timeout(5000)

# Then filter by "Venda" or "Comprar" from the sub-menu
```

- Use `wait_until="domcontentloaded"` NOT `networkidle` (SPA keeps loading)
- OLX redirects subdomain (sp.olx.com.br) to www.olx.com.br — use the canonical domain
- Listings render after JS execution — may need 5-10s wait
- Screenshot to debug: `await page.screenshot(path="/tmp/screenshot.png")`
