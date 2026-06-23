"""
mega_leiloes_parser — Parser for Mega Leilões (megaleiloes.com.br).

Mega Leilões is a major Brazilian auction portal that uses Algolia for its
search functionality. This parser extracts listings directly from the Algolia
API, bypassing the Cloudflare-protected SSR pages.

## Extraction Strategy

### Primary: Direct Algolia API Query
- Application ID: 1A8O5M7X6Q
- Public search-only API Key: 055311365c6f5cdd0d1bff3e0acba7ae
- Index name: Items
- Endpoint: POST https://1A8O5M7X6Q.algolia.net/1/indexes/Items/query
- ~122K total records, ~1000 per page max

### Filtering
Real estate subcategories are filtered at query time via Algolia facet filters.
Active listings include batch_status 0 (upcoming) and 1 (open).

### Image URLs
- Thumbnail (from Algolia): https://cdn1.megaleiloes.com.br/batches/{batch_id}/{md5_hash}_320x240.jpg
- Medium (SSR carousel):   https://cdn1.megaleiloes.com.br/batches/{batch_id}/{md5_hash}_670x380.jpg
- Full (SSR lightbox):     https://cdn1.megaleiloes.com.br/batches/{batch_id}/{md5_hash}_1024x768.jpg

**Important:** The Algolia API returns only ONE image per listing (via ``image_path``). The
SSR detail page can show MULTIPLE images (2-5+ unique md5 hashes), but all follow the
same CDN pattern with the same batch_id. The ``image_path`` from Algolia does NOT
necessarily correspond to the first SSR gallery image — it is an arbitrary hash.

To extract all images for a listing, the SSR detail page must be scraped (requires
Cloudflare bypass). The Algolia-only extraction captures only the single image from
``image_path``.

Functions:
    from_mega_listing(hit: dict) -> dict
        Convert a single Algolia hit to unified Imovel dict.

    from_mega_payload(raw) -> list[dict]
        Convert an Algolia API response to list of Imovel dicts.

    fetch_active_listings() -> list[dict]
        Fetch all active real estate listings from Algolia (all pages).

    _query_algolia(page, hits_per_page, filters) -> dict
        POST to Algolia search API.

    _build_image_url(batch_id, md5_hash, size=670) -> str
        Build CDN image URL for a given batch and hash.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ── Schema import ────────────────────────────────────────────────────────────

# Imovel schema lives at ~/.hermes/imovel_schema.py
_HERMES_PATH = Path.home() / ".hermes"
if str(_HERMES_PATH) not in sys.path:
    sys.path.insert(0, str(_HERMES_PATH))

try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None  # Fallback: return dict if Imovel not available

logger = logging.getLogger("mega_leiloes_parser")

# ── Constants ─────────────────────────────────────────────────────────────────

FONTE = "megaleiloes"

ALGOLIA_APP_ID = "1A8O5M7X6Q"
ALGOLIA_API_KEY = "055311365c6f5cdd0d1bff3e0acba7ae"
ALGOLIA_INDEX = "Items"
ALGOLIA_URL = (
    f"https://{ALGOLIA_APP_ID}.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
)

# Pagination
HITS_PER_PAGE = 1000
MAX_PAGES = 130  # Safety cap: 130 * 1000 = 130K > ~122K total

# Batch status values
BATCH_STATUS_UPCOMING = 0
BATCH_STATUS_OPEN = 1
BATCH_STATUS_SUSPENDED = 3
ACTIVE_STATUS_VALUES = [BATCH_STATUS_UPCOMING, BATCH_STATUS_OPEN]

# Real estate subcategories for filtering
REAL_ESTATE_SUBCATEGORIES = [
    "Apartamentos",
    "Casas",
    "Terrenos e Lotes",
    "Salas e Conjuntos",
    "Galpões e Depósitos",
    "Prédios",
    "Lojas",
    "Fazendas e Sítios",
    "Andares e Coberturas",
    "Imóveis Comerciais",
]

# CDN image URL patterns
# Three resolutions available on the same CDN:
#   - 320x240  (thumbnail, from Algolia image_path — 1 per listing)
#   - 670x380  (medium, SSR carousel using OwlCarousel)
#   - 1024x768 (full, SSR lightbox using MagnificPopup)
CDN_BASE = "https://cdn1.megaleiloes.com.br/batches"
THUMBNAIL_SIZE = 320
MEDIUM_RES_SIZE = 670     # Carousel display
FULL_RES_SIZE = 1024      # Lightbox / popup display

# Image URL regex to extract md5_hash from thumbnail URLs
_RE_IMAGE_MD5 = re.compile(r"/([a-f0-9]{32})_\d+x\d+\.jpg$")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
}

ALGOLIA_HEADERS = {
    "X-Algolia-API-Key": ALGOLIA_API_KEY,
    "X-Algolia-Application-Id": ALGOLIA_APP_ID,
    "Content-Type": "application/json",
}

DEFAULT_TIMEOUT = 30  # seconds

# ── Algolia query helper ─────────────────────────────────────────────────────


def _query_algolia(
    page: int = 0,
    hits_per_page: int = HITS_PER_PAGE,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """POST to Algolia search API and return the full response.

    NOTE: Server-side filters (``filters``, ``facetFilters``) are intentionally
    omitted because the Mega Leilões Algolia index does not have ``subcategory``
    or ``batch_status`` configured as filterable/facet attributes. All filtering
    is done client-side in ``fetch_active_listings()``.

    Args:
        page: Zero-based page number.
        hits_per_page: Max results per page (max 1000).
        timeout: HTTP request timeout in seconds.

    Returns:
        The parsed JSON response dict from Algolia.

    Raises:
        requests.RequestException: On HTTP/network errors.
        ValueError: On non-JSON or error responses.
    """
    params_parts = [
        "query=",
        f"hitsPerPage={hits_per_page}",
        f"page={page}",
        "attributesToRetrieve=*",
    ]

    params_str = "&".join(params_parts)
    payload = {"params": params_str}

    logger.debug("Algolia query: page=%d, hitsPerPage=%d", page, hits_per_page)

    resp = requests.post(
        ALGOLIA_URL,
        headers=ALGOLIA_HEADERS,
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()

    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"Algolia returned non-dict response: {type(data).__name__}")

    return data


# ── Image URL helpers ────────────────────────────────────────────────────────


def _extract_md5_hash(image_url: str) -> str | None:
    """Extract the md5 hash from a Mega Leilões CDN image URL.

    The URL format is:
        https://cdn1.megaleiloes.com.br/batches/{batch_id}/{md5_hash}_320x240.jpg

    Args:
        image_url: The full CDN image URL.

    Returns:
        The 32-character hex md5 hash, or None if not found.
    """
    if not image_url or not isinstance(image_url, str):
        return None
    match = _RE_IMAGE_MD5.search(image_url)
    if match:
        return match.group(1)
    return None


def _build_image_url(
    batch_id: int | str,
    md5_hash: str,
    size: int = MEDIUM_RES_SIZE,
) -> str:
    """Build a Mega Leilões CDN image URL for a given batch and hash.

    The URL patterns are:
        - Thumbnail:  {base}/{batch_id}/{md5_hash}_320x240.jpg  (size=320)
        - Medium:     {base}/{batch_id}/{md5_hash}_670x380.jpg  (size=670)
        - Full:       {base}/{batch_id}/{md5_hash}_1024x768.jpg (size=1024)

    Args:
        batch_id: The batch ID (int or string).
        md5_hash: The 32-character hex md5 hash.
        size: Desired width (320=thumbnail, 670=medium, 1024=full).

    Returns:
        The full CDN image URL string.
    """
    height = {
        320: 240,
        670: 380,
        1024: 768,
    }.get(size, 380)
    return f"{CDN_BASE}/{batch_id}/{md5_hash}_{size}x{height}.jpg"


def _get_medium_res_image(image_path: str | None) -> str | None:
    """Convert a thumbnail URL to its medium-resolution (670×380) variant.

    Takes the thumbnail URL from the Algolia hit and converts it
    to the 670×380 resolution by substituting the size in the filename.
    For full resolution (1024×768), call _build_image_url(size=FULL_RES_SIZE).

    Args:
        image_path: The thumbnail URL from Algolia (image_path field).

    Returns:
        Medium-resolution URL string (670×380), or None if input is invalid.
    """
    if not image_path or not isinstance(image_path, str):
        return None

    # Replace _320x240 with _670x380
    high_res = image_path.replace("_320x240.jpg", "_670x380.jpg")
    if high_res == image_path:
        # Maybe it's already a different size or format
        # Try to extract md5 and build from scratch
        md5 = _extract_md5_hash(image_path)
        if md5:
            # Extract batch_id from the URL
            # URL pattern: .../batches/{batch_id}/{md5_hash}_320x240.jpg
            before_hash = image_path[: image_path.find(md5)]
            batch_part = before_hash.rstrip("/").split("/")[-1]
            if batch_part.isdigit():
                return _build_image_url(int(batch_part), md5, MEDIUM_RES_SIZE)
        return image_path  # fallback: return original URL

    return high_res


# ── Field mapping: Algolia hit -> Imovel ─────────────────────────────────────

# Direct field name mapping from Algolia hit fields to Imovel schema keys
FIELD_MAP = {
    "objectID": "raw_id",
    "headline": "titulo",
    "batch_id": "batch_id",
    "batch": "batch",
    "batch_status": "batch_status",
    "auction": "auction",
    "auction_id": "auction_id",
    "auction_headline": "auction_headline",
    "category": "category",
    "subcategory": "subcategory",
    "address": "endereco",
    "sublocality": "bairro",
    "city": "cidade",
    "state": "uf",
    "first_instance_value": "first_instance_value",
    "second_instance_value": "second_instance_value",
    "third_instance_value": "third_instance_value",
    "currency": "currency",
    "first_instance_date_start": "first_instance_date_start_ts",
    "first_instance_date_end": "first_instance_date_end_ts",
    "second_instance_date_end": "second_instance_date_end_ts",
    "type": "tipo_leilao",
    "process_number": "process_number",
    "forum": "forum",
    "author": "author",
    "respondent": "respondent",
    "constituent": "constituent",
    "image_path": "image_path_original",
    "url": "url",
    "rating": "rating",
}

# Subcategory -> Imovel tipo mapping
SUBCATEGORY_TIPO_MAP = {
    "Apartamentos": "apartamento",
    "Casas": "casa",
    "Terrenos e Lotes": "terreno",
    "Salas e Conjuntos": "comercial",
    "Galpões e Depósitos": "comercial",
    "Prédios": "comercial",
    "Lojas": "comercial",
    "Fazendas e Sítios": "casa",
    "Andares e Coberturas": "apartamento",
    "Imóveis Comerciais": "comercial",
    "Coberturas": "cobertura",
    "Flat": "flat",
    "Kitnet": "kitnet",
    "Casa em Condomínio": "casa_condominio",
    "Sobrado": "sobrado",
    "Studio": "studio",
    "Loft": "loft",
}


# ── Safe type converters ─────────────────────────────────────────────────────


def _safe_get(hit: dict, *keys: str, default: Any = None) -> Any:
    """Get the first non-None value from hit for the given keys."""
    for key in keys:
        val = hit.get(key)
        if val is not None:
            return val
    return default


def _to_float(val: Any, default: float | None = None) -> float | None:
    """Convert a value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val: Any, default: int | None = None) -> int | None:
    """Convert a value to int safely."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _to_str(val: Any, default: str = "") -> str:
    """Convert a value to string safely."""
    if val is None:
        return default
    if isinstance(val, (str, int, float, bool)):
        return str(val)
    return str(val) if val else default


# ── Price parsing ────────────────────────────────────────────────────────────

# Regex to extract numeric value from Brazilian price strings
# Examples: "R$ 450.000,00" -> 450000.00, "R$ 1.234.567,89" -> 1234567.89
_RE_BRL_PRICE = re.compile(
    r"(?:R\$\s*)?([\d.]+,\d{2})"
)
_RE_USD_PRICE = re.compile(
    r"(?:US\$\s*)?([\d.]+,\d{2})"
)


def _parse_br_price(price_str: str | None) -> float | None:
    """Parse a Brazilian price string to float.

    Handles formats:
      - "R$ 450.000,00" -> 450000.00
      - "R$ 1.200.000,00" -> 1200000.00
      - "450000" -> 450000.00
      - None/"0"/"" -> None

    Args:
        price_str: Raw price string from Algolia (e.g., first_instance_value).

    Returns:
        Float value in BRL, or None if not parseable.
    """
    if not price_str or not isinstance(price_str, str):
        return None
    price_str = price_str.strip()
    if not price_str or price_str in ("0", "0,00", "0.00", ""):
        return None

    # Try to find a Brazilian-formatted number (with commas and dots)
    match = _RE_BRL_PRICE.search(price_str)
    if match:
        raw = match.group(1)
        # Brazilian format: 1.234.567,89 -> remove dots, replace comma with dot
        clean = raw.replace(".", "").replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            pass

    # Fallback: try direct float conversion
    try:
        return float(price_str.replace("R$", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_timestamp(ts: int | float | None) -> str | None:
    """Convert a Unix timestamp (seconds) to ISO 8601 string.

    Args:
        ts: Unix timestamp in seconds. Can be int or float.

    Returns:
        ISO 8601 formatted string, or None if ts is None/invalid.
    """
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (OSError, ValueError, TypeError):
        return None


# ── Main conversion functions ────────────────────────────────────────────────


def from_mega_listing(hit: dict) -> dict | Any | None:
    """Convert a single Algolia hit from Mega Leilões to unified Imovel dict.

    Args:
        hit: A single hit dict from the Algolia API response's ``hits`` array.

    Returns:
        Dict in unified Imovel schema (or Imovel instance if available).
        None if the hit is invalid/empty.
    """
    if not hit or not isinstance(hit, dict):
        return None

    mapped: dict[str, Any] = {}

    # ── Core fields via FIELD_MAP ────────────────────────────────────────
    for src_key, dst_key in FIELD_MAP.items():
        if src_key in hit:
            mapped[dst_key] = hit[src_key]

    # ── ID ───────────────────────────────────────────────────────────────
    # Use objectID as the unique ID, prefixed with fonte
    raw_id = _to_str(hit.get("objectID") or hit.get("batch_id", ""))
    if raw_id and isinstance(hit.get("objectID"), str):
        imovel_id = f"{FONTE}_{hit['objectID']}"
    elif raw_id:
        imovel_id = f"{FONTE}_batch_{raw_id}"
    else:
        imovel_id = ""
    mapped["id"] = imovel_id
    mapped["origem_id"] = hit.get("objectID")

    # ── Title ────────────────────────────────────────────────────────────
    # headline is the main title; fallback to auction + subcategory
    titulo = _to_str(hit.get("headline"))
    if not titulo:
        auction = _to_str(hit.get("auction"))
        subcategory = _to_str(hit.get("subcategory"))
        if auction and subcategory:
            titulo = f"{auction} - {subcategory}"
        elif auction:
            titulo = auction
        else:
            titulo = "Imóvel Mega Leilões"
    mapped["titulo"] = titulo[:500]

    # ── URL ──────────────────────────────────────────────────────────────
    raw_url = _to_str(hit.get("url"))
    if raw_url and not raw_url.startswith("http"):
        raw_url = f"https://www.megaleiloes.com.br{raw_url if raw_url.startswith('/') else '/' + raw_url}"
    mapped["url"] = raw_url

    # ── Source ───────────────────────────────────────────────────────────
    mapped["fonte"] = FONTE

    # ── Location ─────────────────────────────────────────────────────────
    mapped["endereco"] = _to_str(hit.get("address"))
    mapped["bairro"] = _to_str(hit.get("sublocality"))

    # city and state
    cidade = _to_str(hit.get("city"))
    mapped["cidade"] = cidade

    uf_raw = _to_str(hit.get("state"))
    uf = uf_raw.upper()[:2] if uf_raw else ""
    mapped["uf"] = uf

    # ── Price ────────────────────────────────────────────────────────────
    currency = _to_str(hit.get("currency", "R$"))

    # first_instance_value is the primary auction value
    first_value_str = _to_str(hit.get("first_instance_value"))
    second_value_str = _to_str(hit.get("second_instance_value"))
    third_value_str = _to_str(hit.get("third_instance_value"))

    mapped["preco_venda"] = _parse_br_price(first_value_str)
    # Store additional auction prices in _extra
    mapped["first_instance_value_raw"] = first_value_str
    mapped["second_instance_value"] = _parse_br_price(second_value_str)
    mapped["third_instance_value"] = _parse_br_price(third_value_str)
    mapped["currency"] = currency

    # ── Dates (Unix timestamps to ISO) ───────────────────────────────────
    mapped["data_leilao_inicio"] = _parse_timestamp(
        _to_int(hit.get("first_instance_date_start"))
    )
    mapped["data_leilao_fim"] = _parse_timestamp(
        _to_int(hit.get("first_instance_date_end"))
    )
    mapped["data_segunda_praca"] = _parse_timestamp(
        _to_int(hit.get("second_instance_date_end"))
    )

    # ── Property type from subcategory ───────────────────────────────────
    subcategory = _to_str(hit.get("subcategory"))
    mapped["subcategory"] = subcategory
    tipo = SUBCATEGORY_TIPO_MAP.get(subcategory, "outro")
    mapped["tipo"] = tipo

    # ── Auction metadata ─────────────────────────────────────────────────
    mapped["tipo_leilao"] = _to_str(hit.get("type"))  # Judicial/Extrajudicial
    mapped["process_number"] = _to_str(hit.get("process_number"))
    mapped["forum"] = _to_str(hit.get("forum"))
    mapped["author"] = _to_str(hit.get("author"))
    mapped["respondent"] = _to_str(hit.get("respondent"))
    mapped["constituent"] = _to_str(hit.get("constituent"))

    # Batch info
    mapped["batch"] = _to_str(hit.get("batch"))
    batch_id = hit.get("batch_id")
    mapped["batch_id"] = _to_int(batch_id)
    mapped["batch_status"] = _to_int(hit.get("batch_status"))

    # ── Auction status label ─────────────────────────────────────────────
    batch_status = mapped.get("batch_status")
    if batch_status == 0:
        mapped["status_leilao"] = "upcoming"
        mapped["disponivel"] = True
        mapped["status"] = "upcoming"
    elif batch_status == 1:
        mapped["status_leilao"] = "open"
        mapped["disponivel"] = True
        mapped["status"] = "ativo"
    elif batch_status == 3:
        mapped["status_leilao"] = "suspended"
        mapped["disponivel"] = False
        mapped["status"] = "suspenso"
    else:
        mapped["status_leilao"] = _to_str(batch_status)
        mapped["disponivel"] = True
        mapped["status"] = "ativo"

    # ── Rating ───────────────────────────────────────────────────────────
    mapped["rating"] = _to_int(hit.get("rating"))

    # ── Images ───────────────────────────────────────────────────────────
    image_path = hit.get("image_path")
    fotos: list[str] = []

    if image_path and isinstance(image_path, str):
        med_res = _get_medium_res_image(image_path)
        if med_res:
            fotos.append(med_res)

    mapped["fotos"] = fotos
    mapped["image_path_original"] = image_path

    # ── Description ──────────────────────────────────────────────────────
    # Build a description from available auction metadata
    desc_parts: list[str] = []
    if mapped.get("tipo_leilao"):
        desc_parts.append(f"Tipo: {mapped['tipo_leilao']}")
    if mapped.get("process_number"):
        desc_parts.append(f"Processo: {mapped['process_number']}")
    if mapped.get("forum"):
        desc_parts.append(f"Foro: {mapped['forum']}")
    if mapped.get("data_leilao_inicio"):
        desc_parts.append(f"1ª Praça: {mapped['data_leilao_inicio']}")
    if mapped.get("data_segunda_praca"):
        desc_parts.append(f"2ª Praça: {mapped['data_segunda_praca']}")
    if mapped.get("first_instance_value_raw"):
        desc_parts.append(f"1ª Avaliação: {mapped['first_instance_value_raw']}")
    if mapped.get("batch"):
        desc_parts.append(f"Lote: {mapped['batch']}")

    mapped["descricao"] = " | ".join(desc_parts) if desc_parts else ""

    # ── Amenities ────────────────────────────────────────────────────────
    # Mega Leilões doesn't provide amenities; use subcategory + type as tags
    tags: list[str] = []
    if subcategory:
        tags.append(subcategory.lower().replace(" ", "_"))
    if mapped.get("tipo_leilao"):
        tags.append(mapped["tipo_leilao"].lower())
    mapped["amenities"] = tags

    # ── Data collection timestamp ────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    mapped["data_coleta"] = now

    # ── Clean up intermediate fields ─────────────────────────────────────
    # Remove raw_id if it's the same as id
    if mapped.get("raw_id") == hit.get("objectID", ""):
        mapped["raw_id"] = hit["objectID"]

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    # If Imovel is available, try to create instance with _extra preservation
    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
    if Imovel is not None:
        try:
            # Collect extra fields not in the Imovel schema
            imovel_extra = {
                k: v for k, v in mapped.items()
                if k not in Imovel.__dataclass_fields__
            }
            imovel = Imovel.from_dict(mapped)
            imovel._extra = imovel_extra

            # Return dict with Imovel schema fields plus extra fields
            result = imovel.to_dict()
            result.update(imovel_extra)
            return result
        except Exception as e:
            logger.warning("Erro ao criar Imovel: %s", e)
            return mapped

    return mapped


# ── Batch conversion ─────────────────────────────────────────────────────────


def from_mega_payload(raw: Any) -> list[dict]:
    """Convert an Algolia API response to list of unified Imovel dicts.

    Accepts:
      - Raw dict with ``hits`` key (standard Algolia response)
      - List of hits directly
      - String containing JSON

    Args:
        raw: Algolia API response or list of hits.

    Returns:
        List of Imovel dicts (never None; empty list on failure).
    """
    # Accept string JSON
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    # Extract hits from Algolia response format
    if isinstance(raw, dict):
        hits = raw.get("hits")
        if isinstance(hits, list):
            raw = hits
            logger.debug("Extracted %d hits from Algolia response", len(hits))
        else:
            # Maybe it's a single hit wrapped in a dict?
            if "objectID" in raw or "batch_id" in raw or "headline" in raw:
                raw = [raw]
            else:
                logger.warning(
                    "Payload dict sem campo 'hits' reconhecido. Chaves: %s",
                    list(raw.keys())[:10],
                )
                return []

    if not isinstance(raw, list):
        logger.warning(
            "Payload inesperado: esperava list, recebeu %s", type(raw).__name__
        )
        return []

    imoveis = []
    for item in raw:
        imovel = from_mega_listing(item)
        if imovel:
            imoveis.append(imovel)

    logger.info("Parsed %d listings from Mega Leilões payload", len(imoveis))
    return imoveis


# ── Fetch all active listings ────────────────────────────────────────────────


def fetch_active_listings(
    timeout: int = DEFAULT_TIMEOUT,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """Fetch all active real estate listings from Mega Leilões via Algolia.

    Iterates through all pages of the Algolia index, filtering client-side for:
      - Category: "Imóveis" (real estate)
      - Batch status: 0 (upcoming) or 1 (open)

    Server-side filters (``filters``, ``facetFilters``) are intentionally
    avoided because this Algolia index does not have ``subcategory`` or
    ``batch_status`` configured as filterable/facet attributes. All filtering
    is done client-side in Python after fetching raw hits.

    Args:
        timeout: HTTP request timeout in seconds per page.
        max_pages: Maximum number of pages to fetch (safety cap).

    Returns:
        Deduplicated list of Imovel dicts sorted by ID (stable order).

    Raises:
        RuntimeError: If the initial Algolia query fails.
        requests.RequestException: On persistent HTTP errors.
    """
    all_hits: list[dict] = []
    seen_ids: set[str] = set()
    total_found = 0
    page = 0

    logger.info(
        "Fetching Mega Leilões listings (client-side filter: Imóveis, "
        "batch_status in %s)",
        ACTIVE_STATUS_VALUES,
    )

    while page < max_pages:
        logger.debug("Fetching Algolia page %d...", page)

        try:
            data = _query_algolia(
                page=page,
                hits_per_page=HITS_PER_PAGE,
                timeout=timeout,
            )
        except requests.RequestException as e:
            if page == 0:
                raise RuntimeError(
                    f"Falha ao consultar Algolia na página 0: {e}"
                )
            logger.error("Erro na página %d: %s — interrompendo", page, e)
            break

        hits = data.get("hits", [])
        nb_pages = data.get("nbPages", 0)
        total_found = data.get("nbHits", 0)

        if not isinstance(hits, list):
            logger.warning("Resposta inesperada: hits não é list na página %d", page)
            break

        if not hits:
            logger.info("Página %d vazia — fim da paginação", page)
            break

        # Filter client-side for real estate + active status
        new_count = 0
        for hit in hits:
            category = hit.get("category", "")
            batch_status = hit.get("batch_status")

            # Client-side filter: must be real estate
            if category != "Imóveis":
                continue

            # Client-side filter: must be active (upcoming or open)
            if batch_status not in ACTIVE_STATUS_VALUES:
                continue

            # Deduplicate by objectID
            oid = hit.get("objectID", "")
            if oid and oid not in seen_ids:
                seen_ids.add(oid)
                all_hits.append(hit)
                new_count += 1
            elif not oid:
                all_hits.append(hit)
                new_count += 1

        logger.debug(
            "Page %d: %d hits (%d new real estate, %d total accumulated, "
            "%d total found)",
            page, len(hits), new_count, len(all_hits), total_found,
        )

        # Stop if we've got all pages
        if page >= nb_pages - 1:
            logger.info(
                "Última página (%d/%d) alcançada", page + 1, nb_pages
            )
            break

        page += 1

        # Rate limiting: small delay between pages
        if page < max_pages:
            import time as _time
            _time.sleep(0.3)

    logger.info(
        "Coletados %d listings únicos de Mega Leilões "
        "(total=%d, páginas=%d)",
        len(all_hits), total_found, page + 1,
    )

    # Parse all hits to unified schema
    imoveis = from_mega_payload(all_hits)

    # Sort by ID for stable ordering
    try:
        imoveis.sort(key=lambda x: x.get("id", "") or "")
    except Exception:
        pass

    return imoveis


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    """CLI for testing the Mega Leilões parser directly."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Mega Leilões Parser — teste e execução"
    )
    sub = parser.add_subparsers(dest="command")

    # fetch: fetch all active listings
    fetch_parser = sub.add_parser("fetch", help="Busca todos os leilões ativos")
    fetch_parser.add_argument(
        "--max-pages", type=int, default=5,
        help="Máximo de páginas (padrão: 5 para teste)"
    )
    fetch_parser.add_argument(
        "--output", help="Salvar JSON em arquivo"
    )
    fetch_parser.add_argument(
        "--limit", type=int, default=0,
        help="Limitar número de resultados (0 = todos)"
    )

    # query: single page test query
    query_parser = sub.add_parser(
        "query", help="Testa uma consulta única ao Algolia"
    )
    query_parser.add_argument(
        "--page", type=int, default=0
    )
    query_parser.add_argument(
        "--hits", type=int, default=5,
        help="Hits per page (padrão: 5)"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.command == "fetch":
        imoveis = fetch_active_listings(max_pages=args.max_pages)
        if args.limit > 0:
            imoveis = imoveis[: args.limit]

        print(f"\n=== Mega Leilões: {len(imoveis)} imóveis coletados ===")
        if imoveis:
            # Summary stats
            precos = [
                i["preco_venda"]
                for i in imoveis
                if i.get("preco_venda") is not None
            ]
            if precos:
                print(
                    f"  Preços: R$ {min(precos):.0f} ~ R$ {max(precos):.0f}"
                )
            estados = {}
            for i in imoveis:
                uf = i.get("uf", "??")
                estados[uf] = estados.get(uf, 0) + 1
            print(f"  Estados: {dict(sorted(estados.items()))}")

            print(f"\n  Amostra (primeiro):")
            first = imoveis[0]
            print(f"    ID:      {first.get('id', 'N/A')}")
            print(f"    Título:  {first.get('titulo', 'N/A')}")
            print(f"    Preço:   R$ {first.get('preco_venda', 'N/A')}")
            print(f"    Cidade:  {first.get('cidade', 'N/A')} - {first.get('uf', 'N/A')}")
            print(f"    Tipo:    {first.get('tipo', 'N/A')}")
            print(f"    Status:  {first.get('status', 'N/A')}")
            fotos = first.get("fotos", [])
            if fotos:
                print(f"    Fotos:   {len(fotos)} (1ª: {fotos[0][:80]}...)")
            else:
                print(f"    Fotos:   0")

        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"\n  Salvo em: {out_path}")

    elif args.command == "query":
        data = _query_algolia(
            page=args.page,
            hits_per_page=args.hits,
        )
        hits = data.get("hits", [])
        # Client-side filter for display
        from collections import Counter
        re_hits = [h for h in hits if h.get("category") == "Imóveis" and h.get("batch_status") in ACTIVE_STATUS_VALUES]
        print(f"\n=== Algolia Query (page={args.page}, hits={len(hits)}) ===")
        print(f"  Total found: {data.get('nbHits', '?')}")
        print(f"  Total pages: {data.get('nbPages', '?')}")
        print(f"  Real estate active: {len(re_hits)}/{len(hits)}")
        print()

        for i, hit in enumerate(re_hits[:5], 1):
            print(f"  {i}. {hit.get('headline', 'N/A')}")
            print(f"     Subcat: {hit.get('subcategory', 'N/A')}")
            print(f"     Price:  {hit.get('first_instance_value', 'N/A')}")
            print(f"     Status: {hit.get('batch_status', 'N/A')}")
            print(f"     City:   {hit.get('city', 'N/A')}/{hit.get('state', 'N/A')}")
            print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
