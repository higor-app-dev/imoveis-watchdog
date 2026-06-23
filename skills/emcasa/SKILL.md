---
name: emcasa
description: "Skill de extração de dados do EmCasa — três abordagens: (1) API Foundation/Garagem AI (cdn.fndn.ai) com cliente HTTP, paginação e cache, (2) Pipeline unificado com PaginatedCache + TokenBucket + emcasa_collect.py para crawl completo em lote, (3) SSR Algolia InstantSearch via extração de JSON do HTML + parser de hits. Schema unificado de 28 campos, facet stats, detecção de redução de preço."
---

# EmCasa — Extração de Imóveis

## Visão Geral

O EmCasa (emcasa.com) é um Next.js que oferece **três formas** de extrair dados dos imóveis:

1. **API Foundation/Garagem AI** (cdn.fndn.ai) — API pública REST sem autenticação, via POST
2. **Pipeline Unificado** — scripts/emcasa_collect.py com PaginatedCache + TokenBucket + EmCasaClient
3. **Algolia InstantSearch (SSR)** — JSON embutido no HTML via window[Symbol.for("InstantSearchInitialResults")]

Todas as abordagens estão implementadas e podem ser usadas conforme a necessidade.

## Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `config.yaml` | Configuração — cidades, schema, paginação, cache |
| `__init__.py` | Exporta todas as funções públicas (16 símbolos) |
| `emcasa_api.py` | Cliente HTTP da API Foundation (POST) com paginação, cache dual (PageCache + PaginatedCache) e rate limiting dual (delay simples + TokenBucket) |
| `emcasa_parser.py` | Parser da API Foundation para schema unificado `Imovel` |
| `extract_page.py` | Extração do JSON do Algolia do HTML SSR (curl + brace-matching) |
| `algolia_parser.py` | Parser de hits do Algolia para schema unificado (28 campos) |
| `test_emcasa_api.py` | Testes unitários + integração da API Foundation (22 unitários + 3 integração) |
| `test_algolia_parser.py` | 8 testes — parser, fallbacks, priceChangePercent, coordenadas |
| `test_extract_page.py` | 20 testes (pytest) — extração SP/RJ, facets, validação |

**Scripts externos (projeto raiz):**

| Arquivo | Descrição |
|---------|-----------|
| `scripts/emcasa_collect.py` | Driver unificado de coleta — lê watchdog.yaml, integra PaginatedCache + TokenBucket, coleta todas as regiões configuradas |
| `scripts/facet_stats.py` | Computa estatísticas de facets (preço min/max, área min/max, quartos, tipos, fontes, etc.) de datasets coletados |
| `skills/cache/cache_engine.py` | PaginatedCache — cache de páginas com TTL, namespace, escrita atômica, thread-safe (26 testes) |
| `skills/rate_limiter/rate_limiter.py` | TokenBucket + AsyncTokenBucket — rate limiting thread-safe com wrapped HTTP clients (30 testes) |
| `config/targets.yaml` | Alvos de busca multi-portal (EmCasa, QuintoAndar, etc.) |
| `watchdog.yaml` | Config do watchdog — cidades, bairros, price_ranges, cache |

---

## Abordagem 1: API Foundation/Garagem AI

A API Foundation é pública, sem autenticação, e retorna dados JSON estruturados de todos os imóveis.

### API Endpoint

```
POST https://cdn.fndn.ai/site/api/sites/{site_id}/search
```

**Site ID:** `ab158f8f-0a75-4f9f-8a9b-54b834aa2698`

### Request Body

```json
{
  "q": "*",
  "per_page": 12,
  "page": 1,
  "filter_by": "location_state:=SP && location_city:=São Paulo"
}
```

### Filtros (filter_by)

Formato: `"campo:=valor && campo2:=valor2"`

| Campo | Exemplo |
|-------|---------|
| location_state | `location_state:=SP` |
| location_city | `location_city:=São Paulo` |
| location_neighborhood | `location_neighborhood:=Vila Madalena` |
| property_type | `property_type:=apartment` |

