#!/usr/bin/env python3
"""
Polymarket Crypto TG-бот
========================
Бот показывает крипто-рынки Polymarket: каждая запись — отдельным сообщением,
листается кнопками ◀️ ▶️, с деталями (стакан / сделки / кошельки) по кнопкам.

Первичный источник — LIVE SQLite (polymarket.db); JSON-снимок — fallback.

Команды:
  /start            — справка
  /menu             — меню выбора
  /markets [актив] [таймфрейм] [тип] — рынки с пагинацией (по 1 записи)
  /updown [актив] [N] — N ближайших свечей Up/Down
  /stats            — статистика БД (P0/P1 метрики)
  /report           — сводка сбора
  /refresh          — перепарсить снимок (fallback)

Токен: tgbot_token.txt рядом со скриптом или env TG_BOT_TOKEN.

Запуск:
  /Users/alexander/agents-env/bin/python3 polymarket_tgbot.py
"""

import asyncio
import datetime
import json
import logging
import os
import threading
import time

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

import polymarket_crypto_parser as P
import polymarket_db as DB

LOG_DIR = P.BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "tgbot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("tgbot")

# подключение к БД (primary source)
DB_CONN = None


def db():
    global DB_CONN
    if DB_CONN is None:
        DB_CONN = DB.connect()
        DB.init_db(DB_CONN)
    return DB_CONN


TOKEN_FILE = P.BASE_DIR / "tgbot_token.txt"
SNAPSHOT_FILE = P.BASE_DIR / "polymarket_crypto_snapshot.json"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
HEADERS = P.HEADERS

SNAPSHOT = {"markets": [], "generated_at": None, "series_count": 0, "source": "none"}

# Хранилище рынков для callback-кнопок (Telegram лимит 64 байта на callback_data)
CALLBACK_STORE = {}
_CB_SEQ = [0]


def store_market(m):
    _CB_SEQ[0] += 1
    key = str(_CB_SEQ[0])
    CALLBACK_STORE[key] = m
    if len(CALLBACK_STORE) > 3000:
        for k in list(CALLBACK_STORE)[:1000]:
            CALLBACK_STORE.pop(k, None)
    return key


# ---------- меню-выбор ----------

ASSETS = ["btc", "eth", "sol", "xrp", "doge", "bnb"]
TFS = ["5m", "15m", "4h", "hourly", "daily", "weekly", "monthly"]
TYPES = [
    ("up-or-down", "📈 Up/Down"),
    ("hit-price", "🎯 Hit-price"),
    ("multi-strikes", "📊 Multi-strike"),
    ("neg-risk", "⚖️ Neg-risk"),
]
ASSET_EMOJI = {"btc": "🟠", "eth": "⚫", "sol": "🟣", "xrp": "🔵", "doge": "🐶", "bnb": "🟡"}


def menu_kb():
    rows = [[InlineKeyboardButton(label, callback_data=f"pick|{slug}")] for slug, label in TYPES]
    return InlineKeyboardMarkup(rows)


