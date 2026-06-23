#!/usr/bin/env python3
"""
emcasa_collect.py — Unified EmCasa data collection driver.

Reads configuration from watchdog.yaml, iterates all configured cities,
neighborhoods, and price ranges, collects listings via the EmCasa API,
using the external PaginatedCache (cache_engine) and TokenBucket (rate_limiter)
for efficient and safe crawling.

Usage:
    python scripts/emcasa_collect.py                           # full crawl
    python scripts/emcasa_collect.py --dry-run                  # show what would be done
    python scripts/emcasa_collect.py --max-pages 2             # limit pages per region (test)
    python scripts/emcasa_collect.py --city "São Paulo"        # single city
    python scripts/emcasa_collect.py --output results.json     # custom output path
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Project root discovery ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

# ── Imports ─────────────────────────────────────────────────────────────────
from skills.cache.cache_engine import PaginatedCache, NullCache, create_cache
from skills.rate_limiter.rate_limiter import TokenBucket

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("emcasa_collect")

# ── Constants ───────────────────────────────────────────────────────────────
EMCASA_CACHE_DIR = PROJECT_ROOT / "data" / "emcasa_cache"
RESULTS_DIR = PROJECT_ROOT / "data" / "results"
EMCASA_RATE_LIMIT = 2.0  # requests per second (conservative for EmCasa API)
EMCASA_BURST = 3          # allow short bursts
DEFAULT_PER_PAGE = 250    # max per_page for efficiency


def build_emcasa_filters(city: str, uf: str = "SP") -> str:
    """Build the filter_by string for the EmCasa API."""
    from skills.emcasa.emcasa_api import filter_city
    return filter_city(city, uf)


def load_config(config_path: str | Path | None = None) -> dict:
    """Load and return the watchdog configuration.

    Searches:
      1. Explicit path
      2. $HERMES_WATCHDOG_CONFIG
      3. ~/.hermes/watchdog.yaml
      4. ./watchdog.yaml
    """
    if config_path is not None:
        path = Path(config_path)
    else:
        env_path = os.environ.get("HERMES_WATCHDOG_CONFIG")
        if env_path:
            path = Path(env_path)
        else:
            home_config = Path.home() / ".hermes" / "watchdog.yaml"
            local_config = PROJECT_ROOT / "watchdog.yaml"
            if home_config.exists():
                path = home_config
            elif local_config.exists():
                path = local_config
            else:
                raise FileNotFoundError(
                    "watchdog.yaml not found. Set HERMES_WATCHDOG_CONFIG "
                    "or place the file at ~/.hermes/watchdog.yaml or ./watchdog.yaml"
                )

    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "watchdog" not in data:
        raise ValueError(f"Invalid config in {path}: missing 'watchdog' key")

    return data["watchdog"]


def expand_targets(config: dict) -> list[dict]:
    """Expand all search combinations (city × neighborhood × price_range).

    Returns a list of target dicts with:
        city, uf, neighborhood (or None), price_min, price_max, price_label
    """
    cities = config.get("cities", [])
    neighborhoods = config.get("neighborhoods", [])
    price_ranges = config.get("price_ranges", [])

    # Group neighborhoods by city
    hoods_by_city: dict[str, list[str]] = {}
    for n in neighborhoods:
        hoods_by_city.setdefault(n["city"], []).append(n["name"])

    targets = []
    for city in cities:
        city_name = city["name"]
        uf = city.get("uf", city.get("state", "SP"))
        hoods = hoods_by_city.get(city_name, [None])

        for hood in hoods:
            for pr in price_ranges:
                targets.append({
                    "city": city_name,
                    "uf": uf,
                    "neighborhood": hood,
                    "price_min": pr["min"],
                    "price_max": pr["max"],
                    "price_label": pr["label"],
                })

    return targets


def collect_region(
    client: Any,
    city: str,
    uf: str,
    neighborhood: str | None,
    price_min: float | None,
    price_max: float | None,
    max_pages: int | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Collect all listings for a specific city + region combination.

    Args:
        client: Configured EmCasaClient instance.
        city: City name (e.g. "São Paulo").
        uf: State code (e.g. "SP").
        neighborhood: Optional neighborhood filter.
        price_min: Minimum price filter (applied post-fetch).
        price_max: Maximum price filter (applied post-fetch).
        max_pages: Limit total pages fetched (None = all).
        dry_run: If True, only log what would be done.

    Returns:
        List of parsed listing dicts in the unified schema.
    """
    from skills.emcasa.emcasa_api import (
        EmCasaClient,
        filter_city,
        filter_neighborhood,
        parse_hit,
        EmCasaAPIError,
    )

    # Build filter
    if neighborhood:
        filter_by = filter_neighborhood(neighborhood, city, uf)
        region_label = f"{city}/{neighborhood}"
    else:
        filter_by = filter_city(city, uf)
        region_label = city

    if dry_run:
        logger.info(f"  [DRY-RUN] Would fetch: {region_label} | {filter_by}")
        return []

    # First page — discover total
    logger.info(f"  Fetching page 1...")
    try:
        first = client.search_page(filter_by, page=1, per_page=DEFAULT_PER_PAGE)
    except EmCasaAPIError as e:
        logger.error(f"  ✗ Failed to fetch first page: {e}")
        return []

    total_found = first.found
    nb_pages = first.nb_pages
    logger.info(f"  Total: {total_found} listings across {nb_pages} pages")

    if total_found == 0:
        return []

    # Apply max_pages limit
    if max_pages is not None:
        nb_pages = min(nb_pages, max_pages)
        if nb_pages < first.nb_pages:
            logger.info(f"  Limited to {nb_pages} pages (max_pages={max_pages})")

    if nb_pages == 0:
        return []

    # Collect all pages
    all_raw = []
    errors = 0

    for page in range(1, nb_pages + 1):
        try:
            result = client.search_page(filter_by, page=page, per_page=DEFAULT_PER_PAGE)
            all_raw.extend(result.hits)
            logger.info(
                f"  Page {page}/{nb_pages} — {len(result.hits)} hits "
                f"(total: {len(all_raw)})"
            )
        except EmCasaAPIError as e:
            logger.error(f"  ✗ Error on page {page}: {e}")
            errors += 1
            continue

    # Parse into unified schema
    parsed = []
    parse_errors = 0
    for hit in all_raw:
        try:
            listing = parse_hit(hit)
            parsed.append(listing)
        except Exception as e:
            parse_errors += 1
            logger.debug(f"  Parse error: {e}")

    # Apply price filters (in case API doesn't support them natively)
    if price_min is not None or price_max is not None:
        before = len(parsed)
        filtered = []
        for listing in parsed:
            price = listing.get("preco_venda")
            if price is None:
                continue
            if price_min is not None and price < price_min:
                continue
            if price_max is not None and price > price_max:
                continue
            filtered.append(listing)
        parsed = filtered
        logger.info(f"  Price filter: {before} → {len(parsed)} listings")

    # Neighborhood post-filter (EmCasa API might return broader results)
    if neighborhood:
        before = len(parsed)
        hood_lower = neighborhood.lower()
        parsed = [
            l for l in parsed
            if l.get("bairro", "").lower() == hood_lower
        ]
        if len(parsed) < before:
            logger.info(f"  Neighborhood filter: {before} → {len(parsed)} listings")

    if errors:
        logger.warning(f"  {errors} page errors, {parse_errors} parse errors")

    logger.info(f"  Done — {len(parsed)} valid listings")
    return parsed


