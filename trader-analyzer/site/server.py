#!/usr/bin/env python3
"""
server.py — автономный FastAPI-бэкенд для сайта trader-analyzer.
Читает profiles.db напрямую (sqlite3), без внешних зависимостей проекта.

Запуск:
    /Users/alexander/agents-env/bin/python3 server.py
    (порт 8770, uvicorn)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "profiles.db"
STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Polymarket Trader Analyzer")

# Подключаем статику (index.html, styles.css, app.js)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


STRATEGY_ORDER = [
    "ladder", "longshot", "certain", "value", "momentum",
    "specialist", "mixed", "unknown",
]

SORTABLE = {
    "pnl": "pnl",
    "name": "name",
    "strategy": "strategy",
    "trades_30d": "trades_30d",
    "trades_per_month": "trades_per_month",
    "volume_30d": "volume_30d",
    "weather_ratio": "weather_ratio",
    "median_entry": "median_entry",
    "city_concentration": "city_concentration",
    "total_trades": "total_trades",
    "active_days_30d": "active_days_30d",
    "updated_at": "updated_at",
    "last_trade_at": "last_trade_at",
}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta():
    conn = _connect()
    try:
        strategies = [
            r["strategy"] for r in conn.execute(
                "SELECT strategy FROM profiles WHERE strategy IS NOT NULL "
                "GROUP BY strategy ORDER BY COUNT(*) DESC"
            )
        ]
        cities = [
            r["top_city"] for r in conn.execute(
                "SELECT top_city FROM profiles WHERE top_city IS NOT NULL "
                "AND top_city != '' GROUP BY top_city ORDER BY COUNT(*) DESC LIMIT 60"
            )
        ]
        topics = [
            r["top_topic"] for r in conn.execute(
                "SELECT top_topic FROM profiles WHERE top_topic IS NOT NULL "
                "AND top_topic != '' GROUP BY top_topic ORDER BY COUNT(*) DESC LIMIT 30"
            )
        ]
    finally:
        conn.close()
    return {"strategies": strategies, "cities": cities, "topics": topics}


@app.get("/api/stats")
def stats():
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]

        by_strategy = []
        for r in conn.execute(
            """
            SELECT strategy,
                   COUNT(*) AS n,
                   ROUND(COALESCE(SUM(pnl),0),1) AS sum_pnl,
                   ROUND(AVG(pnl),1) AS avg_pnl,
                   SUM(pnl IS NOT NULL AND pnl > 0) AS winners,
                   SUM(pnl IS NOT NULL AND pnl <= 0) AS losers
            FROM profiles
            WHERE strategy IS NOT NULL
            GROUP BY strategy
            """
        ):
            winners = r["winners"] or 0
            losers = r["losers"] or 0
            total_pnl = winners + losers
            profit_pct = round(100 * winners / total_pnl, 1) if total_pnl else 0
            by_strategy.append({
                "strategy": r["strategy"],
                "n": r["n"],
                "sum_pnl": r["sum_pnl"],
                "avg_pnl": r["avg_pnl"],
                "profit_pct": profit_pct,
            })
        # сортировка в каноническом порядке
        by_strategy.sort(key=lambda x: STRATEGY_ORDER.index(x["strategy"])
                         if x["strategy"] in STRATEGY_ORDER else 99)

        total_pnl = conn.execute(
            "SELECT ROUND(COALESCE(SUM(pnl),0),1) FROM profiles"
        ).fetchone()[0]

        playbook = conn.execute(
            "SELECT COUNT(*) FROM profiles WHERE playbook = 1"
        ).fetchone()[0]

        win_w, lose_w = conn.execute(
            "SELECT SUM(pnl IS NOT NULL AND pnl > 0), "
            "SUM(pnl IS NOT NULL AND pnl <= 0) FROM profiles"
        ).fetchone()
        win_w, lose_w = win_w or 0, lose_w or 0
        winrate = round(win_w / (win_w + lose_w), 3) if (win_w + lose_w) else 0

        top_cities = [
            {"city": r["city"], "n": r["n"], "sum_pnl": round(r["sum_pnl"] or 0, 1)}
            for r in conn.execute(
                """
                SELECT top_city AS city, COUNT(*) AS n,
                       ROUND(SUM(pnl),1) AS sum_pnl
                FROM profiles WHERE top_city IS NOT NULL AND top_city != ''
                GROUP BY top_city ORDER BY SUM(pnl) DESC LIMIT 10
                """
            )
        ]

        top_topics = [
            {"topic": r["top_topic"], "n": r["n"]}
            for r in conn.execute(
                """
                SELECT top_topic, COUNT(*) AS n
                FROM profiles WHERE top_topic IS NOT NULL AND top_topic != ''
                GROUP BY top_topic ORDER BY COUNT(*) DESC LIMIT 8
                """
            )
        ]

        top_wallets = [
            dict(r) for r in conn.execute(
                """
                SELECT wallet, name, strategy, ROUND(pnl,1) AS pnl,
                       total_trades, top_city, weather_ratio
                FROM profiles
                WHERE pnl IS NOT NULL
                ORDER BY pnl DESC LIMIT 12
                """
            )
        ]
        for w in top_wallets:
            w["wallet"] = w["wallet"][:10] + "…" + w["wallet"][-6:]

        # распределение PnL по бакетам (лог-шкала) для гистограммы
        dist_order = ["< $0", "$0–100", "$100–1K", "$1K–10K", "$10K–100K", "$100K+"]
        pnl_dist = {
            r["bucket"]: r["n"]
            for r in conn.execute(
                """
                SELECT CASE
                    WHEN pnl < 0 THEN '< $0'
                    WHEN pnl < 100 THEN '$0–100'
                    WHEN pnl < 1000 THEN '$100–1K'
                    WHEN pnl < 10000 THEN '$1K–10K'
                    WHEN pnl < 100000 THEN '$10K–100K'
                    ELSE '$100K+'
                END AS bucket, COUNT(*) AS n
                FROM profiles WHERE pnl IS NOT NULL GROUP BY bucket
                """
            )
        }
        pnl_dist = [{"bucket": b, "n": pnl_dist.get(b, 0)} for b in dist_order]

    finally:
        conn.close()

    return {
        "total": total,
        "total_pnl": total_pnl,
        "playbook": playbook,
        "winrate": winrate,
        "by_strategy": by_strategy,
        "top_cities": top_cities,
        "top_topics": top_topics,
        "top_wallets": top_wallets,
        "pnl_dist": pnl_dist,
    }


@app.get("/api/wallets")
def wallets(
    strategy: str | None = None,
    city: str | None = None,
    topic: str | None = None,
    q: str | None = None,
    min_pnl: float | None = None,
    playbook: bool | None = None,
    sort: str = "pnl",
    desc: bool = True,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = _connect()
    where: list[str] = []
    args: list = []

    if strategy:
        names = [s.strip() for s in strategy.split(",") if s.strip()]
        if names:
            where.append("(" + " OR ".join("strategy = ?" for _ in names) + ")")
            args.extend(names)
    if city:
        where.append("LOWER(COALESCE(top_city,'')) LIKE ?")
        args.append(f"%{city.lower()}%")
    if topic:
        where.append("top_topic = ?")
        args.append(topic)
    if q:
        where.append("(LOWER(COALESCE(name,'')) LIKE ? OR LOWER(wallet) LIKE ?)")
        like = f"%{q.lower()}%"
        args.extend([like, like])
    if min_pnl is not None:
        where.append("pnl IS NOT NULL AND pnl >= ?")
        args.append(min_pnl)
    if playbook is True:
        where.append("playbook = 1")
    elif playbook is False:
        where.append("(playbook = 0 OR playbook IS NULL)")

    order_col = SORTABLE.get(sort, "pnl")
    direction = "DESC" if desc else "ASC"

    try:
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            "SELECT COUNT(*) FROM profiles" + where_sql, args
        ).fetchone()[0]

        sql = (
            "SELECT * FROM profiles" + where_sql +
            f" ORDER BY {order_col} {direction} NULLS LAST, wallet ASC "
            "LIMIT ? OFFSET ?"
        )
        rows = conn.execute(sql, args + [limit, offset]).fetchall()
    except Exception:
        # старый sqlite без NULLS LAST
        sql = (
            "SELECT * FROM profiles" + where_sql +
            f" ORDER BY {order_col} {direction}, wallet ASC LIMIT ? OFFSET ?"
        )
        rows = conn.execute(sql, args + [limit, offset]).fetchall()
    finally:
        pass

    result = [dict(r) for r in rows]
    conn.close()

    for r in result:
        # короткие адреса для отображения
        w = r.get("wallet") or ""
        r["wallet_short"] = (w[:10] + "…" + w[-6:]) if len(w) > 18 else w
        for k in ("pnl", "median_entry", "volume_30d", "trades_per_month",
                  "weather_ratio", "city_concentration", "topic_concentration",
                  "ladder_ratio", "longshot_ratio", "certain_ratio"):
            v = r.get(k)
            r[k] = round(v, 2) if isinstance(v, (int, float)) else v

    return {"total": total, "items": result, "limit": limit, "offset": offset}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")
