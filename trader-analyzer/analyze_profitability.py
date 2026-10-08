"""
analyze_profitability.py — прибыльность/риск по стратегиям и городам.

Для каждого кошелька: официальный PnL (lb-api) + метрики из profiles.db.
Группировка по стратегиям и городам → прибыльность, ROI, рискованность, размер, активность.
"""
import sqlite3, json, math, time
from collections import defaultdict

from config import DB_PATH, make_http_client

HTTP = make_http_client(timeout=20, headers={'User-Agent': 'Mozilla/5.0'})

DB = str(DB_PATH)

def get_pnl(wallet):
    """Официальный total PnL из lb-api."""
    try:
        r = HTTP.get(f"https://lb-api.polymarket.com/profit?address={wallet}")
        d = r.json()
        # структура: список или dict с полем pnl/profit
        if isinstance(d, list) and d:
            d = d[0]
        for k in ('pnl', 'profit', 'realizedPnl', 'amount'):
            if k in d and d[k] is not None:
                return float(d[k])
        # может быть nested
        return None
    except Exception:
        return None

def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute("""
        SELECT wallet, name, strategy, weather_ratio, top_city, median_entry,
               total_trades, ladder_ratio, longshot_ratio, certain_ratio
        FROM profiles
    """).fetchall()
    conn.close()

    print(f"Всего кошельков: {len(rows)}")

    data = []
    for i, (w, name, strat, wr, city, med, trades, lr, sr, cr) in enumerate(rows, 1):
        pnl = get_pnl(w)
        data.append({
            'wallet': w, 'name': name, 'strategy': strat, 'wr': wr, 'city': city,
            'median': med, 'trades': trades or 0, 'pnl': pnl,
            'ladder': lr or 0, 'longshot': sr or 0, 'certain': cr or 0,
        })
        if i % 15 == 0:
            print(f"  ...PnL получен для {i}/{len(rows)}")
            time.sleep(0.3)

    json.dump(data, open('/tmp/profitability_data.json', 'w'))

    # === Агрегация по стратегиям ===
    print(f"\n{'='*80}")
    print("АНАЛИЗ ПО СТРАТЕГИЯМ")
    print(f"{'='*80}")

    strats = defaultdict(list)
    for d in data:
        strats[d['strategy']].append(d)

    def median(lst):
        if not lst: return 0
        s = sorted(lst)
        return s[len(s)//2]

    print(f"\n{'стратегия':12s} {'кош':>3s} {'медиан.PnL':>10s} {'сумм.PnL':>11s} {'%приб':>6s} {'мед.вход':>8s} {'мед.сделок':>9s}")
    print("-"*72)
    for s in ['ladder', 'certain', 'mixed', 'unknown']:
        g = strats.get(s, [])
        if not g: continue
        pnls = [d['pnl'] for d in g if d['pnl'] is not None]
        profit = [p for p in pnls if p > 0]
        pct = len(profit)/len(pnls)*100 if pnls else 0
        print(f"{s:12s} {len(g):>3d} {median(pnls):>10,.0f} {sum(pnls):>11,.0f} {pct:>5.0f}% "
              f"{median([d['median'] or 0 for d in g]):>8.3f} {median([d['trades'] for d in g]):>9d}")

    # === Агрегация по городам ===
    print(f"\n{'='*80}")
    print("АНАЛИЗ ПО ГОРОДАМ (топ по числу кошельков)")
    print(f"{'='*80}")

    cities = defaultdict(list)
    for d in data:
        if d['city'] and d['city'] != '?':
            cities[d['city']].append(d)

    print(f"\n{'город':16s} {'кош':>3s} {'медиан.PnL':>10s} {'сумм.PnL':>11s} {'%приб':>6s} {'мед.вход':>8s} {'мед.сделок':>9s}")
    print("-"*76)
    for city, g in sorted(cities.items(), key=lambda x: -len(x[1])):
        pnls = [d['pnl'] for d in g if d['pnl'] is not None]
        profit = [p for p in pnls if p > 0]
        pct = len(profit)/len(pnls)*100 if pnls else 0
        print(f"{city:16s} {len(g):>3d} {median(pnls):>10,.0f} {sum(pnls):>11,.0f} {pct:>5.0f}% "
              f"{median([d['median'] or 0 for d in g]):>8.3f} {median([d['trades'] for d in g]):>9d}")

    print("\nГотово. Данные в /tmp/profitability_data.json")

if __name__ == '__main__':
    main()
