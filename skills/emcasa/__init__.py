"""
EmCasa — Extração de imóveis via API Foundation/Garagem AI.

Exporta as classes e funções principais para consumo externo.
"""

from .emcasa_api import (
    EmCasaClient,
    EmCasaSearchResult,
    EmCasaAPIError,
    PageCache,
    parse_hit,
    filter_city,
    filter_city_type,
    filter_neighborhood,
)
from .emcasa_parser import (
    from_emcasa_hit,
    from_emcasa_hits,
    from_emcasa_api_response,
    from_emcasa_safe,
)
from .algolia_parser import (
    parse_hit as algolia_parse_hit,
    parse_hits as algolia_parse_hits,
)
from .extract_page import (
    extract_page,
    extract_page_results,
)

__all__ = [
    "EmCasaClient",
    "EmCasaSearchResult",
    "EmCasaAPIError",
    "PageCache",
    "parse_hit",
    "algolia_parse_hit",
    "algolia_parse_hits",
    "filter_city",
    "filter_city_type",
    "filter_neighborhood",
    "from_emcasa_hit",
    "from_emcasa_hits",
    "from_emcasa_api_response",
    "from_emcasa_safe",
    "extract_page",
    "extract_page_results",
]
