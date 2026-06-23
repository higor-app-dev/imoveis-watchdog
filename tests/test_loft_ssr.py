"""
test_loft_ssr.py — Unit tests for Loft SSR data extraction.

Tests the loft_ssr module:
- extract_from_html(): parsing __NEXT_DATA__ from a cached HTML sample
- extract_from_ssr(): end-to-end HTTP fetch + parse
- Fallback DOM parsing when __NEXT_DATA__ is missing
- Field mapping completeness for all required fields
"""

import json
import os
import re
import sys
from pathlib import Path

# Allow importing from project root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import pytest

from skills.loft.loft_ssr import (
    extract_from_html,
    extract_from_ssr,
    extract_from_dom,
    map_listing_to_imovel,
    _extract_next_data_json,
    _map_property_type,
    _build_photo_urls,
    _get_neighborhood,
)


# ── Required output fields ─────────────────────────────────────────────────

REQUIRED_FIELDS = [
    "id",               # Property code
    "titulo",           # Title
    "fonte",            # Source (always "loft")
    "preco_venda",      # Sale price
    "condominio",       # Condo fee
    "endereco",         # Address
    "bairro",           # Neighborhood
    "area",             # Area in m²
    "quartos",          # Bedrooms
    "banheiros",        # Bathrooms
    "vagas",            # Parking spots
    "tipo",             # Property type
    "url",              # Listing URL
    "imagens",          # Photo URLs
]

