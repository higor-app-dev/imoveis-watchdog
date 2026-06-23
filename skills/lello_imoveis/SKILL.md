|---
name: lello-imoveis
description: "Skill de extração de dados da Lello Imóveis (lelloimoveis.com.br) via SSR __NEXT_DATA__. Parseia páginas de busca e detalhe. Schema unificado com 22+ campos. Suporte a paginação, filtro por tipo/negociação/bairro."
---

# Lello Imóveis — Extração de Imóveis via SSR

## Visão Geral

Extrai dados da **Lello Imóveis** (lelloimoveis.com.br) — imobiliária tradicional de SP com 60+ anos. O site usa Next.js Pages Router com React Query. Os dados são injetados inline no HTML via `__NEXT_DATA__`, sem necessidade de browser.

### Arquivos da Skill

| Arquivo | Descrição |
|---------|-----------|
| `lello_ssr.py` | Extração SSR de `__NEXT_DATA__`, parse de listagens e detalhe, mapeamento para schema unificado |
| `lello_parser.py` | Wrapper com paginação (crawl_tipo, crawl_all), save_results, integração com output_schema |
| `config.yaml` | Configuração de URLs, tipos, cache, schema |
| `test_lello_ssr.py` | 35+ testes unitários para SSR extraction |
| `test_lello_parser.py` | 13+ testes para parser e paginação |

### Fonte de Dados

| Fonte | Formato | Acessível? |
|-------|---------|-----------|
| Páginas de busca SSR (`/venda/residencial/{tipo}-tipos/{N}-pagina/`) | `__NEXT_DATA__` JSON | ✅ requests HTTP |
| Páginas de detalhe (`/imovel/{codigo}/{slug}/`) | `__NEXT_DATA__` JSON | ✅ requests HTTP |
| API Gateway (`apigateway.lelloimoveis.com.br`) | JSON | ⚠️ Alternativa |

## SSR Data Structure

O `__NEXT_DATA__` contém:

```python
# Search page (key: "paginated-realties")
props.pageProps.dehydratedState.queries[0].state.data = {
    "list": [ ... ],     # array de imóveis
    "total": 10911,      # total de resultados
    "page": 1,           # página atual
    "pages": 546,        # total de páginas
    "limit": 20,         # por página
}

# Detail page
props.pageProps.realtyDataWithMetatags.imovelDetalheVO = {
    "idImovel": 43923,
    "descricaoImovel": "...",     # descrição completa
    "fotos": [...],                # array completo de fotos
    "complementos": [...],         # amenities
    ...
}
```

## Campos Extraídos

| Campo Lello | Schema Unificado | Tipo | Exemplo |
|-------------|-----------------|------|---------|
| idImovel | codigo | str | "43923" |
| tipoImovel + subTipoImovel | tipo | str | "apartamento" |
| valorVenda | preco_venda | float | 700000.0 |
| previsaoCondominio | condominio | float | 600.0 |
| previsaoIptu | iptu | float | 52.0 |
| metragemPrincipal | area | float | 140.0 |
| quantidadeDormitorios | quartos | int | 4 |
| quantidadeBanheiros | banheiros | int | 1 |
| quantidadeVagas | vagas | int | 1 |
| quantidadeSuites | suites | int | 0 |
| andar | andar | int | 0 |
| endereco | endereco | str | "Rua Padre Benedito Maria Cardoso" |
| bairro | bairro | str | "Mooca" |
| cidade | cidade | str | "São Paulo" |
| uf | uf | str | "SP" |
| latitude/longitude | latitude/longitude | float | -23.554, -46.592 |
| fotos[].enderecoFoto | fotos | list[str] | URLs absolutas (Azure Blob + CloudFront CDN) |
| fotos[].enderecoFoto | image_urls | list[str] | Alias para fotos, URLs absolutas normalizadas |
| dataCadastro | data_publicacao | str | "2008-11-19" |
| descricaoImovel | descricao | str | "Apartamento com 140 m²..." |
| complementos[].nomeComplemento | comodidades | list[str] | ["varanda", "sacada"] |
| arquitetoDeBolso | _extra.arquiteto_de_bolso | bool | true |

