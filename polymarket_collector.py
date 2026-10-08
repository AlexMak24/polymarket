#!/usr/bin/env python3
"""
Polymarket Collector — фоновый сборщик данных в БД.
====================================================
Собирает ВСЁ для точных бектестов:
  1) Полный пересбор (раз в --refresh сек): рынки + цены + РЕЗОЛЮЦИИ закрытых.
  2) Частый тик (раз в --tick сек):
     - стакан (bid/ask/mid) по «горячим» рынкам → price_snapshots
     - новые сделки → trades
     - позиции топ-кошельков → positions

Пишет в SQLite (polymarket.db) + логирует в logs/collector.log.
Не падает: каждая операция в try/except, бесконечный цикл.

Запуск:
  /Users/alexander/agents-env/bin/python3 polymarket_collector.py --tick 30 --refresh 600
"""

import argparse
import datetime
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import urllib.request

import polymarket_crypto_parser as P
import polymarket_db as DB

CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
HEADERS = P.HEADERS

LOG_DIR = DB.BASE_DIR / "logs"


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)
    log = logging.getLogger("collector")
    log.setLevel(logging.INFO)
    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh = logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)
    return log


log = setup_logging()

TITLE_ASSET = {
    "bitcoin": "btc", "ethereum": "eth", "solana": "sol", "xrp": "xrp",
    "dogecoin": "doge", "doge": "doge", "bnb": "bnb", "chainlink": "link",
    "ethena": "ena", "litecoin": "ltc",
}


def asset_from_title(t):
    t = (t or "").lower()
    for k, v in TITLE_ASSET.items():
        if t.startswith(k):
            return v
    return None


def fetch_book(token_id):
    r = httpx.get(f"{CLOB}/book", params={"token_id": token_id}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_trades(condition_id, limit=200):
    r = httpx.get(f"{DATA}/trades", params={"market": condition_id, "limit": limit},
                  headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_positions(wallet, limit=500):
    r = httpx.get(f"{DATA}/positions", params={"user": wallet, "limit": limit, "offset": 0},
                  headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()



SPOT_ASSETS = ("btc", "eth", "sol", "xrp")
_BINANCE = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
}
_CG = {
    "btc": "bitcoin", "eth": "ethereum", "sol": "solana", "xrp": "ripple",
}
_BYBIT = {
    "btc": "BTCUSDT", "eth": "ETHUSDT", "sol": "SOLUSDT", "xrp": "XRPUSDT",
}


def _http_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "polymarket-collector/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_spot_price(asset: str):
    """Geo-aware: Binance → CoinGecko → Bybit. Returns (price, source) or (None, None)."""
    a = (asset or "").lower()
    # 1) Binance
    sym = _BINANCE.get(a)
    if sym:
        try:
            d = _http_json(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}")
            return float(d["price"]), "binance"
        except Exception:
            pass
    # 2) CoinGecko
    cid = _CG.get(a)
    if cid:
        try:
            d = _http_json(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cid}&vs_currencies=usd"
            )
            return float(d[cid]["usd"]), "coingecko"
        except Exception:
            pass
    # 3) Bybit
    sym = _BYBIT.get(a)
    if sym:
        try:
            d = _http_json(
                f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}"
            )
            lst = (d.get("result") or {}).get("list") or []
            if lst:
                return float(lst[0]["lastPrice"]), "bybit"
        except Exception:
            pass
    return None, None


def tick_spot_prices(conn, assets=SPOT_ASSETS):
    n = 0
    for a in assets:
        price, source = fetch_spot_price(a)
        if price is None:
            continue
        DB.insert_spot_tick(conn, a, price, source)
        n += 1
    if n:
        conn.commit()
    return n


