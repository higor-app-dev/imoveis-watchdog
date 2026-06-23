"""
loft_paginate — Pagination loop for Loft search pages.

Generates paginated SSR URLs for each listing category, calls the
single-page SSR extraction function for each page, and collects all
listings into a combined result. Stops when a page returns no
listings or a non-200 HTTP status.

Extends loft_ssr.extract_from_ssr() with page iteration logic.

Usage:
    from skills.loft.loft_paginate import crawl_category, crawl_all_categories

    # Crawl first 3 pages of venda/apartamentos em SP
    imoveis = crawl_category("venda/apartamentos", max_pages=3)

    # Crawl all categories, 3 pages each
    results = crawl_all_categories(max_pages=3)

    # CLI
    python skills/loft/loft_paginate.py venda/apartamentos --pages 3
    python skills/loft/loft_paginate.py all --pages 3 --output results.json
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

logger = logging.getLogger("loft_paginate")


# ── Listing categories (transaction_type / property_type) ─────────────────────
#
# Loft URL pattern:
#   https://loft.com.br/{category}/sp/sao-paulo/         (page 1)
#   https://loft.com.br/{category}/sp/sao-paulo/{n}-pagina (page 2+)
#
# Categories are transaction type + property type slugs.

LISTING_CATEGORIES: list[str] = [
    "venda/apartamentos",
    "venda/casas",
    "venda/terrenos",
    "venda/coberturas",
    "venda/comercial",
    "venda/estudio",
    "aluguel/apartamentos",
    "aluguel/casas",
    "aluguel/terrenos",
    "aluguel/coberturas",
    "aluguel/comercial",
    "aluguel/estudio",
]

# Supported cities (Loft uses slug format: sp/sao-paulo)
VALID_CITIES: list[str] = [
    "sp/sao-paulo",
]

# Defaults
DEFAULT_CATEGORY = "venda/apartamentos"
DEFAULT_CITY = "sp/sao-paulo"
DEFAULT_MAX_PAGES = 10
DEFAULT_RATE_LIMIT = 1.5  # seconds between requests
LOFT_BASE_URL = "https://loft.com.br"


# ── URL construction ──────────────────────────────────────────────────────────


def build_page_url(
    category: str = DEFAULT_CATEGORY,
    city: str = DEFAULT_CITY,
    page: int = 1,
) -> str:
    """Build a Loft search page URL for a given category, city, and page number.

    Args:
        category: Listing category slug (e.g. 'venda/apartamentos').
        city: City slug (e.g. 'sp/sao-paulo').
        page: Page number (1-based). Page 1 has no suffix; 2+ get '-pagina'.

    Returns:
        Full URL string.

    Examples:
        >>> build_page_url("venda/apartamentos", page=1)
        'https://loft.com.br/venda/apartamentos/sp/sao-paulo/'

        >>> build_page_url("venda/apartamentos", page=2)
        'https://loft.com.br/venda/apartamentos/sp/sao-paulo/2-pagina'

        >>> build_page_url("aluguel/casas", page=3)
        'https://loft.com.br/aluguel/casas/sp/sao-paulo/3-pagina'
    """
    base = f"{LOFT_BASE_URL}/{category}/{city}/"
    if page <= 1:
        return base
    return f"{base}{page}-pagina"


def get_default_categories() -> list[str]:
    """Return the default list of listing categories to crawl."""
    return LISTING_CATEGORIES.copy()


# ── Page fetching ─────────────────────────────────────────────────────────────


def fetch_page(
    category: str,
    city: str = DEFAULT_CITY,
    page: int = 1,
    timeout: int = 30,
) -> list[dict]:
    """Fetch a single page of listings from a Loft search category.

    Constructs the paginated URL and calls extract_ssr() to parse the
    SSR __NEXT_DATA__.

    Args:
        category: Listing category slug.
        city: City slug.
        page: Page number (1-based).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of Imovel dicts. Empty list if the page has no listings or
        the request failed.
    """
    url = build_page_url(category, city, page)
    logger.info(f"[{category}] Fetching page {page}: {url}")

    try:
        from skills.loft.loft_ssr import extract_from_ssr as _ssr

        listings = _ssr(url, timeout=timeout)
    except ImportError:
        # Fallback: try via loft_parser.extract_ssr()
        try:
            from skills.loft.loft_parser import extract_ssr as _ssr_fallback

            listings = _ssr_fallback(url, timeout=timeout)
        except ImportError:
            logger.error("Cannot import extract_ssr — loft_ssr.py or loft_parser.py missing")
            return []
    except Exception as e:
        # HTTP errors (403, 404, 500) or network errors
        logger.warning(f"[{category}] Page {page} failed: {type(e).__name__}: {e}")
        return []

    if not listings:
        logger.info(f"[{category}] Page {page}: no listings returned")
        return []

    logger.info(f"[{category}] Page {page}: {len(listings)} listings")
    return listings


# ── Category crawler ──────────────────────────────────────────────────────────


def crawl_category(
    category: str = DEFAULT_CATEGORY,
    city: str = DEFAULT_CITY,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Crawl pages of a single Loft listing category.

    Fetches pages sequentially, starting from page 1. Stops early if:
    - A page returns zero listings (end of results)
    - A page request fails entirely (network error, non-200)
    - max_pages is reached

    Args:
        category: Listing category slug.
        city: City slug.
        max_pages: Maximum number of pages to fetch.
        rate_limit: Seconds between requests.
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (listings, stats_dict) where listings is a flat list of
        Imovel dicts in the unified schema, and stats_dict contains
        pagination metadata.
    """
    all_listings: list[dict] = []
    errors = 0
    empty_pages = 0
    consecutive_empty = 0

    for page_num in range(1, max_pages + 1):
        # Rate limit between requests (skip after page 1 if already done)
        if page_num > 1 and rate_limit > 0:
            time.sleep(rate_limit)

        try:
            page_listings = fetch_page(category, city, page_num, timeout=timeout)
        except Exception as e:
            logger.warning(f"[{category}] Unexpected error on page {page_num}: {e}")
            errors += 1
            page_listings = []

        if not page_listings:
            empty_pages += 1
            consecutive_empty += 1
        else:
            consecutive_empty = 0
            all_listings.extend(page_listings)

        # Stop if we hit an empty page (end of pagination)
        if consecutive_empty >= 1:
            logger.info(
                f"[{category}] Stopping at page {page_num} — "
                f"page returned {len(page_listings)} listings"
            )
            break

    stats = {
        "category": category,
        "city": city,
        "pages_fetched": page_num,
        "max_pages": max_pages,
        "total_listings": len(all_listings),
        "errors": errors,
        "empty_pages": empty_pages,
        "stopped_early": page_num < max_pages,
        "stop_reason": (
            "empty_page" if empty_pages > 0 and page_num < max_pages
            else "max_pages" if page_num >= max_pages
            else "error"
        ),
    }

    logger.info(
        f"[{category}] Done — {stats['total_listings']} listings "
        f"across {page_num} pages "
        f"({errors} errors, {empty_pages} empty pages)"
    )
    return all_listings, stats


