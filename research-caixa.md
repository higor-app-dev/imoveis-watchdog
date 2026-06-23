# Venda de Imóveis Caixa — Research Report

**Site:** https://venda-imoveis.caixa.gov.br  
**Investigated:** 2026-06-21  
**Status:** Complete

---

## 1. Site Overview

Caixa Econômica Federal sells foreclosed/auctioned properties through this portal. Properties are sold through multiple modalities:

| Modalidade | Code | Description |
|-----------|------|-------------|
| 1º Leilão SFI | 4 | First auction |
| 2º Leilão SFI | 5 | Second auction (cheaper) |
| Concorrência Pública | 2 | Public competition |
| Leilão SFI - Edital Único | 14 | Single notice auction |
| Licitação Aberta | 21 | Open bidding |
| Venda Direta FAR | 9 | Direct sale (FAR program) |
| Venda Direta Online | 34 | Direct sale online |
| Venda Online | 33 | Online sale (most common) |

---

## 2. Anti-Bot Measures

**Severity: HIGH** — Radware Bot Manager with hCaptcha

- **Radware Bot Manager** (via `perfdrive.com`): Detects headless browsers, curl, and automation tools
- **hCaptcha**: Shown as interactive challenge after Radware pre-detection
- **Cookie tracking**: `__uzma`, `__uzmb`, `__uzmc`, `__uzmd`, `__uzme` cookies tracking behavior
- **JS behavioral analysis**: Mouse movement, touch events, scroll, click tracking
- **CSS visibility monitoring**: Checks if CAPTCHA iframe is hidden/visible
- **Server**: Azion edge platform (Brazilian CDN)
- **SSL**: Sectigo RSA DV certificate, valid until Dec 2026

**Status by page**:
| Page | Direct Access | Browser (headless) | curl |
|------|---------------|-------------------|------|
| `/sistema/busca-imovel.asp` | BLOCKED (Radware) | BLOCKED | BLOCKED |
| `/sistema/detalhe-imovel.asp` | BLOCKED (Radware) | BLOCKED | BLOCKED |
| `/sistema/download-lista.asp` | BLOCKED (JS needed) | BLOCKED | HTML page (no CAPTCHA on GET) |
| `/sistema/carregaListaImoveis.asp` | BLOCKED | BLOCKED | BLOCKED |
| `/fotos/F*.jpg` | **ACCESSIBLE** (no protection) | **ACCESSIBLE** | **ACCESSIBLE** |
| `/sistema/assets/` (CSS/JS) | **ACCESSIBLE** | **ACCESSIBLE** | **ACCESSIBLE** |

**Recommendation**: Scraping requires either:
1. **Playwright/Stealth** with residential proxy rotation (similar to QuintoAndar/Loft approach)
2. **Paid API** (Apify, BrightData, Zyte) — multiple Actors already exist on Apify
3. **CSV download** via Selenium+stealth (JS interaction needed to trigger download)

---

## 3. Technical Architecture

### 3.1. Technology Stack
- **Frontend**: Classic ASP (`.asp` pages), jQuery 1.10.2, custom CSS framework
- **Backend**: ASP on IIS or similar Microsoft stack
- **CDN/Edge**: Azion (Brazilian edge platform)
- **Bot Protection**: Radware Bot Manager (formerly ShieldSquare)
- **Analytics**: Google Tag Manager (GTM-NDBHSL)
- **Images**: Separate `/fotos/` path, plain JPEG, no protection
- **Download**: CSV files generated server-side, triggered via JS AJAX

### 3.2. Page Structure (Classic ASP SSR)
The site uses server-side rendered HTML with jQuery-driven AJAX for:
- Form navigation (multi-step search)
- Property listing loading (`carregaListaImoveis.asp`)
- CSV download

### 3.3. Key Endpoints

| Endpoint | Method | Parameters | Purpose |
|----------|--------|------------|---------|
| `/sistema/busca-imovel.asp` | POST | Filters (state, city, type, price, etc.) | Search form + results |
| `/sistema/carregaListaImoveis.asp` | POST | `hdnImov` (pipe-separated property IDs) | Loads property listing HTML |
| `/sistema/detalhe-imovel.asp` | GET | `hdnimovel={propertyNumber}` or `hdnOrigem=index&hdnimovel={propertyNumber}` | Property detail page |
| `/sistema/download-lista.asp` | POST | `cmb_estado=SP`, `hdn_estado=SP`, `hdnorigem=licitacoes` | CSV download |
| `/fotos/F{propertyNumber}.jpg` | GET | None | Property photo (NO PROTECTION) |

