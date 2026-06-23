"""
Real browser smoke test for extract_listings.

This navigates to a real QuintoAndar search page and attempts
to extract listing data using all three strategies.

Prerequisites:
    pip install playwright && playwright install chromium

Run:
    python skills/quinto-andar/smoke_test_extraction.py
"""

import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
_SKILL_DIR = str(_PROJECT_ROOT / "skills" / "quinto-andar")
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from extraction import extract_listings


def test_comprar_ssr():
    """Navigate to SSR comprar page and extract listings."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(45000)

            # Navigate to QuintoAndar buy search
            url = "https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/apartamento"
            print(f"\nNavigating to: {url}")
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(3)  # let SPA settle

            print(f"Current URL: {page.url}")

            # Check for listing cards in DOM
            card_count = page.evaluate(
                "document.querySelectorAll('a[href*=\"/imovel/\"]').length"
            )
            print(f"Listing card links in DOM: {card_count}")

            # Extract listings
            listings = extract_listings(page)
            print(f"\nExtract result: {len(listings)} listings")

            if listings:
                # Print first listing as sample
                print(f"\nSample listing (1/{len(listings)}):")
                sample = listings[0]
                print(json.dumps(sample, ensure_ascii=False, indent=2))
                print(f"\n✅ Success: {len(listings)} listings extracted")
            else:
                print("❌ No listings extracted")

            return listings

        finally:
            browser.close()


def test_alugar_ssr():
    """Navigate to SSR alugar page and extract listings."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(45000)

            # Navigate to QuintoAndar rent search
            url = "https://www.quintoandar.com.br/alugar/imovel/sao-paulo-sp-brasil/apartamento"
            print(f"\nNavigating to: {url}")
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(3)

            # Extract listings
            listings = extract_listings(page)
            print(f"\n[RENT] Extract result: {len(listings)} listings")

            if listings:
                sample = listings[0]
                print(
                    f"  Sample: id={sample.get('id')}, "
                    f"rentPrice={sample.get('rentPrice')}, "
                    f"neighbourhood={sample.get('neighbourhood')}"
                )
                print(f"✅ Rent success: {len(listings)} listings")
            else:
                print("❌ No rent listings extracted")

            return listings

        finally:
            browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("QuintoAndar Extraction — Real Browser Smoke Test")
    print("=" * 60)

    # Test 1: Buy (comprar)
    print("\n>>> TEST 1: COMPRAR (Buy)")
    comprar_results = test_comprar_ssr()

    # Test 2: Rent (alugar)
    print("\n>>> TEST 2: ALUGAR (Rent)")
    alugar_results = test_alugar_ssr()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  COMPRAR (Buy):  {len(comprar_results) if comprar_results else 0} listings")
    print(f"  ALUGAR (Rent):  {len(alugar_results) if alugar_results else 0} listings")

    all_ok = (comprar_results and len(comprar_results) > 0) and \
             (alugar_results and len(alugar_results) > 0)
    print(f"\n{'✅ PASS' if all_ok else '❌ FAIL'}")
    sys.exit(0 if all_ok else 1)
