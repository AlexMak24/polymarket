"""
topic.py — классификатор тем (разделов) рынков Polymarket.

Расширение городского/погодного парсера: помимо weather определяет секцию
рынка по заголовку и исходу. Два уровня детализации:

  * `classify_topic` — тонкая тема (внутренний тег, 10 значений, вкл.
    economics/world/business — пригодятся post-MVP).
  * `topic_distribution` / `top_topic` / `topic_ratio` — канонические
    6 разделов + `other` (economics/world/business сворачиваются в `other`),
    это и есть разбивка для отчёта-портрета.

Классификация чисто текстовая — без сети и без ключей, поэтому её можно
тестировать на синтетических заголовках.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

from city_parser import parse_trade

# Тонкие темы (внутренние теги). Порядок важен: первое совпадение — тема.
TOPICS = (
    "weather",
    "politics",
    "sports",
    "crypto",
    "economics",
    "science",
    "world",
    "pop_culture",
    "business",
    "other",
)

# Канонические разделы отчёта: 6 + other.
CANONICAL_TOPICS = (
    "weather",
    "politics",
    "sports",
    "crypto",
    "science",
    "pop_culture",
    "other",
)

# Сворачивание тонких тем в канонические (economics/world/business -> other).
_CANONICAL = {
    "weather": "weather",
    "politics": "politics",
    "sports": "sports",
    "crypto": "crypto",
    "science": "science",
    "pop_culture": "pop_culture",
    "economics": "other",
    "world": "other",
    "business": "other",
    "other": "other",
}

# Собственный weather-детект с границами слов: city_parser.is_weather_text
# использует голые подстроки и ошибочно ловит "rain" внутри "Ukraine".
_WEATHER_WORDS = re.compile(
    r"\b(temperature|hottest|coldest|highest|lowest|rain|rains|rainy|snow|"
    r"storm|hurricane|typhoon|cyclone)\b|\d+\s*°\s*[CF]",
    re.IGNORECASE,
)

_RULES: tuple[tuple[str, str], ...] = (
    # politics — выборы, органы власти, политики
    ("politics", r"\b(election|president|senator|governor|congress|mayor|"
     r"parliament|prime minister|minister|ballot|incumbent|nominee|cabinet|"
     r"republican|democrat|party leader|vote|impeach|vice president)\b"),
    # sports
    ("sports", r"\b(nba|nfl|mlb|nhl|soccer|football|basketball|baseball|"
     r"hockey|world cup|super bowl|olympic|championship|ufc|mma|boxing|"
     r"tennis|golf|grand prix|formula 1|f1|playoff|final|goals?\b|"
     r"super bowl|premier league|la liga|serie a|bundesliga)\b"),
    # crypto
    ("crypto", r"\b(bitcoin|btc|ethereum|eth|solana|sol|crypto|blockchain|"
     r"coin|token|doge|dogecoin|xrp|defi|nft|halving|altcoin|satoshi|"
     r"price of (bitcoin|ethereum|solana)|above \$?\d{2,3}k)\b"),
    # economics
    ("economics", r"\b(fed|federal reserve|inflation|cpi|gdp|unemployment|"
     r"interest rate|rate cut|rate hike|recession|tariff|treasury|bond|"
     r"stock market|s&p 500|nasdaq|dow jones|jobs report|payroll)\b"),
    # science / tech / health
    ("science", r"\b(nasa|spacex|mars|moon landing|quantum|artificial "
     r"intelligence|agi|ai model|pandemic|virus|vaccine|fda|cure|cancer|"
     r"climate|wildfire|earthquake|volcano|asteroid|fossil)\b"),
    # world — конфликты и геополитика
    ("world", r"\b(war|russia|ukraine|china|taiwan|iran|israel|nato|"
     r"conflict|ceasefire|invasion|sanctions|border|missile|nuclear)\b"),
    # pop_culture
    ("pop_culture", r"\b(oscar|grammy|emmy|movie|film|box office|tv series|"
     r"celebrity|album|music award|award show|streaming|netflix)\b"),
    # business
    ("business", r"\b(tesla|apple|amazon|microsoft|google|meta|nvidia|"
     r"earnings|revenue|acquisition|merger|ipo|startup|layoffs|"
     r"ceo|valuation)\b"),
)

_COMPILED: tuple[tuple[str, re.Pattern], ...] = tuple(
    (topic, re.compile(pattern, re.IGNORECASE)) for topic, pattern in _RULES
)


def classify_topic(title: str, outcome: str | None = None) -> str:
    """Возвращает тонкую тему рынка по заголовку и опциональному исходу."""
    text = f"{title or ''} {outcome or ''}".strip()
    if not text:
        return "other"

    # Погода: структурированный парсер (temperature/rain/storm) ИЛИ
    # word-boundary регэксп. Приоритет — историческая специализация тула.
    if parse_trade({"title": title or "", "outcome": outcome or ""}).get("kind") != "other" \
            or _WEATHER_WORDS.search(text):
        return "weather"

    lowered = text.lower()
    for topic, pattern in _COMPILED:
        if pattern.search(lowered):
            return topic
    return "other"


def canonical_topic(topic: str) -> str:
    """Сворачивает тонкую тему в канонический раздел (6 + other)."""
    return _CANONICAL.get(topic, "other")


def topic_distribution_fine(trades: Iterable[dict]) -> dict[str, int]:
    """Число сделок по тонким темам (10 значений, включая нули)."""
    counts: Counter[str] = Counter()
    for t in trades:
        title = t.get("title") or t.get("question") or ""
        outcome = t.get("outcome") or t.get("name") or ""
        counts[classify_topic(str(title), str(outcome))] += 1
    return {topic: counts.get(topic, 0) for topic in TOPICS}


def topic_distribution(trades: Iterable[dict]) -> dict[str, int]:
    """Число сделок по каноническим разделам (6 + other)."""
    fine = topic_distribution_fine(trades)
    out: Counter[str] = Counter()
    for topic, n in fine.items():
        out[canonical_topic(topic)] += n
    return {t: out.get(t, 0) for t in CANONICAL_TOPICS}


def top_topic(trades: Iterable[dict]) -> str | None:
    """Доминирующий канонический раздел, либо None при пустом вводе."""
    dist = topic_distribution(trades)
    if not sum(dist.values()):
        return None
    return max(dist, key=dist.get)


def topic_ratio(trades: Iterable[dict], topic: str) -> float:
    """Доля сделок канонического раздела (0..1)."""
    dist = topic_distribution(trades)
    total = sum(dist.values())
    if not total:
        return 0.0
    return dist.get(canonical_topic(topic), 0) / total
