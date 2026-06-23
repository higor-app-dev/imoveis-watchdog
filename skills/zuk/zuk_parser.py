"""
zuk_parser — Extractor do Portal Zuk (portalzuk.com.br) para o schema unificado Imovel.

Portal Laravel server-rendered (NÃO SPA) com ~1008 imóveis em 24 UF.
Proteção Cloudflare — requer User-Agent de navegador real.

## Estratégia Combinada (Recomendada)

1. **Listagem HTML** — extrai cards `.card-property` (título, endereço, preços, datas, imagem)
2. **Inline JSON `properties`** — extrai array JavaScript com dados estruturados (lat/lng, valor
   avaliação, áreas, tipo flags)
3. **Correlação** — pelo `ilo` (lote ID) entre HTML cards e JSON properties

## Fontes de Dados por Campo

| Campo | Fonte |
|-------|-------|
| título | `.card-property-price-lote` (HTML) |
| endereço | `.card-property-address` (HTML) |
| valor_avaliação | `properties[].lv` (inline JSON) |
| valor_1a_praca | `.card-property-price-value` com line-through (HTML) |
| valor_2a_praca | `.card-property-price-value` sem line-through (HTML) |
| data_1a_praca | `.card-property-price-data` com line-through (HTML) |
| data_2a_praca | `.card-property-price-data` sem line-through (HTML) |
| image_urls | `img` src em `.card-property-image-wrapper` (HTML) |
| latitude/longitude | `properties[].la`, `properties[].lo` (inline JSON) |
| areas | `properties[].a_uti`, `a_pri`, `a_con`, `a_ter`, `a_tot` (inline JSON) |
| tipo_flags | `properties[].i_res`, `i_com`, `i_rur`, `i_ter` (inline JSON) |
| desconto | `properties[].i_abaixo` (inline JSON) |

## URLs

- Listagem: `https://www.portalzuk.com.br/leilao-de-imoveis?page=N`
- Detalhe: `https://www.portalzuk.com.br/imovel/{uf}/{cidade}/{bairro}/{rua}/{leilaoId}-{loteId}`
- Imagens: `https://imagens.portalzuk.com.br/{tamanho}/{ano}/{mes}/{hash}.{ext}`
  - `/mini/` = thumbnail (~200px), `/detalhe/` = full (~800px), `.webp` padrão

Funções:
    from_zuk_listing(html_card, inline_props, coleta_ts) -> dict | None
    from_zuk_payload(raw) -> list[dict]
    extract_from_html(html, source_url) -> tuple[list[dict], dict]
    extract_listing_page(url, timeout, headers) -> list[dict]
    crawl_listing(start_url, pages, rate_limit, timeout) -> list[dict]
    build_listing_url(uf, cidade, page) -> str
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup, Tag

# Schema unificado
sys.path.insert(0, str(Path.home() / ".hermes"))
try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None  # Fallback: returns dict

logger = logging.getLogger("zuk_parser")

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://www.portalzuk.com.br"
IMAGE_BASE = "https://imagens.portalzuk.com.br"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

DEFAULT_TIMEOUT = 30  # seconds
ITEMS_PER_PAGE = 30

# ── Safe type converters ─────────────────────────────────────────────────────


def _to_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    """Convert a value to float safely."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _to_int(val: Any, default: Optional[int] = None) -> Optional[int]:
    """Convert a value to int safely."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _as_str(val: Any, default: str = "") -> str:
    """Convert a value to string safely."""
    if val is None:
        return default
    return str(val).strip()


def _as_list(val: Any) -> list:
    """Convert a value to list safely."""
    if isinstance(val, list):
        return val
    if val is None:
        return []
    return []


# ── Price parsing ────────────────────────────────────────────────────────────


def _parse_br_price(text: str) -> Optional[float]:
    """Parse Brazilian-format price string like 'R$ 450.000,00' or 'R$ 1.200.000'.

    Returns float value or None.
    """
    if not text:
        return None
    # Remove 'R$', 'R$ ', etc.
    cleaned = re.sub(r"[Rr]\$\s*", "", text)
    cleaned = cleaned.strip()
    # Detect format: if has comma as decimal separator (BR format)
    if "," in cleaned and "." in cleaned:
        # BR format: 1.200.000,00 -> remove dots, replace comma with dot
        # Last comma is decimal separator
        parts = cleaned.rsplit(",", 1)
        integer_part = parts[0].replace(".", "")
        decimal_part = parts[1]
        cleaned = f"{integer_part}.{decimal_part}"
    elif "," in cleaned:
        # Simple comma as decimal: 450000,00 -> 450000.00
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        # Multiple dots: 1.200.000 -> 1200000 (thousands separators)
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


# ── Photo URL normalization (CDN de imagens.portalzuk.com.br) ─────────────────

def _normalize_photo_url(url: Any) -> str | None:
    """Normalize a Zuk photo URL to an absolute detalhe (full) CDN URL.

    Zuk CDN pattern: imagens.portalzuk.com.br/{size}/{year}/{month}/{hash}.{ext}
    - Mini thumbnails:  /mini/2025/01/abc123.jpg  (~29KB)
    - Full images:      /detalhe/2025/01/abc123.jpg (~138KB)

    This function:
    - Accepts relative mini URLs, relative URLs without size prefix,
      dicts with 'url' keys, or already-absolute URLs.
    - Converts mini -> detalhe (full resolution).
    - Prepends CDN base for relative URLs.

    Args:
        url: Raw photo value (string URL, dict with 'url' key, or None).

    Returns:
        Absolute detalhe URL string, or None if invalid.
    """
    if not url:
        return None
    # Dict format (e.g. {'url': '/mini/2025/01/abc123.jpg'})
    if isinstance(url, dict):
        url = url.get("url") or url.get("src") or None
        if not url:
            return None
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()

    # Already absolute HTTP(S) URL
    if url.startswith("http://") or url.startswith("https://"):
        # If it's already a detalhe URL, return as-is
        if "/detalhe/" in url:
            return url
        # If it's a mini URL, convert to detalhe
        if "/mini/" in url:
            return url.replace("/mini/", "/detalhe/")
        # If it's from imagens.portalzuk.com.br but unknown size, assume full
        if "imagens.portalzuk.com.br" in url:
            return url
        # External URL (e.g. og:image fallback) — pass through
        return url

    # Relative URL starting with /
    if url.startswith("/"):
        # Convert /mini/... to full detalhe absolute URL
        clean_path = url.lstrip("/")
        if clean_path.startswith("mini/"):
            clean_path = "detalhe/" + clean_path[5:]
        return f"{IMAGE_BASE}/{clean_path}"

    # Plain filename — unlikely for Zuk but handle gracefully
    return f"{IMAGE_BASE}/{url.lstrip('/')}"


def _collect_photos(raw: dict) -> list[str]:
    """Collect and normalize all photo URLs from a raw Zuk listing dict.

    Sources (in priority order):
    1. `image_urls` — array of raw image URL strings from card HTML extraction
    2. `image_url` — single image URL (string or dict)
    3. `fotos` / `imagens` — fallback keys for legacy or detail-page data

    All photos are converted to absolute detalhe CDN URLs.

    Args:
        raw: Parsed Zuk listing dict.

    Returns:
        Deduplicated list of absolute detalhe CDN URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []

    candidates: list[str] = []

    # Source 1: image_urls array (most common from HTML card extraction)
    raw_image_urls = raw.get("image_urls") or []
    if isinstance(raw_image_urls, list):
        for item in raw_image_urls:
            normalized = _normalize_photo_url(item)
            if normalized:
                candidates.append(normalized)

    # Source 2: image_url (single image from card)
    raw_image_url = raw.get("image_url")
    if raw_image_url:
        normalized = _normalize_photo_url(raw_image_url)
        if normalized:
            candidates.append(normalized)

    # Source 3: fotos / imagens (detail page or alternative format)
    for fallback_key in ("fotos", "imagens", "photos"):
        raw_fallback = raw.get(fallback_key, [])
        if isinstance(raw_fallback, list):
            for item in raw_fallback:
                normalized = _normalize_photo_url(item)
                if normalized:
                    candidates.append(normalized)

    # Deduplicate preserving order
    for url in candidates:
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


