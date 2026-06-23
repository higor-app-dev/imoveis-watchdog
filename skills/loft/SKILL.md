---
name: loft-parser
description: Parse, normalize, and validate Loft property listings to the unified Imovel schema. Supports individual listing pages (via web_extract), Next.js payloads, and API responses.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [loft, parser, normalization, validation, imoveis, imoveis-watchdog]
    related_skills: [browser-automation, quinto-andar, turso-db]
---

# Loft — Parser e Normalização de Dados

Pipeline completa: extração → parsing → schema unificado → validação → dedup → banco.

## Visão Geral

A Loft (loft.com.br) é um portal Next.js (Pages Router) de imóveis. Diferente do QuintoAndar, a Loft é protegida por CloudFront (AWS), bloqueando tentativas de scraping direto via curl ou navegadores headless.

### Fontes de Dados

| Fonte | Formato | Acessível? | Recomendado? |
|-------|---------|-----------|-------------|
| Página de detalhe (`/imovel/{slug}/{id}`) | HTML renderizado + Meta tags | ✅ Sim (web_extract / browser) | ✅ Parsing via web_extract |
| Página de busca (`/venda/apartamentos/sp/sao-paulo`) | Next.js SSR | ❌ CloudFront 403 | Usar Apify API |
| Apify Scraper (`gio21/loft-scraper`) | JSON | ✅ API paga | ✅ Para automatização |
| `__NEXT_DATA__` inline | JSON | ❌ CloudFront | Alternativa se acessível |

## Schema Unificado

Usa o mesmo schema `Imovel` do QuintoAndar (em `~/.hermes/imovel_schema.py`).

```python
from imovel_schema import Imovel

imovel = Imovel(
    id="ino0ntno",
    titulo="Cobertura Duplex 4 quartos, Jardim Guedala",
    url="https://loft.com.br/imovel/apartamento-.../ino0ntno",
    fonte="loft",
    endereco="Rua Albertina de Oliveira Godinho",
    bairro="Jardim Guedala",
    cidade="São Paulo",
    uf="SP",
    preco_venda=35950000.0,
    area=1200.0,
    quartos=4,
    banheiros=8,
    vagas=10,
    tipo="cobertura",
    condominio=25400.0,
    iptu=17000.0,
    amenities=["piscina", "sauna", "churrasqueira"],
    fotos=["https://img.loft.com.br/foto1.jpg"],
)
```

## Parser Loft (loft_parser.py)

Vive em `skills/loft/loft_parser.py`. Importa `sys.path.insert(0, ~/.hermes)` para achar o schema.

### Módulos de conversão

```python
# 1. De um listing individual (dict bruto)
from loft_parser import from_loft_listing
imovel = from_loft_listing(listing_dict)

# 2. De uma lista de listings
from loft_parser import from_loft_listings
imoveis = from_loft_listings(listings_list)

# 3. Do payload de busca (Next.js ou API)
from loft_parser import from_loft_payload
imoveis = from_loft_payload(payload_dict)
# Navega: pageProps → listings / data → listings / listings / results

# 4. Wrapper à prova de crash (tenta tudo)
from loft_parser import from_loft_safe
imoveis = from_loft_safe(payload_unk)
# Tenta: Next.js → API → lista direta → dict único → []
```

### Parsing de web_extract (listing detail)

```python
from loft_parser import _parse_web_extract_text, from_loft_listing

# Extrai dados da Loft via web_extract
text = response["results"][0]["content"]
parsed = _parse_web_extract_text(text)
imovel = from_loft_listing(parsed)
```

### Processamento de arquivos

```python
from loft_parser import process_file, process_web_extract_file

# Processa arquivo JSON (API output)
imoveis = process_file("data/loft_results.json")

# Processa arquivo de texto (web_extract output)
imoveis = process_web_extract_file("data/loft_listing.txt")
```

### CLI

```bash
# Processar arquivo JSON com dados da Loft
python skills/loft/loft_parser.py data/loft_results.json --pretty

# Processar texto do web_extract
python skills/loft/loft_parser.py data/loft_listing.txt --pretty

# Salvar saída
python skills/loft/loft_parser.py data/loft_results.json -o data/normalizado.json
```

## Mapeamento de Campos

| Campo Loft (API) | Campo Schema | Helper |
|-------------------|-------------|--------|
| `id` | `id` | `_extract_id_from_url()` se ausente |
| `salePrice` / `price` | `preco_venda` | `_to_float()` |
| `rentPrice` / `rentalPrice` | `preco_aluguel` | `_to_float()` |
| `condominiumFee` / `condoFee` | `condominio` | `_to_float()` |
| `propertyTax` / `iptu` | `iptu` | `_to_float()` |
| `area` / `usableArea` | `area` | `_to_float()` |
| `bedrooms` / `dormitorios` | `quartos` | `_to_int()` |
| `bathrooms` / `suites` | `banheiros` | `_to_int()` |
| `parkingSpots` / `garageSpots` | `vagas` | `_to_int()` |
| `type` / `propertyType` | `tipo` | `_map_tipo()` |
| `address.street` / `street` | `endereco` | |
| `address.neighborhood` / `neighborhood` | `bairro` | |
| `address.city` / `city` | `cidade` | |
| `address.stateCode` / `stateCode` | `uf` | Normaliza 2 chars |
| `description` | `descricao` | |
| `amenities` / `features` | `amenities` | `_normalize_amenity()` |
| `photos` / `images` | `fotos` | `_extract_photos_loft()` |
| `disponivel` | `disponivel` | Aceita bool ou string |
| `publishDate` / `createdAt` | `data_publicacao` | |

