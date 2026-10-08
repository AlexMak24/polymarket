#!/usr/bin/env python3
"""
dashboard.py — single-file web dashboard for Polymarket weather-wallet analysis.

Pure stdlib (http.server + json + sqlite3). No pip installs required.

Run:
    /Users/alexander/agents-env/bin/python3 dashboard.py

Endpoints:
    GET /               -> HTML dashboard (dark theme, auto-refresh 60s)
    GET /api/stats      -> JSON summary stats
    GET /api/wallets    -> JSON filtered wallet list (delegates to query.query_profiles)

Port: 8765 (falls back to 8766, then 8767 if busy).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Make `query` / `config` importable from this directory regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config import DB_PATH, WEATHER_MIN_RATIO  # noqa: E402
from query import query_profiles  # noqa: E402

HOST = "127.0.0.1"
PORTS = (8765, 8766, 8767)
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

# Sorting options exposed in the UI (all keys valid for query.SORTABLE).
SORT_OPTIONS = ("pnl", "trades_30d", "trades_per_month", "volume_30d")

# Strategy options for the multiselect. The 7 in the spec plus `certain`,
# which is the largest cohort in the DB (467 wallets) and must be filterable.
STRATEGIES = (
    "ladder", "value", "specialist", "momentum", "longshot", "mixed",
    "unknown", "certain",
)


def compute_stats() -> dict:
    """Summary stats over weather wallets (weather_ratio >= WEATHER_MIN_RATIO)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM profiles WHERE weather_ratio >= ?",
            (WEATHER_MIN_RATIO,),
        ).fetchone()[0]
        with_pnl = conn.execute(
            "SELECT COUNT(*) FROM profiles "
            "WHERE weather_ratio >= ? AND pnl IS NOT NULL",
            (WEATHER_MIN_RATIO,),
        ).fetchone()[0]

        def avg_top_pnl(n: int) -> float:
            rows = conn.execute(
                "SELECT pnl FROM profiles "
                "WHERE weather_ratio >= ? AND pnl IS NOT NULL "
                "ORDER BY pnl DESC LIMIT ?",
                (WEATHER_MIN_RATIO, n),
            ).fetchall()
            vals = [r[0] for r in rows if r[0] is not None]
            return (sum(vals) / len(vals)) if vals else 0.0

        top_strategy_row = conn.execute(
            "SELECT COALESCE(strategy, 'unknown'), COUNT(*) FROM profiles "
            "WHERE weather_ratio >= ? GROUP BY strategy "
            "ORDER BY COUNT(*) DESC LIMIT 1",
            (WEATHER_MIN_RATIO,),
        ).fetchone()

        return {
            "total_wallets": total,
            "with_pnl": with_pnl,
            "avg_pnl_top_50": round(avg_top_pnl(50), 2),
            "avg_pnl_top_100": round(avg_top_pnl(100), 2),
            "top_strategy": top_strategy_row[0] if top_strategy_row else None,
        }
    finally:
        conn.close()


def _one(qs: dict, key: str):
    vals = qs.get(key)
    return vals[0] if vals else None


def _to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def build_wallets(qs: dict) -> list[dict]:
    """Translate URL query params into query_profiles kwargs and run it."""
    kwargs: dict = {"weather_only": True}

    strategy = _one(qs, "strategy")
    if strategy:
        kwargs["strategy"] = strategy

    city = _one(qs, "city")
    if city:
        kwargs["city"] = city

    min_pnl = _to_float(_one(qs, "min_pnl"))
    if min_pnl is not None:
        kwargs["min_pnl"] = min_pnl

    max_pnl = _to_float(_one(qs, "max_pnl"))
    if max_pnl is not None:
        kwargs["max_pnl"] = max_pnl

    min_trades = _to_int(_one(qs, "min_trades_30d"))
    if min_trades is not None:
        kwargs["min_trades_30d"] = min_trades

    sort = _one(qs, "sort") or "pnl"
    if sort not in SORT_OPTIONS:
        sort = "pnl"
    kwargs["sort"] = sort

    limit = _to_int(_one(qs, "limit")) or DEFAULT_LIMIT
    kwargs["limit"] = max(1, min(limit, MAX_LIMIT))

    return query_profiles(**kwargs)


