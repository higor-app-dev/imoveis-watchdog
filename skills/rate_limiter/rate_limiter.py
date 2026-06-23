"""
rate_limiter.py — Rate limiting utilities for API clients.

Provides a Token Bucket algorithm with both synchronous (threading) and
asynchronous (asyncio) implementations.  Designed to be reused across
different data sources (EmCasa / CDN / Algolia / any HTTP API).

Usage (sync):
    bucket = TokenBucket(rate=10, burst=20)  # 10 req/s, burst up to 20
    bucket.acquire()                          # blocks until a token is available
    resp = requests.get("https://api.example.com")

Usage (async):
    bucket = AsyncTokenBucket(rate=10, burst=20)
    await bucket.acquire()
    resp = await httpx.AsyncClient().get("https://api.example.com")

Usage (wrapped session — sync):
    session = RateLimitedSession(rate=10, burst=20)
    session.get("https://api.example.com")   # auto-rate-limited

Usage (wrapped client — async):
    client = RateLimitedAsyncClient(rate=10, burst=20)
    await client.get("https://api.example.com")
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional


# ── Token Bucket (threading) ────────────────────────────────────────────────


class TokenBucket:
    """Token bucket rate limiter — thread-safe.

    The bucket fills at *rate* tokens per second, up to *burst* tokens max.
    Each call to ``acquire`` consumes one token (or *n* tokens) and blocks
    the calling thread until enough tokens have accumulated.

    Thread safety is provided by a ``threading.Lock``, so this is safe to
    share across threads in a concurrent scraper (e.g. ``concurrent.futures``).

    Attributes:
        rate:       Tokens added per second.
        burst:      Maximum token capacity (burst size).
        tokens:     Current token count (float, may be fractional).
        last_refill: Monotonic timestamp of last refill.
    """

    def __init__(self, rate: float = 10.0, burst: Optional[float] = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.burst = burst if burst is not None else rate
        if self.burst < 1:
            raise ValueError("burst must be >= 1")
        self.tokens: float = float(self.burst)
        self.last_refill: float = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Add tokens proportional to elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """Block until *tokens* are available, up to *timeout* seconds.

        Args:
            tokens:  Number of tokens to consume (default 1).
            timeout: Max seconds to wait. ``None`` means wait forever.

        Returns:
            ``True`` if tokens were acquired, ``False`` if the timeout
            elapsed before enough tokens were available.
        """
        if tokens <= 0:
            return True
        remaining = timeout
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            acquired = self._try_acquire(tokens)
            if acquired:
                return True

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False

            # Sleep for a short interval so we don't busy-loop
            sleep_for = min(
                0.05,  # max resolution
                remaining if remaining is not None else 0.05,
            )
            time.sleep(max(sleep_for, 0.001))

    def try_acquire(self, tokens: int = 1) -> bool:
        """Non-blocking attempt to consume *tokens*.

        Returns:
            ``True`` if tokens were available and consumed immediately,
            ``False`` otherwise (caller should wait or retry later).
        """
        if tokens <= 0:
            return True
        return self._try_acquire(tokens)

    def _try_acquire(self, tokens: int) -> bool:
        """Internal: attempt to consume *tokens* under lock."""
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """Return estimated available tokens (read-only snapshot)."""
        with self._lock:
            self._refill()
            return self.tokens

    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        with self._lock:
            self.tokens = float(self.burst)
            self.last_refill = time.monotonic()

    def __repr__(self) -> str:
        return (
            f"TokenBucket(rate={self.rate}, burst={self.burst}, "
            f"tokens={self.tokens:.2f})"
        )


# ── Token Bucket (asyncio) ──────────────────────────────────────────────────


class AsyncTokenBucket:
    """Token bucket rate limiter — async/await safe.

    Identical semantics to ``TokenBucket`` but uses ``asyncio.Lock`` and
    ``asyncio.sleep`` so it doesn't block the event loop.

    Usage:
        bucket = AsyncTokenBucket(rate=10, burst=20)
        async def fetch():
            await bucket.acquire()
            ...  # make HTTP request
    """

    def __init__(self, rate: float = 10.0, burst: Optional[float] = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.burst = burst if burst is not None else rate
        if self.burst < 1:
            raise ValueError("burst must be >= 1")
        self.tokens: float = float(self.burst)
        self.last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill_sync(self) -> None:
        """Synchronous refill — used only under lock."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

    async def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """Await until *tokens* are available, up to *timeout* seconds.

        Args:
            tokens:  Number of tokens to consume (default 1).
            timeout: Max seconds to wait. ``None`` means wait forever.

        Returns:
            ``True`` if tokens were acquired, ``False`` on timeout.
        """
        if tokens <= 0:
            return True
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            acquired = await self._try_acquire(tokens)
            if acquired:
                return True

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                sleep_for = min(0.05, remaining)
            else:
                sleep_for = 0.05

            await asyncio.sleep(max(sleep_for, 0.001))

    async def try_acquire(self, tokens: int = 1) -> bool:
        """Non-blocking acquire — returns immediately.

        Returns:
            ``True`` if tokens were available immediately.
        """
        if tokens <= 0:
            return True
        return await self._try_acquire(tokens)

    async def _try_acquire(self, tokens: int) -> bool:
        """Internal: attempt to consume *tokens* under lock."""
        async with self._lock:
            self._refill_sync()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    async def available_tokens(self) -> float:
        """Return estimated available tokens (read-only snapshot)."""
        async with self._lock:
            self._refill_sync()
            return self.tokens

    async def reset(self) -> None:
        """Reset the bucket to full capacity."""
        async with self._lock:
            self.tokens = float(self.burst)
            self.last_refill = time.monotonic()

    def __repr__(self) -> str:
        return (
            f"AsyncTokenBucket(rate={self.rate}, burst={self.burst}, "
            f"tokens={self.tokens:.2f})"
        )


