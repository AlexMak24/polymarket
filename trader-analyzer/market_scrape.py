"""
market_scrape.py — сборщик weather-кошельков ЧЕРЕЗ РЫНКИ.

Правильный подход (в отличие от агрегаторов, где погодных почти нет):
  1. Взять conditionId weather-рынков из сделок известных weather-трейдеров
  2. Для каждого рынка вытащить ВСЕХ трейдеров (Data API /trades?market=<conditionId>)
  3. Уникальные адреса → это и есть weather-кошельки
  4. Прогнать через classifier → сохранить погодных в profiles.db

НЕ трогает работающий weather-бот.
"""

from collections import Counter

from api import get_all_trades
from city_parser import is_weather_text
from classifier import classify_wallet
from collector import upsert_profile, WEATHER_MIN_RATIO, get_all_profiles, KNOWN_WALLETS
from config import make_http_client

_client = None


def _c():
    global _client
    if _client is None:
        _client = make_http_client(timeout=30)
    return _client


def get_weather_condition_ids(wallets: list[str], max_trades: int = 300) -> set[str]:
    """Собирает conditionId всех weather-рынков из сделок известных кошельков."""
    cond_ids = set()
    for w in wallets:
        try:
            trades = get_all_trades(w, max_trades=max_trades)
            for t in trades:
                title = t.get("title", "")
                if is_weather_text(title):
                    cid = t.get("conditionId")
                    if cid:
                        cond_ids.add(cid)
        except Exception:
            continue
    return cond_ids


def get_market_traders(condition_id: str, limit: int = 200) -> Counter:
    """Все трейдеры конкретного рынка (proxyWallet → число сделок)."""
    r = _c().get("https://data-api.polymarket.com/trades",
                 params={"market": condition_id, "limit": limit})
    try:
        trades = r.json()
    except Exception:
        return Counter()
    return Counter(t.get("proxyWallet") for t in trades if t.get("proxyWallet"))


def collect_from_markets(min_trades: int = 2, verbose: bool = True) -> dict:
    """
    Полный цикл: weather-рынки → трейдеры → фильтр погодных → сохранить.
    min_trades — минимальное число сделок трейдера на weather-рынках (отсев шума).
    """
    # 1. Рынки из известных weather-трейдеров
    known = list(KNOWN_WALLETS.keys())
    cond_ids = get_weather_condition_ids(known)
    if verbose:
        print(f"Weather-рынков найдено: {len(cond_ids)}")

    # 2. Трейдеры всех рынков
    all_traders = Counter()
    for cid in cond_ids:
        all_traders.update(get_market_traders(cid))

    if verbose:
        print(f"Уникальных трейдеров на weather-рынках: {len(all_traders)}")

    # 3. Отсев: только с >= min_trades сделок
    candidates = [a for a, n in all_traders.items() if n >= min_trades]
    if verbose:
        print(f"Кандидатов (>= {min_trades} сделок): {len(candidates)}")

    # 4. Фильтр погодных + сохранить
    saved = []
    for addr in candidates:
        try:
            trades = get_all_trades(addr, max_trades=300)
            profile = classify_wallet(trades)
            wr = profile.get("weather_ratio", 0)
            if wr >= WEATHER_MIN_RATIO:
                full = upsert_profile(addr, max_trades=500)
                saved.append({"wallet": addr, **full})
                if verbose:
                    print(f"  ✅ {addr[:10]}... weather={wr:.2f} "
                          f"strategy={full['strategy']} top={full.get('top_city')}")
            elif verbose and wr > 0.05:
                print(f"  ⏭️  {addr[:10]}... weather={wr:.2f} (пропущен)")
        except Exception as e:
            if verbose:
                print(f"  ❌ {addr[:10]}... {str(e)[:40]}")

    return {
        "weather_markets": len(cond_ids),
        "market_traders": len(all_traders),
        "candidates": len(candidates),
        "saved": len(saved),
    }


if __name__ == "__main__":
    result = collect_from_markets()
    print(f"\n=== ИТОГ ===")
    print(f"Всего погодных в базе: {len(get_all_profiles())}")
