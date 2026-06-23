"""
loft_ssr — SSR data extraction for Loft single listing pages.

Extracts listing data from Loft's Next.js search pages by fetching the HTML
and parsing the __NEXT_DATA__ JSON embedded in the server-rendered response.
No browser required — works with plain HTTP requests because Loft is an SSR
Next.js app that embeds all page data inline.

Functions:
    extract_from_ssr(url: str) -> list[dict]
        Fetch a Loft search listing URL, parse __NEXT_DATA__, return listings.

    extract_from_html(html: str) -> list[dict]
        Parse __NEXT_DATA__ from raw HTML string (no HTTP call).

    extract_from_dom(html: str, url: str) -> list[dict]
        Fallback DOM/HTML parsing when __NEXT_DATA__ is missing.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger("loft_ssr")

# ── Photo CDN base ────────────────────────────────────────────────────────────

PHOTO_BASE = "https://content.loft.com.br/homes"

# ── Property type map ─────────────────────────────────────────────────────────

PROPERTY_TYPE_MAP = {
    "apartment": "apartamento",
    "default": "apartamento",
    "rooftop": "cobertura",
    "house": "casa",
    "studio": "studio",
    "duplex": "duplex",
    "triplex": "triplex",
    "garden": "casa_condominio",
    "conjugado": "conjugado",
    "penthouse": "cobertura",
    "flat": "flat",
}


def _map_property_type(raw_type: str | None) -> str:
    """Map Loft property type keys to Portuguese unified type names."""
    if not raw_type:
        return "apartamento"
    return PROPERTY_TYPE_MAP.get(raw_type.lower(), raw_type.lower())


def _build_photo_urls(photos: list[str] | None) -> list[str]:
    """Build full CDN URLs from photo filenames.

    Loft stores photos as relative filenames on the CDN.
    We need to construct full URLs pointing to the CDN base.
    """
    if not photos:
        return []
    # Remove duplicates while preserving order
    seen: set[str] = set()
    urls: list[str] = []
    for filename in photos:
        if filename and filename not in seen:
            seen.add(filename)
            # Some filenames may already have a protocol prefix
            if filename.startswith("http"):
                urls.append(filename)
            else:
                urls.append(f"{PHOTO_BASE}/{filename}")
    return urls


def _get_neighborhood(address: dict) -> str:
    """Extract neighborhood name from various address shapes."""
    # Try direct 'neighborhood' field first
    nb = address.get("neighborhood") or ""
    if nb:
        return nb
    # Try nested 'neighbourhood' object
    nb_obj = address.get("neighbourhood") or {}
    if isinstance(nb_obj, dict):
        return nb_obj.get("name") or nb_obj.get("slug", "").split("_")[0] or ""
    if isinstance(nb_obj, str):
        return nb_obj
    return ""


def _build_address_str(address: dict) -> str:
    """Build a human-readable address string from the address object."""
    parts = [
        address.get("streetFullName") or "",
        address.get("number") or "",
    ]
    addr_str = ", ".join(p for p in parts if p)
    if not addr_str:
        addr_str = _get_neighborhood(address)
    return addr_str


def map_listing_to_imovel(item: dict) -> dict | None:
    """Convert a single listing dict from Loft SSR data to unified Imovel schema.

    Args:
        item: A listing object from __NEXT_DATA__ → Listing:Search → listings[].

    Returns:
        Dict in unified Imovel schema, or None if the item is invalid.
    """
    if not item or not isinstance(item, dict):
        return None

    # Handle both nested shape ({listing: {...}}) and flat shape ({...})
    listing = item.get("listing", item) if "listing" in item else item

    address = listing.get("address") or {}
    neighborhood = _get_neighborhood(address)
    endereco = _build_address_str(address)

    # Prefer propertyType (more specific: rooftop, garden) over homeType (generic: apartment)
    raw_type = listing.get("propertyType") or listing.get("homeType") or ""
    property_type = _map_property_type(raw_type)
    is_sale = listing.get("transactionType") == "FOR_SALE" or listing.get("status") == "FOR_SALE"

    # Photos
    photo_filenames: list[str] = []
    raw_photos = listing.get("photos") or []
    for p in raw_photos:
        if isinstance(p, str):
            photo_filenames.append(p)
        elif isinstance(p, dict) and p.get("url"):
            photo_filenames.append(str(p["url"]))
    photo_urls = _build_photo_urls(photo_filenames) if photo_filenames else []

    # Amenities
    amenities = [
        *(listing.get("unitFeatures") or []),
        *(listing.get("condominiumInfrastructure") or []),
        *(listing.get("condominiumLeisure") or []),
    ]
    amenities = [a for a in amenities if a]

    # Price reduction
    previous_price = listing.get("previousPrice")
    current_price = listing.get("price")
    has_reduction = bool(previous_price and current_price and previous_price > current_price)
    reduction_pct = 0.0
    if has_reduction:
        reduction_pct = round((1 - current_price / previous_price) * 100, 2)

    # Geolocation
    geoloc = listing.get("_geoloc") or {}
    lat = geoloc.get("lat") or address.get("lat")
    lng = geoloc.get("lng") or address.get("lng")
    if lat:
        lat = float(lat)
    if lng:
        lng = float(lng)

    # Build title
    title = listing.get("title")
    if not title:
        title = f"{property_type.capitalize()} em {neighborhood}".strip() or property_type.capitalize()

    # Build listing URL from ID if not provided
    listing_url = listing.get("url") or ""
    listing_id = listing.get("id") or listing.get("objectID") or ""
    if not listing_url and listing_id:
        listing_url = f"https://loft.com.br/imovel/{listing_id}"

    return {
        # Identification
        "id": listing_id,
        "titulo": title,
        "descricao": listing.get("description") or "",
        "fonte": "loft",
        "url": listing_url,

        # Prices
        "preco_venda": float(current_price) if is_sale and current_price is not None else None,
        "preco_anterior": float(previous_price) if is_sale and previous_price is not None else None,
        "data_atualizacao_preco": listing.get("priceUpdatedAt") or None,
        "preco_aluguel": float(listing["rentalPrice"]) if not is_sale and listing.get("rentalPrice") is not None else None,

        # Fees
        "condominio": float(listing["complexFee"]) if listing.get("complexFee") is not None else None,
        "iptu": float(listing["propertyTax"]) if listing.get("propertyTax") is not None else None,

        # Characteristics
        "area": float(listing["area"]) if listing.get("area") is not None else None,
        "quartos": int(listing["bedrooms"]) if listing.get("bedrooms") is not None else None,
        "suites": int(listing["suits"]) if listing.get("suits") is not None else None,
        "banheiros": int(listing["restrooms"]) if listing.get("restrooms") is not None else None,
        "vagas": int(listing["parkingSpots"]) if listing.get("parkingSpots") is not None else None,
        "andar": int(listing["floor"]) if listing.get("floor") is not None else None,

        # Classification
        "tipo": property_type,
        "uso": listing.get("usageType") or "residential",

        # Location
        "endereco": endereco,
        "bairro": neighborhood,
        "cidade": address.get("city") or "São Paulo",
        "uf": address.get("state") or "SP",
        "cep": address.get("postalCode") or None,
        "latitude": lat,
        "longitude": lng,

        # Media
        "imagens": photo_urls,
        "comodidades": amenities,

        # Metadata
        "agencia": listing.get("agencyName") or "",
        "origem_id": str(listing["unitId"]) if listing.get("unitId") is not None else None,
        "data_criacao": listing.get("createdAt") or None,

        # Price drop
        "tem_reducao": has_reduction,
        "percentual_reducao": reduction_pct,

        # Raw identifiers
        "raw_id": listing.get("id") or listing.get("objectID"),
        "listingGroupKey": listing.get("listingGroupKey") or None,

        # Collection timestamp
        "data_coleta": datetime.now(timezone.utc).isoformat(),
    }


def _extract_next_data_json(html: str) -> dict | None:
    """Extract and parse the __NEXT_DATA__ JSON from HTML.

    Args:
        html: Raw HTML string from a Loft SSR page.

    Returns:
        Parsed __NEXT_DATA__ JSON dict, or None if not found.
    """
    # First try the standard <script id="__NEXT_DATA__"> tag
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse __NEXT_DATA__ JSON: {e}")
            return None

    # Try alternative: self-closing script tag pattern
    match = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json"\s*/?>',
        html,
        re.DOTALL,
    )
    if match:
        # Find content between this tag and next script tag
        start = match.end()
        end_match = re.search(r"</script>", html[start:])
        if end_match:
            try:
                return json.loads(html[start:start + end_match.start()])
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse __NEXT_DATA__ (alt pattern): {e}")

    return None


def _extract_listings_from_next_data(next_data: dict) -> list[dict]:
    """Extract listings from parsed __NEXT_DATA__ JSON.

    Navigates through the Next.js dehydrated state structure to find
    the Listing:Search query data and extract all listings.

    Args:
        next_data: Parsed __NEXT_DATA__ JSON dict.

    Returns:
        List of raw listing dicts from the SSR payload.
    """
    page_props = (next_data.get("props") or {}).get("pageProps")
    if not page_props:
        logger.warning("pageProps not found in __NEXT_DATA__")
        return []

    queries = (page_props.get("dehydratedState") or {}).get("queries") or []
    if not queries:
        logger.warning("No queries in dehydratedState")
        return []

    # Find the Listing:Search query
    search_query = None
    for q in queries:
        query_key = q.get("queryKey")
        if isinstance(query_key, list) and query_key and query_key[0] == "Listing:Search":
            search_query = q
            break

    if not search_query:
        available = [q.get("queryKey", [""])[0] for q in queries if isinstance(q.get("queryKey"), list)]
        logger.warning(f"Listing:Search query not found. Available: {', '.join(available)}")
        return []

    state = search_query.get("state") or {}
    data = state.get("data") or {}
    if not data:
        logger.warning("No data in Listing:Search query state")
        return []

    return data.get("listings") or []


def extract_from_ssr(
    url: str,
    timeout: int = 30,
    headers: dict | None = None,
) -> list[dict]:
    """Fetch a Loft search listing page and extract listings from SSR data.

    Performs an HTTP GET on the provided URL, extracts __NEXT_DATA__ from
    the HTML, parses it, and maps all listings to the unified Imovel schema.

    Args:
        url: Full URL of a Loft search listing page (e.g.,
             'https://loft.com.br/venda/apartamentos/sp/sao-paulo/').
        timeout: HTTP request timeout in seconds (default: 30).
        headers: Optional dict of extra HTTP headers. Default User-Agent
                 mimics a standard Chrome browser.

    Returns:
        List of dicts in the unified Imovel schema. Empty list if extraction
        fails at any step.

    Raises:
        requests.RequestException: If the HTTP request itself fails.
    """
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)

    logger.info(f"Fetching: {url}")
    response = requests.get(url, headers=default_headers, timeout=timeout)
    response.raise_for_status()

    html = response.text
    if not html or len(html) < 1000:
        logger.warning(f"Response too short ({len(html)} chars) for {url}")
        return []

    return extract_from_html(html, url)


def extract_from_html(html: str, source_url: str = "") -> list[dict]:
    """Parse listings from raw Loft SSR HTML.

    Extracts __NEXT_DATA__ from the HTML and maps all listings to the
    unified Imovel schema. Falls back to DOM parsing if __NEXT_DATA__
    is missing.

    Args:
        html: Raw HTML string from a Loft page.
        source_url: Original URL for context (used in fallback).

    Returns:
        List of dicts in the unified Imovel schema.
    """
    # Strategy 1: Extract from __NEXT_DATA__
    next_data = _extract_next_data_json(html)
    if next_data:
        logger.info("Found __NEXT_DATA__ in HTML")
        raw_listings = _extract_listings_from_next_data(next_data)
        if raw_listings:
            logger.info(f"Extracted {len(raw_listings)} raw listings from SSR data")
            mapped = [map_listing_to_imovel(item) for item in raw_listings]
            mapped = [m for m in mapped if m]
            logger.info(f"Mapped {len(mapped)} listings to unified schema")
            return mapped
        logger.warning("No listings found in __NEXT_DATA__")
    else:
        logger.warning("__NEXT_DATA__ not found in HTML")

    # Strategy 2: Fallback to DOM parsing
    logger.info("Falling back to DOM/HTML parsing...")
    return extract_from_dom(html, source_url)


def extract_from_dom(html: str, url: str = "") -> list[dict]:
    """Fallback DOM/HTML parsing when __NEXT_DATA__ is missing.

    Attempts to extract listing information from the raw HTML by looking for:
    - JSON-LD structured data (<script type="application/ld+json">)
    - Open Graph meta tags
    - HTML5 data attributes
    - Title and meta description

    Note: This is a limited fallback and may not capture all fields.
    Most Loft pages include __NEXT_DATA__, so this is rarely needed.

    Args:
        html: Raw HTML string to parse.
        url: Original URL for context.

    Returns:
        List of dicts in unified Imovel schema (usually 0 or 1 item
        for a listing detail page, or empty for search pages without SSR).
    """
    listings: list[dict] = []

    # Method 1: Extract JSON-LD structured data
    ld_matches = re.finditer(
        r'<script\s+type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    for match in ld_matches:
        try:
            ld = json.loads(match.group(1))
            if isinstance(ld, dict) and ld.get("@type") in ("Product", "RealEstateListing", "Apartment"):
                listing = _map_jsonld_to_imovel(ld)
                if listing:
                    listings.append(listing)
        except (json.JSONDecodeError, ValueError):
            continue

    # Method 2: Extract from meta tags / Open Graph
    if not listings:
        og_title = _extract_meta(html, "og:title")
        og_description = _extract_meta(html, "og:description")
        og_image = _extract_meta(html, "og:image")
        og_url = _extract_meta(html, "og:url") or url

        # Extract price from HTML patterns if available
        price_match = re.search(
            r'R?\$\s*([\d.,]+)\s*(?:mil|\.\d{3})?',
            html,
        )
        price = None
        if price_match:
            price_str = price_match.group(1).replace(".", "").replace(",", ".")
            try:
                price = float(price_str)
            except ValueError:
                pass

        if og_title or price:
            listings.append({
                "id": "",
                "titulo": og_title or "Imóvel Loft",
                "descricao": og_description or "",
                "fonte": "loft",
                "url": og_url,
                "preco_venda": price,
                "preco_anterior": None,
                "data_atualizacao_preco": None,
                "preco_aluguel": None,
                "condominio": None,
                "iptu": None,
                "area": None,
                "quartos": None,
                "suites": None,
                "banheiros": None,
                "vagas": None,
                "andar": None,
                "tipo": "apartamento",
                "uso": "residential",
                "endereco": "",
                "bairro": "",
                "cidade": "São Paulo",
                "uf": "SP",
                "cep": None,
                "latitude": None,
                "longitude": None,
                "imagens": [og_image] if og_image else [],
                "comodidades": [],
                "agencia": "",
                "origem_id": None,
                "data_criacao": None,
                "tem_reducao": False,
                "percentual_reducao": 0.0,
                "raw_id": None,
                "listingGroupKey": None,
                "data_coleta": datetime.now(timezone.utc).isoformat(),
            })

    logger.info(f"DOM parsing extracted {len(listings)} listings")
    return listings


def _extract_meta(html: str, property_name: str) -> str | None:
    """Extract a meta tag's content by property or name attribute."""
    # Try property= first, then name=
    pattern = rf'<meta\s+(?:property="{property_name}"|name="{property_name}")\s+content="([^"]*)"'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        return match.group(1)
    # Reverse order: name= then property=
    pattern2 = rf'<meta\s+(?:name="{property_name}"|property="{property_name}")\s+content="([^"]*)"'
    match = re.search(pattern2, html, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _map_jsonld_to_imovel(ld: dict) -> dict | None:
    """Map a JSON-LD structured data object to the unified Imovel schema.

    Args:
        ld: A parsed JSON-LD dict (type Product, RealEstateListing, etc.).

    Returns:
        Dict in unified Imovel schema, or None.
    """
    if not ld or not isinstance(ld, dict):
        return None

    name = ld.get("name") or ld.get("title") or ""
    description = ld.get("description") or ""

    # Extract price from offers
    offers = ld.get("offers") or {}
    if isinstance(offers, dict):
        price = offers.get("price")
        currency = offers.get("priceCurrency")
        if price is not None:
            try:
                price = float(price)
            except (ValueError, TypeError):
                price = None
    else:
        price = None

    # Extract address
    addr = ld.get("address") or {}
    if isinstance(addr, dict):
        address_str = ", ".join(
            p for p in [addr.get("streetAddress", ""), addr.get("addressLocality", "")]
            if p
        )
        neighborhood = addr.get("addressLocality", "")
        city = addr.get("addressLocality", ld.get("city", "São Paulo"))
        state = addr.get("addressRegion", "SP")
    else:
        address_str = ""
        neighborhood = ""
        city = "São Paulo"
        state = "SP"

    # Extract geo
    geo = ld.get("geo") or {}
    lat = geo.get("latitude")
    lng = geo.get("longitude")
    if lat:
        lat = float(lat)
    if lng:
        lng = float(lng)

    # Extract image
    image = ld.get("image") or ""
    if isinstance(image, list):
        image = image[0] if image else ""
    if isinstance(image, dict):
        image = image.get("url", "")

    return {
        "id": ld.get("sku") or ld.get("@id") or "",
        "titulo": name,
        "descricao": description,
        "fonte": "loft",
        "url": ld.get("url") or ld.get("@id") or "",
        "preco_venda": price,
        "preco_anterior": None,
        "data_atualizacao_preco": None,
        "preco_aluguel": None,
        "condominio": None,
        "iptu": None,
        "area": None,
        "quartos": None,
        "suites": None,
        "banheiros": None,
        "vagas": None,
        "andar": None,
        "tipo": _infer_type_from_name(name),
        "uso": "residential",
        "endereco": address_str,
        "bairro": neighborhood,
        "cidade": city,
        "uf": state,
        "cep": None,
        "latitude": lat,
        "longitude": lng,
        "imagens": [image] if image else [],
        "comodidades": [],
        "agencia": "",
        "origem_id": None,
        "data_criacao": None,
        "tem_reducao": False,
        "percentual_reducao": 0.0,
        "raw_id": None,
        "listingGroupKey": None,
        "data_coleta": datetime.now(timezone.utc).isoformat(),
    }


def _infer_type_from_name(name: str) -> str:
    """Infer property type from name/title when not explicitly given."""
    lower = name.lower()
    if any(k in lower for k in ("kitnet", "studio")):
        return "kitnet"
    if "cobertura" in lower:
        return "cobertura"
    if "casa" in lower:
        return "casa"
    if "flat" in lower:
        return "flat"
    if "duplex" in lower:
        return "duplex"
    return "apartamento"


# ── CLI ────────────────────────────────────────────────────────────────────────


def main():
    """CLI for testing the SSR extractor directly.

    Usage:
        python skills/loft/loft_ssr.py <url>
        python skills/loft/loft_ssr.py --file <path> [--url <source_url>]
        python skills/loft/loft_ssr.py --sample
    """
    import argparse

    parser = argparse.ArgumentParser(description="Loft SSR Extractor — test extração via SSR")
    parser.add_argument("url", nargs="?", help="URL da página de busca Loft")
    parser.add_argument("--file", help="Arquivo HTML local para testar parsing")
    parser.add_argument("--source-url", help="URL original do HTML (para fallback DOM)")
    parser.add_argument("--sample", action="store_true", help="Extrair da página padrão de SP")
    parser.add_argument("--pretty", action="store_true", help="Output JSON pretty-printed")
    parser.add_argument("--count", action="store_true", help="Apenas contar listings")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.file:
        with open(args.file) as f:
            html = f.read()
        listings = extract_from_html(html, source_url=args.source_url or "")

    elif args.sample:
        listings = extract_from_ssr("https://loft.com.br/venda/apartamentos/sp/sao-paulo/")

    elif args.url:
        listings = extract_from_ssr(args.url)

    else:
        parser.print_help()
        return

    if args.count:
        print(f"Total listings: {len(listings)}")
        return

    if not listings:
        print("Nenhum imóvel extraído.")
        return

    print(f"Total: {len(listings)} imóveis\n")

    # Show sample
    for i, imovel in enumerate(listings[:3]):
        print(f"--- Imóvel {i + 1} ---")
        for key, val in imovel.items():
            if val:
                if isinstance(val, list) and len(val) > 3:
                    print(f"  {key}: [{len(val)} items]")
                elif isinstance(val, float):
                    print(f"  {key}: {val:,.2f}")
                else:
                    print(f"  {key}: {val}")
        print()

    if args.pretty:
        import sys
        json.dump(listings, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
