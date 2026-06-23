"""
PaginatedCache — Caching engine for paginated API queries.

Design:
  - Cache key = ``namespace:page`` where namespace includes city/neighborhood.
  - Storage: file-based (JSON) by default; can be subclassed for other backends.
  - TTL per entry; expired entries are skipped on read and pruned on write.
  - Invalidation by namespace prefix or global flush.

Usage:
    from skills.cache.cache_engine import PaginatedCache

    cache = PaginatedCache(cache_dir="data/cache", default_ttl_seconds=1800)

    def fetch_page(namespace: str, page: int) -> dict:
        return cache.get_or_fetch(namespace, page, lambda: do_request(namespace, page))

    # Force invalidate a namespace
    cache.invalidate("sao-paulo-bela-vista")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Optional

logger = logging.getLogger("cache")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_path(part: str) -> str:
    """Sanitize a string so it can safely be used as a file-system path segment.

    Replaces anything that isn't ASCII-alphanumeric, ``-``, ``_``, ``.`` with
    an underscore and truncates to 128 characters to avoid FS limits.
    """
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in part)
    return safe[:128]


def _cache_key(namespace: str, page: int) -> str:
    """Return a deterministic, filesystem-safe cache key.

    A human-readable prefix (sanitized namespace + page) is kept for easy
    debugging; a full SHA-256 hash of the raw namespace avoids collisions.
    """
    prefix = _safe_path(namespace)
    raw = f"{namespace}:{page}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"{prefix}_p{page:04d}_{h}"


# ── Cache entry shape ────────────────────────────────────────────────────────

CACHE_ENTRY_VERSION = 1

# ── PaginatedCache ──────────────────────────────────────────────────────────


class PaginatedCache:
    """File-based, TTL-aware cache for paginated API responses.

    Each page of results is stored as an individual JSON file under
    *cache_dir*.  Files are self-describing (they carry metadata such as
    creation time, expiry, and version), so the cache can be inspected or
    purged with standard file-system tools.

    Thread-safe for concurrent reads and writes via a per-instance lock.

    Parameters
    ----------
    cache_dir:
        Directory where cache files are stored. Created automatically.
    default_ttl_seconds:
        Time-to-live for new entries, in seconds.  Defaults to 1 hour.
    """

    def __init__(
        self,
        cache_dir: str | Path = "data/cache",
        default_ttl_seconds: int = 3600,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._default_ttl = default_ttl_seconds
        self._lock = Lock()

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, namespace: str, page: int) -> dict | None:
        """Return cached data for *namespace:page*, or ``None`` on miss/expiry.

        Expired entries are silently removed from disk before returning
        ``None``.
        """
        path = self._resolve_path(namespace, page)
        if not path.exists():
            return None

        try:
            entry = self._read(path)
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Cache read error for %s:%d — %s", namespace, page, exc)
            path.unlink(missing_ok=True)
            return None

        if self._is_expired(entry):
            path.unlink(missing_ok=True)
            logger.debug("Cache expired for %s:%d", namespace, page)
            return None

        return entry.get("data")

    def set(self, namespace: str, page: int, data: dict) -> None:
        """Store *data* in the cache under *namespace:page*."""
        entry = self._build_entry(data)
        path = self._resolve_path(namespace, page)
        self._write(entry, path)

    def get_or_fetch(
        self,
        namespace: str,
        page: int,
        fetch_fn: Callable[[], dict],
    ) -> dict:
        """Return cached data or call *fetch_fn*, cache the result, and return it.

        This is the primary API for callers::

            result = cache.get_or_fetch("sao-paulo", 3, lambda: api.fetch(page=3))
        """
        cached = self.get(namespace, page)
        if cached is not None:
            logger.info("Cache HIT  %s  page=%d", namespace, page)
            return cached

        logger.info("Cache MISS %s  page=%d — fetching...", namespace, page)
        data = fetch_fn()
        self.set(namespace, page, data)
        return data

    def invalidate(self, namespace: str | None = None) -> int:
        """Remove cached entries.

        Parameters
        ----------
        namespace:
            If given, only entries whose namespace *starts with* this string
            are removed.  If ``None``, the **entire cache directory** is wiped.

        Returns
        -------
        Number of files removed.
        """
        removed = 0
        if namespace is None:
            # Flush everything
            with self._lock:
                for p in self._cache_dir.iterdir():
                    if p.is_file() and p.suffix == ".json":
                        p.unlink()
                        removed += 1
            logger.info("Cache flushed completely — %d files removed", removed)
            return removed

        prefix = _safe_path(namespace)
        with self._lock:
            for p in self._cache_dir.iterdir():
                if p.is_file() and p.suffix == ".json" and p.name.startswith(prefix):
                    p.unlink()
                    removed += 1
        logger.info(
            "Cache invalidated for namespace '%s' — %d files removed",
            namespace,
            removed,
        )
        return removed

    def clear_expired(self) -> int:
        """Scan all cache files and remove those that are expired.

        Returns the number of files removed.  Safe to call periodically
        (e.g. in a cron job or before a large run).
        """
        removed = 0
        with self._lock:
            for p in self._cache_dir.glob("*.json"):
                try:
                    entry = self._read(p)
                    if self._is_expired(entry):
                        p.unlink()
                        removed += 1
                except (json.JSONDecodeError, OSError, KeyError):
                    # Corrupt files get cleaned up too
                    p.unlink(missing_ok=True)
                    removed += 1
        if removed:
            logger.info("Cleared %d expired cache entries", removed)
        return removed

    def stats(self) -> dict:
        """Return summary statistics about the cache."""
        total = 0
        expired = 0
        now = time.time()
        with self._lock:
            for p in self._cache_dir.glob("*.json"):
                total += 1
                try:
                    entry = self._read(p)
                    if self._is_expired(entry, now=now):
                        expired += 1
                except Exception:
                    expired += 1
        return {
            "cache_dir": str(self._cache_dir),
            "total_files": total,
            "expired": expired,
            "default_ttl_seconds": self._default_ttl,
        }

    # ── Internal helpers ────────────────────────────────────────────────────

    def _resolve_path(self, namespace: str, page: int) -> Path:
        """Return the filesystem path for a given namespace + page."""
        key = _cache_key(namespace, page)
        return self._cache_dir / f"{key}.json"

    def _build_entry(self, data: dict) -> dict:
        """Build a self-describing cache entry envelope."""
        now = time.time()
        return {
            "_version": CACHE_ENTRY_VERSION,
            "_created_at": now,
            "_expires_at": now + self._default_ttl,
            "_ttl": self._default_ttl,
            "data": data,
        }

    @staticmethod
    def _read(path: Path) -> dict:
        """Read and return a cache entry from disk."""
        with open(path, "r") as f:
            return json.load(f)

    def _write(self, entry: dict, path: Path) -> None:
        """Atomically write a cache entry to disk."""
        tmp = path.with_suffix(".tmp")
        with self._lock:
            with open(tmp, "w") as f:
                json.dump(entry, f, ensure_ascii=False, default=str)
            tmp.rename(path)

    @staticmethod
    def _is_expired(entry: dict, now: float | None = None) -> bool:
        """Check whether a cache entry is past its expiry."""
        expires = entry.get("_expires_at", 0)
        return (now if now is not None else time.time()) >= expires


# ── NullCache (no-op for testing / disabling) ────────────────────────────────


class NullCache:
    """A no-op cache that always misses and never stores.

    Drop-in replacement for ``PaginatedCache`` — useful for testing or
    temporarily disabling caching without changing caller code.
    """

    def get(self, namespace: str, page: int) -> None:
        return None

    def set(self, namespace: str, page: int, data: dict) -> None:
        pass

    def get_or_fetch(
        self,
        namespace: str,
        page: int,
        fetch_fn: Callable[[], dict],
    ) -> dict:
        return fetch_fn()

    def invalidate(self, namespace: str | None = None) -> int:
        return 0

    def clear_expired(self) -> int:
        return 0

    def stats(self) -> dict:
        return {"backend": "null", "total_files": 0, "expired": 0}


# ── Factory ──────────────────────────────────────────────────────────────────


def create_cache(config: dict | None = None) -> PaginatedCache | NullCache:
    """Create a cache instance from a config dictionary.

    Config schema (all keys optional)::

        {
            "enabled": true,                 # false → NullCache
            "dir": "data/cache",             # cache directory
            "ttl_seconds": 3600,             # default TTL per entry
        }

    Parameters
    ----------
    config:
        Dictionary with cache configuration.  If ``None`` or empty, returns
        a ``PaginatedCache`` with default settings.

    Returns
    -------
    PaginatedCache or NullCache.
    """
    if config is None:
        return PaginatedCache()
    if not config.get("enabled", True):
        return NullCache()

    return PaginatedCache(
        cache_dir=config.get("dir", "data/cache"),
        default_ttl_seconds=config.get("ttl_seconds", 3600),
    )
