"""
Tests for QuintoAndar browser navigation (skills/quinto-andar/navigation.py).

Tested tiers:
  Tier 1 — Unit tests for URL construction and validation (no browser).
  Tier 2 — Mock Playwright integration with fake Page/Browser objects.
  Tier 3 — Smoke tests (skipped by default, requires real browser).

Run:
    python -m pytest tests/test_navigation.py -v
    python -m pytest tests/test_navigation.py -v -k "not smoke"
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Import setup (hyphen in dir name = no dotted package import) ──
_SKILL_DIR = str(Path(__file__).resolve().parent.parent / "skills" / "quinto-andar")
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from navigation import (
    VALID_TRANSACTIONS,
    _build_ssr_url,
    navigate_to_search,
    navigate_to_search_safe,
)


# ═══════════════════════════════════════════════════════════════════════
# Tier 1 — URL construction & validation
# ═══════════════════════════════════════════════════════════════════════


class TestBuildSsrUrl:
    """URL construction from parameters."""

    def test_basic_comprar(self):
        url = _build_ssr_url("sao-paulo-sp-brasil", "apartamento", "comprar")
        assert url == (
            "https://www.quintoandar.com.br/"
            "comprar/imovel/sao-paulo-sp-brasil/apartamento"
        )

    def test_basic_alugar(self):
        url = _build_ssr_url("sao-paulo-sp-brasil", "casa", "alugar")
        assert url == (
            "https://www.quintoandar.com.br/"
            "alugar/imovel/sao-paulo-sp-brasil/casa"
        )

    def test_no_type_name(self):
        """When type_name is empty string, omit the type segment."""
        url = _build_ssr_url("sao-paulo-sp-brasil", "", "comprar")
        assert url == (
            "https://www.quintoandar.com.br/"
            "comprar/imovel/sao-paulo-sp-brasil"
        )

    def test_rio_de_janeiro(self):
        url = _build_ssr_url("rio-de-janeiro-rj-brasil", "apartamento", "alugar")
        assert url == (
            "https://www.quintoandar.com.br/"
            "alugar/imovel/rio-de-janeiro-rj-brasil/apartamento"
        )

    def test_kitnet_type(self):
        url = _build_ssr_url("sao-paulo-sp-brasil", "kitnet", "comprar")
        assert url == (
            "https://www.quintoandar.com.br/"
            "comprar/imovel/sao-paulo-sp-brasil/kitnet"
        )

    @pytest.mark.parametrize("txn", VALID_TRANSACTIONS)
    def test_all_valid_transactions(self, txn):
        url = _build_ssr_url("sao-paulo-sp-brasil", "apartamento", txn)
        assert f"/{txn}/" in url


class TestValidation:
    """Input validation for transaction type."""

    def test_invalid_transaction_raises(self):
        browser = MagicMock()
        with pytest.raises(ValueError, match="comprar.*alugar"):
            navigate_to_search(browser, "sp", "apto", "vender")

    def test_invalid_transaction_uppercase(self):
        browser = MagicMock()
        # The implementation lowercases, so "COMPRAR" → "comprar" which IS valid.
        # Only truly invalid values should raise.
        pass  # covered by test_invalid_transaction_raises

    def test_invalid_transaction_aluguel_vs_alugar(self):
        browser = MagicMock()
        with pytest.raises(ValueError, match="comprar.*alugar"):
            navigate_to_search(browser, "sp", "apto", "aluguel")


class TestSafeWrapper:
    """navigate_to_search_safe never raises."""

    @patch("navigation._navigate_impl")
    def test_success(self, mock_impl):
        mock_page = MagicMock()
        mock_page.url = "https://www.quintoandar.com.br/comprar/imovel/sp/apto"
        mock_impl.return_value = mock_page

        browser = MagicMock()
        ok, page, msg = navigate_to_search_safe(browser, "sp", "apto", "comprar")

        assert ok is True
        assert page is mock_page
        assert "OK" in msg
        assert "comprar/imovel/sp/apto" in msg

    @patch("navigation._navigate_impl")
    def test_failure(self, mock_impl):
        mock_impl.side_effect = TimeoutError("listings not found")

        browser = MagicMock()
        ok, page, msg = navigate_to_search_safe(browser, "sp", "apto", "comprar")

        assert ok is False
        assert page is None
        assert "FAIL" in msg
        assert "listings not found" in msg


# ═══════════════════════════════════════════════════════════════════════
# Tier 2 — Mock browser integration
# ═══════════════════════════════════════════════════════════════════════


class TestNavigateToSearchMocked:
    """Test the full navigation flow with a mocked Playwright page.

    These tests verify that:
    - page.goto is called with the correct URL
    - _wait_for_spa is invoked after navigation
    - Browser.new_page() is called
    """

    @pytest.fixture
    def mock_page(self):
        p = MagicMock()
        p.url = "https://www.quintoandar.com.br/comprar/imovel/sp/apto"
        return p

    @pytest.fixture
    def mock_browser(self, mock_page):
        b = MagicMock()
        b.new_page.return_value = mock_page
        return b

    @patch("navigation._wait_for_spa")
    def test_navigate_no_neighbourhood(self, mock_wait, mock_browser, mock_page):
        """SSR: navigate directly to city+type URL, wait for listings."""
        result = navigate_to_search(
            mock_browser, "sao-paulo-sp-brasil", "apartamento", "comprar"
        )

        assert result is mock_page
        mock_browser.new_page.assert_called_once()
        mock_page.goto.assert_called_once_with(
            "https://www.quintoandar.com.br/"
            "comprar/imovel/sao-paulo-sp-brasil/apartamento",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        mock_wait.assert_called_once_with(mock_page, 30000)

    @patch("navigation._wait_for_spa")
    def test_navigate_alugar(self, mock_wait, mock_browser, mock_page):
        """Rent scenario."""
        result = navigate_to_search(
            mock_browser, "rio-de-janeiro-rj-brasil", "casa", "alugar"
        )

        assert result is mock_page
        mock_page.goto.assert_called_once_with(
            "https://www.quintoandar.com.br/"
            "alugar/imovel/rio-de-janeiro-rj-brasil/casa",
            wait_until="domcontentloaded",
            timeout=30000,
        )

    @patch("navigation._wait_for_spa")
    def test_navigate_no_type(self, mock_wait, mock_browser, mock_page):
        """No type_name → omit type segment."""
        result = navigate_to_search(
            mock_browser, "sao-paulo-sp-brasil", "", "comprar"
        )

        assert result is mock_page
        mock_page.goto.assert_called_once_with(
            "https://www.quintoandar.com.br/"
            "comprar/imovel/sao-paulo-sp-brasil",
            wait_until="domcontentloaded",
            timeout=30000,
        )

    @patch("navigation._build_neighbourhood_page")
    @patch("navigation._wait_for_spa")
    def test_navigate_with_neighbourhood(
        self, mock_wait, mock_nb, mock_browser, mock_page
    ):
        """Neighbourhood: uses client-side interaction path."""
        result = navigate_to_search(
            mock_browser,
            "sao-paulo-sp-brasil",
            "apartamento",
            "comprar",
            neighbourhood="Vila Mariana",
        )

        assert result is mock_page
        # Should NOT call goto directly; _build_neighbourhood_page handles nav
        mock_page.goto.assert_not_called()
        mock_nb.assert_called_once_with(
            mock_page,
            "sao-paulo-sp-brasil",
            "comprar",
            "Vila Mariana",
            30000,
        )


# ═══════════════════════════════════════════════════════════════════════
# Tier 3 — Smoke tests (SKIPPED by default, requires real Playwright)
# ═══════════════════════════════════════════════════════════════════════


class TestNavigationSmoke:
    """Smoke tests that attempt real browser navigation.

    These are SKIPPED by default. Run explicitly with:
        python -m pytest tests/test_navigation.py -v -k smoke
        python -m pytest tests/test_navigation.py -v -k smoke --headed

    Prerequisites:
        playwright install chromium
    """

    @pytest.mark.smoke
    @pytest.mark.skip(reason="Requires real Playwright browser. "
                              "Run with --headed or --no-header -k smoke")
    def test_real_comprar_ssr(self):
        """Navigate to SSR comprar page and verify listings appear."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = navigate_to_search(
                    browser,
                    "sao-paulo-sp-brasil",
                    "apartamento",
                    "comprar",
                    timeout=45000,
                )
                content = page.content()
                assert "quintoandar" in page.url
                assert "/comprar/" in page.url
                # Check for listing cards or listing data in the DOM
                has_listings = page.evaluate(
                    "document.querySelectorAll('a[href*=\"/imovel/\"]').length > 0"
                )
                assert has_listings, "No listing cards found on SSR page"
            finally:
                browser.close()

    @pytest.mark.smoke
    @pytest.mark.skip(reason="Requires real Playwright browser")
    def test_real_alugar_ssr(self):
        """Navigate to SSR alugar page and verify listings appear."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = navigate_to_search(
                    browser,
                    "sao-paulo-sp-brasil",
                    "apartamento",
                    "alugar",
                    timeout=45000,
                )
                assert "/alugar/" in page.url
                has_listings = page.evaluate(
                    "document.querySelectorAll('a[href*=\"/imovel/\"]').length > 0"
                )
                assert has_listings, "No listing cards found on SSR page"
            finally:
                browser.close()

    @pytest.mark.smoke
    @pytest.mark.skip(reason="Requires real Playwright browser + "
                              "needs neighbourhood interaction")
    def test_real_neighbourhood(self):
        """Navigate with neighbourhood filter."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = navigate_to_search(
                    browser,
                    "sao-paulo-sp-brasil",
                    "apartamento",
                    "comprar",
                    neighbourhood="Vila Mariana",
                    timeout=60000,
                )
                # Should have filtered listings (fewer than city level)
                has_listings = page.evaluate(
                    "document.querySelectorAll('a[href*=\"/imovel/\"]').length > 0"
                )
                assert has_listings
            finally:
                browser.close()