# ── Inline JSON extraction ────────────────────────────────────────────────────


def _extract_inline_properties(html: str) -> list[dict]:
    """Extract the `properties` array from inline JavaScript in the HTML.

    In the listing page, each property is embedded as:
        var properties = [{...}, {...}, ...];

    Args:
        html: Raw HTML string of the listing page.

    Returns:
        List of property dicts with keys: il, ilo, la, lo, lv, areas, flags, etc.
    """
    # Pattern 1: var properties = [...];
    pattern = r"var\s+properties\s*=\s*(\[.*?\])\s*;"
    match = re.search(pattern, html, re.DOTALL)
    if match:
        try:
            properties = json.loads(match.group(1))
            if isinstance(properties, list):
                return properties
        except json.JSONDecodeError:
            pass

    # Pattern 2: window.properties = [...];
    pattern2 = r"window\.properties\s*=\s*(\[.*?\])\s*;"
    match = re.search(pattern2, html, re.DOTALL)
    if match:
        try:
            properties = json.loads(match.group(1))
            if isinstance(properties, list):
                return properties
        except json.JSONDecodeError:
            pass

    return []


def _build_props_index(properties: list[dict]) -> dict[int, dict]:
    """Build an index of inline properties by lote ID (ilo).

    Args:
        properties: List of property dicts from inline JS.

    Returns:
        Dict mapping ilo (lote ID) -> property dict.
    """
    index: dict[int, dict] = {}
    for prop in properties:
        ilo = _to_int(prop.get("ilo"))
        if ilo:
            index[ilo] = prop
    return index


# ── HTML card extraction ─────────────────────────────────────────────────────


def _extract_lote_id_from_card(card: Tag) -> Optional[int]:
    """Extract the lote ID from a card-property element.

    The lote ID appears in:
    - `<span id="{id}">` inside favorite span
    - `id="{id}"` on any descendant element
    - URL of the link: `/imovel/.../{leilaoId}-{loteId}`

    Args:
        card: BeautifulSoup Tag for the card-property div.

    Returns:
        Lote ID integer or None.
    """
    # Try ID from span elements
    for span in card.find_all("span"):
        span_id = span.get("id", "")
        if span_id and span_id.isdigit():
            return int(span_id)
    # Try from href
    link = card.find("a", href=True)
    if link:
        href = link["href"]
        # Pattern: /imovel/.../{leilaoId}-{loteId}
        m = re.search(r"-(\d+)$", href)
        if m:
            return int(m.group(1))
    return None


