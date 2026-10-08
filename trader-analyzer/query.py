"""
query.py — фильтр профилей в SQLite (PnL, активность, стратегия, город).
"""

from __future__ import annotations

from typing import Any

from collector import _connect, _profile_columns
from config import WEATHER_MIN_RATIO

SORTABLE = {
    "pnl": "pnl",
    "trades_30d": "trades_30d",
    "trades_per_month": "trades_per_month",
    "volume_30d": "volume_30d",
    "weather_ratio": "weather_ratio",
    "median_entry": "median_entry",
    "city_concentration": "city_concentration",
    "topic_concentration": "topic_concentration",
    "buy_trades": "buy_trades",
    "updated_at": "updated_at",
    "last_trade_at": "last_trade_at",
    "active_days_30d": "active_days_30d",
}


def query_profiles(
    *,
    weather_only: bool = True,
    strategy: str | None = None,
    city: str | None = None,
    topic: str | None = None,
    min_pnl: float | None = None,
    max_pnl: float | None = None,
    min_month: float | None = None,
    min_trades_30d: int | None = None,
    min_volume_30d: float | None = None,
    min_active_days: int | None = None,
    min_weather: float | None = None,
    max_weather: float | None = None,
    min_entry: float | None = None,
    max_entry: float | None = None,
    min_conc: float | None = None,
    playbook: bool | None = None,
    sort: str = "pnl",
    desc: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    cols = _profile_columns()
    where: list[str] = []
    args: list[Any] = []

    wr = WEATHER_MIN_RATIO if min_weather is None and weather_only else min_weather
    if wr is not None:
        where.append("weather_ratio >= ?")
        args.append(wr)
    if max_weather is not None:
        where.append("weather_ratio <= ?")
        args.append(max_weather)
    if strategy:
        names = [s.strip() for s in strategy.split(",") if s.strip()]
        if names:
            where.append("(" + " OR ".join("strategy = ?" for _ in names) + ")")
            args.extend(names)
    if city:
        where.append("LOWER(COALESCE(top_city,'')) LIKE ?")
        args.append(f"%{city.lower()}%")
    if topic:
        names = [t.strip() for t in topic.split(",") if t.strip()]
        if names:
            where.append("(" + " OR ".join("top_topic = ?" for _ in names) + ")")
            args.extend(names)
    if min_pnl is not None:
        where.append("pnl IS NOT NULL AND pnl >= ?")
        args.append(min_pnl)
    if max_pnl is not None:
        where.append("pnl IS NOT NULL AND pnl <= ?")
        args.append(max_pnl)
    if min_month is not None:
        where.append("trades_per_month >= ?")
        args.append(min_month)
    if min_trades_30d is not None:
        where.append("trades_30d >= ?")
        args.append(min_trades_30d)
    if min_volume_30d is not None:
        where.append("volume_30d >= ?")
        args.append(min_volume_30d)
    if min_active_days is not None:
        where.append("active_days_30d >= ?")
        args.append(min_active_days)
    if min_entry is not None:
        where.append("median_entry >= ?")
        args.append(min_entry)
    if max_entry is not None:
        where.append("median_entry <= ?")
        args.append(max_entry)
    if min_conc is not None:
        where.append("city_concentration >= ?")
        args.append(min_conc)
    if playbook is True:
        where.append("playbook = 1")
    elif playbook is False:
        where.append("(playbook = 0 OR playbook IS NULL)")

    order_col = SORTABLE.get(sort, "pnl")
    direction = "DESC" if desc else "ASC"
    nulls = "NULLS LAST"
    sql = "SELECT * FROM profiles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY {order_col} {direction} {nulls}, wallet ASC"
    if limit and limit > 0:
        sql += " LIMIT ?"
        args.append(int(limit))

    conn = _connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    except Exception:
        # older sqlite without NULLS LAST
        sql = sql.replace(" NULLS LAST", "")
        rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]
