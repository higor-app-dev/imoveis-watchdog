"""
Caixa Imóveis — Extração de imóveis da Caixa Econômica Federal (venda-imoveis.caixa.gov.br).

## ⚠️ Anti-Bot Warning

Este portal tem proteção **Radware Bot Manager + hCaptcha**. Requisições HTTP diretas
(requests, httpx, curl) são bloqueadas para todas as páginas de busca e detalhe.
As únicas URLs sem proteção são as imagens em `/fotos/`.

**Abordagem recomendada**: Integração com Apify (actors especializados) ou
Playwright + stealth + proxies residenciais.

## Uso básico

```python
from skills.caixa_imoveis.caixa_imoveis_parser import (
    from_caixa_listing,
    from_caixa_payload,
    build_photo_url,
    fetch_via_apify,
)

# Parsear uma listagem individual (dict de qualquer fonte)
imovel = from_caixa_listing(raw_dict)

# Parsear payload de busca (lista de dicts, ou dict com results/listings/hits)
imoveis = from_caixa_payload(api_response)

# Construir URL de foto a partir do número do imóvel
photo_url = build_photo_url("155550814458-7")
# -> https://venda-imoveis.caixa.gov.br/fotos/F1555508144587.jpg
```

## Apify Actors disponíveis

| Actor | Preço | Descrição |
|-------|-------|-----------|
| `pizani/caixa-imoveis-leiloes-api` | $10/mês | Busca por estado/cidade/modalidade |
| `leadercorp/caixa-leiloes-scraper` | $5/1000 | Mais completo (página de detalhe) |
| `brasil-scrapers/caixa-leiloes-api` | $25/mês | Detalhamento completo com imagens |
| `brasildados/ia-leilao-caixa-api` | $15/1000 | Com estimativa de valor de mercado IA |
"""

from .caixa_imoveis_parser import (
    from_caixa_listing,
    from_caixa_payload,
    fetch_via_apify,
    _normalize_photo_url,
    build_photo_url,
    build_photo_urls,
    _collect_photos,
    _parse_br_price,
    _extract_property_number_digits,
    FIELD_MAP,
    FONTE,
    BASE_URL,
    PHOTO_URL_PREFIX,
    SEARCH_BASE,
)

__all__ = [
    "from_caixa_listing",
    "from_caixa_payload",
    "fetch_via_apify",
    "_normalize_photo_url",
    "build_photo_url",
    "build_photo_urls",
    "_collect_photos",
    "_parse_br_price",
    "_extract_property_number_digits",
    "FIELD_MAP",
    "FONTE",
    "BASE_URL",
    "PHOTO_URL_PREFIX",
    "SEARCH_BASE",
]