def _extract_card_title(card: Tag) -> str:
    """Extract the title from a card-property."""
    title_el = card.select_one(".card-property-price-lote")
    if title_el:
        return title_el.get_text(strip=True)

    # Fallback: try h2 or any heading
    heading = card.find(["h2", "h3", "h4"])
    if heading:
        return heading.get_text(strip=True)

    return ""


def _extract_card_address(card: Tag) -> str:
    """Extract full address from a card-property."""
    addr_el = card.select_one(".card-property-address")
    if addr_el:
        return addr_el.get_text(" ", strip=True)

    # Fallback: look for address patterns
    for p in card.find_all(["p", "span"]):
        text = p.get_text(strip=True)
        if text and (
            "/" in text
            or any(
                uf in text
                for uf in [
                    "SP", "RJ", "MG", "RS", "PR", "SC",
                    "BA", "DF", "GO", "ES", "MT", "MS",
                    "CE", "PE", "AL", "RN", "PB", "SE",
                    "PI", "MA", "PA", "AM", "RO", "AC",
                    "AP", "RR", "TO",
                ]
            )
        ):
            return text

    return ""


def _extract_card_prices(card: Tag) -> dict[str, Any]:
    """Extract prices from a card-property.

    Returns dict with:
        preco_1a_praca: Optional[float] — preço riscado (1ª praça)
        preco_2a_praca: Optional[float] — preço atual (2ª praça)
    """
    result: dict[str, Any] = {
        "preco_1a_praca": None,
        "preco_2a_praca": None,
    }

    price_elements = card.select(".card-property-price-value")
    prices = []
    for el in price_elements:
        # Get only the element's direct text, excluding child elements
        # (the percent badge is nested inside the price element)
        direct_text = ""
        for child in el.children:
            if isinstance(child, str):
                direct_text += child.strip()
            elif child.name == "span" and "card-property-price-percent" in child.get("class", []):
                continue  # skip the percentage badge
            else:
                # If it's not the percent badge, get its text too
                if not isinstance(child, str):
                    child_text = child.get_text(strip=True)
                    if child_text:
                        direct_text += " " + child_text
        text = direct_text.strip()
        price = _parse_br_price(text)
        if price:
            style = el.get("style", "") or ""
            parent_style = ""
            if el.parent:
                parent_style = el.parent.get("style", "") or ""
            is_strikethrough = (
                "line-through" in style
                or "text-decoration:line-through" in style.replace(" ", "")
                or "line-through" in parent_style
            )
            prices.append((price, is_strikethrough))

    if prices:
        st_prices = [p for p, s in prices if s]
        reg_prices = [p for p, s in prices if not s]
        if st_prices:
            result["preco_1a_praca"] = st_prices[0]
        if reg_prices:
            result["preco_2a_praca"] = reg_prices[0]
        elif not st_prices and len(prices) >= 1:
            result["preco_1a_praca"] = prices[0][0]

    return result


def _extract_card_dates(card: Tag) -> dict[str, str]:
    """Extract auction dates from a card-property.

    Returns dict with:
        data_1a_praca: str — date with strikethrough if passed
        data_2a_praca: str — current/open date
    """
    result: dict[str, str] = {
        "data_1a_praca": "",
        "data_2a_praca": "",
    }

    date_elements = card.select(".card-property-price-data")
    dates = []
    for el in date_elements:
        text = el.get_text(strip=True)
        if not text:
            continue
        style = el.get("style", "") or ""
        parent_style = ""
        if el.parent:
            parent_style = el.parent.get("style", "") or ""
        is_strikethrough = (
            "line-through" in style
            or "text-decoration:line-through" in style.replace(" ", "")
            or "line-through" in parent_style
        )
        dates.append((text, is_strikethrough))

    if dates:
        st_dates = [d for d, s in dates if s]
        reg_dates = [d for d, s in dates if not s]
        if st_dates:
            result["data_1a_praca"] = st_dates[0]
        if reg_dates:
            result["data_2a_praca"] = reg_dates[0]
        elif not st_dates and len(dates) >= 1:
            result["data_1a_praca"] = dates[0][0]

    return result


def _extract_card_image_url(card: Tag) -> Optional[str]:
    """Extract the thumbnail image URL from a card-property.

    Returns the raw URL string (may be mini-size relative URL).
    """
    img = card.select_one(".card-property-image-wrapper img")
    if img:
        src = img.get("src", "")
        if src:
            if src.startswith("http"):
                return src
            return f"{BASE_URL}{src}" if src.startswith("/") else f"{BASE_URL}/{src}"

    # Fallback: any img with reasonable URL
    for img in card.find_all("img"):
        src = img.get("src", "")
        if src and ("imagens.portalzuk" in src or src.startswith("http")):
            return src if src.startswith("http") else f"{BASE_URL}{src}"

    return None


def _extract_card_images(card: Tag) -> list[str]:
    """Extract all image URLs from a card-property."""
    img_url = _extract_card_image_url(card)
    if img_url:
        return [img_url]
    return []


