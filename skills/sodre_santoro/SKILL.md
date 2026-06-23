---
name: sodre-santoro
description: Extração de leilões de imóveis do Sodré Santoro (leilao.sodresantoro.com.br) via API REST pública — sem autenticação, ~13 lotes ativos, múltiplas imagens por lote
version: 1.1.0
platforms: [linux, macos]
environments: [imoveis-watchdog]
metadata:
  hermes:
    tags: [imoveis-watchdog, extraction, leilao, sodresantoro, rest-api]
    related_skills: [output_schema, imovel_schema, portal_registry, mega-leiloes, loft]
---

# Sodré Santoro — Extração de Leilões de Imóveis

> Extrai dados do Sodré Santoro (leilao.sodresantoro.com.br) via API REST pública.
> Sem autenticação, sem Cloudflare nas requisições de listagem.

## Estrutura

```
skills/sodre_santoro/
├── sodre_santoro_parser.py     # Parser completo (696+ linhas)
├── test_sodre_santoro_parser.py # Testes unitários (637+ linhas)
├── SKILL.md                     # Esta documentação
```

## Estratégia de Extração

### API REST (primária, sem restrições)

Sodré Santoro expõe uma API REST pública **sem autenticação** para busca de leilões:

| Parâmetro | Valor |
|-----------|-------|
| Endpoint | `GET https://prd-api.sodresantoro.com.br/api/v1/auctions` |
| Query params | `segmentName=imoveis&limit=20&page=1` |
| Paginação | API sempre retorna mesmos ~14 leilões (páginação não funcional) |
| ~Total | ~13 lotes de imóveis ativos |
| Rate limit | Nenhum detectado |

**Vantagens:**
- ✅ Sem autenticação — requisições HTTP diretas
- ✅ Sem Cloudflare/WAF — API pública aberta
- ✅ Dados estruturados (JSON) com todos os campos
- ✅ Múltiplas imagens por lote no `lot_pictures[]`
- ✅ URLs absolutas das imagens já incluídas

**Limitações:**
- ❌ Detail page (`leilao.sodresantoro.com.br/{auction_id}/{lot_id}`) atrás de Azion WAF — retorna 403 Forbidden sem browser
- ❌ API não expõe 2ª data de praça separadamente
- ❌ Paginação retorna mesmos dados em todas as páginas

## Image CDN Pattern

All images are served from `photos.sodresantoro.com.br` via **Azion Edge** with **Azion Image Processing** for dynamic on-the-fly resize.

### URL Pattern

```
https://photos.sodresantoro.com.br/imoveis/{auction_id}/{lot_id}/{timestamp}_{hash}I{N}N{N}.JPG
```

Example:
```
https://photos.sodresantoro.com.br/imoveis/28679/2763869/1780339198_I16940N16.JPG
```

### Dynamic Resize (Azion Image Processing)

The CDN supports the `?ims=` query parameter for dynamic image resizing:

| Size Name | `?ims=` Param | ~File Size | Typical Usage |
|-----------|--------------|------------|---------------|
| Thumbnail | `?ims=300x` | ~17 KB | Gallery thumbnails |
| Medium | `?ims=916x` | ~160 KB | Detail page gallery |
| Large | `?ims=1920x` | ~500 KB | Lightbox / full-screen |
| Original | (no param) | ~300 KB | As returned by API |

**Resolution examples (same image at different sizes):**

| Resolution | URL |
|-----------|-----|
| Original | `https://photos.sodresantoro.com.br/imoveis/28679/2763869/1780339198_I16940N16.JPG` |
| Large (1920×) | Same URL + `?ims=1920x` |
| Medium (916×) | Same URL + `?ims=916x` |
| Thumb (300×) | Same URL + `?ims=300x` |

### Multiple Images Per Lot

A listing can have **1–13+ photos**, each with its own filename hash. The API returns **all** of them in the `lot_pictures` array — no SSR scraping needed.

Statistics (per page of 13 active lots):
- **Avg photos/lot**: 5.2
- **Median**: 3
- **Max**: 13
- **Min**: 1

### URL Normalization

The parser's `_normalize_photo_url()` strips any `?ims=` resize params to always return the **original full-resolution** URL. To get a specific size, use `_generate_resized_url(base_url, size_name)`:

```python
from sodre_santoro_parser import _normalize_photo_url, _generate_resized_url

# Get full-res URL (strips ?ims= if present)
full = _normalize_photo_url("https://photos.sodresantoro.com.br/...JPG?ims=916x")

# Generate specific sizes
thumb = _generate_resized_url(full, "thumb")    # ?ims=300x
medium = _generate_resized_url(full, "medium")  # ?ims=916x
large = _generate_resized_url(full, "large")    # ?ims=1920x

# Or get all at once
from sodre_santoro_parser import _generate_all_resolutions
all_sizes = _generate_all_resolutions(full)
# Returns: {"original": "...", "large": "...", "medium": "...", "thumb": "..."}
```

### Related Documents

The detail page (Azion-protected) may contain PDF documents (edital, matrícula) which are **not** accessible via the list API.

