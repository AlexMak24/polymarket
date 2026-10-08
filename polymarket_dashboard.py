#!/usr/bin/env python3
"""
Polymarket Crypto Dashboard
===========================
Локальный дашборд для проверки крипто-рынков Polymarket:
  - список рынков (актив / таймфрейм / тип / цена / объём)
  - стакан (bids/asks) по рынку
  - последние сделки с кошельками
  - топ кошельков-трейдеров (агрегация сделок)

Запуск:
  /Users/alexander/agents-env/bin/python3 polymarket_dashboard.py [--port 8844]
  Открыть: http://127.0.0.1:8844

Ноль зависимостей: стандартный http.server + httpx.
"""

import argparse
import datetime
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

import polymarket_crypto_parser as P

GAMMA = P.GAMMA
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
HEADERS = P.HEADERS

# Кэш снимка рынков в памяти
SNAPSHOT = {"markets": [], "total": 0, "generated_at": None, "series_count": 0}

# Кэш live-запросов (стакан/сделки) на N секунд
LIVE_CACHE = {}
CACHE_TTL = 5  # сек


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def rebuild_snapshot(types=None):
    """Перепарсивает все крипто-рынки и обновляет SNAPSHOT."""
    global SNAPSHOT
    all_series = P.discover_series()
    target = [s for s in all_series if P.is_target_series(s, types, None)]
    now = now_utc()
    records = []
    for s in target:
        try:
            events = P.fetch_active_events(s.get("id"), now)
        except Exception:
            continue
        for e in events:
            for m in e.get("markets", []):
                records.append(P.market_to_record(s, m, now))
    # сортировка
    tf_order = {t: i for i, t in enumerate(P.TIMEFRAMES)}
    records.sort(key=lambda r: (
        r["asset"] or "", tf_order.get(r["recurrence"], 99), r["endDate"] or ""))
    SNAPSHOT = {
        "markets": records,
        "total": len(records),
        "generated_at": now.isoformat(),
        "series_count": len(target),
    }
    return SNAPSHOT


def cached(key, fetcher, ttl=CACHE_TTL):
    """Простой TTL-кэш для live-запросов."""
    hit = LIVE_CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    val = fetcher()
    LIVE_CACHE[key] = (time.time(), val)
    return val