---

## 4. API Data Flow (Reverse Engineered)

### Step 1: Search Request
**POST** to search page (e.g., `busca-imovel.asp`) with form parameters:
```
hdn_estado=SP
hdn_cidade=9851
hdn_bairro=
hdn_tp_venda=0
hdn_tp_imovel=Selecione
hdn_area_util=Selecione
hdn_faixa_vlr=0
hdn_quartos=2
hdn_vg_garagem=Selecione
```

Content-Type: `application/x-www-form-urlencoded`  
**Note**: City codes appear to be numeric IDs (e.g., 9851 = São Paulo city)

### Step 2: Load Listing
The search response contains hidden `<input>` fields with ids like `hdnImov{X}` — these contain property IDs. The second request concatenates them and POSTs to:

**POST** `/sistema/carregaListaImoveis.asp`  
Body: `hdnImov=ID1||ID2||ID3||...`

Response: HTML with `<li class="group-block-item">` elements.

### Step 3: Detail Page
**GET** `/sistema/detalhe-imovel.asp?hdnimovel={propertyNumber}`  
(or with `hdnOrigem=index` parameter)

---

## 5. Available Data Fields

### 5.1. From CSV Download (basic fields)

| Field | CSV Column | Example |
|-------|-----------|---------|
| Property Number | `N° do imóvel` | 155550814458-7 |
| State | `UF` | SP |
| City | `Cidade` | SAO PAULO |
| Neighborhood | `Bairro` | VILA PRUDENTE |
| Address | `Endereço` | RUA DAS LOBELIAS, N. 380 Apto. 44 BL B |
| Price | `Preço` | 310000.00 |
| Appraisal Value | `Valor de avaliação` | 350000.00 |
| Discount | `Desconto` | 11.43 |
| Description | `Descrição` | 2 Quartos, 1 Vaga... |
| Sale Modality | `Modalidade de venda` | Venda Online |
| Access Link | `Link de acesso` | detalhe-imovel.asp?hdnimovel=... |

### 5.2. From Detail Page (full detail)

| Field | Type | Description |
|-------|------|-------------|
| `propertyNumber` | string | Unique property code |
| `state` | string | State UF |
| `city` | string | City name |
| `district` | string | Neighborhood |
| `zipCode` | string | Postal code (CEP) |
| `address` | string | Full address |
| `propertyType` | string | Property type (Apartamento, Casa, Terreno, Loja, etc.) |
| `rooms` | integer | Number of bedrooms |
| `garage` | integer | Parking spaces |
| `privateArea` | float | Private area in m² |
| `totalArea` | float | Total area in m² |
| `landArea` | float | Land area in m² |
| `evaluationValue` | float | Appraisal value (BRL) |
| `minimumSaleValue` | float | Minimum sale price (BRL) |
| `discount` | float | Discount percentage |
| `modality` | string | Sale modality |
| `firstAuctionDate` | string | Date/time of 1st auction |
| `secondAuctionDate` | string | Date/time of 2nd auction |
| `paymentMethods` | array | Accepted payment methods |
| `expenseRules` | array | Condo/tax payment rules |
| `description` | string | Full description |
| `registrationNumber` | string | Notary registration number |
| `notaryDistrict` | string | Comarca |
| `notaryOffice` | string | Office number |
| `propertyRegistration` | string | Municipal property registration |
| `auctionAnnotation` | string | Negative auction annotation status |
| `urlMatricula` | string | PDF link to property registration |
| `auctioneer` | string | Auctioneer name |
| `edital` | string | Notice ID |
| `numberItem` | integer | Item number in auction |
| `occupancy` | string | Occupied/Vacant status |
| `acceptsFGTS` | boolean | Whether FGTS funds can be used |
| `image` | string | Main photo URL |
| `url` | string | Detail page link |

---

## 6. Image URL Patterns

### Format
```
https://venda-imoveis.caixa.gov.br/fotos/F{propertyNumberDigits}.jpg
```

### Examples
- `https://venda-imoveis.caixa.gov.br/fotos/F155550814458721.jpg`
- `https://venda-imoveis.caixa.gov.br/fotos/F123456789012321.jpg`

