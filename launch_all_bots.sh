#!/bin/bash
# =============================================================================
# Polymarket — launch/keepalive всех ботов (идемпотентный)
# PID-файлы + pgrep fallback. Безопасно для LaunchAgent / cron / вручную.
#
# Phase A 2026-08-24: pause bleeding value/fade-NO; specialist city clones;
# idle longshot-only; surferx Asia-first via .env.
# =============================================================================
export PATH="/opt/homebrew/opt/node@20/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

ROOT="/Users/alexander/projects/polymarket/strategies"
LOGS="/Users/alexander/projects/polymarket/logs"
PIDS="$LOGS/pids"

HERMES_PY="/Users/alexander/.hermes/hermes-agent/venv/bin/python"
HOMEBREW_PY="/opt/homebrew/Cellar/python@3.12/3.12.13_2/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
MIHRM9_PY="$ROOT/mihirm9-weather/.venv/bin/python"
IDLE_PY="$ROOT/idlepraxis-weather/.venv/bin/python"
NODE_BIN="$(command -v node || true)"
if [[ -z "$NODE_BIN" || ! -x "$NODE_BIN" ]]; then
  NODE_BIN="/opt/homebrew/opt/node@20/bin/node"
fi

mkdir -p "$LOGS" "$PIDS"

# Paused: paper bleed / no shortlist benchmark (re-enable by removing from list)
# Specialists = top ladder cities (analyzer): London, Munich, Seoul, HK, Shenzhen.
# Pause weaker/non-top city clones to keep Open-Meteo rate-limit headroom.
PAUSE_BOTS="guillermo hrrr-metar risedownlabs balles-edge surferx-shanghai surferx-singapore surferx-madrid surferx-paris surferx-kl"

alive() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

is_paused() {
  local name="$1"
  [[ " $PAUSE_BOTS " == *" $name "* ]]
}

stop_bot() {
  local name="$1"
  local pidfile="$PIDS/$name.pid"
  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(tr -d '[:space:]' < "$pidfile")
    if alive "$pid"; then
      kill "$pid" 2>/dev/null || true
      sleep 0.3
      alive "$pid" && kill -9 "$pid" 2>/dev/null || true
      echo "[$(date '+%F %T')] $name: PAUSED/stopped (was pid $pid)"
    fi
    rm -f "$pidfile"
  fi
}

is_running() {
  local name="$1"
  local pattern="$2"
  local pidfile="$PIDS/$name.pid"

  if [[ -f "$pidfile" ]]; then
    local pid
    pid=$(tr -d '[:space:]' < "$pidfile")
    if alive "$pid"; then
      return 0
    fi
    rm -f "$pidfile"
  fi

  if [[ -n "$pattern" ]]; then
    local found
    found=$(pgrep -f "$pattern" 2>/dev/null | head -1)
    if [[ -n "$found" ]] && alive "$found"; then
      echo "$found" > "$pidfile"
      return 0
    fi
  fi
  return 1
}

launch() {
  local name="$1" dir="$2" pattern="$3"
  shift 3

  if is_paused "$name"; then
    stop_bot "$name"
    return 0
  fi

  if is_running "$name" "$pattern"; then
    return 0
  fi

  if [[ "$name" == "idlepraxis" ]]; then
    rm -f "$dir/data/bot.pid"
  fi

  if [[ ! -d "$dir" ]]; then
    echo "[$(date '+%F %T')] $name: SKIP — no dir $dir"
    return 1
  fi

  (
    cd "$dir" || exit 1
    nohup "$@" >> "$LOGS/$name.log" 2>&1 &
    echo $! > "$PIDS/$name.pid"
    disown
  )
  sleep 0.5
  local pid
  pid=$(tr -d '[:space:]' < "$PIDS/$name.pid" 2>/dev/null)
  if alive "$pid"; then
    echo "[$(date '+%F %T')] $name: ЗАПУЩЕН (pid $pid)"
  else
    echo "[$(date '+%F %T')] $name: FAIL — process died immediately (see $LOGS/$name.log)"
    rm -f "$PIDS/$name.pid"
  fi
}

