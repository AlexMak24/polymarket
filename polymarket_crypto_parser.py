#!/usr/bin/env python3
"""
Polymarket Crypto Parser
=========================
Собирает все прикладные крипто-рынки Polymarket:
  - Up or Down (свечи 5м / 15м / 1ч / 4ч / день / неделя / месяц) — «какой цвет свечи будет»
  - Hit Price (дойдёт ли цена до X за период)
  - Multi Strikes (страйк-опционы)
  - Neg Risk (негативный риск, набор страйков)

Для каждого рынка вытаскивает: вопрос, временное окно, цену Up/Yes (bid/ask/mid),
спред, conditionId, clobTokenIds, объём.

Вывод:
  --out JSON  (по умолчанию ./polymarket_crypto_snapshot.json) — полный снимок
  stdout       — сводка по активам и таймфреймам

Запуск:
  /Users/alexander/agents-env/bin/python3 polymarket_crypto_parser.py
  /Users/alexander/agents-env/bin/python3 polymarket_crypto_parser.py --types up-or-down
  /Users/alexander/agents-env/bin/python3 polymarket_crypto_parser.py --assets btc,eth,sol
  /Users/alexander/agents-env/bin/python3 polymarket_crypto_parser.py --timeframes 5m,15m,1h
"""

import argparse
import re
import datetime
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).resolve().parent
GAMMA = "https://gamma-api.polymarket.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Паттерны slug для типов серий
SERIES_TYPES = {
    "up-or-down": "up-or-down",
    "hit-price": "hit-price",
    "multi-strikes": "multi-strikes",
    "neg-risk": "neg-risk",
}

# Крипто-активы: первый сегмент slug → канонический тикер
ASSET_ALIASES = {
    "btc": "btc", "bitcoin": "btc", "archbtc": "btc",
    "eth": "eth", "ethereum": "eth", "ethbtc": "eth",
    "sol": "sol", "solana": "sol", "soleth": "sol",
    "xrp": "xrp",
    "doge": "doge", "dogecoin": "doge",
    "bnb": "bnb",
    "chainlink": "link",
    "ethena": "ena",
    "litecoin": "ltc",
}

# Таймфреймы (по recurrence в серии)
TIMEFRAMES = ["5m", "15m", "4h", "hourly", "daily", "weekly", "monthly"]


def discover_series():
    """Пагинация /series — все серии."""
    series = []
    off = 0
    while True:
        r = httpx.get(f"{GAMMA}/series", params={"limit": 50, "offset": off},
                      headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        series.extend(batch)
        if len(batch) < 50:
            break
        off += 50
    return series


def match_asset(slug):
    """Определяет канонический актив по первому сегменту slug серии."""
    slug = slug or ""
    first = slug.split("-")[0].lower()
    return ASSET_ALIASES.get(first)


def is_target_series(s, types, assets):
    slug = (s.get("slug") or "").lower()
    a = match_asset(slug)
    if a is None:
        return False  # не крипто-серия
    if not any(SERIES_TYPES[t] in slug for t in SERIES_TYPES):
        return False
    if types and not any(SERIES_TYPES[t] in slug for t in types):
        return False
    if assets and a not in assets:
        return False
    return True


def parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_active_events(series_id, now, limit_hours=None):
    """Собирает события серии с endDate >= now (активные/будущие), order=endDate desc."""
    events = []
    off = 0
    while True:
        r = httpx.get(
            f"{GAMMA}/events",
            params={
                "series_id": series_id,
                "active": "true",
                "closed": "false",
                "limit": 100,
                "offset": off,
                "order": "endDate",
                "ascending": "false",
            },
            headers=HEADERS,
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break

        hit_past = False
        for e in batch:
            ed = parse_iso(e.get("endDate"))
            if ed is None:
                continue
            if ed >= now:
                if limit_hours is None or ed <= now + datetime.timedelta(hours=limit_hours):
                    events.append(e)
            else:
                hit_past = True
        if hit_past or len(batch) < 100:
            break
        off += 100
        if off > 5000:
            break
    return events


def fetch_closed_events(series_id, limit=20):
    """Последние закрытые события серии (для резолюций). order=endDate desc."""
    r = httpx.get(
        f"{GAMMA}/events",
        params={
            "series_id": series_id,
            "closed": "true",
            "limit": limit,
            "offset": 0,
            "order": "endDate",
            "ascending": "false",
        },
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_market_by_id(gamma_id):
    """Один рынок Gamma по id (для резолюции)."""
    r = httpx.get(f"{GAMMA}/markets/{gamma_id}", headers=HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json()
    return None


def fetch_market_by_condition_id(condition_id):
    """Один рынок Gamma по conditionId (fallback когда нет gamma_id)."""
    if not condition_id:
        return None
    r = httpx.get(
        f"{GAMMA}/markets",
        params={"condition_ids": condition_id},
        headers=HEADERS,
        timeout=15,
    )
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, list):
        return data[0] if data else None
    return data


def fetch_event_by_slug(slug):
    """Событие Gamma по slug (для priceToBeat / finalPrice в eventMetadata)."""
    if not slug:
        return None
    r = httpx.get(f"{GAMMA}/events", params={"slug": slug}, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, list):
        return data[0] if data else None
    return data




# --- gamma_id recovery via event slug (historical markets drop from /markets?condition_ids=) ---
RECURRENCE_SECONDS = {
    "5m": 300,
    "15m": 900,
    "hourly": 3600,
    "4h": 14400,
    "daily": 86400,
}

_ASSET_FULL = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "xrp": "xrp",
    "doge": "dogecoin",
    "bnb": "bnb",
}

_HOURLY_Q_RE = re.compile(
    r"^(Bitcoin|Ethereum|Solana|XRP|Dogecoin|BNB)\s+Up or Down\s+-\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{1,2})(AM|PM)\s*ET",
    re.IGNORECASE,
)


def _end_unix(end_date: str | None) -> int | None:
    if not end_date:
        return None
    try:
        t = dt.datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp())


def hourly_updown_slug_from_question(question: str | None, year: int | None = None) -> str | None:
    """Bitcoin Up or Down - September 24, 3PM ET → bitcoin-up-or-down-september-24-2026-3pm-et"""
    if not question:
        return None
    m = _HOURLY_Q_RE.match(question.strip())
    if not m:
        return None
    y = year if year is not None else dt.datetime.now(dt.timezone.utc).year
    asset_full = m.group(1).lower()
    month = m.group(2).lower()
    day = m.group(3)
    hour = m.group(4)
    ap = m.group(5).lower()
    return f"{asset_full}-up-or-down-{month}-{day}-{y}-{hour}{ap}-et"



_HOURLY_ABOVE_Q_RE = re.compile(
    r"^(Bitcoin|Ethereum|Solana|XRP|Dogecoin|BNB)\s+above\s+[0-9,]+\s+on\s+"
    r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{1,2})(AM|PM)\s*ET",
    re.IGNORECASE,
)


