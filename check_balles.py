import json, glob
from datetime import datetime

# ===== balles-edge =====
print("=== balles-edge (paper) ===")
d = json.load(open('/Users/alexander/projects/polymarket/strategies/balles-edge/data/paper_portfolio_weather.json'))
print(f"  bankroll: {d.get('bankroll')} / initial {d.get('initial_bankroll')}")
print(f"  total_pnl: {d.get('total_pnl')}")
print(f"  n_won={d.get('n_won')} n_lost={d.get('n_lost')} n_expired={d.get('n_expired')}")
print(f"  last_updated: {d.get('last_updated')}")
print(f"  открытых позиций: {len(d.get('positions',[]))}")
for p in d.get('positions',[]):
    print(f"    {p.get('event_date')} {p.get('series_slug','')} {p.get('temp_str','')} @ {p.get('entry_price')}")

# последние закрытые сделки (по дате)
ct = d.get('closed_trades', [])
# поля резолва — ищем resolved/closed/date
print(f"\n  closed_trades всего: {len(ct)}")
# последние 12
recent = ct[-12:]
for t in recent:
    ed = t.get('event_date','?')
    res = t.get('resolved_at') or t.get('closed_at') or t.get('resolved') or '?'
    pnl = t.get('pnl') or t.get('realized_pnl') or t.get('profit') or '?'
    print(f"    {ed} | {t.get('series_slug','')[:20]} {t.get('temp_str','')} | pnl={pnl} | {str(res)[:19]}")