def rebuild_markets(conn):
    """Полный пересбор: discover + fetch → markets + снимок цен + резолюции закрытых."""
    t0 = time.time()
    all_series = P.discover_series()
    target = [s for s in all_series if P.is_target_series(s, None, None)]
    now = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    resolved = 0
    for s in target:
        sid = s.get("id")
        # активные рынки
        try:
            events = P.fetch_active_events(sid, now)
        except Exception as e:
            log.warning("серия %s: %s", s.get("slug"), e)
            continue
        for e in events:
            for m in e.get("markets", []):
                rec = P.market_to_record(s, m, now)
                ptb, fp = P.extract_event_spot_prices(e)
                if ptb is None and fp is None:
                    ptb, fp = P.extract_event_spot_prices(m)
                # spot-on-open: refetch eventMetadata when missing on newly seen actives
                if ptb is None:
                    slug = e.get("slug") or m.get("slug")
                    if slug:
                        try:
                            ev2 = P.fetch_event_by_slug(slug)
                            ptb2, fp2 = P.extract_event_spot_prices(ev2)
                            if ptb2 is not None:
                                ptb = ptb2
                            if fp is None and fp2 is not None:
                                fp = fp2
                        except Exception:
                            pass
                if ptb is not None:
                    rec["price_to_beat"] = ptb
                if fp is not None:
                    rec["final_price"] = fp
                DB.upsert_market(conn, rec)
                DB.snapshot_price(
                    conn, rec["conditionId"], rec["bid"], rec["ask"], rec["mid"],
                    rec.get("volumeNum") if rec.get("volumeNum") is not None else rec.get("volume"),
                    rec.get("liquidity"), rec.get("lastTradePrice"),
                )
                count += 1
        # закрытые рынки (резолюции)
        try:
            cevs = P.fetch_closed_events(sid, limit=100)
        except Exception:
            cevs = []
        for e in cevs:
            for m in e.get("markets", []):
                if m.get("umaResolutionStatus") != "resolved":
                    continue
                cond = m.get("conditionId")
                winner = DB.resolve_outcome(m.get("outcomes"), m.get("outcomePrices"))
                rec = P.market_to_record(s, m, now)
                ptb, fp = P.extract_event_spot_prices(e)
                if ptb is None and fp is None:
                    ptb, fp = P.extract_event_spot_prices(m)
                if ptb is not None:
                    rec["price_to_beat"] = ptb
                if fp is not None:
                    rec["final_price"] = fp
                DB.upsert_market(conn, rec)
                DB.mark_resolution(
                    conn, cond, m.get("outcomePrices"), "resolved", winner,
                    price_to_beat=ptb, final_price=fp,
                )
                resolved += 1
        conn.commit()  # освобождаем write-lock после каждой серии
    log.info("пересбор: %d рынков, %d резолюций, %d серий за %.1fс",
             count, resolved, len(target), time.time() - t0)
    return count


def tick_prices(conn, window_minutes=30, workers=16):
    """Частый снимок СТАКАНА (bid/ask/mid) по горячим рынкам (параллельно)."""
    hot = DB.get_hot_markets(conn, window_minutes)
    valid = [m for m in hot if m["token_yes"]]

    def snap(m):
        try:
            b = fetch_book(m["token_yes"])
            bids = b.get("bids") or []
            asks = b.get("asks") or []
            bid = float(bids[-1]["price"]) if bids else None
            ask = float(asks[0]["price"]) if asks else None
            bid_size = float(bids[-1]["size"]) if bids else None
            ask_size = float(asks[0]["size"]) if asks else None
            mid = round((bid + ask) / 2, 4) if bid is not None and ask is not None else None
            lt = b.get("last_trade_price")
            return (m["condition_id"], bid, ask, mid, lt, bid_size, ask_size)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(snap, valid))
    ok = 0
    for r in results:
        if r:
            DB.snapshot_price(
                conn, r[0], r[1], r[2], r[3], None, None, r[4],
                bid_size=r[5], ask_size=r[6],
            )
            ok += 1
    conn.commit()
    return ok, len(valid)


def tick_trades(conn, window_minutes=30, workers=8):
    """Сделки по горячим рынкам (дедуп по tx_hash, параллельно)."""
    hot = DB.get_hot_markets(conn, window_minutes)

    def grab(m):
        try:
            trades = fetch_trades(m["condition_id"], 200)
            return m["condition_id"], trades
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(grab, hot))
    n = 0
    for r in results:
        if r:
            n += DB.insert_trades(conn, r[0], r[1])
    return n
def _decisive_winner(outcomes, prices):
    """Winner if one outcome price is clearly decisive (>=0.95)."""
    try:
        if isinstance(prices, str):
            prices_list = json.loads(prices)
        else:
            prices_list = prices
        outcomes_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    except (TypeError, json.JSONDecodeError):
        return None
    if not outcomes_list or not prices_list:
        return None
    try:
        vals = [float(x) for x in prices_list]
    except (TypeError, ValueError):
        return None
    if not vals or max(vals) < 0.95:
        return None
    winner = DB.resolve_outcome(outcomes_list, prices_list)
    if winner is not None:
        return winner
    i = vals.index(max(vals))
    if i < len(outcomes_list):
        return outcomes_list[i]
    return None


