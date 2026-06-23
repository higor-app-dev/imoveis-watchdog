"""
pagination — Paginate QuintoAndar search pages with "Ver mais" button.

QuintoAndar's search results page renders:
  - SSR: ~14 listing cards with full data (captured via data route / __NEXT_DATA__)
  - Dynamic loader: a "Ver mais" button that loads ~12 more cards per click
  - Sentinels: IntersectionObserver sentinels for scroll-triggered loading

This module handles clicking the load-more button, waiting for new cards,
re-extracting, and deduplicating by listing ID across pages.

Usage:
    from pagination import paginate_and_collect, get_listing_count
    from extraction import extract_listings

    page = navigate_to_search(browser, "sao-paulo-sp-brasil", "apartamento", "comprar")
    all_listings = paginate_and_collect(page, extract_fn=extract_listings, max_pages=5)
    # → 35+ unique listings across 3+ pages
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

# Ensure project root in path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Logging ──────────────────────────────────────────────────────────────

logger = logging.getLogger("quintoandar_pagination")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.INFO)
    _handler.setFormatter(logging.Formatter("[pagination] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ── QuintoAndar-specific selectors ──────────────────────────────────────

LOAD_MORE_SELECTOR = '[data-testid="load-more-button"]'
HOUSE_CARD_SELECTOR = '[data-testid="house-card-container"]'

# ── Public API ──────────────────────────────────────────────────────────


def paginate_and_collect(
    page: Any,
    extract_fn: Callable[[Any], list[dict[str, Any]]],
    max_pages: int = 5,
    click_wait_s: float = 4.0,
    poll_interval_s: float = 1.0,
    poll_timeout_s: float = 15.0,
    scroll_fallback: bool = True,
) -> list[dict[str, Any]]:
    """
    Paginate a QuintoAndar search page by clicking the "Ver mais" button.

    Workflow per page:
        1. Call ``extract_fn(page)`` for all currently visible listings.
        2. Track unique IDs for deduplication.
        3. Click ``[data-testid="load-more-button"]`` ("Ver mais").
        4. Poll DOM until new ``[data-testid="house-card-container"]`` cards appear.
        5. Call ``extract_fn(page)`` again.
        6. Keep only previously unseen listings (dedup by ``id`` field).
        7. Repeat up to ``max_pages``.
        8. Stop when the load-more button disappears or card count doesn't increase.

    Parameters
    ----------
    page : Page
        A Playwright Page loaded by ``navigate_to_search()``.
    extract_fn : Callable[[Page], list[dict]]
        Function that reads the current page and returns listing dicts.
        Must handle extraction from both SSR and dynamically loaded cards.
        E.g. ``extraction.extract_listings``.
    max_pages : int
        Maximum pages/clicks to attempt (default 5).
    click_wait_s : float
        Seconds to wait after clicking before polling for new cards
        (default 4.0).
    poll_interval_s : float
        Seconds between DOM card-count checks (default 1.0).
    poll_timeout_s : float
        Max seconds to poll after clicking before declaring "no more
        content" (default 15.0).
    scroll_fallback : bool
        If True and no load-more button is found, fall back to scroll-
        based loading (default True).

    Returns
    -------
    list[dict]
        Combined, deduplicated list of all unique listings across all
        pages, in first-seen order.
    """
    if page is None:
        logger.warning("paginate_and_collect: page is None")
        return []

    # ── Page 0: initial extraction ────────────────────────────────────
    logger.info(f"Starting pagination, max_pages={max_pages}")
    all_listings = extract_fn(page)
    seen_ids: set[str] = _collect_ids(all_listings)

    logger.info(
        f"Page 0: {len(all_listings)} listings extracted, "
        f"{len(seen_ids)} unique IDs"
    )

    # ── Pages 1..max_pages-1: click load-more, wait, re-extract ───────
    page_num = 0
    for page_num in range(1, max_pages):
        initial_card_count = _count_cards(page)
        logger.info(
            f"Page {page_num}: starting from {initial_card_count} cards, "
            f"{len(seen_ids)} unique IDs seen"
        )

        # Click the load-more button (or try scroll fallback)
        clicked = _click_load_more(page, scroll_fallback)
        if not clicked:
            logger.info(
                f"Page {page_num}: no load-more button found — "
                "no more listings to load"
            )
            break

        # Wait for new cards to appear in the DOM
        _sleep_s(click_wait_s)

        new_card_count = _wait_for_more_cards(
            page,
            initial_card_count,
            timeout_s=poll_timeout_s,
            interval_s=poll_interval_s,
        )

        if new_card_count <= initial_card_count:
            logger.info(
                f"Page {page_num}: card count {initial_card_count} → "
                f"{new_card_count} (no increase) — stopping"
            )
            break

        logger.info(
            f"Page {page_num}: cards increased "
            f"{initial_card_count} → {new_card_count}"
        )

        # Re-extract and filter new unique listings
        fresh_listings = extract_fn(page)
        new_unique = _filter_new(fresh_listings, seen_ids)

        if not new_unique:
            logger.info(
                f"Page {page_num}: cards increased but no new unique "
                "listings found — stopping"
            )
            break

        logger.info(
            f"Page {page_num}: +{len(new_unique)} new unique listings "
            f"(total before: {len(all_listings)})"
        )
        all_listings.extend(new_unique)

    pages_loaded = min(page_num + 1, max_pages) if page_num > 0 else 1
    logger.info(
        f"Pagination complete: {len(all_listings)} total unique listings "
        f"across {pages_loaded} pages"
    )
    return all_listings


def get_listing_count(page: Any) -> int:
    """
    Count ``[data-testid="house-card-container"]`` elements in the DOM.

    Returns 0 on error.
    """
    try:
        return page.evaluate(
            f"document.querySelectorAll('{HOUSE_CARD_SELECTOR}').length"
        )
    except Exception as exc:
        logger.warning(f"get_listing_count failed: {exc}")
        return 0


# ── Internal helpers ────────────────────────────────────────────────────


def _count_cards(page: Any) -> int:
    """
    Count house-card-container elements via evaluate (faster than
    Playwright locator.count() which does an extra round-trip).
    """
    try:
        return page.evaluate(
            f"document.querySelectorAll('{HOUSE_CARD_SELECTOR}').length"
        )
    except Exception:
        return 0


def _click_load_more(page: Any, scroll_fallback: bool) -> bool:
    """
    Click the ``[data-testid="load-more-button"]`` button.

    Returns True if the button was clicked, False if it wasn't found.
    If ``scroll_fallback`` is True and no button is found, attempts a
    scroll-to-bottom as a fallback.
    """
    try:
        has_button = page.evaluate(
            f"""() => {{
                const btn = document.querySelector('{LOAD_MORE_SELECTOR}');
                return btn ? {{
                    visible: btn.offsetParent !== null,
                    disabled: !!btn.disabled,
                }} : null;
            }}"""
        )

        if has_button and has_button.get("visible") and not has_button.get("disabled"):
            btn = page.locator(LOAD_MORE_SELECTOR)
            btn.click()
            logger.debug("Clicked load-more button")
            return True

        if has_button and has_button.get("disabled"):
            logger.info("Load-more button exists but is disabled")
            return False

    except Exception as exc:
        logger.warning(f"_click_load_more error: {exc}")

    # Fallback: scroll if configured
    if scroll_fallback:
        logger.info("No load-more button — trying scroll fallback")
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            _sleep_s(3)
            return True
        except Exception:
            pass

    return False


def _wait_for_more_cards(
    page: Any,
    previous_count: int,
    timeout_s: float,
    interval_s: float,
) -> int:
    """
    Poll the DOM until the house-card count exceeds ``previous_count``.

    Returns the new count (same as ``previous_count`` if timeout).
    """
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        _sleep_s(interval_s)
        current_count = _count_cards(page)
        if current_count > previous_count:
            # Extra settle time for React rendering
            _sleep_s(0.5)
            return _count_cards(page)

    return _count_cards(page)


def _collect_ids(listings: list[dict[str, Any]]) -> set[str]:
    """Collect all non-empty ``id`` values from listing dicts."""
    return {str(lst.get("id") or "") for lst in listings if lst.get("id")}


def _filter_new(
    listings: list[dict[str, Any]],
    seen_ids: set[str],
) -> list[dict[str, Any]]:
    """Return entries whose ``id`` is not in ``seen_ids``.

    Entries without a truthy ``id`` value are excluded from the result
    (they would create duplicates on every page).
    """
    result: list[dict[str, Any]] = []
    for lst in listings:
        lid = str(lst.get("id") or "")
        if lid and lid not in seen_ids:
            seen_ids.add(lid)
            result.append(lst)
    return result


def _sleep_s(seconds: float) -> None:
    """Blocking sleep, capped at 30s to prevent hangs."""
    time.sleep(max(0.0, min(seconds, 30.0)))


# ── CLI — quick test / demo ─────────────────────────────────────────────


def _demo() -> None:
    """Print example usage and expected behaviour."""
    print("paginate_and_collect — Demo / Reference")
    print("=" * 60)
    print()
    print("This module is designed for QuintoAndar's 'Ver mais' pagination.")
    print()
    print("Example usage from another script or Hermes skill:")
    print()
    print("  from playwright.sync_api import sync_playwright")
    print("  from navigation import navigate_to_search")
    print("  from extraction import extract_listings")
    print("  from pagination import paginate_and_collect")
    print()
    print("  with sync_playwright() as pw:")
    print("      browser = pw.chromium.launch(headless=True)")
    print("      try:")
    print("          page = navigate_to_search(")
    print('              browser, "sao-paulo-sp-brasil", "apartamento", "comprar"')
    print("          )")
    print("          all_listings = paginate_and_collect(")
    print("              page, extract_fn=extract_listings, max_pages=5")
    print("          )")
    print(f"          print(f'{{len(all_listings)}} total listings')")
    print("      finally:")
    print("          browser.close()")
    print()
    print("DOM selectors:")
    print(f"  - {LOAD_MORE_SELECTOR} (load-more button)")
    print(f"  - {HOUSE_CARD_SELECTOR} (listing cards)")
    print()
    print("Acceptance:", 14 * 3, "listings across 3 pages")


if __name__ == "__main__":
    _demo()
