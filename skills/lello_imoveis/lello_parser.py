"""
lello_parser — Higher-level parser and pagination loop for Lello Imóveis.

Wraps lello_ssr functions with pagination, batch extraction, and unified
schema output. Follows the same patterns as skills/loft/loft_parser.py
and skills/emcasa/emcasa_parser.py.

Functions:
    from_lello_listing(item: dict, negociacao: str) -> dict
        Convert a single raw item to unified schema (delegates to lello_ssr).

    from_lello_payload(payload: dict) -> list[dict]
        Convert a batch of listings from a search page response.

    build_lello_url(params: dict) -> str
        Build a search URL from filter parameters.

    crawl_tipo(tipo, negociacao, bairro, max_pages, rate_limit) -> list[dict]
        Crawl multiple pages of a single tipo/negociacao combo.

    crawl_all(max_pages, rate_limit) -> list[dict]
        Crawl all known tipo/negociacao combinations.

    save_results(listings, output_path) -> str
        Save crawled listings to a JSON file.

Usage:
    from skills.lello_imoveis.lello_parser import from_lello_listing, from_lello_payload
    from skills.lello_imoveis.lello_parser import crawl_tipo, crawl_all, save_results
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

import yaml

logger = logging.getLogger("lello_parser")

# ── Typing types ─────────────────────────────────────────────────────────────

# Property types and negotiation combinations
TIPOS_DISPONIVEIS = [
    "apartamento",
    "casa",
    "cobertura",
    "duplex",
    "kitnet",
    "loft",
    "studio",
    "flat",
    "terreno",
    "comercial",
    "sala_comercial",
    "predio",
    "sobrado",
    "conjugado",
]

NEGOCIACOES = ["venda", "aluguel"]

# Defaults
DEFAULT_MAX_PAGES = 10
DEFAULT_RATE_LIMIT = 1.0  # seconds between requests


# ── Wrapper imports and delegations ──────────────────────────────────────────


def _get_ssr_module():
    """Lazy-import lello_ssr to avoid circular imports."""
    from skills.lello_imoveis.lello_ssr import (
        extract_from_ssr as _extract,
        extract_detail_from_ssr as _detail,
        build_search_url as _build_url,
        map_listing_to_imovel as _map,
        build_detail_url as _detail_url,
    )

    return _extract, _detail, _build_url, _map, _detail_url


def build_lello_url(params: dict) -> str:
    """Build a Lello search URL from filter parameters.

    Args:
        params: Dict with optional keys:
            tipo (str): Property type (default: 'apartamento').
            negociacao (str): 'venda' or 'aluguel' (default: 'venda').
            bairro (str): Optional neighborhood.
            pagina (int): Page number (default: 1).

    Returns:
        Full search URL string.
    """
    _, _, build_url, _, _ = _get_ssr_module()
    return build_url(
        tipo=params.get("tipo", "apartamento"),
        negociacao=params.get("negociacao", "venda"),
        bairro=params.get("bairro"),
        pagina=params.get("pagina", 1),
    )


def from_lello_listing(item: dict, negociacao: str = "venda") -> dict:
    """Convert a single raw Lello listing dict to unified schema.

    Args:
        item: Raw listing dict from __NEXT_DATA__ or detail page.
        negociacao: 'venda' or 'aluguel'.

    Returns:
        Dict in unified Imovel schema.
    """
    _, _, _, map_fn, _ = _get_ssr_module()
    result = map_fn(item, negociacao=negociacao)
    return result or {}


def from_lello_payload(payload: dict) -> list[dict]:
    """Convert a batch of listings into unified schema.

    Accepts:
      - Dict with 'list' key (search page response)
      - List of raw items
      - Dict with 'data' key

    Args:
        payload: Search response or list of raw items.

    Returns:
        List of unified-schema listing dicts.
    """
    _, _, _, map_fn, _ = _get_ssr_module()

    # Determine negotiation from context hint
    negociacao = "venda"

    # Try various payload shapes
    raw_items: list[dict] = []
    if isinstance(payload, dict):
        # Search page response: { list: [...], ... }
        raw_items = payload.get("list") or payload.get("data") or []
        # Try to infer negociacao from metadata
        total_data = payload.get("data", {})
        if isinstance(total_data, dict):
            raw_items = total_data.get("list") or raw_items
    elif isinstance(payload, list):
        raw_items = payload
    else:
        logger.warning(f"from_lello_payload: unexpected type {type(payload).__name__}")
        return []

    if not isinstance(raw_items, list):
        logger.warning(f"from_lello_payload: 'list' field is {type(raw_items).__name__}")
        return []

    results = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        converted = map_fn(item, negociacao=negociacao)
        if converted:
            results.append(converted)

    logger.info(f"from_lello_payload: {len(results)} listings from {len(raw_items)} raw items")
    return results


# ── Single page fetch ────────────────────────────────────────────────────────


def fetch_page(
    tipo: str = "apartamento",
    negociacao: str = "venda",
    bairro: str | None = None,
    pagina: int = 1,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Fetch a single page of Lello search results.

    Args:
        tipo: Property type.
        negociacao: 'venda' or 'aluguel'.
        bairro: Optional neighborhood.
        pagina: Page number (1-based).
        timeout: HTTP request timeout.

    Returns:
        Tuple of (listings_list, metadata_dict).
    """
    extract_fn, _, build_url, _, _ = _get_ssr_module()
    url = build_url(tipo=tipo, negociacao=negociacao, bairro=bairro, pagina=pagina)
    logger.info(f"[{negociacao}/{tipo}] Page {pagina}: {url}")

    try:
        listings, meta = extract_fn(url, timeout=timeout)
        if isinstance(listings, list) and listings:
            # Tag each listing with correct negotiation
            for l in listings:
                l["negociacao"] = negociacao
        return listings, meta
    except Exception as e:
        logger.warning(
            f"[{negociacao}/{tipo}] Page {pagina} failed: {type(e).__name__}: {e}"
        )
        return [], {}


