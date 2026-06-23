"""
Tests for QuintoAndar extraction (skills/quinto-andar/extraction.py).

Tiers:
  Tier 1 — Unit tests for helper functions (_imovel_to_listing_dict, _find_raw_listing)
  Tier 2 — Integration test using mock payload data
  Tier 3 — Smoke test (skipped by default, requires real browser + Playwright)

Run:
    python skills/quinto-andar/test_extraction.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root and schema in path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SKILL_DIR = str(_PROJECT_ROOT / "skills" / "quinto-andar")
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)
sys.path.insert(0, str(Path.home() / ".hermes"))

from imovel_schema import Imovel
from extraction import (
    _imovel_to_listing_dict,
    _find_raw_listing,
    _parse_payload,
    extract_listings,
)

# ── Sample Imovel object (as returned by from_quintoandar_listing) ─────────

SAMPLE_IMOVEL = Imovel(
    id="892820623",
    titulo="Apartamento 3 quartos em Santana",
    url="https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/892820623",
    fonte="quintoandar",
    endereco="R. Mal. Hermes da Fonseca, 123",
    bairro="Santana",
    cidade="São Paulo",
    uf="SP",
    preco_venda=1000000.0,
    preco_aluguel=3700.0,
    condominio=800.0,
    iptu=150.50,
    area=105.0,
    quartos=3,
    banheiros=2,
    vagas=3,
    tipo="apartamento",
    descricao="Ótimo apartamento na região de Santana",
    amenities=["piscina", "academia"],
    fotos=[
        "https://img.quintoandar.com.br/foto1.jpg",
        "https://img.quintoandar.com.br/foto2.jpg",
    ],
)

# Sample raw listing dict mirroring what QuintoAndar returns
SAMPLE_RAW_LISTING = {
    "id": "892820623",
    "salePrice": 1000000,
    "rentPrice": 3700,
    "area": 105,
    "bedrooms": 3,
    "bathrooms": 2,
    "parkingSpots": 3,
    "type": "Apartamento",
    "address": {
        "address": "R. Mal. Hermes da Fonseca, 123",
        "city": "São Paulo",
        "stateCode": "SP",
        "neighborhood": "Santana",
    },
    "neighbourhood": "Santana",
    "regionName": "Santana",
    "condoIptu": {"condoFee": 800, "iptu": 150.50},
    "forSale": True,
    "shortSaleDescription": "Apartamento para comprar em Santana com 3 quartos, 2 banheiros, 105m² e 3 vagas de garagem",
    "description": "Ótimo apartamento na região de Santana",
    "title": "Apartamento 3 quartos em Santana",
    "amenities": ["Piscina", "Academia"],
    "photos": [{"url": "https://img.quintoandar.com.br/foto1.jpg"}],
    "citySlug": "sao-paulo-sp-brasil",
}

SAMPLE_PAYLOAD = {
    "pageProps": {
        "initialState": {
            "houses": {
                "892820623": SAMPLE_RAW_LISTING,
            },
            "search": {"count": 1},
        }
    }
}


# ── Tier 1: Unit tests ──────────────────────────────────────────────────


def test_imovel_to_listing_dict():
    """Convert Imovel → listing dict with required keys."""
    result = _imovel_to_listing_dict(SAMPLE_IMOVEL, SAMPLE_PAYLOAD)

    # All required keys present
    required_keys = {
        "id", "salePrice", "rentPrice", "area", "bedrooms", "bathrooms",
        "parkingSpots", "type", "address", "neighbourhood", "condoIptu",
        "photos", "amenities", "shortSaleDescription",
    }
    assert required_keys.issubset(result.keys()), f"Missing keys: {required_keys - result.keys()}"

    # Values preserved
    assert result["id"] == "892820623"
    assert result["salePrice"] == 1000000.0
    assert result["rentPrice"] == 3700.0
    assert result["area"] == 105.0
    assert result["bedrooms"] == 3
    assert result["bathrooms"] == 2
    assert result["parkingSpots"] == 3
    assert result["type"] == "apartamento"
    assert result["neighbourhood"] == "Santana"
    assert len(result["photos"]) == 2
    assert len(result["amenities"]) == 2
    assert "Santana" in result["shortSaleDescription"]

    # condoIptu is an object
    assert isinstance(result["condoIptu"], dict)
    assert result["condoIptu"]["condoFee"] == 800.0
    assert result["condoIptu"]["iptu"] == 150.50

    # address from raw payload is the raw object
    assert isinstance(result["address"], dict)
    assert result["address"].get("address") == "R. Mal. Hermes da Fonseca, 123"
    assert result["address"].get("city") == "São Paulo"

    print(f"[PASS] test_imovel_to_listing_dict: {len(result)} keys OK")


def test_imovel_to_listing_dict_minimal():
    """Minimal Imovel (no optional fields) → defaults to None/empty."""
    minimal = Imovel(
        id="12345",
        preco_venda=350000.0,
        area=45.0,
        quartos=2,
        banheiros=1,
        tipo="casa",
    )
    result = _imovel_to_listing_dict(minimal)

    assert result["id"] == "12345"
    assert result["salePrice"] == 350000.0
    assert result["rentPrice"] is None
    assert result["condoIptu"] is None
    assert result["address"] is None
    assert result["neighbourhood"] is None
    assert result["photos"] == []
    assert result["amenities"] == []

    print(f"[PASS] test_imovel_to_listing_dict_minimal: all optional fields handled")


def test_imovel_to_listing_dict_rent_only():
    """Rent-only listing → rentPrice set, salePrice None."""
    rent_only = Imovel(
        id="67890",
        preco_aluguel=2500.0,
        area=50.0,
        bairro="Centro",
    )
    result = _imovel_to_listing_dict(rent_only)

    assert result["salePrice"] is None
    assert result["rentPrice"] == 2500.0
    assert result["neighbourhood"] == "Centro"

    print(f"[PASS] test_imovel_to_listing_dict_rent_only: rentPrice={result['rentPrice']}")


def test_find_raw_listing():
    """Find raw listing dict by id in payload."""
    result = _find_raw_listing(SAMPLE_PAYLOAD, "892820623")
    assert result is not None
    assert result["id"] == "892820623"
    assert result["address"]["city"] == "São Paulo"
    print(f"[PASS] test_find_raw_listing: found id={result['id']}")

    # Non-existent id → None
    assert _find_raw_listing(SAMPLE_PAYLOAD, "nonexistent") is None
    print(f"[PASS] test_find_raw_listing: missing id → None")


def test_find_raw_listing_list_format():
    """Find raw listing when houses is a list (not dict)."""
    payload = {
        "pageProps": {
            "initialState": {
                "houses": [SAMPLE_RAW_LISTING],
            }
        }
    }
    result = _find_raw_listing(payload, "892820623")
    assert result is not None
    assert result["id"] == "892820623"
    print(f"[PASS] test_find_raw_listing_list_format: found id={result['id']}")


def test_parse_payload():
    """Parse Next.js payload → list of listing dicts."""
    raw_listing_simple = {
        "id": "111",
        "salePrice": 500000,
        "type": "Apartamento",
        "area": 70,
        "bedrooms": 2,
        "bathrooms": 1,
    }
    payload = {
        "pageProps": {
            "initialState": {
                "houses": [raw_listing_simple],
            }
        }
    }

    imoveis = _parse_payload(payload)
    assert len(imoveis) == 1
    assert imoveis[0].id == "111"
    assert imoveis[0].preco_venda == 500000.0
    print(f"[PASS] test_parse_payload: {len(imoveis)} imoveis")


def test_empty_payload():
    """Empty payload → empty list."""
    assert _parse_payload({}) == []
    assert _parse_payload(None) == []  # type: ignore
    assert _parse_payload([]) == []  # type: ignore
    print(f"[PASS] test_empty_payload: all empty cases handled")


# ── JSON serialization check ──────────────────────────────────────────


def test_json_serializable():
    """Result of _imovel_to_listing_dict must be JSON-serializable."""
    result = _imovel_to_listing_dict(SAMPLE_IMOVEL, SAMPLE_PAYLOAD)
    json_str = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(json_str)
    assert parsed["id"] == "892820623"
    assert parsed["salePrice"] == 1000000.0
    assert parsed["condoIptu"]["condoFee"] == 800.0
    assert len(parsed["photos"]) == 2
    print(f"[PASS] test_json_serializable: JSON roundtrip OK ({len(json_str)} chars)")


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_imovel_to_listing_dict,
        test_imovel_to_listing_dict_minimal,
        test_imovel_to_listing_dict_rent_only,
        test_find_raw_listing,
        test_find_raw_listing_list_format,
        test_parse_payload,
        test_empty_payload,
        test_json_serializable,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"Resultado: {passed} passaram, {failed} falharam")
    sys.exit(0 if failed == 0 else 1)