def _extract_card_link(card: Tag) -> str:
    """Extract the detail page URL from a card-property."""
    link = card.select_one("a")
    if link:
        href = link.get("href", "")
        if href:
            if href.startswith("http"):
                return href
            return f"{BASE_URL}{href}" if href.startswith("/") else f"{BASE_URL}/{href}"
    return ""


def _extract_card_percent(card: Tag) -> Optional[float]:
    """Extract the discount percentage from a card."""
    percent_el = card.select_one(".card-property-price-percent")
    if percent_el:
        text = percent_el.get_text(strip=True)
        m = re.search(r"([\d,.]+)", text)
        if m:
            return _to_float(m.group(1).replace(",", "."))
    return None


def _parse_card(card: Tag) -> dict:
    """Parse a single card-property div into a structured dict.

    Args:
        card: BeautifulSoup Tag for the card-property div.

    Returns:
        Dict with extracted fields.
    """
    lote_id = _extract_lote_id_from_card(card)

    result = {
        "ilo": lote_id,
        "titulo": _extract_card_title(card),
        "endereco": _extract_card_address(card),
        "url": _extract_card_link(card),
        "image_urls": _extract_card_images(card),
        "percentual_desconto": _extract_card_percent(card),
    }

    # Prices and dates
    result.update(_extract_card_prices(card))
    result.update(_extract_card_dates(card))

    return result


# ── Main extraction from HTML ────────────────────────────────────────────────


def extract_from_html(
    html: str,
    source_url: str = "",
) -> tuple[list[dict], dict]:
    """Extract all listings from a Zuk listing page HTML.

    Combines card-property HTML extraction with inline properties JSON.

    Args:
        html: Raw HTML of the Zuk listing page.
        source_url: URL of the page (for metadata and link resolution).

    Returns:
        Tuple of (listings_list, metadata_dict).
        metadata includes total listing count, page info, etc.
    """
    soup = BeautifulSoup(html, "html.parser")

    # 1. Extract inline properties JSON
    inline_props = _extract_inline_properties(html)
    props_index = _build_props_index(inline_props)

    logger.info(
        f"Found {len(inline_props)} inline properties, "
        f"{len(props_index)} with valid ilo"
    )

    # 2. Parse card-property elements
    cards = soup.select(".card-property")
    if not cards:
        # Fallback: look for any listing-like cards
        cards = soup.select("[class*=card]")

    logger.info(f"Found {len(cards)} card elements on page")

    listings: list[dict] = []
    for card in cards:
        parsed = _parse_card(card)
        if not parsed.get("titulo") and not parsed.get("ilo"):
            continue  # Skip empty cards

        # 3. Merge with inline properties data by ilo
        ilo = parsed.get("ilo")
        if ilo and ilo in props_index:
            prop = props_index[ilo]
            # Add structured data from inline JSON
            parsed["latitude"] = _to_float(prop.get("la"))
            parsed["longitude"] = _to_float(prop.get("lo"))
            parsed["valor_avaliacao"] = _to_float(prop.get("lv"))
            parsed["i_abaixo"] = _to_float(prop.get("i_abaixo"))
            parsed["parcelas"] = _to_int(prop.get("i_parcelas"))

            # Areas
            areas = {}
            for area_key in ["a_uti", "a_pri", "a_con", "a_ter", "a_tot"]:
                val = prop.get(area_key)
                if val is not None:
                    areas[area_key] = _to_float(val)
            parsed["areas"] = areas

            # Type flags
            for flag in ["i_res", "i_com", "i_rur", "i_ter", "i_out"]:
                val = prop.get(flag)
                if val is not None:
                    parsed[flag] = bool(val)

            # Lease info
            parsed["i_loc"] = prop.get("i_loc")
            parsed["i_ocu"] = prop.get("i_ocu")

        # 4. Infer type from title if possible
        parsed["tipo_inferido"] = _infer_tipo(
            parsed.get("titulo", ""),
            parsed.get("i_res"),
            parsed.get("i_com"),
            parsed.get("i_rur"),
            parsed.get("i_ter"),
        )

        listings.append(parsed)

    # 5. Pagination info from URL or page
    page_num = 1
    m = re.search(r"[?&]page=(\d+)", source_url)
    if m:
        page_num = int(m.group(1))

    metadata = {
        "page": page_num,
        "listings_found": len(listings),
        "inline_properties": len(inline_props),
        "cards_parsed": len(cards),
        "source_url": source_url,
    }

    return listings, metadata


def _infer_tipo(
    titulo: str,
    i_res: Any = None,
    i_com: Any = None,
    i_rur: Any = None,
    i_ter: Any = None,
) -> str:
    """Infer property type from title + type flags.

    Args:
        titulo: Property title text.
        i_res: Residential flag.
        i_com: Commercial flag.
        i_rur: Rural flag.
        i_ter: Land flag.

    Returns:
        Normalized type string.
    """
    # Try flags first
    if i_ter:
        return "terreno"
    if i_rur:
        return "rural"
    if i_com and not i_res:
        return "comercial"
    if i_res:
        return "residencial"

    # Infer from title
    if not titulo:
        return ""

    title_lower = titulo.lower().strip()

    tipo_map = [
        ("terreno", "terreno"),
        ("casa", "casa"),
        ("apartamento", "apartamento"),
        ("kitnet", "kitnet"),
        ("studio", "studio"),
        ("loft", "loft"),
        ("flat", "flat"),
        ("cobertura", "cobertura"),
        ("sobrado", "sobrado"),
        ("comercial", "comercial"),
        ("sala", "comercial"),
        ("rural", "rural"),
        ("prédio", "predio"),
        ("predio", "predio"),
        ("galpão", "comercial"),
        ("galpao", "comercial"),
    ]

    for keyword, tipo in tipo_map:
        if keyword in title_lower:
            return tipo

    return title_lower


