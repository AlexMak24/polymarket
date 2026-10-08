#!/usr/bin/env python3
"""Inventory scan of ~/projects/polymarket/strategies bots."""
import json, os, sqlite3, csv, glob, datetime

BASE = os.path.expanduser("~/projects/polymarket/strategies")

def jload(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception as e:
        return {"__err__": str(e)}

def dbval(path, sql):
    try:
        c = sqlite3.connect(path); cur = c.cursor()
        cur.execute(sql); r = cur.fetchone(); c.close()
        return r[0] if r else None
    except Exception as e:
        return f"err:{e}"

def rowdicts(path, sql):
    try:
        c = sqlite3.connect(path); c.row_factory = sqlite3.Row; cur = c.cursor()
        cur.execute(sql); rows = [dict(r) for r in cur.fetchall()]; c.close()
        return rows
    except Exception as e:
        return [{"__err__": str(e)}]

out = {}

# ---------- weather (main bot) ----------
w = {}
tj = jload(f"{BASE}/weather/data/trade_journal.json")
if isinstance(tj, list):
    pnl = sum(t.get("pnl", 0) for t in tj if isinstance(t, dict))
    won = sum(1 for t in tj if t.get("won"))
    w["journal_trades"] = len(tj)
    w["journal_pnl"] = round(pnl, 2)
    w["journal_won"] = won
    if tj:
        last = max(t.get("resolved_at","") for t in tj)
        w["journal_last_resolved"] = last
st = jload(f"{BASE}/weather/data/state.json")
if isinstance(st, dict) and "__err__" not in st:
    w["balance"] = st.get("balance"); w["starting"] = st.get("starting_balance")
    w["total_trades"] = st.get("total_trades"); w["wins"] = st.get("wins"); w["losses"] = st.get("losses")
wr = jload(f"{BASE}/weather/data/win_rates.json")
if isinstance(wr, dict) and "__err__" not in wr:
    w["win_rates_keys"] = list(wr.keys())[:20]
mktfiles = glob.glob(f"{BASE}/weather/data/markets/*.json")
w["market_files"] = len(mktfiles)
# learning trade_log
tl = jload(f"{BASE}/weather/data/learning/trade_log.json")
if isinstance(tl, list):
    w["learning_trade_log"] = len(tl)
out["weather"] = w

# ---------- hrrr-metar ----------
h = {}
hst = jload(f"{BASE}/hrrr-metar/data/state.json")
if isinstance(hst, dict) and "__err__" not in hst:
    h.update(hst)
hmkt = glob.glob(f"{BASE}/hrrr-metar/data/markets/*.json")
h["market_files"] = len(hmkt)
open_pos = 0; resolved = 0; res_pnl = 0.0
for mf in hmkt:
    d = jload(mf)
    if not isinstance(d, dict) or "__err__" in d:
        continue
    stt = d.get("status") or d.get("state") or d.get("resolved")
    if stt in (None, "open", "pending", "partial", "active"):
        open_pos += 1
    elif stt in ("resolved", "closed", "settled") or d.get("resolved_at") or d.get("closed_at"):
        resolved += 1
        p = d.get("pnl") or d.get("realized_pnl") or d.get("profit") or 0
        if isinstance(p, (int, float)):
            res_pnl += p
h["markets_open"] = open_pos; h["markets_resolved"] = resolved; h["markets_resolved_pnl"] = round(res_pnl, 2)
out["hrrr-metar"] = h

# ---------- balles-edge ----------
b = jload(f"{BASE}/balles-edge/data/paper_portfolio_weather.json")
if isinstance(b, dict) and "__err__" not in b:
    out["balles-edge"] = {
        "bankroll": b.get("bankroll"),
        "initial_bankroll": b.get("initial_bankroll"),
        "positions": len(b.get("positions", [])),
        "closed_trades": len(b.get("closed_trades", [])),
        "keys": [k for k in b.keys() if k not in ("positions", "closed_trades")],
    }
    # pull summary scalars
    for k in b.keys():
        if k in ("positions", "closed_trades"):
            continue
        v = b[k]
        if isinstance(v, (int, float, str, bool)) or v is None:
            out["balles-edge"][k] = v
else:
    out["balles-edge"] = {"__err__": b.get("__err__")}

# ---------- aadixd200-weather ----------
a = {}
a["trades_rows"] = dbval(f"{BASE}/aadixd200-weather/paper_trades.db", "SELECT COUNT(*) FROM trades")
a["markets_rows"] = dbval(f"{BASE}/aadixd200-weather/paper_trades.db", "SELECT COUNT(*) FROM markets")
a["bankroll"] = rowdicts(f"{BASE}/aadixd200-weather/paper_trades.db", "SELECT * FROM bankroll")
a["scan_log_last"] = rowdicts(f"{BASE}/aadixd200-weather/paper_trades.db", "SELECT * FROM scan_log ORDER BY rowid DESC LIMIT 1")
out["aadixd200-weather"] = a

# ---------- riekert-poc ----------
rk = {}
for dbn in ["trading", "trading_additive", "trading_multiplicative"]:
    p = f"{BASE}/riekert-poc/data/{dbn}.db"
    rows = rowdicts(p, "SELECT * FROM trades ORDER BY rowid DESC LIMIT 3")
    # schema columns for pnl
    c = sqlite3.connect(p); cur = c.cursor(); cur.execute("PRAGMA table_info(trades)"); cols = [r[1] for r in cur.fetchall()]; c.close()
    pnlsum = dbval(p, "SELECT SUM(pnl) FROM trades") if "pnl" in cols else None
    rk[dbn] = {"cols": cols, "last3": rows, "pnl_sum": pnlsum,
               "n": dbval(p, "SELECT COUNT(*) FROM trades")}
out["riekert-poc"] = rk

# ---------- mihirm9-weather ----------
def csv_count(path):
    try:
        with open(path) as f:
            return sum(1 for _ in f) - 1
    except Exception:
        return 0

mi = {}
mi["trades_csv"] = csv_count(f"{BASE}/mihirm9-weather/logs/trades.csv")
mi["resolved_csv"] = csv_count(f"{BASE}/mihirm9-weather/logs/resolved_trades.csv")
mi["positions_csv"] = csv_count(f"{BASE}/mihirm9-weather/logs/positions.csv")
ts = jload(f"{BASE}/mihirm9-weather/logs/tracker_state.json")
if isinstance(ts, dict) and "__err__" not in ts:
    mi["saved_at"] = ts.get("saved_at"); mi["daily_realized"] = ts.get("daily_realized"); mi["daily_pending"] = ts.get("daily_pending")
    mi["orders"] = len(ts.get("orders", {}))
# resolved pnl sum
try:
    with open(f"{BASE}/mihirm9-weather/logs/resolved_trades.csv") as f:
        r = csv.DictReader(f); pnl = 0.0; n=0
        for row in r:
            try: pnl += float(row["pnl"]); n += 1
            except: pass
        mi["resolved_pnl_sum"] = round(pnl, 2); mi["resolved_n"] = n
except Exception as e:
    mi["resolved_err"] = str(e)
out["mihirm9-weather"] = mi

# ---------- surferx-ladder ----------
su = {}
su["trades_csv"] = csv_count(f"{BASE}/surferx-ladder/logs/trades.csv")
su["resolved_csv"] = csv_count(f"{BASE}/surferx-ladder/logs/resolved_trades.csv")
su["positions_csv"] = csv_count(f"{BASE}/surferx-ladder/logs/positions.csv")
ts2 = jload(f"{BASE}/surferx-ladder/logs/tracker_state.json")
if isinstance(ts2, dict) and "__err__" not in ts2:
    su["saved_at"] = ts2.get("saved_at"); su["daily_realized"] = ts2.get("daily_realized"); su["daily_pending"] = ts2.get("daily_pending")
    su["orders"] = len(ts2.get("orders", {}))
try:
    with open(f"{BASE}/surferx-ladder/logs/resolved_trades.csv") as f:
        r = csv.DictReader(f); pnl = 0.0; n=0
        for row in r:
            try: pnl += float(row["pnl"]); n += 1
            except: pass
        su["resolved_pnl_sum"] = round(pnl, 2); su["resolved_n"] = n
except Exception as e:
    su["resolved_err"] = str(e)
out["surferx-ladder"] = su

# ---------- risedownlabs ----------
rd = jload(f"{BASE}/risedownlabs-weather/data/state.json")
out["risedownlabs-weather"] = rd if isinstance(rd, dict) else {"__err__": str(rd)}

# ---------- guillermo / moonsat ----------
for nm in ["guillermo-weather", "moonsat-weather"]:
    s = jload(f"{BASE}/{nm}/simulation.json")
    if isinstance(s, dict) and "__err__" not in s:
        out[nm] = {k: s[k] for k in s if k in ("balance","starting_balance","total_trades","wins","losses","peak_balance")}
        out[nm]["positions_n"] = len(s.get("positions", {}))
        out[nm]["trades_n"] = len(s.get("trades", []))
    else:
        out[nm] = {"__err__": s}

# ---------- poly-arbitrage ----------
pa = {}
for fn in ["backtest_summary.json","backtest_enhanced_summary.json","live_scan_summary.json","scan_summary.json","bot_config.json"]:
    d = jload(f"{BASE}/poly-arbitrage/{fn}")
    pa[fn] = d if isinstance(d, dict) else {"__err__": str(d)}
out["poly-arbitrage"] = pa

# ---------- yannbellec-ecmwf ----------
ye = {}
am = jload(f"{BASE}/yannbellec-ecmwf/data/active_markets.json")
ye["active_markets"] = am if isinstance(am, (list, dict)) else str(am)[:200]
# feature store line count
fs = f"{BASE}/yannbellec-ecmwf/data/ml/feature_store.jsonl"
try:
    with open(fs) as f:
        ye["feature_store_lines"] = sum(1 for _ in f)
except Exception:
    ye["feature_store_lines"] = 0
# realtime signals under bots/
import subprocess
ye["bots_tree"] = subprocess.run(["find", f"{BASE}/yannbellec-ecmwf/data/bots", "-type","f"], capture_output=True, text=True).stdout.splitlines()[:30]
out["yannbellec-ecmwf"] = ye

# ---------- polyweather ----------
pw = {}
cti = jload(f"{BASE}/polyweather/data/city_thread_ids.json")
pw["city_thread_ids"] = (len(cti) if isinstance(cti, (list,dict)) else str(cti)[:200])
pts = f"{BASE}/polyweather/data/probability_training_snapshots.jsonl"
try:
    with open(pts) as f:
        pw["prob_snapshots_lines"] = sum(1 for _ in f)
except Exception:
    pw["prob_snapshots_lines"] = 0
out["polyweather"] = pw

# ---------- ensemble-173 ----------
en = {}
for fn in ["favorites.csv","forecasts.csv","signals.csv","market_open_study.csv"]:
    p = f"{BASE}/ensemble-173/{fn}"
    en[fn] = csv_count(p)
out["ensemble-173"] = en

# ---------- arbitrage (log only) ----------
ar = {}
bl = f"{BASE}/arbitrage/logs/bot.log"
try:
    with open(bl) as f:
        lines = f.read().splitlines()
    ar["bot_log_lines"] = len(lines)
    ar["bot_log_last"] = lines[-1][:160] if lines else ""
except Exception as e:
    ar["err"] = str(e)
ar["trades_log_size"] = os.path.getsize(f"{BASE}/arbitrage/logs/trades.log")
ar["opportunities_log_size"] = os.path.getsize(f"{BASE}/arbitrage/logs/opportunities.log")
out["arbitrage"] = ar

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