# Fields that should be present but may be null
OPTIONAL_FIELDS = [
    "preco_anterior",
    "iptu",
    "suites",
    "andar",
    "cep",
    "latitude",
    "longitude",
    "preco_aluguel",
    "tem_reducao",
    "percentual_reducao",
]


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def loft_html_sample():
    """Fetch a fresh Loft search page HTML once per test session."""
    import requests
    r = requests.get(
        "https://loft.com.br/venda/apartamentos/sp/sao-paulo/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.text


@pytest.fixture(scope="session")
def ssr_listings(loft_html_sample):
    """Parse listings from the cached HTML once per test session."""
    return extract_from_html(loft_html_sample, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/")


# ── Tests: __NEXT_DATA__ extraction ────────────────────────────────────────────


class TestNextDataExtraction:
    def test_extract_next_data_present(self, loft_html_sample):
        """__NEXT_DATA__ script tag must be present in the HTML."""
        assert "__NEXT_DATA__" in loft_html_sample

    def test_extract_next_data_valid_json(self, loft_html_sample):
        """__NEXT_DATA__ content must be valid JSON."""
        nd = _extract_next_data_json(loft_html_sample)
        assert nd is not None, "Failed to extract __NEXT_DATA__"
        assert isinstance(nd, dict), "__NEXT_DATA__ is not a dict"
        assert "props" in nd, "__NEXT_DATA__ missing 'props'"
        assert "pageProps" in nd["props"], "__NEXT_DATA__ missing 'pageProps'"

    def test_has_listing_search_query(self, loft_html_sample):
        """Must contain Listing:Search query with listings data."""
        nd = _extract_next_data_json(loft_html_sample)
        assert nd is not None
        queries = (nd.get("props", {}).get("pageProps", {})
                   .get("dehydratedState", {}).get("queries", []))
        assert len(queries) > 0, "No queries in dehydratedState"

        search = next(
            (q for q in queries
             if isinstance(q.get("queryKey"), list)
             and q["queryKey"][0] == "Listing:Search"),
            None,
        )
        assert search is not None, "Listing:Search query not found"
        data = search.get("state", {}).get("data", {})
        assert "listings" in data, "No 'listings' key in search data"
        assert len(data["listings"]) > 0, "Empty listings array"


# ── Tests: field mapping ──────────────────────────────────────────────────────


class TestFieldMapping:
    def test_all_required_fields_present(self, ssr_listings):
        """Every extracted listing must have all required fields."""
        assert len(ssr_listings) > 0, "No listings extracted"
        for i, listing in enumerate(ssr_listings):
            for field in REQUIRED_FIELDS:
                msg = f"Listing {i} (id={listing.get('id')}): missing required field '{field}'"
                assert field in listing, msg

    def test_all_required_fields_non_empty(self, ssr_listings):
        """Every listing should have non-empty values for critical fields."""
        for i, listing in enumerate(ssr_listings):
            assert listing["id"], f"Listing {i}: empty id"
            assert listing["titulo"], f"Listing {i}: empty titulo"
            assert listing["fonte"] == "loft", f"Listing {i}: fonte != 'loft'"
            assert listing["area"] is None or listing["area"] > 0, \
                f"Listing {i}: invalid area={listing['area']}"

    def test_price_present(self, ssr_listings):
        """At least one of preco_venda or preco_aluguel must be present."""
        for i, listing in enumerate(ssr_listings):
            has_sale = listing.get("preco_venda") is not None
            has_rent = listing.get("preco_aluguel") is not None
            assert has_sale or has_rent, \
                f"Listing {i} ({listing['id']}): neither sale nor rent price"

    def test_all_types_valid(self, ssr_listings):
        """Property types must be valid Portuguese names."""
        valid_types = {
            "apartamento", "casa", "kitnet", "cobertura",
            "studio", "flat", "duplex", "triplex",
            "casa_condominio", "conjugado", "outro",
        }
        for i, listing in enumerate(ssr_listings):
            assert listing["tipo"] in valid_types, \
                f"Listing {i}: invalid tipo '{listing['tipo']}'"

    def test_no_default_type(self, ssr_listings):
        """No listing should have tipo='default'."""
        defaults = [l for l in ssr_listings if l["tipo"] == "default"]
        assert len(defaults) == 0, f"{len(defaults)} listings have tipo='default'"

    def test_url_is_valid(self, ssr_listings):
        """URLs must be valid HTTP URLs."""
        for i, listing in enumerate(ssr_listings):
            url = listing.get("url", "")
            assert url.startswith("http"), \
                f"Listing {i}: url '{url}' doesn't start with http"

    def test_photos_are_urls(self, ssr_listings):
        """Photo URLs must be valid HTTP URLs."""
        for i, listing in enumerate(ssr_listings):
            for j, img in enumerate(listing.get("imagens", [])):
                assert img.startswith("http"), \
                    f"Listing {i} photo {j}: '{img[:50]}' doesn't start with http"

    def test_price_types_are_numeric(self, ssr_listings):
        """Numeric price fields must be numbers, not strings."""
        for i, listing in enumerate(ssr_listings):
            for field in ["preco_venda", "preco_anterior", "condominio", "iptu", "area"]:
                val = listing.get(field)
                if val is not None:
                    assert isinstance(val, (int, float)), \
                        f"Listing {i}: {field} is {type(val).__name__}, expected number"

    def test_required_int_fields(self, ssr_listings):
        """Integer fields must be ints or None."""
        for i, listing in enumerate(ssr_listings):
            for field in ["quartos", "banheiros", "vagas", "suites", "andar"]:
                val = listing.get(field)
                if val is not None:
                    assert isinstance(val, int), \
                        f"Listing {i}: {field} is {type(val).__name__}, expected int or None"


# ── Tests: price reduction detection ──────────────────────────────────────────


class TestPriceReduction:
    def test_reduction_fields_present(self, ssr_listings):
        """Every listing must have tem_reducao and percentual_reducao."""
        for i, listing in enumerate(ssr_listings):
            assert "tem_reducao" in listing, f"Listing {i}: missing tem_reducao"
            assert "percentual_reducao" in listing, \
                f"Listing {i}: missing percentual_reducao"

    def test_reduction_values_consistent(self, ssr_listings):
        """tem_reducao=False must have percentual_reducao=0."""
        for i, listing in enumerate(ssr_listings):
            if not listing.get("tem_reducao"):
                assert listing.get("percentual_reducao", 0) == 0 or \
                       listing.get("percentual_reducao") is None, \
                    f"Listing {i}: tem_reducao=False but pct={listing['percentual_reducao']}"

    def test_reduction_matches_prices(self, ssr_listings):
        """If previousPrice > price, tem_reducao must be True."""
        for i, listing in enumerate(ssr_listings):
            prev = listing.get("preco_anterior")
            curr = listing.get("preco_venda")
            if prev and curr and prev > curr:
                assert listing.get("tem_reducao"), \
                    f"Listing {i}: previousPrice > price but tem_reducao=False"

    def test_some_reductions_found(self, ssr_listings):
        """At least some listings in SP should have price reductions."""
        reductions = [l for l in ssr_listings if l.get("tem_reducao")]
        assert len(reductions) > 0, \
            "No price reductions found — Loft market may have changed"


# ── Tests: extract_from_ssr (end-to-end) ──────────────────────────────────────


class TestEndToEnd:
    def test_fetch_and_extract(self):
        """End-to-end: fetch real Loft page and extract listings."""
        listings = extract_from_ssr(
            "https://loft.com.br/venda/apartamentos/sp/sao-paulo/",
            timeout=30,
        )
        assert len(listings) > 0, "No listings extracted from live URL"
        assert len(listings) <= 100, f"Unexpectedly large result: {len(listings)}"
        assert all(l["fonte"] == "loft" for l in listings)

    def test_fetch_casas(self):
        """End-to-end: extract casa listings."""
        listings = extract_from_ssr(
            "https://loft.com.br/venda/casas/sp/sao-paulo/",
            timeout=30,
        )
        assert len(listings) > 0, "No casa listings"
        assert all(l["tipo"] == "casa" for l in listings), \
            "Not all extracted listings are 'casa'"

    def test_fetch_empty_url_returns_empty(self):
        """A URL that doesn't exist should raise an error."""
        import requests
        with pytest.raises(requests.RequestException):
            extract_from_ssr(
                "https://loft.com.br/venda/nonexistent-type/sp/sao-paulo/",
                timeout=10,
            )


# ── Tests: fallback DOM parsing ───────────────────────────────────────────────


class TestDomFallback:
    def test_extract_from_dom_without_next_data(self):
        """Fallback should work on pages without __NEXT_DATA__."""
        # A minimal HTML page with meta tags
        html = """<!DOCTYPE html>
<html><head>
<meta property="og:title" content="Apartamento na Consolação SP - R$ 450.000">
<meta property="og:description" content="Lindo apartamento na Consolação">
<meta property="og:image" content="https://img.loft.com.br/photo.jpg">
<script type="application/ld+json">
{"@type":"Product","name":"Apto Consolação","offers":{"price":450000,"priceCurrency":"BRL"},"url":"https://loft.com.br/imovel/test"}
</script>
</head><body></body></html>"""
        listings = extract_from_dom(html)
        assert len(listings) > 0, "DOM fallback returned no listings"
        assert any("Consolação" in l.get("titulo", "") for l in listings)

    def test_extract_from_dom_empty_html(self):
        """Fallback should return empty list for truly empty HTML."""
        listings = extract_from_dom("<html></html>")
        assert listings == [], f"Expected empty, got {len(listings)}"

    def test_extract_from_html_fallback_chain(self):
        """extract_from_html should chain to DOM fallback when no __NEXT_DATA__."""
        html = """<html><head>
<meta property="og:title" content="Test Listing">
</head><body></body></html>"""
        listings = extract_from_html(html)
        # Should still get at least 1 from DOM fallback
        assert len(listings) > 0


# ── Tests: helper functions ───────────────────────────────────────────────────


class TestHelpers:
    def test_map_property_type(self):
        assert _map_property_type("default") == "apartamento"
        assert _map_property_type("apartment") == "apartamento"
        assert _map_property_type("rooftop") == "cobertura"
        assert _map_property_type("house") == "casa"
        assert _map_property_type("studio") == "studio"
        assert _map_property_type("duplex") == "duplex"
        assert _map_property_type(None) == "apartamento"
        assert _map_property_type("") == "apartamento"
        assert _map_property_type("unknown") == "unknown"

    def test_build_photo_urls(self):
        urls = _build_photo_urls(["a.jpg", "b.jpg"])
        assert len(urls) == 2
        assert urls[0].startswith("https://content.loft.com.br/homes/")
        assert urls[1].startswith("https://content.loft.com.br/homes/")

    def test_build_photo_urls_dedup(self):
        urls = _build_photo_urls(["a.jpg", "a.jpg", "b.jpg"])
        assert len(urls) == 2  # Deduplication

    def test_build_photo_urls_with_absolute(self):
        urls = _build_photo_urls(["https://cdn.example.com/photo.jpg"])
        assert urls == ["https://cdn.example.com/photo.jpg"]

    def test_build_photo_urls_empty(self):
        assert _build_photo_urls(None) == []
        assert _build_photo_urls([]) == []

    def test_get_neighborhood(self):
        # Direct neighborhood field
        addr1 = {"neighborhood": "Vila Madalena"}
        assert _get_neighborhood(addr1) == "Vila Madalena"

        # Nested neighbourhood object
        addr2 = {"neighbourhood": {"name": "Pinheiros", "slug": "pinheiros_sp"}}
        assert _get_neighborhood(addr2) == "Pinheiros"

        # Empty
        assert _get_neighborhood({}) == ""

    def test_map_listing_to_imovel_none(self):
        assert map_listing_to_imovel(None) is None
        assert map_listing_to_imovel({}) is None  # Empty dict has no values

    def test_map_listing_to_imovel_minimal(self):
        # A minimal working listing
        raw = {
            "id": "test123",
            "price": 500000,
            "transactionType": "FOR_SALE",
            "status": "FOR_SALE",
            "address": {
                "neighborhood": "Teste",
                "city": "São Paulo",
                "state": "SP",
            },
            "homeType": "apartment",
        }
        result = map_listing_to_imovel(raw)
        assert result is not None
        assert result["id"] == "test123"
        assert result["preco_venda"] == 500000.0
        assert result["tipo"] == "apartamento"
        assert result["fonte"] == "loft"
        assert result["bairro"] == "Teste"