# ── HTTP fetch ────────────────────────────────────────────────────────────────


def _session() -> requests.Session:
    """Create a requests session with default headers."""
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


def fetch_page(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict | None = None,
) -> str:
    """Fetch a Zuk listing page HTML.

    Args:
        url: Full URL of the listing page.
        timeout: Request timeout in seconds.
        headers: Optional override headers.

    Returns:
        Raw HTML string.

    Raises:
        requests.RequestException: On HTTP errors or timeouts.
    """
    sess = _session()
    if headers:
        sess.headers.update(headers)

    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()

    # Check for Cloudflare challenge
    if "Just a moment" in resp.text or "cf-browser-verification" in resp.text:
        logger.warning("Cloudflare challenge detected — browser tool may be needed")

    return resp.text


# ── Public extraction API ─────────────────────────────────────────────────────


def extract_listing_page(
    url: str = f"{BASE_URL}/leilao-de-imoveis",
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict | None = None,
) -> list[dict]:
    """Fetch and parse a single Zuk listing page.

    Args:
        url: Full listing URL. Defaults to main listing page.
        timeout: HTTP request timeout.
        headers: Optional override headers.

    Returns:
        List of parsed listing dicts (raw, before Imovel conversion).

    Raises:
        requests.RequestException: On HTTP errors.
    """
    html = fetch_page(url, timeout=timeout, headers=headers)
    listings, meta = extract_from_html(html, source_url=url)
    logger.info(
        f"Page {meta['page']}: {meta['listings_found']} listings from "
        f"{meta['cards_parsed']} cards"
    )
    return listings