# ── Full crawl across all categories ──────────────────────────────────────────


def crawl_all_categories(
    categories: list[str] | None = None,
    city: str = DEFAULT_CITY,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Crawl all specified Loft listing categories.

    Iterates over each category, crawling its pages, and collects
    all results into a single combined list.

    Args:
        categories: List of category slugs. Defaults to LISTING_CATEGORIES.
        city: City slug.
        max_pages: Maximum pages per category.
        rate_limit: Seconds between requests.
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (all_listings, crawl_metadata_dict).
    """
    if categories is None:
        categories = LISTING_CATEGORIES

    all_listings: list[dict] = []
    per_category_stats: list[dict] = []
    total_errors = 0
    total_empty = 0
    categories_with_data = 0

    start_time = time.time()

    for idx, category in enumerate(categories):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"[{idx + 1}/{len(categories)}] Crawling: {category}")
        logger.info(f"{'=' * 60}")

        listings, stats = crawl_category(
            category=category,
            city=city,
            max_pages=max_pages,
            rate_limit=rate_limit,
            timeout=timeout,
        )

        all_listings.extend(listings)
        per_category_stats.append(stats)
        total_errors += stats["errors"]
        total_empty += stats["empty_pages"]
        if listings:
            categories_with_data += 1

    elapsed = time.time() - start_time

    metadata = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "city": city,
        "categories_requested": len(categories),
        "categories_with_data": categories_with_data,
        "max_pages_per_category": max_pages,
        "total_listings": len(all_listings),
        "total_errors": total_errors,
        "total_empty_pages": total_empty,
        "elapsed_seconds": round(elapsed, 1),
        "rate_limit": rate_limit,
        "per_category": per_category_stats,
    }

    logger.info(f"\n{'=' * 60}")
    logger.info("FULL CRAWL COMPLETE")
    logger.info(f"  Categories:   {categories_with_data}/{len(categories)} with data")
    logger.info(f"  Total:        {len(all_listings)} listings")
    logger.info(f"  Errors:       {total_errors}")
    logger.info(f"  Elapsed:      {elapsed:.1f}s")
    logger.info(f"{'=' * 60}")

    return all_listings, metadata


# ── Save results ──────────────────────────────────────────────────────────────


def save_results(
    listings: list[dict],
    metadata: dict,
    output_path: str | None = None,
) -> str:
    """Save crawled listings and metadata to a JSON file.

    Args:
        listings: List of Imovel dicts.
        metadata: Crawl metadata dict.
        output_path: Output file path. Auto-generated if None.

    Returns:
        Absolute path to the saved file.
    """
    if output_path is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(
            os.path.expanduser("~"),
            "imoveis-watchdog",
            "data",
            "results",
            f"loft_crawl_{ts}.json",
        )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    result = {
        "meta": metadata,
        "listings": listings,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(listings)} listings to {output_path}")
    return os.path.abspath(output_path)


# ── CLI ───────────────────────────────────────────────────────────────────────


def setup_logging(verbose: bool = False):
    """Configure logging with optional debug verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_categories(category_arg: str) -> list[str]:
    """Parse the --category CLI argument into a list of category slugs."""
    if category_arg.lower() in ("all", "*", "todas"):
        return LISTING_CATEGORIES
    return [c.strip() for c in category_arg.split(",") if c.strip()]


def cli_main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Loft Pagination Crawler — extrai listings via SSR paginado",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s venda/apartamentos --pages 3
  %(prog)s all --pages 3 --output resultados.json
  %(prog)s venda/apartamentos,aluguel/apartamentos --pages 5
        """,
    )
    parser.add_argument(
        "category",
        type=str,
        nargs="?",
        default="all",
        help="Categoria: 'all' (padrão), ou uma ou mais separadas por vírgula",
    )
    parser.add_argument(
        "--city",
        type=str,
        default=DEFAULT_CITY,
        help=f"Cidade slug (padrão: {DEFAULT_CITY})",
    )
    parser.add_argument(
        "--pages",
        "-p",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Máximo de páginas por categoria (padrão: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--rate-limit",
        "-r",
        type=float,
        default=DEFAULT_RATE_LIMIT,
        help=f"Segundos entre requisições (padrão: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=30,
        help="Timeout por página em segundos (padrão: 30)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Caminho do arquivo JSON de saída",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log detalhado (debug)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Apenas mostrar resumo, sem salvar",
    )

    args = parser.parse_args()

    setup_logging(args.verbose)

    categories = parse_categories(args.category)

    if len(categories) == 1:
        logger.info(f"Crawling category: {categories[0]}")
        listings, stats = crawl_category(
            category=categories[0],
            city=args.city,
            max_pages=args.pages,
            rate_limit=args.rate_limit,
            timeout=args.timeout,
        )
        metadata = {
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "city": args.city,
            "categories_requested": 1,
            "categories_with_data": 1 if listings else 0,
            "max_pages_per_category": args.pages,
            "total_listings": len(listings),
            "elapsed_seconds": 0,
            "rate_limit": args.rate_limit,
            "per_category": [stats],
        }
    else:
        logger.info(f"Crawling {len(categories)} categories, {args.pages} pages each")
        listings, metadata = crawl_all_categories(
            categories=categories,
            city=args.city,
            max_pages=args.pages,
            rate_limit=args.rate_limit,
            timeout=args.timeout,
        )

    # Print summary
    print(f"\n── Resumo ──")
    print(f"  Total:       {len(listings)} imóveis")
    if listings:
        prices = [i.get("preco_venda") for i in listings if i.get("preco_venda")]
        if prices:
            print(f"  Preços:      R$ {min(prices):,.0f} ~ R$ {max(prices):,.0f}")
        areas = [i.get("area") for i in listings if i.get("area")]
        if areas:
            print(f"  Áreas:       {min(areas):.0f} ~ {max(areas):.0f} m²")
        reducoes = [i for i in listings if i.get("tem_reducao")]
        if reducoes:
            print(f"  Reduções:    {len(reducoes)} imóveis ({len(reducoes)/len(listings)*100:.0f}%)")
        bairros = {}
        for i in listings:
            b = i.get("bairro", "N/I")
            bairros[b] = bairros.get(b, 0) + 1
        print(f"  Bairros:     {len(bairros)} diferentes")
        for b, c in sorted(bairros.items(), key=lambda x: -x[1])[:5]:
            print(f"    {b}: {c}")

    if args.summary:
        return

    if not args.output:
        args.output = None  # auto-generate

    save_path = save_results(listings, metadata, output_path=args.output)
    print(f"  Salvo em:    {save_path}")


if __name__ == "__main__":
    cli_main()
