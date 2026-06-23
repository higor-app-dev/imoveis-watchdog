"""
QuintoAndar — Browser Navigation

Provides async functions to navigate QuintoAndar's SPA search pages
using Playwright (sync/async), returning pages ready for data extraction.

SSR URLs work directly for city + type_name:
  - /comprar/imovel/sao-paulo-sp-brasil/apartamento  ✅
  - /alugar/imovel/sao-paulo-sp-brasil                ✅

Neighbourhood filters require client-side interaction (SPA ignores URL params):
  - /sp-sao-paulo/<bairro>  ❌ ignored
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Ensure project root in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from playwright.sync_api import Browser, Page, TimeoutError as PwTimeout
except ImportError:
    Browser = None  # type: ignore
    Page = None  # type: ignore
    PwTimeout = Exception

BASE_URL = "https://www.quintoandar.com.br"
VALID_TRANSACTIONS = {"comprar", "alugar"}

# Default selectors for QuintoAndar SPA (browser-interaction mode)
# These may need updating if QuintoAndar changes their UI.
_SELECTORS = {
    "search_tab": 'button[role="tab"]:has-text("{transaction}")',
    "city_combobox": 'button[aria-label*="Cidade"]',
    "city_option": 'li[role="option"]:has-text("{city}")',
    "neighbourhood_combobox": 'button[aria-label*="Bairro"]',
    "neighbourhood_option": 'li[role="option"]:has-text("{neighbourhood}")',
    "search_button": 'button:has-text("Buscar imóveis")',
    "listing_card": 'a[data-testid="listing-card"], a[href*="/imovel/"]',
    "listing_grid": '[data-testid="listing-grid"], [class*="listing"]',
}

# ── Sync API ──────────────────────────────────────────────────────────────


def navigate_to_search(
    browser: Browser,
    city: str,
    type_name: str,
    transaction_type: str,
    neighbourhood: Optional[str] = None,
    timeout: int = 30000,
) -> Page:
    """
    Navigate to a QuintoAndar search page and wait for listings to render.

    Parameters
    ----------
    browser : Browser
        A Playwright ``Browser`` instance (headless or headed).
    city : str
        City slug, e.g. ``"sao-paulo-sp-brasil"``.
    type_name : str
        Property type slug, e.g. ``"apartamento"``, ``"casa"``, ``"kitnet"``.
        Pass ``""`` or ``None`` to omit the type filter.
    transaction_type : str
        ``"comprar"`` for buy, ``"alugar"`` for rent.
    neighbourhood : str | None, optional
        Brazilian neighbourhood name, e.g. ``"Vila Mariana"``.
        If provided, client-side filter interaction is performed
        (SSR ignores neighbourhood URL params).
    timeout : int
        Maximum milliseconds to wait for listings to appear (default 30s).

    Returns
    -------
    Page
        The Playwright ``Page`` object, already navigated and with listings
        visible in the DOM.  The caller may read ``page.content()``, extract
        the Next.js data route, or continue interacting.

    Raises
    ------
    ValueError
        If ``transaction_type`` is not ``"comprar"`` or ``"alugar"``.
    TimeoutError
        If listings do not render within ``timeout`` ms.
    """
    return _navigate_impl(browser, city, type_name, transaction_type,
                          neighbourhood, timeout)


def navigate_to_search_safe(
    browser: Browser,
    city: str,
    type_name: str,
    transaction_type: str,
    neighbourhood: Optional[str] = None,
    timeout: int = 30000,
) -> tuple[bool, Optional[Page], str]:
    """
    Wrapper around ``navigate_to_search`` that never raises.

    Returns
    -------
    tuple[bool, Page | None, str]
        ``(ok, page_or_None, message)``
    """
    try:
        page = _navigate_impl(browser, city, type_name, transaction_type,
                              neighbourhood, timeout)
        return (True, page, f"OK — navigated to {page.url}")
    except Exception as exc:
        return (False, None, f"FAIL — {exc}")


# ── ── Helpers ── ──


def _build_ssr_url(city: str, type_name: str,
                   transaction_type: str) -> str:
    """Build the SSR URL for direct navigation."""
    txn = transaction_type
    path = f"/{txn}/imovel/{city}"
    if type_name:
        path += f"/{type_name}"
    return f"{BASE_URL}{path}"


def _build_neighbourhood_page(
    page: Page,
    city: str,
    transaction_type: str,
    neighbourhood: str,
    timeout: int,
) -> None:
    """
    Perform client-side interaction to select a neighbourhood.

    Strategy:
      1. Navigate to base city page (SSR loads city).
      2. Click the neighbourhood combobox.
      3. Select the desired neighbourhood from the dropdown.
      4. Apply / wait for SPA to re-render with filtered results.
    """
    # Start from the city-level SSR page
    base_url = _build_ssr_url(city, "", transaction_type)
    page.goto(base_url, wait_until="domcontentloaded", timeout=timeout)
    _wait_for_spa(page, timeout)

    # The SPA search bar should be visible — click the bairro filter
    _click_filter_combobox(page, "Bairro", neighbourhood, timeout)

    # Now find and click the apply / search button
    try:
        btn = page.locator("button:has-text('Buscar imóveis')")
        btn.wait_for(state="visible", timeout=5000)
        btn.click()
    except Exception:
        # Some QuintoAndar layouts auto-apply when selecting neighbourhood
        pass

    _wait_for_spa(page, timeout)


def _click_filter_combobox(
    page: Page,
    filter_label: str,
    option_text: str,
    timeout: int,
) -> None:
    """
    Click a filter combobox by label and select an option.

    Uses multiple selectors for robustness across QuintoAndar's UI changes.
    """
    import time as _time

    # Try locating the combobox by aria-label first, then by visible text
    selectors = [
        f'button[aria-label*="{filter_label}" i]',
        f'button:has-text("{filter_label}")',
        f'div[class*="filter"] button:has-text("{filter_label}")',
    ]
    combo = None
    for sel in selectors:
        locator = page.locator(sel).first
        if locator.is_visible(timeout=3000):
            combo = locator
            break
    if combo is None:
        # Fallback: try any visible filter button
        combo = page.locator("button[role='combobox'], button[aria-haspopup='listbox']").first

    combo.click()
    _time.sleep(1)  # allow dropdown animation

    # Find and click the option
    option_selectors = [
        f'li[role="option"]:has-text("{option_text}")',
        f'li:has-text("{option_text}")',
        f'div[role="option"]:has-text("{option_text}")',
        f'label:has-text("{option_text}")',
        f'span:has-text("{option_text}")',
    ]
    for sel in option_selectors:
        option = page.locator(sel).first
        if option.is_visible(timeout=2000):
            option.click()
            _time.sleep(0.5)
            return

    # Last-resort: click any visible list item containing the text
    page.locator(f':visible:has-text("{option_text}")').first.click()


def _wait_for_spa(page: Page, timeout: int) -> None:
    """
    Wait for the QuintoAndar SPA to finish rendering listings.

    This waits for listing cards to appear in the DOM or for
    the loading indicator to disappear.
    """
    # Wait for network to settle then check DOM
    page.wait_for_load_state("domcontentloaded", timeout=timeout)

    # Try to wait for listing cards
    try:
        page.wait_for_selector(
            'a[data-testid="listing-card"], '
            'a[href*="/imovel/"], '
            '[data-testid="listing-grid"]',
            state="visible",
            timeout=timeout,
        )
    except Exception:
        # Fall back to a structural wait if selectors don't match
        # (QuintoAndar may update their data-testid attributes)
        page.wait_for_timeout(3000)
        # Check if the page loaded a "no results" state
        has_listings = page.evaluate(
            "document.querySelectorAll('a[href*=\"/imovel/\"]').length > 0"
        )
        if not has_listings:
            raise TimeoutError(
                "No listing cards found in DOM after navigation"
            )


def _navigate_impl(
    browser: Browser,
    city: str,
    type_name: str,
    transaction_type: str,
    neighbourhood: Optional[str],
    timeout: int,
) -> Page:
    """Internal implementation shared by sync wrappers."""
    txn = transaction_type.lower()
    if txn not in VALID_TRANSACTIONS:
        raise ValueError(
            f"Invalid transaction_type '{transaction_type}'. "
            f"Must be one of {VALID_TRANSACTIONS}"
        )

    page = browser.new_page()
    page.set_default_timeout(timeout)

    if neighbourhood:
        _build_neighbourhood_page(page, city, txn, neighbourhood, timeout)
    else:
        url = _build_ssr_url(city, type_name, txn)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        _wait_for_spa(page, timeout)

    return page


# ── Async API ─────────────────────────────────────────────────────────────


async def navigate_to_search_async(
    browser: "Browser",  # keep as forward-ref for lazy importers
    city: str,
    type_name: str,
    transaction_type: str,
    neighbourhood: Optional[str] = None,
    timeout: int = 30000,
) -> "Page":
    """
    Async variant of ``navigate_to_search``.

    Uses the same logic internally but accepts an async Playwright
    ``Browser`` and returns an async ``Page``.

    Usage::

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await navigate_to_search_async(
                browser, "sao-paulo-sp-brasil", "apartamento", "comprar"
            )
            # ... extract data ...
            await browser.close()
    """
    from playwright.async_api import TimeoutError as AsyncPwTimeout

    txn = transaction_type.lower()
    if txn not in VALID_TRANSACTIONS:
        raise ValueError(
            f"Invalid transaction_type '{transaction_type}'. "
            f"Must be one of {VALID_TRANSACTIONS}"
        )

    page = await browser.new_page()
    page.set_default_timeout(timeout)

    if neighbourhood:
        await _async_build_neighbourhood_page(
            page, city, txn, neighbourhood, timeout
        )
    else:
        url = _build_ssr_url(city, type_name, txn)
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        await _async_wait_for_spa(page, timeout)

    return page


async def _async_build_neighbourhood_page(
    page: "Page",
    city: str,
    transaction_type: str,
    neighbourhood: str,
    timeout: int,
) -> None:
    """Async version of _build_neighbourhood_page."""
    import time as _time

    base_url = _build_ssr_url(city, "", transaction_type)
    await page.goto(base_url, wait_until="domcontentloaded", timeout=timeout)
    await _async_wait_for_spa(page, timeout)

    await _async_click_filter_combobox(page, "Bairro", neighbourhood, timeout)

    try:
        btn = page.locator("button:has-text('Buscar imóveis')")
        await btn.wait_for(state="visible", timeout=5000)
        await btn.click()
    except Exception:
        pass

    await _async_wait_for_spa(page, timeout)


async def _async_click_filter_combobox(
    page: "Page",
    filter_label: str,
    option_text: str,
    timeout: int,
) -> None:
    """Async version of _click_filter_combobox."""
    import time as _time

    selectors = [
        f'button[aria-label*="{filter_label}" i]',
        f'button:has-text("{filter_label}")',
        f'div[class*="filter"] button:has-text("{filter_label}")',
    ]
    combo = None
    for sel in selectors:
        locator = page.locator(sel).first
        try:
            if await locator.is_visible(timeout=3000):
                combo = locator
                break
        except Exception:
            continue
    if combo is None:
        combo = page.locator(
            "button[role='combobox'], button[aria-haspopup='listbox']"
        ).first

    await combo.click()
    await page.wait_for_timeout(1000)

    option_selectors = [
        f'li[role="option"]:has-text("{option_text}")',
        f'li:has-text("{option_text}")',
        f'div[role="option"]:has-text("{option_text}")',
        f'label:has-text("{option_text}")',
        f'span:has-text("{option_text}")',
    ]
    for sel in option_selectors:
        option = page.locator(sel).first
        try:
            if await option.is_visible(timeout=2000):
                await option.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue

    await page.locator(f':visible:has-text("{option_text}")').first.click()


async def _async_wait_for_spa(page: "Page", timeout: int) -> None:
    """Async version of _wait_for_spa."""
    await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    try:
        await page.wait_for_selector(
            'a[data-testid="listing-card"], '
            'a[href*="/imovel/"], '
            '[data-testid="listing-grid"]',
            state="visible",
            timeout=timeout,
        )
    except Exception:
        await page.wait_for_timeout(3000)
        has_listings = await page.evaluate(
            "document.querySelectorAll('a[href*=\"/imovel/\"]').length > 0"
        )
        if not has_listings:
            raise TimeoutError(
                "No listing cards found in DOM after navigation"
            )


# ── CLI — quick test / smoke check ────────────────────────────────────────


def _demo() -> None:
    """Quick demo: print SSR URLs for common configurations."""
    examples = [
        ("sao-paulo-sp-brasil", "apartamento", "comprar"),
        ("sao-paulo-sp-brasil", "casa", "comprar"),
        ("sao-paulo-sp-brasil", "apartamento", "alugar"),
        ("sao-paulo-sp-brasil", "", "comprar"),
        ("rio-de-janeiro-rj-brasil", "apartamento", "comprar"),
    ]
    print("QuintoAndar Navigation — Example SSR URLs")
    print("=" * 60)
    for city, tp, txn in examples:
        url = _build_ssr_url(city, tp, txn)
        label = f"  {txn:8s} {city:30s} {tp or '(all)':15s} →"
        print(f"{label} {url}")
    print()
    print("Neighbourhood filtering requires browser interaction (SPA).")
    print("  navigate_to_search(browser, city, type, transaction, neighbourhood)")


if __name__ == "__main__":
    _demo()
