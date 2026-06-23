"""
output_schema — Transform, filter, and save listings in the unified JSON schema.

Functions:
    infer_negociacao(item: dict) -> str | None
        Determine negotiation type from price fields.

    normalize_to_schema(items: list[dict]) -> list[dict]
        Transform a list of extracted items into the unified schema.

    save_listings(items: list[dict], output_path: str, filter_fn=None, **filter_kwargs) -> Path
        Normalize, optionally filter, and save to a JSON file.

    save_listings_batch(batches: dict[str, list[dict]], output_dir: str, filter_fn=None) -> Path
        Save multiple source batches into one unified JSON file with provenance.

Uso:
    from skills.output_schema import save_listings, normalize_to_schema

    # Basic: save all items
    path = save_listings(items, "data/results/coleta.json")

    # With filter
    from skills.filter_imoveis import filter_imoveis
    path = save_listings(
        items, "data/results/sp_venda.json",
        filter_fn=filter_imoveis,
        tipo="apartamento", negociacao="venda",
    )
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("output_schema")

# ── Schema field mapping ──────────────────────────────────────────────────────
# Maps from the various parser output formats to the unified schema.
# Source format: the Imovel-compatible dict used by all parsers.
# Target format: the unified schema as defined in imovel_schema.json.

UNIFIED_SCHEMA_FIELDS = {
    # Identity
    "codigo": str,
    "titulo": str,
    "url": str,
    "fonte": str,
    "negociacao": str,
    # Type
    "tipo": str,
    "uso": str,
    # Prices
    "preco": (int, float, type(None)),
    "preco_venda": (int, float, type(None)),
    "preco_aluguel": (int, float, type(None)),
    "preco_anterior": (int, float, type(None)),
    "condominio": (int, float, type(None)),
    "iptu": (int, float, type(None)),
    # Location
    "endereco": str,
    "bairro": str,
    "cidade": str,
    "uf": str,
    "cep": (str, type(None)),
    "latitude": (int, float, type(None)),
    "longitude": (int, float, type(None)),
    # Characteristics
    "area": (int, float, type(None)),
    "quartos": (int, type(None)),
    "suites": (int, type(None)),
    "banheiros": (int, type(None)),
    "vagas": (int, type(None)),
    "andar": (int, type(None)),
    # Content
    "descricao": str,
    "comodidades": list,
    "fotos": list,
    # Agency
    "agencia": str,
    "origem_id": (str, type(None)),
    # Metadata
    "disponivel": bool,
    "tem_reducao": bool,
    "percentual_reducao": (int, float),
    "data_coleta": str,
    "data_publicacao": (str, type(None)),
    "data_atualizacao_preco": (str, type(None)),
}

# Defaults for fields that might be missing
FIELD_DEFAULTS: dict[str, Any] = {
    "codigo": "",
    "titulo": "",
    "url": "",
    "fonte": "",
    "negociacao": "",
    "tipo": "",
    "uso": "residential",
    "preco": None,
    "preco_venda": None,
    "preco_aluguel": None,
    "preco_anterior": None,
    "condominio": None,
    "iptu": None,
    "endereco": "",
    "bairro": "",
    "cidade": "",
    "uf": "",
    "cep": None,
    "latitude": None,
    "longitude": None,
    "area": None,
    "quartos": None,
    "suites": None,
    "banheiros": None,
    "vagas": None,
    "andar": None,
    "descricao": "",
    "comodidades": [],
    "fotos": [],
    "agencia": "",
    "origem_id": None,
    "disponivel": True,
    "tem_reducao": False,
    "percentual_reducao": 0.0,
    "data_coleta": "",
    "data_publicacao": None,
    "data_atualizacao_preco": None,
}

# Field name mapping: source (Imovel dict key) → target (unified schema key)
FIELD_NAME_MAP: dict[str, str] = {
    "id": "codigo",
    "list_id": "codigo",
    "codigo": "codigo",
}

# Source fields that map to unified schema directly (same name)
DIRECT_FIELDS = {
    "titulo", "url", "fonte", "tipo", "uso",
    "preco_venda", "preco_aluguel", "preco_anterior",
    "condominio", "iptu",
    "endereco", "bairro", "cidade", "uf", "cep",
    "latitude", "longitude",
    "area", "quartos", "suites", "banheiros", "vagas", "andar",
    "descricao",
    "agencia", "origem_id",
    "disponivel", "tem_reducao", "percentual_reducao",
    "data_coleta", "data_publicacao", "data_atualizacao_preco",
}

# Source fields that map to "comodidades" in unified schema
AMENITIES_ALIASES: dict[str, str] = {
    "amenities": "comodidades",
    "comodidades": "comodidades",
    "features": "comodidades",
}

# Source fields that map to "fotos" in unified schema
PHOTOS_ALIASES: dict[str, str] = {
    "fotos": "fotos",
    "imagens": "fotos",
    "photos": "fotos",
    "images": "fotos",
    "photo_urls": "fotos",
}


def _infer_negociacao(item: dict) -> str | None:
    """Determine the negotiation type from an item's price fields.

    Args:
        item: A listing dict with preco_venda and/or preco_aluguel.

    Returns:
        'venda' if preco_venda is set, 'aluguel' if preco_aluguel is set,
        or None if neither (or both) are set.
    """
    # Check both raw source fields and unified schema fields
    venda = (
        item.get("preco_venda") is not None
        or item.get("price") is not None
    )
    aluguel = (
        item.get("preco_aluguel") is not None
        or item.get("rentalPrice") is not None
    )

    if venda and not aluguel:
        return "venda"
    if aluguel and not venda:
        return "aluguel"
    # When both are present, prefer venda (common case: listing has both prices)
    if venda and aluguel:
        return "venda"
    return None


def _infer_preco(item: dict, negociacao: str | None) -> float | None:
    """Infer the active price based on negotiation type.

    Args:
        item: Listing dict.
        negociacao: Already-inferred negotiation type.

    Returns:
        The negotiated price, or the only available price.
    """
    if negociacao == "venda":
        return item.get("preco_venda") or item.get("price")
    if negociacao == "aluguel":
        return item.get("preco_aluguel") or item.get("rentalPrice")
    return item.get("preco_venda") or item.get("preco_aluguel") or item.get("price")


def _get_photos(item: dict) -> list[str]:
    """Extract photo URLs from an item using all known aliases."""
    for key in ("fotos", "imagens", "photos", "images", "photo_urls"):
        val = item.get(key)
        if isinstance(val, list) and val:
            return [str(u) for u in val if u]
    return []


def _get_amenities(item: dict) -> list[str]:
    """Extract amenities from an item using all known aliases."""
    for key in ("comodidades", "amenities", "features"):
        val = item.get(key)
        if isinstance(val, list) and val:
            return [str(a) for a in val if a]
    return []


def normalize_to_schema(items: list[dict]) -> list[dict]:
    """Transform a list of extracted items into the unified JSON schema.

    Accepts items from any parser (loft_ssr, loft_parser, emcasa_parser,
    parse_ad from OLX pipeline, etc.). Returns a list of dicts conforming
    to imovel_schema.json.

    Args:
        items: List of dicts from any parser. Non-dict items are skipped.

    Returns:
        List of normalized dicts in the unified schema.
    """
    result: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for item in items:
        if not isinstance(item, dict):
            continue

        entry: dict[str, Any] = {}

        # Start with defaults
        for field, default in FIELD_DEFAULTS.items():
            entry[field] = default

        # Copy direct fields (same name in source and target)
        for field in DIRECT_FIELDS:
            if field in item and item[field] is not None:
                entry[field] = item[field]

        # Map renamed fields
        for src_key, dst_key in FIELD_NAME_MAP.items():
            if src_key in item and item[src_key] is not None:
                entry[dst_key] = str(item[src_key])
                break

        # Map amenity aliases
        for src_key, dst_key in AMENITIES_ALIASES.items():
            val = item.get(src_key)
            if isinstance(val, list) and val:
                entry[dst_key] = [str(a) for a in val if a]
                break
        if not entry["comodidades"]:
            entry["comodidades"] = _get_amenities(item)

        # Map photo aliases
        for src_key, dst_key in PHOTOS_ALIASES.items():
            val = item.get(src_key)
            if isinstance(val, list) and val:
                entry[dst_key] = [str(u) for u in val if u]
                break
        if not entry["fotos"]:
            entry["fotos"] = _get_photos(item)

        # Infer negotiation type
        neg = _infer_negociacao(item)
        if neg:
            entry["negociacao"] = neg
        elif not entry["negociacao"]:
            entry["negociacao"] = "venda"  # sensible default

        # Infer active price
        entry["preco"] = _infer_preco(item, entry.get("negociacao"))

        # Ensure data_coleta has a value
        if not entry["data_coleta"]:
            entry["data_coleta"] = now

        # Compute tem_reducao if not explicitly set
        if not entry["tem_reducao"]:
            prev = entry.get("preco_anterior")
            curr = entry.get("preco_venda")
            if prev is not None and curr is not None and prev > curr:
                entry["tem_reducao"] = True
                entry["percentual_reducao"] = round((1 - curr / prev) * 100, 2)

        result.append(entry)

    return result


def save_listings(
    items: list[dict],
    output_path: str | Path,
    filter_fn: Callable | None = None,
    **filter_kwargs: Any,
) -> Path:
    """Normalize, optionally filter, and save listings to a JSON file.

    Steps:
    1. Normalize all items to the unified schema.
    2. If filter_fn is provided, apply it with any extra keyword args.
    3. Write the result to output_path as a pretty-printed JSON file.

    Args:
        items: Raw listing dicts from any parser.
        output_path: Path for the output JSON file.
        filter_fn: Optional filter function. Must accept (items, **kwargs)
                   and return a filtered list of dicts.
                   Example: filter_imoveis from skills.filter_imoveis.
        **filter_kwargs: Additional keyword args forwarded to filter_fn
                         (e.g., tipo='apartamento', bairro='Moema').

    Returns:
        Absolute Path of the saved file.

    Raises:
        ValueError: If filter_fn is provided but fails.
        OSError: If the output file cannot be written.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: Normalize
    normalized = normalize_to_schema(items)
    logger.info(f"Normalized {len(normalized)} items to unified schema")

    if not normalized:
        logger.warning("No items to save after normalization")
        # Write empty file anyway
        _write_json(output, _build_output_envelope(normalized, "loft"))
        return output.resolve()

    # Step 2: Apply filter if provided
    if filter_fn is not None:
        try:
            filtered = filter_fn(normalized, **filter_kwargs)
            logger.info(
                f"Filter applied: {len(normalized)} → {len(filtered)} items "
                f"(filter_fn={filter_fn.__name__}, kwargs={filter_kwargs})"
            )
        except Exception as exc:
            raise ValueError(
                f"Filter function {filter_fn.__name__} failed: {exc}"
            ) from exc
    else:
        filtered = normalized

    # Step 3: Write
    _write_json(output, _build_output_envelope(filtered, None))
    logger.info(f"Saved {len(filtered)} listings to {output.resolve()}")

    return output.resolve()


