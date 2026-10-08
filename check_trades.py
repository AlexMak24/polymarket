import json, os, glob
from datetime import datetime, timezone

BASE = "/Users/alexander/projects/polymarket/strategies/weather/data"

# 1. trade_journal — зарезолвившиеся
journal = json.load(open(f"{BASE}/trade_journal.json"))
print(f"=== ЖУРНАЛ (зарезолвившиеся): {len(journal)} сделок ===")
for t in journal:
    d = t.get('resolved_at','')[:10]
    pnl = t.get('pnl', 0)
    mark = "✅ WIN" if t.get('won') else "❌ LOSS"
    print(f"  {t.get('city','?'):12s} {t.get('date','?'):12s} резолв {d} | {mark} {pnl:+.2f}$ | {t.get('source','?')}")

# 2. markets — открытые позиции
print("\n=== ОТКРЫТЫЕ ПОЗИЦИИ (markets/*.json) ===")
open_pos = []
for f in sorted(glob.glob(f"{BASE}/markets/*.json")):
    try:
        m = json.load(open(f))
    except:
        continue
    pos = m.get("position")
    if pos and pos.get("status") in ("open", "pending", "partial", None):
        open_pos.append({
            "city": m.get("city","?"),
            "date": m.get("date","?"),
            "side": pos.get("side","?"),
            "price": pos.get("entry_price",0),
            "shares": pos.get("shares",0),
            "cost": pos.get("cost",0),
            "status": pos.get("status","?"),
        })

print(f"Всего открытых: {len(open_pos)}")
for p in sorted(open_pos, key=lambda x: x['date']):
    print(f"  {p['city']:14s} {p['date']:12s} {p['side']:3s} @ {p['price']:.2f} x{p['shares']} (${p['cost']:.2f}) [{p['status']}]")

# 3. суммарный PnL журнала
total_pnl = sum(t.get('pnl',0) for t in journal)
wins = sum(1 for t in journal if t.get('won'))
losses = sum(1 for t in journal if not t.get('won'))
print(f"\n=== ИТОГО (журнал): {len(journal)} сделок, {wins} win / {losses} loss, PnL {total_pnl:+.2f}$ ===")
