#!/usr/bin/env python3
"""
Polymarket DB — SQLite-слой для хранения собираемых данных.
============================================================
Таблицы:
  markets         — статичные атрибуты рынка + резолюция (исход)
  price_snapshots — временной ряд цен (bid/ask/mid/volume/liquidity) для бектестов
  trades          — сделки (сторона, исход, цена, размер, кошелёк, псевдоним)
  positions       — открытые позиции кошельков (по адресу)

Ноль внешних зависимостей — только stdlib sqlite3.
"""

import datetime
import json
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "polymarket.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    condition_id      TEXT PRIMARY KEY,
    gamma_id          INTEGER,
    question          TEXT,
    series_slug       TEXT,
    asset             TEXT,
    recurrence        TEXT,
    end_date          TEXT,
    outcomes          TEXT,
    token_yes         TEXT,
    token_no          TEXT,
    volume            REAL,
    liquidity         REAL,
    outcome_prices    TEXT,
    resolution_status TEXT,
    resolved_outcome  TEXT,
    resolved_prices   TEXT,
    price_to_beat     REAL,
    final_price       REAL,
    first_seen        TEXT,
    last_seen         TEXT
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    ts           TEXT NOT NULL,
    bid          REAL,
    ask          REAL,
    mid          REAL,
    volume       REAL,
    liquidity    REAL,
    last_trade   REAL,
    bid_size     REAL,
    ask_size     REAL,
    UNIQUE(condition_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_price_cond_ts ON price_snapshots(condition_id, ts);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    ts           INTEGER NOT NULL,
    side         TEXT,
    outcome      TEXT,
    size         REAL,
    price        REAL,
    wallet       TEXT,
    pseudonym    TEXT,
    tx_hash      TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_trades_cond_ts ON trades(condition_id, ts);
CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades(wallet);

CREATE TABLE IF NOT EXISTS positions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet       TEXT NOT NULL,
    condition_id TEXT,
    asset        TEXT,
    outcome      TEXT,
    size         REAL,
    avg_price    REAL,
    cur_price    REAL,
    current_value REAL,
    cash_pnl     REAL,
    realized_pnl REAL,
    percent_pnl  REAL,
    total_bought REAL,
    ts           INTEGER,
    UNIQUE(wallet, condition_id, outcome)
);
CREATE INDEX IF NOT EXISTS idx_positions_wallet ON positions(wallet);