def assets_kb(typ):
    rows, row = [], []
    for i, a in enumerate(ASSETS):
        row.append(InlineKeyboardButton(f"{ASSET_EMOJI[a]} {a.upper()}", callback_data=f"pick|{typ}|{a}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Типы", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def tf_kb(asset):
    rows, row = [], []
    for i, tf in enumerate(TFS):
        row.append(InlineKeyboardButton(tf.upper(), callback_data=f"pick|up-or-down|{asset}|{tf}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Активы", callback_data=f"pick|up-or-down")])
    return InlineKeyboardMarkup(rows)


TYPE_LABEL = dict(TYPES)

# ---------- дайджест сбора ----------

CHAT_ID_FILE = P.BASE_DIR / "tgbot_chat_id.txt"


def load_chat_id():
    try:
        if CHAT_ID_FILE.exists():
            return int(CHAT_ID_FILE.read_text().strip())
    except Exception:
        pass
    return None


def save_chat_id(cid):
    try:
        CHAT_ID_FILE.write_text(str(cid))
    except Exception:
        pass


def fmt_px(x, digits=2):
    if x is None:
        return "—"
    try:
        return f"{float(x):,.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def fmt_digest(d, title="📊 Сводка сбора"):
    t = d["totals"]
    extra = d.get("extra") or {}
    lines = [
        f"{title} — за {d['minutes']} мин",
        "",
        f"🆕 новых рынков: <b>{d['new_markets']}</b>",
        f"📈 снимков цен: <b>{d['new_snapshots']}</b>",
        f"💱 сделок: <b>{d['new_trades']}</b>",
        f"✅ резолюций: <b>{d['new_resolved']}</b>",
        "",
        f"📚 всего в БД: {t['markets']} рынков · {t['snapshots']} снимков · "
        f"{t['trades']} сделок · {t['resolved']} решено · {t['positions']} позиций",
    ]
    if extra:
        lines.append(
            f"🔥 hot: {extra.get('hot', '—')} · "
            f"⏳ unresolved past: {extra.get('unresolved_past', '—')} · "
            f"🎯 ptb: {extra.get('price_to_beat_filled', '—')}"
        )
        spots = extra.get("spots") or []
        if spots:
            spot_s = " · ".join(f"{s['asset'].upper()} {fmt_px(s['price'])}" for s in spots[:6])
            lines.append(f"💵 spot: {spot_s}")
    if d["by_asset"]:
        lines.append("")
        lines.append("<b>Снимки по активам:</b>")
        for r in d["by_asset"]:
            lines.append(f"  {(r['asset'] or '?').upper()} {r['tf']}: {r['count']}")
    if d["recent_trades"]:
        lines.append("")
        lines.append("<b>Свежие сделки:</b>")
        for tr in d["recent_trades"]:
            ts = datetime.datetime.fromtimestamp(tr["ts"]).strftime("%H:%M:%S")
            sz = tr["size"] if tr["size"] else 0
            lines.append(
                f"  {ts} {tr['side']} {tr['outcome']} px={tr['price']} "
                f"sz={sz:.0f} {tr['pseudonym'] or ''}"
            )
    return "\n".join(lines)


# ---------- расширенная статистика из LIVE DB ----------

def enrich_stats(conn):
    """Доп. метрики P0/P1 поверх DB.stats()."""
    base = DB.stats(conn)
    now = DB.now_iso()
    unresolved_past = conn.execute(
        """SELECT COUNT(*) FROM markets
           WHERE end_date < ?
             AND (resolution_status IS NULL OR resolution_status = '')""",
        (now,),
    ).fetchone()[0]
    ptb = conn.execute(
        "SELECT COUNT(*) FROM markets WHERE price_to_beat IS NOT NULL"
    ).fetchone()[0]
    hot = len(DB.get_hot_markets(conn))
    spots = []
    try:
        rows = conn.execute(
            """SELECT s.asset, s.price, s.ts, s.source
               FROM spot_ticks s
               INNER JOIN (
                 SELECT asset, MAX(ts) AS mts FROM spot_ticks GROUP BY asset
               ) t ON s.asset = t.asset AND s.ts = t.mts
               ORDER BY s.asset"""
        ).fetchall()
        spots = [
            {"asset": r[0], "price": r[1], "ts": r[2], "source": r[3]}
            for r in rows
        ]
    except Exception as e:
        log.warning("spot_ticks: %s", e)
    base.update({
        "unresolved_past": unresolved_past,
        "price_to_beat_filled": ptb,
        "hot_markets": hot,
        "spots": spots,
    })
    return base


def dig_with_extra(conn, minutes=30):
    d = DB.activity_digest(conn, minutes)
    s = enrich_stats(conn)
    d["extra"] = {
        "hot": s["hot_markets"],
        "unresolved_past": s["unresolved_past"],
        "price_to_beat_filled": s["price_to_beat_filled"],
        "spots": s["spots"],
    }
    return d


def market_row_from_db(r):
    """Кортеж SELECT → dict в формате, совместимом с parser-снимком."""
    (
        condition_id, question, series_slug, asset, recurrence, end_date,
        token_yes, token_no, volume, liquidity, outcome_prices,
        resolution_status, resolved_outcome, price_to_beat, final_price,
        bid, ask, mid,
    ) = r
    return {
        "conditionId": condition_id,
        "question": question or "",
        "series_slug": series_slug or "",
        "asset": asset or "",
        "recurrence": recurrence or "",
        "endDate": end_date or "",
        "token_yes": token_yes,
        "token_no": token_no,
        "volume": volume,
        "volumeNum": volume,
        "liquidity": liquidity,
        "outcome_prices": outcome_prices,
        "resolution_status": resolution_status,
        "resolved_outcome": resolved_outcome,
        "price_to_beat": price_to_beat,
        "final_price": final_price,
        "bid": bid,
        "ask": ask,
        "mid": mid,
    }


def load_markets_from_db(upcoming_only=True):
    """LIVE рынки из SQLite + последний bid/ask/mid из price_snapshots."""
    conn = db()
    now = DB.now_iso()
    where = "WHERE 1=1"
    params = []
    if upcoming_only:
        # активные/будущие + небольшой grace для только что закрытых
        where = "WHERE (m.end_date >= ? OR m.resolution_status IS NULL OR m.resolution_status = '')"
        # фактически: end_date ещё не прошёл OR ещё не решён — но для UI
        # берём end_date >= now-2h чтобы не тащить всю историю
        lo = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=2)).isoformat()
        where = "WHERE m.end_date >= ?"
        params = [lo]
    rows = conn.execute(
        f"""SELECT m.condition_id, m.question, m.series_slug, m.asset, m.recurrence,
                  m.end_date, m.token_yes, m.token_no, m.volume, m.liquidity,
                  m.outcome_prices, m.resolution_status, m.resolved_outcome,
                  m.price_to_beat, m.final_price,
                  (SELECT p.bid FROM price_snapshots p
                     WHERE p.condition_id=m.condition_id ORDER BY p.ts DESC LIMIT 1),
                  (SELECT p.ask FROM price_snapshots p
                     WHERE p.condition_id=m.condition_id ORDER BY p.ts DESC LIMIT 1),
                  (SELECT p.mid FROM price_snapshots p
                     WHERE p.condition_id=m.condition_id ORDER BY p.ts DESC LIMIT 1)
           FROM markets m
           {where}
           ORDER BY m.end_date""",
        params,
    ).fetchall()
    return [market_row_from_db(r) for r in rows]