### Uso CLI (API Foundation)

```bash
cd ~/imoveis-watchdog

# Info de uma cidade
python skills/emcasa/emcasa_api.py --cidade "São Paulo" --apenas-info

# Todas as páginas
python skills/emcasa/emcasa_api.py --cidade "Diadema" --todas --delay 0.3

# Faixa de páginas
python skills/emcasa/emcasa_api.py --cidade "São Paulo" --paginas 0-5 --pretty

# Salvar em arquivo
python skills/emcasa/emcasa_api.py --cidade "Diadema" --todas -o diadema.json --pretty
```

### Uso como Biblioteca (API Foundation)

```python
from skills.emcasa.emcasa_api import EmCasaClient, parse_hit, filter_city, PageCache

client = EmCasaClient(delay=0.5, cache=PageCache())

# Página única
result = client.search_page(
    "location_state:=SP && location_city:=São Paulo",
    page=1, per_page=12,
)

# Todas as páginas
all_hits = client.search_all(
    filter_city("São Paulo", "SP"),
    per_page=12,
    on_progress=lambda page, nb_pages, total, hits: print(f"{page}/{nb_pages}"),
)

# Converte para schema normalizado
for raw_hit in result.hits:
    imovel = parse_hit(raw_hit)
    print(f"{imovel['titulo']} - R$ {imovel['preco_venda']}")
```

---

## Abordagem 3: Pipeline Unificado (emcasa_collect.py)

O **pipeline unificado** integra PaginatedCache (cache de páginas) + TokenBucket (rate limiter) + EmCasaClient em um único driver de coleta que lê a configuração do `watchdog.yaml` e itera por todas as combinações de cidade × bairro × faixa de preço.

### Arquitetura

```
scripts/emcasa_collect.py          ← orquestrador (lê watchdog.yaml, dirige coleta)
skills/
├── cache/cache_engine.py          ← PaginatedCache (TTL, namespace, thread-safe)
├── rate_limiter/rate_limiter.py   ← TokenBucket (thread-safe, 30 testes)
└── emcasa/
    ├── emcasa_api.py              ← EmCasaClient (aceita ambas as formas)
    └── emcasa_parser.py           ← parse_hit() para schema unificado
watchdog.yaml                      ← configuração: cidades, bairros, price_ranges, cache
data/
├── cache/                         ← cache de páginas (reusado entre runs)
└── results/                       ← datasets coletados (JSON timestamped)
```

### Configuração (watchdog.yaml)

```yaml
watchdog:
  cities:
    - name: "São Paulo"
      state: "SP"
    - name: "Rio de Janeiro"
      state: "RJ"

  neighborhoods:
    - name: "Centro"
      city: "São Paulo"
    - name: "Pinheiros"
      city: "São Paulo"
    - name: "Copacabana"
      city: "Rio de Janeiro"

  price_ranges:
    - label: "econômico"
      min: 150000
      max: 350000
    - label: "médio"
      min: 350000
      max: 700000
    - label: "alto"
      min: 700000
      max: 1500000
    - label: "luxo"
      min: 1500000
      max: 5000000

  cache:
    enabled: true
    dir: "data/cache"
    ttl_seconds: 1800
```

### Uso CLI (Pipeline Unificado)

```bash
cd ~/imoveis-watchdog

# Crawl completo (todas as cidades, todos os bairros)
python scripts/emcasa_collect.py

# Apenas uma cidade
python scripts/emcasa_collect.py --city "São Paulo"

# Teste rápido (limitar páginas por região)
python scripts/emcasa_collect.py --max-pages 2

# Dry-run (mostra o que seria feito)
python scripts/emcasa_collect.py --dry-run

# Salvar em arquivo específico
python scripts/emcasa_collect.py --output data/results/sp_full.json
```

### Integração com PaginatedCache + TokenBucket

O `EmCasaClient` aceita parâmetros opcionais que substituem os mecanismos built-in:

```python
from skills.cache.cache_engine import PaginatedCache
from skills.rate_limiter.rate_limiter import TokenBucket
from skills.emcasa.emcasa_api import EmCasaClient, filter_city

cache = PaginatedCache(cache_dir="data/cache", default_ttl_seconds=1800)
bucket = TokenBucket(rate=2, burst=3)

client = EmCasaClient(
    rate_limiter=bucket,
    paginated_cache=cache,
)

result = client.search_all(filter_city("São Paulo"), per_page=250)
print(f"{len(result)} listings com {client.get_stats()['cache_hits']} cache hits")
```

**Prioridade do cache:**
1. `paginated_cache` (PaginatedCache externo) — usado quando fornecido
2. `cache` (PageCache built-in) — fallback legado

**Rate limiting:**
1. `rate_limiter` (TokenBucket externo) — usado quando fornecido
2. `delay` simples — fallback legado (`time.sleep`)

### Facet Stats

O script `scripts/facet_stats.py` computa estatísticas agregadas de datasets coletados:

```bash
# Analisar datasets específicos
python scripts/facet_stats.py data/results/emcasa_collect_*.json

# Salvar facets como JSON
python scripts/facet_stats.py --output data/facets.json

# Todos os datasets em data/results/
python scripts/facet_stats.py
```

**Saída:** preço (min/max/média/mediana), área (min/max/média), quartos (distribuição), tipos, fontes, bairros, cidades, total de fotos.

---

## Abordagem 2: Algolia InstantSearch (SSR)

O EmCasa renderiza os dados de busca no lado servidor via Next.js e embute o resultado do Algolia em:

```js
window[Symbol.for("InstantSearchInitialResults")] = { ... }
```

A função `extract_page()` usa curl para baixar o HTML e brace-matching para extrair o JSON.

### Dados Extraídos (28 campos por imóvel)

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `askingPrice` | float | Preço anunciado |
| `price` | float | Preço atual |
| `previousPrice` | float \| None | Preço anterior |
| `priceChangePercent` | float \| None | % de variação (negativo = redução!) |
| `bedrooms` | int \| None | Dormitórios |
| `bathrooms` | int \| None | Banheiros |
| `parkingSpaces` | int \| None | Vagas |
| `suites` | int \| None | Suítes |
| `property_area_total` | int \| None | Área total m² |
| `property_type` | str | Tipo (apartment, house, penthouse) |
| `location_neighborhood` | str | Bairro |
| `location_city` | str | Cidade |
| `location_street` | str | Logradouro |
| `condoFee` | float \| None | Condomínio |
| `propertyTax` | float \| None | IPTU |
| `propertyFeatures` | list[str] | Características (piscina, academia...) |
| `buildingAmenities` | list[str] | Amenidades do edifício |
| `imageUrls` | list[str] | URLs das fotos (normalizadas para `/large` — alta resolução) |
| `primaryImageUrl` | str | URL da foto principal (usada como primeira foto) |
| `thumbnailUrls` | list[str] | URLs das thumbnails |
| `listing_type` | str | sale / rent |
| `propertyTitle` | str | Título do anúncio |
| `description` | str | Descrição |
| `coordinates` | dict \| None | `{lat, lng}` |
| `floor` | str | Andar |
| `buildingName` | str | Nome do edifício |
| `photoCount` | int \| None | Quantidade de fotos |
| `videoCount` | int \| None | Quantidade de vídeos |
| `status` | str | available / sold |

### Uso como Biblioteca (Algolia SSR)

```python
from skills.emcasa.extract_page import extract_page, extract_page_results
from skills.emcasa.algolia_parser import parse_hit, parse_hits

# Extrai dados crus de uma página
data = extract_page("sp", 0)          # SP, página 0
hits = extract_page_results("rj", 2)  # RJ, página 2 (atalho)

# Converte para schema unificado
imoveis = parse_hits(hits)
for imv in imoveis:
    if imv["previousPrice"] and imv["price"] < imv["previousPrice"]:
        print(f"REDUÇÃO! {imv['propertyTitle']} - R${imv['price']} ({imv['priceChangePercent']}%)")
```

### Crawl Completo