def save_listings_batch(
    batches: dict[str, list[dict]],
    output_dir: str | Path = "data/results",
    filter_fn: Callable | None = None,
    **filter_kwargs: Any,
) -> Path:
    """Save multiple source batches into one unified JSON file with provenance.

    Each batch key is a source name (e.g., 'loft', 'emcasa'). Items from
    all batches are normalized, merged, optionally filtered, and saved
    to a single timestamped file.

    Args:
        batches: Dict mapping source name → list of raw listing dicts.
        output_dir: Directory for the output file.
        filter_fn: Optional filter function (same semantics as save_listings).
        **filter_kwargs: Keyword args forwarded to filter_fn.

    Returns:
        Absolute Path of the saved merged file.
    """
    output_dir_p = Path(output_dir)
    output_dir_p.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir_p / f"coleta_unificada_{timestamp}.json"

    all_normalized: list[dict] = []
    provenance: dict[str, int] = {}

    for source, source_items in batches.items():
        normalized = normalize_to_schema(source_items)
        # Ensure each item has the correct source
        for item in normalized:
            if not item["fonte"]:
                item["fonte"] = source
        all_normalized.extend(normalized)
        provenance[source] = len(normalized)
        logger.info(f"  {source}: {len(normalized)} items")

    logger.info(f"Total normalized: {len(all_normalized)} items from {len(batches)} sources")

    # Apply filter
    if filter_fn is not None:
        try:
            filtered = filter_fn(all_normalized, **filter_kwargs)
            logger.info(
                f"Filter applied: {len(all_normalized)} → {len(filtered)} items"
            )
        except Exception as exc:
            raise ValueError(
                f"Filter function {filter_fn.__name__} failed: {exc}"
            ) from exc
    else:
        filtered = all_normalized

    # Write
    envelope = {
        "versao": 1,
        "schema": "imovel_schema.json",
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fontes": provenance,
        "total": len(filtered),
        "total_bruto": len(all_normalized),
        "filtro": {
            "aplicado": filter_fn.__name__ if filter_fn else None,
            "kwargs": filter_kwargs if filter_fn else None,
        },
        "imoveis": filtered,
    }

    _write_json(output_path, envelope)
    logger.info(f"Saved {len(filtered)} unified listings to {output_path.resolve()}")

    return output_path.resolve()


