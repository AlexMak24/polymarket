#!/usr/bin/env python3
import os, sys, json, subprocess, threading, time
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
load_dotenv(BASE / ".env")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

WEATHER_DIR = BASE / "strategies" / "weather"
STATE_FILE = WEATHER_DIR / "data" / "state.json"
MARKETS_DIR = WEATHER_DIR / "data" / "markets"
CONFIG_FILE = WEATHER_DIR / "config.json"

def load_state():
    try: return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except: return {}

def load_config():
    try: return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    except: return {}

def load_positions():
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
                        "pnl": pos.get("unrealized_pnl") or 0,
                        "forecast": m.get("ensemble_mean", "-"),
                        "unit": m.get("unit", "F"),
                        "ev": pos.get("ev", 0),
                    })
            except: pass
    return positions

def is_bot_running():
    try:
        r = subprocess.run(["pgrep", "-f", "bot_v3.py"], capture_output=True, text=True)
        return bool(r.stdout.strip())
    except: return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Status", callback_data="status"), InlineKeyboardButton("P&L", callback_data="pnl")],
        [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Config", callback_data="config")],
        [InlineKeyboardButton("Start Bot", callback_data="start_weather"), InlineKeyboardButton("Stop Bot", callback_data="stop_weather")],
    ]
    await update.message.reply_text("Polymarket Bot Manager - Weather strategy active. Paper mode, 1 trade.", reply_markup=InlineKeyboardMarkup(keyboard))

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state(); cfg = load_config(); positions = load_positions()
    running = is_bot_running(); balance = state.get("balance", 500); pnl = balance - 500
    text = f"*Weather Bot* {'RUNNING' if running else 'STOPPED'}\nBalance: ${balance:.2f}\nP&L: ${pnl:+.2f}\nTrades: {state.get('total_trades',0)}\nPositions: {len(positions)}\nMode: {'LIVE' if cfg.get('live_trade') else 'PAPER'}"
    if positions:
        text += "\n\n*Open:*\n" + "\n".join(f"{p['city']} {p['date']} — {p['shares']}sh ${p['pnl']:+.2f}" for p in positions[:5])
    await update.message.reply_text(text, parse_mode="Markdown")

async def pnl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = load_state(); pnl = state.get("balance", 500) - 500
    await update.message.reply_text(f"*P&L*\nStart: $500.00\nCurrent: ${state.get('balance',500):.2f}\nResult: ${pnl:+,.2f}", parse_mode="Markdown")

async def positions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    positions = load_positions()
    if not positions: await update.message.reply_text("No open positions"); return
    text = "\n".join(f"{p['city']} {p['date']} — {p['shares']}sh x ${p['price']:.2f} — EV:{p['ev']:.2f} P&L:${p['pnl']:+.2f}" for p in positions)
    await update.message.reply_text(text)

async def config_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    safe = {k:v for k,v in cfg.items() if "key" not in k.lower() and "secret" not in k.lower() and "token" not in k.lower()}
    await update.message.reply_text("```json\n" + json.dumps(safe, indent=2)[:3500] + "\n```", parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); cmd = query.data
    if cmd == "start_weather":
        if is_bot_running(): await query.message.reply_text("Already running")
        else:
            subprocess.Popen([sys.executable, str(WEATHER_DIR / "bot_v3.py")], cwd=str(WEATHER_DIR))
            await query.message.reply_text("Bot started")
    elif cmd == "stop_weather":
        subprocess.run(["pkill", "-f", "bot_v3.py"])
        await query.message.reply_text("Bot stopped")
    elif cmd == "status": await status_cmd(query, context)
    elif cmd == "pnl": await pnl_cmd(query, context)
    elif cmd == "positions": await positions_cmd(query, context)
    elif cmd == "config": await config_cmd(query, context)

async def webapp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 http://127.0.0.1:8099 — открой в браузере на маке")

def main():
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    if not token: print("TG_BOT_TOKEN not set"); return
    app = Application.builder().token(token).build()
    for cmd, handler in [("start", start), ("status", status_cmd), ("pnl", pnl_cmd), ("positions", positions_cmd), ("config", config_cmd), ("webapp", webapp_cmd)]:
        app.add_handler(CommandHandler(cmd, handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