O orquestrador em `scripts/emcasa_crawl.py` percorre todas as páginas de SP e RJ, aplica filtros e salva em JSON.

```bash
cd ~/imoveis-watchdog

# Crawl completo SP + RJ (~15.600 imóveis)
python scripts/emcasa_crawl.py

# Apenas SP
python scripts/emcasa_crawl.py --city sp

# Com filtros
python scripts/emcasa_crawl.py --city rj --listing-type sale \
  --min-price 500000 --max-price 1500000 \
  --neighborhood "Copacabana,Ipanema"

# Rate limit customizado
python scripts/emcasa_crawl.py --rate-limit 0.3
```

### Paginação

- **hitsPerPage:** 12 (default da API)
- **Page range:** 0 a 1066 (SP: ~12.800 imóveis / 12 = 1067 páginas)
- **Crawl SP completo:** ~46 minutos com rate-limit 1s (0 erros)
- **Crawl RJ completo:** ~5 minutos
- **Total crawl:** ~15.684 listings (SP: 14.208, RJ: 1.476)

### Filtros no Crawl

| Flag | Descrição |
|------|-----------|
| `--city sp,rj` | Cidade(s) para crawl |
| `--listing-type sale,rent` | Tipo de negócio |
| `--neighborhood "Bela Vista,Pinheiros"` | Bairros (OR) |
| `--min-price 500000` | Preço mínimo |
| `--max-price 1500000` | Preço máximo |
| `--rate-limit 0.3` | Segundos entre requests |
| `--output path/to/output.json` | Caminho customizado |

### Extração de Imagens

**Campo JSON usado:** `imageUrls` — array de URLs absolutas de fotos dos imóveis, retornado pela API Foundation/Garagem AI e também disponível no Algolia SSR. O campo `primaryImageUrl` contém a URL da foto principal (usada como primeira foto — índice 0 em `fotos[]`).

**Padrão CDN:** `https://cdn.fndn.ai/images/{hash}/{suffix}`

O CDN `cdn.fndn.ai` serve a mesma imagem em várias resoluções via sufixo:

| Sufixo | Tamanho | Uso |
|--------|---------|-----|
| `/thumbnail` | ~6KB | Miniatura (não usada) |
| `/detail` | ~238KB | Média resolução (não usada) |
| `/large` | ~1MB | **Alta resolução (target)** |

**Normalização:** Todas as URLs de imagem são automaticamente convertidas para `/large` (alta resolução). URLs de outros CDNs passam sem alteração. Duplicatas são removidas por URL única.

### Detecção de Redução de Preço

O campo `priceChangePercent` é computado quando `previousPrice ≠ price`:

```python
# Fórmula: ((price - previousPrice) / previousPrice) * 100
# Negativo = redução de preço!
if result["priceChangePercent"] and result["priceChangePercent"] < 0:
    print(f"Redução de {abs(result['priceChangePercent'])}%")
```

---

## Cache (API Foundation)

O EmCasaClient suporta **dois sistemas de cache** que podem ser usados independentemente:

### 1. PageCache (built-in, legado)
Cache local salvo em `data/emcasa_cache/`.

- **Chave:** hash MD5 do filtro + página + per_page
- **Primeira página:** sempre API real (descobre `found` e `nb_pages`)
- **Páginas subsequentes:** usam cache quando disponível
- **Limpeza:** `rm -rf data/emcasa_cache/`

### 2. PaginatedCache (externo, pipeline unificado)
Cache em `skills/cache/cache_engine.py` com TTL configurável, namespace e escrita atômica.

- **Chave:** `{namespace_sanitized}_p{page:04d}_{sha256[:12]}` — human-readable + hash
- **TTL:** configurável (default 1800s), entradas expiradas são removidas na leitura
- **Namespace:** agrupa páginas da mesma cidade+bairro (ex.: `location_state:=SP && location_city:=São Paulo`)
- **Thread-safe:** Lock  por instância, escrita atômica via `.tmp` + `rename`
- **Factory:** `create_cache(config_dict)` lê de dict — compatível com `watchdog.yaml`
- **NullCache:** no-op para desabilitar cache sem mudar código
- **26 testes** — miss/hit, TTL, invalidação por namespace, thread safety (10 threads × 20 ops)
- **clear_expired():** varredura periódica para remover entradas vencidas

