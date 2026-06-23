"""Smoke test: QuintoAndar SSR navigation (comprar + alugar)."""
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REPO_ROOT = TEST_DIR.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "quinto-andar"))
from navigation import navigate_to_search

from playwright.sync_api import sync_playwright


def count_listing_links(page) -> int:
    """Count listing card anchor tags in the DOM."""
    return page.eval_on_selector_all(
        "a[href*='/imovel/']",
        "els => els.length",
    )


def test_comprar():
    print("--- Test 1: /comprar/imovel/sao-paulo-sp-brasil/apartamento ---")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = navigate_to_search(
                browser, "sao-paulo-sp-brasil", "apartamento", "comprar",
                timeout=45000,
            )
            print(f"  URL: {page.url}")
            count = count_listing_links(page)
            print(f"  Listing card links in DOM: {count}")
            build_id = page.evaluate("window.__NEXT_DATA__?.buildId")
            print(f"  Build ID: {build_id or 'N/A'}")
            assert count > 0, "No listings found on comprar page!"
            print("  ✅ PASS")
        finally:
            browser.close()


def test_alugar():
    print("--- Test 2: /alugar/imovel/sao-paulo-sp-brasil/apartamento ---")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            page = navigate_to_search(
                browser, "sao-paulo-sp-brasil", "apartamento", "alugar",
                timeout=45000,
            )
            print(f"  URL: {page.url}")
            count = count_listing_links(page)
            print(f"  Listing card links in DOM: {count}")
            assert count > 0, "No listings found on alugar page!"
            print("  ✅ PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("  Smoke Test: QuintoAndar SSR Navigation")
    print("=" * 60)
    test_comprar()
    test_alugar()
    print("=" * 60)
    print("  Both scenarios PASSED")
    print("=" * 60)
