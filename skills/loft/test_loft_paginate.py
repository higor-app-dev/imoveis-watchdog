"""
Tests for loft_paginate — pagination loop and URL construction.

Tests the URL builder, category definitions, and pagination logic
without making actual HTTP requests (mocks extract_from_ssr).
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from skills.loft.loft_paginate import (
    build_page_url,
    LISTING_CATEGORIES,
    VALID_CITIES,
    DEFAULT_CATEGORY,
    DEFAULT_CITY,
    fetch_page,
    crawl_category,
    crawl_all_categories,
    get_default_categories,
    save_results,
    parse_categories,
)


class TestBuildPageUrl(unittest.TestCase):
    """Test URL construction for paginated Loft pages."""

    def test_page_1_no_suffix(self):
        """Page 1 has no '-pagina' suffix."""
        url = build_page_url("venda/apartamentos", "sp/sao-paulo", page=1)
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/")

    def test_page_2_with_suffix(self):
        """Page 2 gets '-pagina' suffix."""
        url = build_page_url("venda/apartamentos", "sp/sao-paulo", page=2)
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/2-pagina")

    def test_page_3_with_suffix(self):
        """Page 3 gets '-pagina' suffix."""
        url = build_page_url("venda/apartamentos", "sp/sao-paulo", page=3)
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/3-pagina")

    def test_aluguel_casas(self):
        """Aluguel de casas generates correct URL."""
        url = build_page_url("aluguel/casas", "sp/sao-paulo", page=2)
        self.assertEqual(url, "https://loft.com.br/aluguel/casas/sp/sao-paulo/2-pagina")

    def test_page_0_defaults_to_page_1(self):
        """Page 0 or negative should behave like page 1 (no suffix)."""
        url = build_page_url("venda/apartamentos", page=0)
        self.assertNotIn("-pagina", url)
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/")

    def test_default_category(self):
        """Default category (venda/apartamentos) works."""
        url = build_page_url()
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/")


class TestCategories(unittest.TestCase):
    """Test category listing and configuration."""

    def test_has_venda_apartamentos(self):
        """'venda/apartamentos' is in the default categories."""
        cats = get_default_categories()
        self.assertIn("venda/apartamentos", cats)

    def test_has_aluguel(self):
        """Rental categories are included."""
        cats = get_default_categories()
        rental_cats = [c for c in cats if c.startswith("aluguel/")]
        self.assertGreater(len(rental_cats), 2)

    def test_balanced_transaction_types(self):
        """Both venda and aluguel categories are present."""
        cats = get_default_categories()
        venda = [c for c in cats if c.startswith("venda/")]
        aluguel = [c for c in cats if c.startswith("aluguel/")]
        self.assertGreater(len(venda), 2)
        self.assertGreater(len(aluguel), 2)

    def test_all_cities_valid(self):
        """All cities have the 'sp/sao-paulo' format."""
        self.assertIn("sp/sao-paulo", VALID_CITIES)

    def test_get_default_categories_returns_copy(self):
        """get_default_categories returns a new list, not a reference."""
        cats1 = get_default_categories()
        cats2 = get_default_categories()
        cats1.append("test")
        self.assertNotIn("test", cats2)


class TestFetchPage(unittest.TestCase):
    """Test single page fetching with mocked SSR."""

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_fetch_page_mocked(self, mock_fetch):
        """fetch_page can be mocked for testing."""
        mock_fetch.return_value = [
            {"id": "test1", "fonte": "loft", "preco_venda": 500000.0},
            {"id": "test2", "fonte": "loft", "preco_venda": 750000.0},
        ]
        result = mock_fetch("venda/apartamentos", "sp/sao-paulo", page=1)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["id"], "test1")

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_fetch_page_empty(self, mock_fetch):
        """An empty page returns an empty list."""
        mock_fetch.return_value = []
        result = mock_fetch("venda/apartamentos", "sp/sao-paulo", page=99)
        self.assertEqual(result, [])


class TestCrawlCategory(unittest.TestCase):
    """Test crawling a single category with mocked SSR."""

    def _make_listing(self, idx: int) -> dict:
        return {
            "id": f"listing_{idx:04d}",
            "fonte": "loft",
            "preco_venda": 500000.0 + idx * 10000,
            "area": 50.0 + idx * 5,
            "bairro": "Vila Madalena",
            "tipo": "apartamento",
        }

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_three_pages_collected(self, mock_fetch_page):
        """Scraping 3 pages with 5 listings each returns 15 total."""
        mock_fetch_page.side_effect = [
            [self._make_listing(i) for i in range(5)],
            [self._make_listing(i + 5) for i in range(5)],
            [self._make_listing(i + 10) for i in range(5)],
        ]
        listings, stats = crawl_category(
            category="venda/apartamentos",
            max_pages=3,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 15)
        self.assertEqual(stats["total_listings"], 15)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["pages_fetched"], 3)

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_stops_on_empty_page(self, mock_fetch_page):
        """Crawling stops when a page returns no listings."""
        mock_fetch_page.side_effect = [
            [self._make_listing(i) for i in range(5)],
            [self._make_listing(i + 5) for i in range(3)],
            [],  # empty → stop
            [self._make_listing(i + 8) for i in range(5)],  # should not be reached
        ]
        listings, stats = crawl_category(
            category="venda/apartamentos",
            max_pages=5,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 8)
        self.assertEqual(stats["pages_fetched"], 3)
        self.assertTrue(stats["stopped_early"])
        self.assertEqual(stats["stop_reason"], "empty_page")

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_single_page(self, mock_fetch_page):
        """With max_pages=1, only the first page is fetched."""
        mock_fetch_page.return_value = [
            self._make_listing(i) for i in range(5)
        ]
        listings, stats = crawl_category(
            category="venda/apartamentos",
            max_pages=1,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 5)
        self.assertEqual(stats["pages_fetched"], 1)
        mock_fetch_page.assert_called_once()

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_no_listings_returned_empty(self, mock_fetch_page):
        """A category with no listings returns empty."""
        mock_fetch_page.return_value = []
        listings, stats = crawl_category(
            category="venda/terrenos",
            max_pages=3,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 0)
        self.assertEqual(stats["total_listings"], 0)

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_first_page_empty_stops_immediately(self, mock_fetch_page):
        """If page 1 is empty, stop immediately (no further fetches)."""
        mock_fetch_page.side_effect = [
            [],  # page 1 empty
            [self._make_listing(i) for i in range(5)],
        ]
        listings, stats = crawl_category(
            category="venda/terrenos",
            max_pages=5,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 0)
        mock_fetch_page.assert_called_once()


class TestCrawlAllCategories(unittest.TestCase):
    """Test crawling multiple categories."""

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_two_categories(self, mock_fetch_page):
        """Two categories, 1 page each, collect both."""
        # Category 1: 3 listings
        # Category 2: 2 listings
        mock_fetch_page.side_effect = [
            [{"id": "c1_l1"}, {"id": "c1_l2"}, {"id": "c1_l3"}],
            [{"id": "c2_l1"}, {"id": "c2_l2"}],
        ]
        listings, metadata = crawl_all_categories(
            categories=["venda/apartamentos", "aluguel/apartamentos"],
            max_pages=1,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 5)
        self.assertEqual(metadata["total_listings"], 5)
        self.assertEqual(metadata["categories_requested"], 2)
        self.assertEqual(metadata["categories_with_data"], 2)

    @patch("skills.loft.loft_paginate.fetch_page")
    def test_mixed_empty_categories(self, mock_fetch_page):
        """Categories with no data are tracked correctly."""
        mock_fetch_page.side_effect = [
            [{"id": "c1_l1"}],  # has data
            [],                   # no data
            [{"id": "c3_l1"}, {"id": "c3_l2"}],  # has data
        ]
        listings, metadata = crawl_all_categories(
            categories=["cat_a", "cat_b", "cat_c"],
            max_pages=1,
            rate_limit=0,
        )
        self.assertEqual(len(listings), 3)
        self.assertEqual(metadata["categories_requested"], 3)
        self.assertEqual(metadata["categories_with_data"], 2)


class TestParseCategories(unittest.TestCase):
    """Test CLI category argument parsing."""

    def test_all_keyword(self):
        """'all' returns all default categories."""
        cats = parse_categories("all")
        self.assertEqual(cats, LISTING_CATEGORIES)

    def test_single_category(self):
        """A single category string is returned as a list."""
        cats = parse_categories("venda/apartamentos")
        self.assertEqual(cats, ["venda/apartamentos"])

    def test_multiple_categories(self):
        """Comma-separated categories are split correctly."""
        cats = parse_categories("venda/apartamentos,aluguel/casas,venda/casas")
        self.assertEqual(cats, ["venda/apartamentos", "aluguel/casas", "venda/casas"])

    def test_asterisk_works(self):
        """'*' works like 'all'."""
        cats = parse_categories("*")
        self.assertEqual(cats, LISTING_CATEGORIES)

    def test_todas_works(self):
        """'todas' (Portuguese) works like 'all'."""
        cats = parse_categories("todas")
        self.assertEqual(cats, LISTING_CATEGORIES)

    def test_strips_whitespace(self):
        """Extra whitespace around categories is stripped."""
        cats = parse_categories("  venda/apartamentos , aluguel/casas  ")
        self.assertEqual(cats, ["venda/apartamentos", "aluguel/casas"])


class TestSaveResults(unittest.TestCase):
    """Test saving crawled results to JSON."""

    def setUp(self):
        self.tmp_dir = "/tmp/loft_paginate_test"
        os.makedirs(self.tmp_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_saves_to_custom_path(self):
        """Results save to the specified output path."""
        output_path = os.path.join(self.tmp_dir, "test_crawl.json")
        listings = [{"id": "test1"}, {"id": "test2"}]
        metadata = {"total_listings": 2, "crawled_at": "test"}

        saved = save_results(listings, metadata, output_path=output_path)
        self.assertEqual(saved, os.path.abspath(output_path))
        self.assertTrue(os.path.exists(output_path))

        with open(output_path) as f:
            data = json.load(f)
        self.assertEqual(data["meta"]["total_listings"], 2)
        self.assertEqual(len(data["listings"]), 2)

    def test_saves_empty_listings(self):
        """Empty listings list saves correctly."""
        output_path = os.path.join(self.tmp_dir, "empty.json")
        saved = save_results([], {"total_listings": 0}, output_path=output_path)
        self.assertTrue(os.path.exists(saved))

        with open(saved) as f:
            data = json.load(f)
        self.assertEqual(len(data["listings"]), 0)


class TestBuildPageUrlEdgeCases(unittest.TestCase):
    """Edge cases for URL construction."""

    def test_commercial_category(self):
        """Commercial category URL."""
        url = build_page_url("venda/comercial", page=1)
        self.assertIn("venda/comercial", url)

    def test_estudio_category(self):
        """Estudio category URL."""
        url = build_page_url("aluguel/estudio", page=3)
        self.assertIn("aluguel/estudio", url)
        self.assertIn("3-pagina", url)

    def test_high_page_number(self):
        """High page numbers work."""
        url = build_page_url("venda/apartamentos", page=100)
        self.assertEqual(url, "https://loft.com.br/venda/apartamentos/sp/sao-paulo/100-pagina")

    def test_trailing_slash_on_page_1(self):
        """Page 1 has a trailing slash."""
        url = build_page_url("venda/apartamentos", page=1)
        self.assertTrue(url.endswith("/"))

    def test_no_trailing_slash_on_paginated(self):
        """Paginated URLs do not end with a trailing slash."""
        url = build_page_url("venda/apartamentos", page=2)
        self.assertFalse(url.endswith("/"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
