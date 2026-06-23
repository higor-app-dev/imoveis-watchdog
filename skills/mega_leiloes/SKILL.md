---
name: mega-leiloes
description: Extração de leilões de imóveis do Mega Leilões (megaleiloes.com.br) via Algolia API pública — sem necessidade de browser, ~122K registros
version: 1.0.0
platforms: [linux, macos]
environments: [imoveis-watchdog]
metadata:
  hermes:
    tags: [imoveis-watchdog, extraction, leilao, megaleiloes, algolia]
    related_skills: [output_schema, imovel_schema, portal_registry, zuk, loft, lello_imoveis]
---

# Mega Leilões — Extração de Leilões de Imóveis

> Extrai dados do Mega Leilões (megaleiloes.com.br) via API pública do Algolia.
> Sem Cloudflare, sem browser — requisições HTTP diretas.

## Estrutura

```
skills/mega_leiloes/
├── __init__.py                # API pública
├── mega_leiloes_parser.py     # Módulo principal (949 linhas)
├── config.yaml                # URLs, headers, constantes
├── requirements.txt           # Dependências
├── schema.json                # Schema normalizado (58 campos documentados)
├── SKILL.md                   # Esta documentação
└── test_mega_leiloes_parser.py # Testes unitários (793 linhas)
```

## Estratégia de Extração

### Primária: API Algolia (recomendada)

Mega Leilões usa **Algolia** como mecanismo de busca com chave **pública search-only**:

| Parâmetro | Valor |
|-----------|-------|
| Application ID | `1A8O5M7X6Q` |
| API Key | `055311365c6f5cdd0d1bff3e0acba7ae` |
| Index | `Items` |
| Endpoint | `POST /1/indexes/Items/query` |
| ~Total | ~122K registros |

**Vantagens:**
- ✅ Sem Cloudflare — requisições diretas via `requests`
- ✅ Sem browser — leve, rápido
- ✅ Até 1000 hits por página
- ✅ Dados estruturados (JSON)
- ✅ Campos: preço, endereço, datas, processo, fotos

**Limitações:**
- ❌ Apenas 1 foto por lote (mais requer SSR)
- ❌ Sem amenities, área, quartos (requer SSR)
- ❌ Sem incremento, comissão, edital (requer SSR)

### Secundária: SSR Detail (enriquecimento)

10 campos adicionais disponíveis apenas na página de detalhe HTML (Cloudflare-protegida). Requer browser ou requests com desafio Cloudflare.

**Múltiplas imagens:** A página SSR de detalhe pode conter **2-5+ imagens** por lote,
diferentemente da Algolia que retorna apenas 1. As imagens extras estão server-renderizadas
no HTML como tags `<img>` dentro de um Owl Carousel. URLs seguem o mesmo padrão CDN.
O `image_path` do Algolia **NÃO** corresponde necessariamente à primeira imagem — é um
hash md5 arbitrário entre as da galeria.

## Image CDN Pattern

All images are served from `cdn1.megaleiloes.com.br` with the pattern:

```
https://cdn1.megaleiloes.com.br/batches/{batch_id}/{md5_hash}_{width}x{height}.jpg
```

### Available Resolutions

| Size | Width × Height | Usage | Source |
|------|---------------|-------|--------|
| Thumbnail | 320×240 | Search results, Algolia `image_path` | Algolia API |
| Medium | 670×380 | Detail page carousel (OwlCarousel) | SSR HTML |
| Full | 1024×768 | Lightbox / popup (MagnificPopup) | SSR HTML (`a` href) |

### Multiple Images

A listing may have **2–5+ unique images**, each with its own md5 hash. The Algolia
API exposes only **one** of these via `image_path`. To obtain all images, scrape
the SSR detail page (`<img>` tags inside `.owl-carousel`).

The `image_path` from Algolia is an arbitrary hash — **not necessarily** the first
image displayed in the gallery.

### Related Documents

PDF documents (edital, matrícula) also live under the same CDN path:

```
https://cdn1.megaleiloes.com.br/batches/{batch_id}/megaleiloes_edital_{refcode}_{datecode}.pdf
https://cdn1.megaleiloes.com.br/batches/{batch_id}/megaleiloes_matricula_{refcode}_{datecode}.pdf
```

## Funcionalidades

