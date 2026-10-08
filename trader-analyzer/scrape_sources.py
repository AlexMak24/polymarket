"""
scrape_sources.py — парсер источников кошельков (Polynyx + Predicts.guru).

Собирает адреса топ-трейдеров из агрегаторов (SSR, без браузера),
прогоняет через classifier.weather_ratio, сохраняет погодных в profiles.db.

НЕ трогает работающий weather-бот.
"""

import re
import json
from api import get_all_trades
from classifier import classify_wallet
from collector import upsert_profile, WEATHER_MIN_RATIO, get_all_profiles
from config import make_http_client

_client = None


def _c():
    global _client
    if _client is None:
        _client = make_http_client(
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"},
        )
    return _client


def _decode_push(s: str) -> str:
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return s


def scrape_polynyx() -> list[str]:
    """Извлекает адреса кошельков из лидерборда Polynyx (/leaderboard)."""
    r = _c().get("https://polynyx.com/leaderboard")
    html = r.text
    pushes = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    all_text = "\n".join(_decode_push(p) for p in pushes)
    addrs = set(re.findall(r'0x[a-fA-F0-9]{40}', all_text))
    return sorted(addrs)


def scrape_predicts_guru() -> list[str]:
    """Извлекает адреса кошельков из Predicts.guru (главная)."""
    r = _c().get("https://predicts.guru")
    addrs = set(re.findall(r'0x[a-fA-F0-9]{40}', r.text))
    return sorted(addrs)


def collect_from_sources(screen_limit: int = 200, verbose: bool = True) -> dict:
    """
    Полный цикл: собрать адреса → отфильтровать погодных → сохранить.

    screen_limit — сколько сделок вытаскивать для быстрого скрина weather_ratio.
    """
    polynyx = scrape_polynyx()
    predicts = scrape_predicts_guru()
    all_addrs = sorted(set(polynyx + predicts))

    if verbose:
        print(f"Polynyx: {len(polynyx)} адресов")
        print(f"Predicts.guru: {len(predicts)} адресов")
        print(f"Всего уникальных: {len(all_addrs)}")
        print(f"\nСкриню на погодность (weather_ratio >= {WEATHER_MIN_RATIO})...\n")

    weather_wallets = []
    for addr in all_addrs:
        try:
            trades = get_all_trades(addr, max_trades=screen_limit)
            profile = classify_wallet(trades)
            wr = profile.get("weather_ratio", 0)
            if wr >= WEATHER_MIN_RATIO:
                weather_wallets.append(addr)
                if verbose:
                    print(f"  ✅ {addr[:10]}... weather={wr:.2f} "
                          f"strategy={profile['strategy']} top={profile.get('top_city')}")
            elif verbose and wr > 0.05:
                print(f"  ⏭️  {addr[:10]}... weather={wr:.2f} (не погодный, "
                      f"strategy={profile['strategy']})")
        except Exception as e:
            if verbose:
                print(f"  ❌ {addr[:10]}... {str(e)[:50]}")

    if verbose:
        print(f"\nНайдено погодных: {len(weather_wallets)}")

    # Полный профиль + сохранение для погодных
    saved = []
    for addr in weather_wallets:
        try:
            profile = upsert_profile(addr, max_trades=500)
            saved.append({"wallet": addr, **profile})
        except Exception as e:
            if verbose:
                print(f"  ❌ сохранить {addr[:10]}... {str(e)[:50]}")

    return {
        "sources": {"polynyx": len(polynyx), "predicts_guru": len(predicts)},
        "unique_addrs": len(all_addrs),
        "weather_found": len(weather_wallets),
        "saved": saved,
    }


if __name__ == "__main__":
    result = collect_from_sources()
    print(f"\n=== ИТОГ ===")
    print(f"Всего в базе погодных профилей: {len(get_all_profiles())}")
