"""
LRU Cache and Response Caching for DeepanCode.
Provides in-memory caching, disk-backed cache, and TTL-based expiration.
"""

import os
import json
import time
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Optional, Dict, Tuple
from collections import OrderedDict
from functools import wraps

logger = logging.getLogger("deepans_code.cache")

CACHE_DIR = Path.home() / ".deepans-code" / "cache"
# Do not create directories at import time (test isolation). DiskCache
# creates its directory lazily in __init__.


class LRUCache:
    """Thread-safe LRU cache with TTL expiration."""

    def __init__(self, max_size: int = 256, default_ttl: int = 3600):
        self._cache: OrderedDict = OrderedDict()
        self._ttl: Dict[str, float] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                if time.time() < self._ttl.get(key, 0):
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return self._cache[key]
                else:
                    del self._cache[key]
                    del self._ttl[key]
            self._misses += 1
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        if self._max_size <= 0:
            return  # zero-capacity cache stores nothing
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= self._max_size:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
                self._ttl.pop(oldest, None)
            self._cache[key] = value
            self._ttl[key] = time.time() + (ttl if ttl is not None else self._default_ttl)

    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)
            self._ttl.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._ttl.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0
            }


class DiskCache:
    """Persistent disk-based cache with TTL (thread-safe, atomic writes)."""

    def __init__(self, cache_dir: Path = None, max_size_mb: int = 100):
        self._dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._lock = threading.Lock()

    def _key_path(self, key: str) -> Path:
        # Full 256-bit digest: no truncation, collision-resistant.
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._dir / f"{h}.cache"

    def get(self, key: str) -> Optional[Any]:
        path = self._key_path(key)
        with self._lock:
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if time.time() > data.get("expires", 0):
                    path.unlink(missing_ok=True)
                    return None
                # Verify stored key matches (defense against hash collision).
                if data.get("key") != key:
                    logger.warning("Disk cache key mismatch; ignoring entry")
                    return None
                return data.get("value")
            except (OSError, ValueError, json.JSONDecodeError) as e:
                logger.debug(f"Disk cache read error: {e}")
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                return None

    def set(self, key: str, value: Any, ttl: int = 3600):
        path = self._key_path(key)
        with self._lock:
            try:
                tmp = path.with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"value": value, "expires": time.time() + ttl, "key": key}, f)
                    f.flush()
                    try:
                        import os as _os
                        _os.fsync(f.fileno())
                    except OSError:
                        pass
                import os as _os2
                _os2.replace(tmp, path)
            except (OSError, ValueError, TypeError) as e:
                logger.error(f"Disk cache write error: {e}")
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            self._evict_if_needed()

    def _evict_if_needed(self):
        # Caller holds self._lock.
        try:
            files = [f for f in self._dir.glob("*.cache") if f.is_file()]
            total = sum(f.stat().st_size for f in files)
        except OSError:
            return
        if total > self._max_size_bytes:
            try:
                files = sorted(files, key=lambda f: f.stat().st_mtime)
            except OSError:
                return
            # Always evict at least one file (single over-budget file case).
            for f in files[: max(1, len(files) // 2)]:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self):
        with self._lock:
            for f in self._dir.glob("*.cache"):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass

    def stats(self) -> Dict[str, Any]:
        try:
            files = list(self._dir.glob("*.cache"))
            total_size = sum(f.stat().st_size for f in files)
        except OSError:
            return {"entries": 0, "size_mb": 0.0, "max_size_mb": self._max_size_bytes / (1024 * 1024)}
        return {
            "entries": len(files),
            "size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self._max_size_bytes / (1024 * 1024)
        }


class ResponseCache:
    """Combined in-memory + disk cache for API responses."""

    def __init__(self):
        self._memory = LRUCache(max_size=128, default_ttl=300)
        self._disk = DiskCache()

    def get(self, key: str) -> Optional[Any]:
        val = self._memory.get(key)
        if val is not None:
            return val
        val = self._disk.get(key)
        if val is not None:
            self._memory.set(key, val, ttl=300)
        return val

    def set(self, key: str, value: Any, ttl: int = 3600, memory_ttl: int = 300):
        self._memory.set(key, value, ttl=memory_ttl)
        self._disk.set(key, value, ttl=ttl)

    def invalidate(self, key: str):
        self._memory.invalidate(key)
        try:
            self._disk._key_path(key).unlink(missing_ok=True)
        except OSError:
            pass

    def clear(self):
        self._memory.clear()
        self._disk.clear()

    def stats(self) -> Dict[str, Any]:
        return {
            "memory": self._memory.stats(),
            "disk": self._disk.stats()
        }


def cached(ttl: int = 3600, key_prefix: str = ""):
    """Decorator for caching function results."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{hashlib.sha256(str((args, sorted(kwargs.items()))).encode()).hexdigest()}"
            result = response_cache.get(cache_key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            if result is not None:
                response_cache.set(cache_key, result, ttl=ttl)
            return result
        return wrapper
    return decorator


_response_cache_instance: Optional["ResponseCache"] = None


def get_response_cache() -> "ResponseCache":
    global _response_cache_instance
    if _response_cache_instance is None:
        _response_cache_instance = ResponseCache()
    return _response_cache_instance


class _LazyResponseCacheProxy:
    def _real(self) -> "ResponseCache":
        return get_response_cache()

    def __getattr__(self, name):
        return getattr(self._real(), name)


response_cache = _LazyResponseCacheProxy()  # type: ignore
