# GrassCRM — app/cache.py v8.0.1

import threading
import time as _time

from app.config import CACHE_TTL


class _Cache:
    def __init__(self, ttl: int):
        self._ttl  = ttl
        self._data = {}
        self._ts   = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        if key not in self._data or _time.monotonic() - self._ts[key] > self._ttl:
            return None
        return self._data[key]

    def set(self, key: str, value):
        with self._lock:
            self._data[key] = value
            self._ts[key]   = _time.monotonic()

    def invalidate(self, *keys):
        with self._lock:
            if not keys or "all" in keys:
                self._data.clear()
                self._ts.clear()
                return
            for k in keys:
                to_remove = [ek for ek in self._data if ek == k or ek.startswith(f"{k}:")]
                for ek in to_remove:
                    self._data.pop(ek, None)
                    self._ts.pop(ek, None)


# Единственный экземпляр — импортировать отовсюду
_cache = _Cache(ttl=CACHE_TTL)
