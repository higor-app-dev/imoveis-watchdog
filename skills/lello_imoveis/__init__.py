"""Lello Imóveis — Extração de imóveis via SSR a partir de __NEXT_DATA__."""

from skills.lello_imoveis.lello_ssr import (
    extract_from_ssr,
    extract_from_html,
    extract_detail_from_ssr,
    map_listing_to_imovel,
    build_search_url,
    build_detail_url,
)

from skills.lello_imoveis.lello_parser import (
    from_lello_listing,
    from_lello_payload,
    build_lello_url,
    crawl_tipo,
    crawl_all,
    crawl_from_targets,
    load_targets_from_yaml,
    save_results,
    save_to_unified_schema,
)

__all__ = [
    "extract_from_ssr",
    "extract_from_html",
    "extract_detail_from_ssr",
    "map_listing_to_imovel",
    "build_search_url",
    "build_detail_url",
    "from_lello_listing",
    "from_lello_payload",
    "build_lello_url",
    "crawl_tipo",
    "crawl_all",
    "crawl_from_targets",
    "load_targets_from_yaml",
    "save_results",
    "save_to_unified_schema",
]