```python
from skills.cache.cache_engine import PaginatedCache, create_cache

# Direto
cache = PaginatedCache(cache_dir="data/cache", default_ttl_seconds=1800)

# Via factory (lê de watchdog.yaml)
cache = create_cache({"enabled": True, "dir": "data/cache", "ttl_seconds": 1800})

# Uso
data = cache.get_or_fetch("location_state:=SP", 1, lambda: api.search_page(...))
```

---

## Performance

| Abordagem | SP (12.800 imóveis) | RJ (1.476 imóveis) |
|-----------|-------------------:|-------------------:|
| Algolia SSR (delay 1s) | ~46 min | ~5 min |
| API Foundation (delay 0.5s, 250/página) | ~2.5 min | ~20s (32 páginas) |
| **Pipeline Unificado** (2 req/s com cache, 250/página) | **~21s** (4 req reais, 44 cache hits) | **~3s** |

**Pipeline Unificado (28 regiões configuradas):**
- 787 listings coletados
- 4 requisições reais à API (44 cache hits — 91% hit rate)
- 0 erros
- 3.8s runtime total
- TokenBucket 2 req/s, burst=3
- PaginatedCache TTL=1800s
- preço/neighborhood filtering post-fetch

---

## Configuração (targets.yaml)

O EmCasa já está integrado no watchdog multi-portal em `config/targets.yaml`:

```yaml
emcasa:
  compra:
    - cidade: "São Paulo"
      uf: "SP"
      bairros: []
      tipos: ["apartamento", "casa", "cobertura", "kitnet", "studio"]
    - cidade: "Campinas"
      uf: "SP"
      tipos: ["apartamento", "casa", "cobertura"]
    - cidade: "Rio de Janeiro"
      uf: "RJ"
      tipos: ["apartamento", "casa", "cobertura", "kitnet", "studio"]
    - cidade: "Niterói"
      uf: "RJ"
      tipos: ["apartamento", "casa", "cobertura"]
```

## Testes

```bash
# Algolia Parser (8 testes — extras unitários)
python skills/emcasa/test_algolia_parser.py

# Extract Page (19 testes — pytest, SP + RJ reais)
python -m pytest skills/emcasa/test_extract_page.py -v

# API Foundation (22 unitários + 3 integração)
python -m pytest skills/emcasa/test_emcasa_api.py -v
EMCASA_INTEGRATION=1 python -m pytest skills/emcasa/test_emcasa_api.py -v -k Integration

# Cache Engine (26 testes - PaginatedCache, NullCache, factory)
python -m pytest skills/cache/test_cache_engine.py -v

# Rate Limiter (30 testes - TokenBucket sync+async, HTTP wrappers)
python -m pytest skills/rate_limiter/test_rate_limiter.py -v

# Todos os testes
python -m pytest skills/emcasa/ skills/cache/ skills/rate_limiter/ -v
```

## Descobertas da Investigação

1. **API não é SSR nem Algolia direto** — o EmCasa usa Foundation/Garagem AI como proxy de busca
2. **Algolia SSR existe como fallback** — o JSON está embutido no HTML renderizado
3. **Não requer autenticação** — ambas as abordagens são públicas
4. **Sem Cloudflare** — responde bem com delay de 0.3-1s
5. **Dados completos** — preço, área, fotos, condomínio, IPTU, amenities, coordenadas
6. **Redução de preço detectável** — `previousPrice` + `priceChangePercent` disponíveis
7. **IDs dos imóveis** são UUIDs
8. **Pipeline unificado** — PaginatedCache + TokenBucket integrados ao EmCasaClient para coleta eficiente em lote com 91% cache hit rate
9. **Facet stats** — script dedicado `scripts/facet_stats.py` que computa estatísticas agregadas de datasets coletados de qualquer fonte