def enrich_market_from_db(m):
    """Дописать resolution / ptb / final / last book из БД к market-dict."""
    cond = m.get("conditionId") or m.get("condition_id")
    if not cond:
        return m
    row = db().execute(
        """SELECT resolution_status, resolved_outcome, resolved_prices,
                  price_to_beat, final_price, volume, liquidity
           FROM markets WHERE condition_id=?""",
        (cond,),
    ).fetchone()
    if row:
        m = dict(m)
        m["resolution_status"] = row[0]
        m["resolved_outcome"] = row[1]
        m["resolved_prices"] = row[2]
        if m.get("price_to_beat") is None:
            m["price_to_beat"] = row[3]
        if m.get("final_price") is None:
            m["final_price"] = row[4]
        if m.get("volume") is None and m.get("volumeNum") is None:
            m["volume"] = row[5]
            m["volumeNum"] = row[5]
        if m.get("liquidity") is None:
            m["liquidity"] = row[6]
    # свежий mid из snapshots, если в записи нет
    if m.get("mid") is None or m.get("bid") is None:
        snap = db().execute(
            """SELECT bid, ask, mid FROM price_snapshots
               WHERE condition_id=? ORDER BY ts DESC LIMIT 1""",
            (cond,),
        ).fetchone()
        if snap:
            m = dict(m)
            if m.get("bid") is None:
                m["bid"] = snap[0]
            if m.get("ask") is None:
                m["ask"] = snap[1]
            if m.get("mid") is None:
                m["mid"] = snap[2]
    return m