def _build_output_envelope(
    listings: list[dict],
    source: str | None,
) -> dict:
    """Build the output envelope with metadata."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "versao": 1,
        "schema": "imovel_schema.json",
        "gerado_em": now,
        "fonte": source or "multiplas",
        "total": len(listings),
        "imoveis": listings,
    }


def _write_json(path: Path, data: dict | list) -> None:
    """Write JSON to a file with pretty-printing."""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ── Schema validation helper ──────────────────────────────────────────────────


def validate_against_schema(
    items: list[dict],
    schema_path: str | Path | None = None,
) -> list[dict]:
    """Validate a list of unified-schema items against the JSON Schema file.

    This is an optional runtime check using the `jsonschema` library.
    If jsonschema is not installed, a warning is logged and items are
    returned as-is.

    Args:
        items: List of normalized items to validate.
        schema_path: Path to imovel_schema.json. If None, auto-detected.

    Returns:
        The validated items (same list if valid, or raises on first error).
    """
    try:
        import jsonschema
    except ImportError:
        logger.warning(
            "jsonschema not installed — skipping schema validation. "
            "Install with: pip install jsonschema"
        )
        return items

    if schema_path is None:
        # Auto-detect relative to this file's location
        schema_path = Path(__file__).resolve().parent / "imovel_schema.json"

    schema_path = Path(schema_path)
    if not schema_path.exists():
        logger.warning(f"Schema file not found: {schema_path}")
        return items

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    errors: list[str] = []
    for i, item in enumerate(items):
        try:
            jsonschema.validate(instance=item, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"Item[{i}] ({item.get('codigo', '?')}): {exc.message}")

    if errors:
        for err in errors:
            logger.warning(f"Schema validation error: {err}")
        raise ValueError(
            f"{len(errors)} items failed schema validation. "
            f"First error: {errors[0]}"
        )

    logger.info(f"All {len(items)} items passed schema validation")
    return items


# ── CLI ───────────────────────────────────────────────────────────────────────


def main():
    """CLI for output_schema."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Output Schema — normalize, filter, and save listings"
    )
    parser.add_argument("input", nargs="?", help="Input JSON file (or '--stdin' for stdin)")
    parser.add_argument("--output", "-o", default="data/results/output.json",
                        help="Output JSON file path")
    parser.add_argument("--filter-tipo", help="Filter by property type")
    parser.add_argument("--filter-negociacao", help="Filter by negotiation type (venda/aluguel)")
    parser.add_argument("--filter-bairro", help="Filter by neighborhood")
    parser.add_argument("--validate", action="store_true",
                        help="Validate against schema (requires jsonschema)")
    parser.add_argument("--stdin", action="store_true",
                        help="Read input from stdin (piped JSON)")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s: %(levelname)s: %(message)s",
    )

    # Load input
    if args.stdin:
        raw_items = json.loads(sys.stdin.read())
    elif args.input:
        input_path = Path(args.input)
        raw_items = json.loads(input_path.read_text(encoding="utf-8"))
    else:
        parser.print_help()
        sys.exit(1)

    # If input is an envelope dict, unwrap
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("imoveis", raw_items.get("listings", raw_items))
    if not isinstance(raw_items, list):
        logger.error("Input must be a list of items or an envelope dict")
        sys.exit(1)

    # Normalize
    normalized = normalize_to_schema(raw_items)
    logger.info(f"Normalized {len(normalized)} items")

    # Optional schema validation
    if args.validate:
        validate_against_schema(normalized)

    # Build filter chain
    filter_fn = None
    filter_kwargs: dict[str, Any] = {}
    if args.filter_tipo or args.filter_negociacao or args.filter_bairro:
        try:
            from skills.filter_imoveis import filter_imoveis
            filter_fn = filter_imoveis
            if args.filter_tipo:
                filter_kwargs["tipo"] = args.filter_tipo
            if args.filter_negociacao:
                filter_kwargs["negociacao"] = args.filter_negociacao
            if args.filter_bairro:
                filter_kwargs["bairro"] = args.filter_bairro
        except ImportError:
            logger.warning("filter_imoveis not available, applying inline filter")
            # Simple inline filter
            if args.filter_tipo:
                normalized = [i for i in normalized
                              if i.get("tipo", "").lower() == args.filter_tipo.lower()]
            if args.filter_negociacao:
                normalized = [i for i in normalized
                              if i.get("negociacao", "").lower() == args.filter_negociacao.lower()]
            if args.filter_bairro:
                normalized = [i for i in normalized
                              if args.filter_bairro.lower() in i.get("bairro", "").lower()]
            filter_fn = None

    # Save
    path = save_listings(normalized, args.output, filter_fn=filter_fn, **filter_kwargs)
    print(f"Salvo: {path}")
    print(f"Total de imóveis: {len(normalized)}")


if __name__ == "__main__":
    main()
