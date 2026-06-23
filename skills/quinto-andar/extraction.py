"""
extraction — Extracts structured listing data from a QuintoAndar page.

Usage:
    from extraction import extract_listings

    # After navigate_to_search:
    page = navigate_to_search(browser, "sao-paulo-sp-brasil", "apartamento", "comprar")
    listings = extract_listings(page)
    # → [{"id": "892820623", "salePrice": 1000000, ...}, ...]

Strategy:
    1. Fast path — Fetch Next.js data route (/_next/data/<buildId>/...json)
    2. Fallback — Parse __NEXT_DATA__ from the SSR DOM
    3. Last resort — Parse individual listing cards from the DOM

Returns JSON-serializable dicts with the task-required fields:
    id, salePrice, rentPrice, area, bedrooms, bathrooms, parkingSpots,
    type, address, neighbourhood, condoIptu, photos, amenities, shortSaleDescription
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Ensure schema in path
sys.path.insert(0, str(Path.home() / ".hermes"))
from imovel_schema import Imovel

# ── Logging ──────────────────────────────────────────────────────────────

logger = logging.getLogger("quintoandar_extraction")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("[extraction] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

QUINTOANDAR_BASE = "https://www.quintoandar.com.br"

# ── Extractors ──────────────────────────────────────────────────────────


def extract_listings(page: Any, timeout_ms: int = 15000) -> list[dict[str, Any]]:
    """
    Extract structured listing data from a QuintoAndar search page.

    Tries, in order:
      1. Next.js data route fetch (fastest, richest data)
      2. __NEXT_DATA__ embedded in SSR HTML
      3. DOM card parsing (last resort)

    Args:
        page: A Playwright Page object loaded by navigate_to_search().
        timeout_ms: Max ms for each extraction attempt.

    Returns:
        List of dicts with keys: id, salePrice, rentPrice, area, bedrooms,
        bathrooms, parkingSpots, type, address, neighbourhood, condoIptu,
        photos, amenities, shortSaleDescription.

        Empty list if nothing could be extracted.
    """
    if page is None:
        logger.warning("extract_listings: page is None")
        return []

    # ── 1. Fast path: Next.js data route ──────────────────────────────
    try:
        result = _try_data_route(page, timeout_ms)
        if result:
            logger.info(f"Data route: {len(result)} listings extracted")
            return result
    except Exception as exc:
        logger.warning(f"Data route failed: {exc}")

    # ── 2. Fallback: __NEXT_DATA__ from SSR DOM ────────────────────────
    try:
        result = _try_ssr_data(page, timeout_ms)
        if result:
            logger.info(f"__NEXT_DATA__: {len(result)} listings extracted")
            return result
    except Exception as exc:
        logger.warning(f"__NEXT_DATA__ failed: {exc}")

    # ── 3. Last resort: DOM parsing ────────────────────────────────────
    try:
        result = _try_dom_parse(page, timeout_ms)
        if result:
            logger.info(f"DOM parse: {len(result)} listings extracted")
            return result
    except Exception as exc:
        logger.warning(f"DOM parse failed: {exc}")

    logger.warning("All extraction strategies failed — returning empty list")
    return []


# ── Strategy 1: Next.js data route fetch ──────────────────────────────────


def _try_data_route(page: Any, timeout_ms: int) -> list[dict[str, Any]]:
    """
    Fetch listing data via the Next.js data route.

    Constructs the URL from buildId + pathname and fetches the JSON endpoint
    from the browser context (same-origin, no CORS issues).
    """
    js_code = f"""
    (async () => {{
        const timeout = {timeout_ms};

        // Helper: fetch with timeout
        const fetchWithTimeout = (url, ms) => {{
            const controller = new AbortController();
            const id = setTimeout(() => controller.abort(), ms);
            return fetch(url, {{ signal: controller.signal }})
                .finally(() => clearTimeout(id));
        }};

        try {{
            // 1. Get build ID
            const buildId = window.__NEXT_DATA__?.buildId;
            if (!buildId) {{
                return {{ error: "No __NEXT_DATA__.buildId found" }};
            }}

            // 2. Get the current page path (without query params)
            const pathname = window.location.pathname;

            // Strip trailing slash for clean route
            const cleanPath = pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;

            // Determine locale — default to pt-BR for QuintoAndar
            const locale = "pt-BR";

            // 3. Build the data route URL
            // Pattern: /_next/data/<buildId>/<locale>/<path>.json
            let dataUrl = `/_next/data/${{buildId}}/${{locale}}${{cleanPath}}.json`;

            // If the path already looks like a data route (has _next/data), strip that
            if (cleanPath.includes('_next/data')) {{
                dataUrl = cleanPath;
                if (!dataUrl.endsWith('.json')) dataUrl += '.json';
            }}

            // 4. Fetch the data route
            const response = await fetchWithTimeout(dataUrl, timeout);
            if (!response.ok) {{
                return {{
                    error: `Data route HTTP ${{response.status}}: ${{dataUrl}}`,
                    url: dataUrl,
                }};
            }}

            const data = await response.json();
            return {{ data, url: dataUrl }};

        }} catch (err) {{
            return {{ error: err.message || String(err) }};
        }}
    }})()
    """

    raw = page.evaluate(js_code)
    if not isinstance(raw, dict):
        logger.warning(f"Data route returned unexpected type: {type(raw).__name__}")
        return []

    if "error" in raw:
        logger.debug(f"Data route error: {raw['error']}")
        return []

    data = raw.get("data")
    if not isinstance(data, dict):
        logger.warning("Data route returned no data payload")
        return []

    # Parse via the existing quintoandar_parser
    imoveis = _parse_payload(data)
    return [_imovel_to_listing_dict(i, data) for i in imoveis]


# ── Strategy 2: __NEXT_DATA__ from SSR DOM ────────────────────────────────


def _try_ssr_data(page: Any, timeout_ms: int) -> list[dict[str, Any]]:
    """
    Extract listing data from __NEXT_DATA__ embedded in the SSR HTML.

    This is available immediately after SSR render without an extra fetch.
    """
    js_code = """
    (() => {
        try {
            const nextData = window.__NEXT_DATA__;
            if (!nextData || !nextData.props) {
                return { error: "No __NEXT_DATA__ available" };
            }
            return { data: nextData };
        } catch (err) {
            return { error: err.message || String(err) };
        }
    })()
    """

    raw = page.evaluate(js_code)
    if not isinstance(raw, dict) or "error" in raw:
        return []

    data = raw.get("data")
    if not isinstance(data, dict):
        return []

    imoveis = _parse_payload(data)
    return [_imovel_to_listing_dict(i, data) for i in imoveis]


# ── Strategy 3: DOM parsing (last resort) ────────────────────────────────


def _try_dom_parse(page: Any, timeout_ms: int) -> list[dict[str, Any]]:
    """
    Parse listing data from the DOM as a last resort.

    QuintoAndar renders listing cards via React — the SSR HTML contains
    minimal data. This extracts what's visible on screen.
    """
    js_code = """
    (() => {
        try {
            // Try to find listing cards
            const cards = document.querySelectorAll(
                'a[data-testid="listing-card"], ' +
                'a[href*="/imovel/"], ' +
                '[class*="listing-card"], ' +
                '[class*="ListingCard"]'
            );

            if (cards.length === 0) {
                // Try the listing grid container
                const grid = document.querySelector(
                    '[data-testid="listing-grid"], ' +
                    '[class*="listing-grid"], ' +
                    '[class*="ListingGrid"]'
                );
                if (!grid) return { error: "No listing cards or grid found" };
                return { error: "Grid found but no cards rendered" };
            }

            const listings = [];
            const seen = new Set();

            cards.forEach((card) => {
                const href = card.getAttribute('href') || '';
                if (seen.has(href)) return;
                seen.add(href);

                const listing = {};

                const idMatch = href.match(/\\/(\\d+)(?:\\?|$)/);
                if (idMatch) listing.id = idMatch[1];

                const titleEl = card.querySelector(
                    '[class*="title"], h2, h3, [class*="Title"]'
                );
                if (titleEl) listing.shortSaleDescription = titleEl.textContent.trim();

                // Extract price
                const priceEl = card.querySelector(
                    '[class*="price"], [class*="Price"], ' +
                    '[class*="sale-price"], [class*="rent-price"]'
                );
                if (priceEl) {
                    const priceText = priceEl.textContent.trim();
                    const numMatch = priceText.replace(/\\./g, '').match(/(\\d+)/);
                    if (numMatch) {
                        const priceVal = parseFloat(numMatch[1]);
                        if (priceText.includes('aluguel') || href.includes('/alugar/')) {
                            listing.rentPrice = priceVal;
                        } else {
                            listing.salePrice = priceVal;
                        }
                    }
                }

                // Extract area, bedrooms, bathrooms, parking
                const areaEl = card.querySelector('[class*="area"], [class*="Area"]');
                if (areaEl) {
                    const areaMatch = areaEl.textContent.match(/(\\d+)/);
                    if (areaMatch) listing.area = parseFloat(areaMatch[1]);
                }

                const bedEl = card.querySelector(
                    '[class*="bedroom"], [class*="Bedroom"], ' +
                    '[class*="quartos"], [class*="Quartos"]'
                );
                if (bedEl) {
                    const bedMatch = bedEl.textContent.match(/(\\d+)/);
                    if (bedMatch) listing.bedrooms = parseInt(bedMatch[1], 10);
                }

                const bathEl = card.querySelector(
                    '[class*="bathroom"], [class*="Bathroom"], ' +
                    '[class*="banheiros"], [class*="Banheiros"]'
                );
                if (bathEl) {
                    const bathMatch = bathEl.textContent.match(/(\\d+)/);
                    if (bathMatch) listing.bathrooms = parseInt(bathMatch[1], 10);
                }

                const parkEl = card.querySelector(
                    '[class*="parking"], [class*="Parking"], ' +
                    '[class*="vagas"], [class*="Vagas"]'
                );
                if (parkEl) {
                    const parkMatch = parkEl.textContent.match(/(\\d+)/);
                    if (parkMatch) listing.parkingSpots = parseInt(parkMatch[1], 10);
                }

                const nbEl = card.querySelector(
                    '[class*="neighbourhood"], [class*="neighborhood"], ' +
                    '[class*="Neighbourhood"], [class*="bairro"], ' +
                    '[class*="Bairro"]'
                );
                if (nbEl) {
                    listing.neighbourhood = nbEl.textContent.trim();
                }

                const imgs = card.querySelectorAll('img[src*="quintoandar"]');
                if (imgs.length > 0) {
                    listing.photos = Array.from(imgs).map(
                        img => img.getAttribute('src') || img.getAttribute('data-src') || ''
                    ).filter(Boolean);
                }

                listing.url = href.startsWith('http')
                    ? href
                    : 'https://www.quintoandar.com.br' + href;

                listing.type = '';

                listings.push(listing);
            });

            return { listings };

        } catch (err) {
            return { error: err.message || String(err) };
        }
    })()
    """

    raw = page.evaluate(js_code)
    if not isinstance(raw, dict) or "error" in raw:
        return []

    listings = raw.get("listings", [])
    if not isinstance(listings, list):
        return []

    # Enrich with URL-derived info
    current_url = page.url
    is_rent = "/alugar/" in current_url
    for lst in listings:
        if is_rent and lst.get("salePrice") and not lst.get("rentPrice"):
            lst["rentPrice"] = lst.pop("salePrice", None)
        lst.setdefault("salePrice", None)
        lst.setdefault("rentPrice", None)
        lst.setdefault("area", None)
        lst.setdefault("bedrooms", None)
        lst.setdefault("bathrooms", None)
        lst.setdefault("parkingSpots", None)
        lst.setdefault("type", "")
        lst.setdefault("address", None)
        lst.setdefault("neighbourhood", "")
        lst.setdefault("condoIptu", None)
        lst.setdefault("photos", [])
        lst.setdefault("amenities", [])
        lst.setdefault("shortSaleDescription", "")

    return listings


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Navigate nested dicts safely (like the parser's _safe_get)."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        if key not in current:
            return default
        current = current[key]
    return current


def _parse_payload(payload: dict) -> list[Imovel]:
    """
    Parse a Next.js data route payload (or __NEXT_DATA__) into Imovel objects.

    Uses the existing quintoandar_parser machinery, but handles the case where
    ``houses`` is a dict keyed by house ID (not a list).  QuintoAndar's SSR
    returns houses as ``{ houseId: House, ... }``.
    """
    try:
        sys.path.insert(0, str(_PROJECT_ROOT / "skills" / "quinto-andar"))
        from quintoandar_parser import from_quintoandar_safe, from_quintoandar_houses
    except ImportError:
        logger.error("quintoandar_parser not available — cannot parse payload")
        return []

    if not isinstance(payload, dict):
        return []

    # First try the standard parser (handles list format)
    imoveis = from_quintoandar_safe(payload)
    if imoveis:
        return imoveis

    # Parser returned empty — check if houses exists as a dict
    # Navigate: pageProps → initialState → houses
    houses = (
        _safe_get(payload, "pageProps", "initialState", "houses")
        or _safe_get(payload, "initialState", "houses")
        or payload.get("houses")
    )

    if isinstance(houses, dict):
        # Houses is a dict keyed by house ID — convert to list
        house_list = [h for h in houses.values() if isinstance(h, dict)]
        if house_list:
            logger.info(f"Parsing {len(house_list)} houses from dict-format houses")
            return from_quintoandar_houses(house_list)

    return []


def _imovel_to_listing_dict(imovel: Imovel, raw_payload: dict | None = None) -> dict[str, Any]:
    """
    Convert an Imovel dataclass back to the flat listing dict format
    required by the task spec.

    Keys: id, salePrice, rentPrice, area, bedrooms, bathrooms, parkingSpots,
    type, address, neighbourhood, condoIptu, photos, amenities, shortSaleDescription
    """
    listing: dict[str, Any] = {
        "id": imovel.id,
        "salePrice": imovel.preco_venda,
        "rentPrice": imovel.preco_aluguel,
        "area": imovel.area,
        "bedrooms": imovel.quartos,
        "bathrooms": imovel.banheiros,
        "parkingSpots": imovel.vagas,
        "type": imovel.tipo,
        "address": imovel.endereco or None,
        "neighbourhood": imovel.bairro or None,
        "condoIptu": None,
        "photos": imovel.fotos or [],
        "amenities": imovel.amenities or [],
        "shortSaleDescription": imovel.titulo or imovel.descricao or "",
    }

    # Build condoIptu object
    if imovel.condominio is not None or imovel.iptu is not None:
        listing["condoIptu"] = {
            "condoFee": imovel.condominio,
            "iptu": imovel.iptu,
        }

    # Try to find the raw listing data in the payload for extra fields
    # that the Imovel schema might have mapped differently
    if raw_payload and imovel.id:
        raw_listing = _find_raw_listing(raw_payload, imovel.id)
        if raw_listing:
            # Use raw shortSaleDescription if available (more idiomatic)
            raw_short = (
                raw_listing.get("shortSaleDescription")
                or raw_listing.get("shortRentDescription")
            )
            if raw_short:
                listing["shortSaleDescription"] = raw_short

            # Use raw address object if available
            raw_addr = raw_listing.get("address")
            if isinstance(raw_addr, dict):
                listing["address"] = raw_addr
            elif not listing["address"]:
                # Build address object from components
                addr_parts = {}
                for k in ("address", "street", "city", "stateCode", "neighborhood", "neighbourhood"):
                    v = raw_listing.get(k)
                    if v:
                        addr_parts[k] = v
                city_slug = raw_listing.get("citySlug")
                if city_slug and "city" not in addr_parts:
                    addr_parts["city"] = " ".join(
                        city_slug.split("-")[:-2]
                    ).replace("-", " ").title() if len(city_slug.split("-")) > 2 else ""
                listing["address"] = addr_parts if addr_parts else None

            # Use raw neighbourhood
            raw_nb = raw_listing.get("neighbourhood") or raw_listing.get("neighborhood") or raw_listing.get("regionName")
            if raw_nb:
                listing["neighbourhood"] = raw_nb

    return listing


def _find_raw_listing(payload: dict, listing_id: str) -> dict | None:
    """Find the raw listing dict by id in a Next.js data route payload."""
    # Navigate to houses dict
    houses = None
    for path in ("pageProps", "props"):
        props = payload.get(path, {})
        if isinstance(props, dict):
            houses = props.get("initialState", {}).get("houses")
            if houses:
                break

    if not houses and "initialState" in payload:
        houses = payload["initialState"].get("houses")
    if not houses and "houses" in payload:
        houses = payload["houses"]

    if isinstance(houses, dict):
        return houses.get(listing_id)

    if isinstance(houses, list):
        for h in houses:
            if isinstance(h, dict) and (str(h.get("id")) == listing_id or str(h.get("listingId")) == listing_id):
                return h

    return None
