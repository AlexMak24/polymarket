#!/usr/bin/env python3
"""
Polymarket Backfill — досбор истории цен по завершённым рынкам.
================================================================
CLOB /prices-history?market=<token_id>&interval=1m&fidelity=10&startTs=..&endTs=..
возвращает {'history': [{'t': unix, 'p': price}, ...]}.

Для каждого resolved-рынка тянем историю цены от конца свечи назад и пишем
в price_snapshots (mid = p). Интервал зависит от таймфрейма.

Запуск:
  /Users/alexander/agents-env/bin/python3 polymarket_backfill.py --hours 24 --limit 2000
"""

import argparse
import datetime
import time

import httpx

import polymarket_db as DB

CLOB = "https://clob.polymarket.com"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
}

# таймфрейм → (interval, окно в секундах до конца)
TF_PARAMS = {
    "5m": ("1m", 3600),
    "15m": ("1m", 7200),
    "4h": ("1h", 6 * 3600),
    "hourly": ("1h", 6 * 3600),
    "daily": ("1h", 24 * 3600),
    "weekly": ("6h", 7 * 24 * 3600),
    "monthly": ("1d", 31 * 24 * 3600),
}


def backfill_market(conn, condition_id, token_yes, end_date, recurrence):
    if not token_yes:
        return 0
    interval, window = TF_PARAMS.get(recurrence, ("1h", 6 * 3600))
    try:
        end_ts = int(datetime.datetime.fromisoformat(
            end_date.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0
    start_ts = end_ts - window
    r = httpx.get(
        f"{CLOB}/prices-history",
        params={"market": token_yes, "interval": interval, "fidelity": 10,
                "startTs": start_ts, "endTs": end_ts},
        headers=HEADERS, timeout=20,
    )
    r.raise_for_status()
    hist = r.json().get("history", [])
    for p in hist:
        ts = datetime.datetime.fromtimestamp(p["t"], datetime.timezone.utc).isoformat()
        DB.snapshot_price(conn, condition_id, None, None, p.get("p"), None, None, None, ts)
    return len(hist)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24, help="бекфилл рынков, завершившихся за последние N часов")
    ap.add_argument("--limit", type=int, default=2000, help="макс. число рынков")
    ap.add_argument("--assets", default=None, help="активы через запятую (btc,eth,...)")
    args = ap.parse_args()

    conn = DB.connect()
    DB.init_db(conn)

    since = (datetime.datetime.now(datetime.timezone.utc)
             - datetime.timedelta(hours=args.hours)).isoformat()
    q = ("SELECT condition_id, token_yes, end_date, recurrence FROM markets "
         "WHERE resolution_status='resolved' AND end_date >= ?")
    rows = conn.execute(q, (since,)).fetchall()
    if args.assets:
        wanted = set(args.assets.split(","))
        rows = [r for r in rows if _asset_of(conn, r[0]) in wanted]

    total_points = 0
    done = 0
    for i, r in enumerate(rows[: args.limit]):
        for attempt in range(5):
            try:
                n = backfill_market(conn, r[0], r[1], r[2], r[3])
                total_points += n
                done += 1
                break
            except Exception:
                time.sleep(3)
        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  ... {i+1}/{len(rows[:args.limit])} рынков, точек: {total_points}", flush=True)
    conn.commit()
    print(f"Бекфилл завершён: {done} рынков, {total_points} точек истории")
    print("Статистика:", DB.stats(conn))


def _asset_of(conn, condition_id):
    r = conn.execute("SELECT asset FROM markets WHERE condition_id=?", (condition_id,)).fetchone()
    return r[0] if r else None


if __name__ == "__main__":
    main()
