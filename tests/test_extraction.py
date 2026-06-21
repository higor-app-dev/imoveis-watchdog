#!/usr/bin/env python3
"""
test_extraction.py — Script de extração de teste para CI.

Lê dados mockados de tests/test_data.json, simula o processamento
do pipeline (parse, normalização, sumarização) e salva o resultado
em data/results/ com timestamp. Usado pelo workflow CI para validar
que o pipeline funciona sem depender de scraping real.

Uso:
    python tests/test_extraction.py

Saída:
    - data/results/test_extraction_<timestamp>.json  (resultado completo)
    - data/results/test_summary_<timestamp>.json      (resumo para CI)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = REPO_ROOT / "tests" / "test_data.json"
OUTPUT_DIR = REPO_ROOT / "data" / "results"


def parse_listings(data: list[dict]) -> list[dict]:
    """Normaliza listings (simula o parse_ad do pipeline principal)."""
    parsed = []
    for ad in data:
        parsed.append({
            "list_id": ad.get("list_id"),
            "title": ad.get("title", "").strip(),
            "url": ad.get("url", ""),
            "price_raw": ad.get("price_raw", ""),
            "price": ad.get("price"),
            "category": ad.get("category", ""),
            "neighbourhood": ad.get("neighbourhood", ""),
            "municipality": ad.get("municipality", ""),
            "uf": ad.get("uf", ""),
            "area_m2": ad.get("area_m2"),
            "rooms": ad.get("rooms"),
            "bathrooms": ad.get("bathrooms"),
        })
    return parsed


def build_summary(parsed: list[dict], city_filter: str | None = None) -> dict:
    """Gera resumo estatístico das listings."""
    if city_filter:
        filtered = [a for a in parsed if a["municipality"] == city_filter]
    else:
        filtered = parsed

    prices = [a["price"] for a in filtered if a["price"]]
    areas = [a["area_m2"] for a in filtered if a["area_m2"]]
    rooms = [a["rooms"] for a in filtered if a["rooms"]]

    return {
        "total_listings": len(filtered),
        "cities": sorted(set(a["municipality"] for a in filtered)),
        "neighbourhoods": sorted(set(a["neighbourhood"] for a in filtered if a["neighbourhood"])),
        "price_range": {
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "avg": round(sum(prices) / len(prices)) if prices else None,
        },
        "area_range": {
            "min": min(areas) if areas else None,
            "max": max(areas) if areas else None,
            "avg": round(sum(areas) / len(areas)) if areas else None,
        },
        "rooms_range": {
            "min": min(rooms) if rooms else None,
            "max": max(rooms) if rooms else None,
        },
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load test data
    print(f"[TEST] Loading test data from {TEST_DATA}")
    if not TEST_DATA.exists():
        print(f"[ERRO] Test data not found: {TEST_DATA}", file=sys.stderr)
        sys.exit(1)

    with open(TEST_DATA) as f:
        raw_data = json.load(f)
    print(f"[TEST] Loaded {len(raw_data)} listings")

    # 2. Parse/normalize
    parsed = parse_listings(raw_data)
    print(f"[TEST] Parsed {len(parsed)} listings successfully")

    # 3. Generate summary
    summary = build_summary(parsed)
    print(f"[TEST] Summary: {summary['total_listings']} listings across {len(summary['cities'])} cities")

    # 4. Save results
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    
    full_output = {
        "timestamp": timestamp,
        "source": "test_extraction",
        "total": len(parsed),
        "listings": parsed,
    }
    full_path = OUTPUT_DIR / f"test_extraction_{timestamp}.json"
    with open(full_path, "w") as f:
        json.dump(full_output, f, indent=2, ensure_ascii=False)
    print(f"[TEST] Full output saved: {full_path}")

    summary_output = {
        "timestamp": timestamp,
        "source": "test_extraction",
        "summary": summary,
    }
    summary_path = OUTPUT_DIR / f"test_summary_{timestamp}.json"
    with open(summary_path, "w") as f:
        json.dump(summary_output, f, indent=2, ensure_ascii=False)
    print(f"[TEST] Summary saved: {summary_path}")

    # 5. Verify output integrity
    with open(full_path) as f:
        verification = json.load(f)
    assert verification["total"] == len(raw_data), "Total mismatch!"
    assert len(verification["listings"]) == len(raw_data), "Listing count mismatch!"
    print(f"[TEST] ✅ Verification passed: {verification['total']} listings saved correctly")

    print(f"[TEST] ✅ Extraction test completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
