"""
discover.py — живые источники weather-кошельков.

Лидерборды (не Polynyx/Predicts.guru — там общий PnL, не ниша):
  Polycopy / weatherbot.bot / polysmartwallet
Плюс трейдеры сегодняшних Gamma-событий highest-temperature.

НЕ трогает strategies/weather/.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from config import make_http_client

_client = None

CITY_SLUGS = [
    "london", "nyc", "paris", "madrid", "rome", "amsterdam", "munich",
    "seoul", "tokyo", "shanghai", "singapore", "hong-kong", "taipei",
    "shenzhen", "guangzhou", "beijing", "los-angeles", "chicago", "miami",
    "dallas", "houston", "atlanta", "denver", "toronto", "buenos-aires",
    "sao-paulo", "lucknow", "tel-aviv", "dubai", "bangkok", "jakarta",
    "wellington", "sydney", "johannesburg", "boston", "seattle", "phoenix",
    "kuala-lumpur", "cape-town", "busan",
]


def _c():
    global _client
    if _client is None:
        _client = make_http_client(
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"},
        )
    return _client


def _norm_addr(addr: str | None) -> str | None:
    if not addr or not isinstance(addr, str):
        return None
    a = addr.strip().lower()
    if re.fullmatch(r"0x[a-f0-9]{40}", a):
        return a
    return None


def fetch_weatherbot() -> list[dict]:
    r = _c().get("https://weatherbot.bot/api/leaderboard")
    r.raise_for_status()
    traders = r.json().get("traders") or []
    out = []
    for t in traders:
        addr = _norm_addr(t.get("address"))
        if not addr:
            continue
        out.append({"address": addr, "name": t.get("name") or None, "source": "weatherbot"})
    return out


def fetch_polysmartwallet(max_pages: int = 8) -> list[dict]:
    out = []
    for page in range(1, max_pages + 1):
        r = _c().get(
            "https://polysmartwallet.com/api/leaderboard.php",
            params={"category": "weather", "page": page},
        )
        r.raise_for_status()
        data = r.json().get("data") or {}
        rows = data.get("portfolio") or []
        if not rows:
            break
        for t in rows:
            addr = _norm_addr(t.get("address"))
            if not addr:
                continue
            out.append({
                "address": addr,
                "name": t.get("userName") or t.get("xName") or None,
                "source": "polysmartwallet",
            })
    return out


def parse_polycopy_traders(html: str) -> list[dict]:
    pairs = re.findall(
        r'\\"wallet\\":\\"(0x[a-fA-F0-9]{40})\\",\\"displayName\\":\\"([^\\"]*)\\"',
        html,
    )
    out = []
    for wallet, name in pairs:
        addr = _norm_addr(wallet)
        if addr:
            out.append({"address": addr, "name": name or None, "source": "polycopy"})
    return out


def fetch_polycopy() -> list[dict]:
    r = _c().get("https://polycopy.app/polymarket-leaderboard/weather")
    r.raise_for_status()
    return parse_polycopy_traders(r.text)


def merge_traders(groups: Iterable[list[dict]]) -> list[dict]:
    by: dict[str, dict] = {}
    for group in groups:
        for t in group:
            addr = t["address"]
            extra_sources = list(t.get("sources") or [])
            if t.get("source"):
                extra_sources.append(t["source"])
            cur = by.get(addr)
            if cur is None:
                by[addr] = {
                    "address": addr,
                    "name": t.get("name"),
                    "sources": list(dict.fromkeys(extra_sources)),
                }
            else:
                if t.get("name") and (not cur.get("name") or cur["name"] == addr):
                    cur["name"] = t["name"]
                for src in extra_sources:
                    if src not in cur["sources"]:
                        cur["sources"].append(src)
    return list(by.values())


def fetch_leaderboards() -> list[dict]:
    return merge_traders([
        fetch_weatherbot(),
        fetch_polysmartwallet(),
        fetch_polycopy(),
    ])


def _month_day_year(dt: datetime) -> tuple[str, int, int]:
    return dt.strftime("%B").lower(), dt.day, dt.year


def fetch_event_by_slug(slug: str) -> dict | None:
    r = _c().get("https://gamma-api.polymarket.com/events", params={"slug": slug})
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


def live_weather_events(days: int = 2, slugs: list[str] | None = None) -> list[dict]:
    """Активные (и только что закрытые) highest-temperature события на окно дат."""
    slugs = slugs or CITY_SLUGS
    now = datetime.now(timezone.utc)
    events: list[dict] = []
    seen: set[str] = set()
    for offset in range(days):
        day = now + timedelta(days=offset)
        month, d, year = _month_day_year(day)
        for city in slugs:
            slug = f"highest-temperature-in-{city}-on-{month}-{d}-{year}"
            try:
                ev = fetch_event_by_slug(slug)
            except Exception:
                continue
            if not ev:
                continue
            eid = str(ev.get("id") or "")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            events.append({
                "id": eid,
                "title": ev.get("title"),
                "slug": ev.get("slug") or slug,
                "closed": bool(ev.get("closed")),
            })
    return events


def live_weather_condition_ids(days: int = 2, slugs: list[str] | None = None) -> list[str]:
    """conditionId бакетов — через события (совместимость)."""
    ids: list[str] = []
    seen: set[str] = set()
    for ev in live_weather_events(days=days, slugs=slugs):
        try:
            full = fetch_event_by_slug(ev["slug"]) if ev.get("slug") else None
        except Exception:
            full = None
        if not full:
            continue
        for mk in full.get("markets") or []:
            cid = mk.get("conditionId") or mk.get("condition_id")
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(cid)
    return ids


def _page_trades(params: dict, limit: int) -> list[str]:
    addrs: list[str] = []
    offset = 0
    while offset < limit:
        batch = min(100, limit - offset)
        q = dict(params)
        q.update({"limit": batch, "offset": offset})
        r = _c().get("https://data-api.polymarket.com/trades", params=q)
        r.raise_for_status()
        rows = r.json()
        if not isinstance(rows, list) or not rows:
            break
        for t in rows:
            addr = _norm_addr(t.get("proxyWallet") or t.get("owner") or t.get("user"))
            if addr:
                addrs.append(addr)
        if len(rows) < batch:
            break
        offset += batch
    return addrs


def traders_of_market(condition_id: str, limit: int = 400) -> list[str]:
    """Трейдеры бакета. Data API фильтрует по market=<conditionId>, не condition_id=."""
    return _page_trades({"market": condition_id}, limit)


def traders_of_event(event_id: str, limit: int = 800) -> list[str]:
    """Трейдеры всего события (все бакеты). Фильтр: eventId=."""
    return _page_trades({"eventId": event_id}, limit)


def fetch_live_market_traders(
    *,
    min_hits: int = 1,
    max_events: int = 50,
    per_event: int = 800,
    days: int = 2,
    max_markets: int | None = None,
    per_market: int | None = None,
) -> list[dict]:
    # max_markets/per_market — старые имена, игнор если передали
    events = live_weather_events(days=days)[:max_events]
    counter: Counter[str] = Counter()
    for ev in events:
        try:
            counter.update(traders_of_event(ev["id"], limit=per_event))
        except Exception:
            continue
    out = []
    for addr, n in counter.most_common():
        if n < min_hits:
            continue
        out.append({
            "address": addr,
            "name": None,
            "source": "live-markets",
            "market_hits": n,
        })
    return out
    cids = live_weather_condition_ids(days=days)
    cids = cids[:max_markets]
    counter: Counter[str] = Counter()
    for cid in cids:
        try:
            counter.update(traders_of_market(cid, limit=per_market))
        except Exception:
            continue
    out = []
    for addr, n in counter.most_common():
        if n < min_hits:
            continue
        out.append({
            "address": addr,
            "name": None,
            "source": "live-markets",
            "market_hits": n,
        })
    return out


def discover_candidates(*, include_live_markets: bool = True) -> dict:
    boards = fetch_leaderboards()
    live = fetch_live_market_traders() if include_live_markets else []
    merged = merge_traders([boards, live])
    return {
        "leaderboards": len(boards),
        "live_markets": len(live),
        "unique": len(merged),
        "traders": merged,
    }
