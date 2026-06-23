#!/usr/bin/env python3
"""
run_coleta.py — Pipeline de coleta unificada de imóveis.

Orquestra todos os componentes do watchdog para:
  1. Scrape de múltiplas fontes (Loft SSR, EmCasa, etc.)
  2. Filtragem opcional (tipo, negociação, bairro)
  3. Saída unificada no schema padronizado (output.json)

Uso:
    python run_coleta.py                                          # coleta todas as fontes
    python run_coleta.py --sources loft                           # só Loft
    python run_coleta.py --sources loft,emcasa                    # Loft + EmCasa
    python run_coleta.py --filter-query                           # modo interativo
    python run_coleta.py --filter-tipo apartamento --filter-bairro Moema
    python run_coleta.py --cache                                  # usa cache SSR

Exemplos:
    # Coletar apartamentos para venda em Moema
    python run_coleta.py --sources loft --filter-tipo apartamento --filter-bairro Moema

    # Coletar tudo e salvar sem filtro
    python run_coleta.py -o data/results/coleta_completa.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Ensure skills dir is on path ─────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SKILLS = _HERE / "skills"
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── Available sources ──────────────────────────────────────────────────────────

AVAILABLE_SOURCES: dict[str, dict[str, Any]] = {
    "loft": {
        "label": "Loft",
        "default_url": "https://loft.com.br/venda/apartamentos/sp/sao-paulo/",
        "description": "Loft — SSR extraction (plain HTTP, no browser)",
    },
    "emcasa": {
        "label": "EmCasa",
        "default_url": None,
        "description": "EmCasa — API scraping (Algolia/Foundation backend)",
    },
    "lello": {
        "label": "Lello Imóveis",
        "default_url": None,
        "description": "Lello — SSR extraction via __NEXT_DATA__ (plain HTTP)",
    },
}

# ── Logging ────────────────────────────────────────────────────────────────────

logger = logging.getLogger("run_coleta")

# ── Source scrapers ────────────────────────────────────────────────────────────


def scrape_loft(
    max_pages: int = 3,
    category: str | None = None,
    url: str | None = None,
) -> tuple[list[dict], str]:
    """Scrape Loft via SSR extraction (no browser).

    Args:
        max_pages: Max pages per category (default: 3).
        category: Specific category slug or 'all' for all categories.
        url: Direct URL override (ignores category/max_pages).

    Returns:
        (listings, source_label)
    """
    from skills.loft.loft_ssr import extract_from_ssr

    listings: list[dict] = []
    label = "loft"

    if url:
        logger.info(f"Loft: fetching single URL: {url}")
        items = extract_from_ssr(url)
        listings.extend(items)
        logger.info(f"Loft: {len(items)} items from {url}")
        return listings, label

    # Use pagination module
    try:
        from skills.loft.loft_paginate import crawl_all_categories, crawl_category

        if category and category != "all":
            logger.info(f"Loft: crawling category '{category}', {max_pages} pages")
            items, stats = crawl_category(category, max_pages=max_pages)
            listings.extend(items)
            logger.info(f"Loft: {len(items)} items from {category} (pages={stats['pages_fetched']})")
        else:
            logger.info(f"Loft: crawling all categories, {max_pages} pages each")
            all_items, meta = crawl_all_categories(max_pages=max_pages)
            listings.extend(all_items)
            logger.info(f"Loft: {len(all_items)} items from all categories")
    except ImportError:
        logger.warning("loft_paginate not available, using single URL fallback")
        fallback_url = url or "https://loft.com.br/venda/apartamentos/sp/sao-paulo/"
        items = extract_from_ssr(fallback_url)
        listings.extend(items)

    return listings, label


def scrape_emcasa(
    max_items: int = 50,
    cidade: str = "São Paulo",
) -> tuple[list[dict], str]:
    """Scrape EmCasa via API.

    Args:
        max_items: Max items to fetch.
        cidade: City to search in.

    Returns:
        (listings, source_label)
    """
    label = "emcasa"
    listings: list[dict] = []

    try:
        from skills.emcasa.emcasa_api import search_emcasa
        from skills.emcasa.emcasa_parser import from_emcasa_api_response

        logger.info(f"EmCasa: searching in {cidade}, max {max_items} items")
        raw_response = search_emcasa(
            cidade=cidade,
            max_results=max_items,
        )

        if isinstance(raw_response, list):
            imoveis = from_emcasa_api_response({"hits": raw_response})
        elif isinstance(raw_response, dict):
            imoveis = from_emcasa_api_response(raw_response)
        else:
            imoveis = []

        # Convert Imovel objects to dicts
        for imovel in imoveis:
            data = imovel.to_dict()
            # Add EmCasa extras
            extra = getattr(imovel, "_extra", {})
            if extra:
                data["_extra"] = extra
            listings.append(data)

        logger.info(f"EmCasa: {len(listings)} items")

    except ImportError as exc:
        logger.warning(f"EmCasa scraper not available: {exc}")
    except Exception as exc:
        logger.error(f"EmCasa scrape failed: {exc}")

    return listings, label


def scrape_lello(
    max_pages: int = 3,
) -> tuple[list[dict], str]:
    """Scrape Lello Imóveis via SSR extraction (no browser).

    Reads targets from config/targets.yaml and crawls all configured
    tipo/negociacao combinations.

    Args:
        max_pages: Max pages per tipo/negociacao combo.

    Returns:
        (listings, source_label)
    """
    label = "lelloimoveis"
    listings: list[dict] = []

    try:
        from skills.lello_imoveis.lello_parser import crawl_from_targets

        logger.info(f"Lello: crawling from targets.yaml, {max_pages} pages per combo")
        items, _ = crawl_from_targets(max_pages=max_pages, rate_limit=1.0)
        listings.extend(items)
        logger.info(f"Lello: {len(items)} items collected")

    except ImportError as exc:
        logger.warning(f"Lello scraper not available: {exc}")
    except Exception as exc:
        logger.error(f"Lello scrape failed: {exc}")

    return listings, label


# ── Integration ────────────────────────────────────────────────────────────────


def run_coleta(
    sources: list[str] | None = None,
    max_pages: int = 2,
    output_path: str | Path | None = None,
    filter_fn: Any = None,
    cache: bool = False,
    **filter_kwargs: Any,
) -> Path:
    """Run the unified collection pipeline.

    Steps:
    1. Scrape configured sources.
    2. Normalize all items to unified schema.
    3. Optionally apply filter function.
    4. Save to timestamped JSON file.

    Args:
        sources: List of source names ('loft', 'emcasa'). None = all.
        max_pages: Max pages per source (where applicable).
        output_path: Output file path. Auto-generated if None.
        filter_fn: Optional filter function (e.g., filter_imoveis).
        cache: Enable SSR-level caching (where supported).
        **filter_kwargs: Keyword args for filter_fn.

    Returns:
        Absolute path of the saved output file.
    """
    from skills.output_schema import save_listings_batch

    if sources is None:
        sources = list(AVAILABLE_SOURCES.keys())

    logger.info(f"=== Unified Collection ===")
    logger.info(f"Sources: {', '.join(sources)}")
    logger.info(f"Max pages: {max_pages}")
    logger.info(f"Filter: {filter_fn.__name__ if filter_fn else 'none'} {filter_kwargs}")

    # ── Step 1: Scrape ────────────────────────────────────────────────────
    batches: dict[str, list[dict]] = {}
    total_raw = 0

    for source_name in sources:
        if source_name not in AVAILABLE_SOURCES:
            logger.warning(f"Unknown source '{source_name}', skipping")
            continue

        source_info = AVAILABLE_SOURCES[source_name]
        logger.info(f"\n{'─' * 50}")
        logger.info(f"Scraping: {source_info['label']}")
        logger.info(f"{'─' * 50}")

        try:
            if source_name == "loft":
                items, _ = scrape_loft(max_pages=max_pages)
            elif source_name == "emcasa":
                items, _ = scrape_emcasa(max_items=max_pages * 20)
            elif source_name == "lello":
                items, _ = scrape_lello(max_pages=max_pages)
            else:
                logger.warning(f"No scraper for source '{source_name}'")
                continue

            if items:
                batches[source_name] = items
                total_raw += len(items)
                logger.info(f"✓ {source_info['label']}: {len(items)} items collected")
            else:
                logger.warning(f"⚠ {source_info['label']}: no items collected")

        except Exception as exc:
            logger.error(f"✗ {source_info['label']} failed: {exc}")
            continue

    if not batches:
        logger.warning("No items collected from any source")
        # Still produce an empty output file so callers can check the path
        empty_output = output_path or _default_output_path()
        from skills.output_schema import save_listings
        return save_listings([], empty_output)

    logger.info(f"\nTotal raw items: {total_raw} from {len(batches)} sources")

    # ── Step 2: Save ──────────────────────────────────────────────────────
    if output_path:
        from skills.output_schema import save_listings
        all_items: list[dict] = []
        for source_items in batches.values():
            all_items.extend(source_items)
        return save_listings(
            all_items,
            output_path,
            filter_fn=filter_fn,
            **filter_kwargs,
        )
    else:
        output_dir = _HERE / "data" / "results"
        return save_listings_batch(
            batches,
            output_dir=output_dir,
            filter_fn=filter_fn,
            **filter_kwargs,
        )


def _default_output_path() -> Path:
    """Generate a timestamped default output path."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return _HERE / "data" / "results" / f"coleta_{ts}.json"


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_filter_fn(args: argparse.Namespace):
    """Build filter function from CLI args."""
    has_filter_args = any([
        args.filter_tipo, args.filter_negociacao, args.filter_bairro,
    ])
    if not has_filter_args:
        return None, {}

    from skills.filter_imoveis import filter_imoveis

    kwargs: dict[str, Any] = {}
    if args.filter_tipo:
        kwargs["tipo"] = args.filter_tipo
    if args.filter_negociacao:
        kwargs["negociacao"] = args.filter_negociacao
    if args.filter_bairro:
        kwargs["bairro"] = args.filter_bairro

    return filter_imoveis, kwargs


