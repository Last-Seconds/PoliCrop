"""Cache layer between providers and the core.

Every external call goes through here, so the app works both live and from
precomputed data (pre-warmed with `python -m fieldshift.prewarm`). Results are
JSON files on disk keyed by provider, method and arguments. If a refresh fails
and an older entry exists, the stale entry is served (a slow or down service
must not break a demo).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

TtlFn = Callable[[str, tuple, Any], "float | None"]


class FileCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / namespace / key[:2] / f"{key}.json"

    def get(self, namespace: str, key: str) -> dict | None:
        p = self._path(namespace, key)
        try:
            return json.loads(p.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable cache entry %s: %s", p, exc)
            return None

    def put(self, namespace: str, key: str, value: Any, ttl: float | None, meta: dict | None = None) -> None:
        p = self._path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {"stored_at": time.time(), "ttl": ttl, "meta": meta or {}, "value": value}
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w") as fh:
            json.dump(entry, fh)
        os.replace(tmp, p)  # atomic: readers never see a half-written file

    def file_path(self, namespace: str, name: str) -> Path:
        """Location for a binary artefact (e.g. a downloaded raster)."""
        p = self.root / namespace / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def make_key(*parts: Any) -> str:
        blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:32]


def is_fresh(entry: dict, now: float | None = None) -> bool:
    ttl = entry.get("ttl")
    return ttl is None or (now or time.time()) - entry.get("stored_at", 0) < ttl


class CachedProvider:
    """Wraps a provider; methods listed in `methods` are cached transparently.

    ttl_fn(method, args, result) returns seconds to keep a result, or None for
    "forever". Attributes that are not cached methods pass through.
    """

    def __init__(self, inner: Any, cache: FileCache, namespace: str, methods: list[str],
                 ttl_fn: TtlFn | None = None):
        self._inner = inner
        self._cache = cache
        self._ns = namespace
        self._methods = set(methods)
        self._ttl_fn = ttl_fn or (lambda m, a, r: None)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in self._methods or not callable(attr):
            return attr

        def wrapper(*args):
            key = FileCache.make_key(self._ns, name, args)
            entry = self._cache.get(self._ns, key)
            if entry and is_fresh(entry):
                return entry["value"]
            with self._cache.lock(key):
                entry = self._cache.get(self._ns, key)  # another thread may have filled it
                if entry and is_fresh(entry):
                    return entry["value"]
                try:
                    value = attr(*args)
                except Exception:
                    if entry is not None:
                        log.warning("%s.%s failed; serving stale cache entry", self._ns, name)
                        return entry["value"]
                    raise
                self._cache.put(self._ns, key, value, self._ttl_fn(name, args, value),
                                {"method": name, "args": _short(args)})
                return value

        return wrapper


def _short(args: tuple) -> str:
    s = json.dumps(args, default=str)
    return s if len(s) < 300 else s[:300] + "…"
