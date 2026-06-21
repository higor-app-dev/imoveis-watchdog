---
name: quinto-andar
description: Parse, normalize, validate, and deduplicate QuintoAndar property listings. Covers schema unificado Imovel, 4 parser entry points, lot validation, and 6-tier duplicate detection.
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [quintoandar, parser, normalization, validation, dedup, imoveis, imoveis-watchdog]
    related_skills: [browser-automation, turso-db]
---

# QuintoAndar — Extração, Parse e Normalização de Dados

Pipeline completa: extração → parsing → schema unificado → validação → dedup → banco.

## Visão Geral

O QuintoAndar é um SPA Next.js. Os dados dos imóveis estão disponíveis em múltiplas fontes:

| Fonte | Formato | Rápido? | Completo? |
|-------|---------|---------|-----------|
| Next.js data route (`/_next/data/{buildId}/...json`) | JSON estruturado | ✅ Sim | ✅ Sim |
| API interna (`apigw.prod.quintoandar.com.br/house-listing-search/`) | JSON | ✅ Sim | ✅ Sim |
| Browser automation (DOM/SSR) | HTML + JSON | ❌ Lento | ✅ Completo |

A pipeline de parser + normalização opera em 4 módulos:

```
dados_brutos → quintoandar_parser.py → Imovel (schema unificado)
                                         → validacao.py  → relatório
                                         → detect_duplicates.py → lista limpa
                                         → banco (Turso/SQLite)
```

## URLs que funcionam

| URL | Resultado |
|-----|-----------|
| `/comprar/imovel/sao-paulo-sp-brasil` | Imóveis à venda em SP |
| `/comprar/imovel/sao-paulo-sp-brasil/apartamento` | Apartamentos à venda |
| `/alugar/imovel/sao-paulo-sp-brasil` | Imóveis para alugar |

⚠️ Filtros de bairro/preço funcionam apenas via interação no browser (SPA client-side).

## Métodos de Extração

### 1. Next.js Data Route (recomendado — rápido, estruturado)
```
GET /_next/data/{buildId}/pt-BR/comprar/imovel/sao-paulo-sp-brasil.json
```
Retorna JSON completo com `pageProps.initialState.houses` (array de imóveis) e `search.count`.

### 2. Browser Automation (para filtros específicos)
- Navegar até a URL base
- Interagir com o formulário de busca (cidade → bairro → valor)
- Clicar em "Buscar imóveis"
- Extrair dados do DOM ou da rota Next.js

### 3. DOM Extraction (fallback)
Os listings estão no DOM como links com atributos `aria-label` contendo preço, área, quartos, endereço.

## Schema Unificado (imovel_schema.py)

Vive em `~/.hermes/imovel_schema.py` (e pode ser copiado para o repo). Dataclass Python com 22 campos.

### Criação

```python
from imovel_schema import Imovel

imovel = Imovel(
    id="qa_892820623",
    titulo="Apto 3q com vaga na Santana",
    url="https://www.quintoandar.com.br/comprar/imovel/...",
    fonte="quintoandar",
    endereco="R. Mal. Hermes da Fonseca",
    bairro="Santana",
    cidade="São Paulo",
    uf="SP",
    preco_venda=1000000.0,
    preco_aluguel=None,
    condominio=800.0,
    iptu=150.0,
    area=105.0,
    quartos=3,
    banheiros=2,
    vagas=2,
    tipo="apartamento",
    descricao="Apartamento amplo...",
    amenities=["piscina", "academia", "portaria_24h"],
    fotos=["https://img.quintoandar.com.br/foto1.jpg"],
)
```

### Serialização

```python
data = imovel.to_dict()          # → dict JSON-safe
json_str = imovel.to_json()      # → string JSON
clone = Imovel.from_dict(data)   # ← de dict

# Para notificações
print(imovel.resumo())           # → "R$ 1.000.000 — 105m² — 3q — 2ban — 2vag — Santana"
```

### Regras de validação

| Campo | Regra |
|-------|-------|
| `id` | Obrigatório |
| `fonte` | Obrigatório |
| `preco_venda` ou `preco_aluguel` | Pelo menos 1 deve existir |
| `preco_*`, `condominio`, `iptu` | > 0 se informado (None = não informado) |
| `area` | > 0 se informada |
| `quartos`, `banheiros`, `vagas` | >= 0, nunca negativos |
| `tipo` | Se informado, deve estar em TIPOS_VALIDOS |
| `uf` | Se informado, exatamente 2 caracteres |
| `url` | Se informada, começa com "http" |
| `data_coleta`, `created_at` | Devem ser ISO 8601 |

### DDL para Turso/SQLite

```python
from imovel_schema import schema_to_sqlite
ddl = schema_to_sqlite()
# CREATE TABLE imoveis_normalizado (id TEXT PK, ...)
```

## Parser QuintoAndar (quintoandar_parser.py)