CREATE TABLE IF NOT EXISTS spot_ticks (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    asset  TEXT NOT NULL,
    ts     TEXT NOT NULL,
    price  REAL NOT NULL,
    source TEXT,
    UNIQUE(asset, ts, source)
);
CREATE INDEX IF NOT EXISTS idx_spot_asset_ts ON spot_ticks(asset, ts);
"""

# колонки markets, добавленные после первой версии (для миграции существующей БД)
MARKET_MIGRATIONS = {
    "gamma_id": "INTEGER",
    "outcome_prices": "TEXT",
    "resolution_status": "TEXT",
    "resolved_outcome": "TEXT",
    "resolved_prices": "TEXT",
    "price_to_beat": "REAL",
    "final_price": "REAL",
}

SNAPSHOT_MIGRATIONS = {
    "bid_size": "REAL",
    "ask_size": "REAL",
    "poll_ts": "TEXT",
    "quote_age_ms": "REAL",
}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def connect(db_path=None):
    db = Path(db_path) if db_path else DEFAULT_DB
    conn = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _migrate(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(markets)")]
    for name, typ in MARKET_MIGRATIONS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE markets ADD COLUMN {name} {typ}")
    scols = [r[1] for r in conn.execute("PRAGMA table_info(price_snapshots)")]
    for name, typ in SNAPSHOT_MIGRATIONS.items():
        if name not in scols:
            conn.execute(f"ALTER TABLE price_snapshots ADD COLUMN {name} {typ}")
    # positions: если старая схема (без cur_price) — пересоздать (данных ещё нет)
    try:
        pcols = [r[1] for r in conn.execute("PRAGMA table_info(positions)")]
        if pcols and "cur_price" not in pcols:
            conn.execute("DROP TABLE positions")
    except Exception:
        pass
    conn.commit()


def init_db(conn):
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(SCHEMA)  # повторно: пересоздаст positions, если была дропнута
    conn.commit()


def _f(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _j(x):
    """Сериализовать список/строку в JSON-строку для хранения."""
    if x is None:
        return None
    if isinstance(x, str):
        return x
    return json.dumps(x)


def resolve_outcome(outcomes, prices):
    """Победивший исход: индекс с ценой 1.0 в outcomePrices."""
    if not outcomes or not prices:
        return None
    try:
        prices = json.loads(prices) if isinstance(prices, str) else prices
        outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
    except (TypeError, json.JSONDecodeError):
        return None
    for i, p in enumerate(prices):
        try:
            if float(p) >= 0.99 and i < len(outcomes):
                return outcomes[i]
        except (TypeError, ValueError):
            continue
    return None


def upsert_market(conn, m):
    """Добавить/обновить рынок. m — dict из market_to_record парсера."""
    ts = now_iso()
    conn.execute(
        """INSERT INTO markets
           (condition_id, gamma_id, question, series_slug, asset, recurrence, end_date,
            outcomes, token_yes, token_no, volume, liquidity, outcome_prices,
            resolution_status, resolved_outcome, resolved_prices,
            price_to_beat, final_price, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(condition_id) DO UPDATE SET
             gamma_id=COALESCE(excluded.gamma_id, markets.gamma_id),
             question=excluded.question, end_date=excluded.end_date,
             volume=excluded.volume, liquidity=excluded.liquidity,
             outcome_prices=excluded.outcome_prices,
             price_to_beat=COALESCE(excluded.price_to_beat, markets.price_to_beat),
             final_price=COALESCE(excluded.final_price, markets.final_price),
             last_seen=excluded.last_seen""",
        (
            m.get("conditionId"),
            m.get("gamma_id"),
            m.get("question"),
            m.get("series_slug"),
            m.get("asset"),
            m.get("recurrence"),
            m.get("endDate"),
            _j(m.get("outcomes")),
            m.get("token_yes"),
            m.get("token_no"),
            m.get("volumeNum") if m.get("volumeNum") is not None else m.get("volume"),
            _f(m.get("liquidity")),
            _j(m.get("outcome_prices")),
            m.get("resolution_status"),
            m.get("resolved_outcome"),
            _j(m.get("resolved_prices")),
            _f(m.get("price_to_beat")),
            _f(m.get("final_price")),
            ts,
            ts,
        ),
    )


def mark_resolution(conn, condition_id, prices, status="resolved", outcome=None,
                   price_to_beat=None, final_price=None):
    conn.execute(
        """UPDATE markets SET resolution_status=?, resolved_outcome=COALESCE(?, resolved_outcome),
           resolved_prices=COALESCE(?, resolved_prices),
           price_to_beat=COALESCE(?, price_to_beat),
           final_price=COALESCE(?, final_price),
           last_seen=?
           WHERE condition_id=?""",
        (status, outcome, _j(prices), _f(price_to_beat), _f(final_price), now_iso(), condition_id),
    )


def update_market_prices(conn, condition_id, price_to_beat=None, final_price=None):
    """Обновить spot-цены (priceToBeat / finalPrice) без смены резолюции."""
    if price_to_beat is None and final_price is None:
        return
    conn.execute(
        """UPDATE markets SET
             price_to_beat=COALESCE(?, price_to_beat),
             final_price=COALESCE(?, final_price),
             last_seen=?
           WHERE condition_id=?""",
        (_f(price_to_beat), _f(final_price), now_iso(), condition_id),
    )


def snapshot_price(conn, condition_id, bid, ask, mid, volume, liquidity, last_trade,
                  bid_size=None, ask_size=None, ts=None, poll_ts=None, quote_age_ms=None):
    ts = ts or now_iso()
    poll_ts = poll_ts or now_iso()  # when WE sampled the book
    conn.execute(
        """INSERT OR IGNORE INTO price_snapshots
           (condition_id, ts, bid, ask, mid, volume, liquidity, last_trade, bid_size, ask_size,
            poll_ts, quote_age_ms)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (condition_id, ts, _f(bid), _f(ask), _f(mid), _f(volume), _f(liquidity),
         _f(last_trade), _f(bid_size), _f(ask_size), poll_ts, _f(quote_age_ms)),
    )



def insert_spot_tick(conn, asset, price, source, ts=None):
    """Record external spot price (Binance/CoinGecko/Bybit)."""
    if not asset or price is None:
        return
    ts = ts or now_iso()
    conn.execute(
        """INSERT OR IGNORE INTO spot_ticks (asset, ts, price, source)
           VALUES (?,?,?,?)""",
        (str(asset).lower(), ts, _f(price), source),
    )


