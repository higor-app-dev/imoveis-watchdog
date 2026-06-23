---
name: biasi-leiloes
description: Extração de leilões de imóveis do Biasi Leilões (biasileiloes.com.br) via AJAX SSR + detail scraping — sem Cloudflare, ~445 imóveis ativos
version: 1.1.0
platforms: [linux, macos]
environments: [imoveis-watchdog]
metadata:
  hermes:
    tags: [imoveis-watchdog, extraction, leilao, biasileiloes, ajax-ssr]
    related_skills: [output_schema, imovel_schema, portal_registry, mega_leiloes, sodre_santoro]
---

# Biasi Leilões — Extração de Leilões de Imóveis

> Extrai dados do Biasi Leilões (biasileiloes.com.br) via AJAX partial HTML + SSR detail pages.
> Sem Cloudflare, sem browser — requisições HTTP diretas com `requests` + `BeautifulSoup`.

## Estrutura

```
skills/biasi_leiloes/
├── __init__.py                # API pública — exports parser + extractor
├── biasi_leiloes_parser.py    # Parser principal — Imovel schema mapping
├── extractor.py               # Extrator SSR: AJAX listing + detail page scraping
├── config.yaml                # URLs, headers, rotas, paginação, field mapping
├── schema.json                # Schema normalizado (campos core + extra de leilão)
├── SKILL.md                   # Esta documentação
├── test_biasi_extractor.py    # Testes do extrator (17 testes)
├── test_biasi_leiloes_parser.py # Testes do parser (79 testes)
```

Testes adicionais em `tests/test_biasi_leiloes.py` (68 testes — extractor mockado + parsing).

**Total: 164 testes, todos passando.**

## Estratégia de Extração

### Primária: AJAX Partial JSON/HTML

O site Biasi Leilões é ASP.NET MVC 5 com GoCache CDN (sem Cloudflare). Os listing cards são carregados via AJAX:

| Parâmetro | Valor |
|-----------|-------|
| Endpoint | `GET /Sale/LotListSearch` |
| Params | `?start=0&limit=48&categoria=1&slug=santander` |
| Método | AJAX HTML partial (retorna HTML com cards) |
| Paginação | Offset-based via `start`/`limit` |
| ~Total | ~445 imóveis (130+ SP, 48 Santander em 1 página) |

**Slugs de parceiros disponíveis:**
- `santander` — Leilões Santander
- `itau` — Leilões Itaú
- `rodobenssa` — Leilões Rodobens
- `""` (vazio) — Todos os parceiros

### Secundária: SSR Detail (enriquecimento)

Cada listing card tem ID numérico. A página de detalhe `/sale/detail?id={NUM}` retorna HTML SSR completo com:

- Endereço completo, bairro, cidade, UF, CEP
- Área, quartos, banheiros, vagas
- Múltiplas fotos via CDN (5+ por imóvel)
- Edital PDF e matrícula
- Nome do leilão, leiloeiro, comissão
- Ocupação do imóvel
- Descrição completa

### CDN de Imagens

```
Base: https://cdn-biasi.blueintra.com/images/lot/{XX}/{YY}/{size}/{imageId}.jpg
Sizes: thumb=250 (35KB), medium=500 (112KB), large=1000 (317KB) — HD
Partition: XX = primeiros 2 chars do imageId, YY = chars 3-4 (zero-padded se < 4 chars)
Example: imageId=1564035 → XX=15, YY=64 → /images/lot/15/64/1000/1564035.jpg
```

**`_generate_all_resolutions(foto_url)`** — gera dict com `{original, large, medium, thumb}` para uma foto. Aceita IDs numéricos ou URLs absolutas do CDN. Retorna None se não parseável.

**Campo `image_urls`** na saída do parser — array de `[{original, large, medium, thumb}, ...]`, uma entrada por foto. Complementa o campo `fotos` (lista plana de URLs).

## Funcionalidades

- **Extração via AJAX SSR**: sem browser, `requests` + `BeautifulSoup`
- **3 parceiros**: Santander, Itaú, Rodobens
- **Paginação offset-based**: 48 itens por página, safety cap 50 páginas / 1000 itens
- **Enriquecimento**: detail scraping opcional para dados completos
- **Conversão de preço BR**: `R$ 329.040,70` → `329040.7`
- **Parser de endereço**: 6 formatos brasileiros + edge cases
- **Inferência de tipo**: 13 tipos de imóvel (apartamento, casa, terreno, kitnet, etc.)
- **Multi-fotos**: 5+ fotos por imóvel via CDN
- **Schema compatível**: Saída unificada `Imovel` da watchdog_pipeline via `from_biasi_listing()`
- **CLI completa**: `run`, `parse`, `parse-listing`, `debug-photo`

## Campos Extraídos

### Core (do schema Imovel)

