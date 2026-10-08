"""
rank_strategies.py — прибыльные weather-стратегии, не certain-скупка.

Официальный PnL с lb-api. Только кошельки с weather_ratio ≥ порога.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from api import fetch_pnl
from collector import get_all_profiles, is_playbook_profile
from config import ROOT, WEATHER_MIN_RATIO, make_http_client

OUT_JSON = ROOT / "strategy_rank.json"
OUT_MD = ROOT / "strategy_rank.md"


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[len(s) // 2]


def rank_weather(*, playbook_only: bool = True, with_pnl: bool = True) -> dict:
    rows = get_all_profiles(weather_only=True)
    if playbook_only:
        rows = [p for p in rows if is_playbook_profile(p)]

    ranked = []
    http = make_http_client(timeout=20, headers={"User-Agent": "Mozilla/5.0"}) if with_pnl else None
    try:
        for i, p in enumerate(rows, 1):
            pnl = p.get("pnl")
            if with_pnl and pnl is None:
                pnl = fetch_pnl(p["wallet"], http=http)
            ranked.append({
                "wallet": p["wallet"],
                "name": p["name"],
                "strategy": p["strategy"],
                "weather_ratio": p["weather_ratio"],
                "top_city": p["top_city"],
                "city_concentration": p["city_concentration"],
                "median_entry": p["median_entry"],
                "buy_trades": p["buy_trades"],
                "ladder_ratio": p["ladder_ratio"],
                "pnl": pnl,
            })
            if with_pnl and i % 20 == 0:
                print(f"  pnl {i}/{len(rows)}", flush=True)
    finally:
        if http is not None:
            http.close()

    ranked.sort(key=lambda r: (r["pnl"] is not None, r["pnl"] or -1e18), reverse=True)

    by_strat: dict[str, list] = defaultdict(list)
    for r in ranked:
        by_strat[r["strategy"]].append(r)

    summary = []
    for strat, g in sorted(by_strat.items(), key=lambda kv: -len(kv[1])):
        pnls = [x["pnl"] for x in g if x["pnl"] is not None]
        pos = [x for x in pnls if x > 0]
        summary.append({
            "strategy": strat,
            "wallets": len(g),
            "median_pnl": round(_median(pnls), 2) if pnls else None,
            "sum_pnl": round(sum(pnls), 2) if pnls else None,
            "pct_profitable": round(100 * len(pos) / len(pnls), 1) if pnls else None,
            "median_entry": round(_median([float(x["median_entry"] or 0) for x in g]), 3),
        })

    payload = {
        "weather_min_ratio": WEATHER_MIN_RATIO,
        "playbook_only": playbook_only,
        "count": len(ranked),
        "by_strategy": summary,
        "wallets": ranked,
    }
    return payload


def format_rank(payload: dict, top: int = 25) -> str:
    lines = [
        f"# Weather strategies — {payload['count']} playbook wallets",
        "",
        f"Порог weather_ratio ≥ {payload['weather_min_ratio']}. "
        "Certain-скупка решённых рынков сюда не входит.",
        "",
        "## По стратегиям",
        "",
        "| strategy | n | median PnL | sum PnL | % profit | median entry |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for s in payload["by_strategy"]:
        lines.append(
            f"| {s['strategy']} | {s['wallets']} | {s['median_pnl']} | "
            f"{s['sum_pnl']} | {s['pct_profitable']} | {s['median_entry']} |"
        )
    lines += ["", "## Топ по официальному PnL", ""]
    for r in payload["wallets"][:top]:
        pnl = "n/a" if r["pnl"] is None else f"${r['pnl']:,.0f}"
        lines.append(
            f"- **{r['name']}** [{r['strategy']}] {r['top_city']} "
            f"weather={r['weather_ratio']} conc={r['city_concentration']} "
            f"entry={r['median_entry']} PnL {pnl}"
        )
    return "\n".join(lines) + "\n"


def write_rank(payload: dict) -> None:
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(format_rank(payload), encoding="utf-8")
