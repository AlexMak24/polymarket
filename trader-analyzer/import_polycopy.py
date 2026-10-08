"""
import_polycopy.py — импорт weather-трейдеров с Polycopy лидерборда в profiles.db.
"""
import json, sys
from collector import get_all_profiles, upsert_profile

def main():
    traders = json.load(open('/tmp/polycopy_weather.json'))
    existing = {p['wallet'].lower() for p in get_all_profiles()}

    new = [t for t in traders if t['wallet'].lower() not in existing]
    known = [t for t in traders if t['wallet'].lower() in existing]

    print(f"Всего в Polycopy weather-лидерборде: {len(traders)}")
    print(f"  уже в базе: {len(known)}")
    print(f"  новых: {len(new)}\n")

    for t in new:
        try:
            prof = upsert_profile(t['wallet'], name=t['name'])
            print(f"  ✅ {t['name'][:18]:18s} weather={prof['weather_ratio']:.2f} "
                  f"strategy={prof['strategy']:8s} top={prof.get('top_city','?')}")
        except Exception as e:
            print(f"  ❌ {t['name'][:18]:18s} ERR {str(e)[:40]}")

    total = len(get_all_profiles())
    print(f"\n=== ИТОГО погодных в базе: {total} ===")

if __name__ == '__main__':
    main()