# ---------- снимок / токен ----------

def load_token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return os.environ.get("TG_BOT_TOKEN", "")


def load_snapshot():
    """Primary: LIVE DB. Fallback: JSON snapshot."""
    try:
        rows = load_markets_from_db(upcoming_only=True)
        if rows:
            SNAPSHOT["markets"] = rows
            SNAPSHOT["generated_at"] = DB.now_iso()
            SNAPSHOT["series_count"] = len({r.get("series_slug") for r in rows})
            SNAPSHOT["source"] = "sqlite"
            return True
    except Exception as e:
        log.warning("load DB markets failed: %s", e)
    if SNAPSHOT_FILE.exists():
        d = json.loads(SNAPSHOT_FILE.read_text())
        SNAPSHOT["markets"] = d.get("markets", [])
        SNAPSHOT["generated_at"] = d.get("generated_at")
        SNAPSHOT["series_count"] = d.get("series_count", 0)
        SNAPSHOT["source"] = "json"
        return True
    return False


def rebuild():
    all_series = P.discover_series()
    target = [s for s in all_series if P.is_target_series(s, None, None)]
    now = datetime.datetime.now(datetime.timezone.utc)
    recs = []
    for s in target:
        try:
            for e in P.fetch_active_events(s.get("id"), now):
                for m in e.get("markets", []):
                    rec = P.market_to_record(s, m, now)
                    try:
                        ptb, fp = P.extract_event_spot_prices(e)
                        if ptb is None and fp is None:
                            ptb, fp = P.extract_event_spot_prices(m)
                        if ptb is not None:
                            rec["price_to_beat"] = ptb
                        if fp is not None:
                            rec["final_price"] = fp
                    except Exception:
                        pass
                    recs.append(rec)
        except Exception:
            continue
    SNAPSHOT["markets"] = recs
    SNAPSHOT["generated_at"] = now.isoformat()
    SNAPSHOT["series_count"] = len(target)
    SNAPSHOT["source"] = "live_parse"


# ---------- live (стакан / сделки / кошельки) ----------

