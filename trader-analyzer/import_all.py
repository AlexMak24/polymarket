"""
import_all.py — импорт всех weather-кошельков с агрегаторов (Polycopy + weatherbot + polysmartwallet).
"""
import json
from collector import get_all_profiles, upsert_profile

def main():
    traders = json.load(open('/tmp/weather_all_sources.json'))
    existing = {p['wallet'].lower() for p in get_all_profiles()}

    new = [t for t in traders if t['address'].lower() not in existing]
    print(f"Всего уникальных с агрегаторов: {len(traders)}")
    print(f"  уже в базе: {len(traders) - len(new)}")
    print(f"  новых к импорту: {len(new)}\n")

    for t in new:
        name = t.get('name') or None
        addr = t['address']
        srcs = '+'.join(t.get('sources', []))
        try:
            prof = upsert_profile(addr, name=name)
            print(f"  ✅ {t['name'][:18]:18s} weather={prof['weather_ratio']:.2f} "
                  f"strat={prof['strategy']:8s} top={prof.get('top_city','?')} [{srcs}]")
        except Exception as e:
            print(f"  ❌ {t['name'][:18]:18s} [{srcs}] ERR {str(e)[:40]}")

    total = len(get_all_profiles())
    print(f"\n=== ИТОГО погодных в базе: {total} ===")

if __name__ == '__main__':
    main()