# ── Wrapped HTTP session (sync — requests) ──────────────────────────────────


class RateLimitedSession:
    """Drop-in replacement for ``requests.Session`` with integrated rate limiting.

    All HTTP methods (``get``, ``post``, ``put``, ``delete``, ``patch``,
    ``head``, ``options``) are rate-limited through the shared token bucket.

    Usage:
        session = RateLimitedSession(rate=5, burst=10)
        resp = session.get("https://api.example.com/properties")
        resp = session.post("https://api.example.com/search", json={...})

    Any extra kwargs (headers, timeout, etc.) are forwarded to the underlying
    ``requests.Session`` method.
    """

    def __init__(
        self,
        rate: float = 10.0,
        burst: Optional[float] = None,
        bucket: Optional[TokenBucket] = None,
    ) -> None:
        import requests

        self._session = requests.Session()
        self._bucket = bucket or TokenBucket(rate=rate, burst=burst)

    def acquire(self, tokens: int = 1) -> None:
        """Block until *tokens* are available. Same as ``TokenBucket.acquire``."""
        self._bucket.acquire(tokens=tokens)

    def get(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.get(url, **kwargs)

    def post(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.post(url, **kwargs)

    def put(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.put(url, **kwargs)

    def delete(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.delete(url, **kwargs)

    def patch(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.patch(url, **kwargs)

    def head(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.head(url, **kwargs)

    def options(self, url: str, **kwargs):
        self._bucket.acquire()
        return self._session.options(url, **kwargs)

    @property
    def headers(self):
        return self._session.headers

    @headers.setter
    def headers(self, value):
        self._session.headers = value

    def close(self) -> None:
        self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Wrapped HTTP client (async — httpx) ─────────────────────────────────────


class RateLimitedAsyncClient:
    """Drop-in wrapper around ``httpx.AsyncClient`` with integrated rate limiting.

    All HTTP methods are rate-limited through the shared async token bucket.

    Usage:
        async with RateLimitedAsyncClient(rate=5, burst=10) as client:
            resp = await client.get("https://api.example.com/properties")

    Any extra kwargs (headers, timeout, params, etc.) are forwarded to the
    underlying ``httpx.AsyncClient`` method.
    """

    def __init__(
        self,
        rate: float = 10.0,
        burst: Optional[float] = None,
        bucket: Optional[AsyncTokenBucket] = None,
        **client_kwargs,
    ) -> None:
        import httpx

        self._client = httpx.AsyncClient(**client_kwargs)
        self._bucket = bucket or AsyncTokenBucket(rate=rate, burst=burst)

    async def acquire(self, tokens: int = 1) -> None:
        """Await until *tokens* are available."""
        await self._bucket.acquire(tokens=tokens)

    async def get(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.get(url, **kwargs)

    async def post(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.post(url, **kwargs)

    async def put(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.put(url, **kwargs)

    async def delete(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.delete(url, **kwargs)

    async def patch(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.patch(url, **kwargs)

    async def head(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.head(url, **kwargs)

    async def options(self, url: str, **kwargs):
        await self._bucket.acquire()
        return await self._client.options(url, **kwargs)

    @property
    def headers(self):
        return self._client.headers

    @headers.setter
    def headers(self, value):
        self._client.headers = value

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
