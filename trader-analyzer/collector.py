"""
collector.py — Фаза 3: сборщик weather-кошельков в SQLite.

Собирает профили ТОЛЬКО weather-кошельков (фильтр по доле temperature-сделок).
НЕ трогает работающий weather-бот.

Источники кошельков:
  1. Стартовая база — известные weather-трейдеры (из статей/ресёрча)
  2. Расширение — add_wallet() / add_wallets() вручную
  3. (далее) — автоматический парсинг Polynyx/Polycopy через Camofox
"""

import sqlite3
import json
from datetime import datetime, timezone

from api import fetch_pnl, get_all_trades
from classifier import classify_wallet
from config import DB_PATH, WEATHER_MIN_RATIO
from metrics import activity_stats

# Стартовая база известных weather-трейдеров (адрес -> имя)
KNOWN_WALLETS = {
    "0x4989bfed5900ba096b08ba1f9b718464527c983e": "WeatherHk (macau.weather)",
    "0xb9012e0d9b60d3920286309328b935cdfa609fc4": "weatherstappen",
    "0xca75fbadcc238afd23c317e253a8b5c47b390a64": "0xSurferX",
}

COLS = ["wallet", "name", "strategy", "ladder_ratio", "longshot_ratio",
        "certain_ratio", "weather_ratio", "median_entry", "top_city",
        "city_concentration", "cities_json", "topics_json", "top_topic",
        "topic_concentration", "total_trades", "buy_trades",
        "updated_at", "pnl", "pnl_updated_at", "last_trade_at", "first_trade_at",
        "trades_30d", "buys_30d", "volume_30d", "active_days_30d",
        "trades_per_month", "period_days", "playbook"]