def fetch_book(token_id):
    r = httpx.get(f"{CLOB}/book", params={"token_id": token_id},
                  headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_trades(condition_id, limit=200):
    r = httpx.get(f"{DATA}/trades", params={"market": condition_id, "limit": limit},
                  headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def aggregate_traders(trades, limit=20):
    agg = {}
    for t in trades:
        w = t.get("proxyWallet") or t.get("traderAddress")
        if not w:
            continue
        a = agg.get(w)
        if a is None:
            a = {
                "wallet": w,
                "pseudonym": t.get("pseudonym") or t.get("name") or "",
                "profileImage": t.get("profileImageOptimized") or "",
                "buys": 0, "sells": 0,
                "buy_usd": 0.0, "sell_usd": 0.0,
                "net_shares": 0.0,
                "last_side": "", "last_time": 0,
            }
            agg[w] = a
        size = float(t.get("size") or 0)
        price = float(t.get("price") or 0)
        usd = size * price
        side = t.get("side", "")
        ts = int(t.get("timestamp") or 0)
        if side == "BUY":
            a["buys"] += 1
            a["buy_usd"] += usd
            a["net_shares"] += size
        else:
            a["sells"] += 1
            a["sell_usd"] += usd
            a["net_shares"] -= size
        if ts > a["last_time"]:
            a["last_time"] = ts
            a["last_side"] = side
    out = list(agg.values())
    for a in out:
        a["total_usd"] = round(a["buy_usd"] + a["sell_usd"], 2)
        a["buy_usd"] = round(a["buy_usd"], 2)
        a["sell_usd"] = round(a["sell_usd"], 2)
        a["net_shares"] = round(a["net_shares"], 1)
    out.sort(key=lambda x: x["total_usd"], reverse=True)
    return out[:limit]


def json_response(handler, obj, status=200):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # тихий лог

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                self._serve_dashboard()
            elif path == "/api/markets":
                self._api_markets(q)
            elif path == "/api/book":
                self._api_book(q)
            elif path == "/api/trades":
                self._api_trades(q)
            elif path == "/api/traders":
                self._api_traders(q)
            elif path == "/api/refresh":
                rebuild_snapshot()
                json_response(self, {"ok": True, "total": SNAPSHOT["total"],
                                     "generated_at": SNAPSHOT["generated_at"]})
            else:
                json_response(self, {"error": "not found"}, 404)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, 500)

    def _serve_dashboard(self):
        try:
            with open(P.BASE_DIR / "dashboard.html", "rb") as f:
                html = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
        except FileNotFoundError:
            json_response(self, {"error": "dashboard.html not found"}, 500)

    def _api_markets(self, q):
        if not SNAPSHOT["markets"]:
            rebuild_snapshot()
        asset = q.get("asset", [""])[0]
        tf = q.get("tf", [""])[0]
        mtype = q.get("type", [""])[0]
        min_vol = float(q.get("min_volume", ["0"])[0] or 0)
        sort = q.get("sort", ["end"])[0]  # end | volume
        limit = int(q.get("limit", ["500"])[0] or 500)

        rows = SNAPSHOT["markets"]
        if asset:
            rows = [r for r in rows if r["asset"] == asset]
        if tf:
            rows = [r for r in rows if r["recurrence"] == tf]
        if mtype:
            rows = [r for r in rows if mtype in (r["series_slug"] or "")]
        if min_vol:
            rows = [r for r in rows if (float(r.get("volumeNum") or r.get("volume") or 0)) >= min_vol]
        if sort == "volume":
            rows = sorted(rows, key=lambda r: float(r.get("volumeNum") or r.get("volume") or 0), reverse=True)
        else:
            rows = sorted(rows, key=lambda r: r["endDate"] or "")

        out = rows[:limit]
        json_response(self, {
            "total": len(rows),
            "generated_at": SNAPSHOT["generated_at"],
            "series_count": SNAPSHOT["series_count"],
            "markets": out,
        })

    def _api_book(self, q):
        token_id = q.get("token_id", [""])[0]
        if not token_id:
            json_response(self, {"error": "token_id required"}, 400)
            return
        book = cached(f"book:{token_id}", lambda: fetch_book(token_id))
        bids = [{"price": float(b["price"]), "size": float(b["size"])} for b in book.get("bids", [])]
        asks = [{"price": float(a["price"]), "size": float(a["size"])} for a in book.get("asks", [])]
        json_response(self, {
            "bids": bids, "asks": asks,
            "last_trade_price": book.get("last_trade_price"),
            "tick_size": book.get("tick_size"),
            "min_order_size": book.get("min_order_size"),
        })

    def _api_trades(self, q):
        cond = q.get("condition_id", [""])[0]
        limit = int(q.get("limit", ["100"])[0] or 100)
        if not cond:
            json_response(self, {"error": "condition_id required"}, 400)
            return
        trades = cached(f"trades:{cond}:{limit}", lambda: fetch_trades(cond, limit))
        out = [{
            "side": t.get("side"),
            "size": t.get("size"),
            "price": t.get("price"),
            "timestamp": t.get("timestamp"),
            "outcome": t.get("outcome"),
            "wallet": t.get("proxyWallet"),
            "pseudonym": t.get("pseudonym") or t.get("name") or "",
            "txHash": t.get("transactionHash"),
        } for t in trades]
        json_response(self, {"trades": out})

    def _api_traders(self, q):
        cond = q.get("condition_id", [""])[0]
        limit = int(q.get("limit", ["20"])[0] or 20)
        if not cond:
            json_response(self, {"error": "condition_id required"}, 400)
            return
        trades = cached(f"trades:{cond}:500", lambda: fetch_trades(cond, 500))
        top = aggregate_traders(trades, limit)
        json_response(self, {"traders": top})


def load_snapshot_from_file():
    """Мгновенная загрузка последнего снимка (если есть) — быстрый старт."""
    global SNAPSHOT
    snap = P.BASE_DIR / "polymarket_crypto_snapshot.json"
    if not snap.exists():
        return False
    try:
        with open(snap) as f:
            d = json.load(f)
        SNAPSHOT = {
            "markets": d.get("markets", []),
            "total": d.get("total_markets", len(d.get("markets", []))),
            "generated_at": d.get("generated_at"),
            "series_count": d.get("series_count", 0),
        }
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8844)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    fast = load_snapshot_from_file()
    if fast:
        print(f"Загружен снимок: {SNAPSHOT['total']} рынков (свежий парсится фоном)", flush=True)
    else:
        print("Парсю рынки при старте...", flush=True)
        rebuild_snapshot()
        print(f"Готово: {SNAPSHOT['total']} рынков, {SNAPSHOT['series_count']} серий", flush=True)
    # фоновый перепарс для свежих данных
    threading.Thread(target=lambda: (rebuild_snapshot(), print(f"Фоновый перепарс готов: {SNAPSHOT['total']} рынков", flush=True)),
                     daemon=True).start()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Дашборд: http://{args.host}:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