class Handler(BaseHTTPRequestHandler):
    server_version = "WeatherWalletDashboard/1.0"

    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        body = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._send_html()
            elif path == "/api/stats":
                self._send_json(compute_stats())
            elif path == "/api/wallets":
                self._send_json(build_wallets(qs))
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Weather Wallet Dashboard</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><text y='14' font-size='14'>🌦️</text></svg>">
<style>
  :root {
    --bg: #0d1117;
    --surface: #161b22;
    --surface-2: #1c232c;
    --border: #30363d;
    --text: #e6edf3;
    --muted: #8b949e;
    --accent: #2dd4bf;
    --accent-dim: #14b8a6;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  a { color: var(--accent); }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    padding: 16px 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  header h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 650;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  header h1 .accent { color: var(--accent); }

  .stats-bar { display: flex; gap: 24px; flex-wrap: wrap; }
  .stat { display: flex; flex-direction: column; align-items: flex-start; }
  .stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
  .stat-value { font-size: 18px; font-weight: 650; font-variant-numeric: tabular-nums; }

  .layout { display: flex; min-height: calc(100vh - 73px); }
  .sidebar {
    width: 260px;
    flex: 0 0 260px;
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 18px;
  }
  .sidebar h2 {
    margin: 0 0 14px;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }
  .filter-group { margin-bottom: 18px; }
  .filter-group > label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--muted); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .two-col label { display: block; margin-bottom: 6px; font-size: 12px; color: var(--muted); }
  input[type="text"], input[type="number"], select {
    width: 100%;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 8px 10px;
    font-size: 13px;
  }
  input:focus, select:focus { outline: none; border-color: var(--accent); }

  .strategy-list { display: flex; flex-direction: column; gap: 6px; }
  .strategy-option { display: flex; align-items: center; gap: 8px; cursor: pointer; }
  .strategy-option input { accent-color: var(--accent); }

  .badge {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    text-transform: capitalize;
    border: 1px solid transparent;
  }
  .badge.ladder     { background: rgba(56,189,248,0.15);  color: #38bdf8; border-color: rgba(56,189,248,0.4); }
  .badge.value      { background: rgba(74,222,128,0.15);  color: #4ade80; border-color: rgba(74,222,128,0.4); }
  .badge.specialist { background: rgba(167,139,250,0.15); color: #a78bfa; border-color: rgba(167,139,250,0.4); }
  .badge.momentum   { background: rgba(251,146,60,0.15);  color: #fb923c; border-color: rgba(251,146,60,0.4); }
  .badge.longshot   { background: rgba(248,113,113,0.15); color: #f87171; border-color: rgba(248,113,113,0.4); }
  .badge.mixed      { background: rgba(148,163,184,0.15); color: #94a3b8; border-color: rgba(148,163,184,0.4); }
  .badge.unknown    { background: rgba(100,116,139,0.15); color: #64748b; border-color: rgba(100,116,139,0.4); }
  .badge.certain    { background: rgba(250,204,21,0.15);  color: #facc15; border-color: rgba(250,204,21,0.4); }

  .btn { display: block; width: 100%; padding: 9px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
  .apply-btn { background: var(--accent-dim); color: #04211c; margin-bottom: 8px; }
  .apply-btn:hover { background: var(--accent); }
  .reset-btn { background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }
  .reset-btn:hover { color: var(--text); }

  .main { flex: 1; padding: 18px 24px; overflow-x: auto; }
  .status { color: var(--muted); font-size: 12px; margin-bottom: 10px; min-height: 18px; }
  .table-wrap { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    position: sticky; top: 0;
    background: var(--surface-2);
    text-align: left;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
  tbody td { padding: 9px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  tbody tr.row { cursor: pointer; transition: background 0.08s ease; }
  tbody tr.row:hover { background: rgba(45,212,191,0.06); }
  tbody tr.row:last-child td { border-bottom: none; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
  .pnl-pos { color: #4ade80; }
  .pnl-neg { color: #f87171; }
  .empty { text-align: center; color: var(--muted); padding: 32px; }

  @media (max-width: 900px) {
    .layout { flex-direction: column; }
    .sidebar { width: 100%; flex: none; border-right: none; border-bottom: 1px solid var(--border); }
  }
</style>
</head>
<body>
<header>
  <h1>🌦️ <span class="accent">Weather Wallet</span> Dashboard</h1>
  <div class="stats-bar">
    <div class="stat"><span class="stat-label">Total wallets</span><span id="stat-total" class="stat-value">–</span></div>
    <div class="stat"><span class="stat-label">With PnL</span><span id="stat-pnl" class="stat-value">–</span></div>
    <div class="stat"><span class="stat-label">Avg PnL (top-100)</span><span id="stat-avg" class="stat-value">–</span></div>
    <div class="stat"><span class="stat-label">Top strategy</span><span id="stat-strategy" class="stat-value">–</span></div>
  </div>
</header>

<div class="layout">
  <aside class="sidebar">
    <h2>Filters</h2>

    <div class="filter-group">
      <label>Strategy</label>
      <div id="strategy-list" class="strategy-list"></div>
    </div>

    <div class="filter-group">
      <label for="city">City</label>
      <input id="city" type="text" placeholder="e.g. Paris">
    </div>

    <div class="filter-group two-col">
      <div><label for="min-pnl">Min PnL $</label><input id="min-pnl" type="number" step="any" placeholder="0"></div>
      <div><label for="max-pnl">Max PnL $</label><input id="max-pnl" type="number" step="any" placeholder="∞"></div>
    </div>

    <div class="filter-group">
      <label for="min-trades">Min trades / 30d</label>
      <input id="min-trades" type="number" step="1" min="0" placeholder="0">
    </div>

    <div class="filter-group">
      <label for="sort">Sort by</label>
      <select id="sort">
        <option value="pnl">PnL</option>
        <option value="trades_30d">Trades / 30d</option>
        <option value="trades_per_month">Trades / month</option>
        <option value="volume_30d">Volume / 30d</option>
      </select>
    </div>

    <button id="apply" class="btn apply-btn">Apply Filters</button>
    <button id="reset" class="btn reset-btn">Reset</button>
  </aside>

  <main class="main">
    <div id="status" class="status">Loading…</div>
    <div class="table-wrap">
      <table id="wallet-table">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Wallet</th>
            <th>Name</th>
            <th>Strategy</th>
            <th class="num">PnL $</th>
            <th class="num">Trades/30d</th>
            <th class="num">Volume/30d</th>
            <th class="num">Active days</th>
            <th>Top city</th>
            <th class="num">Weather %</th>
          </tr>
        </thead>
        <tbody id="tbody"></tbody>
      </table>
    </div>
  </main>
</div>

<script>
  const STRATEGIES = ["ladder","value","specialist","momentum","longshot","mixed","unknown","certain"];

  function escapeHtml(s) {
    if (s == null) return "—";
    return String(s).replace(/[&<>"']/g, c => (
      {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]
    ));
  }

  function strategyBadge(s) {
    const v = String(s || "unknown");
    const cls = STRATEGIES.includes(v) ? v : "unknown";
    return '<span class="badge ' + cls + '">' + escapeHtml(v) + '</span>';
  }

  function fmtMoney(v) {
    if (v == null || isNaN(v)) return "—";
    const n = Number(v);
    const abs = Math.abs(n);
    let out;
    if (abs >= 1e9) out = "$" + (n / 1e9).toFixed(2) + "B";
    else if (abs >= 1e6) out = "$" + (n / 1e6).toFixed(2) + "M";
    else if (abs >= 1e3) out = "$" + (n / 1e3).toFixed(1) + "K";
    else out = "$" + n.toFixed(2);
    return '<span class="' + (n < 0 ? "pnl-neg" : "pnl-pos") + '">' + out + '</span>';
  }

  function fmtNum(v) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toLocaleString();
  }

  function fmtPct(v) {
    if (v == null || isNaN(v)) return "—";
    return (Number(v) * 100).toFixed(1) + "%";
  }

  function maskWallet(w) {
    if (!w) return "—";
    if (w.length <= 14) return escapeHtml(w);
    return escapeHtml(w.slice(0, 6) + "…" + w.slice(-4));
  }

  function buildStrategyList() {
    const list = document.getElementById("strategy-list");
    STRATEGIES.forEach(s => {
      const label = document.createElement("label");
      label.className = "strategy-option";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = s;
      cb.id = "strat-" + s;
      const span = document.createElement("span");
      span.className = "badge " + s;
      span.textContent = s;
      label.appendChild(cb);
      label.appendChild(span);
      list.appendChild(label);
    });
  }

  function currentParams() {
    const checked = Array.from(document.querySelectorAll("#strategy-list input:checked")).map(c => c.value);
    const p = new URLSearchParams();
    if (checked.length) p.set("strategy", checked.join(","));
    const city = document.getElementById("city").value.trim();
    if (city) p.set("city", city);
    const minPnl = document.getElementById("min-pnl").value;
    if (minPnl !== "") p.set("min_pnl", minPnl);
    const maxPnl = document.getElementById("max-pnl").value;
    if (maxPnl !== "") p.set("max_pnl", maxPnl);
    const minTrades = document.getElementById("min-trades").value;
    if (minTrades !== "") p.set("min_trades_30d", minTrades);
    p.set("sort", document.getElementById("sort").value);
    p.set("limit", "100");
    return p.toString();
  }

  async function loadStats() {
    try {
      const r = await fetch("/api/stats");
      if (!r.ok) return;
      const s = await r.json();
      document.getElementById("stat-total").textContent = fmtNum(s.total_wallets);
      document.getElementById("stat-pnl").textContent = fmtNum(s.with_pnl);
      document.getElementById("stat-avg").innerHTML = fmtMoney(s.avg_pnl_top_100);
      document.getElementById("stat-strategy").textContent = s.top_strategy || "—";
    } catch (e) { console.error(e); }
  }

  function renderTable(rows) {
    const tbody = document.getElementById("tbody");
    tbody.innerHTML = "";
    if (!rows || !rows.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty">No wallets match the current filters.</td></tr>';
      return;
    }
    rows.forEach((w, i) => {
      const tr = document.createElement("tr");
      tr.className = "row";
      tr.title = "Open profile: " + (w.wallet || "");
      const city = escapeHtml(w.top_city);
      const name = escapeHtml(w.name);
      tr.innerHTML =
        '<td>' + (i + 1) + '</td>' +
        '<td class="mono">' + maskWallet(w.wallet) + '</td>' +
        '<td>' + name + '</td>' +
        '<td>' + strategyBadge(w.strategy) + '</td>' +
        '<td class="num">' + fmtMoney(w.pnl) + '</td>' +
        '<td class="num">' + fmtNum(w.trades_30d) + '</td>' +
        '<td class="num">' + fmtMoney(w.volume_30d) + '</td>' +
        '<td class="num">' + fmtNum(w.active_days_30d) + '</td>' +
        '<td>' + city + '</td>' +
        '<td class="num">' + fmtPct(w.weather_ratio) + '</td>';
      tr.addEventListener("click", () => {
        if (w.wallet) window.open("https://polymarket.com/profile/" + encodeURIComponent(w.wallet), "_blank");
      });
      tbody.appendChild(tr);
    });
  }

  async function loadWallets() {
    const status = document.getElementById("status");
    status.textContent = "Loading…";
    try {
      const r = await fetch("/api/wallets?" + currentParams());
      if (!r.ok) {
        let msg = "Error " + r.status;
        try { const j = await r.json(); if (j.error) msg += ": " + j.error; } catch (e) {}
        status.textContent = msg;
        return;
      }
      const rows = await r.json();
      renderTable(rows);
      status.textContent = rows.length + " wallets · updated " + new Date().toLocaleTimeString();
    } catch (e) {
      status.textContent = "Error: " + e;
    }
  }

  function resetFilters() {
    document.querySelectorAll("#strategy-list input:checked").forEach(c => { c.checked = false; });
    document.getElementById("city").value = "";
    document.getElementById("min-pnl").value = "";
    document.getElementById("max-pnl").value = "";
    document.getElementById("min-trades").value = "";
    document.getElementById("sort").value = "pnl";
    loadWallets();
  }

  document.getElementById("apply").addEventListener("click", loadWallets);
  document.getElementById("reset").addEventListener("click", resetFilters);

  ["city", "min-pnl", "max-pnl", "min-trades", "sort"].forEach(id => {
    const el = document.getElementById(id);
    el.addEventListener("keydown", e => { if (e.key === "Enter") loadWallets(); });
  });

  buildStrategyList();
  loadStats();
  loadWallets();
  setInterval(() => { loadStats(); loadWallets(); }, 60000);
</script>
</body>
</html>
"""


def main() -> None:
    last_err = None
    for port in PORTS:
        try:
            srv = ThreadingHTTPServer((HOST, port), Handler)
        except OSError as exc:
            last_err = exc
            print(f"[dashboard] port {port} busy ({exc}); trying next...")
            continue
        print(f"[dashboard] serving on http://{HOST}:{port} "
              f"(db={DB_PATH})")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n[dashboard] shutting down.")
            srv.server_close()
        return
    print(f"[dashboard] no free port in {PORTS}. Last error: {last_err}")
    sys.exit(1)


if __name__ == "__main__":
    main()