_EXTRA_COLS = {
    "pnl": "REAL",
    "pnl_updated_at": "TEXT",
    "last_trade_at": "TEXT",
    "first_trade_at": "TEXT",
    "trades_30d": "INTEGER",
    "buys_30d": "INTEGER",
    "volume_30d": "REAL",
    "active_days_30d": "INTEGER",
    "trades_per_month": "REAL",
    "period_days": "REAL",
    "playbook": "INTEGER",
    "topics_json": "TEXT",
    "top_topic": "TEXT",
    "topic_concentration": "REAL",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(profiles)")}
    for name, typ in _EXTRA_COLS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE profiles ADD COLUMN {name} {typ}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_strategy ON profiles(strategy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_pnl ON profiles(pnl)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_profiles_tpm ON profiles(trades_per_month)")


def _profile_columns() -> list[str]:
    conn = _connect()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(profiles)")]
    conn.close()
    return cols


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            wallet TEXT PRIMARY KEY,
            name TEXT,
            strategy TEXT,
            ladder_ratio REAL,
            longshot_ratio REAL,
            certain_ratio REAL,
            weather_ratio REAL,
            median_entry REAL,
            top_city TEXT,
            city_concentration REAL,
            cities_json TEXT,
            topics_json TEXT,
            top_topic TEXT,
            topic_concentration REAL,
            total_trades INTEGER,
            buy_trades INTEGER,
            updated_at TEXT
        )
    """)
    _migrate(conn)
    conn.commit()
    return conn


def _save_profile(wallet: str, profile: dict, name: str | None = None) -> dict:
    act = {k: profile.get(k) for k in (
        "last_trade_at", "first_trade_at", "trades_30d", "buys_30d",
        "volume_30d", "active_days_30d", "trades_per_month", "period_days",
    )}
    playbook = 1 if is_playbook_profile(profile) else 0
    profile["playbook"] = playbook
    now = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    prev = conn.execute(
        "SELECT name, pnl, pnl_updated_at FROM profiles WHERE wallet = ?",
        (wallet,),
    ).fetchone()
    prev_name, prev_pnl, prev_pnl_at = (prev if prev else (None, None, None))
    pnl = profile.get("pnl")
    if pnl is None:
        pnl = prev_pnl
        pnl_at = prev_pnl_at
    else:
        pnl_at = now
    label = name or prev_name or profile.get("top_city") or "unknown"

    conn.execute("""
        INSERT INTO profiles (wallet, name, strategy, ladder_ratio,
            longshot_ratio, certain_ratio, weather_ratio, median_entry,
            top_city, city_concentration, cities_json, topics_json, top_topic,
            topic_concentration, total_trades, buy_trades, updated_at, pnl,
            pnl_updated_at, last_trade_at, first_trade_at, trades_30d,
            buys_30d, volume_30d, active_days_30d, trades_per_month,
            period_days, playbook)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(wallet) DO UPDATE SET
            name=excluded.name, strategy=excluded.strategy,
            ladder_ratio=excluded.ladder_ratio,
            longshot_ratio=excluded.longshot_ratio,
            certain_ratio=excluded.certain_ratio,
            weather_ratio=excluded.weather_ratio,
            median_entry=excluded.median_entry, top_city=excluded.top_city,
            city_concentration=excluded.city_concentration,
            cities_json=excluded.cities_json,
            topics_json=excluded.topics_json, top_topic=excluded.top_topic,
            topic_concentration=excluded.topic_concentration,
            total_trades=excluded.total_trades,
            buy_trades=excluded.buy_trades, updated_at=excluded.updated_at,
            pnl=excluded.pnl, pnl_updated_at=excluded.pnl_updated_at,
            last_trade_at=excluded.last_trade_at,
            first_trade_at=excluded.first_trade_at,
            trades_30d=excluded.trades_30d, buys_30d=excluded.buys_30d,
            volume_30d=excluded.volume_30d,
            active_days_30d=excluded.active_days_30d,
            trades_per_month=excluded.trades_per_month,
            period_days=excluded.period_days, playbook=excluded.playbook
    """, (
        wallet,
        label,
        profile["strategy"],
        profile["ladder_ratio"],
        profile["longshot_ratio"],
        profile["certain_ratio"],
        profile["weather_ratio"],
        profile["median_entry"],
        profile["top_city"],
        profile["city_concentration"],
        json.dumps(profile.get("cities", {})),
        json.dumps(profile.get("topics", {})),
        profile.get("top_topic"),
        profile.get("topic_concentration"),
        profile["total_trades"],
        profile["buy_trades"],
        now,
        pnl,
        pnl_at,
        act.get("last_trade_at"),
        act.get("first_trade_at"),
        act.get("trades_30d"),
        act.get("buys_30d"),
        act.get("volume_30d"),
        act.get("active_days_30d"),
        act.get("trades_per_month"),
        act.get("period_days"),
        playbook,
    ))
    conn.commit()
    conn.close()
    profile["pnl"] = pnl
    profile["name"] = label
    return profile


def profile_from_trades(trades: list[dict], pnl: float | None = None) -> dict:
    profile = classify_wallet(trades)
    profile.update(activity_stats(trades))
    if pnl is not None:
        profile["pnl"] = pnl
    return profile


def upsert_profile(wallet: str, name: str | None = None,
                   max_trades: int = 500) -> dict:
    """Вытаскивает сделки, классифицирует и сохраняет профиль в БД."""
    trades = get_all_trades(wallet, max_trades=max_trades)
    profile = profile_from_trades(trades)
    return _save_profile(wallet, profile, name=name)


def is_playbook_profile(profile: dict, min_weather: float | None = None) -> bool:
    """Кошелёк годится как образец стратегии, а не certain-скупка решённых."""
    wr = float(profile.get("weather_ratio") or 0)
    if wr < (WEATHER_MIN_RATIO if min_weather is None else min_weather):
        return False
    strat = profile.get("strategy") or "unknown"
    if strat in ("ladder", "value", "specialist", "longshot", "momentum"):
        return True
    if strat == "mixed" and float(profile.get("city_concentration") or 0) >= 0.4:
        return True
    return False


def screen_wallet(
    wallet: str,
    name: str | None = None,
    *,
    max_trades: int = 150,
    min_buys: int = 1,
) -> dict | None:
    """Сохраняет профиль любого кошелька с >= min_buys BUY.

    Погодный гейт (weather_ratio >= WEATHER_MIN_RATIO) снят — MVP §3.1:
    профиль сохраняется для любого кошелька с >= 1 BUY; min_buys остаётся
    только как анти-туристический фильтр для harvest-пути.
    """
    trades = get_all_trades(wallet, max_trades=max_trades)
    profile = profile_from_trades(trades)
    if int(profile.get("buy_trades") or 0) < min_buys:
        return None
    return _save_profile(wallet, profile, name=name)


# Прежнее имя без погодного фильтра (обратная совместимость).
screen_weather_wallet = screen_wallet


def is_weather_wallet(wallet: str, max_trades: int = 200) -> bool:
    """Проверяет, является ли кошелёк погодным (доля temperature >= порога)."""
    trades = get_all_trades(wallet, max_trades=max_trades)
    profile = classify_wallet(trades)
    return profile.get("weather_ratio", 0) >= WEATHER_MIN_RATIO


def collect_known(verbose: bool = True) -> list[dict]:
    """Собирает известные кошельки, пропуская не-погодные."""
    results = []
    for wallet, name in KNOWN_WALLETS.items():
        try:
            profile = upsert_profile(wallet, name=name)
            is_w = profile.get("weather_ratio", 0) >= WEATHER_MIN_RATIO
            tag = "✅" if is_w else "⏭️ не погодный"
            results.append({"wallet": wallet, "name": name, **profile})
            if verbose:
                print(f"  {tag} {name}: {profile['strategy']} "
                      f"(weather={profile.get('weather_ratio', 0)}, "
                      f"median={profile['median_entry']}, "
                      f"top={profile['top_city']})")
        except Exception as e:
            if verbose:
                print(f"  ❌ {name}: {e}")
    return results


def get_all_profiles(weather_only: bool = True) -> list[dict]:
    """Возвращает профили из БД (по умолчанию только погодные)."""
    conn = _connect()
    if weather_only:
        rows = conn.execute(
            "SELECT * FROM profiles WHERE weather_ratio >= ? ORDER BY median_entry",
            (WEATHER_MIN_RATIO,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM profiles ORDER BY median_entry").fetchall()
    conn.close()
    cols = _profile_columns()
    return [dict(zip(cols, r)) for r in rows]


def add_wallet(wallet: str, name: str | None = None) -> dict:
    """Добавить один кошелёк в БД."""
    return upsert_profile(wallet, name=name)


def refresh_queue(stale_hours: float = 24) -> list[dict]:
    """Кошельки без метрик или с устаревшим updated_at."""
    conn = _connect()
    rows = conn.execute(
        "SELECT wallet, name, updated_at, trades_30d, pnl FROM profiles"
    ).fetchall()
    conn.close()
    now = datetime.now(timezone.utc)
    out = []
    for wallet, name, updated_at, trades_30d, pnl in rows:
        stale = True
        if updated_at and trades_30d is not None:
            try:
                ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                age_h = (now - ts).total_seconds() / 3600
                stale = age_h >= stale_hours
            except ValueError:
                stale = True
        if stale or trades_30d is None:
            out.append({"wallet": wallet, "name": name, "pnl": pnl})
    return out


def refresh_wallet(wallet: str, name: str | None = None, *,
                   max_trades: int = 250, with_pnl: bool = True,
                   http=None) -> dict:
    trades = get_all_trades(wallet, max_trades=max_trades)
    pnl = fetch_pnl(wallet, http=http) if with_pnl else None
    profile = profile_from_trades(trades, pnl=pnl)
    return _save_profile(wallet, profile, name=name)


def refresh_pnl_only(wallet: str, http=None) -> float | None:
    pnl = fetch_pnl(wallet, http=http)
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    conn.execute(
        "UPDATE profiles SET pnl = ?, pnl_updated_at = ? WHERE wallet = ?",
        (pnl, now, wallet),
    )
    conn.commit()
    conn.close()
    return pnl


if __name__ == "__main__":
    print("Собираю weather-кошельки...")
    collect_known()
    print(f"\nВсего погодных профилей: {len(get_all_profiles())}")
