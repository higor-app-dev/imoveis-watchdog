"""
caixa_imoveis_parser — Parser for Caixa Econômica Federal property sales (venda-imoveis.caixa.gov.br).

## ANTI-BOT WARNING: Radware Bot Manager + hCaptcha

The Caixa property portal (venda-imoveis.caixa.gov.br) is protected by **Radware Bot Manager**
perfdrive.com) with **hCaptcha** challenges. This is a HIGH-severity anti-bot system that:

- Blocks all direct HTTP requests (curl, Python requests, httpx, aiohttp) to search and
  detail endpoints — always returns Radware CAPTCHA challenge HTML.
- Blocks headless browsers detected as automation (Puppeteer/Playwright without stealth).
- Uses behavioral analysis (mouse movement, scroll, click patterns) via JS.
- Tracks session via `__uzma`, `__uzmb`, `__uzmc`, `__uzmd`, `__uzme` cookies.
- Served behind Azion edge platform (Brazilian CDN).

**Direct HTTP scraping of listing/detail pages is NOT feasible with standard tools.**

## What IS accessible without protection

| Endpoint | Access | Purpose |
|----------|--------|---------|
| `/fotos/F*.jpg` | UNPROTECTED — direct HTTP works | Property images |
| `/sistema/assets/*.css` | UNPROTECTED | Static assets |

## Recommended approaches for data extraction

### Option A: Apify Actor (Recommended for production)
Multiple Apify actors already handle Radware bypass. See `fetch_via_apify()` below.

### Option B: Playwright + Stealth + Residential Proxies
Use the existing browser-automation skill with:
- `playwright-stealth` plugin
- Residential proxy rotation (BrightData, Oxylabs)
- Realistic user-agent + viewport randomization

### Option C: CSV Download (Partial data)
The `/sistema/download-lista.asp` endpoint can generate CSVs via Selenium with
manual CAPTCHA solving or saved session cookies.

## Photo URLs (UNPROTECTED)
Image URLs follow the pattern:
    https://venda-imoveis.caixa.gov.br/fotos/F{propertyNumberDigits}.jpg

The property number numeric portion is used in the filename. Examples:
    Property "155550814458-7" -> "F155550814458721.jpg" (exact mapping may vary)
These can be fetched with simple HTTP GET — no cookies, no special headers.

## Data flow (reverse engineered)
1. POST `busca-imovel.asp` — search form with city/state/type/price filters
2. POST `carregaListaImoveis.asp` — pipe-separated property IDs → HTML listing
3. GET `detalhe-imovel.asp?hdnimovel={propertyNumber}` — full detail HTML
4. POST `download-lista.asp` — CSV download (limited fields)

Functions:
    from_caixa_listing(dict) -> dict | None
        Convert a single Caixa listing dict to unified Imovel schema.

    from_caixa_payload(dict|list) -> list[dict]
        Convert a Caixa payload (list or dict) to list of Imovel dicts.

    fetch_via_apify(apify_token, actor_id, run_input) -> list[dict]
        Placeholder for Apify actor integration.

    _normalize_photo_url(url, property_number) -> str | None
        Normalize a photo URL to absolute URL.

    build_photo_urls(property_number) -> list[str]
        Construct image URLs from property number.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Schema import ────────────────────────────────────────────────────────────

# Imovel schema lives at ~/.hermes/imovel_schema.py
_HERMES_PATH = Path.home() / ".hermes"
if str(_HERMES_PATH) not in sys.path:
    sys.path.insert(0, str(_HERMES_PATH))

try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None  # Fallback: return dict if Imovel not available

logger = logging.getLogger("caixa_imoveis_parser")

# ── Constants ─────────────────────────────────────────────────────────────────

FONTE = "caixa"
BASE_URL = "https://venda-imoveis.caixa.gov.br"
PHOTO_URL_PREFIX = f"{BASE_URL}/fotos"
SEARCH_BASE = f"{BASE_URL}/sistema"

# Photo URL pattern
#   Full URL: https://venda-imoveis.caixa.gov.br/fotos/F{propertyNumberDigits}.jpg
#   Relative: /fotos/F{propertyNumberDigits}.jpg
PHOTO_FILENAME_PREFIX = "F"
PHOTO_EXTENSION = ".jpg"

# ── Modalidade → tipo_venda mapping ──────────────────────────────────────────

# Modalidades de venda direta (sem leilão)
VENDA_DIRETA_MODALIDADES = frozenset({
    "Venda Online",
    "Venda Direta Online",
    "Venda Direta FAR",
    "33",  # Venda Online (código numérico)
    "34",  # Venda Direta Online
    "9",   # Venda Direta FAR
})

# Modalidades de leilão
LEILAO_MODALIDADES = frozenset({
    "1º Leilão SFI",
    "1o Leilao SFI",
    "2º Leilão SFI",
    "2o Leilao SFI",
    "Concorrência Pública",
    "Concorrencia Publica",
    "Leilão SFI - Edital Único",
    "Leilao SFI - Edital Unico",
    "Licitação Aberta",
    "Licitacao Aberta",
    "4",   # 1º Leilão SFI
    "5",   # 2º Leilão SFI
    "2",   # Concorrência Pública
    "14",  # Leilão SFI - Edital Único
    "21",  # Licitação Aberta
})


def _derivar_tipo_venda(modalidade: str | None) -> str | None:
    """Deriva o tipo de venda (venda_direta ou leilao) a partir da modalidade.

    Args:
        modalidade: Nome ou código da modalidade (ex.: 'Venda Online', '33').

    Returns:
        'venda_direta', 'leilao', ou None se não reconhecida.
    """
    if not modalidade:
        return None
    modalidade = modalidade.strip()
    if modalidade in VENDA_DIRETA_MODALIDADES:
        return "venda_direta"
    if modalidade in LEILAO_MODALIDADES:
        return "leilao"
    logger.debug("Modalidade não reconhecida para tipo_venda: %s", modalidade)
    return None


# ── Field mapping: Caixa listing dict -> Imovel ──────────────────────────────

# Maps field names from the Caixa portal (detail page / CSV / any extraction
# method) to the unified Imovel schema keys.
#
# The left column shows canonical field names as they appear in the Caixa data
# (from detail page scraping, CSV columns, or Apify actor output). The right
# column maps to the unified Imovel schema.
#
# Caixa-specific fields that don't have a direct Imovel equivalent are prefixed
# with "caixa_" to preserve them during conversion.
FIELD_MAP = {
    # Identity
    "propertyNumber": "origem_id",
    "N. do imovel": "origem_id",
    "N° do imóvel": "origem_id",
    "N do imovel": "origem_id",
    "codigo": "origem_id",

    # Price (Apify simplified: "price": 310000)
    "price": "preco_venda",

    # Type (Apify simplified: "type": "Apartamento")
    "type": "tipo",

    # Notice/modalidade (Apify detailed: "notice": "Leilão SFI - Edital Único")
    "notice": "caixa_modalidade",
    "edital_notice": "caixa_modalidade",

    # Office (Apify detailed: "office": "03")
    "office": "caixa_cartorio",

    # Real estate registration (Apify detailed: "realEstateRegistration")
    "realEstateRegistration": "caixa_registro_imovel",
    "realEstateRegistrationNumber": "caixa_registro_imovel",

    # Location
    "state": "uf",
    "UF": "uf",
    "estado": "uf",
    "city": "cidade",
    "Cidade": "cidade",
    "cidade": "cidade",
    "district": "bairro",
    "Bairro": "bairro",
    "bairro": "bairro",
    "address": "endereco",
    "Endereço": "endereco",
    "Endereco": "endereco",
    "endereco": "endereco",
    "zipCode": "cep",
    "cep": "cep",
    "CEP": "cep",

    # Property characteristics
    "propertyType": "tipo",
    "Tipo": "tipo",
    "Tipo de imóvel": "tipo",
    "tipo_imovel": "tipo",
    "rooms": "quartos",
    "quartos": "quartos",
    "Quartos": "quartos",
    "Dormitórios": "quartos",
    "Dormitorios": "quartos",
    "garage": "vagas",
    "vagas": "vagas",
    "Vagas": "vagas",
    "Garagem": "vagas",
    "privateArea": "area",
    "private_area": "area",
    "Área privativa": "area",
    "Area privativa": "area",
    "area_privativa": "area",
    "totalArea": "caixa_area_total",
    "total_area": "caixa_area_total",
    "Área total": "caixa_area_total",
    "Area total": "caixa_area_total",
    "landArea": "caixa_area_terreno",
    "land_area": "caixa_area_terreno",
    "Área do terreno": "caixa_area_terreno",
    "Area do terreno": "caixa_area_terreno",

    # Pricing
    "evaluationValue": "caixa_valor_avaliacao",
    "Valor de avaliação": "caixa_valor_avaliacao",
    "Valor de avaliacao": "caixa_valor_avaliacao",
    "valor_avaliacao": "caixa_valor_avaliacao",
    "minimumSaleValue": "preco_venda",
    "Preço": "preco_venda",
    "Preco": "preco_venda",
    "preco": "preco_venda",
    "preco_venda": "preco_venda",
    "discount": "caixa_desconto_percentual",
    "Desconto": "caixa_desconto_percentual",
    "desconto": "caixa_desconto_percentual",

    # Auction / Sale info
    "modality": "caixa_modalidade",
    "Modalidade de venda": "caixa_modalidade",
    "modalidade": "caixa_modalidade",
    "firstAuctionDate": "caixa_primeira_data_leilao",
    "primeira_data_leilao": "caixa_primeira_data_leilao",
    "secondAuctionDate": "caixa_segunda_data_leilao",
    "segunda_data_leilao": "caixa_segunda_data_leilao",
    "paymentMethods": "caixa_formas_pagamento",
    "formas_pagamento": "caixa_formas_pagamento",
    "expenseRules": "caixa_regras_despesas",
    "regras_despesas": "caixa_regras_despesas",
    "occupancy": "caixa_ocupacao",
    "ocupacao": "caixa_ocupacao",
    "acceptsFGTS": "caixa_aceita_fgts",
    "aceita_fgts": "caixa_aceita_fgts",

    # Content
    "description": "descricao",
    "Descrição": "descricao",
    "Descricao": "descricao",
    "descricao": "descricao",

    # Metadata
    "registrationNumber": "caixa_matricula",
    "matricula": "caixa_matricula",
    "notaryDistrict": "caixa_comarca",
    "comarca": "caixa_comarca",
    "notaryOffice": "caixa_cartorio",
    "cartorio": "caixa_cartorio",
    "propertyRegistration": "caixa_registro_imovel",
    "registro_imovel": "caixa_registro_imovel",
    "edital": "caixa_edital",
    "auctioneer": "caixa_leiloeiro",
    "leiloeiro": "caixa_leiloeiro",
    "numberItem": "caixa_numero_item",
    "numero_item": "caixa_numero_item",

    # Image
    "image": "foto_principal",
    "foto_principal": "foto_principal",
    "image_url": "foto_principal",

    # URL
    "url": "url",
    "Link de acesso": "url",
    "link": "url",
}

# ── Safe type helpers ────────────────────────────────────────────────────────


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Return the first non-None value found for any of the given keys."""
    for key in keys:
        val = data.get(key)
        if val is not None:
            return val
    return default


