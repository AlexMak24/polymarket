"""
classifier.py — стратегия кошелька по сделкам.

Стратегии (по приоритету):
  ladder      — ≥3 соседних бакетов одного города+даты+типа
  certain     — медиана/доля входов > 85¢
  longshot    — доля входов < 10¢ (не только <1¢)
  specialist  — город-специалист: высокая концентрация, одиночные бакеты
  value       — медиана входа 25–50¢
  momentum    — медиана входа 50–70¢
  mixed / unknown
"""

from __future__ import annotations

from collections import Counter, defaultdict

from city_parser import parse_trade
from topic import topic_distribution

WEATHER_KINDS = {"temperature", "rain", "storm"}


def longest_consecutive_run(degrees: list[int]) -> int:
    """Длина самой длинной последовательности соседних градусов."""
    if not degrees:
        return 0
    degrees = sorted(set(degrees))
    best = cur = 1
    for i in range(1, len(degrees)):
        if degrees[i] - degrees[i - 1] == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


def detect_ladders(trades: list[dict], min_buckets: int = 3) -> dict:
    """
    Находит лестницы: группы (город, дата, тип) с >= min_buckets соседних
    градусов. Возвращает словарь групп -> {degrees, trades_count}.
    """
    groups: dict = defaultdict(lambda: {"degrees": set(), "trades": 0})

    for t in trades:
        if t.get("side") != "BUY":
            continue
        info = parse_trade(t)
        if info["kind"] != "temperature" or info["degree"] is None:
            continue
        key = (info["city"], info["date"], info["type"], info.get("unit") or "C")
        groups[key]["degrees"].add(info["degree"])
        groups[key]["trades"] += 1

    ladders = {}
    for key, val in groups.items():
        run = longest_consecutive_run(list(val["degrees"]))
        if run >= min_buckets:
            ladders[key] = {
                "city": key[0],
                "date": key[1],
                "type": key[2],
                "unit": key[3],
                "degrees": sorted(val["degrees"]),
                "run": run,
                "trades": val["trades"],
            }
    return ladders


def _pick_strategy(
    *,
    ladder_ratio: float,
    certain_ratio: float,
    longshot_ratio: float,
    topic_concentration: float,
    top_topic: str | None,
    median: float,
) -> str:
    if ladder_ratio >= 0.5:
        return "ladder"
    if certain_ratio >= 0.5:
        return "certain"
    if longshot_ratio >= 0.5:
        return "longshot"
    # specialist теперь по теме, а не по погоде: кошелёк сконцентрирован в
    # одном разделе (не «other» — иначе это просто неклассифицированный шум).
    if topic_concentration >= 0.55 and top_topic and top_topic != "other":
        return "specialist"
    if 0.25 <= median <= 0.50:
        return "value"
    if 0.50 < median < 0.70:
        return "momentum"
    if ladder_ratio >= 0.3 or longshot_ratio >= 0.3 or certain_ratio >= 0.3:
        return "mixed"
    return "unknown"


def classify_wallet(trades: list[dict]) -> dict:
    """
    Полный профиль стратегии кошелька.

    Возвращает strategy и признаки (ladder/longshot/certain/value/specialist).
    """
    buys = [t for t in trades if t.get("side") == "BUY"]
    if not buys:
        return {
            "strategy": "unknown",
            "total_trades": len(trades),
            "buy_trades": 0,
            "ladder_ratio": 0.0,
            "longshot_ratio": 0.0,
            "certain_ratio": 0.0,
            "weather_ratio": 0.0,
            "median_entry": 0.0,
            "avg_entry": 0.0,
            "cities": {},
            "top_city": None,
            "city_concentration": 0.0,
            "topics": {},
            "top_topic": None,
            "topic_concentration": 0.0,
            "ladders": [],
        }

    prices = [float(t.get("price") or 0) for t in buys]
    prices_sorted = sorted(prices)
    median = prices_sorted[len(prices_sorted) // 2]
    avg = sum(prices) / len(prices)

    # Лонгшоты: < 10¢ (раньше было <1¢ — value/mid-longshot уезжали в unknown)
    longshot_count = sum(1 for p in prices if p < 0.10)
    longshot_ratio = longshot_count / len(prices)

    certain_count = sum(1 for p in prices if p > 0.85)
    certain_ratio = certain_count / len(prices)

    ladders = detect_ladders(trades)
    ladder_trades = sum(l["trades"] for l in ladders.values())
    ladder_ratio = ladder_trades / len(buys)

    cities: Counter[str] = Counter()
    weather_count = 0
    for t in buys:
        info = parse_trade(t)
        if info["kind"] in WEATHER_KINDS:
            weather_count += 1
        if info["city"]:
            cities[info["city"]] += 1

    weather_ratio = weather_count / len(buys)
    top_city = cities.most_common(1)[0][0] if cities else None
    city_concentration = (cities[top_city] / len(buys)) if top_city else 0.0

    # Тематическая разбивка (канонические 6 + other) — главная разбивка профиля.
    topics = topic_distribution(trades)
    topic_total = sum(topics.values())
    top_topic = max(topics, key=topics.get) if topic_total else None
    topic_concentration = (topics[top_topic] / topic_total) if topic_total else 0.0

    strategy = _pick_strategy(
        ladder_ratio=ladder_ratio,
        certain_ratio=certain_ratio,
        longshot_ratio=longshot_ratio,
        topic_concentration=topic_concentration,
        top_topic=top_topic,
        median=median,
    )

    return {
        "strategy": strategy,
        "ladder_ratio": round(ladder_ratio, 3),
        "longshot_ratio": round(longshot_ratio, 3),
        "certain_ratio": round(certain_ratio, 3),
        "weather_ratio": round(weather_ratio, 3),
        "median_entry": round(median, 4),
        "avg_entry": round(avg, 4),
        "cities": dict(cities.most_common(10)),
        "top_city": top_city,
        "city_concentration": round(city_concentration, 3),
        "topics": topics,
        "top_topic": top_topic,
        "topic_concentration": round(topic_concentration, 3),
        "total_trades": len(trades),
        "buy_trades": len(buys),
        "ladders": [
            {
                "city": l["city"],
                "date": l["date"],
                "type": l["type"],
                "run": l["run"],
                "degrees": l["degrees"],
            }
            for l in list(ladders.values())[:10]
        ],
    }