def insert_trades(conn, condition_id, trades):
    """trades — список dict из Data API /trades."""
    n = 0
    for t in trades:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO trades
                   (condition_id, ts, side, outcome, size, price, wallet, pseudonym, tx_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    condition_id,
                    int(t.get("timestamp") or 0),
                    t.get("side"),
                    t.get("outcome"),
                    _f(t.get("size")),
                    _f(t.get("price")),
                    t.get("proxyWallet"),
                    t.get("pseudonym") or t.get("name"),
                    t.get("transactionHash"),
                ),
            )
            if cur.rowcount and cur.rowcount > 0:
                n += 1
        except Exception:
            continue
    conn.commit()
    return n


def upsert_positions(conn, positions):
    """positions — список dict {wallet, condition_id, asset, outcome, size, avg_price, ...}."""
    n = 0
    for p in positions:
        try:
            conn.execute(
                """INSERT INTO positions
                   (wallet, condition_id, asset, outcome, size, avg_price, cur_price,
                    current_value, cash_pnl, realized_pnl, percent_pnl, total_bought, ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(wallet, condition_id, outcome) DO UPDATE SET
                     size=excluded.size, avg_price=excluded.avg_price,
                     cur_price=excluded.cur_price, current_value=excluded.current_value,
                     cash_pnl=excluded.cash_pnl, realized_pnl=excluded.realized_pnl,
                     percent_pnl=excluded.percent_pnl, total_bought=excluded.total_bought,
                     ts=excluded.ts""",
                (
                    p.get("wallet"), p.get("condition_id"), p.get("asset"), p.get("outcome"),
                    _f(p.get("size")), _f(p.get("avg_price")), _f(p.get("cur_price")),
                    _f(p.get("current_value")), _f(p.get("cash_pnl")), _f(p.get("realized_pnl")),
                    _f(p.get("percent_pnl")), _f(p.get("total_bought")), int(p.get("ts") or 0),
                ),
            )
            n += 1
        except Exception:
            continue
    conn.commit()
    return n


# ---------- чтение (для бектеста) ----------

def price_series(conn, condition_id, limit=None):
    q = "SELECT ts, bid, ask, mid, volume, liquidity, last_trade FROM price_snapshots WHERE condition_id=? ORDER BY ts"
    rows = conn.execute(q, (condition_id,)).fetchall()
    if limit:
        rows = rows[-limit:]
    return [
        {"ts": r[0], "bid": r[1], "ask": r[2], "mid": r[3],
         "volume": r[4], "liquidity": r[5], "last_trade": r[6]}
        for r in rows
    ]


RECURRENCE_MINUTES = {
    "5m": 5, "15m": 15, "hourly": 60, "1h": 60, "4h": 240,
    "daily": 1440, "weekly": 10080, "monthly": 43200,
}


def recurrence_duration_minutes(recurrence):
    if not recurrence:
        return None
    key = str(recurrence).strip().lower()
    if key in RECURRENCE_MINUTES:
        return RECURRENCE_MINUTES[key]
    return RECURRENCE_MINUTES.get(key.replace(" ", ""))


def get_hot_markets(conn, window_minutes=30, grace_minutes=2):
    """Горячие рынки: полный window по duration (5m/15m с start) + grace после end."""
    now = datetime.datetime.now(datetime.timezone.utc)
    max_duration = max(RECURRENCE_MINUTES.values())
    horizon = max(int(window_minutes), max_duration)
    lo = (now - datetime.timedelta(minutes=max_duration + grace_minutes)).isoformat()
    hi = (now + datetime.timedelta(minutes=horizon)).isoformat()
    rows = conn.execute(
        "SELECT condition_id, token_yes, token_no, asset, recurrence, question, end_date "
        "FROM markets WHERE end_date >= ? AND end_date <= ?",
        (lo, hi),
    ).fetchall()
    out = []
    for r in rows:
        end_raw = r[6]
        if not end_raw:
            continue
        try:
            end = datetime.datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if end.tzinfo is None:
            end = end.replace(tzinfo=datetime.timezone.utc)
        duration = recurrence_duration_minutes(r[4]) or int(window_minutes)
        effective = max(int(window_minutes), int(duration))
        start = end - datetime.timedelta(minutes=duration)
        # hot: end in [now, now+effective] OR currently in window [start, end+grace]
        in_future_window = now <= end <= now + datetime.timedelta(minutes=effective)
        in_active_window = (start <= now <= end + datetime.timedelta(minutes=grace_minutes))
        if not (in_future_window or in_active_window):
            continue
        out.append({
            "condition_id": r[0], "token_yes": r[1], "token_no": r[2], "asset": r[3],
            "recurrence": r[4], "question": r[5], "end_date": r[6],
        })
    return out