# ── Pagination crawler ───────────────────────────────────────────────────────


def crawl_tipo(
    tipo: str = "apartamento",
    negociacao: str = "venda",
    bairro: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Crawl multiple pages of a single tipo/negociacao combo.

    Fetches pages sequentially starting from page 1. Stops early if:
    - A page returns zero listings (end of results)
    - A page request fails entirely
    - max_pages is reached

    Args:
        tipo: Property type slug.
        negociacao: 'venda' or 'aluguel'.
        bairro: Optional neighborhood filter.
        max_pages: Maximum pages to fetch.
        rate_limit: Seconds between requests.
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (all_listings, stats_dict).
    """
    all_listings: list[dict] = []
    errors = 0
    empty_pages = 0
    consecutive_empty = 0
    pages_fetched = 0

    for page_num in range(1, max_pages + 1):
        if page_num > 1 and rate_limit > 0:
            time.sleep(rate_limit)

        try:
            page_listings, meta = fetch_page(
                tipo=tipo,
                negociacao=negociacao,
                bairro=bairro,
                pagina=page_num,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(f"[{negociacao}/{tipo}] Unexpected error on page {page_num}: {e}")
            errors += 1
            page_listings = []

        pages_fetched = page_num

        if not page_listings:
            empty_pages += 1
            consecutive_empty += 1
        else:
            consecutive_empty = 0
            all_listings.extend(page_listings)

        # Stop if we hit an empty page (end of results)
        if consecutive_empty >= 1:
            logger.info(
                f"[{negociacao}/{tipo}] Stopping at page {page_num} — "
                f"empty page"
            )
            break

    stats = {
        "tipo": tipo,
        "negociacao": negociacao,
        "bairro": bairro,
        "pages_fetched": pages_fetched,
        "max_pages": max_pages,
        "total_listings": len(all_listings),
        "errors": errors,
        "empty_pages": empty_pages,
        "stopped_early": pages_fetched < max_pages,
    }

    logger.info(
        f"[{negociacao}/{tipo}] Done — {stats['total_listings']} listings "
        f"across {pages_fetched} pages ({errors} errors)"
    )
    return all_listings, stats


# ── Full crawl ───────────────────────────────────────────────────────────────


def parse_tipos_arg(tipos_str: str) -> list[str]:
    """Parse a comma-separated list of property types."""
    if tipos_str.lower() in ("all", "*", "todos"):
        return TIPOS_DISPONIVEIS
    return [t.strip().lower() for t in tipos_str.split(",") if t.strip()]


def crawl_all(
    tipos: list[str] | None = None,
    negociacoes: list[str] | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Crawl all specified tipo/negociacao combinations.

    Iterates over each combination, crawling pages, and collects
    all results into a single combined list.

    Args:
        tipos: List of property types. Defaults to TIPOS_DISPONIVEIS.
        negociacoes: ['venda'] or ['venda', 'aluguel'].
        max_pages: Maximum pages per tipo/negociacao combo.
        rate_limit: Seconds between requests.
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (all_listings, crawl_metadata_dict).
    """
    if tipos is None:
        tipos = TIPOS_DISPONIVEIS
    if negociacoes is None:
        negociacoes = NEGOCIACOES

    all_listings: list[dict] = []
    per_combo_stats: list[dict] = []
    total_errors = 0
    combos_with_data = 0

    start_time = time.time()

    for negociacao in negociacoes:
        for tipo in tipos:
            label = f"{negociacao}/{tipo}"
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Crawling: {label}")
            logger.info(f"{'=' * 60}")

            listings, stats = crawl_tipo(
                tipo=tipo,
                negociacao=negociacao,
                max_pages=max_pages,
                rate_limit=rate_limit,
                timeout=timeout,
            )

            all_listings.extend(listings)
            per_combo_stats.append(stats)
            total_errors += stats["errors"]
            if listings:
                combos_with_data += 1

            # Extra delay between combos
            if rate_limit > 0:
                time.sleep(rate_limit)

    elapsed = time.time() - start_time

    metadata = {
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "tipos_requested": len(tipos),
        "negociacoes_requested": len(negociacoes),
        "combos_with_data": combos_with_data,
        "max_pages_per_combo": max_pages,
        "total_listings": len(all_listings),
        "total_errors": total_errors,
        "elapsed_seconds": round(elapsed, 1),
        "rate_limit": rate_limit,
        "per_combo": per_combo_stats,
    }

    logger.info(f"\n{'=' * 60}")
    logger.info("FULL CRAWL COMPLETE")
    logger.info(f"  Combos with data: {combos_with_data}")
    logger.info(f"  Total: {len(all_listings)} listings")
    logger.info(f"  Errors: {total_errors}")
    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"{'=' * 60}")

    return all_listings, metadata


