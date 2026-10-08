"""
deep_analyze_unknown.py — глубокий разбор unknown-кошельков.

Для каждого unknown: полные сделки (до 1000) → точный паттерн:
  - ценовая гистограмма входа
  - лестницы (соседние градусы одного города+даты+типа)
  - города и концентрация
  - период активности (первая-последняя сделка)
  - число бакетов на группу (лестница vs одиночные)
Результат → profiles.db поле + JSON-отчёт.
"""
import sqlite3, json, re
from collections import defaultdict, Counter
from datetime import datetime
from api import get_all_trades
from classifier import detect_ladders
from city_parser import parse_trade
from config import DB_PATH

DB = str(DB_PATH)

def deep_profile(wallet):
    trades = get_all_trades(wallet, max_trades=1000)
    buys = [t for t in trades if t.get('side') == 'BUY']
    if not buys:
        return {'wallet': wallet, 'buys': 0, 'note': 'no buys'}

    prices = [t.get('price', 0) or 0 for t in buys]

    # гистограмма цен
    hist = {'<1¢': 0, '1-10¢': 0, '10-25¢': 0, '25-50¢': 0, '50-85¢': 0, '>85¢': 0}
    for p in prices:
        if p < 0.01: hist['<1¢'] += 1
        elif p < 0.10: hist['1-10¢'] += 1
        elif p < 0.25: hist['10-25¢'] += 1
        elif p < 0.50: hist['25-50¢'] += 1
        elif p < 0.85: hist['50-85¢'] += 1
        else: hist['>85¢'] += 1

    # города
    cities = Counter()
    temp = 0
    for t in buys:
        info = parse_trade(t)
        if info['kind'] == 'temperature': temp += 1
        if info['city']: cities[info['city']] += 1

    # лестницы
    ladders = detect_ladders(trades)
    ladder_trades = sum(l['trades'] for l in ladders.values())
    max_run = max([l['run'] for l in ladders.values()], default=0)

    # период активности (по timestamps)
    ts = [t.get('timestamp') or t.get('ts') or '' for t in trades]
    ts = [x for x in ts if x]
    period_days = None
    if ts:
        try:
            dts = [datetime.fromisoformat(str(x).replace('Z','+00:00')) for x in ts]
            period_days = (max(dts) - min(dts)).days
        except:
            period_days = None

    # медиана
    ps = sorted(prices)
    median = ps[len(ps)//2] if ps else 0

    # доминирующий паттерн
    n_buys = len(buys)
    ladder_ratio = ladder_trades / n_buys
    cheap_ratio = (hist['<1¢'] + hist['1-10¢']) / n_buys
    high_ratio = hist['>85¢'] / n_buys

    if ladder_ratio >= 0.5:
        pattern = 'ladder'
    elif cheap_ratio >= 0.5:
        pattern = 'longshot'
    elif high_ratio >= 0.5:
        pattern = 'certain'
    elif max_run >= 2:
        pattern = 'semi-ladder'
    else:
        pattern = 'scattered'  # разрозненные одиночные бакеты

    return {
        'wallet': wallet, 'buys': n_buys,
        'median': round(median, 3),
        'hist': hist,
        'cities': dict(cities.most_common(6)),
        'top_city': cities.most_common(1)[0][0] if cities else None,
        'city_conc': round((cities.most_common(1)[0][1]/n_buys) if cities else 0, 2),
        'n_ladders': len(ladders),
        'max_run': max_run,
        'ladder_ratio': round(ladder_ratio, 2),
        'cheap_ratio': round(cheap_ratio, 2),
        'high_ratio': round(high_ratio, 2),
        'period_days': period_days,
        'pattern': pattern,
        'weather_ratio': round(temp/n_buys, 2),
    }

def main():
    conn = sqlite3.connect(DB)
    unknown = [r[0] for r in conn.execute(
        "SELECT wallet FROM profiles WHERE strategy='unknown'").fetchall()]
    conn.close()

    print(f"Unknown кошельков: {len(unknown)}")

    results = []
    for i, w in enumerate(unknown, 1):
        try:
            r = deep_profile(w)
            results.append(r)
            print(f"  [{i}/{len(unknown)}] {w[:10]}... → {r.get('pattern')} "
                  f"median={r.get('median')} run={r.get('max_run')} city={r.get('top_city')}")
        except Exception as e:
            print(f"  [{i}/{len(unknown)}] {w[:10]}... ERR {str(e)[:40]}")

    json.dump(results, open('/tmp/deep_unknown.json', 'w'))

    # сводка по паттернам
    pat = Counter(r.get('pattern') for r in results)
    print(f"\n=== Итог по выявленным паттернам ===")
    for p, n in pat.most_common():
        print(f"  {p:15s} {n}")

if __name__ == '__main__':
    main()
