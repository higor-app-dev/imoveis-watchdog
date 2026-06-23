"""
Tests for QuintoAndar pagination (skills/quinto-andar/pagination.py).

Tested tiers:
  Tier 1 — Unit tests for helpers: _filter_new, get_listing_count behaviour (mocked).
  Tier 2 — Mock integration: paginate_and_collect with fake Page objects.
  Tier 3 — Smoke tests (skipped by default, requires real browser + internet).

Run:
    python -m pytest tests/test_pagination.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Import setup (hyphen in dir name = no dotted package import) ──
_SKILL_DIR = str(Path(__file__).resolve().parent.parent / "skills" / "quinto-andar")
if _SKILL_DIR not in sys.path:
    sys.path.insert(0, _SKILL_DIR)

from pagination import (
    _click_load_more,
    _filter_new,
    _sleep_s,
    _wait_for_more_cards,
    get_listing_count,
    paginate_and_collect,
)


# ═══════════════════════════════════════════════════════════════════════
# Tier 1 — Helpers
# ═══════════════════════════════════════════════════════════════════════


class TestFilterNew:
    """Deduplication by 'id' field."""

    def test_all_new(self):
        listings = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]
        seen = set()
        result = _filter_new(listings, seen)
        assert len(result) == 2
        assert seen == {"1", "2"}

    def test_some_duplicates(self):
        listings = [
            {"id": "1", "name": "A"},
            {"id": "2", "name": "B"},
            {"id": "1", "name": "A dup"},
        ]
        seen = {"1"}
        result = _filter_new(listings, seen)
        assert len(result) == 1
        assert result[0]["id"] == "2"
        assert seen == {"1", "2"}

    def test_all_duplicates(self):
        listings = [{"id": "1"}, {"id": "2"}]
        seen = {"1", "2"}
        result = _filter_new(listings, seen)
        assert result == []

    def test_empty_listings(self):
        result = _filter_new([], {"1", "2"})
        assert result == []

    def test_no_id_field(self):
        """Listings without an 'id' field are excluded (would cause dupes)."""
        listings = [{"name": "A"}, {"name": "B"}]
        seen = set()
        result = _filter_new(listings, seen)
        assert len(result) == 0

    def test_empty_string_id(self):
        listings = [{"id": "", "name": "A"}]
        seen = set()
        result = _filter_new(listings, seen)
        assert len(result) == 0  # empty id excluded

    def test_numeric_id(self):
        listings = [{"id": 42, "name": "A"}]
        seen = set()
        result = _filter_new(listings, seen)
        assert len(result) == 1
        assert "42" in seen


class TestSleepS:
    """_sleep_s — trivial but good to have a boundary test."""

    def test_zero_sleep(self):
        _sleep_s(0)  # should not raise

    def test_small_sleep(self):
        _sleep_s(0.005)  # quick, should return near-instantly


# ═══════════════════════════════════════════════════════════════════════
# Tier 2 — Mock integration
# ═══════════════════════════════════════════════════════════════════════


def _make_mock_page(
    initial_count: int = 11,
    listing_counts: list[int] | None = None,
    has_loadmore: bool = True,
) -> MagicMock:
    """
    Build a fake Playwright Page that simulates QuintoAndar pagination.

    ``listing_counts``: values returned by consecutive ``get_listing_count()``
        calls (i.e. ``_count_cards``). If ``None``, defaults to
        ``[initial_count, initial_count]`` (no new cards ever appear).
    """
    page = MagicMock()
    count_idx = [0]
    loadmore_clicks = [0]

    def evaluate_side_effect(js_code, *args, **kwargs):
        js = js_code if isinstance(js_code, str) else ""

        # _count_cards calls — querySelectorAll for house-card-container
        if "house-card-container" in js:
            if listing_counts is not None:
                ci = min(count_idx[0], len(listing_counts) - 1)
                count_idx[0] += 1
                return listing_counts[ci]
            return initial_count

        # _click_load_more check: querySelector for load-more-button
        if "load-more-button" in js:
            if has_loadmore:
                return {"visible": True, "disabled": False}
            return None

        # End-of-list / no-more-content check
        return None

    page.evaluate = MagicMock(side_effect=evaluate_side_effect)
    page.locator = MagicMock(return_value=MagicMock())
    return page


class TestGetListingCount:
    """get_listing_count via mocked page.evaluate."""

    def test_returns_count(self):
        page = MagicMock()
        page.evaluate.return_value = 11
        assert get_listing_count(page) == 11

    def test_returns_zero_on_error(self):
        page = MagicMock()
        page.evaluate.side_effect = Exception("browser error")
        assert get_listing_count(page) == 0


class TestClickLoadMore:
    """_click_load_more button detection."""

    def test_button_exists_and_clicks(self):
        page = MagicMock()
        page.evaluate.return_value = {"visible": True, "disabled": False}
        page.locator.return_value = MagicMock()

        result = _click_load_more(page, scroll_fallback=False)
        assert result is True
        assert page.locator.called

    def test_button_not_found(self):
        page = MagicMock()
        page.evaluate.return_value = None

        result = _click_load_more(page, scroll_fallback=False)
        assert result is False

    def test_button_disabled(self):
        page = MagicMock()
        page.evaluate.return_value = {"visible": True, "disabled": True}

        result = _click_load_more(page, scroll_fallback=False)
        assert result is False

    def test_button_not_visible(self):
        page = MagicMock()
        page.evaluate.return_value = {"visible": False, "disabled": False}

        result = _click_load_more(page, scroll_fallback=False)
        assert result is False


class TestWaitForMoreCards:
    """_wait_for_more_cards polling behaviour."""

    def test_new_cards_appear(self):
        page = MagicMock()
        call_count = [0]

        def evaluate_side(js, *args, **kwargs):
            if "house-card-container" in js:
                call_count[0] += 1
                if call_count[0] == 1:
                    return 11  # initial check
                return 23  # after scroll, new cards appear
            return None

        page.evaluate.side_effect = evaluate_side

        result = _wait_for_more_cards(page, previous_count=11, timeout_s=5, interval_s=0.05)
        assert result >= 23

    def test_timeout_returns_current(self):
        page = MagicMock()
        page.evaluate.return_value = 11  # never changes

        result = _wait_for_more_cards(page, previous_count=11, timeout_s=1, interval_s=0.05)
        assert result == 11


class TestPaginateAndCollect:
    """Full flow with mocked page and extract_fn."""

    def test_single_page_no_scroll(self):
        """max_pages=1 means just initial extraction."""
        page = _make_mock_page(initial_count=11)
        extract_fn = MagicMock(return_value=[{"id": "1"}, {"id": "2"}])

        result = paginate_and_collect(page, extract_fn, max_pages=1)
        assert len(result) == 2
        extract_fn.assert_called_once_with(page)

    def test_two_pages_with_new_listings(self):
        """Button click triggers new cards → extract returns new data → dedup."""
        page = _make_mock_page(
            initial_count=11,
            listing_counts=[11, 11, 23, 23],
            has_loadmore=True,
        )

        call_idx = [0]

        def extract_fn(pg):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx == 0:
                return [{"id": "1"}, {"id": "2"}]
            return [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}]

        result = paginate_and_collect(
            page, extract_fn, max_pages=2,
            click_wait_s=0.05, poll_timeout_s=3, poll_interval_s=0.05,
        )
        assert len(result) == 4  # 1,2 from page 0 + 3,4 from page 1 (deduped)
        ids = {lst["id"] for lst in result}
        assert ids == {"1", "2", "3", "4"}

    def test_no_load_more_stops_early(self):
        """If button is not found, stop after initial extraction."""
        page = _make_mock_page(
            initial_count=11,
            has_loadmore=False,
        )

        def extract_fn(pg):
            return [{"id": "1"}, {"id": "2"}]

        result = paginate_and_collect(
            page, extract_fn, max_pages=5,
            click_wait_s=0.05, poll_timeout_s=1, poll_interval_s=0.05,
        )
        assert len(result) == 2  # only initial page

    def test_no_new_cards_after_click_stops(self):
        """Button clicked but card count doesn't increase."""
        page = _make_mock_page(
            initial_count=11,
            listing_counts=[11, 11, 11, 11],
            has_loadmore=True,
        )

        def extract_fn(pg):
            return [{"id": "1"}, {"id": "2"}]

        result = paginate_and_collect(
            page, extract_fn, max_pages=5,
            click_wait_s=0.05, poll_timeout_s=1, poll_interval_s=0.05,
        )
        assert len(result) == 2

    def test_no_endless_scroll_when_all_seen(self):
        """If extract returns same IDs after card increase, stop."""
        page = _make_mock_page(
            initial_count=11,
            listing_counts=[11, 11, 23, 23],
            has_loadmore=True,
        )

        def extract_fn(pg):
            return [{"id": "1"}, {"id": "2"}]  # always same

        result = paginate_and_collect(
            page, extract_fn, max_pages=10,
            click_wait_s=0.05, poll_timeout_s=3, poll_interval_s=0.05,
        )
        assert len(result) == 2

    def test_returns_empty_list_for_none_page(self):
        result = paginate_and_collect(None, lambda p: [{"id": "1"}])
        assert result == []

    def test_max_pages_respected(self):
        """Even if more cards keep appearing, stop at max_pages."""
        page = _make_mock_page(
            initial_count=11,
            listing_counts=[11, 11, 23, 23, 35, 35, 47, 47, 47, 47],
            has_loadmore=True,
        )

        call_count = [0]

        def extract_fn(pg):
            call_count[0] += 1
            return [{"id": str(call_count[0] * 10 + i)} for i in range(3)]

        result = paginate_and_collect(
            page, extract_fn, max_pages=3,
            click_wait_s=0.05, poll_timeout_s=3, poll_interval_s=0.05,
        )
        # Should have 3 extract calls (initial + 2 scrolls)
        assert call_count[0] == 3
        # 3 pages × 3 listings each (all unique because ids are distinct)
        assert len(result) == 9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