def crawl_listing(
    start_url: str = f"{BASE_URL}/leilao-de-imoveis",
    pages: int = 1,
    rate_limit: float = 1.5,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[list[dict], dict]:
    """Crawl multiple pages of Zuk listings.

    Starts from the given URL and follows ?page=N pagination.
    Stops early if a page returns zero listings.

    Args:
        start_url: Starting URL (default: main listing page).
        pages: Maximum number of pages to fetch.
        rate_limit: Seconds between requests (default: 1.5).
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (all_listings, crawl_metadata).
    """
    all_listings: list[dict] = []
    total_pages = 0
    errors = 0

    for page_num in range(1, pages + 1):
        # Build page URL
        if "?" in start_url:
            page_url = re.sub(r"[?&]page=\d+", "", start_url)
            sep = "&" if "?" in page_url else "?"
            page_url = f"{page_url}{sep}page={page_num}"
        else:
            page_url = f"{start_url}?page={page_num}"

        if page_num > 1 and rate_limit > 0:
            logger.info(f"Rate limit: waiting {rate_limit}s...")
            time.sleep(rate_limit)

        try:
            logger.info(f"Fetching page {page_num}: {page_url}")
            page_listings = extract_listing_page(url=page_url, timeout=timeout)
        except Exception as e:
            logger.warning(f"Page {page_num} failed: {type(e).__name__}: {e}")
            errors += 1
            page_listings = []

        total_pages = page_num
        if page_listings:
            all_listings.extend(page_listings)
        else:
            logger.info(f"Stopping at page {page_num} — no listings found")
            break

    metadata = {
        "pages_fetched": total_pages,
        "pages_requested": pages,
        "total_listings": len(all_listings),
        "errors": errors,
        "start_url": start_url,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        f"Crawl complete: {len(all_listings)} listings across "
        f"{total_pages} pages ({errors} errors)"
    )
    return all_listings, metadata


# ── FIELD_MAP: raw fields -> unified Imovel schema ───────────────────────────

# Maps raw parsed field names (from _parse_card + inline JSON merge)
# to the unified Imovel schema field names.
FIELD_MAP = {
    "ilo": "origem_id",
    "titulo": "titulo",
    "endereco": "endereco",
    "url": "url",
    "preco_2a_praca": "preco_venda",
    "preco_1a_praca": "preco_anterior",
    "percentual_desconto": "percentual_reducao",
    "latitude": "latitude",
    "longitude": "longitude",
    "valor_avaliacao": "valor_avaliacao",
    "data_1a_praca": "data_1a_praca",
    "data_2a_praca": "data_2a_praca",
    "parcelas": "parcelas",
    "tipo_inferido": "tipo",
    "i_abaixo": "i_abaixo",
    "i_loc": "i_loc",
    "i_ocu": "i_ocu",
    "i_res": "i_res",
    "i_com": "i_com",
    "i_rur": "i_rur",
    "i_ter": "i_ter",
}


# ── Conversion to Imovel schema ──────────────────────────────────────────────


def _build_zuk_id(listing: dict) -> str:
    """Build a unique ID for a Zuk listing."""
    ilo = listing.get("ilo")
    if ilo:
        return f"zuk_{ilo}"
    # Fallback: hash of URL
    url = listing.get("url", "")
    if url:
        m = re.search(r"(\d+)-(\d+)$", url)
        if m:
            return f"zuk_{m.group(2)}"
    return ""


def from_zuk_listing(
    listing: dict,
    coleta_ts: str | None = None,
) -> dict | Any | None:
    """Convert a parsed Zuk listing dict to the unified Imovel schema.

    Uses FIELD_MAP for field name translation and _collect_photos for
    CDN-normalized photo URLs.

    Args:
        listing: Parsed listing dict from extract_from_html or
                 extract_listing_page.
        coleta_ts: ISO timestamp. Auto-generated if omitted.

    Returns:
        Imovel (if available) or dict in unified schema.
        None if the input is invalid.
    """
    if not listing or not isinstance(listing, dict):
        return None

    now = coleta_ts or datetime.now(timezone.utc).isoformat()
    imovel_id = _build_zuk_id(listing)
    if not imovel_id:
        logger.warning("Listing without identifiable ID — skipping")
        return None

    # Apply FIELD_MAP: translate known fields
    mapped: dict[str, Any] = {}
    for src_key, dst_key in FIELD_MAP.items():
        if src_key in listing and listing[src_key] is not None:
            mapped[dst_key] = listing[src_key]

    # ── Photo URL normalization ──────────────────────────────────────────
    mapped["fotos"] = _collect_photos(listing)

    # ── Set static / computed fields ─────────────────────────────────────
    mapped["id"] = imovel_id
    mapped["fonte"] = "zuk"
    mapped["negociacao"] = "leilao"
    mapped["disponivel"] = True
    mapped["data_coleta"] = now
    mapped["preco_aluguel"] = None
    mapped["condominio"] = None
    mapped["iptu"] = None
    mapped["quartos"] = None
    mapped["banheiros"] = None
    mapped["vagas"] = None
    mapped["descricao"] = ""

    # Parse endereço into components
    endereco_full = listing.get("endereco", "")
    mapped["endereco"], mapped["bairro"], mapped["cidade"], mapped["uf"] = _parse_address(
        endereco_full
    )

    # Use 1ª praça as preco_anterior (already mapped via FIELD_MAP)
    # Ensure preco_venda has a fallback
    if mapped.get("preco_venda") is None:
        mapped["preco_venda"] = listing.get("preco_1a_praca") or listing.get("valor_avaliacao")

    # ── Area (from inline areas dict) ────────────────────────────────────
    area = None
    areas = listing.get("areas", {}) or {}
    if isinstance(areas, dict):
        area = (
            _to_float(areas.get("a_tot"))
            or _to_float(areas.get("a_uti"))
            or _to_float(areas.get("a_pri"))
            or _to_float(areas.get("a_con"))
            or _to_float(areas.get("a_ter"))
        )
    mapped["area"] = area

    # ── tem_reducao / percentual_reducao ─────────────────────────────────
    reducao_pct = mapped.get("percentual_reducao")
    mapped["tem_reducao"] = bool(reducao_pct and reducao_pct > 0)
    if not mapped.get("percentual_reducao"):
        # Try inline i_abaixo as fallback discount
        i_abaixo = listing.get("i_abaixo")
        if i_abaixo is not None:
            mapped["percentual_reducao"] = _to_float(i_abaixo)
            mapped["tem_reducao"] = bool(mapped["percentual_reducao"] and mapped["percentual_reducao"] > 0)

    # ── Convert types ────────────────────────────────────────────────────
    for num_field in [
        "preco_venda", "preco_anterior", "condominio", "iptu",
        "area", "latitude", "longitude", "percentual_reducao", "valor_avaliacao",
    ]:
        if num_field in mapped and mapped[num_field] is not None:
            try:
                mapped[num_field] = float(mapped[num_field])
            except (ValueError, TypeError):
                mapped[num_field] = None

    for int_field in ["quartos", "suites", "banheiros", "vagas", "andar", "parcelas"]:
        if int_field in mapped and mapped[int_field] is not None:
            try:
                mapped[int_field] = int(mapped[int_field])
            except (ValueError, TypeError):
                mapped[int_field] = None

    # ── Preserve extra Zuk fields ────────────────────────────────────────
    extra_fields = {}
    for key in [
        "ilo", "parcelas", "i_loc", "i_ocu",
        "i_res", "i_com", "i_rur", "i_ter", "i_out",
        "areas", "data_1a_praca", "data_2a_praca",
        "preco_1a_praca", "preco_2a_praca", "i_abaixo",
        "valor_avaliacao", "modalidade", "data_leilao",
        "image_urls",
    ]:
        if key in listing and listing[key] is not None:
            extra_fields[key] = listing[key]

    # Try to create Imovel instance
    if Imovel is not None:
        try:
            # Filter only fields known to Imovel
            imovel_kwargs = {
                k: v for k, v in mapped.items()
                if k in Imovel.__dataclass_fields__
            }
            imovel = Imovel.from_dict(imovel_kwargs)
            imovel._extra = extra_fields  # type: ignore[attr-defined]
            result = imovel.to_dict()
            # Merge all mapped fields that are not in Imovel schema
            # (preserves valor_avaliacao, preco_anterior, data_1a_praca, etc.)
            imovel_fields = set(Imovel.__dataclass_fields__.keys())
            for k, v in mapped.items():
                if k not in imovel_fields and v is not None:
                    result[k] = v
            # Also merge extra_fields values not covered by mapped
            for k in extra_fields:
                if k not in result or result[k] is None:
                    result[k] = extra_fields[k]
            return result
        except Exception as e:
            logger.warning(f"Erro ao criar Imovel: {e}")
            return mapped

    # Include extra in plain dict
    if extra_fields:
        mapped["_extra"] = extra_fields
    return mapped


def from_zuk_payload(
    payload: Any,
) -> list[dict]:
    """Convert a batch of Zuk listings to unified schema.

    Accepts:
      - List of parsed listing dicts
      - Dict with 'listings' key
      - String containing JSON

    Args:
        payload: Zuk listings payload (list of raw dicts).

    Returns:
        List of Imovel (or dict) in unified schema.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    if isinstance(payload, dict):
        payload = payload.get("listings") or payload.get("data") or []

    if not isinstance(payload, list):
        logger.warning(
            f"Payload inesperado: esperava list, recebeu {type(payload).__name__}"
        )
        return []

    now = datetime.now(timezone.utc).isoformat()
    imoveis = []
    for item in payload:
        imovel = from_zuk_listing(item, coleta_ts=now)
        if imovel:
            imoveis.append(imovel)

    logger.info(f"Converted {len(imoveis)} Zuk listings to unified schema")
    return imoveis


# ── Address parsing ──────────────────────────────────────────────────────────


def _parse_address(full_address: str) -> tuple[str, str, str, str]:
    """Parse a Zuk address string into components.

    Typical format from `.card-property-address`:
      "São Paulo - SP - Centro - Rua Exemplo"
      "São Paulo - SP - Vila Mariana"
      "Cidade/UF - Bairro - Rua"

    Args:
        full_address: Raw address string.

    Returns:
        Tuple of (endereco, bairro, cidade, uf).
    """
    endereco = ""
    bairro = ""
    cidade = ""
    uf = ""

    if not full_address:
        return (endereco, bairro, cidade, uf)

    # Try splitting by " - " separator
    parts = [p.strip() for p in full_address.split(" - ") if p.strip()]

    if len(parts) >= 3:
        # Format possibilities:
        #   "Cidade - UF - Bairro - Rua"
        #   "Cidade/UF - Bairro - Rua"  (UF embedded in cidade)
        cidade_raw = parts[0]
        second = parts[1]

        # Try to extract UF from first part (e.g. "Belo Horizonte/MG")
        if "/" in cidade_raw:
            cid_parts = cidade_raw.split("/", 1)
            cidade = cid_parts[0].strip()
            uf = cid_parts[1].strip().upper()[:2]
            # UF already extracted, second is definitely bairro
            bairro = second
            # Rest is endereco
            endereco_parts = parts[2:]
        else:
            cidade = cidade_raw
            # Second part might be UF or bairro
            if re.match(r"^[A-Z]{2}$", second.upper().strip()):
                uf = second.upper().strip()[:2]
                bairro = parts[2] if len(parts) > 2 else ""
                # Cidade - UF - Bairro - Rua...
                endereco_parts = parts[3:]
            else:
                bairro = second
                # Look for UF somewhere in the rest
                found_uf = False
                for i, part in enumerate(parts[2:], start=2):
                    p = part.upper().strip()
                    if re.match(r"^[A-Z]{2}$", p):
                        uf = p
                        endereco_parts = parts[i + 1:]
                        found_uf = True
                        break
                if not found_uf:
                    endereco_parts = parts[2:]

        if endereco_parts:
            endereco = " - ".join(endereco_parts)

    elif len(parts) == 2:
        cidade_raw = parts[0]
        rest = parts[1]

        # Check if cidade contains UF embedded (e.g. "Uberlândia / MG")
        if "/" in cidade_raw:
            cid_parts = cidade_raw.split("/", 1)
            cidade = cid_parts[0].strip()
            uf = cid_parts[1].strip().upper()[:2]
        else:
            cidade = cidade_raw
            # Might be "Cidade - Bairro" with UF completely missing
            # Try to find UF at end of the first part
            uf_match = re.search(r"\b([A-Z]{2})$", cidade_raw)
            if uf_match:
                uf = uf_match.group(1).upper()
                cidade = cidade_raw[: -2].strip().rstrip("/").rstrip()

        # Split rest into bairro and endereco
        # Pattern: bairro name followed by "Rua", "Avenida", "Av.", "Alameda", etc.
        street_prefixes = r"(Rua |Avenida |Av\. |Alameda |Praça |Travessa |Rodovia |Estrada |BR-|Sítio )"
        bairro_endereco_match = re.split(street_prefixes, rest, maxsplit=1)
        if len(bairro_endereco_match) >= 3:
            bairro = bairro_endereco_match[0].strip()
            endereco = bairro_endereco_match[1] + bairro_endereco_match[2].strip()
        else:
            bairro = rest.strip()

    elif len(parts) == 1:
        # Just one string — could be full address without separator
        endereco = parts[0]

    return (endereco, bairro, cidade, uf)
# ── URL builders ─────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Normalize text to ASCII slug (remove accents, lowercase, dashes)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def build_listing_url(
    uf: str | None = None,
    cidade: str | None = None,
    page: int = 1,
) -> str:
    """Build a Zuk listing URL with optional filters.

    Uses Laravel route: leilao-de-imoveis/{abrangencia?}/{uf?}/{cidade?}/...

    Args:
        uf: Optional UF filter (e.g., 'SP').
        cidade: Optional city slug (e.g., 'sao-paulo').
        page: Page number (default: 1).

    Returns:
        Full listing URL.
    """
    if uf and cidade:
        uf_slug = uf.lower()
        cidade_slug = _slugify(cidade)
        url = f"{BASE_URL}/leilao-de-imoveis/todos/{uf_slug}/{cidade_slug}"
    elif uf:
        url = f"{BASE_URL}/leilao-de-imoveis/todos/{uf.lower()}"
    else:
        url = f"{BASE_URL}/leilao-de-imoveis"

    if page > 1:
        url = f"{url}?page={page}"

    return url


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    """CLI para testar o parser Zuk diretamente."""
    import argparse

    parser = argparse.ArgumentParser(description="Zuk Parser — extração e teste")
    sub = parser.add_subparsers(dest="command")

    # extract: fetch and parse a single page
    ext_parser = sub.add_parser("extract", help="Extrair uma página de listagem")
    ext_parser.add_argument(
        "--url",
        default=f"{BASE_URL}/leilao-de-imoveis",
        help="URL da página de listagem",
    )
    ext_parser.add_argument("--output", help="Salvar JSON em arquivo")

    # crawl: multi-page extraction
    crawl_parser = sub.add_parser("crawl", help="Crawl múltiplas páginas")
    crawl_parser.add_argument(
        "--url",
        default=f"{BASE_URL}/leilao-de-imoveis",
        help="URL inicial",
    )
    crawl_parser.add_argument("--pages", type=int, default=5, help="Máx. páginas")
    crawl_parser.add_argument("--output", help="Salvar JSON em arquivo")
    crawl_parser.add_argument("--rate-limit", type=float, default=1.5)

    # parse: parse a local HTML file
    parse_parser = sub.add_parser("parse", help="Parsear arquivo HTML local")
    parse_parser.add_argument("input_file", help="Caminho do arquivo .html")
    parse_parser.add_argument("--output", help="Salvar JSON em arquivo")

    # convert: convert raw JSON to unified schema (tests FIELD_MAP + _collect_photos)
    convert_parser = sub.add_parser("convert", help="Converter JSON bruto para schema unificado")
    convert_parser.add_argument("input_file", help="Caminho do arquivo .json")
    convert_parser.add_argument("--output", help="Salvar JSON convertido")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [zuk] %(message)s",
    )

    if args.command == "extract":
        listings = extract_listing_page(url=args.url)
        print(f"\nExtraídos {len(listings)} imóveis da página")
        if listings:
            converted = from_zuk_listing(listings[0]) or {}
            print(
                f"  Amostra: {converted.get('titulo', 'N/A')} — "
                f"R$ {converted.get('preco_venda', 'N/A')}"
            )
            if args.output:
                full = from_zuk_payload(listings)
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                with open(args.output, "w") as f:
                    json.dump(full, f, indent=2, ensure_ascii=False)
                print(f"  Salvo em: {args.output}")

    elif args.command == "crawl":
        listings, meta = crawl_listing(
            start_url=args.url,
            pages=args.pages,
            rate_limit=args.rate_limit,
        )
        print(
            f"\nExtraídos {len(listings)} imóveis em {meta['pages_fetched']} páginas"
        )
        if listings:
            converted = from_zuk_payload(listings)
            print(f"  Convertidos: {len(converted)} para schema unificado")
            if converted:
                prices = [
                    i.get("preco_venda", 0)
                    for i in converted
                    if i.get("preco_venda")
                ]
                if prices:
                    print(
                        f"  Preços: R$ {min(prices):.0f} ~ R$ {max(prices):.0f}"
                    )
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                with open(args.output, "w") as f:
                    json.dump(converted, f, indent=2, ensure_ascii=False)
                print(f"  Salvo em: {args.output}")

    elif args.command == "parse":
        with open(args.input_file) as f:
            html = f.read()
        listings, meta = extract_from_html(html, source_url=args.input_file)
        print(f"\nParseados {len(listings)} imóveis de {args.input_file}")
        if listings:
            converted = from_zuk_payload(listings)
            print(f"  Convertidos: {len(converted)} para schema unificado")
            if args.output:
                Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                with open(args.output, "w") as f:
                    json.dump(converted, f, indent=2, ensure_ascii=False)
                print(f"  Salvo em: {args.output}")

    elif args.command == "convert":
        with open(args.input_file) as f:
            data = json.load(f)
        converted = from_zuk_payload(data)
        print(f"\nConvertidos {len(converted)} imóveis de {args.input_file}")
        if converted:
            sample = converted[0]
            print(
                f"  Amostra: {sample.get('titulo', 'N/A')} — "
                f"R$ {sample.get('preco_venda', 'N/A')} — "
                f"{len(sample.get('fotos', []))} fotos"
            )
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(converted, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