def hourly_above_slug_from_question(question: str | None, year: int | None = None) -> str | None:
    """Bitcoin above 86,400 on September 24, 7PM ET? → bitcoin-above-on-september-24-2026-7pm-et"""
    if not question:
        return None
    m = _HOURLY_ABOVE_Q_RE.match(question.strip().rstrip("?"))
    if not m:
        return None
    y = year if year is not None else dt.datetime.now(dt.timezone.utc).year
    asset_full = m.group(1).lower()
    month = m.group(2).lower()
    day = m.group(3)
    hour = m.group(4)
    ap = m.group(5).lower()
    return f"{asset_full}-above-on-{month}-{day}-{y}-{hour}{ap}-et"


def candidate_event_slugs(asset: str | None, recurrence: str | None, end_date: str | None,
                          question: str | None = None) -> list[str]:
    """Build Gamma event slug candidates for markets missing gamma_id."""
    out: list[str] = []
    a = (asset or "").lower().strip()
    rec = (recurrence or "").lower().strip()
    u = _end_unix(end_date)
    if a and rec in ("5m", "15m") and u is not None:
        dur = RECURRENCE_SECONDS[rec]
        # Polymarket uses window START unix in slug: btc-updown-5m-{start}
        out.append(f"{a}-updown-{rec}-{u - dur}")
        out.append(f"{a}-updown-{rec}-{u}")  # rare fallback
    if a and rec == "hourly" and question:
        y = None
        if end_date:
            try:
                y = dt.datetime.fromisoformat(str(end_date).replace("Z", "+00:00")).year
            except ValueError:
                y = None
        slug = hourly_updown_slug_from_question(question, year=y)
        if slug:
            out.append(slug)
        m = _HOURLY_Q_RE.match(question.strip())
        if m:
            # older events omit year in slug
            out.append(
                f"{m.group(1).lower()}-up-or-down-{m.group(2).lower()}-"
                f"{m.group(3)}-{m.group(4)}{m.group(5).lower()}-et"
            )
        # multi-strike "above" hourly: event slug has NO strike — markets are children
        above = hourly_above_slug_from_question(question, year=y)
        if above:
            out.append(above)
            # also try without year
            m2 = _HOURLY_ABOVE_Q_RE.match(question.strip().rstrip("?"))
            if m2:
                out.append(
                    f"{m2.group(1).lower()}-above-on-{m2.group(2).lower()}-"
                    f"{m2.group(3)}-{m2.group(4)}{m2.group(5).lower()}-et"
                )
        # series slug hint → try reconstructing from series_slug if question parse fails
        # (handled in fetch_market_via_series_recovery)
    # de-dupe preserve order
    seen = set()
    uniq = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def fetch_market_via_slug_recovery(condition_id: str, asset=None, recurrence=None,
                                   end_date=None, question=None, series_slug=None):
    """Recover Gamma market JSON by reconstructing event slug; require conditionId match."""
    if not condition_id:
        return None
    want = condition_id.lower()
    for slug in candidate_event_slugs(asset, recurrence, end_date, question):
        try:
            ev = fetch_event_by_slug(slug)
        except Exception:
            continue
        if not ev:
            continue
        for m in (ev.get("markets") or []):
            cid = (m.get("conditionId") or m.get("condition_id") or "").lower()
            if cid == want:
                # attach event slug for spot-price follow-up
                m = dict(m)
                m.setdefault("eventSlug", ev.get("slug") or slug)
                if ev.get("eventMetadata") and not m.get("eventMetadata"):
                    m["eventMetadata"] = ev.get("eventMetadata")
                return m
    # series scan fallback (multi-strike hourly residuals)
    try:
        hit = fetch_market_via_series_recovery(condition_id, series_slug, end_date)
        if hit:
            return hit
    except Exception:
        pass
    return None