# ── Target-driven crawl (reads from config/targets.yaml) ─────────────────────


def load_targets_from_yaml(
    config_path: str | Path | None = None,
) -> dict:
    """Load Lello targets from config/targets.yaml.

    Returns a dict with keys 'compra' and/or 'aluguel', each
    containing a list of target dicts with 'cidade', 'uf', 'tipos', etc.

    Args:
        config_path: Path to targets.yaml. Defaults to <repo_root>/config/targets.yaml.

    Returns:
        Dict with negotiation keys, each value being a list of target configs.

    Raises:
        FileNotFoundError: If config/targets.yaml is not found.
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent.parent / "config" / "targets.yaml"

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"targets.yaml not found at {config_path}"
        )

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    lello_cfg = data.get("lello", {})
    if not lello_cfg:
        logger.warning("No 'lello' section found in targets.yaml")
        return {}

    return lello_cfg


def crawl_from_targets(
    config_path: str | Path | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    rate_limit: float = DEFAULT_RATE_LIMIT,
    timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Crawl Lello listings using targets from config/targets.yaml.

    Reads the 'lello' section of targets.yaml and calls crawl_all()
    with the tipos and negociacoes found there. Also respects per-target
    bairro and preco_max filters (preco_max is passed as a hint).

    Args:
        config_path: Path to targets.yaml. Defaults to <repo_root>/config/targets.yaml.
        max_pages: Max pages per tipo/negociacao combo.
        rate_limit: Seconds between requests.
        timeout: Per-page HTTP timeout.

    Returns:
        Tuple of (all_listings, crawl_metadata).
    """
    lello_cfg = load_targets_from_yaml(config_path)
    if not lello_cfg:
        logger.warning("No Lello targets found — falling back to all tipos")
        return crawl_all(
            tipos=TIPOS_DISPONIVEIS,
            negociacoes=NEGOCIACOES,
            max_pages=max_pages,
            rate_limit=rate_limit,
            timeout=timeout,
        )

    # Collect unique tipos and negociacoes from all targets
    tipos_set: set[str] = set()
    negociacoes_set: set[str] = set()
    bairros_por_negociacao: dict[str, list[str]] = {}

    for neg_key in ("compra", "aluguel"):
        if neg_key not in lello_cfg:
            continue
        targets = lello_cfg[neg_key]
        if not isinstance(targets, list):
            targets = [targets]

        negociacao = "venda" if neg_key == "compra" else "aluguel"
        negociacoes_set.add(negociacao)
        bairros_por_negociacao[negociacao] = []

        for target in targets:
            tipos = target.get("tipos", [])
            if isinstance(tipos, list):
                for t in tipos:
                    tipos_set.add(t)
            bairros = target.get("bairros", [])
            if isinstance(bairros, list) and bairros:
                bairros_por_negociacao[negociacao].extend(bairros)

    # Filter to known tipos only
    valid_tipos = [t for t in tipos_set if t in TIPOS_DISPONIVEIS]
    if not valid_tipos:
        logger.warning("No valid tipos found in targets — using all")
        valid_tipos = TIPOS_DISPONIVEIS

    negociacoes = list(negociacoes_set) or NEGOCIACOES

    logger.info(
        f"crawl_from_targets: {len(valid_tipos)} tipos, "
        f"{len(negociacoes)} negociacoes"
    )

    return crawl_all(
        tipos=valid_tipos,
        negociacoes=negociacoes,
        max_pages=max_pages,
        rate_limit=rate_limit,
        timeout=timeout,
    )