## Output Fields

### Unified Schema (Imovel-compatible)

| Field | Source | Description |
|-------|--------|-------------|
| `id` | Constructed | `sodre_{auction_id}_{lot_id}` |
| `titulo` | `lot_title` | Título do lote |
| `url` | Detail URL | `https://leilao.sodresantoro.com.br/{auction_id}/{lot_id}` |
| `fonte` | Constant | `sodre_santoro` |
| `preco_venda` | `bid_actual` or `bid_initial` | Maior lance ou lance inicial (R$) |
| `preco_anterior` | `tj_praca_value` | Avaliação judicial / preço de praça (R$) |
| `bairro` | Parsed from title | `_extract_city_state()` → 3º segmento |
| `cidade` | Parsed from title | `_extract_city_state()` → 2º segmento |
| `uf` | Parsed from title | `_extract_city_state()` → último segmento |
| `tipo` | Parsed from title | Tudo antes dos 3 últimos segmentos |
| `descricao` | `lot_description` | Descrição do lote |
| `fotos` | `lot_pictures` | Lista de URLs full-resolution |
| `image_urls` | Derivado de `fotos` | Cada foto com {original, large, medium, thumb} |
| `data_publicacao` | `closingDate` | Data de encerramento (ISO 8601) |
| `data_coleta` | Now | Timestamp da coleta |

### Auction-specific Fields

| Field | Source | Description |
|-------|--------|-------------|
| `auction_id` | `id` | ID do leilão |
| `lot_id` | `lot_id` | ID do lote |
| `auction_type` | `type` | `judicial` (1), `fiscal` (2), `extrajudicial` (0) |
| `closing_date` | `closingDate` | Data de encerramento |
| `auctioneer` | `auctioneer` | Nome do leiloeiro |
| `court_name` | `name` | Nome do tribunal / vara |
| `bid_initial` | `bid_initial` | Lance inicial (R$) |
| `bid_actual` | `bid_actual` | Lance atual (R$) |
| `tj_praca_value` | `tj_praca_value` | Valor da 2ª praça (R$) |
| `tj_praca_discount` | `tj_praca_discount` | % desconto para 2ª praça |
| `lot_visits` | `lot_visits` | Nº de visitas |
| `lot_bids` | `lot_bids` | Nº de lances |
| `financiable` | `lot_is_financiable` | Financiável? |
| `installment` | `lot_installment` | Parcelamento? |

## Uso

### Python

```python
from skills.sodre_santoro.sodre_santoro_parser import (
    fetch_listings,
    from_sodre_payload,
    from_sodre_listing,
    _generate_all_resolutions,
)

# Fetch from API directly
imoveis = fetch_listings(max_pages=2)
print(f"Extraídos {len(imoveis)} imóveis")

# Acessar image_urls com resoluções
for imovel in imoveis[:2]:
    print(f"  {imovel['titulo']} — {len(imovel['fotos'])} fotos")
    for entry in imovel['image_urls']:
        print(f"    thumb:  {entry['thumb']}")
        print(f"    medium: {entry['medium']}")
        print(f"    large:  {entry['large']}")
```

### CLI

```bash
# Fetch listings da API (teste)
cd /home/higor/imoveis-watchdog
python -m skills.sodre_santoro.sodre_santoro_parser fetch --pages 2

# Fetch e salvar
python -m skills.sodre_santoro.sodre_santoro_parser fetch --pages 2 --output data/results/sodre_2pages.json

# Parse arquivo JSON já baixado
python -m skills.sodre_santoro.sodre_santoro_parser parse data/results/sodre_2pages.json
```

## Paginação

A API aceita parâmetros `page` e `limit`, mas sempre retorna os mesmos ~14 leilões independente da página. O parser tem `consecutive_empties` detection: se 2 páginas consecutivas retornarem vazias, a extração é encerrada. Para o dataset atual (~13 lotes ativos), 1 página (`limit=20`) é suficiente.

## Anti-bot

- **API REST**: Sem proteção — requisições HTTP diretas funcionam
- **Detail page** (`leilao.sodresantoro.com.br`): Azion Edge WAF — retorna 403 para curl sem headers de browser
- **CDN de fotos** (`photos.sodresantoro.com.br`): Acessível sem restrições

## Testes

```bash
cd /home/higor/imoveis-watchdog
python skills/sodre_santoro/test_sodre_santoro_parser.py

# Cobertura: parsing, payload, preços, fotos, image_urls com resoluções,
#             timestamps, paginação, deduplicação, normalização de URLs CDN
```

## CDN Pattern Summary

| Aspecto | Detalhe |
|---------|---------|
| Provider | Azion Edge com Azion Image Processing |
| Domain | `photos.sodresantoro.com.br` |
| Path | `/imoveis/{auction_id}/{lot_id}/{filename}` |
| Resize param | `?ims={width}x` (width-based) ou `?ims=x{height}` (height-based) |
| Available sizes | `thumb`: 300×, `medium`: 916×, `large`: 1920× |
| Max photos/lot | 13+ |
| WAF status | CDN open, detail page blocked |
