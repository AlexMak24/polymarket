"""
snowball.py — снежный ком сбора weather-кошельков.

Итеративно расширяет базу:
  seed → их weather-рынки → трейдеры этих рынков → новые погодные → снова.

Итерация 0: текущие погодные в profiles.db (10 шт)
Итерация N: для каждого погодного собрать conditionId его weather-рынков
           → для каждого рынка собрать всех трейдеров → weather_ratio → новые.

Плюс: выгребает адреса-кандидаты с Polynyx (все категории) как дополнительный посев.
Останавливается когда новых погодных < 2 за итерацию, максимум 4 итерации.
"""
import sqlite3, time
from collections import Counter, defaultdict
from api import get_all_trades
from collector import get_all_profiles, DB_PATH, upsert_profile
from classifier import classify_wallet
from config import make_http_client

HTTP = make_http_client(timeout=25, headers={'User-Agent': 'Mozilla/5.0'})

WEATHER_RE = r'(?i)temperature|°C|°F|hottest|coldest|highest|lowest|rain|snow|wind|storm|hurricane|tornado|climate'

def get_weather_markets(wallet, max_trades=500):
    """conditionId всех weather-рынков трейдера."""
    trades = get_all_trades(wallet, max_trades)
    cids = set()
    for t in trades:
        title = (t.get('title') or '') + ' ' + (t.get('name') or '')
        if __import__('re').search(WEATHER_RE, title):
            cid = t.get('conditionId') or t.get('condition_id')
            if cid:
                cids.add(cid)
    return cids

def traders_of_market(cid, limit=100):
    try:
        r = HTTP.get(f"https://data-api.polymarket.com/trades",
                     params={'market': cid, 'limit': limit, 'offset': 0})
        d = r.json()
        return [t.get('proxyWallet') for t in d if t.get('proxyWallet')]
    except Exception:
        return []

def main():
    conn = sqlite3.connect(DB_PATH)
    known = {p['wallet'].lower() for p in get_all_profiles()}
    print(f"[итер 0] погодных в базе: {len(known)}")

    # Посев: все известные погодные
    seeds = list(known)
    for iteration in range(1, 5):
        # 1. собрать weather-рынки всех seeds
        all_markets = set()
        for w in seeds:
            all_markets |= get_weather_markets(w)
        print(f"[итер {iteration}] собрано weather-рынков: {len(all_markets)}")

        # 2. собрать трейдеров этих рынков
        counter = Counter()
        for i, cid in enumerate(all_markets):
            for t in traders_of_market(cid):
                counter[t] += 1
            if (i + 1) % 50 == 0:
                print(f"    ...обработано {i+1}/{len(all_markets)} рынков, трейдеров: {len(counter)}")

        # 3. фильтр: weather_ratio >= 0.3, не в базе
        new_found = []
        candidates = [w for w, n in counter.items() if n >= 2 and w.lower() not in known]
        print(f"[итер {iteration}] кандидатов: {len(candidates)}")
        for w in candidates:
            try:
                trades = get_all_trades(w)
                res = classify_wallet(trades)
            except Exception as e:
                print(f"    ⚠️ {w[:12]}... ERR {str(e)[:40]}")
                continue
            if res.get('weather_ratio', 0) >= 0.3:
                new_found.append((w, res))
                known.add(w.lower())
                try:
                    upsert_profile(w)  # сохранить в базу
                except Exception:
                    pass
                print(f"    ✅ {w[:12]}... weather={res['weather_ratio']:.2f} "
                      f"strategy={res['strategy']} top={res.get('top_city','?')}")

        print(f"[итер {iteration}] новых погодных: {len(new_found)}")
        if len(new_found) < 2:
            print("Стоп: новых < 2, снежный ком исчерпан")
            break
        seeds = [w for w, _ in new_found]
        time.sleep(1)

    conn.close()
    total = len(get_all_profiles())
    print(f"\n=== ИТОГО погодных в базе: {total} ===")

if __name__ == '__main__':
    main()