def _to_float(val: Any, default: float | None = None) -> float | None:
    """Safely convert a value to float."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val: Any, default: int | None = None) -> int | None:
    """Safely convert a value to int."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _to_str(val: Any, default: str = "") -> str:
    """Safely convert a value to string."""
    if val is None:
        return default
    if isinstance(val, (str, int, float, bool)):
        return str(val).strip()
    return str(val).strip() if val else default


# ── Photo URL helpers ─────────────────────────────────────────────────────────


def _extract_property_number_digits(prop_number: Any) -> str | None:
    """Extract only the digit portion of a property number.

    Caixa property numbers come in formats like:
        "155550814458-7" -> "1555508144587"
        "1555508144587"  -> "1555508144587"
        1555508144587    -> "1555508144587"

    The image filename uses the numeric digits without the hyphen separator.
    Note: The exact mapping from property number to the image filename suffix
    may need empirical verification — the research suggests the hyphen is
    removed, but the image filename may contain additional digits.

    Args:
        prop_number: Raw property number (string or numeric).

    Returns:
        String of digits only, or None if input is empty.
    """
    if prop_number is None:
        return None
    s = _to_str(prop_number)
    if not s:
        return None
    # Remove everything except digits
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    return digits


def build_photo_url(property_number: Any) -> str | None:
    """Build a single photo URL for a given Caixa property number.

    Image URL pattern:
        https://venda-imoveis.caixa.gov.br/fotos/F{digits}.jpg

    The /fotos/ path is NOT protected by Radware — images can be fetched
    with plain HTTP requests.

    Args:
        property_number: Property number (e.g., "155550814458-7" or 155550814458721).

    Returns:
        Absolute photo URL string, or None if property_number is invalid.
    """
    digits = _extract_property_number_digits(property_number)
    if not digits:
        return None
    return f"{PHOTO_URL_PREFIX}/{PHOTO_FILENAME_PREFIX}{digits}{PHOTO_EXTENSION}"


