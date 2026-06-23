"""
Tests for the rate limiter module.

Covers:
    - Basic acquire / try_acquire
    - Rate accuracy (measured vs configured rate)
    - Burst capacity
    - Timeout behaviour
    - Thread safety (concurrent access)
    - Async version (AsyncTokenBucket)
    - Edge cases (rate=0 rejected, burst<1 rejected, tokens=0 is no-op)
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from skills.rate_limiter.rate_limiter import (
    TokenBucket,
    AsyncTokenBucket,
    RateLimitedSession,
    RateLimitedAsyncClient,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _consume(bucket: TokenBucket, n: int = 1) -> float:
    """Helper that measures how long *n* acquires take."""
    t0 = time.monotonic()
    for _ in range(n):
        bucket.acquire()
    return time.monotonic() - t0


async def _aconsume(bucket: AsyncTokenBucket, n: int = 1) -> float:
    """Async helper — same as _consume but for AsyncTokenBucket."""
    t0 = time.monotonic()
    for _ in range(n):
        await bucket.acquire()
    return time.monotonic() - t0


# ── TokenBucket: basic ──────────────────────────────────────────────────────


class TestTokenBucketBasic:
    def test_instant_burst(self):
        """Acquiring within burst should be near-instant."""
        bucket = TokenBucket(rate=10, burst=10)
        elapsed = _consume(bucket, 10)
        assert elapsed < 0.1, f"burst took {elapsed:.3f}s, expected < 0.1s"

    def test_rate_limiting(self):
        """After burst is exhausted, subsequent acquires should be rate-limited."""
        bucket = TokenBucket(rate=10, burst=5)
        # drain burst
        _consume(bucket, 5)
        # next acquire should take ~0.1s
        elapsed = _consume(bucket, 1)
        assert 0.08 <= elapsed <= 0.25, f"expected ~0.1s, got {elapsed:.3f}s"

    def test_try_acquire_success(self):
        """try_acquire returns True when tokens are available."""
        bucket = TokenBucket(rate=10, burst=5)
        assert bucket.try_acquire(3) is True

    def test_try_acquire_failure(self):
        """try_acquire returns False when tokens are exhausted."""
        bucket = TokenBucket(rate=10, burst=1)
        bucket.try_acquire(1)
        assert bucket.try_acquire(1) is False

    def test_available_tokens(self):
        """available_tokens reflects consumed tokens."""
        bucket = TokenBucket(rate=100, burst=10)
        assert bucket.available_tokens == pytest.approx(10.0, abs=0.5)
        bucket.acquire(3)
        assert bucket.available_tokens == pytest.approx(7.0, abs=0.5)

    def test_reset(self):
        """reset restores full capacity."""
        bucket = TokenBucket(rate=100, burst=10)
        bucket.acquire(8)
        bucket.reset()
        assert bucket.available_tokens == pytest.approx(10.0, abs=0.5)

    def test_zero_tokens_noop(self):
        """acquire(0) and try_acquire(0) are always successful no-ops."""
        bucket = TokenBucket(rate=10, burst=1)
        assert bucket.acquire(0) is True
        assert bucket.try_acquire(0) is True

    def test_negative_rate_rejected(self):
        """rate <= 0 raises ValueError."""
        with pytest.raises(ValueError):
            TokenBucket(rate=0)
        with pytest.raises(ValueError):
            TokenBucket(rate=-1)

    def test_burst_below_one_rejected(self):
        """burst < 1 raises ValueError."""
        with pytest.raises(ValueError):
            TokenBucket(rate=10, burst=0.5)

    def test_burst_defaults_to_rate(self):
        """When burst is not given, it defaults to rate."""
        bucket = TokenBucket(rate=5)
        assert bucket.burst == 5

    def test_timeout_returns_false(self):
        """acquire with a short timeout returns False when tokens won't come."""
        bucket = TokenBucket(rate=1, burst=1)
        bucket.acquire(1)  # drain
        assert bucket.acquire(1, timeout=0.01) is False

    def test_timeout_succeeds_when_tokens_arrive(self):
        """acquire with a reasonable timeout waits for tokens to refill."""
        bucket = TokenBucket(rate=20, burst=1)
        bucket.acquire(1)  # drain
        # At 20 tokens/s, a new token arrives in 0.05s — give it 0.2s
        assert bucket.acquire(1, timeout=0.2) is True

    def test_sustained_rate_stays_within_bounds(self):
        """Over 2x burst, the average rate should be close to the configured rate."""
        bucket = TokenBucket(rate=50, burst=10)
        elapsed = _consume(bucket, 100)  # 100 acquires
        # At 50 t/s, 100 tokens should take ~2s
        rate_actual = 100 / elapsed
        assert 40 <= rate_actual <= 65, f"measured rate {rate_actual:.1f} t/s outside [40, 65]"


# ── TokenBucket: thread safety ──────────────────────────────────────────────