def fetch_market_via_series_recovery(condition_id: str, series_slug: str | None = None,
                                      end_date: str | None = None, pages: int = 8):
    """Scan closed Gamma events for series_slug; match child market by conditionId."""
    if not condition_id or not series_slug:
        return None
    want = condition_id.lower()
    # resolve series id
    sid = None
    try:
        r = httpx.get(f"{GAMMA}/series", params={"slug": series_slug}, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                sid = data[0].get("id")
            elif isinstance(data, dict):
                sid = data.get("id")
    except Exception:
        sid = None
    if sid is None:
        return None
    for page in range(pages):
        try:
            r = httpx.get(
                f"{GAMMA}/events",
                params={
                    "series_id": sid,
                    "closed": "true",
                    "limit": 50,
                    "offset": page * 50,
                    "order": "endDate",
                    "ascending": "false",
                },
                headers=HEADERS,
                timeout=30,
            )
            if r.status_code != 200:
                break
            batch = r.json() or []
        except Exception:
            break
        if not batch:
            break
        for ev in batch:
            for m in (ev.get("markets") or []):
                cid = (m.get("conditionId") or m.get("condition_id") or "").lower()
                if cid == want:
                    m = dict(m)
                    m.setdefault("eventSlug", ev.get("slug"))
                    if ev.get("eventMetadata") and not m.get("eventMetadata"):
                        m["eventMetadata"] = ev.get("eventMetadata")
                    return m
    return None


def extract_event_spot_prices(event_or_market):
    """Достаёт priceToBeat / finalPrice из eventMetadata или плоских полей."""
    if not event_or_market:
        return None, None

    def _from_obj(obj):
        if not isinstance(obj, dict):
            return None, None
        meta = obj.get("eventMetadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except (TypeError, json.JSONDecodeError):
                meta = {}
        if not isinstance(meta, dict):
            meta = {}
        ptb = meta.get("priceToBeat") or obj.get("priceToBeat")
        fp = meta.get("finalPrice") or obj.get("finalPrice")
        return ptb, fp

    ptb, fp = _from_obj(event_or_market)
    if ptb is not None or fp is not None:
        return ptb, fp
    # market payloads sometimes nest the parent event
    events_list = event_or_market.get("events")
    if isinstance(events_list, list):
        for ev in events_list:
            ptb, fp = _from_obj(ev)
            if ptb is not None or fp is not None:
                return ptb, fp
    return None, None


def market_to_record(s, m, now):
    """Преобразует market Gamma → плоский dict."""
    outcomes = m.get("outcomes")
    tokens = m.get("clobTokenIds")
    try:
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    except (TypeError, json.JSONDecodeError):
        outcomes = []
    try:
        tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
    except (TypeError, json.JSONDecodeError):
        tokens = []

    bid = m.get("bestBid")
    ask = m.get("bestAsk")
    mid = None
    if bid is not None and ask is not None:
        mid = round((float(bid) + float(ask)) / 2, 4)

    rec = {
        "series_slug": s.get("slug"),
        "series_id": s.get("id"),
        "asset": match_asset(s.get("slug") or ""),
        "recurrence": s.get("recurrence"),
        "question": m.get("question"),
        "endDate": m.get("endDate"),
        "outcomes": outcomes,
        "bid": bid,          # цена YES/Up (bid)
        "ask": ask,          # цена YES/Up (ask)
        "mid": mid,          # середина спреда
        "spread": m.get("spread"),
        "conditionId": m.get("conditionId"),
        "token_yes": tokens[0] if len(tokens) > 0 else None,
        "token_no": tokens[1] if len(tokens) > 1 else None,
        "volume": m.get("volume"),
        "volumeNum": m.get("volumeNum"),
        "liquidity": m.get("liquidity"),
        "lastTradePrice": m.get("lastTradePrice"),
        # новые поля (для резолюций и полной картины)
        "gamma_id": m.get("id"),
        "outcome_prices": m.get("outcomePrices"),
        "resolution_status": m.get("umaResolutionStatus"),
        "closed": m.get("closed"),
        "price_to_beat": None,
        "final_price": None,
    }
    ptb, fp = extract_event_spot_prices(m)
    if ptb is not None:
        rec["price_to_beat"] = ptb
    if fp is not None:
        rec["final_price"] = fp
    return rec


def main():
    ap = argparse.ArgumentParser(description="Polymarket crypto parser")
    ap.add_argument("--out", default="./polymarket_crypto_snapshot.json",
                    help="путь к выходному JSON")
    ap.add_argument("--types", default=None,
                    help="типы серий через запятую: up-or-down,hit-price,multi-strikes,neg-risk")
    ap.add_argument("--assets", default=None,
                    help="активы через запятую: btc,eth,sol,xrp,doge,bnb")
    ap.add_argument("--timeframes", default=None,
                    help="таймфреймы через запятую: 5m,15m,1h,4h,daily")
    ap.add_argument("--limit-hours", type=float, default=None,
                    help="горизонт: только рынки с концом в пределах N часов (по умолчанию все будущие)")
    args = ap.parse_args()

    types = args.types.split(",") if args.types else None
    assets = args.assets.split(",") if args.assets else None
    tfs = args.timeframes.split(",") if args.timeframes else None

    t0 = time.time()
    print("Обнаруживаю серии...", file=sys.stderr)
    all_series = discover_series()
    target = [s for s in all_series if is_target_series(s, types, assets)]
    if tfs:
        target = [s for s in target if (s.get("recurrence") or "") in tfs]
    print(f"Серий всего: {len(all_series)}, под фильтр: {len(target)}", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc)
    records = []
    stats = {}  # (asset, recurrence) -> count

    for s in target:
        sid = s.get("id")
        try:
            events = fetch_active_events(sid, now, args.limit_hours)
        except Exception as exc:
            print(f"  ! серия {s.get('slug')} (id {sid}): {exc}", file=sys.stderr)
            continue
        for e in events:
            for m in e.get("markets", []):
                rec = market_to_record(s, m, now)
                records.append(rec)
                key = (rec["asset"], rec["recurrence"])
                stats[key] = stats.get(key, 0) + 1
        time.sleep(0.05)  # щадящий ритм

    # Сортировка: актив -> таймфрейм -> endDate
    tf_order = {t: i for i, t in enumerate(TIMEFRAMES)}
    records.sort(key=lambda r: (
        r["asset"] or "",
        tf_order.get(r["recurrence"], 99),
        r["endDate"] or "",
    ))

    out = {
        "generated_at": now.isoformat(),
        "total_markets": len(records),
        "series_count": len(target),
        "markets": records,
    }
    with open(args.out, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Сохранено {len(records)} рынков -> {args.out}", file=sys.stderr)

    # ---- Сводка в stdout ----
    print(f"\n=== POLYMARKET CRYPTO: {len(records)} активных рынков, {len(target)} серий ===")
    print(f"Снимок: {now.isoformat(timespec='seconds')} UTC\n")

    # Таблица по активу × таймфрейму
    assets_order = list(dict.fromkeys(r["asset"] for r in records))
    header = "актив".ljust(8) + " | " + " | ".join(t.ljust(5) for t in TIMEFRAMES)
    print(header)
    print("-" * len(header))
    for a in assets_order:
        row = [str(stats.get((a, t), 0)).ljust(5) for t in TIMEFRAMES]
        print(a.ljust(8) + " | " + " | ".join(row))
    print("\n(числа = количество активных рынков)\n")

    # Примеры ближайших Up/Down рынков
    ud = [r for r in records if "up-or-down" in (r["series_slug"] or "")]
    ud = sorted(ud, key=lambda r: r["endDate"] or "")[:20]
    if ud:
        print("=== Ближайшие Up/Down рынки ===")
        for r in ud:
            mid = f"{r['mid']:.3f}" if r["mid"] is not None else "-"
            print(f"  {r['asset'].ljust(6)} {r['question'][:55].ljust(56)} up={mid} bid={r['bid']} ask={r['ask']}")


if __name__ == "__main__":
    main()