def build_photo_urls(*property_numbers: Any) -> list[str]:
    """Build photo URLs for one or more property numbers.

    Convenience wrapper around ``build_photo_url`` that accepts multiple
    property numbers and returns a deduplicated list of absolute URLs.

    Args:
        *property_numbers: One or more property number values (string or numeric).

    Returns:
        Deduplicated list of absolute photo URLs. Invalid inputs are skipped.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for pn in property_numbers:
        url = build_photo_url(pn)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _normalize_photo_url(
    url: Any,
    property_number: Any = None,
) -> str | None:
    """Normalize a photo URL to an absolute URL.

    Handles:
    - Already absolute HTTP(S) URL -> pass through
    - Relative path (e.g., "/fotos/F123.jpg") -> prepend BASE_URL
    - Just filename (e.g., "F123.jpg") -> prepend PHOTO_URL_PREFIX
    - Dict with "url" or "src" key -> extract and normalize
    - None / empty -> fall back to ``build_photo_url(property_number)``
    - If all else fails and property_number is given, construct from it

    Args:
        url: Raw photo value from Caixa data (str, dict, or None).
        property_number: Fallback property number to construct URL from.

    Returns:
        Absolute URL string, or None if nothing valid could be produced.
    """
    # Dict format (e.g. {"url": "/fotos/F123.jpg", "subtitle": "Sala"})
    if isinstance(url, dict):
        url = url.get("url") or url.get("src") or None
        if not url:
            # Fallback to property_number
            if property_number is not None:
                return build_photo_url(property_number)
            return None

    if url is None:
        if property_number is not None:
            return build_photo_url(property_number)
        return None

    if not isinstance(url, str) or not url.strip():
        if property_number is not None:
            return build_photo_url(property_number)
        return None

    url = url.strip()

    # Already absolute HTTP(S) URL
    if url.startswith(("http://", "https://")):
        return url

    # Relative path starting with /
    if url.startswith("/"):
        return f"{BASE_URL}{url}"

    # Just a filename (e.g. "F123.jpg")
    if "/" not in url:
        return f"{PHOTO_URL_PREFIX}/{url}"

    # Some other relative path
    return f"{BASE_URL}/{url.lstrip('/')}"


def _collect_photos(raw: dict) -> list[str]:
    """Collect and normalize all photo URLs from a raw Caixa listing dict.

    Sources (in priority order):
    1. ``fotos`` — array of photo URLs (from Apify or scraper)
    2. ``imagens`` — fallback array
    3. ``image`` / ``foto_principal`` / ``image_url`` — single cover photo
    4. Construct from ``propertyNumber`` if no photos found

    Args:
        raw: Raw Caixa listing dict.

    Returns:
        Deduplicated list of absolute photo URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []

    candidates: list[str] = []

    # Source 1: fotos[] array
    raw_fotos = raw.get("fotos") or raw.get("photos") or []
    if isinstance(raw_fotos, list):
        for p in raw_fotos:
            normalized = _normalize_photo_url(p)
            if normalized:
                candidates.append(normalized)

    # Source 2: imagens[] fallback
    raw_imagens = raw.get("imagens") or raw.get("images") or []
    if isinstance(raw_imagens, list):
        for p in raw_imagens:
            normalized = _normalize_photo_url(p)
            if normalized:
                candidates.append(normalized)

    # Source 3: single image field
    single_image = _normalize_photo_url(
        raw.get("image") or raw.get("foto_principal") or raw.get("image_url"),
        property_number=raw.get("propertyNumber"),
    )
    if single_image:
        # Prioritize as first image (cover)
        urls.append(single_image)
        seen.add(single_image)

    # Add deduplicated candidates
    for url in candidates:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    # Source 4: construct from propertyNumber if we have nothing
    if not urls:
        prop_num = raw.get("propertyNumber")
        if prop_num is not None:
            constructed = build_photo_url(prop_num)
            if constructed:
                urls.append(constructed)

    return urls