- **Extração via Algolia**: API pública, sem browser
- **Filtragem client-side**: Categoria "Imóveis" + status ativos (upcoming/open)
- **Conversão de preço BR**: `R$ 450.000,00` → `450000.00`
- **Imagens em 3 resoluções**: Thumbnail 320×240 → Médio 670×380 → Full 1024×768
- **Timestamps ISO**: Unix seconds → ISO 8601 UTC
- **Deduplicação**: Por `objectID` do Algolia
- **CLI completa**: `fetch`, `query` para debug
- **Schema compatível**: Saída unificada Imovel da watchdog_pipeline

## Campos Extraídos

| Campo | Fonte | Descrição |
|-------|-------|-----------|
| `id` | Algolia | `megaleiloes_{objectID}` |
| `titulo` | `headline` | Título do leilão |
| `preco_venda` | `first_instance_value` | Valor 1ª praça (avaliação) |
| `second_instance_value` | Algolia | Valor 2ª praça |
| `endereco` | `address` | Endereço completo |
| `bairro` | `sublocality` | Bairro |
| `cidade` | `city` | Cidade |
| `uf` | `state` | Estado (maiúsculo) |
| `tipo` | `subcategory` → mapa | apartamento, casa, terreno, etc. |
| `status` | `batch_status` → label | upcoming, ativo, suspenso |
| `disponivel` | batch_status | True se ativo |
| `data_leilao_inicio` | Unix ts → ISO | Início 1ª praça |
| `data_leilao_fim` | Unix ts → ISO | Fim 1ª praça |
| `data_segunda_praca` | Unix ts → ISO | Fim 2ª praça |
| `tipo_leilao` | `type` | Judicial / Extrajudicial |
| `process_number` | Algolia | Número do processo |
| `forum` | Algolia | Foro / Vara |
| `author` | Algolia | Autor (exequente) |
| `respondent` | Algolia | Réu (executado) |
| `fotos` | `image_path` → méd 670×380 | URLs das imagens (1 via Algolia, + via SSR) |
| `descricao` | Construída | Metadados concatenados |
| `batch_id` | Algolia | ID do lote |
| `batch_status` | Algolia | 0/1/3 |

### SSR-only (enriquecimento futuro)

`incremento`, `comissao_leiloeiro`, `leiloeiro`, `edital_url`, `matricula_url`,
`visitas`, `habilitados`, `qtd_lances`, `desconto_pct`, `area`, `quartos`, `banheiros`, `vagas`

## Uso

### Python

```python
from skills.mega_leiloes import fetch_active_listings, from_mega_listing

# Buscar todos os leilões ativos
imoveis = fetch_active_listings(max_pages=5)
print(f"Extraídos {len(imoveis)} imóveis")

# Parsear hit individual
imovel = from_mega_listing(algolia_hit)
```

### CLI

```bash
# Fetch ativos (teste — 5 páginas)
python -m skills.mega_leiloes.mega_leiloes_parser fetch --max-pages 5

# Fetch e salvar em arquivo
python -m skills.mega_leiloes.mega_leiloes_parser fetch --max-pages 5 --output data/results/mega_5pages.json

# Query única de debug
python -m skills.mega_leiloes.mega_leiloes_parser query --page 0 --hits 5
```

## Paginação

- **1000 hits por página** via Algolia (`hitsPerPage=1000`)
- **~122 páginas** para o total de ~122K registros
- Filtragem **client-side**: `category="Imóveis"` + `batch_status in {0,1}`
- Delay de 300ms entre páginas

## Anti-bot

- **Algolia API**: sem proteção — chave pública search-only
- **SSR detail**: Cloudflare ativo — requer browser para enriquecimento

## Dependências

```bash
pip install requests>=2.31.0
```

## Testes

```bash
# Todos os testes
cd /home/higor/imoveis-watchdog
python -m pytest skills/mega_leiloes/test_mega_leiloes_parser.py -v

# Cobertura: parsing, payload, preços, imagens, timestamps,
#             paginação mockada, deduplicação, filtros, descrição
```

## Schema

Schema completo em `schema.json` — 58 campos documentados com:
- Mapeamento Algolia → Imovel → campo de negócio
- Regras de transformação (`_parse_br_price`, timestamps, image URL)
- Validação condicional (batch_status → status/disponivel)
- `FieldSourceMapping` em `defs` para auditoria
