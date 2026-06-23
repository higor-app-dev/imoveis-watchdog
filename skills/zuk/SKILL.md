---
name: zuk
description: Extração de leilões de imóveis do Portal Zuk (portalzuk.com.br) — Laravel server-rendered, dados inline JS, Cloudflare
version: 1.0.0
platforms: [linux, macos]
environments: [imoveis-watchdog]
metadata:
  hermes:
    tags: [imoveis-watchdog, extraction, leilao, zuk, portalzuk, scraper]
    related_skills: [output_schema, imovel_schema, portal_registry, loft, lello_imoveis]
---

# Zuk — Extração de Leilões de Imóveis

> Extrai dados do Portal Zuk (portalzuk.com.br), antigo Zukerman.
> Laravel server-rendered, Cloudflare, dados inline JS.

## Estrutura

```
skills/zuk/
├── __init__.py          # API pública
├── zuk_parser.py        # Módulo principal (extração + parsing + schema)
├── config.yaml          # URLs, headers, constantes
├── requirements.txt     # Dependências
├── SKILL.md             # Esta documentação
└── test_zuk_parser.py   # Testes unitários
```

## Funcionalidades

- **Extração combinada**: HTML listing + inline `properties` JSON
- **Correlação por lote ID** (`ilo`) entre HTML cards e JSON
- **Páginas de listagem**: 30 imóveis/página, paginação via `?page=N`
- **Schema unificado Imovel**: saída compatível com a pipeline watchdog
- **CLI**: `python -m skills.zuk.zuk_parser {extract|crawl|parse}`

## Campos Extraídos

| Campo | Fonte | Descrição |
|-------|-------|-----------|
| `titulo` | HTML card | Tipo do imóvel (Terreno, Casa, etc.) |
| `endereco` | HTML card | Cidade/UF - Bairro - Rua |
| `preco_1a_praca` | HTML card | Valor 1ª praça (riscado se passou) |
| `preco_2a_praca` | HTML card | Valor atual do leilão |
| `data_1a_praca` | HTML card | Data 1ª praça |
| `data_2a_praca` | HTML card | Data 2ª praça |
| `valor_avaliacao` | Inline JSON (`lv`) | Valor de avaliação |
| `latitude/longitude` | Inline JSON (`la`/`lo`) | Coordenadas |
| `areas` | Inline JSON | Útil, privativa, construída, total |
| `tipo` | Inferido | residencial, comercial, terreno, etc. |
| `image_urls` | HTML card | Thumbnail URL |
| `url` | HTML card | Link para página de detalhe |
| `percentual_desconto` | HTML card | % abaixo da avaliação |

## Uso

```python
from skills.zuk import extract_listing_page, from_zuk_payload

# Single page
listings = extract_listing_page()
imoveis = from_zuk_payload(listings)

# Multi-page crawl
all_listings, meta = crawl_listing(pages=10, rate_limit=1.5)
imoveis = from_zuk_payload(all_listings)
print(f"Extraídos {len(imoveis)} imóveis")
```

### CLI

```bash
# Extrair página única
python -m skills.zuk.zuk_parser extract --output data/results/zuk_page1.json

# Crawl múltiplas páginas
python -m skills.zuk.zuk_parser crawl --pages 5 --output data/results/zuk_5pages.json

# Parsear HTML local salvo
python -m skills.zuk.zuk_parser parse tests/fixtures/zuk_listing.html
```

## Anti-bot (Cloudflare)

O Portal Zuk tem proteção Cloudflare. Medidas:
- **User-Agent de navegador real** (já configurado por padrão)
- Se Cloudflare challenge aparecer, usar browser tool (Playwright)
- Endpoints POST requerem CSRF token (`_token`) extraído do HTML

## Estratégia de Extração

Preferir **Estratégia Combinada**:
1. GET na página de listagem com headers de navegador
2. Parsear cards HTML para dados visuais (título, preços, datas)
3. Extrair `properties` array do JS inline para dados estruturados
4. Correlacionar por `ilo` (lote ID)
5. Paginar via `?page=N`

Para dados enriquecidos (descrição, matrícula, galeria):
- Fazer GET na página de detalhe (`/imovel/{uf}/{cidade}/.../{leilaoId}-{loteId}`)
- Parsear HTML com seletores do detalhe

## Paginação

- Botão "Carregar mais" com AJAX incremental
- Parâmetro `?page=N` nas URLs
- 30 resultados por página
- ~1008 imóveis → ~34 páginas

## Dependências

```bash
pip install requests beautifulsoup4 pyyaml
```

## Testes

```bash
cd /home/higor/imoveis-watchdog
python -m pytest skills/zuk/test_zuk_parser.py -v
```
