"""
config.py — единая конфигурация trader-analyzer.

Прокси и пороги читаются из окружения / .env рядом с этим файлом.
Живой weather-бот (`strategies/weather/`) не трогаем.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "profiles.db"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip("'").strip('"')
        os.environ[key] = value


_load_dotenv(ROOT / ".env")


def http_proxy() -> str | None:
    """HTTP(S) proxy for Polymarket Data API. Empty = direct (set POLYMARKET_HTTP_PROXY)."""
    for key in ("POLYMARKET_HTTP_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


WEATHER_MIN_RATIO = float(os.getenv("WEATHER_MIN_RATIO", "0.30"))
SIGNAL_RECENCY_HOURS = int(os.getenv("SIGNAL_RECENCY_HOURS", "48"))
REFRESH_STALE_HOURS = float(os.getenv("REFRESH_STALE_HOURS", "24"))


def make_http_client(timeout: float = 30, **kwargs):
    import httpx

    proxy = http_proxy()
    mounts = {"all://": httpx.HTTPTransport(proxy=proxy)} if proxy else None
    return httpx.Client(
        mounts=mounts,
        timeout=timeout,
        follow_redirects=True,
        **kwargs,
    )