def reconcile_resolutions(conn, limit=200, offset=0):
    """Добить unresolved через Gamma market id / condition_ids / event slug."""
    pending = DB.unresolved_markets(conn, limit, offset=offset)
    n = 0
    for m in pending:
        gid = m.get("gamma_id")
        raw = None
        try:
            if gid:
                raw = P.fetch_market_by_id(gid)
            if not raw:
                raw = P.fetch_market_by_condition_id(m["condition_id"])
            if not raw:
                raw = P.fetch_market_via_slug_recovery(
                    m["condition_id"],
                    asset=m.get("asset"),
                    recurrence=m.get("recurrence"),
                    end_date=m.get("end_date"),
                    question=m.get("question"),
                    series_slug=m.get("series_slug"),
                )
        except Exception:
            continue
        if not raw:
            continue

        status = (raw.get("umaResolutionStatus") or "").lower()
        closed = bool(raw.get("closed"))
        winner = _decisive_winner(raw.get("outcomes"), raw.get("outcomePrices"))
        is_resolved = (
            status == "resolved"
            or (closed and winner is not None)
            or (status in ("proposed", "disputed", "") and winner is not None)
        )
        if not is_resolved:
            continue

        price_to_beat, final_price = None, None
        try:
            price_to_beat, final_price = P.extract_event_spot_prices(raw)
        except Exception:
            pass
        if price_to_beat is None and final_price is None:
            slug = raw.get("slug") or raw.get("eventSlug")
            if not slug and raw.get("events"):
                ev0 = raw["events"][0] if isinstance(raw["events"], list) else None
                slug = (ev0 or {}).get("slug") if isinstance(ev0, dict) else None
            if slug:
                try:
                    ev = P.fetch_event_by_slug(slug)
                    price_to_beat, final_price = P.extract_event_spot_prices(ev)
                except Exception:
                    pass

        if not gid and raw.get("id") is not None:
            try:
                conn.execute(
                    "UPDATE markets SET gamma_id=COALESCE(gamma_id, ?) WHERE condition_id=?",
                    (raw.get("id"), m["condition_id"]),
                )
            except Exception:
                pass

        DB.mark_resolution(
            conn,
            m["condition_id"],
            raw.get("outcomePrices"),
            "resolved",
            winner,
            price_to_beat=price_to_beat,
            final_price=final_price,
        )
        n += 1
    conn.commit()
    return n

def tick_positions(conn, top_n=100, workers=8):
    """Открытые позиции топ-кошельков (по активности в сделках)."""
    wallets = DB.top_wallets(conn, top_n)

    def grab(w):
        try:
            pos = fetch_positions(w)
            out = []
            for p in pos:
                out.append({
                    "wallet": w,
                    "condition_id": p.get("conditionId"),
                    "asset": asset_from_title(p.get("title")),
                    "outcome": p.get("outcome"),
                    "size": p.get("size"),
                    "avg_price": p.get("avgPrice"),
                    "cur_price": p.get("curPrice"),
                    "current_value": p.get("currentValue"),
                    "cash_pnl": p.get("cashPnl"),
                    "realized_pnl": p.get("realizedPnl"),
                    "percent_pnl": p.get("percentPnl"),
                    "total_bought": p.get("totalBought"),
                    "ts": int(p.get("timestamp") or 0),
                })
            return out
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(grab, wallets))
    n = 0
    for r in results:
        if r:
            n += DB.upsert_positions(conn, r)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", type=int, default=30, help="период частого тика, сек")
    ap.add_argument("--refresh", type=int, default=600, help="период полного пересбора, сек")
    ap.add_argument("--db", default=None, help="путь к SQLite")
    ap.add_argument("--once", action="store_true", help="один полный пересбор и выход")
    args = ap.parse_args()

    conn = DB.connect(args.db)
    DB.init_db(conn)
    log.info("=== Collector старт (tick=%ds, refresh=%ds) ===", args.tick, args.refresh)

    if args.once:
        rebuild_markets(conn)
        try:
            nr = reconcile_resolutions(conn, limit=500)
            log.info("reconcile once: %d", nr)
        except Exception as e:
            log.error("reconcile once упал: %s", e)
        log.info("Статистика: %s", DB.stats(conn))
        return

    last_refresh = 0.0
    while True:
        try:
            # 1) полный пересбор + резолюции по расписанию
            if time.time() - last_refresh >= args.refresh:
                try:
                    rebuild_markets(conn)
                    try:
                        nr = reconcile_resolutions(conn, limit=200)
                        if nr:
                            log.info("reconcile: %d резолюций добито", nr)
                    except Exception as e:
                        log.error("reconcile упал: %s", e)
                    last_refresh = time.time()
                except Exception as e:
                    log.error("пересбор упал: %s", e)
                    last_refresh = time.time()

            # 2) частые тики
            try:
                ok, total = tick_prices(conn)
                log.info("стакан: %d/%d горячих рынков обновлено", ok, total)
            except Exception as e:
                log.error("тик стакана упал: %s", e)

            try:
                n = tick_trades(conn)
                if n:
                    log.info("сделки: +%d новых", n)
            except Exception as e:
                log.error("тик сделок упал: %s", e)

            try:
                np_ = tick_positions(conn)
                if np_:
                    log.info("позиции: %d обновлено", np_)
            except Exception as e:
                log.error("тик позиций упал: %s", e)

            try:
                ns = tick_spot_prices(conn)
                if ns:
                    log.info("spot_ticks: %d assets", ns)
            except Exception as e:
                log.error("тик spot упал: %s", e)

        except Exception as e:
            log.error("общий сбой цикла: %s", e)

        time.sleep(args.tick)


if __name__ == "__main__":
    main()
