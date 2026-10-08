import json, glob

# hrrr-metar: открытые позиции в markets/
print("=== hrrr-metar: открытые позиции ===")
hrrr_markets = "/Users/alexander/projects/polymarket/strategies/hrrr-metar/data/markets"
open_pos = []
for f in sorted(glob.glob(f"{hrrr_markets}/*.json")):
    try:
        m = json.load(open(f))
    except:
        continue
    # разные структуры — ищем поле позиции/состояния
    pos = m.get("position") or m.get("state") or {}
    if isinstance(pos, dict):
        st = pos.get("status") or pos.get("state") or m.get("status")
        if st in ("open", "pending", "partial", None, "active"):
            open_pos.append((m.get("city") or m.get("location") or f.split('/')[-1], 
                             m.get("date","?"), pos.get("side","?"), 
                             pos.get("entry_price", pos.get("price",0)),
                             pos.get("shares",0), st))
    else:
        # попробовать top-level статус
        st = m.get("status")
        if st in ("open", "pending", "active", None):
            open_pos.append((m.get("city","?"), m.get("date","?"), m.get("side","?"),
                             m.get("entry_price", m.get("price",0)), m.get("shares",0), st))

print(f"Открытых: {len(open_pos)}")
for p in open_pos[:30]:
    print("  ", p)

# balles-edge: портфель
print("\n=== balles-edge: paper_portfolio ===")
d = json.load(open('/Users/alexander/projects/polymarket/strategies/balles-edge/data/paper_portfolio_weather.json'))
print('Тип:', type(d).__name__)
if isinstance(d, dict):
    keys = list(d.keys())
    print('Ключи:', keys[:30])
    # найти список сделок
    for k in keys:
        v = d[k]
        if isinstance(v, list) and v:
            print(f'\n  [список] {k}: {len(v)} элементов, первый:', json.dumps(v[0], ensure_ascii=False)[:250])
elif isinstance(d, list):
    print('len:', len(d))
    if d:
        print('первый:', json.dumps(d[0], ensure_ascii=False)[:300])
        print('последний:', json.dumps(d[-1], ensure_ascii=False)[:300])