def fetch_book(token_id):
    r = httpx.get(f"{CLOB}/book", params={"token_id": token_id}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_trades(condition_id, limit=50):
    r = httpx.get(f"{DATA}/trades", params={"market": condition_id, "limit": limit},
                  headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def aggregate_traders(trades, limit=15):
    agg = {}
    for t in trades:
        w = t.get("proxyWallet") or t.get("traderAddress")
        if not w:
            continue
        a = agg.get(w)
        if a is None:
            a = {"wallet": w, "pseudonym": t.get("pseudonym") or t.get("name") or "",
                 "buys": 0, "sells": 0, "buy_usd": 0.0, "sell_usd": 0.0, "net_shares": 0.0}
            agg[w] = a
        size = float(t.get("size") or 0)
        price = float(t.get("price") or 0)
        if t.get("side") == "BUY":
            a["buys"] += 1
            a["buy_usd"] += size * price
            a["net_shares"] += size
        else:
            a["sells"] += 1
            a["sell_usd"] += size * price
            a["net_shares"] -= size
    out = list(agg.values())
    for a in out:
        a["total_usd"] = round(a["buy_usd"] + a["sell_usd"], 2)
        a["buy_usd"] = round(a["buy_usd"], 2)
        a["sell_usd"] = round(a["sell_usd"], 2)
        a["net_shares"] = round(a["net_shares"], 1)
    out.sort(key=lambda x: x["total_usd"], reverse=True)
    return out[:limit]


# ---------- фильтры и форматирование ----------

def filter_markets(asset="", tf="", mtype=""):
    # подтянуть LIVE DB перед фильтром, если источник sqlite/пустой
    if SNAPSHOT["source"] in ("sqlite", "none") or not SNAPSHOT["markets"]:
        try:
            load_snapshot()
        except Exception:
            pass
    rows = SNAPSHOT["markets"]
    if asset:
        rows = [r for r in rows if r.get("asset") == asset]
    if tf:
        rows = [r for r in rows if r.get("recurrence") == tf]
    if mtype:
        rows = [r for r in rows if mtype in (r.get("series_slug") or "")]
    return sorted(rows, key=lambda r: r.get("endDate") or "")


def fmt_vol(v):
    n = float(v or 0)
    if not n:
        return "—"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{n:.0f}"


def fmt_mid(m):
    if m.get("mid") is not None:
        return f"{m['mid']:.3f}"
    return "—"


def fmt_resolution(m):
    st = (m.get("resolution_status") or "").lower()
    if st == "resolved":
        out = m.get("resolved_outcome") or "?"
        return f"✅ решено: <b>{out}</b>"
    if st:
        return f"⏳ статус: {st}"
    end = m.get("endDate") or ""
    if end and end < DB.now_iso():
        return "⚠️ просрочен, без резолюции"
    return "🟢 открыт"


def fmt_market(m, idx, total):
    m = enrich_market_from_db(m)
    mid = fmt_mid(m)
    bid = m.get("bid")
    ask = m.get("ask")
    bid_s = f"{bid:.3f}" if isinstance(bid, (int, float)) else (str(bid) if bid is not None else "—")
    ask_s = f"{ask:.3f}" if isinstance(ask, (int, float)) else (str(ask) if ask is not None else "—")
    vol = fmt_vol(m.get("volumeNum") if m.get("volumeNum") is not None else m.get("volume"))
    liq = fmt_vol(m.get("liquidity"))
    ptb = m.get("price_to_beat")
    fp = m.get("final_price")
    slug = m.get("series_slug") or ""
    kind = "свеча" if "up-or-down" in slug else (slug.split("-")[1] if "-" in slug else slug)
    lines = [
        f"🏷 <b>{(m.get('asset') or '?').upper()}</b> · {m.get('recurrence') or '?'} · <i>{kind}</i>",
        f"<b>{m.get('question') or ''}</b>",
        f"⏱ конец: <code>{(m.get('endDate') or '').replace('T', ' ')[:16]}</code>",
        f"📊 mid: <b>{mid}</b> (bid {bid_s} / ask {ask_s})",
        f"🎯 price_to_beat: <b>{fmt_px(ptb)}</b> · final: <b>{fmt_px(fp)}</b>",
        f"{fmt_resolution(m)}",
        f"💰 объём: {vol} · ликв: {liq}",
        "",
        f"<i>запись {idx}/{total} · src={SNAPSHOT.get('source')}</i>",
    ]
    return "\n".join(lines)


def market_kb(m, idx, total):
    key = store_market(m)
    rows = []
    nav = []
    asset = m.get("asset") or ""
    tf = m.get("recurrence") or ""
    if idx > 1:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"nav|{asset}|{tf}|{idx-2}"))
    nav.append(InlineKeyboardButton(f"{idx}/{total}", callback_data="noop"))
    if idx < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"nav|{asset}|{tf}|{idx}"))
    rows.append(nav)
    det = [
        InlineKeyboardButton("📖 Стакан", callback_data=f"book|{key}"),
        InlineKeyboardButton("💱 Сделки", callback_data=f"trades|{key}"),
        InlineKeyboardButton("🐋 Кошельки", callback_data=f"whales|{key}"),
        InlineKeyboardButton("📈 История", callback_data=f"history|{key}"),
    ]
    rows.append(det)
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


