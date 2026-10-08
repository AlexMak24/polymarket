"""
onchain.py — on-chain выводы USDC/ETH кошелька.

Разбирает ленту активности (deposits/withdrawals) Polymarket Data API в
сводку выводов: сколько суммарно выведено, куда, сколько раз и за какой
период. Чистая функция — работает на готовых записях, поэтому тестируется
без сети.

Формат записей активности защитный: принимает несколько имён полей
(Data API / lb-api / сырые RPC-логи), чтобы не зависеть от одной схемы.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

# Типы записей, которые считаются выводом средств.
_WITHDRAWAL_TYPES = {
    "WITHDRAWAL", "WITHDRAW", "OUT", "SEND", "OUTFLOW", "WITHDRAWAL_PENDING",
    "TRANSFER_OUT",
}

# Типы записей, которые считаются депозитом.
_DEPOSIT_TYPES = {
    "DEPOSIT", "IN", "RECEIVE", "INFLOW", "DEPOSIT_PENDING", "TRANSFER_IN",
}

# Имена полей, где может лежать сумма (проверяются по порядку).
_AMOUNT_FIELDS = ("usdcSize", "size", "amount", "value", "amountUSD",
                  "tokenAmount", "amountUsd")

# Имена полей назначения перевода.
_DEST_FIELDS = ("to", "destination", "counterparty", "recipient",
                "transactionHash", "txHash", "hash")


def _amount(rec: dict) -> float | None:
    for k in _AMOUNT_FIELDS:
        v = rec.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _ts(rec: dict) -> float:
    raw = rec.get("timestamp") or rec.get("ts") or 0
    if isinstance(raw, (int, float)):
        ts = float(raw)
        return ts / 1000.0 if ts > 1e12 else ts
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _iso(ts: float) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _dest(rec: dict) -> str | None:
    for k in _DEST_FIELDS:
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _is_withdrawal(rec: dict, type_field: str) -> bool:
    typ = str(rec.get(type_field) or rec.get("type") or "").upper().strip()
    return typ in _WITHDRAWAL_TYPES


def withdrawal_stats(
    activity: Iterable[dict],
    *,
    type_field: str = "type",
    currency: str | None = None,
) -> dict:
    """
    Сводка по выводам средств.

    Возвращает:
      count          — сколько раз выводил
      total          — суммарно выведено (USDC/ETH, по полю currency)
      currencies     — какие валюты встречались (по полю currency/asset)
      destinations   — уникальные адреса/хеши назначения
      n_destinations — число уникальных назначений
      period_days    — от первого до последнего вывода
      first_at       — ISO первого вывода
      last_at        — ISO последнего вывода
    """
    wds: list[dict] = []
    for rec in activity:
        if not isinstance(rec, dict):
            continue
        if not _is_withdrawal(rec, type_field):
            continue
        amt = _amount(rec)
        if amt is None:
            continue
        cur = (rec.get("currency") or rec.get("asset") or rec.get("token")
               or "USDC")
        if currency and str(cur).upper() != currency.upper():
            continue
        wds.append({
            "amount": amt,
            "currency": str(cur).upper(),
            "dest": _dest(rec),
            "ts": _ts(rec),
        })

    amounts = [w["amount"] for w in wds]
    currencies = sorted({w["currency"] for w in wds})
    dests = [w["dest"] for w in wds if w["dest"]]
    stamps = sorted(w["ts"] for w in wds if w["ts"] > 0)

    period_days = 0.0
    if len(stamps) >= 2:
        period_days = (stamps[-1] - stamps[0]) / 86400.0

    return {
        "count": len(wds),
        "total": round(sum(amounts), 2),
        "currencies": currencies,
        "destinations": list(dict.fromkeys(dests)),
        "n_destinations": len(set(dests)),
        "period_days": round(period_days, 1),
        "first_at": _iso(stamps[0]) if stamps else None,
        "last_at": _iso(stamps[-1]) if stamps else None,
    }


def is_usdc_or_eth(currency: str) -> bool:
    """Является ли валютная метка USDC или ETH (для фильтра выводов)."""
    return str(currency).upper() in {"USDC", "ETH", "WETH", "USDC.E"}


def _currency(rec: dict) -> str:
    return str(rec.get("currency") or rec.get("asset") or rec.get("token")
               or "USDC").upper()


def _direction(rec: dict, type_field: str) -> str | None:
    typ = str(rec.get(type_field) or rec.get("type") or "").upper().strip()
    if typ in _WITHDRAWAL_TYPES:
        return "out"
    if typ in _DEPOSIT_TYPES:
        return "in"
    return None


def _agg(recs: list[dict]) -> dict:
    amounts = [r["amount"] for r in recs]
    currencies = sorted({r["currency"] for r in recs})
    stamps = sorted(r["ts"] for r in recs if r["ts"] > 0)
    return {
        "count": len(recs),
        "total": round(sum(amounts), 2),
        "currencies": currencies,
        "first_at": _iso(stamps[0]) if stamps else None,
        "last_at": _iso(stamps[-1]) if stamps else None,
    }


def flow(activity: Iterable[dict], *, type_field: str = "type") -> dict:
    """Депозиты (in), выводы (out) и нетто-поток (in − out) по валютам.

    Возвращает:
      in / out        — сводки по депозитам/выводам (count, total, currencies,
                        first_at, last_at)
      net             — {"total": in−out, "currencies": {cur: net}}
      deposits        — нормализованные записи депозитов
      withdrawals     — нормализованные записи выводов
    """
    deposits: list[dict] = []
    withdrawals: list[dict] = []
    for rec in activity:
        if not isinstance(rec, dict):
            continue
        d = _direction(rec, type_field)
        if d is None:
            continue
        amt = _amount(rec)
        if amt is None:
            continue
        normalized = {
            "amount": amt,
            "currency": _currency(rec),
            "ts": _ts(rec),
            "dest": _dest(rec),
        }
        (deposits if d == "in" else withdrawals).append(normalized)

    net_by_currency: dict[str, float] = {}
    all_cur = {r["currency"] for r in deposits + withdrawals}
    for cur in sorted(all_cur):
        net_by_currency[cur] = round(
            sum(r["amount"] for r in deposits if r["currency"] == cur)
            - sum(r["amount"] for r in withdrawals if r["currency"] == cur),
            2,
        )

    return {
        "in": _agg(deposits),
        "out": _agg(withdrawals),
        "net": {
            "total": round(_agg(deposits)["total"] - _agg(withdrawals)["total"], 2),
            "currencies": net_by_currency,
        },
        "deposits": deposits,
        "withdrawals": withdrawals,
    }


def reconcile(net_flow: float, lb_pnl: float | None) -> dict:
    """Сверка on-chain нетто vs официальный lb-api PnL (MVP §6)."""
    if lb_pnl is None:
        return {
            "net_flow": round(net_flow, 2), "pnl": None, "delta": None,
            "verdict": "unknown", "note": "no lb-api PnL",
        }
    delta = round(net_flow - lb_pnl, 2)
    verdict = "matched" if abs(delta) < 1.0 else "diverged"
    return {
        "net_flow": round(net_flow, 2), "pnl": round(lb_pnl, 2), "delta": delta,
        "verdict": verdict, "note": "on-chain net vs lb-api PnL",
    }


def flow_wallet(wallet: str) -> dict:
    """Живой on-chain срез кошелька с kill-переключателем (KILL-2, MVP §6).

    Источник по приоритету (план §6): PolygonScan API (нужен ключ) -> публичный
    RPC (лимитится) -> Data API /activity через существующий прокси. В текущем
    окружении нет POLYGONSCAN_API_KEY, а публичный RPC заблокирован, поэтому
    остаётся Data API /activity (идёт через config.make_http_client).

    Если источник недоступен или пуст — возвращает {"enabled": False, ...}:
    секция on-chain в портрете честно отключается, портрет живёт на lb-api PnL.
    """
    try:
        import api as _api
    except Exception as exc:  # pragma: no cover - import guard
        return {"enabled": False, "reason": f"api import failed: {exc}"}

    try:
        activity = _api.get_full_activity(wallet)
    except Exception as exc:
        return {"enabled": False, "reason": f"activity source unavailable: {exc}"}

    fl = flow(activity)
    if not activity:
        return {"enabled": True, "flow": fl, "reconcile": None, "empty": True}

    pnl = _api.fetch_pnl(wallet)
    return {
        "enabled": True,
        "flow": fl,
        "reconcile": reconcile(fl["net"]["total"], pnl),
        "empty": False,
    }
