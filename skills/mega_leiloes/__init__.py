"""
Mega Leilões — Extração de imóveis via Algolia API.

Mega Leilões (megaleiloes.com.br) é um grande portal de leilões brasileiro
que usa Algolia como mecanismo de busca. Este módulo extrai dados
diretamente da API pública do Algolia, sem necessidade de browser.

Uso básico:
    from skills.mega_leiloes.mega_leiloes_parser import (
        from_mega_listing,
        from_mega_payload,
        fetch_active_listings,
    )

    # Buscar todos os leilões ativos de imóveis
    imoveis = fetch_active_listings()

    # Parsear um hit individual do Algolia
    imovel = from_mega_listing(algolia_hit)

    # Parsear resposta completa da API
    imoveis = from_mega_payload(algolia_response)
"""

from .mega_leiloes_parser import (
    from_mega_listing,
    from_mega_payload,
    fetch_active_listings,
    _query_algolia,
    _build_image_url,
    _get_medium_res_image,
    FIELD_MAP,
    SUBCATEGORY_TIPO_MAP,
    REAL_ESTATE_SUBCATEGORIES,
    ALGOLIA_APP_ID,
    ALGOLIA_URL,
)

__all__ = [
    "from_mega_listing",
    "from_mega_payload",
    "fetch_active_listings",
    "_query_algolia",
    "_build_image_url",
    "_get_medium_res_image",
    "FIELD_MAP",
    "SUBCATEGORY_TIPO_MAP",
    "REAL_ESTATE_SUBCATEGORIES",
    "ALGOLIA_APP_ID",
    "ALGOLIA_URL",
]