# ---------- обработчики ----------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    text = (
        "📊 <b>Polymarket Crypto бот</b>\n\n"
        "Показывает крипто-рынки: свечи Up/Down, hit-price, страйки.\n"
        "Источник: <b>LIVE SQLite</b> (polymarket.db).\n"
        "Выбери тип кнопкой ниже → дальше актив (для свечей ещё таймфрейм).\n\n"
        "<b>Быстрые команды:</b>\n"
        "/markets [актив] [таймфрейм] [тип] — рынки постранично\n"
        "/updown [актив] [N] — N ближайших свечей\n"
        "/stats — статистика БД\n"
        "/report — сводка сбора\n"
        "/refresh — перепарсить снимок"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=menu_kb())


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 <b>Выбери тип рынка:</b>", parse_mode="HTML", reply_markup=menu_kb())


async def cmd_markets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = (update.message.text or "").split()[1:]
    asset = args[0] if len(args) > 0 else ""
    tf = args[1] if len(args) > 1 else ""
    mtype = args[2] if len(args) > 2 else ""
    rows = filter_markets(asset, tf, mtype)
    if not rows:
        await update.message.reply_text("Ничего не нашёл. Проверь актив/таймфрейм, или /refresh.")
        return
    m = rows[0]
    await update.message.reply_text(fmt_market(m, 1, len(rows)), parse_mode="HTML",
                                    reply_markup=market_kb(m, 1, len(rows)))


async def cmd_updown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = (update.message.text or "").split()[1:]
    asset = args[0] if len(args) > 0 else "btc"
    n = int(args[1]) if len(args) > 1 else 5
    n = max(1, min(n, 20))
    rows = [r for r in filter_markets(asset, "", "up-or-down")]
    if not rows:
        await update.message.reply_text("Свечей не найдено. /refresh?")
        return
    for i, m in enumerate(rows[:n]):
        await update.message.reply_text(
            fmt_market(m, i + 1, len(rows)),
            parse_mode="HTML",
            reply_markup=market_kb(m, i + 1, len(rows)),
        )