## Performance

| Negociação/Tipo | Total | Páginas | 20/página |
|----------------|------:|--------:|----------:|
| Venda / Apartamentos | 10,911 | 546 | ~18 min (1s delay) |
| Venda / Casas | 5,555 | 278 | ~9 min |
| Aluguel / Apartamentos | 2,937 | 147 | ~5 min |

## Uso

```python
# Extrair página de busca SSR
from skills.lello_imoveis.lello_ssr import extract_from_ssr, build_search_url

url = build_search_url(tipo="apartamento", negociacao="venda", pagina=1)
listings, meta = extract_from_ssr(url)
print(f"{len(listings)} listings, page {meta['page']}/{meta['pages']}")
print(f"Total: {meta['total']} imóveis")

# Crawl múltiplas páginas
from skills.lello_imoveis.lello_parser import crawl_tipo, crawl_all

listings, stats = crawl_tipo(tipo="apartamento", negociacao="venda", max_pages=5)
print(f"{stats['total_listings']} imóveis em {stats['pages_fetched']} páginas")

# Crawl completo (todos os tipos)
all_listings, meta = crawl_all(max_pages=3)

# Extrair detalhe
from skills.lello_imoveis.lello_ssr import extract_detail_from_ssr

detail = extract_detail_from_ssr("https://www.lelloimoveis.com.br/imovel/43923/")
print(detail["descricao"][:200])
print(f"{len(detail['fotos'])} fotos")

# Salvar com schema unificado
from skills.lello_imoveis.lello_parser import save_to_unified_schema

path = save_to_unified_schema(listings)
```

## CLI

```bash
# Buscar 3 páginas de apartamentos à venda
python -c "from skills.lello_imoveis.lello_parser import cli_main; cli_main()" apartamento --pages 3

# Crawl todos os tipos, 2 páginas cada
python -c "from skills.lello_imoveis.lello_parser import cli_main; cli_main()" all --pages 2 --negociacao venda,aluguel

# Extrair detalhe
python -c "from skills.lello_imoveis.lello_ssr import main; main()" detail 43923
```

Detalhado (CLI do módulo `lello_ssr`):

```bash
# Precisa de PYTHONPATH
cd ~/imoveis-watchdog
PYTHONPATH=. python -c "
from skills.lello_imoveis.lello_ssr import main
main()
" search --tipo apartamento --pagina 1 --verbose
```

Ou via módulo pytest:
```bash
python -m pytest skills/lello_imoveis/ -v
```

## Integração com output_schema

```python
from skills.lello_imoveis.lello_parser import crawl_tipo, save_to_unified_schema
from skills.filter_imoveis import filter_imoveis

listings, stats = crawl_tipo(tipo="apartamento", negociacao="venda", max_pages=3)

# Salva normalizando pelo schema unificado
path = save_to_unified_schema(
    listings,
    filter_fn=filter_imoveis,
    tipo="apartamento",
    negociacao="venda",
    bairro="Mooca",
)
```

## Observações

- **Lello não usa Cloudflare** — responde bem a requests HTTP com User-Agent de browser
- **Fotos dupla origem** — `fotos[].enderecoFoto` contém URLs de dois CDNs:
  - **Azure Blob** (`upikblob.blob.core.windows.net/match-uploads/...`) — PNG originais
  - **CloudFront CDN** (`d2wln4evk52tbc.cloudfront.net/...`) — JPG via CDN (alta resolução)
  - `enderecoFotoPrincipal` é relativo — usa CloudFront CDN como base para URL absoluta
- **Preço 0 = sem preço** — `valorVenda=0` significa "apenas aluguel"
- **Campos de campanha** — `valorCampanhaVenda/Locacao=0` significa "sem campanha"
- **Rate limit recomendado**: 1s entre requisições
- **Cobertura**: principalemente SP capital + ABC + Osasco + Guarulhos
