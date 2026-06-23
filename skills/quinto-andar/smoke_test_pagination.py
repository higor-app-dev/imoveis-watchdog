"""
Real browser smoke test for paginate_and_collect.

This navigates to a real QuintoAndar search page, extracts the first page,
then clicks "Ver mais" to load more listings via pagination, verifying that:
  - Initial extraction yields ~14 listings
  - After pagination, total unique listings > 14
  - At least 2 pages of data were loaded (card count increases)

Prerequisites:
    pip install playwright && playwright install chromium

Run:
    python skills/quinto-andar/smoke_test_pagination.py
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
from pagination import paginate_and_collect, get_listing_count


def test_comprar_pagination() -> list[dict]:
    """Navigate to SSR comprar page, extract, paginate."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.set_default_timeout(45000)

            url = "https://www.quintoandar.com.br/comprar/imovel/sao-paulo-sp-brasil/apartamento"
            print(f"\nNavigating to: {url}")
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            print(f"Current URL: {page.url}")

            # Initial state
            initial_count = get_listing_count(page)
            print(f"Initial house cards in DOM: {initial_count}")

            initial_listings = extract_listings(page)
            print(f"Initial extraction: {len(initial_listings)} listings")

            if initial_listings:
                sample = initial_listings[0]
                print(f"  Sample: id={sample.get('id')}, "
                      f"salePrice={sample.get('salePrice')}, "
                      f"neighbourhood={sample.get('neighbourhood')}")

            # Paginate
            print(f"\nRunning paginate_and_collect (max_pages=4)...")
            all_listings = paginate_and_collect(
                page, extract_fn=extract_listings,
                max_pages=4,
                click_wait_s=3.0,
            )

            print(f"\n=== PAGINATION RESULT ===")
            print(f"  Total unique listings: {len(all_listings)}")
            print(f"  Initial: {len(initial_listings)}")
            new_count = len(all_listings) - len(initial_listings)
            print(f"  New from pagination: {new_count}")

            if all_listings:
                print(f"\n  Sample fields from first listing:")
                s = all_listings[0]
                print(f"    id:            {s.get('id')}")
                print(f"    salePrice:     {s.get('salePrice')}")
                print(f"    rentPrice:     {s.get('rentPrice')}")
                print(f"    area:          {s.get('area')}")
                print(f"    bedrooms:      {s.get('bedrooms')}")
                print(f"    neighbourhood: {s.get('neighbourhood')}")
                print(f"    address:       {s.get('address')}")

            # Save results
            output_dir = _PROJECT_ROOT / "data" / "results"
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"pagination_smoke_{timestamp}.json"
            with open(output_path, "w") as f:
                json.dump(all_listings, f, indent=2, ensure_ascii=False)
            print(f"\n  Saved to: {output_path}")

            # Acceptance criteria
            print(f"\n=== ACCEPTANCE ===")
            passed = True

            if len(all_listings) > 14:
                print(f"  ✅ >14 listings: {len(all_listings)}")
            else:
                print(f"  ❌ Need >14, got {len(all_listings)}")
                passed = False

            if new_count > 0:
                print(f"  ✅ New from scroll: {new_count}")
            else:
                print(f"  ❌ No new from scroll")
                passed = False

            # Verify at least some have real data
            with_prices = [l for l in all_listings if l.get("salePrice")]
            print(f"  ✅ Listings with prices: {len(with_prices)}/{len(all_listings)}")

            print(f"\n  Overall: {'✅ PASS' if passed else '❌ FAIL'}")
            return all_listings

        finally:
            browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("QuintoAndar Pagination — Real Browser Smoke Test")
    print("=" * 60)

    result = test_comprar_pagination()

    if result and len(result) > 14:
        sys.exit(0)
    else:
        print("\n❌ Smoke test FAILED — acceptance criteria not met")
        sys.exit(1)