async def cmd_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Обновляю из БД / парсера…")

    def _do():
        if load_snapshot() and SNAPSHOT["source"] == "sqlite":
            return
        rebuild()

    threading.Thread(target=_do, daemon=True).start()


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data or ""
    parts = data.split("|")

    if data == "noop":
        await q.answer()
        return

    if data == "menu":
        await q.edit_message_text("🏠 <b>Выбери тип рынка:</b>", parse_mode="HTML", reply_markup=menu_kb())
        await q.answer()
        return

    if parts[0] == "pick":
        if len(parts) == 2:
            typ = parts[1]
            await q.edit_message_text(f"{TYPE_LABEL.get(typ, typ)} — выбери актив:",
                                      parse_mode="HTML", reply_markup=assets_kb(typ))
        elif len(parts) == 3:
            typ, asset = parts[1], parts[2]
            if typ == "up-or-down":
                await q.edit_message_text(
                    f"{ASSET_EMOJI.get(asset, '')} <b>{asset.upper()}</b> · Up/Down — таймфрейм:",
                    parse_mode="HTML", reply_markup=tf_kb(asset),
                )
            else:
                rlist = filter_markets(asset, "", typ)
                if not rlist:
                    await q.answer("по этому активу таких рынков нет")
                    return
                m = rlist[0]
                await q.edit_message_text(fmt_market(m, 1, len(rlist)), parse_mode="HTML",
                                          reply_markup=market_kb(m, 1, len(rlist)))
        elif len(parts) == 4:
            _, typ, asset, tf = parts
            rlist = filter_markets(asset, tf, typ)
            if not rlist:
                await q.answer("ничего не нашлось")
                return
            m = rlist[0]
            await q.edit_message_text(fmt_market(m, 1, len(rlist)), parse_mode="HTML",
                                      reply_markup=market_kb(m, 1, len(rlist)))
        await q.answer()
        return

    if parts[0] == "nav":
        _, asset, tf, idx = parts
        idx = int(idx)
        rows = filter_markets(asset, tf, "")
        if 0 <= idx < len(rows):
            m = rows[idx]
            await q.edit_message_text(fmt_market(m, idx + 1, len(rows)), parse_mode="HTML",
                                      reply_markup=market_kb(m, idx + 1, len(rows)))
        await q.answer()
        return

    if parts[0] == "book":
        m = CALLBACK_STORE.get(parts[1])
        if m:
            m = enrich_market_from_db(m)
        token = m.get("token_yes") if m else None
        if not token:
            await q.answer("рынок не найден в кэше")
            return
        try:
            b = await asyncio.to_thread(fetch_book, token)
            bids = b.get("bids", [])[-8:]
            asks = b.get("asks", [])[:8]
            best_bid = float(bids[-1]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None
            mid = round((best_bid + best_ask) / 2, 4) if best_bid is not None and best_ask is not None else None
            txt = (
                f"📖 <b>Стакан</b>\n"
                f"{m.get('question') or ''}\n"
                f"mid=<b>{mid if mid is not None else '—'}</b> · "
                f"bid={best_bid if best_bid is not None else '—'} · "
                f"ask={best_ask if best_ask is not None else '—'}\n"
                f"🎯 ptb={fmt_px(m.get('price_to_beat'))} · final={fmt_px(m.get('final_price'))}\n"
                f"{fmt_resolution(m)}\n"
                f"посл. цена {b.get('last_trade_price')}\n\n"
            )
            txt += "<b>Bids (покупка):</b>\n" + "\n".join(
                f"  {x['price']} × {float(x['size']):,.0f}" for x in bids
            ) + "\n"
            txt += "<b>Asks (продажа):</b>\n" + "\n".join(
                f"  {x['price']} × {float(x['size']):,.0f}" for x in asks
            )
            await q.message.reply_text(txt[:4000], parse_mode="HTML")
        except Exception as e:
            await q.message.reply_text(f"стакан: {e}")
        await q.answer()
        return

    if parts[0] == "trades":
        m = CALLBACK_STORE.get(parts[1])
        cond = (m.get("conditionId") or m.get("condition_id")) if m else None
        if not cond:
            await q.answer("рынок не найден в кэше")
            return
        try:
            tr = await asyncio.to_thread(fetch_trades, cond, 20)
            if not tr:
                await q.message.reply_text("Сделок нет.")
            else:
                txt = "💱 <b>Последние сделки</b>\n\n"
                for t in tr:
                    ts = datetime.datetime.fromtimestamp(t["timestamp"]).strftime("%H:%M:%S")
                    w = (t.get("proxyWallet") or "")[:8]
                    txt += (
                        f"{ts} {t['side']:4} {t['outcome']:3} px={float(t['price']):.3f} "
                        f"sz={float(t['size']):.0f} <code>{w}…</code> {t.get('pseudonym') or ''}\n"
                    )
                await q.message.reply_text(txt[:4000], parse_mode="HTML")
        except Exception as e:
            await q.message.reply_text(f"сделки: {e}")
        await q.answer()
        return

    if parts[0] == "whales":
        m = CALLBACK_STORE.get(parts[1])
        cond = (m.get("conditionId") or m.get("condition_id")) if m else None
        if not cond:
            await q.answer("рынок не найден в кэше")
            return
        try:
            tr = await asyncio.to_thread(fetch_trades, cond, 300)
            top = aggregate_traders(tr, 12)
            if not top:
                await q.message.reply_text("Кошельков нет.")
            else:
                txt = "🐋 <b>Топ кошельков</b>\n\n"
                for t in top:
                    w = t["wallet"][:10]
                    txt += (
                        f"<code>{w}…</code> buy=${t['buy_usd']:,.0f} sell=${t['sell_usd']:,.0f} "
                        f"net={t['net_shares']:+,.0f} ({t['buys']+t['sells']} сделок) {t['pseudonym']}\n"
                    )
                await q.message.reply_text(txt[:4000], parse_mode="HTML")
        except Exception as e:
            await q.message.reply_text(f"кошельки: {e}")
        await q.answer()
        return

    if parts[0] == "history":
        m = CALLBACK_STORE.get(parts[1])
        if m:
            m = enrich_market_from_db(m)
        cond = (m.get("conditionId") or m.get("condition_id")) if m else None
        qtext = m.get("question", "") if m else ""
        if not cond:
            await q.answer("рынок не найден в кэше")
            return
        series = DB.price_series(db(), cond, limit=40)
        if not series:
            await q.message.reply_text("Истории по этому рынку ещё нет (сборщик не накопил).")
        else:
            txt = f"📈 <b>История цены</b>\n{qtext}\n"
            txt += f"🎯 ptb={fmt_px(m.get('price_to_beat'))} · final={fmt_px(m.get('final_price'))}\n"
            txt += f"{fmt_resolution(m)}\n\n"
            prev = None
            for s in series:
                ts = (s["ts"] or "")[11:19]
                mid = f"{s['mid']:.3f}" if s.get("mid") is not None else "—"
                bid = f"{s['bid']:.3f}" if s.get("bid") is not None else "—"
                ask = f"{s['ask']:.3f}" if s.get("ask") is not None else "—"
                arrow = ""
                if prev is not None and s.get("mid") is not None:
                    arrow = " ↑" if s["mid"] > prev else (" ↓" if s["mid"] < prev else " →")
                txt += f"{ts}  mid={mid} ({bid}/{ask}){arrow}\n"
                prev = s.get("mid")
            txt += f"\nточек: {len(series)} (последние)"
            await q.message.reply_text(txt[:4000], parse_mode="HTML")
        await q.answer()
        return

    await q.answer()


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = enrich_stats(db())
    spots = s.get("spots") or []
    spot_lines = "\n".join(
        f"  {(x['asset'] or '?').upper()}: <b>{fmt_px(x['price'])}</b> "
        f"<i>({x.get('source') or '?'} · {(x.get('ts') or '')[11:19]})</i>"
        for x in spots
    ) or "  —"
    txt = (
        f"📊 <b>БД статистика</b> (LIVE SQLite)\n\n"
        f"рынков: <b>{s['markets']}</b>\n"
        f"снимков цен: <b>{s['snapshots']}</b>\n"
        f"сделок: <b>{s['trades']}</b>\n"
        f"позиций: {s['positions']}\n"
        f"решено: <b>{s['resolved']}</b>\n"
        f"⏳ unresolved past: <b>{s['unresolved_past']}</b>\n"
        f"🎯 price_to_beat заполнен: <b>{s['price_to_beat_filled']}</b>\n"
        f"🔥 hot-рынков: <b>{s['hot_markets']}</b>\n\n"
        f"<b>Spot (spot_ticks):</b>\n{spot_lines}\n\n"
        f"кэш бота: {SNAPSHOT.get('source')} · {SNAPSHOT.get('generated_at')}"
    )
    await update.message.reply_text(txt, parse_mode="HTML")


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    save_chat_id(update.effective_chat.id)
    d = dig_with_extra(db(), 30)
    await update.message.reply_text(fmt_digest(d), parse_mode="HTML")


async def auto_digest(ctx: ContextTypes.DEFAULT_TYPE):
    cid = load_chat_id()
    if not cid:
        return
    d = dig_with_extra(db(), 30)
    try:
        await ctx.bot.send_message(cid, fmt_digest(d), parse_mode="HTML")
    except Exception as e:
        log.error("дайджест: %s", e)


def main():
    token = load_token()
    if not token:
        print("Токен не найден. Создай tgbot_token.txt или задай TG_BOT_TOKEN.")
        return

    if not load_snapshot():
        print("БД/снимка нет — парсю при старте...")
        rebuild()
    print(f"Загружено рынков: {len(SNAPSHOT['markets'])} (src={SNAPSHOT.get('source')})")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("markets", cmd_markets))
    app.add_handler(CommandHandler("updown", cmd_updown))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CallbackQueryHandler(on_callback))

    app.job_queue.run_repeating(auto_digest, interval=1800, first=60)

    log.info("Бот запущен (long polling, src=%s).", SNAPSHOT.get("source"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