# ── Save results ──────────────────────────────────────────────────────────────


def save_results(
    listings: list[dict],
    metadata: dict,
    output_path: str | None = None,
) -> str:
    """Save crawled listings and metadata to a JSON file.

    Args:
        listings: List of unified-schema listing dicts.
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
            f"lello_crawl_{ts}.json",
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


# ── Combined batch output (uses output_schema) ───────────────────────────────


def save_to_unified_schema(
    listings: list[dict],
    output_dir: str | Path = "data/results",
    filter_fn: Any = None,
    **filter_kwargs: Any,
) -> str:
    """Save listings using the unified output schema.

    Normalizes listings through output_schema.save_listings() for
    consistent format with other portal scrapers.

    Args:
        listings: Raw listing dicts (will be normalized).
        output_dir: Output directory.
        filter_fn: Optional filter function.
        **filter_kwargs: Filter kwargs.

    Returns:
        Absolute path to saved file.
    """
    try:
        from skills.output_schema import save_listings as _save

        ts_now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        result = _save(
            listings,
            Path(output_dir) / f"lello_coleta_{ts_now}.json",
            filter_fn=filter_fn,
            **filter_kwargs,
        )
        return str(result)
    except ImportError:
        logger.warning("output_schema not available, saving raw")
        ts_now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return save_results(listings, {}, str(Path(output_dir) / f"lello_raw_{ts_now}.json"))


# ── CLI ──────────────────────────────────────────────────────────────────────


def setup_logging(verbose: bool = False):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )


def cli_main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Lello Crawler — extrai imóveis via SSR paginado",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s apartamento --negociacao venda --pages 3
  %(prog)s all --pages 3 --negociacao venda --output resultados.json
  %(prog)s apartamento,casa --negociacao venda,aluguel --pages 5 --verbose
        """,
    )
    parser.add_argument(
        "tipos",
        type=str,
        nargs="?",
        default="all",
        help="Tipo(s): 'all' (padrão), ou separados por vírgula (apartamento,casa)",
    )
    parser.add_argument(
        "--negociacao",
        "-n",
        type=str,
        default="venda",
        help="Negociação: 'venda' (padrão), 'aluguel', ou 'venda,aluguel'",
    )
    parser.add_argument(
        "--bairro",
        "-b",
        type=str,
        default=None,
        help="Bairro opcional para filtrar",
    )
    parser.add_argument(
        "--pages",
        "-p",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Máximo de páginas por combinação (padrão: {DEFAULT_MAX_PAGES})",
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
        "--summary",
        action="store_true",
        help="Apenas mostrar resumo, sem salvar",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log detalhado",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    tipos = parse_tipos_arg(args.tipos)
    negociacoes = [n.strip() for n in args.negociacao.split(",") if n.strip()]

    if len(tipos) <= 1 and len(negociacoes) <= 1:
        logger.info(
            f"Crawling {negociacoes[0]}/{tipos[0]}, "
            f"{args.pages} pages"
        )
        listings, stats = crawl_tipo(
            tipo=tipos[0],
            negociacao=negociacoes[0],
            bairro=args.bairro,
            max_pages=args.pages,
            rate_limit=args.rate_limit,
            timeout=args.timeout,
        )
        metadata = {
            "crawled_at": datetime.now(timezone.utc).isoformat(),
            "total_listings": len(listings),
            "elapsed_seconds": 0,
            "rate_limit": args.rate_limit,
            "per_combo": [stats],
        }
    else:
        logger.info(
            f"Crawling {len(tipos)} tipo(s), {len(negociacoes)} negociação(ões), "
            f"{args.pages} pages each"
        )
        listings, metadata = crawl_all(
            tipos=tipos,
            negociacoes=negociacoes,
            max_pages=args.pages,
            rate_limit=args.rate_limit,
            timeout=args.timeout,
        )

    # Print summary
    print(f"\n── Resumo ──")
    print(f"  Total:       {len(listings)} imóveis")
    if metadata.get("per_combo"):
        for s in metadata["per_combo"]:
            print(
                f"  {s.get('negociacao','?')}/{s.get('tipo','?')}: "
                f"{s.get('total_listings',0)} imóveis "
                f"({s.get('pages_fetched',0)} páginas)"
            )
    print(f"  Erros:       {metadata.get('total_errors', 0)}")
    print(f"  Taxa:        {args.rate_limit}s entre requisições")
    print(f"  Tempo:       {metadata.get('elapsed_seconds', '?')}s")

    if args.summary:
        return

    if not listings:
        print("\nNenhum imóvel encontrado.")
        return

    output = save_results(listings, metadata, args.output)
    print(f"\n  Salvo em:    {output}")


if __name__ == "__main__":
    cli_main()
