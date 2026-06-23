#!/usr/bin/env python3
"""
crawl.py — Full EmCasa crawl orchestration.

Iterates over cities (sp, rj), paginates through all Algolia pages,
parses hits into the unified schema, optionally filters, and saves
to a timestamped JSON file.

Usage:
    python crawl.py                                    # Full crawl (SP + RJ)
    python crawl.py --city sp                          # Only São Paulo
    python crawl.py --city rj --listing-type rent      # Only Rio, rentals
    python crawl.py --min-price 500000 --max-price 1500000
    python crawl.py --neighborhood "Pinheiros,Vila Mariana"
    python crawl.py --output data/emcasa_crawl.json    # Custom output path
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# ── Add imoveis-watchdog project root to path ─────────────────────────────
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
# Find the imoveis-watchdog directory relative to this project
# The workspace is under ~/.hermes/kanban/boards/imoveis-watchdog/workspaces/t_xxx
# The imoveis-watchdog project is at ~/imoveis-watchdog
WATCHDOG_DIR = os.path.expanduser("~/imoveis-watchdog")
if WATCHDOG_DIR not in sys.path:
    sys.path.insert(0, WATCHDOG_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("crawl")

# ── Imports (after sys.path manipulation) ─────────────────────────────────
try:
    from skills.emcasa.extract_page import extract_page, VALID_CITIES
    from skills.emcasa.algolia_parser import parse_hit as algolia_parse_hit, parse_hits as algolia_parse_hits
except ImportError as e:
    logger.error(f"Failed to import emcasa skills: {e}")
    logger.error("Make sure imoveis-watchdog is at ~/imoveis-watchdog")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────
DEFAULT_RATE_LIMIT = 1.0  # seconds between requests
DEFAULT_OUTPUT_DIR = os.path.join(WATCHDOG_DIR, "data", "results")


# ── Filtering ─────────────────────────────────────────────────────────────

def apply_filters(
    hit: dict,
    listing_type: str | None = None,
    neighborhood: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> bool:
    """
    Apply optional filters to a parsed hit.

    Returns True if the hit passes all filters (include it),
    False if it should be excluded.
    """
    # listing_type filter (sale / rent)
    if listing_type:
        hit_type = (hit.get("listing_type") or "").lower().strip()
        expected = listing_type.lower().strip()
        if hit_type != expected:
            return False

    # neighborhood filter (comma-separated, OR semantics)
    if neighborhood:
        hit_neighborhood = (hit.get("location_neighborhood") or "").lower().strip()
        allowed = [n.strip().lower() for n in neighborhood.split(",") if n.strip()]
        if not any(hit_neighborhood == a for a in allowed):
            return False

    # price range
    price = hit.get("price")
    if price is not None:
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False

    return True


# ── Crawl logic ───────────────────────────────────────────────────────────

def get_page_info(city: str, page: int) -> tuple[list[dict], int, int] | tuple[None, None, None]:
    """
    Fetch one page and return (hits, nb_hits, nb_pages).

    Returns (None, None, None) on error.
    """
    data = extract_page(city, page)
    if data is None:
        return None, None, None

    results = data.get("properties", {}).get("results", [])
    if not results:
        logger.warning(f"No 'results' in response for {city} p.{page}")
        return [], 0, 0

    r0 = results[0]
    hits = r0.get("hits", [])
    nb_hits = r0.get("nbHits", 0)
    nb_pages = r0.get("nbPages", 0)
    return hits, nb_hits, nb_pages


def crawl_city(
    city: str,
    filters: dict[str, Any] | None = None,
    rate_limit: float = DEFAULT_RATE_LIMIT,
) -> list[dict]:
    """
    Crawl all pages for a given city.

    Args:
        city: City code ('sp' or 'rj').
        filters: Optional dict with keys: listing_type, neighborhood, min_price, max_price.
        rate_limit: Seconds between requests.

    Returns:
        List of parsed hits (unified schema) matching filters.
    """
    filters = filters or {}
    city_name = VALID_CITIES.get(city, city.upper())
    all_parsed: list[dict] = []
    errors = 0

    # ── Page 0: determine total pages ─────────────────────────────────────
    logger.info(f"[{city_name}] Fetching page 0...")
    hits, nb_hits, nb_pages = get_page_info(city, 0)

    if hits is None:
        logger.error(f"[{city_name}] Failed to fetch page 0 — skipping city")
        return []

    if nb_pages == 0:
        logger.info(f"[{city_name}] No listings found")
        return []

    total_pages = nb_pages
    logger.info(
        f"[{city_name}] Total: {nb_hits} listings across {total_pages} pages "
        f"(hitsPerPage: {len(hits)})"
    )

    # ── Page 0 results ────────────────────────────────────────────────────
    logger.info(f"[{city_name}] Parsing page 0/{total_pages}...")
    for hit_raw in hits:
        try:
            parsed = algolia_parse_hit(hit_raw)
            if apply_filters(parsed, **filters):
                all_parsed.append(parsed)
        except Exception as e:
            logger.warning(f"[{city_name}] Error parsing hit on page 0: {e}")
            errors += 1

    # ── Remaining pages ───────────────────────────────────────────────────
    for page_num in range(1, total_pages):
        time.sleep(rate_limit)
        logger.info(f"[{city_name}] Fetching page {page_num}/{total_pages}...")

        try:
            hits_page, _, _ = get_page_info(city, page_num)
            if hits_page is None:
                logger.warning(f"[{city_name}] Failed page {page_num} — skipping")
                errors += 1
                continue
        except Exception as e:
            logger.warning(f"[{city_name}] Error on page {page_num}: {e}")
            errors += 1
            continue

        logger.info(
            f"[{city_name}] Parsing page {page_num}/{total_pages} ({len(hits_page)} hits)..."
        )
        for hit_raw in hits_page:
            try:
                parsed = algolia_parse_hit(hit_raw)
                if apply_filters(parsed, **filters):
                    all_parsed.append(parsed)
            except Exception as e:
                logger.warning(f"[{city_name}] Error parsing hit on page {page_num}: {e}")
                errors += 1

    logger.info(
        f"[{city_name}] Done — {len(all_parsed)} listings after filters "
        f"({errors} errors)"
    )
    return all_parsed


# ── Main ──────────────────────────────────────────────────────────────────

def build_output_path(output: str | None, cities: list[str]) -> str:
    """Build the output file path."""
    if output:
        return output

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    city_suffix = "_".join(cities) if cities else "all"
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    return os.path.join(DEFAULT_OUTPUT_DIR, f"emcasa_crawl_{city_suffix}_{ts}.json")


def main():
    parser = argparse.ArgumentParser(
        description="Full EmCasa crawl — iterate all cities, save to JSON"
    )
    parser.add_argument(
        "--city", "-c",
        type=str,
        default=None,
        help="City code: sp, rj, or comma-separated (default: both)",
    )
    parser.add_argument(
        "--listing-type", "-t",
        type=str,
        choices=["sale", "rent"],
        default=None,
        help="Filter by listing type (sale/rent)",
    )
    parser.add_argument(
        "--neighborhood", "-n",
        type=str,
        default=None,
        help="Filter by neighborhood(s) — comma-separated, OR logic",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=None,
        help="Minimum price filter",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=None,
        help="Maximum price filter",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=DEFAULT_RATE_LIMIT,
        help=f"Seconds between requests (default: {DEFAULT_RATE_LIMIT})",
    )

    args = parser.parse_args()

    # Determine cities to crawl
    if args.city:
        cities = [c.strip().lower() for c in args.city.split(",") if c.strip()]
        invalid = [c for c in cities if c not in VALID_CITIES]
        if invalid:
            parser.error(f"Invalid city code(s): {', '.join(invalid)}. Use: {', '.join(VALID_CITIES)}")
    else:
        cities = sorted(VALID_CITIES.keys())

    logger.info("=" * 60)
    logger.info("EmCasa Full Crawl — starting")
    logger.info(f"Cities: {', '.join(cities)}")
    active_filters = {k: v for k, v in {
        "listing_type": args.listing_type,
        "neighborhood": args.neighborhood,
        "min_price": args.min_price,
        "max_price": args.max_price,
    }.items() if v is not None}
    logger.info(f"Filters: {json.dumps(active_filters, ensure_ascii=False)}")
    logger.info(f"Rate limit: {args.rate_limit}s")
    logger.info("=" * 60)

    start_time = time.time()
    all_listings: list[dict] = []

    for city in cities:
        all_listings.extend(
            crawl_city(
                city,
                filters={
                    "listing_type": args.listing_type,
                    "neighborhood": args.neighborhood,
                    "min_price": args.min_price,
                    "max_price": args.max_price,
                },
                rate_limit=args.rate_limit,
            )
        )

    elapsed = time.time() - start_time

    # ── Save ──────────────────────────────────────────────────────────────
    output_path = build_output_path(args.output, cities)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    crawl_meta = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "cities": cities,
        "filters_applied": {
            "listing_type": args.listing_type,
            "neighborhood": args.neighborhood,
            "min_price": args.min_price,
            "max_price": args.max_price,
        },
        "total_listings": len(all_listings),
        "elapsed_seconds": round(elapsed, 1),
        "listing_type_counts": {},
    }

    # Count by listing_type for the metadata
    for l in all_listings:
        lt = l.get("listing_type", "unknown")
        crawl_meta["listing_type_counts"][lt] = crawl_meta["listing_type_counts"].get(lt, 0) + 1

    result = {
        "meta": crawl_meta,
        "listings": all_listings,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("=" * 60)
    logger.info(f"Finished — {len(all_listings)} total listings")
    logger.info(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")
    if all_listings:
        logger.info(f"Types: {json.dumps(crawl_meta['listing_type_counts'], ensure_ascii=False)}")
    logger.info(f"Saved to: {output_path}")
    logger.info("=" * 60)

    return output_path, len(all_listings)


if __name__ == "__main__":
    main()
