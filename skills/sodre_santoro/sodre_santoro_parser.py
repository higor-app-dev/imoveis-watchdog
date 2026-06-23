"""
sodre_santoro_parser — Parser for Sodré Santoro (sodresantoro.com.br) auction listings.

Converts the REST API responses from the prd-api.sodresantoro.com.br endpoint
into the unified Imovel schema used by the watchdog pipeline.

API endpoint (fully open, no auth):
    GET https://prd-api.sodresantoro.com.br/api/v1/auctions?segmentName=imoveis&limit=20&page=1

Response structure:
    {
        "status": 200,
        "data": [
            {
                "id": 28678,              ← auction_id
                "type": 1,                ← 0=extra/unknown, 1=judicial, 2=fiscal
                "closingDate": "2026-07-01 11:00:00",
                "dates": [{"active": true, "value": "..."}],
                "name": "(TJ) - 12ª Vara Cível do Foro Central Cível da Capital/SP",
                "categories": [{"id": 13, "name": "Área de terras", ...}],
                "lots": [
                    {
                        "lot_id": 2763868,
                        "lot_title": "área de terras - siriúba - ilhabela - sp",
                        "lot_pictures": ["https://photos.sodresantoro.com.br/..."],
                        "bid_initial": 16233286,      ← BRL cents
                        "bid_actual": 16233286,        ← BRL cents
                        "tj_praca_value": 8116643,     ← BRL cents
                        "tj_praca_discount": 50,        ← percentage
                        "lot_visits": 4416,
                        "lot_bids": null,
                        "lot_is_financiable": null,
                        "lot_installment": null,
                        "lot_is_property": true,
                    }
                ]
            }
        ]
    }

Functions:
    from_sodre_listing(auction_dict, lot_dict) -> dict
        Convert a single auction+lot pair into unified schema.

    from_sodre_payload(raw) -> list[dict]
        Convert full API response to list of unified dicts.

    fetch_listings() -> list[dict]
        GET from prd-api with pagination, return parsed results.

    _extract_city_state(title) -> dict
        Parse 'apartamento - imirim - são paulo - sp' pattern.

    _parse_price(cents) -> float | None
        Convert BRL cents to float.

    _normalize_photo_url(url) -> str | None
        Strip ?ims resize param from photo URLs for full resolution.

    _generate_resized_url(base_url, size) -> str | None
        Add ?ims={width}x for dynamic CDN resize (thumb/medium/large).

    _generate_all_resolutions(base_url) -> dict | None
        Generate all {original, large, medium, thumb} for one photo.

    _collect_photos(raw_lot) -> list[str]
        Extract and normalize all lot_pictures from API response.

Output fields:
    fotos: list[str]         — All photos at full resolution
    image_urls: list[dict]   — Each photo with all resolutions:
        [{"original": "...", "large": "...", "medium": "...", "thumb": "..."}, ...]
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

# ── Schema import ────────────────────────────────────────────────────────────

_hermes_path = Path.home() / ".hermes"
if str(_hermes_path) not in sys.path:
    sys.path.insert(0, str(_hermes_path))

try:
    from imovel_schema import Imovel
except ImportError:
    Imovel = None

logger = logging.getLogger("sodre_santoro_parser")

# ── Constants ────────────────────────────────────────────────────────────────

API_BASE = "https://prd-api.sodresantoro.com.br/api/v1/auctions"
PHOTO_BASE = "https://photos.sodresantoro.com.br"
DETAIL_BASE = "https://leilao.sodresantoro.com.br"
SEGMENT = "imoveis"
PAGE_SIZE = 20

# Auction type mapping (from API `type` field)
TYPE_MAP = {
    0: "extrajudicial",   # Private/extrajudicial auctions (client name, no court)
    1: "judicial",        # TJ = Tribunal de Justiça
    2: "fiscal",          # SEF = Setor de Execuções Fiscais
}

# ── Field mapping: normalized dict -> Imovel schema ──────────────────────────

FIELD_MAP = {
    "id": "id",
    "titulo": "titulo",
    "url": "url",
    "fonte": "fonte",
    "preco_venda": "preco_venda",
    "preco_anterior": "preco_anterior",
    "area": "area",
    "tipo": "tipo",
    "bairro": "bairro",
    "cidade": "cidade",
    "uf": "uf",
    "descricao": "descricao",
    "fotos": "fotos",
    "data_publicacao": "data_publicacao",
    "data_coleta": "data_coleta",
    "disponivel": "disponivel",
    # Auction-specific fields
    "auction_id": "auction_id",
    "auction_type": "auction_type",
    "closing_date": "closing_date",
    "auctioneer": "auctioneer",
    "court_name": "court_name",
    "bid_initial": "bid_initial",
    "bid_actual": "bid_actual",
    "tj_praca_value": "tj_praca_value",
    "tj_praca_discount": "tj_praca_discount",
    "lot_visits": "lot_visits",
    "lot_bids": "lot_bids",
    "lot_id": "lot_id",
    "financiable": "financiable",
    "installment": "installment",
}

# ── Photo URL normalization ──────────────────────────────────────────────────

# Available resize sizes via Azion Image Processing (`?ims=` parameter)
RESIZE_SIZES = {
    "thumb": "300x",    # ~17KB — gallery thumbnails
    "medium": "916x",   # ~160KB — detail page gallery
    "large": "1920x",   # ~500KB — lightbox / original-like
}


def _normalize_photo_url(url: Any) -> str | None:
    """Normalize a Sodré Santoro photo URL to full resolution.

    Handles:
    - Already absolute URL → strip ?ims resize parameter
    - Relative URL → prepend PHOTO_BASE
    - None / empty → return None

    Args:
        url: Raw photo URL from API.

    Returns:
        Absolute URL string without resize params, or None if invalid.
    """
    if not url:
        return None
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()

    # Already absolute HTTP(S) URL
    if url.startswith("http://") or url.startswith("https://"):
        # Strip ?ims=... query param for full resolution
        parsed = urlparse(url)
        if parsed.query and "ims=" in parsed.query:
            # Strip all query params (ims is the only one used)
            clean = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                "",       # drop query string
                parsed.fragment,
            ))
            return clean
        return url

    # Relative URL → prepend photo base
    relative = url.lstrip("/")
    return f"{PHOTO_BASE}/{relative}"


def _generate_resized_url(base_url: str, size: str) -> str | None:
    """Generate a resized version of a photo URL using Azion Image Processing.

    The CDN at photos.sodresantoro.com.br supports dynamic on-the-fly resize
    via the ``?ims={width}x`` query parameter (Azion Image Processing).

    Available sizes:
        - ``thumb``: ``?ims=300x`` (~17KB, ~300px wide)
        - ``medium``: ``?ims=916x`` (~160KB, ~916px wide)
        - ``large``: ``?ims=1920x`` (~500KB, ~1920px wide)

    Args:
        base_url: The full-resolution photo URL (output of _normalize_photo_url).
        size: One of ``thumb``, ``medium``, ``large``.

    Returns:
        URL string with resize parameter, or None if invalid.
    """
    if not base_url or not isinstance(base_url, str):
        return None
    if size not in RESIZE_SIZES:
        return None

    return f"{base_url}?ims={RESIZE_SIZES[size]}"


def _generate_all_resolutions(base_url: str) -> dict[str, str] | None:
    """Generate all available resolutions for a photo URL.

    Args:
        base_url: The full-resolution photo URL.

    Returns:
        Dict with keys ``original``, ``large``, ``medium``, ``thumb``,
        each mapping to the respective URL, or None if input is invalid.
    """
    if not base_url or not isinstance(base_url, str):
        return None

    result = {"original": base_url}
    for size_name in RESIZE_SIZES:
        resized = _generate_resized_url(base_url, size_name)
        if resized:
            result[size_name] = resized
    return result


def _collect_photos(raw_lot: dict) -> list[str]:
    """Extract and normalize all photo URLs from a lot dict.

    Source: `lot_pictures` array from the API.

    Args:
        raw_lot: The lot dict from the API response.

    Returns:
        Deduplicated list of absolute CDN URLs at full resolution.
    """
    seen: set[str] = set()
    urls: list[str] = []

    raw_pics = raw_lot.get("lot_pictures") or []
    if isinstance(raw_pics, list):
        for p in raw_pics:
            normalized = _normalize_photo_url(p)
            if normalized and normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)

    return urls


# ── Price parsing ────────────────────────────────────────────────────────────


def _parse_price(cents: Any) -> float | None:
    """Convert BRL cents to float (R$).

    Args:
        cents: Integer value in BRL cents (e.g. 16233286 → R$ 162.332,86).

    Returns:
        Float value in R$, or None if invalid.
    """
    if cents is None:
        return None
    try:
        val = float(cents)
        if val < 0:
            return None
        return val / 100.0
    except (ValueError, TypeError):
        return None


# ── City/State extraction from title ─────────────────────────────────────────


def _extract_city_state(title: str | None) -> dict:
    """Parse city, state, neighborhood, and property type from lot title.

    Title format follows: "{property_type} - {neighborhood} - {city} - {state}"
    e.g. "apartamento - imirim - são paulo - sp"
         "imóvel residencial tipo sobrado - jardim dos estados - santo amaro - sp"
         "salão anexo - depósito - bela vista - são paulo - sp"

    Logic:
    - Last segment (split by ' - ') = state (UF, 2 chars)
    - Second-to-last = city
    - Third-to-last = neighborhood
    - All preceding segments joined = property type

    Args:
        title: Raw lot_title string from API.

    Returns:
        dict with keys: tipo, bairro, cidade, uf (all lowercase strings).
    """
    result = {"tipo": "", "bairro": "", "cidade": "", "uf": ""}

    if not title or not isinstance(title, str) or not title.strip():
        return result

    parts = [p.strip() for p in title.split(" - ")]
    parts = [p for p in parts if p]

    if len(parts) >= 4:
        # Last three: neighborhood, city, state
        result["uf"] = parts[-1].lower().strip()
        result["cidade"] = parts[-2].lower().strip()
        result["bairro"] = parts[-3].lower().strip()
        # Everything before the last three is the property type
        result["tipo"] = " - ".join(parts[:-3]).lower().strip()
    elif len(parts) == 3:
        # Fallback: neighborhood, city, state
        result["uf"] = parts[-1].lower().strip()
        result["cidade"] = parts[-2].lower().strip()
        result["bairro"] = parts[-3].lower().strip()
    elif len(parts) == 2:
        result["cidade"] = parts[-2].lower().strip()
        result["uf"] = parts[-1].lower().strip()
        result["tipo"] = parts[0].lower().strip()
    elif len(parts) == 1:
        result["tipo"] = parts[0].lower().strip()

    return result


# ── Detail URL construction ──────────────────────────────────────────────────


def _build_detail_url(auction_id: int | str, lot_id: int | str) -> str:
    """Build the auction detail URL from auction and lot IDs.

    Args:
        auction_id: The auction ID.
        lot_id: The lot ID.

    Returns:
        Full URL string.
    """
    return f"{DETAIL_BASE}/{auction_id}/{lot_id}"


# ── Type helper ──────────────────────────────────────────────────────────────


def _map_auction_type(api_type: int | None) -> str:
    """Map API type integer to human-readable string.

    Args:
        api_type: Integer type from API (0, 1, 2).

    Returns:
        String: 'judicial', 'extrajudicial', 'fiscal', or 'desconhecido'.
    """
    if api_type is None:
        return "desconhecido"
    return TYPE_MAP.get(api_type, "desconhecido")


# ── Single listing parser ────────────────────────────────────────────────────


def from_sodre_listing(auction: dict, lot: dict) -> dict | Any | None:
    """Convert a single auction+lot pair to unified Imovel schema.

    Args:
        auction: The auction-level dict from the API response.
        lot: The lot-level dict from the auction's `lots` array.

    Returns:
        Dict in the unified Imovel schema, or None if input is invalid.
    """
    if not auction or not isinstance(auction, dict):
        return None
    if not lot or not isinstance(lot, dict):
        return None

    # Don't process lots that aren't properties
    if lot.get("lot_is_property") is False:
        return None

    # Skip lots without a title (extrajudicial/private auctions with no data)
    if not lot.get("lot_title"):
        return None

    # ── Extract from title ─────────────────────────────────────────────
    title = lot.get("lot_title") or ""
    parsed = _extract_city_state(title)

    # ── Build detail URL ───────────────────────────────────────────────
    auction_id = auction.get("id")
    lot_id = lot.get("lot_id")
    detail_url = _build_detail_url(auction_id, lot_id) if auction_id and lot_id else ""

    # ── Prices ─────────────────────────────────────────────────────────
    bid_initial = _parse_price(lot.get("bid_initial"))
    bid_actual = _parse_price(lot.get("bid_actual"))
    tj_praca = _parse_price(lot.get("tj_praca_value"))
    tj_discount = lot.get("tj_praca_discount")  # percentage, keep as is

    # Use bid_actual as the primary sale price (current highest bid)
    sale_price = bid_actual or bid_initial

    # ── Auction type ───────────────────────────────────────────────────
    auction_type = _map_auction_type(auction.get("type"))

    # ── Dates ──────────────────────────────────────────────────────────
    closing_date = auction.get("closingDate", "")
    # Normalize date format: "2026-07-01 11:00:00" → ISO 8601
    if closing_date and isinstance(closing_date, str) and " " in closing_date:
        try:
            dt = datetime.strptime(closing_date, "%Y-%m-%d %H:%M:%S")
            closing_date = dt.isoformat()
        except ValueError:
            pass

    # ── Collect photos ────────────────────────────────────────────────
    fotos = _collect_photos(lot)

    # Build structured image_urls with all resolutions
    image_urls: list[dict[str, str]] = []
    for foto_url in fotos:
        resolutions = _generate_all_resolutions(foto_url)
        if resolutions:
            image_urls.append(resolutions)

    # ── Court name ─────────────────────────────────────────────────────
    court_name = auction.get("name", "")

    # ── Build mapped dict ──────────────────────────────────────────────
    mapped = {
        "id": f"sodre_{auction_id}_{lot_id}",
        "titulo": title,
        "url": detail_url,
        "fonte": "sodre_santoro",
        "preco_venda": sale_price,
        "preco_anterior": tj_praca,  # avaliação judicial ("preço de praça")
        "area": None,
        "tipo": parsed["tipo"],
        "bairro": parsed["bairro"],
        "cidade": parsed["cidade"],
        "uf": parsed["uf"],
        "descricao": lot.get("lot_description") or "",
        "fotos": fotos,
        "image_urls": image_urls,  # structured: [{"original":..., "large":..., "medium":..., "thumb":...}, ...]
        "data_publicacao": closing_date,
        "data_coleta": datetime.now(timezone.utc).isoformat(),
        "disponivel": True,
        # Auction-specific fields
        "auction_id": auction_id,
        "lot_id": lot_id,
        "auction_type": auction_type,
        "closing_date": closing_date,
        "auctioneer": auction.get("auctioneer", ""),
        "court_name": court_name,
        "bid_initial": bid_initial,
        "bid_actual": bid_actual,
        "tj_praca_value": tj_praca,
        "tj_praca_discount": tj_discount,
        "lot_visits": lot.get("lot_visits"),
        "lot_bids": lot.get("lot_bids"),
        "financiable": lot.get("lot_is_financiable"),
        "installment": lot.get("lot_installment"),
    }

    # ── Validate via Imovel schema (if available), but return full dict ──
    # Auction-specific fields (auction_type, tj_praca_*, etc.) are not part
    # of the base Imovel schema — we always return the full mapped dict
    # so downstream consumers have access to all auction data.
    if Imovel is not None:
        try:
            # Validate — raises on critical errors, logs warnings otherwise
            imovel = Imovel.from_dict(mapped)
            errors = imovel.validate()
            if errors:
                logger.debug(
                    f"Imovel validation warnings for {mapped['id']}: {errors}"
                )
        except Exception as e:
            logger.warning(f"Erro ao criar/validar Imovel: {e}")

    return mapped


# ── Payload parser ───────────────────────────────────────────────────────────


def from_sodre_payload(raw: Any) -> list[dict]:
    """Convert full Sodré Santoro API response to list of unified Imovel dicts.

    Handles:
    - Full API response dict with "data" key
    - Raw list of auctions
    - JSON string

    Args:
        raw: The API response (dict, list, or JSON string).

    Returns:
        List of dicts in the unified Imovel schema.
    """
    # Accept JSON string
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Payload inválido: não é JSON válido")
            return []

    # Extract data array from response wrapper
    if isinstance(raw, dict):
        raw = raw.get("data", raw)

    if not isinstance(raw, list):
        logger.warning(
            f"Payload inesperado: esperava list, recebeu {type(raw).__name__}"
        )
        return []

    imoveis: list[dict] = []
    for auction in raw:
        if not isinstance(auction, dict):
            continue
        lots = auction.get("lots") or []
        if not isinstance(lots, list):
            continue
        for lot in lots:
            imovel = from_sodre_listing(auction, lot)
            if imovel:
                imoveis.append(imovel)

    logger.info(
        f"Parsed {len(imoveis)} listings from Sodré Santoro payload "
        f"({len(raw)} auctions)"
    )
    return imoveis


# ── API fetcher ──────────────────────────────────────────────────────────────


def fetch_listings(
    limit: int = PAGE_SIZE,
    max_pages: int = 5,
    timeout: int = 30,
) -> list[dict]:
    """Fetch listings directly from the Sodré Santoro API.

    The API is fully open — no authentication or rate limiting detected.
    Endpoint: GET https://prd-api.sodresantoro.com.br/api/v1/auctions
    Query params: segmentName=imoveis, limit, page

    Args:
        limit: Items per page (default: 20).
        max_pages: Maximum pages to fetch (default: 5).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of dicts in the unified Imovel schema.

    Raises:
        RuntimeError: If the HTTP request fails repeatedly.
    """
    import urllib.request
    import urllib.error

    user_agent = "imoveis-watchdog/1.0"
    headers = {"User-Agent": user_agent}

    all_imoveis: list[dict] = []
    seen_ids: set[str] = set()
    consecutive_empties = 0
    consecutive_duplicates = 0

    for page in range(1, max_pages + 1):
        url = f"{API_BASE}?segmentName={SEGMENT}&limit={limit}&page={page}"
        logger.info(f"Fetching page {page}: {url}")

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            logger.error(f"HTTP error on page {page}: {e}")
            if page == 1:
                raise RuntimeError(
                    f"Falha ao acessar API Sodré Santoro na página 1: {e}"
                )
            break
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"JSON decode error on page {page}: {e}")
            if page == 1:
                raise RuntimeError(
                    f"API retornou JSON inválido na página 1: {e}"
                )
            break
        except OSError as e:
            logger.error(f"Network error on page {page}: {e}")
            if page == 1:
                raise RuntimeError(
                    f"Erro de rede ao acessar API Sodré Santoro: {e}"
                )
            break

        imoveis_page = from_sodre_payload(data)

        if not imoveis_page:
            consecutive_empties += 1
            if consecutive_empties >= 2:
                logger.info(
                    f"Duas páginas consecutivas vazias — encerrando "
                    f"(page={page})"
                )
                break
        else:
            consecutive_empties = 0
            # Deduplicate — skip already-seen listings
            new_imoveis = []
            for imovel in imoveis_page:
                imovel_id = str(imovel.get("id") or "")
                if not imovel_id or imovel_id in seen_ids:
                    continue
                seen_ids.add(imovel_id)
                new_imoveis.append(imovel)

            if not new_imoveis:
                consecutive_duplicates += 1
                if consecutive_duplicates >= 1:
                    logger.info(
                        f"Página {page} só trouxe duplicatas — "
                        f"encerrando paginação"
                    )
                    break
            else:
                consecutive_duplicates = 0
                all_imoveis.extend(new_imoveis)
                logger.info(
                    f"Page {page}: {len(imoveis_page)} listings "
                    f"({len(new_imoveis)} new, total: {len(all_imoveis)})"
                )

    logger.info(
        f"Fetched {len(all_imoveis)} listings from Sodré Santoro "
        f"({len(raw_data := [])} pages)"  # rough count placeholder
    )
    return all_imoveis


# ── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI for testing the Sodré Santoro parser directly.

    Usage:
        python sodre_santoro_parser.py fetch [--pages N] [--output FILE]
        python sodre_santoro_parser.py parse <input.json>
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Sodré Santoro Parser — teste e execução"
    )
    sub = parser.add_subparsers(dest="command")

    # fetch: calls the API
    fetch_parser = sub.add_parser("fetch", help="Busca listings da API")
    fetch_parser.add_argument("--pages", type=int, default=3)
    fetch_parser.add_argument("--output", help="Salvar JSON em arquivo")

    # parse: parseia arquivo JSON já baixado
    parse_parser = sub.add_parser("parse", help="Parseia um arquivo JSON da API")
    parse_parser.add_argument("input_file", help="Caminho do JSON")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if args.command == "fetch":
        imoveis = fetch_listings(max_pages=args.pages)
        print(f"\nExtraídos {len(imoveis)} imóveis da API Sodré Santoro")
        if imoveis:
            precos = [
                i.get("preco_venda", 0) or 0
                for i in imoveis
                if i.get("preco_venda")
            ]
            if precos:
                print(
                    f"  Preços: R$ {min(precos):.2f} ~ R$ {max(precos):.2f}"
                )
            print(f"  Cidades: {len(set(i.get('cidade', '') for i in imoveis if i.get('cidade')))}")
            print(f"  Tipos de leilão: {set(i.get('auction_type', '') for i in imoveis)}")
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w") as f:
                json.dump(imoveis, f, indent=2, ensure_ascii=False)
            print(f"  Salvo em: {args.output}")

    elif args.command == "parse":
        with open(args.input_file) as f:
            data = json.load(f)
        imoveis = from_sodre_payload(data)
        print(
            f"Parseados {len(imoveis)} imóveis de {args.input_file}"
        )
        if imoveis:
            print(
                f"  Amostra: {imoveis[0]['titulo']} — "
                f"R$ {imoveis[0].get('preco_venda', 'N/A')}"
            )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