def save_results(
    results: dict[str, Any],
    output_path: str | Path | None = None,
) -> Path:
    """Save aggregated results to a timestamped JSON file."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = RESULTS_DIR / f"emcasa_collect_{ts}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"Saved to: {output_path}")
    return Path(output_path)


def run_collection(
    config_path: str | Path | None = None,
    dry_run: bool = False,
    max_pages: int | None = None,
    city_filter: str | None = None,
    output_path: str | Path | None = None,
    no_notify: bool = False,
) -> int:
    """Run the full EmCasa data collection pipeline.

    Returns exit code (0 = success).
    """
    start = time.time()
    logger.info("=" * 60)
    logger.info("EmCasa Collection Driver")
    logger.info(f"Start: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)

    # 1. Load config
    logger.info("\n[1/5] Loading configuration...")
    try:
        config = load_config(config_path)
        targets = expand_targets(config)
        cache_config = config.get("cache", {})
        logger.info(f"  ✓ {len(targets)} targets expanded")
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"  ✗ {e}")
        return 1

    if city_filter:
        targets = [t for t in targets if t["city"].lower() == city_filter.lower()]
        logger.info(f"  Filtered to {len(targets)} targets for city '{city_filter}'")

    # 2. Initialize cache
    logger.info("\n[2/5] Initializing cache...")
    page_cache = create_cache(cache_config)
    cache_status = "active" if isinstance(page_cache, PaginatedCache) else "disabled"
    logger.info(f"  ✓ PaginatedCache ({cache_status})")

    if isinstance(page_cache, PaginatedCache):
        cache_dir = str(page_cache._cache_dir)
        logger.info(f"  Cache dir: {cache_dir}")

    # 3. Initialize rate limiter
    logger.info("\n[3/5] Initializing rate limiter...")
    rate_limiter = TokenBucket(rate=EMCASA_RATE_LIMIT, burst=EMCASA_BURST)
    logger.info(f"  ✓ TokenBucket (rate={EMCASA_RATE_LIMIT}/s, burst={EMCASA_BURST})")

    # 4. Initialize EmCasa client
    logger.info("\n[4/5] Initializing EmCasa client...")
    from skills.emcasa.emcasa_api import EmCasaClient

    client = EmCasaClient(
        delay=1.0 / EMCASA_RATE_LIMIT,  # fallback if rate_limiter not used
        rate_limiter=rate_limiter,
        paginated_cache=page_cache if isinstance(page_cache, PaginatedCache) else None,
    )
    logger.info("  ✓ EmCasaClient ready")

    # 5. Collect for each target
    logger.info("\n[5/5] Collecting listings...")
    all_regions: dict[str, Any] = {}
    total_listings = 0

    # Group targets by (city, uf) to avoid duplicate city-wide fetches
    # When a city has neighborhoods configured, we fetch by neighborhood
    # When it doesn't, we fetch the whole city and apply price filter
    city_neighborhoods: dict[str, list[str]] = {}
    for t in targets:
        if t["neighborhood"]:
            city_neighborhoods.setdefault(t["city"], []).append(t["neighborhood"])

    for target in targets:
        city = target["city"]
        uf = target["uf"]
        neighborhood = target["neighborhood"]
        price_label = target["price_label"]
        price_min = target["price_min"]
        price_max = target["price_max"]

        region_key = f"{city}|{neighborhood or 'all'}|{price_label}"

        logger.info(f"\n  {'─' * 50}")
        label = f"{city}"
        if neighborhood:
            label += f" / {neighborhood}"
        label += f" ({price_label}: R$ {price_min:,.0f} – R$ {price_max:,.0f})"
        logger.info(f"  {label}")

        listings = collect_region(
            client,
            city=city,
            uf=uf,
            neighborhood=neighborhood,
            price_min=price_min,
            price_max=price_max,
            max_pages=max_pages,
            dry_run=dry_run,
        )

        all_regions[region_key] = {
            "city": city,
            "uf": uf,
            "neighborhood": neighborhood,
            "price_label": price_label,
            "price_min": price_min,
            "price_max": price_max,
            "total": len(listings),
            "listings": listings,
        }
        total_listings += len(listings)

    elapsed = time.time() - start
    logger.info(f"\n{'=' * 60}")
    logger.info(f"Collection complete: {total_listings} listings across {len(all_regions)} regions")
    logger.info(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f}m)")

    # Stats
    if hasattr(client, 'get_stats'):
        stats = client.get_stats()
        logger.info(f"API requests: {stats.get('requests', 0)}")
        logger.info(f"Cache hits:   {stats.get('cache_hits', 0)}")
        logger.info(f"Errors:       {stats.get('errors', 0)}")

    # Save results
    if not dry_run:
        result = {
            "meta": {
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "total_listings": total_listings,
                "total_regions": len(all_regions),
                "elapsed_seconds": round(elapsed, 1),
                "config_source": str(config_path or "watchdog.yaml"),
                "max_pages": max_pages,
            },
            "regions": all_regions,
        }
        saved_path = save_results(result, output_path)
        logger.info(f"\nResults saved to: {saved_path}")

        # Also save to the kanban workspace for the next task
        ws_path = os.environ.get("HERMES_KANBAN_WORKSPACE", "")
        if ws_path:
            ws_dir = Path(ws_path)
            ws_dir.mkdir(parents=True, exist_ok=True)
            ws_output = ws_dir / "emcasa_collect_results.json"
            with open(ws_output, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            logger.info(f"Also saved to workspace: {ws_output}")
    else:
        logger.info("\n[DRY-RUN] No data saved")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Done: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="EmCasa Unified Data Collection Driver"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to watchdog.yaml (default: auto-discover)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be done without fetching",
    )
    parser.add_argument(
        "--max-pages", "-m",
        type=int,
        default=None,
        help="Max pages per region (default: all)",
    )
    parser.add_argument(
        "--city", "-C",
        type=str,
        default=None,
        help="Filter by city name (e.g. 'São Paulo')",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file path",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip Telegram notification (not implemented yet)",
    )
    args = parser.parse_args()

    result = run_collection(
        config_path=args.config,
        dry_run=args.dry_run,
        max_pages=args.max_pages,
        city_filter=args.city,
        output_path=args.output,
        no_notify=args.no_notify,
    )
    sys.exit(result)


if __name__ == "__main__":
    main()
