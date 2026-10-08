"""
portrait.py — полный «портрет» кошелька Polymarket.

Собирает в один словарь всё, что тул знает о кошельке:
  - стратегию (classifier.classify_wallet)
  - темы/разделы сделок (topic)
  - on-chain выводы USDC/ETH (onchain)
  - активность и полную историю сделок (metrics + api)

CLI-команда `portrait` рендерит этот словарь в человекочитаемый отчёт.
Чистая по данным: если trades/activity не переданы — тянет их из сети.
"""

from __future__ import annotations

from classifier import classify_wallet
from metrics import activity_stats, trade_ts
from onchain import withdrawal_stats
from topic import classify_topic, topic_distribution, top_topic


def normalize_trade(t: dict) -> dict:
    """Компактная нормализованная запись сделки для истории в портрете."""
    title = t.get("title") or t.get("question") or ""
    outcome = t.get("outcome") or t.get("name") or ""
    ts = trade_ts(t)
    return {
        "side": t.get("side"),
        "price": t.get("price"),
        "size": t.get("size"),
        "title": str(title),
        "outcome": str(outcome),
        "topic": classify_topic(str(title), str(outcome)),
        "conditionId": t.get("conditionId") or t.get("market"),
        "timestamp": ts or None,
    }


def _trades_window(trades: list[dict]) -> dict:
    stamps = sorted(s for s in (trade_ts(t) for t in trades) if s > 0)
    return {
        "from": stamps[0] if stamps else None,
        "to": stamps[-1] if stamps else None,
        "count": len(trades),
        "truncated": False,
        "source": "provided",
    }


def build_portrait(
    wallet: str,
    name: str | None = None,
    *,
    trades: list[dict] | None = None,
    activity: list[dict] | None = None,
    pnl: float | None = None,
    max_trades: int = 1000,
) -> dict:
    """Собирает полный портрет кошелька (MVP §8).

    live-режим (trades=None): история через `api.get_all_trades_full` (с window
    метаданными и честным `truncated`), PnL через `api.fetch_pnl`, on-chain
    через `onchain.flow_wallet` (kill-switch). Оффлайн (trades переданы) — без
    сети: on-chain срез строится из переданной ленты `activity`.
    """
    live = trades is None
    if live:
        from api import get_all_trades_full, fetch_pnl as _fetch_pnl
        full = get_all_trades_full(wallet, safety_cap=max_trades)
        trades = full["trades"]
        window = full["window"]
        if pnl is None:
            pnl = _fetch_pnl(wallet)
    else:
        window = _trades_window(trades or [])
    if activity is None:
        activity = []

    profile = classify_wallet(trades or [])
    topics = topic_distribution(trades or [])
    act = activity_stats(trades or [])
    history = [normalize_trade(t) for t in (trades or [])]

    # on-chain срез: live — сеть (kill-switch), оффлайн — из переданной ленты.
    if live:
        from onchain import flow_wallet
        chain = flow_wallet(wallet)
    elif activity:
        from onchain import flow
        chain = {
            "enabled": True,
            "flow": flow(activity),
            "reconcile": None,
            "empty": False,
            "source": "provided",
        }
    else:
        chain = {"enabled": False, "reason": "offline build (no live source)"}

    return {
        "wallet": wallet,
        "name": name or profile.get("top_city") or "unknown",
        "strategy": profile["strategy"],
        "pnl": pnl,
        # темы
        "topics": topics,
        "top_topic": top_topic(trades or []),
        # окно истории + честный truncated-флаг (MVP §7)
        "window": window,
        "truncated": bool(window.get("truncated")),
        # стратегия (признаки из classifier)
        "profile": {
            "ladder_ratio": profile["ladder_ratio"],
            "longshot_ratio": profile["longshot_ratio"],
            "certain_ratio": profile["certain_ratio"],
            "weather_ratio": profile["weather_ratio"],
            "median_entry": profile["median_entry"],
            "avg_entry": profile["avg_entry"],
            "top_city": profile["top_city"],
            "city_concentration": profile["city_concentration"],
            "buy_trades": profile["buy_trades"],
            "total_trades": profile["total_trades"],
        },
        # on-chain выводы (с kill-switch) + сводка выводов
        "onchain": chain,
        "withdrawals": withdrawal_stats(activity),
        # активность
        "activity": act,
        # полная история сделок
        "history": history,
        "history_count": len(history),
    }
