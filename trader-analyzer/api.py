"""
api.py — обёртка над публичным Polymarket Data API (Goldsky subgraph).

Data API НЕ требует ключей — он отдаёт публичную историю сделок любого
кошелька. Это то, что нужно для анализа чужих стратегий.

Endpoint'ы:
  GET /trades?user=0x...&limit=100&offset=0     — история сделок
  GET /positions?user=0x...&limit=100           — открытые позиции
"""

from config import make_http_client
from metrics import trade_ts

BASE = "https://data-api.polymarket.com"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = make_http_client(timeout=30)
    return _client


def get_trades(wallet: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """Полная история сделок кошелька (BUY + SELL)."""
    r = _get_client().get(
        f"{BASE}/trades",
        params={"user": wallet, "limit": limit, "offset": offset},
    )
    r.raise_for_status()
    return r.json()


def get_all_trades(wallet: str, max_trades: int | None = None) -> list[dict]:
    """Вытаскивает сделки пагинацией. max_trades=None — без ограничения (MVP §7)."""
    trades = []
    offset = 0
    cap = max_trades if max_trades is not None else float("inf")
    while len(trades) < cap:
        batch = get_trades(wallet, limit=100, offset=offset)
        if not batch:
            break
        trades.extend(batch)
        offset += 100
        if len(batch) < 100:
            break
    if max_trades is not None:
        trades = trades[:max_trades]
    return trades


def get_all_trades_full(wallet: str, safety_cap: int = 10000) -> dict:
    """Полная история + метаданные окна (MVP §7).

    Возвращает {"trades": [...], "window": {"from", "to", "count",
    "truncated", "source"}}. "truncated" честно True, только если упёрлись в
    safety_cap при всё ещё полном батче (API отдаёт больше, чем мы взяли).
    """
    trades: list[dict] = []
    offset = 0
    truncated = False
    while len(trades) < safety_cap:
        batch = get_trades(wallet, limit=100, offset=offset)
        if not batch:
            break
        trades.extend(batch)
        offset += 100
        if len(batch) < 100:
            break
        if len(trades) >= safety_cap:
            truncated = True
    stamps = [s for s in (trade_ts(t) for t in trades) if s > 0]
    return {
        "trades": trades,
        "window": {
            "from": min(stamps) if stamps else None,
            "to": max(stamps) if stamps else None,
            "count": len(trades),
            "truncated": truncated,
            "source": "data-api",
        },
    }


def get_full_history(wallet: str, safety_cap: int = 5000) -> list[dict]:
    """Полная история сделок кошелька (пагинация до исчерпания, с защитным
    потолком safety_cap против бесконечного цикла)."""
    return get_all_trades_full(wallet, safety_cap=safety_cap)["trades"]


def fetch_pnl(wallet: str, http=None) -> float | None:
    """Официальный total PnL (lb-api)."""
    own = http is None
    if own:
        http = make_http_client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    try:
        r = http.get(f"https://lb-api.polymarket.com/profit?address={wallet}")
        d = r.json()
        if isinstance(d, list) and d:
            d = d[0]
        if not isinstance(d, dict):
            return None
        for k in ("pnl", "profit", "realizedPnl", "amount"):
            if d.get(k) is not None:
                return float(d[k])
    except Exception:
        return None
    finally:
        if own:
            http.close()
    return None


def get_positions(wallet: str) -> list[dict]:
    """Открытые позиции кошелька."""
    r = _get_client().get(
        f"{BASE}/positions",
        params={"user": wallet, "limit": 100},
    )
    r.raise_for_status()
    return r.json()


def get_activity(wallet: str, limit: int = 100, offset: int = 0) -> list[dict]:
    """Лента on-chain активности кошелька (deposits/withdrawals USDC/ETH).

    Data API /activity отдаёт переводы средств; поле type — DEPOSIT / WITHDRAWAL.
    Возвращает список записей как есть (без сводки — см. onchain.withdrawal_stats).
    """
    r = _get_client().get(
        f"{BASE}/activity",
        params={"user": wallet, "limit": limit, "offset": offset},
    )
    r.raise_for_status()
    return r.json()


def get_full_activity(wallet: str, safety_cap: int = 2000) -> list[dict]:
    """Вся on-chain активность кошелька (deposits/withdrawals) пагинацией."""
    out: list[dict] = []
    offset = 0
    while len(out) < safety_cap:
        batch = get_activity(wallet, limit=100, offset=offset)
        if not batch:
            break
        out.extend(batch)
        offset += 100
        if len(batch) < 100:
            break
    return out
