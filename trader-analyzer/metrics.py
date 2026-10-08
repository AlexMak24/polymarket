"""
metrics.py — активность и timestamps сделок.
"""

from __future__ import annotations

from datetime import datetime, timezone


def trade_ts(t: dict) -> float:
    raw = t.get("timestamp") or t.get("ts") or 0
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:
            ts /= 1000.0
        return ts
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _iso(ts: float) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def activity_stats(trades: list[dict], window_days: int = 30) -> dict:
    """Считает активность за окно и нормализованные сделки/месяц."""
    stamps = [trade_ts(t) for t in trades]
    stamps = [s for s in stamps if s > 0]
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window_days * 86400

    recent = []
    for t, ts in zip(trades, [trade_ts(x) for x in trades]):
        if ts >= cutoff:
            recent.append((t, ts))

    buys_30d = 0
    volume_30d = 0.0
    days = set()
    for t, ts in recent:
        days.add(int(ts // 86400))
        if t.get("side") == "BUY":
            buys_30d += 1
        size = float(t.get("size") or 0)
        price = float(t.get("price") or 0)
        volume_30d += size * price

    first_ts = min(stamps) if stamps else 0.0
    last_ts = max(stamps) if stamps else 0.0
    period_days = (last_ts - first_ts) / 86400 if last_ts > first_ts else 0.0
    trades_30d = len(recent)
    if period_days >= 1:
        trades_per_month = len(trades) / period_days * 30.0
    else:
        trades_per_month = float(trades_30d)

    return {
        "last_trade_at": _iso(last_ts),
        "first_trade_at": _iso(first_ts),
        "trades_30d": trades_30d,
        "buys_30d": buys_30d,
        "volume_30d": round(volume_30d, 2),
        "active_days_30d": len(days),
        "trades_per_month": round(trades_per_month, 1),
        "period_days": round(period_days, 1),
    }