class TestTokenBucketThreadSafety:
    def test_concurrent_acquires_dont_exceed_rate(self):
        """Multiple threads acquiring simultaneously stay within rate."""
        bucket = TokenBucket(rate=100, burst=20)

        def worker(n: int):
            for _ in range(n):
                bucket.acquire()

        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker, 25) for _ in range(4)]
            for f in as_completed(futures):
                f.result()
        elapsed = time.monotonic() - t0

        # 100 acquires at 100 t/s → ~1s
        rate_actual = 100 / elapsed
        assert 70 <= rate_actual <= 140, f"concurrent rate {rate_actual:.1f} t/s outside [70, 140]"

    def test_try_acquire_thread_safe(self):
        """try_acquire is safe under concurrent access (no race conditions)."""
        bucket = TokenBucket(rate=1000, burst=200)
        success_count = 0

        def worker():
            nonlocal success_count
            for _ in range(50):
                if bucket.try_acquire():
                    success_count += 1

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(worker) for _ in range(4)]
            for f in as_completed(futures):
                f.result()

        # Should have consumed at most burst (200) tokens immediately
        assert success_count <= bucket.burst
        assert success_count > 0

    def test_available_tokens_does_not_drain(self):
        """available_tokens is read-only; repeated calls don't consume tokens."""
        bucket = TokenBucket(rate=100, burst=10)
        v1 = bucket.available_tokens
        v2 = bucket.available_tokens
        v3 = bucket.available_tokens
        assert v1 == v2 == v3


# ── AsyncTokenBucket ────────────────────────────────────────────────────────


class TestAsyncTokenBucket:
    @pytest.mark.asyncio
    async def test_instant_burst_async(self):
        bucket = AsyncTokenBucket(rate=10, burst=10)
        elapsed = await _aconsume(bucket, 10)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_rate_limiting_async(self):
        bucket = AsyncTokenBucket(rate=10, burst=5)
        await _aconsume(bucket, 5)
        elapsed = await _aconsume(bucket, 1)
        assert 0.08 <= elapsed <= 0.25

    @pytest.mark.asyncio
    async def test_try_acquire_async(self):
        bucket = AsyncTokenBucket(rate=10, burst=3)
        assert await bucket.try_acquire(3) is True
        assert await bucket.try_acquire(1) is False

    @pytest.mark.asyncio
    async def test_available_tokens_async(self):
        bucket = AsyncTokenBucket(rate=100, burst=10)
        assert await bucket.available_tokens() == pytest.approx(10.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_reset_async(self):
        bucket = AsyncTokenBucket(rate=100, burst=10)
        await bucket.acquire(8)
        await bucket.reset()
        assert await bucket.available_tokens() == pytest.approx(10.0, abs=0.5)

    @pytest.mark.asyncio
    async def test_timeout_false_async(self):
        bucket = AsyncTokenBucket(rate=1, burst=1)
        await bucket.acquire(1)
        assert await bucket.acquire(1, timeout=0.01) is False

    @pytest.mark.asyncio
    async def test_concurrent_async_acquires(self):
        """Multiple concurrent coroutines stay within rate."""
        bucket = AsyncTokenBucket(rate=100, burst=20)

        async def worker(n: int):
            for _ in range(n):
                await bucket.acquire()

        t0 = time.monotonic()
        await asyncio.gather(worker(25), worker(25), worker(25), worker(25))
        elapsed = time.monotonic() - t0
        rate_actual = 100 / elapsed
        assert 70 <= rate_actual <= 140, f"async rate {rate_actual:.1f} t/s outside [70, 140]"

    @pytest.mark.asyncio
    async def test_zero_tokens_noop_async(self):
        bucket = AsyncTokenBucket(rate=10, burst=1)
        assert await bucket.acquire(0) is True
        assert await bucket.try_acquire(0) is True

    @pytest.mark.asyncio
    async def test_burst_defaults_to_rate_async(self):
        bucket = AsyncTokenBucket(rate=5)
        assert bucket.burst == 5

    @pytest.mark.asyncio
    async def test_negative_rate_rejected_async(self):
        with pytest.raises(ValueError):
            AsyncTokenBucket(rate=0)
        with pytest.raises(ValueError):
            AsyncTokenBucket(rate=-1)

    @pytest.mark.asyncio
    async def test_burst_below_one_rejected_async(self):
        with pytest.raises(ValueError):
            AsyncTokenBucket(rate=10, burst=0.5)

    @pytest.mark.asyncio
    async def test_str(self):
        bucket = AsyncTokenBucket(rate=10, burst=5)
        r = repr(bucket)
        assert "AsyncTokenBucket" in r
        assert "rate=10" in r


# ── RateLimitedSession ──────────────────────────────────────────────────────


class TestRateLimitedSession:
    def test_acquire_blocks(self):
        """RateLimitedSession.acquire delegates to the bucket."""
        bucket = TokenBucket(rate=100, burst=5)
        session = RateLimitedSession(bucket=bucket)
        session.acquire(5)
        assert bucket.available_tokens == pytest.approx(0.0, abs=0.5)


# ── RateLimitedAsyncClient ──────────────────────────────────────────────────


class TestRateLimitedAsyncClient:
    @pytest.mark.asyncio
    async def test_acquire_blocks_async(self):
        bucket = AsyncTokenBucket(rate=100, burst=5)
        client = RateLimitedAsyncClient(bucket=bucket)
        await client.acquire(5)
        assert await bucket.available_tokens() == pytest.approx(0.0, abs=0.5)
