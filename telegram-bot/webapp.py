#!/usr/bin/env python3
"""Weather Bot WebApp — Flask дашборд для Telegram WebApp."""

import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

try:
    from flask import Flask, jsonify, render_template_string
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask", "-q"])
    from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

WEATHER_DIR = BASE / "strategies" / "weather"
STATE_FILE = WEATHER_DIR / "data" / "state.json"
MARKETS_DIR = WEATHER_DIR / "data" / "markets"
CONFIG_FILE = WEATHER_DIR / "config.json"

WEATHER_SOURCES = {
    "open-meteo": {"name": "Open-Meteo Standard", "limit": "10K/день", "key": False, "note": "Основной источник (ECMWF+ICON+GFS+GEM)"},
    "open-meteo-ensemble": {"name": "Open-Meteo Ensemble", "limit": "10K/день", "key": False, "note": "48+ членов ансамбля"},
    "noaa-nws": {"name": "NOAA/NWS (США)", "limit": "безлимит", "key": False, "note": "Правительство США"},
    "openweathermap": {"name": "OpenWeatherMap", "limit": "1K/день", "key": True, "note": "Исторические данные 5 дней"},
    "weatherapi": {"name": "WeatherAPI.com", "limit": "1M/мес", "key": True, "note": "Самый щедрый тир"},
    "visual-crossing": {"name": "Visual Crossing", "limit": "1K/день", "key": True, "note": "Верификация факта (VC_KEY)"},
    "tomorrow-io": {"name": "Tomorrow.io", "limit": "500/день", "key": True, "note": "AI-модели + процентили"},
}

def load_state():
    try: return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except: return {}

def load_config():
    try: return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    except: return {}

def get_stats():
    state = load_state()
    cfg = load_config()
    balance = state.get("balance", cfg.get("balance", 500))
    realized = state.get("realized_pnl", 0)
    total_trades = state.get("total_trades", 0)
    wins = state.get("wins", 0)
    positions = get_positions()
    unrealized = sum(p["pnl"] for p in positions if p["pnl"])
    return {
        "balance": f"${balance:,.2f}", "balance_raw": balance,
        "pnl": f"${balance - 500:+,.2f}", "pnl_raw": balance - 500,
        "realized": f"${realized:+,.2f}", "unrealized": f"${unrealized:+,.2f}",
        "positions": len(positions), "trades": total_trades, "wins": wins,
        "live": cfg.get("live_trade", False),
        "max_bet": cfg.get("max_bet", 5),
        "floor": cfg.get("balance_floor", 50),
        "last_scan": state.get("last_scan", "—"),
    }

def get_positions():
    positions = []
    if MARKETS_DIR.exists():
        for f in sorted(MARKETS_DIR.glob("*.json"), reverse=True):
            try:
                m = json.loads(f.read_text())
                pos = m.get("position")
                if pos and pos.get("status") in ("open", "pending", "partial", None):
                    positions.append({
                        "city": m.get("city", "?").title(),
                        "date": m.get("date", "?"),
                        "side": pos.get("side", "?"),
                        "price": pos.get("entry_price", 0),
                        "shares": int(pos.get("shares", 0)),
                        "cost": pos.get("cost", 0),
                        "pnl": round(pos.get("unrealized_pnl") or 0, 2),
                        "forecast": m.get("ensemble_mean", "—"),
                        "unit": m.get("unit", "F"),
                        "ev": pos.get("ev", 0),
                        "opened": pos.get("opened_at", "?")[:16] if pos.get("opened_at") else "?",
                    })
            except: pass
    return positions

HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=yes"><meta http-equiv="refresh" content="60"><title>Weather Bot — Polymarket</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1117;color:#c9d1d9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:16px;min-height:100vh}
h1{color:#58a6ff;font-size:18px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:16px}
.stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;text-align:center}
.stat .value{font-size:22px;font-weight:700}
.stat .label{font-size:10px;color:#8b949e;margin-top:4px;text-transform:uppercase;letter-spacing:1px}
.green{color:#3fb950}.red{color:#f85149}.yellow{color:#d2991d}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;margin-bottom:12px}
.card h2{color:#58a6ff;font-size:12px;text-transform:uppercase;margin-bottom:8px;letter-spacing:1px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#8b949e;padding:6px 4px;border-bottom:1px solid #30363d;font-weight:600}
td{padding:6px 4px;border-bottom:1px solid #21262d}
.badge{padding:2px 6px;border-radius:10px;font-size:10px;font-weight:600}
.badge-free{background:#238636;color:#fff}.badge-key{background:#9e6a03;color:#fff}
.btn{background:#238636;color:#fff;border:1px solid #3fb950;padding:8px 16px;border-radius:6px;cursor:pointer;font-size:12px;margin-right:6px}
.btn.danger{background:#da3633;border-color:#f85149}
.empty{color:#8b949e;padding:16px;text-align:center}
.footer{margin-top:16px;color:#484f58;font-size:11px;text-align:center}
</style></head>
<body>
<h1>🌤️ Polymarket Weather Bot</h1>
<div class="grid">
<div class="stat"><div class="value">{{ stats.balance }}</div><div class="label">Баланс</div></div>
<div class="stat"><div class="value {{ 'green' if stats.pnl_raw >= 0 else 'red' }}">{{ stats.pnl }}</div><div class="label">P&amp;L</div></div>
<div class="stat"><div class="value">{{ stats.realized }}</div><div class="label">Реализовано</div></div>
<div class="stat"><div class="value">{{ stats.unrealized }}</div><div class="label">Нереализовано</div></div>
<div class="stat"><div class="value">{{ stats.positions }}</div><div class="label">Позиций</div></div>
<div class="stat"><div class="value">{{ stats.trades }}</div><div class="label">Сделок</div></div>
</div>

<div class="card"><h2>📊 Открытые позиции</h2>
{% if positions %}
<table><tr><th>Город</th><th>Дата</th><th>Тип</th><th>Цена</th><th>Размер</th><th>Прогноз</th><th>P&amp;L</th></tr>
{% for p in positions %}<tr><td>{{ p.city }}</td><td>{{ p.date }}</td><td>{{ p.side }}</td>
<td>${{ "%.2f"|format(p.price) }}</td><td>{{ p.shares }} sh</td>
<td>{{ p.forecast }}°{{ p.unit }}</td>
<td class="{{ 'green' if p.pnl >= 0 else 'red' }}">${{ "%.2f"|format(p.pnl) }}</td></tr>{% endfor %}</table>
{% else %}<div class="empty">Нет открытых позиций</div>{% endif %}</div>

<div class="card"><h2>🔌 Источники погоды</h2>
<table><tr><th>Источник</th><th>Ключ</th><th>Лимит</th><th>Примечание</th></tr>
{% for s in sources %}<tr><td><strong>{{ s.name }}</strong></td>
<td><span class="badge {{ 'badge-free' if not s.key else 'badge-key' }}">{{ 'БЕСПЛАТНО' if not s.key else 'НУЖЕН КЛЮЧ' }}</span></td>
<td>{{ s.limit }}</td><td style="font-size:11px;color:#8b949e">{{ s.note }}</td></tr>{% endfor %}</table></div>

<div class="card">
<h2>⚙️ Управление</h2>
<p style="margin-bottom:8px;font-size:12px">
Режим: <span class="badge {{ 'badge-key' if not stats.live else 'badge-free' }}">{{ 'LIVE' if stats.live else 'PAPER' }}</span>
&nbsp;Max bet: <strong>${{ stats.max_bet }}</strong>
&nbsp;Floor: <strong>${{ stats.floor }}</strong></p>
<button class="btn" onclick="fetch('/api/start',{method:'POST'}).then(()=>location.reload())">▶ Запустить</button>
<button class="btn danger" onclick="fetch('/api/stop',{method:'POST'}).then(()=>location.reload())">⏹ Остановить</button></div>

<div class="footer">Автообновление: 60 сек | {{ now }}</div>
</body></html>"""

@app.route("/")
def dashboard():
    stats = get_stats()
    positions = get_positions()
    sources = [{"name": s["name"], "key": s["key"], "limit": s["limit"], "note": s["note"]} for s in WEATHER_SOURCES.values()]
    return render_template_string(HTML, stats=stats, positions=positions, sources=sources, now=datetime.now().strftime("%H:%M:%S"))

@app.route("/api/status")
def api_status():
    return jsonify({"stats": get_stats(), "positions": get_positions()})

@app.route("/api/start", methods=["POST"])
def api_start():
    return jsonify({"message": "OK"})

@app.route("/api/stop", methods=["POST"])
def api_stop():
    return jsonify({"message": "OK"})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8099, debug=False)
