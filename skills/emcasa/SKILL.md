---
name: emcasa
description: "Skill de extração de dados do EmCasa via API Foundation/Garagem AI (cdn.fndn.ai). Inclui cliente HTTP, paginação, cache e parser para schema normalizado."
---

# EmCasa — Extração de Imóveis via API Foundation

## Visão Geral

O EmCasa (emcasa.com) usa a plataforma **Foundation/Garagem AI** (`cdn.fndn.ai`) como backend de busca. A API é **pública** (sem autenticação) e retorna dados JSON estruturados de todos os imóveis anunciados.

**O backend do EmCasa NÃO usa Algolia diretamente no frontend.** A busca é feita via `cdn.fndn.ai` que indexa dados do Algolia internamente. A API é acessível via POST sem necessidade de SSR ou scraping HTML.

## Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `emcasa_api.py` | Cliente HTTP com paginação, cache, parser e CLI |
| `test_emcasa_api.py` | 22 testes unitários + 3 testes de integração |

## API Endpoint

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

### Response (parcial)

```json
{
  "found": 12800,
  "page": 1,
  "hits": [{ "document": { "id": "...", "askingPrice": 450000, ... } }],
  "facet_counts": [...],
  "out_of": 96784
}
```

### Paginação

- **page**: 1-indexed (primeira página = 1)
- **per_page**: default 12, máximo testado 250
- **nb_pages**: `ceil(found / per_page)`
- São Paulo (12.800 resultados) ≈ 1.067 páginas com per_page=12

### Filtros (filter_by)

Formato: `"campo:=valor && campo2:=valor2"`

| Campo | Exemplo |
|-------|---------|
| location_state | `location_state:=SP` |
| location_city | `location_city:=São Paulo` |
| location_neighborhood | `location_neighborhood:=Vila Madalena` |
| property_type | `property_type:=apartment` |

Tipos de imóvel: `apartment`, `house`, `penthouse`, `flat`, `kitnet`, `loft`, `townhouse`, `studio`

## Uso CLI

```bash
# Info de uma cidade
python emcasa_api.py --cidade "São Paulo" --apenas-info

# Todas as páginas (itera automaticamente)
python emcasa_api.py --cidade "Diadema" --todas --delay 0.3

# Faixa de páginas específica
python emcasa_api.py --cidade "São Paulo" --paginas 0-5 --pretty

# Salvar em arquivo
python emcasa_api.py --cidade "Diadema" --todas -o diadema.json --pretty

# Sem cache
python emcasa_api.py --cidade "Diadema" --todas --no-cache
```

## Uso como Biblioteca

```python
from skills.emcasa.emcasa_api import EmCasaClient, parse_hit, filter_city, PageCache

client = EmCasaClient(delay=0.5, cache=PageCache())

# Página única
result = client.search_page(
    "location_state:=SP && location_city:=São Paulo",
    page=1,
    per_page=12,
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

## Descobertas da Investigação

1. **API não é SSR nem Algolia direto** — o EmCasa usa Foundation/Garagem AI como proxy de busca
2. **Não requer autenticação** — API pública
3. **Sem Cloudflare/rate limiting agressivo** — responde bem com delay de 0.3s
4. **Dados completos** — preço, área, fotos (múltiplas URLs), condomínio, IPTU, amenities, coordenadas
5. **IDs dos imóveis** são UUIDs no formato `id` do documento
6. **Slugs de URL** são construídos como `{neighborhood}/{street}/{id}`

## Schema Normalizado

O `parse_hit()` converte cada hit da API para:

```python
{
  "id": "emcasa_{uuid}",
  "titulo": "...",
  "url": "https://www.emcasa.com/imovel/{slug}",
  "fonte": "emcasa",
  "endereco": "...",
  "bairro": "...",
  "cidade": "...",
  "uf": "SP",
  "preco_venda": 450000.0,
  "preco_aluguel": None,
  "condominio": 800.0,
  "iptu": 1500.0,
  "area": 76.0,
  "quartos": 2,
  "banheiros": 1,
  "vagas": 1,
  "tipo": "apartamento",
  "descricao": "...",
  "amenities": ["piscina", "academia"],
  "fotos": ["https://cdn.fndn.ai/images/.../detail"],
  "data_coleta": "2026-06-21T19:29:57+00:00",
  "_raw": {  # dados extras preservados
    "id": "uuid",
    "buildingName": "...",
    "floor": "12",
    "coordinates": [-23.5505, -46.6445],
    "createdAt": 1721145991,
    ...
  }
}
```

## Cache

O `PageCache` salva cada página como arquivo JSON no diretório `data/emcasa_cache/`.

- **Chave**: hash MD5 do filtro + página + per_page
- **Primeira página**: SEMPRE vai à API real (descobre `found` e `nb_pages`), depois salva no cache
- **Páginas subsequentes**: usam cache quando disponível
- **Limpeza**: `client.cache.clear()` ou `rm -rf data/emcasa_cache/`

## Rate Limiting

- Default: 0.5s entre requisições
- Configurável via `delay` no construtor ou `--delay` na CLI
- Retry: 3 tentativas com backoff exponencial (1s, 2s, 4s)
- Para São Paulo (1067 páginas): ~9 minutos com delay=0.5s

## Performance

- Primeira página: ~300ms (API real)
- Páginas subsequentes em cache: ~1ms (leitura de arquivo)
- 30 imóveis (Diadema, 3 páginas): ~2s com delay=0.3s
- 12.800 imóveis (SP, 1067 páginas): ~9 min com delay=0.5s

## Testes

```bash
# Unitários
python -m pytest skills/emcasa/test_emcasa_api.py -v

# Integração (API real)
EMCASA_INTEGRATION=1 python -m pytest skills/emcasa/test_emcasa_api.py -v -k Integration
```
