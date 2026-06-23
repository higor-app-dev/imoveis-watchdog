"""
Sodré Santoro — Parser for sodresantoro.com.br auction listings.

Extracts property auction listings from the Sodré Santoro REST API
(prd-api.sodresantoro.com.br) and converts them to the unified
Imovel schema used by the imoveis-watchdog pipeline.

Exports:
    from_sodre_listing(auction, lot) -> dict | None
    from_sodre_payload(raw) -> list[dict]
    fetch_listings(limit, max_pages) -> list[dict]
    FIELD_MAP
"""

from .sodre_santoro_parser import (
    from_sodre_listing,
    from_sodre_payload,
    fetch_listings,
    FIELD_MAP,
    _normalize_photo_url,
    _collect_photos,
    _parse_price,
    _extract_city_state,
    API_BASE,
    PHOTO_BASE,
    DETAIL_BASE,
    TYPE_MAP,
)
