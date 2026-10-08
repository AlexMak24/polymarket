"""
city_parser.py — разбор названий weather-рынков Polymarket.

Живые форматы (август 2026):
  Will the highest temperature in London be 22°C on August 19?
  Will the highest temperature in London be 20°C or below on August 19?
  Will the highest temperature in London be 30°C or higher on August 19?
  Highest temperature in London on August 19          (event, градус в outcome)
  Will NYC reach 80°F on March 22?
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

CITIES = [
    "Hong Kong", "Shenzhen", "Guangzhou", "Shanghai", "Beijing", "Taipei",
    "Seoul", "Busan", "Tokyo", "Singapore", "Bangkok", "Jakarta", "Manila",
    "Kuala Lumpur", "Mumbai", "Delhi", "Lucknow", "Dubai", "Riyadh",
    "London", "Paris", "Berlin", "Madrid", "Rome", "Amsterdam", "Milan",
    "Tel Aviv", "New York", "Los Angeles", "Chicago", "Houston", "Dallas",
    "Miami", "Austin", "San Francisco", "Seattle", "Atlanta", "Denver",
    "Toronto", "Vancouver", "Mexico City", "Buenos Aires", "Sao Paulo",
    "Santiago", "Cape Town",
]

# Sort longest first so "New York" wins over a stray "York".
_CITIES_BY_LEN = sorted(CITIES, key=len, reverse=True)

TEMP_RANGE_RE = re.compile(
    r"(?:Will\s+the\s+)?"
    r"(?P<typ>highest|lowest)\s+temperature\s+in\s+"
    r"(?P<city>.+?)\s+be\s+between\s+"
    r"(?P<lo>\d+)\s*[-–]\s*(?P<hi>\d+)\s*°\s*(?P<unit>[CF])"
    r"\s+on\s+(?P<date>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

TEMP_BUCKET_RE = re.compile(
    r"(?:Will\s+the\s+)?"
    r"(?P<typ>highest|lowest)\s+temperature\s+in\s+"
    r"(?P<city>.+?)\s+be\s+"
    r"(?P<degree>\d+)\s*°\s*(?P<unit>[CF])"
    r"(?:\s+or\s+(?P<bound>below|higher|above))?"
    r"\s+on\s+(?P<date>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

TEMP_EVENT_RE = re.compile(
    r"(?:Will\s+the\s+)?"
    r"(?P<typ>highest|lowest)\s+temperature\s+in\s+"
    r"(?P<city>.+?)\s+on\s+(?P<date>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

REACH_RE = re.compile(
    r"Will\s+(?P<city>.+?)\s+reach\s+"
    r"(?P<degree>\d+)\s*°\s*(?P<unit>[CF])"
    r"\s+on\s+(?P<date>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

RAIN_RE = re.compile(
    r"Will\s+it\s+rain\s+in\s+(?P<city>.+?)\s+on\s+(?P<date>.+?)\s*\??\s*$",
    re.IGNORECASE,
)

STORM_RE = re.compile(r"(Typhoon|Hurricane|Cyclone)", re.IGNORECASE)

OUTCOME_RE = re.compile(
    r"(?P<degree>\d+)\s*°\s*(?P<unit>[CF])"
    r"(?:\s+or\s+(?P<bound>below|higher|above))?",
    re.IGNORECASE,
)

WEATHER_HINT_RE = re.compile(
    r"temperature|°\s*[CF]|hottest|coldest|highest|lowest|rain|snow|storm|"
    r"hurricane|typhoon|cyclone",
    re.IGNORECASE,
)

_EMPTY = {
    "kind": "other",
    "city": None,
    "type": None,
    "degree": None,
    "unit": None,
    "bound": None,
    "date": None,
    "date_iso": None,
}


def _norm_bound(raw: str | None) -> str | None:
    if not raw:
        return None
    bound = raw.lower()
    if bound == "above":
        return "higher"
    return bound


def _norm_unit(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.upper()


def extract_city(title: str) -> str | None:
    """Возвращает город из названия рынка, либо None."""
    tl = title.lower()
    for city in _CITIES_BY_LEN:
        if city.lower() in tl:
            return city
    return None


def parse_market_date(raw: str | None, year: int | None = None) -> str | None:
    """Нормализует 'August 19' / 'Aug 19, 2026' → ISO YYYY-MM-DD, иначе None."""
    if not raw:
        return None
    text = raw.strip().rstrip("?.,").strip()
    formats = (
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
        "%B %d",
        "%b %d",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                y = year or datetime.now(timezone.utc).year
                dt = dt.replace(year=y)
            return dt.date().isoformat()
        except ValueError:
            continue
    return None


def _result(
    *,
    kind: str,
    city: str | None = None,
    typ: str | None = None,
    degree: int | None = None,
    unit: str | None = None,
    bound: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    city_clean = city.strip() if city else None
    date_clean = date.strip().rstrip("?") if date else None
    return {
        "kind": kind,
        "city": city_clean,
        "type": typ.lower() if typ else None,
        "degree": degree,
        "unit": _norm_unit(unit),
        "bound": _norm_bound(bound),
        "date": date_clean,
        "date_iso": parse_market_date(date_clean),
    }


def parse_market(title: str) -> dict[str, Any]:
    """
    Разбирает название рынка.

    Возвращает:
      kind    — temperature | rain | storm | other
      city    — str | None
      type    — highest | lowest | None
      degree  — int | None
      unit    — C | F | None
      bound   — below | higher | None  (крайние бакеты)
      date    — сырая дата из заголовка
      date_iso— YYYY-MM-DD если распознали
    """
    text = (title or "").strip()
    if not text:
        return dict(_EMPTY)

    m = TEMP_RANGE_RE.search(text)
    if m:
        lo, hi = int(m.group("lo")), int(m.group("hi"))
        info = _result(
            kind="temperature",
            city=m.group("city"),
            typ=m.group("typ"),
            degree=lo,
            unit=m.group("unit"),
            date=m.group("date"),
        )
        info["range"] = [lo, hi]
        return info

    m = TEMP_BUCKET_RE.search(text)
    if m:
        return _result(
            kind="temperature",
            city=m.group("city"),
            typ=m.group("typ"),
            degree=int(m.group("degree")),
            unit=m.group("unit"),
            bound=m.group("bound"),
            date=m.group("date"),
        )

    m = REACH_RE.search(text)
    if m:
        return _result(
            kind="temperature",
            city=m.group("city"),
            typ="highest",
            degree=int(m.group("degree")),
            unit=m.group("unit"),
            date=m.group("date"),
        )

    m = TEMP_EVENT_RE.search(text)
    if m:
        return _result(
            kind="temperature",
            city=m.group("city"),
            typ=m.group("typ"),
            date=m.group("date"),
        )

    m = RAIN_RE.search(text)
    if m:
        return _result(
            kind="rain",
            city=m.group("city"),
            date=m.group("date"),
        )

    if STORM_RE.search(text):
        return _result(kind="storm", city=extract_city(text))

    city = extract_city(text)
    kind = "other"
    if city and WEATHER_HINT_RE.search(text):
        kind = "temperature"
    return _result(kind=kind, city=city)


def parse_outcome(outcome: str) -> dict[str, Any]:
    """Разбирает имя исхода ('21°C', '20°C or below')."""
    m = OUTCOME_RE.search(outcome or "")
    if not m:
        return {"degree": None, "unit": None, "bound": None}
    return {
        "degree": int(m.group("degree")),
        "unit": _norm_unit(m.group("unit")),
        "bound": _norm_bound(m.group("bound")),
    }


def parse_trade(trade: dict) -> dict[str, Any]:
    """
    Разбирает сделку Data API: title (событие/маркет) + outcome/name (бакет).
    Если градус только в outcome — подмешивает его в temperature-результат.
    """
    title = trade.get("title") or trade.get("question") or ""
    outcome = trade.get("outcome") or trade.get("name") or ""
    info = parse_market(str(title))
    if info["degree"] is None and outcome:
        extra = parse_outcome(str(outcome))
        if extra["degree"] is not None:
            info["degree"] = extra["degree"]
            info["unit"] = extra["unit"] or info["unit"]
            info["bound"] = extra["bound"] or info["bound"]
            if info["kind"] == "other":
                info["kind"] = "temperature"
    return info


def is_weather_text(text: str) -> bool:
    return bool(WEATHER_HINT_RE.search(text or ""))
