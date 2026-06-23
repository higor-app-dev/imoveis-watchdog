"""Biasi Leilões — Extração de imóveis de leilões via SSR (biasileiloes.com.br)."""

from skills.biasi_leiloes.biasi_leiloes_parser import (
    from_biasi_listing,
    from_biasi_payload,
    run_scraper,
    _normalize_photo_url,
    _collect_photos,
    _generate_all_resolutions,
    _parse_area_text,
    _parse_bedrooms_text,
    _parse_money_br,
    _parse_date_br,
    _derive_partition,
    _infer_tipo,
    _extract_vagas_text,
    PHOTO_SIZES,
    CDN_BASE,
)

from skills.biasi_leiloes.extractor import (
    extract_listings,
    extract_detail,
    extract_all,
    extract_imoveis,
)

__all__ = [
    # Parser
    "from_biasi_listing",
    "from_biasi_payload",
    "run_scraper",
    "_normalize_photo_url",
    "_collect_photos",
    "_generate_all_resolutions",
    "_parse_area_text",
    "_parse_bedrooms_text",
    "_parse_money_br",
    "_parse_date_br",
    "_derive_partition",
    "_infer_tipo",
    "_extract_vagas_text",
    "PHOTO_SIZES",
    "CDN_BASE",
    # Extractor
    "extract_listings",
    "extract_detail",
    "extract_all",
    "extract_imoveis",
]
