# Caixa Imóveis — Extração de Imóveis da Caixa Econômica Federal

> Extrai dados de imóveis da Caixa Econômica Federal (venda-imoveis.caixa.gov.br).
> Venda direta e leilão — proteção Radware Bot Manager + hCaptcha em todas as páginas ASP.

## ⚠️ Anti-Bot

**Radware Bot Manager + hCaptcha** protege TODAS as páginas `/sistema/`. Requisições HTTP diretas (requests, curl) são bloqueadas. A abordagem recomendada é:

1. **Primária**: Apify API (atores especializados que resolvem Radware)
2. **Secundária**: Playwright + stealth + proxies residenciais + CAPTCHA solver
3. **Complementar**: Imagens (`/fotos/`) e editais (`/editais/`) via CDN Azion — sem proteção

## Estrutura

```
skills/caixa_imoveis/
├── __init__.py                 # API pública — exports parser functions
├── caixa_imoveis_parser.py     # Parser principal (905 linhas) — Imovel schema mapping
├── config.yaml                 # Site config, endpoints, modalidades, estratégia
├── schema.json                 # Schema normalizado (40+ campos documentados)
├── SKILL.md                    # Esta documentação
└── test_caixa_imoveis_parser.py # Testes unitários (69 testes)
```

## Funcionalidades

- **Parser agnóstico**: Aceita dados de qualquer fonte (Apify, CSV, HTML extraído, manual)
- **Field mapping flexível**: FIELD_MAP suporta múltiplos nomes de campo por fonte
- **Conversão de preço BR**: `R$ 1.234.567,89` → `1234567.89`
- **URL de fotos**: Construção automática a partir do número do imóvel (`/fotos/F{digits}.jpg`)
- **Múltiplos formatos**: Aceita dict, lista, JSON string, payloads com `results`/`listings`/`hits`
- **Diferenciação Venda Direta vs Leilão**: Automática a partir da modalidade
- **Apify integration**: Função `fetch_via_apify()` com documentação e tratamento de erros
- **CLI completa**: `parse` (JSON), `photo` (build photo URL)
- **Schema compatível**: Saída unificada `Imovel` da watchdog_pipeline via `from_caixa_listing()`

## Campos Extraídos

### Core (Imovel schema)

| Campo | Descrição | Exemplo |
|-------|-----------|---------|
| `id` | `caixa_{propertyNumber}` | `caixa_155550814458-7` |
| `titulo` | Tipo + localização | `Apartamento — VILA PRUDENTE — SAO PAULO` |
| `url` | Página de detalhe | `/sistema/detalhe-imovel.asp?...` |
| `fonte` | Constante `caixa` | `caixa` |
| `endereco` | Logradouro + número | `RUA DAS LOBELIAS, N. 380 Apto. 44 BL B` |
| `bairro` | Bairro | `VILA PRUDENTE` |
| `cidade` | Cidade | `SAO PAULO` |
| `uf` | Estado | `SP` |
| `preco_venda` | Valor mínimo de venda (R$) | `310000.0` |
| `area` | Área privativa (m²) | `55.0` |
| `quartos` | Quartos | `2` |
| `vagas` | Vagas | `1` |
| `tipo` | Tipo do imóvel | `Apartamento` |
| `descricao` | Descrição textual | ... |
| `fotos` | URLs das imagens | `[.../F1555508144587.jpg]` |

### Específicos Caixa (prefixo `caixa_`)

| Campo | Descrição |
|-------|-----------|
| `caixa_valor_avaliacao` | Valor de avaliação (R$) |
| `caixa_desconto_percentual` | % de desconto |
| `caixa_modalidade` | Modalidade (Venda Online, Leilão SFI, etc.) |
| `caixa_tipo_venda` | `venda_direta` ou `leilao` |
| `caixa_primeira_data_leilao` | Data 1º leilão |
| `caixa_segunda_data_leilao` | Data 2º leilão |
| `caixa_formas_pagamento` | Formas de pagamento (array) |
| `caixa_regras_despesas` | Regras de despesas (array) |
| `caixa_ocupacao` | Ocupado / Desocupado |
| `caixa_aceita_fgts` | Aceita FGTS (bool) |
| `caixa_edital` | Número do edital |
| `caixa_matricula` | Número da matrícula |
| `caixa_leiloeiro` | Nome do leiloeiro |
| `caixa_cartorio` | Número do cartório |
| `caixa_registro_imovel` | Inscrição imobiliária (ID único Caixa) |
| `caixa_numero_item` | Número do item no leilão |
| `caixa_area_total` | Área total (m²) |
| `caixa_area_terreno` | Área do terreno (m²) |

## Modalidades

| Código | Modalidade | Tipo |
|--------|-----------|------|
| 33 | Venda Online | venda_direta |
| 34 | Venda Direta Online | venda_direta |
| 9 | Venda Direta FAR | venda_direta |
| 4 | 1º Leilão SFI | leilao |
| 5 | 2º Leilão SFI | leilao |
| 14 | Leilão SFI - Edital Único | leilao |
| 2 | Concorrência Pública | leilao |
| 21 | Licitação Aberta | leilao |

## Uso

### Python

```python
from skills.caixa_imoveis.caixa_imoveis_parser import (
    from_caixa_listing,
    from_caixa_payload,
    build_photo_url,
    fetch_via_apify,
)

# Parsear um imóvel individual (de Apify, CSV, HTML, etc.)
imovel = from_caixa_listing(sp_apto_dict)
print(imovel["preco_venda"], imovel["caixa_modalidade"])

# Parsear payload (lista / dict com results/listings/hits / JSON string)
imoveis = from_caixa_payload(api_response)

# Construir URL de foto
url = build_photo_url("155550814458-7")
# -> https://venda-imoveis.caixa.gov.br/fotos/F1555508144587.jpg

# Extrair via Apify (requer apify-client + APIFY_TOKEN)
# imoveis = fetch_via_apify(apify_token="apify_api_...")
```

### CLI

```bash
# Parsear JSON de listagens Caixa
python -m skills.caixa_imoveis.caixa_imoveis_parser parse data/raw/caixa.json --output data/results/caixa.json

# Construir URL de foto
python -m skills.caixa_imoveis.caixa_imoveis_parser photo 155550814458-7
```

## Apify Actors

| Actor | Preço | Uso |
|-------|-------|-----|
| `pizani/caixa-imoveis-leiloes-api` | $10/mês | Busca por estado/cidade/modalidade |
| `leadercorp/caixa-leiloes-scraper` | $5/1000 | Página de detalhe completa |
| `brasil-scrapers/caixa-leiloes-api` | $25/mês | Detalhamento completo com imagens |

## Testes

```bash
cd /home/higor/imoveis-watchdog

# Todos os 69 testes
python -m pytest skills/caixa_imoveis/test_caixa_imoveis_parser.py -v

# Cobertura: parsing, payload, preços, fotos, field map,
# URLs, timestamps, deduplicação, Apify mockado
```

## Dependências

```bash
pip install requests>=2.31.0
# Opcional (Apify):
pip install apify-client
```