# ── Price parsing ────────────────────────────────────────────────────────────

# Regex to extract numeric value from Brazilian price strings
# Examples: "R$ 450.000,00" -> 450000.00, "R$ 1.234.567,89" -> 1234567.89
_RE_BRL_PRICE = re.compile(r"(?:R\$\s*)?([\d.]+,\d{2})")


def _parse_br_price(price_str: Any) -> float | None:
    """Parse a Brazilian price value to float.

    Handles:
      - "R$ 450.000,00" -> 450000.00
      - "R$ 1.200.000,00" -> 1200000.00
      - "450000" (already numeric) -> 450000.00
      - 450000.00 (float) -> 450000.00
      - None / "0" / "" -> None

    Args:
        price_str: Raw price value (string or numeric).

    Returns:
        Float value in BRL, or None if not parseable.
    """
    if price_str is None:
        return None

    # Already a number
    if isinstance(price_str, (int, float)):
        return float(price_str) if float(price_str) != 0 else None

    if not isinstance(price_str, str):
        return None

    price_str = price_str.strip()
    if not price_str or price_str in ("0", "0,00", ""):
        return None

    # Try Brazilian format (with commas and dots)
    match = _RE_BRL_PRICE.search(price_str)
    if match:
        raw = match.group(1)
        # Brazilian format: 1.234.567,89 -> remove dots, replace comma with dot
        clean = raw.replace(".", "").replace(",", ".")
        try:
            return float(clean)
        except ValueError:
            pass

    # Try direct float conversion
    try:
        return float(price_str.replace("R$", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return None


# ── Main conversion functions ────────────────────────────────────────────────


def from_caixa_listing(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert a single Caixa listing dict to unified Imovel schema dict.

    Accepts data from any extraction method:
    - Apify actor output (structured JSON)
    - HTML detail page (extracted via Playwright/beautifulsoup)
    - CSV row (parsed from Caixa's CSV download)
    - Manual dict (for testing)

    The function:
    1. Maps fields via FIELD_MAP (supports multiple input key variants)
    2. Constructs a unique ID: ``caixa_{propertyNumber}``
    3. Normalizes photo URLs
    4. Parses Brazilian price strings
    5. Sets defaults for mandatory fields
    6. Returns the full mapped dict (includes both Imovel-standard fields
       and Caixa-specific fields prefixed with ``caixa_``)

    Args:
        raw: A single Caixa listing dict from any extraction method.

    Returns:
        Dict with both Imovel-standard fields and Caixa-specific fields
        (prefixed with ``caixa_``). None if the input is None or not a dict.
    """
    if raw is None or not isinstance(raw, dict):
        return None
    # Allow empty dict — return defaults

    mapped: dict[str, Any] = {}

    # ── Core fields via FIELD_MAP ────────────────────────────────────────
    # For each FIELD_MAP entry, try all the source key variants and use
    # the first non-None value found.
    for src_keys_str, dst_key in FIELD_MAP.items():
        # src_keys_str is the canonical key; try exact match first
        if src_keys_str in raw and raw[src_keys_str] is not None:
            mapped[dst_key] = raw[src_keys_str]

    # ── ID ───────────────────────────────────────────────────────────────
    origem_id = _to_str(mapped.get("origem_id", ""))
    if not origem_id:
        # Try raw origin fields
        origem_id = _to_str(raw.get("objectID") or raw.get("id") or raw.get("codigo", ""))
    if origem_id:
        mapped["id"] = f"{FONTE}_{origem_id}"
    else:
        mapped["id"] = ""
    mapped["origem_id"] = origem_id

    # ── Title ────────────────────────────────────────────────────────────
    titulo = _to_str(_safe_get(raw, "titulo", "title", "headline", "Título", "Titulo"))
    if not titulo:
        # Build a title from location + type
        tipo = _to_str(mapped.get("tipo", ""))
        bairro = _to_str(mapped.get("bairro", ""))
        cidade = _to_str(mapped.get("cidade", ""))
        parts = [p for p in [tipo, bairro, cidade] if p]
        titulo = f"Imóvel Caixa {' — '.join(parts)}" if parts else f"Imóvel Caixa #{origem_id}"
    mapped["titulo"] = titulo[:500]

    # ── Source ───────────────────────────────────────────────────────────
    mapped["fonte"] = FONTE

    # ── URL ──────────────────────────────────────────────────────────────
    raw_url = _to_str(mapped.get("url", ""))
    if not raw_url:
        raw_url = _to_str(_safe_get(raw, "Link de acesso", "link", "url"))
    if raw_url and not raw_url.startswith("http"):
        raw_url = f"{SEARCH_BASE}/{raw_url.lstrip('/')}" if raw_url.startswith("/") else raw_url
    mapped["url"] = raw_url

    # ── Photo URL normalization ──────────────────────────────────────────
    mapped["fotos"] = _collect_photos(raw)

    # ── Price parsing ────────────────────────────────────────────────────
    # preco_venda: try minimumSaleValue first, then preco/preco_venda fields
    if "preco_venda" not in mapped or mapped["preco_venda"] is None:
        mapped["preco_venda"] = _parse_br_price(
            _safe_get(raw, "minimumSaleValue", "Preço", "Preco", "preco", "preco_venda")
        )
    elif isinstance(mapped.get("preco_venda"), str):
        mapped["preco_venda"] = _parse_br_price(mapped["preco_venda"])

    # caixa_valor_avaliacao
    if "caixa_valor_avaliacao" in mapped and isinstance(mapped["caixa_valor_avaliacao"], str):
        mapped["caixa_valor_avaliacao"] = _parse_br_price(mapped["caixa_valor_avaliacao"])

    # caixa_desconto_percentual: handle BR format "40,31"
    if "caixa_desconto_percentual" in mapped and isinstance(mapped["caixa_desconto_percentual"], str):
        parsed_discount = _parse_br_price(mapped["caixa_desconto_percentual"])
        if parsed_discount is not None:
            mapped["caixa_desconto_percentual"] = parsed_discount

    # ── Tipo de venda (venda_direta vs leilao) ─────────────────────────
    caixa_modalidade = mapped.get("caixa_modalidade", "")
    if caixa_modalidade:
        tipo_venda = _derivar_tipo_venda(str(caixa_modalidade))
        if tipo_venda:
            mapped["caixa_tipo_venda"] = tipo_venda
    # Fallback: tentar raw dict
    if "caixa_tipo_venda" not in mapped:
        raw_modalidade = _safe_get(raw, "modality", "Modalidade de venda", "modalidade", "caixa_modalidade")
        tipo_venda = _derivar_tipo_venda(raw_modalidade)
        if tipo_venda:
            mapped["caixa_tipo_venda"] = tipo_venda

    # ── Type conversion for numeric fields ──────────────────────────────
    for num_field in ["preco_venda", "caixa_valor_avaliacao", "caixa_desconto_percentual",
                       "area", "latitude", "longitude"]:
        if num_field in mapped and mapped[num_field] is not None:
            mapped[num_field] = _to_float(mapped[num_field])

    for int_field in ["quartos", "vagas", "caixa_numero_item"]:
        if int_field in mapped and mapped[int_field] is not None:
            mapped[int_field] = _to_int(mapped[int_field])

    # ── Location ─────────────────────────────────────────────────────────
    # Ensure city/uf/bairro are strings
    mapped.setdefault("cidade", _to_str(_safe_get(raw, "city", "Cidade", "cidade")))
    mapped.setdefault("uf", _to_str(_safe_get(raw, "state", "UF", "estado", "uf")).upper()[:2])
    mapped.setdefault("bairro", _to_str(_safe_get(raw, "district", "Bairro", "bairro")))
    mapped.setdefault("endereco", _to_str(_safe_get(raw, "address", "Endereço", "Endereco", "endereco")))

    # ── Defaults ─────────────────────────────────────────────────────────
    mapped.setdefault("descricao", _to_str(_safe_get(raw, "description", "Descrição", "Descricao", "descricao")))
    mapped.setdefault("tipo", _to_str(_safe_get(raw, "propertyType", "Tipo", "Tipo de imóvel", "tipo_imovel", "tipo")))

    # ── Convert to Imovel if available ──────────────────────────────────
    # Note: Imovel.from_dict().to_dict() strips fields not in the dataclass
    # (like caixa_* prefixes). To preserve all fields, we merge the Imovel
    # standard fields with the extras from the full mapped dict.
    if Imovel is not None:
        try:
            imovel_instance = Imovel.from_dict(mapped)
            imovel_standard = imovel_instance.to_dict()
            # Merge: start with Imovel standard fields, overlay extras
            merged = dict(imovel_standard)
            for k, v in mapped.items():
                if k not in merged:
                    merged[k] = v
            return merged
        except Exception as e:
            logger.warning("Erro ao criar Imovel: %s", e)
            return mapped

    return mapped


def from_caixa_payload(raw: Any) -> list[dict[str, Any]]:
    """Convert a Caixa payload (list or dict) to list of unified Imovel dicts.

    Accepts:
    - List of dicts (each a single listing)
    - Dict with ``results``, ``listings``, or ``data`` key containing the list
    - Dict with ``hits`` key (Algolia-style response, for Apify compatibility)
    - String containing JSON

    Args:
        raw: The Caixa payload from any extraction method (Apify, CSV, HTML).

    Returns:
        List of dicts in unified Imovel schema. Empty list on invalid input.
    """
    # Accept string JSON
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    # Accept list directly
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        # Try common response wrappers
        items = (
            raw.get("results")
            or raw.get("listings")
            or raw.get("hits")
            or raw.get("data")
            or []
        )
        if isinstance(items, dict):
            # Nested: {"data": {"results": [...]}}
            items = items.get("results") or items.get("listings") or items.get("hits") or []
    else:
        logger.warning("Payload inesperado: esperava list/dict, recebeu %s", type(raw).__name__)
        return []

    if not isinstance(items, list):
        logger.warning("Payload sem array de resultados: %s", type(items).__name__)
        return []

    imoveis = []
    for item in items:
        imovel = from_caixa_listing(item)
        if imovel:
            imoveis.append(imovel)

    logger.info("Parsed %d listings from Caixa payload", len(imoveis))
    return imoveis


# ── Apify integration placeholder ────────────────────────────────────────────

# Apify actors available for Caixa property data:
#
# 1. pizani/caixa-imoveis-leiloes-api ($10/month)
#    - Search by state/city/modalidade
#    - 5.0 stars
#    - Returns structured JSON with property details
#    - Best value for basic listing data
#
# 2. leadercorp/caixa-leiloes-scraper (from $5/1000 results)
#    - Most comprehensive (detail page scraping)
#    - Returns full property descriptions, auction dates, etc.
#    - Pay-per-result model
#
# 3. brasil-scrapers/caixa-leiloes-api ($25/month)
#    - Full detail scraping including images
#    - 5.0 stars
#
# 4. brasildados/ia-leilao-caixa-api ($15/1000 results)
#    - Includes AI market value estimation
#    - Most expensive but adds valuation data
#
# Integration pattern (using Apify Python client):
#
#   from apify_client import ApifyClient
#
#   client = ApifyClient("YOUR_APIFY_TOKEN")
#   run = client.actor("pizani/caixa-imoveis-leiloes-api").call(
#       run_input={
#           "estado": "SP",
#           "cidade": "SAO PAULO",
#           "modalidade": 33,  # Venda Online
#       }
#   )
#   dataset = client.dataset(run["defaultDatasetId"])
#   items = dataset.list_items().items
#   imoveis = from_caixa_payload(items)


def fetch_via_apify(
    apify_token: str,
    actor_id: str = "pizani/caixa-imoveis-leiloes-api",
    run_input: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch Caixa property listings via Apify actor.

    This is a PLACEHOLDER function that documents the Apify integration
    pattern. Apify actors handle Radware Bot Manager + hCaptcha bypass
    using their residential proxy infrastructure.

    Args:
        apify_token: Apify API token (get from https://console.apify.com).
        actor_id: Apify actor ID. Recommended:
            - "pizani/caixa-imoveis-leiloes-api" ($10/month, best value)
            - "leadercorp/caixa-leiloes-scraper" ($5/1000 results, most detailed)
            - "brasil-scrapers/caixa-leiloes-api" ($25/month, full detail)
        run_input: Actor run input dict. Defaults to searching SP state.

    Returns:
        List of dicts in unified Imovel schema.

    Raises:
        ImportError: If ``apify_client`` is not installed.
        RuntimeError: If the Apify run fails.

    Example usage:
        >>> imoveis = fetch_via_apify(
        ...     apify_token="apify_api_...",
        ...     actor_id="pizani/caixa-imoveis-leiloes-api",
        ...     run_input={"estado": "SP", "cidade": "SAO PAULO"},
        ... )
        >>> print(f"Found {len(imoveis)} properties")
    """
    try:
        from apify_client import ApifyClient
    except ImportError:
        raise ImportError(
            "Apify client not installed. Install with: pip install apify-client"
        )

    if run_input is None:
        run_input = {
            "estado": "SP",
            "cidade": "SAO PAULO",
        }

    client = ApifyClient(apify_token)

    logger.info(
        "Starting Apify actor '%s' with input: %s",
        actor_id,
        json.dumps(run_input, ensure_ascii=False),
    )

    try:
        run = client.actor(actor_id).call(run_input=run_input)
    except Exception as e:
        raise RuntimeError(
            f"Apify actor call failed for '{actor_id}': {e}"
        )

    if run.get("status") == "FAILED":
        raise RuntimeError(
            f"Apify actor '{actor_id}' failed: "
            f"{run.get('statusMessage', 'Unknown error')}"
        )

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError(
            f"Apify actor '{actor_id}' returned no dataset ID"
        )

    dataset = client.dataset(dataset_id)
    items = dataset.list_items().items

    logger.info("Apify returned %d raw items", len(items))

    return from_caixa_payload(items)


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI for testing the Caixa parser directly."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Caixa Imóveis Parser — teste e validação"
    )
    sub = parser.add_subparsers(dest="command")

    # parse: parse a JSON file of Caixa listings
    parse_parser = sub.add_parser(
        "parse", help="Parseia um arquivo JSON de listagens Caixa"
    )
    parse_parser.add_argument("input_file", help="Caminho do arquivo JSON")
    parse_parser.add_argument(
        "--output", "-o", help="Salvar resultado parseado em arquivo JSON"
    )

    # photo: build photo URLs from property number
    photo_parser = sub.add_parser(
        "photo", help="Constrói URL de foto a partir do número do imóvel"
    )
    photo_parser.add_argument("property_number", help="Número do imóvel Caixa")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.command == "parse":
        with open(args.input_file) as f:
            data = json.load(f)
        imoveis = from_caixa_payload(data)
        print(f"Parseados {len(imoveis)} imóveis de {args.input_file}")
        if imoveis:
            sample = imoveis[0]
            print(f"  Amostra: {sample.get('titulo', 'N/I')} — "
                  f"R$ {sample.get('preco_venda', 'N/I')} — "
                  f"{sample.get('cidade', 'N/I')}/{sample.get('uf', 'N/I')}")
            print(f"  Fotos: {len(sample.get('fotos', []))}")
        if args.output and imoveis:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    elif args.command == "photo":
        url = build_photo_url(args.property_number)
        if url:
            print(f"Property:   {args.property_number}")
            print(f"Photo URL:  {url}")
        else:
            print(f"Não foi possível construir URL a partir de: {args.property_number}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