### Pattern Explanation
- Base path: `/fotos/`
- Prefix: `F`
- Property number: The numeric portion of the property number WITHOUT the dash-suffix (e.g., property `155550814458-7` → image `F155550814458721.jpg` ... the exact mapping needs verification but pattern suggests hyphen is removed or replaced)
- Extension: `.jpg`

### Access
- **NO Radware protection** on `/fotos/` path
- HTTP 200 with `content-type: image/jpeg`
- Direct curl/HTTP access works
- Can be fetched without cookies or special headers
- `Last-Modified` headers present (useful for change detection)
- Content-Length indicates full images, not thumbnails
- **404** returned for non-existent image IDs

### Image Source (scraped)
From the listing HTML: `div.fotoimovel-col1 > img[src]` — the `src` attribute contains a relative path that needs to be prepended with `https://venda-imoveis.caixa.gov.br`

---

## 7. Existing Solutions / Tools

### 7.1. Open Source
- **DouglasFantoni/scrapper-imoveis** — NestJS/TypeScript scraper (Caixa + Lance Judicial + Leilão Imovel + Zuckerman). 32 stars. Last updated Sep 2023. Uses cheerio + axios.
- **luigibreda/caixa-sniper** — Web UI tool that works with CSV downloads from Caixa. TypeScript, MIT license. Uses CSV data, not direct API.

### 7.2. Commercial APIs
- **Apify: brasil-scrapers/caixa-leiloes-api** — $25/month. Full detail scraping. 5.0 stars.
- **Apify: pizani/caixa-imoveis-leiloes-api** — $10/month. By state/city/modalidade. 5.0 stars.
- **Apify: leadercorp/caixa-leiloes-scraper** — From $5/1000 results. Most comprehensive (detail page scraping).
- **Apify: brasildados/ia-leilao-caixa-api** — $15/1000 results. Includes AI market value estimation.
- **Criscon: Caixa Leilões API** — Commercial API for businesses.

### 7.3. Key Takeaway from Existing Solutions
The Apify actors manage to bypass Radware using Apify's residential proxy infrastructure + browser automation. Direct HTTP requests (curl, Python requests) consistently fail against Radware-protected endpoints.

---

## 8. Recommendations for imoveis-watchdog

### Option A: Playwright + Stealth (Self-Hosted)
- Use the existing `browser-automation` skill's Playwright patterns
- Need residential proxy integration (BrightData, Oxylabs, or similar)
- Stealth plugin + realistic user agent + viewport randomization
- Slower but no ongoing API costs
- **Risk**: Radware may adapt and block

### Option B: CSV Download (Simpler, Partial Data)
- The `/sistema/download-lista.asp` form can potentially be automated with Selenium
- ~~Select state → submit form → get CSV~~
- **Caveat**: The Radware JS challenge appears only with browser automation; a real browser session with human interaction may work
- CSV has limited fields (no image URLs, no detail data)

### Option C: Apify Actor (Recommended for Production)
- Use `pizani/caixa-imoveis-leiloes-api` ($10/month) or `leadercorp/caixa-leiloes-scraper` ($5/1000)
- Proven infrastructure, structured JSON output
- Apify handles Radware bypass
- No maintenance burden
- Integrate via Apify API (Python client available)

### Option D: Apify + Self-Hosted Hybrid
- Use Apify for Caixa scraping (hardest target)
- Keep existing self-hosted scrapers for other portals
- Single unified output format

### Regarding Image Scraping
Since images are **not protected**, they can be downloaded separately:
1. From listing data, extract the property number
2. Construct image URL: `https://venda-imoveis.caixa.gov.br/fotos/F{propertyNumberDigits}.jpg`
3. Download via simple HTTP GET
4. **Need to verify**: the exact digit transformation from property number to image filename

---

## 9. Summary

| Aspect | Finding |
|--------|---------|
| **Bot Protection** | Radware Bot Manager + hCaptcha — HIGH severity |
| **Data Format** | SSR HTML (classic ASP), CSV download available |
| **API Endpoints** | POST-based, no JSON API found; ASP pages return HTML fragments |
| **Data Richness** | Very high — 40+ fields from detail page |
| **Image Access** | UNPROTECTED — direct HTTP access via `/fotos/F*.jpg` |
| **Existing Software** | Apify Actors ($10-25/month), 2 open-source scrapers |
| **Extraction Difficulty** | HIGH — Radware bypass required for listing/detail pages |
| **Recommended Approach** | Apify Actor integration or Playwright+stealth+proxies |
