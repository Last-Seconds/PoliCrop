"""Small HTTP helpers with retries, shared by providers."""
from __future__ import annotations

import time
from pathlib import Path

import httpx

USER_AGENT = "FieldShift/0.0 (NASA Space Apps 2026 prototype)"


def _retry(fn, attempts: int = 3, backoff: float = 2.0):
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(backoff * (i + 1))
    raise RuntimeError(f"request failed after {attempts} attempts: {last!r}") from last


def get_json(url: str, params: dict | None = None, timeout: float = 60, attempts: int = 3):
    def go():
        r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True)
        r.raise_for_status()
        return r.json()
    return _retry(go, attempts)


def get_text(url: str, params: dict | None = None, timeout: float = 60, attempts: int = 3) -> str:
    def go():
        r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT},
                      follow_redirects=True)
        r.raise_for_status()
        return r.text
    return _retry(go, attempts)


def download(url: str, dest: Path, timeout: float = 300, attempts: int = 3) -> Path:
    tmp = dest.with_suffix(dest.suffix + ".part")

    def go():
        with httpx.stream("GET", url, timeout=timeout, headers={"User-Agent": USER_AGENT},
                          follow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    fh.write(chunk)
        tmp.replace(dest)
        return dest
    return _retry(go, attempts)