### Mapeamento de tipos

14 variantes mapeadas (TIPO_MAP): Apartamento, Casa, Kitnet, Cobertura, Cobertura Duplex, Studio, Flat, Loft, Sobrado, Terreno, Casa em Condomínio, Comercial, Sala Comercial.

### Helpers de acesso seguro

- `_safe_get(obj, *keys, default=None)` — navega dicts aninhados sem crash
- `_safe_navigate(payload, *paths, default=None)` — tenta múltiplos caminhos
- `_to_float(val)` / `_to_int(val)` — conversão segura com suporte a formato BR (R$ 1.200,50 → 1200.5)
- `_as_str(val, default="")` — type guard
- `_normalize_amenity(name)` — snake_case sem acentos (unicodedata NFKD)

## Extração via web_extract

Páginas individuais da Loft (`/imovel/{slug}/{id}`) são acessíveis via `web_extract`. O conteúdo é convertido automaticamente para markdown estruturado com tabelas.

```python
from hermes_tools import web_extract

resp = web_extract(urls=["https://loft.com.br/imovel/apartamento-.../id123"])
text = resp["results"][0]["content"]

from loft_parser import _parse_web_extract_text, from_loft_listing
parsed = _parse_web_extract_text(text)
imovel = from_loft_listing(parsed)
```

O parser de web_extract extrai:
- Preço (de `**R$ X.XXX.XXX**` ou tabela markdown)
- Área (padrão `X m²`)
- Cômodos (quartos, banheiros, vagas da tabela)
- Condomínio e IPTU (da tabela)
- Endereço completo (bairro, cidade, UF do título ou seção de localização)
- Tipo (inferido do título e corpo do texto)
- Amenities (de listas com hífen e seções de amenidades)
- Descrição (seção "Descrição" no markdown)

### Tratamento de listing indisponível

Quando o imóvel não está mais disponível, o Loft retorna "Este imóvel está indisponível". O parser detecta isso via presença de "indisponível" no texto e marca `disponivel=False`.

## Extração via Apify API

Para acesso programático em escala, o Apify oferece o ator `gio21/loft-scraper`:

```python
import requests

API_TOKEN = os.environ["APIFY_API_TOKEN"]
response = requests.post(
    f"https://api.apify.com/v2/acts/gio21~loft-scraper/run-sync-get-dataset-items",
    json={"searchTerm": "Vila Mariana", "city": "sao-paulo", "transaction": "sale", "maxItems": 50},
    params={"token": API_TOKEN},
)
listings = response.json()

from loft_parser import from_loft_listings
imoveis = from_loft_listings(listings)
```

## Testes

```bash
cd ~/imoveis-watchdog
python skills/loft/test_loft_parser.py
```

22 testes que cobrem:
- Listing completo com todos os campos
- Listing médio e mínimo (edge cases)
- Listing indisponível
- Payload de busca Next.js e API
- Parsing de texto do web_extract (2 amostras)
- Extração de ID da URL
- Extração de cidade/UF
- Normalização de amenities
- Fotos em múltiplos formatos
- Validação do schema unificado
- Roundtrip JSON (to_dict → from_dict)

## Pipeline de Watchdog

Para integrar no watchdog, adicione no `watchdog_pipeline.py`:

```python
try:
    sys.path.insert(0, str(Path("skills/loft").resolve()))
    from loft_parser import from_loft_listings, from_loft_safe
    from validacao import validar_lote, relatorio_resumido
    imoveis = from_loft_listings(listings)
    lote = validar_lote(imoveis)
    logger.info(relatorio_resumido(lote))
except ImportError:
    logger.warning("Loft parser não disponível — pulando")
```

## Dependências

- Python 3.11+
- `~/.hermes/imovel_schema.py` (schema unificado)
- Opcional: `requests` (Apify API), `playwright` (extração avançada)

## Common Pitfalls

1. **CloudFront bloqueia busca**: A página de busca (`/venda/apartamentos/...`) retorna 403. Use a API Apify ou extraia listings individuais via web_extract.

2. **"loft" como tipo**: O nome do portal "Loft" aparece no título das páginas (ex: "...| Loft"). O parser ignora "loft" no título se "apartamento" também estiver presente.

3. **Preço em formato brasileiro**: `R$ 35.950.000` → `35950000.0`. O `_to_float()` trata os formatos BR.

4. **IDs sem prefixo**: IDs extraídos do campo `id` da Loft são usados como estão (ex: `ino0ntno`). IDs extraídos da URL recebem prefixo `loft_` (ex: `loft_ino0ntno`).

5. **Banheiros vs Suítes**: A Loft pode retornar `bathrooms` ou `suites`. O parser tenta ambos.

## Verification Checklist

- [ ] `from_loft_listing()` retorna Imovel (não crasha)
- [ ] `from_loft_safe()` aceita dict, lista, None sem crash
- [ ] `imovel.validate()` retorna lista vazia para dados válidos
- [ ] `_parse_web_extract_text()` extrai preço, área, cômodos
- [ ] `from_loft_payload()` navega pageProps → listings
- [ ] URL com slug longo é preservada como URL do anúncio
- [ ] CLI `python loft_parser.py input.json` funciona
- [ ] `_extract_id_from_url()` extrai ID de URL curta e longa
- [ ] Tipos "Cobertura Duplex" → `cobertura`
- [ ] Amenities normalizadas para snake_case sem acentos