Vive em `skills/quinto-andar/quintoandar_parser.py`. 4 entry points + wrapper à prova de crash.

### Entry points

```python
from quintoandar_parser import (
    from_quintoandar_listing,    # 1 listing individual
    from_quintoandar_houses,     # lista de houses
    from_quintoandar_payload,    # payload Next.js completo
    from_quintoandar_api_response, # API interna
    from_quintoandar_safe,       # wrapper que tenta tudo e nunca crasha
    process_file,                # lê JSON do disco
)
```

`from_quintoandar_safe()` tenta automaticamente: Next.js data route → API response → lista direta → `[]`.

### CLI

```bash
# Processar arquivo(s) JSON
python skills/quinto-andar/quintoandar_parser.py data/resultado.json --pretty

# Com build ID
python skills/quinto-andar/quintoandar_parser.py data/resultado.json --build-id abc123 -o data/normalizado.json
```

Cada execução mostra: quantos imóveis parseados + relatório de validação.

## Validação em Lote (validacao.py)

Vive em `skills/quinto-andar/validacao.py`.

```python
from validacao import validar_lote, relatorio_resumido

lote = validar_lote(imoveis)
print(relatorio_resumido(lote))
# 📋 Validação: 25 imóveis
#    ✅ 24 válidos   ❌ 1 inválido
```

```bash
python skills/quinto-andar/validacao.py data/normalizado.json --json
```

Exit code: 0 se todos OK, 1 se houver inválidos.

## Detecção de Duplicatas (detect_duplicates.py)

Vive em `skills/detect-duplicates/detect_duplicates.py`.

### 6 tiers de matching

| Tier | Critério | Score | Definitivo |
|------|----------|-------|------------|
| EXACT_URL | URL normalizada idêntica | 1.0 | ✅ |
| EXACT_ID | Mesmo ID na mesma fonte | 1.0 | ✅ |
| STRUCTURAL | Cidade+bairro+UF+área+quartos+preço (±5%) | até 0.85 | ❌ |
| FUZZY_TITLE | Token-set ratio no título | até 0.80 | ❌ |
| FUZZY_ADDRESS | Token-set ratio no endereço | até 0.70 | ❌ |
| FUZZY_DESCRIPTION | SequenceMatcher na descrição | até 0.60 | ❌ |

```python
from detect_duplicates import find_duplicates, dedup_list, fingerprint, summarize_matches

matches = find_duplicates(current_dicts, ref_dicts, min_score=0.60)
novos_unicos, matches = dedup_list(current_dicts, ref_dicts)
fp = fingerprint(current)  # SHA-256 dos IDs (primeiros 16 chars)
stats = summarize_matches(matches)
```

## Pipeline Completa

```python
# 1. Parse
from quintoandar_parser import process_file
imoveis = process_file("data/raw_quintoandar.json", build_id="abc123")

# 2. Validar
from validacao import validar_lote, relatorio_resumido
lote = validar_lote(imoveis)
print(relatorio_resumido(lote))

# 3. Dedup
from detect_duplicates import dedup_list
novos, matches = dedup_list([i.to_dict() for i in imoveis], dados_anteriores)

# 4. Salvar
import json
with open("data/resultado.json", "w") as f:
    json.dump(novos, f, ensure_ascii=False, indent=2)
```

## Fluxo Recomendado

1. Configurar alvos em `config/targets.yaml`
2. Extrair dados via Next.js data route ou browser automation
3. Parsear com `process_file()` ou `from_quintoandar_safe()`
4. Validar com `validar_lote()`
5. Deduplicar contra execução anterior com `dedup_list()`
6. Salvar em `data/results/` com timestamp
7. Armazenar no Turso via schema unificado

## Common Pitfalls

1. **sys.path para o schema**: O parser insere `~/.hermes` no path para importar `imovel_schema`.
2. **build_id vazio**: URLs podem não ser montadas corretamente sem build_id.
3. **condoIptu aninhado**: QuintoAndar pode retornar objeto `{condoFee, iptu}` ou campos diretos. Ambos são suportados.
4. **EXACT_ID exige fonte**: O tier só ativa se ambas as fontes forem iguais e não vazias.
5. **Validação opcional na pipeline**: Se falhar import, pipeline continua sem validação.
6. **Fotos em múltiplos formatos**: `_extract_photos()` aceita vários formatos de lista e objeto.

## Verification Checklist

- [ ] `from_quintoandar_safe()` não crasha com payload malformado
- [ ] `imovel.validate()` retorna vazio para dados válidos
- [ ] `validar_lote()` produz relatório com total/validos/invalidos
- [ ] `find_duplicates()` ordena por score descendente
- [ ] `Imovel.to_dict()` ↔ `Imovel.from_dict()` roundtrip funcional
- [ ] CLI `python quintoandar_parser.py input.json` funciona
- [ ] CLI `python validacao.py input.json` retorna exit code 0/1
