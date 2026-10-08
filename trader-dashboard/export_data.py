#!/usr/bin/env python3
"""Экспорт реальных данных trader-analyzer в data.json для дашборда."""
import json, sqlite3, sys, os

BASE = "/Users/alexander/projects/polymarket/trader-analyzer"
DB = os.path.join(BASE, "profiles.db")
RANK = os.path.join(BASE, "strategy_rank.json")
OUT = "/Users/alexander/projects/polymarket/trader-dashboard/data.json"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT * FROM profiles").fetchall()

COLS = ["wallet","name","strategy","ladder_ratio","longshot_ratio","certain_ratio",
        "weather_ratio","median_entry","top_city","city_concentration","cities_json",
        "total_trades","buy_trades","pnl","last_trade_at","first_trade_at",
        "trades_30d","buys_30d","volume_30d","active_days_30d","trades_per_month",
        "period_days","playbook"]

wallets = []
for r in rows:
    w = {c: r[c] for c in COLS if c in r.keys()}
    # cities_json -> список для удобства
    try:
        w["cities"] = json.loads(r["cities_json"]) if r["cities_json"] else {}
    except Exception:
        w["cities"] = {}
    w.pop("cities_json", None)
    wallets.append(w)

# распределение стратегий (реальное из БД)
strat_counts = {}
for w in wallets:
    s = (w["strategy"] or "unknown")
    strat_counts[s] = strat_counts.get(s, 0) + 1
strategies = [{"k": k, "n": strat_counts[k]} for k in sorted(strat_counts, key=lambda x: -strat_counts[x])]

# реальный ранг стратегий
rank = {}
try:
    rank = json.load(open(RANK))
except Exception as e:
    rank = {"error": str(e)}

weather_count = sum(1 for w in wallets if (w.get("weather_ratio") or 0) >= 0.3)

data = {
    "generated_at": __import__("datetime").datetime.now().isoformat(),
    "totals": {
        "wallets": len(wallets),
        "weather": weather_count,
        "threshold": 0.3,
        "strategies": len(strategies),
    },
    "strategies": strategies,
    "strategy_rank": rank,
    "wallets": wallets,
}

with open(OUT, "w") as f:
    json.dump(data, f, ensure_ascii=False)

print(f"OK: {len(wallets)} кошельков, {len(strategies)} стратегий, weather={weather_count}")
print(f"-> {OUT} ({os.path.getsize(OUT)//1024} KB)")