| Campo | Fonte Primária | Descrição |
|-------|----------------|-----------|
| `id` | Card `data-id` | ID numérico do anúncio |
| `titulo` | Card title | Título do imóvel |
| `url` | Construído | `/sale/detail?id={id}` |
| `fonte` | Constante | `biasileiloes` |
| `preco_venda` | Detail / card | Valor 1ª praça (avaliação) |
| `preco_segundo_leilao` | Detail / card | Valor 2ª praça |
| `endereco` | Detail | Logradouro + número |
| `bairro` | Detail | Bairro |
| `cidade` | Detail | Cidade |
| `uf` | Detail | Estado (maiúsculo) |
| `tipo` | Detail / inferido | apartamento, casa, terreno, etc. |
| `status` | Card badge | Liberado para Lance, Não Iniciado, Vendido |
| `disponivel` | Status inferido | True se ativo |
| `area` | Detail | m² |
| `quartos` | Detail | Número de quartos |
| `banheiros` | Detail | Número de banheiros |
| `vagas` | Detail | Vagas de garagem |
| `descricao` | Detail | Descrição textual |
|| `fotos` | CDN | Array de URLs das imagens (1000px) |
|| `image_urls` | CDN | Array estruturado: `[{original, large, medium, thumb}, ...]` |

### Extra (específicos de leilão — preservados em `_extra`)

| Campo | Descrição |
|-------|-----------|
| `nome_leilao` | Nome do evento de leilão |
| `numero_lote` | Número do lote |
| `data_primeiro_leilao` | Data 1ª praça (ISO) |
| `data_segundo_leilao` | Data 2ª praça (ISO) |
| `edital_url` | URL do PDF do edital |
| `matricula` | Número da matrícula |
| `cadastro_municipal` | SQL / inscrição municipal |
| `ocupacao` | Ocupado / desocupado |
| `whatsapp` | Contato WhatsApp |

## Uso

### Python

```python
from skills.biasi_leiloes import extract_listings, extract_detail, from_biasi_listing

# Extrair listagens Santander (dados dos cards)
listings = extract_listings(source='santander', pages=1)
print(f"Extraídos {len(listings)} imóveis")

# Parsear para schema unificado
from skills.biasi_leiloes import from_biasi_payload
imoveis = from_biasi_payload(listings)

# Extrair detalhe de um imóvel específico
detalhe = extract_detail(listing_id=57352)
imovel = from_biasi_listing(detalhe)
print(imovel['endereco'], imovel['cidade'], imovel['preco_venda'])

# Extrair tudo (lista + detalhes)
from skills.biasi_leiloes import extract_all
todos = extract_all(source='santander', pages=1, fetch_detail=True)
```

### Extrair de todos os parceiros

```python
from skills.biasi_leiloes import extract_imoveis

# Extrai de Santander, Itaú e Rodobens
todos = extract_imoveis(pages_per_source=1, fetch_detail=False)
for fonte, imoveis in todos.items():
    print(f"{fonte}: {len(imoveis)} imóveis")
```

### CLI

```bash
# Parsear um arquivo JSON bruto para schema unificado
python -m skills.biasi_leiloes.biasi_leiloes_parser parse data/raw/biasi.json --output data/results/biasi.json

# Parsear um único listing
echo '{"id": 57352, "titulo": "...", "valor_primeira_praca": "R$ 329.040,70"}' | \
  python -m skills.biasi_leiloes.biasi_leiloes_parser parse-listing

# Debug de URL de foto CDN
python -m skills.biasi_leiloes.biasi_leiloes_parser debug-photo 1564035
```

## Paginação

- **48 itens por página** via AJAX (`start`/`limit` offset)
- Safety cap: 50 páginas / 1000 itens
- Delay de 300ms entre requisições
- Parada antecipada quando página retorna vazia

## Anti-bot

- **AJAX search**: sem proteção — GoCache CDN sem Cloudflare
- **Detail pages**: mesma CDN, sem desafio
- Rate limiting: delay de 300ms entre chamadas

## Dependências

```bash
pip install requests>=2.31.0 beautifulsoup4>=4.12.0
```

## Testes

```bash
# Todos os 164 testes
cd /home/higor/imoveis-watchdog

# Extractor específico (17 testes)
python -m pytest skills/biasi_leiloes/test_biasi_extractor.py -v

# Parser específico (79 testes)
python -m pytest skills/biasi_leiloes/test_biasi_leiloes_parser.py -v

# Testes integrados mockados (68 testes)
python -m pytest tests/test_biasi_leiloes.py -v

# Tudo de uma vez
python -m pytest skills/biasi_leiloes/ tests/test_biasi_leiloes.py -v
```

## Schema

Schema completo em `schema.json` — 37+ campos documentados com:
- Mapeamento AJAX/SSR → Imovel → campo de negócio
- Regras de transformação (`_parse_money_br`, CDN image URL, parser de endereço)
- Validação condicional (status → disponivel)
- `_extra` preservando campos específicos de leilão
