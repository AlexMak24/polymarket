"""
recommend.py — рекомендации для weather-бота.

Из свежих лестниц топ-трейдеров: город, бакеты, корзина.
Не меняет код бота — только текст/JSON.
"""

from __future__ import annotations

from datetime import datetime, timezone

from api import get_all_trades
from city_parser import parse_trade
from classifier import detect_ladders
from config import SIGNAL_RECENCY_HOURS
from metrics import trade_ts


def filter_recent(trades: list[dict], hours: int | None = None) -> list[dict]:
    window = SIGNAL_RECENCY_HOURS if hours is None else hours
    if window <= 0:
        return trades
    cutoff = datetime.now(timezone.utc).timestamp() - window * 3600
    return [t for t in trades if trade_ts(t) >= cutoff]


def recommend_from_ladder_traders(
    max_trades: int = 300,
    hours: int | None = None,
) -> list[dict]:
    """
    Свежие лестницы у ladder-трейдеров.
    hours=None → SIGNAL_RECENCY_HOURS; hours=0 → без фильтра.
    """
    from collector import get_all_profiles

    profiles = get_all_profiles(weather_only=True)
    recs = []
    window = SIGNAL_RECENCY_HOURS if hours is None else hours

    for p in profiles:
        if p["strategy"] != "ladder":
            continue
        trades = get_all_trades(p["wallet"], max_trades=max_trades)
        recent = filter_recent(trades, hours=window)
        source = recent if recent else trades
        ladders = detect_ladders(source, min_buckets=3)

        for key, l in ladders.items():
            prices = []
            last_ts = 0.0
            for t in source:
                if t.get("side") != "BUY":
                    continue
                info = parse_trade(t)
                unit = info.get("unit") or "C"
                if (info["city"], info["date"], info["type"], unit) == key:
                    prices.append(float(t.get("price") or 0))
                    last_ts = max(last_ts, trade_ts(t))
            avg_price = sum(prices) / len(prices) if prices else 0
            recs.append({
                "trader": p["name"],
                "wallet": p["wallet"],
                "city": l["city"],
                "date": l["date"],
                "type": l["type"],
                "degrees": l["degrees"],
                "run": l["run"],
                "buckets": len(l["degrees"]),
                "avg_price": round(avg_price, 3),
                "last_trade_ts": last_ts,
                "from_recent_window": bool(recent),
            })

    recs.sort(key=lambda r: r.get("last_trade_ts") or 0, reverse=True)
    return recs


def format_recommendations(recs: list[dict], hours: int | None = None) -> str:
    window = SIGNAL_RECENCY_HOURS if hours is None else hours
    if not recs:
        if window > 0:
            return (
                f"Нет лестниц за последние {window}ч. "
                "Расширь окно: `python cli.py recommend --hours 0`."
            )
        return "Нет лестниц у лестничных трейдеров."

    lines = [f"## Рекомендации для weather-бота (лестницы, окно {window}ч)\n"]
    for r in recs:
        degs = "-".join(str(d) for d in r["degrees"])
        stale = "" if r.get("from_recent_window") else " · без свежих сделок, по всей истории"
        lines.append(
            f"- **{r['city']}** ({r['date']}, {r['type']}): "
            f"корзина {degs}° = {r['buckets']} бакетов, "
            f"средняя цена входа ~${r['avg_price']} "
            f"({r['trader']}){stale}"
        )
    lines.append(
        "\n> Как применить: вместо одиночной ставки на 1 градус — "
        "ставить корзину из соседних бакетов (как топ-трейдеры)."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    recs = recommend_from_ladder_traders()
    print(format_recommendations(recs))
