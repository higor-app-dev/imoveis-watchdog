"""
zuk — Extractor do Portal Zuk (portalzuk.com.br) para o schema unificado Imovel.

Exporta as funções principais para uso pela pipeline:
    from_zuk_listing(raw_dict) -> Imovel
    from_zuk_payload(payload) -> list[Imovel]
    crawl_listing(url, pages) -> list[Imovel]
    extract_from_html(html, source_url) -> list[dict]
    extract_listing_page(url, timeout) -> list[dict]
"""

from __future__ import annotations

from skills.zuk.zuk_parser import (
    from_zuk_listing,
    from_zuk_payload,
    crawl_listing,
    extract_from_html,
    extract_listing_page,
    build_listing_url,
)

__all__ = [
    "from_zuk_listing",
    "from_zuk_payload",
    "crawl_listing",
    "extract_from_html",
    "extract_listing_page",
    "build_listing_url",
]
