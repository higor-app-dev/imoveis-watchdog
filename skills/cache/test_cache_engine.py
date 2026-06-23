"""
Testes para o módulo skills/cache/cache_engine.py.

Cobre:
  - Cache hit / miss / set / get
  - Expiração (TTL)
  - Invalidação por namespace e global
  - get_or_fetch (fetch chamado apenas em miss)
  - Limpeza de entradas expiradas
  - Thread safety (concorrência básica)
  - NullCache (no-op)
  - Factory create_cache
  - Key sanitization
  - Corrupção de arquivo
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cache.cache_engine import (
    PaginatedCache,
    NullCache,
    create_cache,
    _cache_key,
    _safe_path,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_cache(**kwargs) -> PaginatedCache:
    """Create a PaginatedCache in a temp directory."""
    tmp = tempfile.mkdtemp(prefix="cache_test_")
    return PaginatedCache(cache_dir=tmp, **kwargs)


# ── Tests: _safe_path / _cache_key ─────────────────────────────────────────


def test_safe_path_ascii():
    """Caracteres ASCII seguros são preservados."""
    assert _safe_path("sao-paulo") == "sao-paulo"
    assert _safe_path("bela_vista_123") == "bela_vista_123"


def test_safe_path_sanitize():
    """Caracteres não-ASCII/perigosos são substituídos."""
    safe = _safe_path("São Paulo!@#$%")
    assert "_" in safe
    assert all(c.isalnum() or c in "-_." for c in safe)


def test_safe_path_truncate():
    """Strings muito longas são truncadas."""
    long_str = "a" * 500
    safe = _safe_path(long_str)
    assert len(safe) <= 128


def test_cache_key_format():
    """Cache key tem prefixo legível + hash."""
    key = _cache_key("sao-paulo-consolacao", 3)
    assert key.startswith("sao-paulo-consolacao_p0003_")
    assert len(key) > 20


# ── Tests: PaginatedCache ───────────────────────────────────────────────────


def test_miss_on_empty():
    """Cache vazio → get retorna None."""
    cache = _make_cache()
    assert cache.get("sao-paulo", 1) is None
    assert cache.get("qualquer", 99) is None


def test_set_and_get():
    """set + get retorna os mesmos dados."""
    cache = _make_cache()
    data = {"listings": [{"id": 1}], "total": 1}
    cache.set("sao-paulo", 1, data)
    result = cache.get("sao-paulo", 1)
    assert result == data


def test_get_different_page():
    """Páginas diferentes são isoladas."""
    cache = _make_cache()
    cache.set("sp", 1, {"page": 1})
    cache.set("sp", 2, {"page": 2})
    assert cache.get("sp", 1) == {"page": 1}
    assert cache.get("sp", 2) == {"page": 2}


def test_get_different_namespace():
    """Namespaces diferentes são isolados."""
    cache = _make_cache()
    cache.set("sao-paulo", 1, {"city": "sp"})
    cache.set("rio", 1, {"city": "rj"})
    assert cache.get("sao-paulo", 1) == {"city": "sp"}
    assert cache.get("rio", 1) == {"city": "rj"}


def test_get_or_fetch_hit():
    """get_or_fetch com cache quente → fetch não é chamado."""
    cache = _make_cache()
    cache.set("sp", 1, {"cached": True})

    call_count = 0

    def fetch():
        nonlocal call_count
        call_count += 1
        return {"fetched": True}

    result = cache.get_or_fetch("sp", 1, fetch)
    assert result == {"cached": True}
    assert call_count == 0  # fetch não foi chamado


def test_get_or_fetch_miss():
    """get_or_fetch com cache frio → fetch é chamado."""
    cache = _make_cache()
    call_count = 0

    def fetch():
        nonlocal call_count
        call_count += 1
        return {"fetched": True}

    result = cache.get_or_fetch("sp", 1, fetch)
    assert result == {"fetched": True}
    assert call_count == 1

    # Segunda chamada → hit, não chama fetch
    result2 = cache.get_or_fetch("sp", 1, fetch)
    assert result2 == {"fetched": True}
    assert call_count == 1


def test_expiry():
    """Entradas expiradas não são retornadas."""
    cache = _make_cache(default_ttl_seconds=1)
    cache.set("sp", 1, {"data": "fresh"})
    assert cache.get("sp", 1) is not None
    time.sleep(1.1)
    assert cache.get("sp", 1) is None


def test_expiry_after_ttl_update():
    """TTL é medido a partir do set, não muda retroativamente."""
    cache = _make_cache(default_ttl_seconds=5)
    cache.set("sp", 1, {"data": "a"})
    # Altera o TTL padrão — entradas existentes não são afetadas
    cache._default_ttl = 0
    # A entrada antiga ainda vale (foi criada com TTL=5)
    assert cache.get("sp", 1) is not None


def test_invalidate_namespace():
    """invalidate(namespace) remove apenas entradas daquele namespace."""
    cache = _make_cache()
    cache.set("sao-paulo", 1, {"x": 1})
    cache.set("sao-paulo", 2, {"x": 2})
    cache.set("rio", 1, {"y": 1})

    removed = cache.invalidate("sao-paulo")
    assert removed == 2
    assert cache.get("sao-paulo", 1) is None
    assert cache.get("sao-paulo", 2) is None
    assert cache.get("rio", 1) == {"y": 1}  # intacto


def test_invalidate_all():
    """invalidate(None) limpa tudo."""
    cache = _make_cache()
    cache.set("a", 1, {"x": 1})
    cache.set("b", 1, {"y": 1})

    removed = cache.invalidate()
    assert removed == 2
    assert cache.stats()["total_files"] == 0


def test_clear_expired():
    """clear_expired remove apenas entradas vencidas."""
    cache = _make_cache(default_ttl_seconds=3600)
    cache.set("permanente", 1, {"keep": True})

    # Cria entrada manualmente com TTL expirado
    expired_entry = {
        "_version": 1,
        "_created_at": 0,
        "_expires_at": 0,
        "_ttl": 1,
        "data": {"expired": True},
    }
    path = cache._resolve_path("temporario", 1)
    with open(path, "w") as f:
        json.dump(expired_entry, f)

    # clear_expired( ) encontra e remove a entrada vencida
    removed = cache.clear_expired()
    assert removed >= 1, f"Esperava remover >=1, removeu {removed}"
    # A entrada permanente (não expirada) continua intacta
    assert cache.get("permanente", 1) == {"keep": True}
    # Temporário foi removido
    assert cache.get("temporario", 1) is None


def test_stats():
    """stats() retorna metadados coerentes."""
    cache = _make_cache()
    cache.set("sp", 1, {"a": 1})
    cache.set("rj", 1, {"b": 2})
    s = cache.stats()
    assert s["total_files"] == 2
    assert s["expired"] == 0
    assert s["default_ttl_seconds"] == 3600


def test_concurrent_access():
    """Múltiplas threads podem ler/escrever sem corrupção."""
    cache = _make_cache()

    def worker(ns: str, page: int):
        for _ in range(20):
            cache.get_or_fetch(ns, page, lambda: {"data": ns})
            cache.set(f"{ns}_other", page, {"ts": time.time()})

    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(f"ns_{i}", i))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    s = cache.stats()
    assert s["total_files"] > 0
    # Verifica que todos os dados são legíveis
    for i in range(10):
        result = cache.get(f"ns_{i}", i)
        assert result is not None


def test_corrupted_file():
    """Arquivo corrompido → tratado como miss (removido silenciosamente)."""
    cache = _make_cache()
    path = cache._resolve_path("corrupt", 1)
    with open(path, "w") as f:
        f.write("not-json-at-all")

    assert cache.get("corrupt", 1) is None
    # Arquivo corrompido foi removido
    assert not path.exists()


# ── Tests: NullCache ────────────────────────────────────────────────────────


def test_null_cache_always_miss():
    """NullCache sempre retorna None e chama fetch."""
    nc = NullCache()
    assert nc.get("sp", 1) is None
    assert nc.get("qualquer", 99) is None

    calls = []
    result = nc.get_or_fetch("sp", 1, lambda: calls.append(1) or {"ok": True})
    assert result == {"ok": True}
    assert len(calls) == 1  # fetch sempre chamado

    result2 = nc.get_or_fetch("sp", 1, lambda: calls.append(1) or {"ok": True})
    assert len(calls) == 2  # fetch chamado de novo (nunca cacheia)


def test_null_cache_set_noop():
    """NullCache.set não faz nada e não crasha."""
    nc = NullCache()
    nc.set("sp", 1, {"data": True})
    assert nc.get("sp", 1) is None


def test_null_cache_invalidate_noop():
    nc = NullCache()
    assert nc.invalidate() == 0
    assert nc.invalidate("sp") == 0


def test_null_cache_stats():
    nc = NullCache()
    s = nc.stats()
    assert s["backend"] == "null"


# ── Tests: create_cache factory ─────────────────────────────────────────────


def test_create_cache_default():
    """Sem config → PaginatedCache com defaults."""
    cache = create_cache()
    assert isinstance(cache, PaginatedCache)


def test_create_cache_empty_config():
    """Config vazio → PaginatedCache."""
    cache = create_cache({})
    assert isinstance(cache, PaginatedCache)


def test_create_cache_disabled():
    """enabled=false → NullCache."""
    cache = create_cache({"enabled": False})
    assert isinstance(cache, NullCache)


def test_create_cache_custom_dir():
    """dir configurado → PaginatedCache no diretório correto."""
    tmp = tempfile.mkdtemp()
    cache = create_cache({"dir": tmp, "ttl_seconds": 600})
    assert isinstance(cache, PaginatedCache)
    assert str(cache._cache_dir) == tmp
    assert cache._default_ttl == 600


# ── Entry point ─────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main(["-v", __file__]))