def main():
    parser = argparse.ArgumentParser(
        description="Coleta unificada de imóveis — Loft, EmCasa e mais",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--sources", "-s",
        default=",".join(AVAILABLE_SOURCES.keys()),
        help=f"Sources to scrape (comma-separated). Available: {', '.join(AVAILABLE_SOURCES.keys())}",
    )
    parser.add_argument(
        "--pages", "-p", type=int, default=2,
        help="Max pages per source (default: 2)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON file path (auto-generated if omitted)",
    )
    parser.add_argument(
        "--filter-tipo",
        help="Filter by property type (e.g., apartamento, casa)",
    )
    parser.add_argument(
        "--filter-negociacao",
        help="Filter by negotiation (venda, aluguel)",
    )
    parser.add_argument(
        "--filter-bairro",
        help="Filter by neighborhood (case-insensitive substring)",
    )
    parser.add_argument(
        "--cache", action="store_true",
        help="Enable SSR response caching (faster repeat runs)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging (DEBUG level)",
    )

    args = parser.parse_args()

    # Logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(name)s: %(levelname)s: %(message)s",
    )

    # Parse sources
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    # Filter function
    filter_fn, filter_kwargs = _build_filter_fn(args)

    # Run
    print(f"{'=' * 60}")
    print(f"Coleta Unificada — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Fontes: {', '.join(sources)}")
    if filter_fn:
        print(f"Filtro: tipo={args.filter_tipo or '*'}, "
              f"negociação={args.filter_negociacao or '*'}, "
              f"bairro={args.filter_bairro or '*'}")
    print(f"{'=' * 60}\n")

    start = time.time()

    try:
        output_path = run_coleta(
            sources=sources,
            max_pages=args.pages,
            output_path=args.output,
            filter_fn=filter_fn,
            cache=args.cache,
            **filter_kwargs,
        )
    except Exception as exc:
        print(f"\n❌ Coleta falhou: {exc}", file=sys.stderr)
        logger.exception("Detalhes do erro:")
        sys.exit(1)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"✓ Coleta concluída em {elapsed:.1f}s")
    print(f"  Arquivo: {output_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