# Specialist / 1-city ladder clone (shared surferx-ladder codebase)
launch_specialist() {
  local tag="$1" city="$2" latlon="$3"
  local name="surferx-${tag}"
  local state="/tmp/bot_state_${name}.json"
  local tracker="logs/tracker_state_${name}.json"
  # Asia/EU: NWS always 404 — Open-Meteo only. Slow scans to avoid 429 stampede.
  launch "$name" "$ROOT/surferx-ladder" "POLYMARKET_BOT=${name}" \
    env POLYMARKET_BOT="$name" \
        STATE_FILE="$state" \
        TRACKER_STATE_FILE="$tracker" \
        SKIP_CSV_BOOTSTRAP=1 \
        SPECIALIST_CITY="$city" \
        CITIES="$city" \
        NWS_POINTS="${city}:${latlon}" \
        SPECIALIST_SIZE_BOOST=1 \
        MODE=dry-run \
        BANKROLL=500 \
        PER_MARKET_MAX_PCT=0.08 \
        MAX_POSITION_USD=25 \
        SCAN_INTERVAL_SEC=480 \
    "$MIHRM9_PY" -u main.py
  sleep 8
}

# --- Active fleet ---
launch weather      "$ROOT/weather"              "/Users/alexander/projects/polymarket/strategies/weather.*bot_v3|bot_v3\\.py run" \
  "$HERMES_PY" -u bot_v3.py run

# PAUSED value clones (Phase A)
launch guillermo   "$ROOT/guillermo-weather"    "POLYMARKET_BOT=guillermo" \
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  POLYMARKET_BOT=guillermo "$NODE_BIN" dist/index.js --live --interval 30

launch hrrr-metar  "$ROOT/hrrr-metar"           "/Users/alexander/projects/polymarket/strategies/hrrr-metar.*bot_v2|bot_v2\\.py run" \
  "$HOMEBREW_PY" -u bot_v2.py run

launch riekert     "$ROOT/riekert-poc"          "/Users/alexander/projects/polymarket/strategies/riekert-poc.*loop\\.py" \
  "$MIHRM9_PY" -u loop.py

launch risedownlabs "$ROOT/risedownlabs-weather" "POLYMARKET_BOT=risedownlabs" \
  env POLYMARKET_BOT=risedownlabs "$NODE_BIN" dist/index.js run

launch balles-edge "$ROOT/balles-edge"          "balles-edge/loop\\.sh" \
  bash loop.sh

launch mihirm9     "$ROOT/mihirm9-weather"      "/Users/alexander/projects/polymarket/strategies/mihirm9-weather.*main\\.py" \
  "$MIHRM9_PY" -u main.py

launch surferx     "$ROOT/surferx-ladder"       "POLYMARKET_BOT=surferx" \
  env POLYMARKET_BOT=surferx \
      STATE_FILE="/tmp/bot_state_surferx.json" \
      TRACKER_STATE_FILE="logs/tracker_state_surferx.json" \
  "$MIHRM9_PY" -u main.py

# Specialist ladder / city clones — top ladder PnL cities
launch_specialist london "London" "51.5048,0.0495"
launch_specialist munich "Munich" "48.3538,11.7861"
launch_specialist seoul "Seoul" "37.4691,126.4505"
launch_specialist hk "Hong Kong" "22.3080,113.9185"
launch_specialist shenzhen "Shenzhen" "22.6394,113.8108"
launch_specialist beijing "Beijing" "39.9042,116.4074"
launch_specialist chengdu "Chengdu" "30.5728,104.0668"
# Paused (still defined so re-enable = drop from PAUSE_BOTS)
launch_specialist shanghai "Shanghai" "31.1434,121.8052"
launch_specialist singapore "Singapore" "1.3644,103.9915"
launch_specialist madrid "Madrid" "40.4983,-3.5676"
launch_specialist paris "Paris" "49.0097,2.5479"
launch_specialist kl "Kuala Lumpur" "2.7456,101.7099"

launch aadixd200   "$ROOT/aadixd200-weather"    "POLYMARKET_BOT=aadixd200" \
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u all_proxy \
  POLYMARKET_BOT=aadixd200 "$MIHRM9_PY" -u daemon.py

# Longshot-only: YES 3–12¢, NO path off (was buying ~48¢ mid)
launch idlepraxis  "$ROOT/idlepraxis-weather"   "/Users/alexander/projects/polymarket/strategies/idlepraxis-weather.*bot\\.py" \
  env EXTREME_DISABLE_NO=1 EXTREME_YES_MIN_PRICE=0.03 EXTREME_YES_MAX_PRICE=0.12 \
  "$IDLE_PY" -u bot.py bot-start --simulation

echo "[$(date '+%F %T')] проверка завершена. PAUSE_BOTS=[$PAUSE_BOTS]"
alive_n=0
for f in "$PIDS"/*.pid; do
  [[ -f "$f" ]] || continue
  pid=$(tr -d '[:space:]' < "$f")
  alive "$pid" && alive_n=$((alive_n + 1))
done
echo "[$(date '+%F %T')] alive: $alive_n  node=$NODE_BIN"
