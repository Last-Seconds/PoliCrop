"""Composition root: load content, pick the provider set for the region, build the service."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .cache import FileCache
from .core.content import load_content
from .core.service import FieldService

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("FIELDSHIFT_DATA", ROOT / "data"))
CACHE_DIR = Path(os.environ.get("FIELDSHIFT_CACHE", ROOT / "cache"))
FRONTEND_DIR = ROOT / "frontend"

PROVIDER_SETS = {}


def _register_us():
    from .providers.us import build_us_providers
    PROVIDER_SETS["us"] = build_us_providers


@lru_cache(maxsize=1)
def get_cache() -> FileCache:
    return FileCache(CACHE_DIR)


@lru_cache(maxsize=1)
def get_service() -> FieldService:
    _register_us()
    content = load_content(DATA_DIR)
    provider_set = content.region.get("provider_set", "us")
    if provider_set not in PROVIDER_SETS:
        raise RuntimeError(f"unknown provider set {provider_set!r} in region.yaml")
    providers = PROVIDER_SETS[provider_set](content, get_cache())
    return FieldService(content, providers)