def unresolved_markets(conn, limit=200, offset=0):
    """Просроченные рынки без resolution_status (для reconcile).
    IMPORTANT: compare end_date to now_iso() (ISO-8601), NOT sqlite datetime('now'),
    because markets.end_date is stored like 2026-09-28T18:05:00Z and lexicographic
    compare against 'YYYY-MM-DD HH:MM:SS' skips recent UTC ISO rows.
    """
    rows = conn.execute(
        """SELECT condition_id, gamma_id, question, end_date, outcome_prices,
                  asset, recurrence, series_slug
           FROM markets
           WHERE end_date < ?
             AND (resolution_status IS NULL OR resolution_status = '')
           ORDER BY end_date DESC
           LIMIT ? OFFSET ?""",
        (now_iso(), int(limit), int(offset)),
    ).fetchall()
    return [
        {
            "condition_id": r[0],
            "gamma_id": r[1],
            "question": r[2],
            "end_date": r[3],
            "outcome_prices": r[4],
            "asset": r[5],
            "recurrence": r[6],
            "series_slug": r[7],
        }
        for r in rows
    ]



def top_wallets(conn, limit=100):
    """Адреса с наибольшей активностью в сделках (для сбора позиций)."""
    rows = conn.execute(
        "SELECT wallet, COUNT(*) c FROM trades WHERE wallet IS NOT NULL "
        "GROUP BY wallet ORDER BY c DESC LIMIT ?", (limit,),
    ).fetchall()
    return [r[0] for r in rows]


def stats(conn):
    m = conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0]
    p = conn.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
    t = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    pos = conn.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
    res = conn.execute("SELECT COUNT(*) FROM markets WHERE resolution_status='resolved'").fetchone()[0]
    return {"markets": m, "snapshots": p, "trades": t, "positions": pos, "resolved": res}


def activity_digest(conn, minutes=30):
    """Предметная сводка: что собрано за последние N минут по каждому разделу."""
    now = datetime.datetime.now(datetime.timezone.utc)
    since_iso = (now - datetime.timedelta(minutes=minutes)).isoformat()
    since_unix = int((now - datetime.timedelta(minutes=minutes)).timestamp())

    new_markets = conn.execute(
        "SELECT COUNT(*) FROM markets WHERE first_seen >= ?", (since_iso,)
    ).fetchone()[0]
    new_snaps = conn.execute(
        "SELECT COUNT(*) FROM price_snapshots WHERE ts >= ?", (since_iso,)
    ).fetchone()[0]
    new_trades = conn.execute(
        "SELECT COUNT(*) FROM trades WHERE ts >= ?", (since_unix,)
    ).fetchone()[0]
    new_res = conn.execute(
        "SELECT COUNT(*) FROM markets WHERE resolution_status='resolved' AND last_seen >= ?", (since_iso,)
    ).fetchone()[0]

    by_asset = conn.execute(
        """SELECT m.asset, m.recurrence, COUNT(*) c
           FROM price_snapshots p JOIN markets m ON m.condition_id = p.condition_id
           WHERE p.ts >= ?
           GROUP BY m.asset, m.recurrence ORDER BY c DESC LIMIT 14""",
        (since_iso,),
    ).fetchall()

    recent_trades = conn.execute(
        """SELECT t.outcome, t.side, t.price, t.size, t.pseudonym, t.ts
           FROM trades t WHERE t.ts >= ? ORDER BY t.ts DESC LIMIT 5""",
        (since_unix,),
    ).fetchall()

    return {
        "minutes": minutes,
        "since": since_iso,
        "new_markets": new_markets,
        "new_snapshots": new_snaps,
        "new_trades": new_trades,
        "new_resolved": new_res,
        "by_asset": [{"asset": r[0], "tf": r[1], "count": r[2]} for r in by_asset],
        "recent_trades": [
            {"outcome": r[0], "side": r[1], "price": r[2], "size": r[3],
             "pseudonym": r[4], "ts": r[5]}
            for r in recent_trades
        ],
        "totals": stats(conn),
    }
