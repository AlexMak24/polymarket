"""
analysis.py — оценка прибыльности и стабильности weather-трейдеров.

Считает из сделок (BUY/SELL по рынкам):
  realized_pnl  — сумма (sell_revenue - buy_cost) по закрытым рынкам
  активность    — число сделок, период, медиана размера ставки
  стабильность  — число рынков (диверсификация), консистентность

НЕ трогает weather-бот.
"""

from collections import defaultdict
from api import get_all_trades
from collector import get_all_profiles


def analyze_wallet(wallet: str, max_trades: int = 500) -> dict:
    """Оценка PnL и активности кошелька из сделок."""
    trades = get_all_trades(wallet, max_trades=max_trades)
    if not trades:
        return {}

    # Группировка по рынку (conditionId)
    by_market = defaultdict(lambda: {"buy_cost": 0.0, "sell_rev": 0.0,
                                     "buy_shares": 0.0, "sell_shares": 0.0})
    for t in trades:
        cid = t.get("conditionId")
        side = t.get("side")
        price = t.get("price", 0)
        size = t.get("size", 0)
        if side == "BUY":
            by_market[cid]["buy_cost"] += size * price
            by_market[cid]["buy_shares"] += size
        elif side == "SELL":
            by_market[cid]["sell_rev"] += size * price
            by_market[cid]["sell_shares"] += size

    # Realized PnL по закрытым рынкам (net shares ~ 0)
    realized = 0.0
    open_shares = 0.0
    n_closed = 0
    for cid, m in by_market.items():
        net = m["buy_shares"] - m["sell_shares"]
        if abs(net) < 1.0:  # позиция закрыта
            realized += m["sell_rev"] - m["buy_cost"]
            n_closed += 1
        else:
            open_shares += net

    # Активность
    sizes = [t.get("size", 0) for t in trades]
    prices = [t.get("price", 0) for t in trades if t.get("side") == "BUY"]
    ts = sorted(t.get("timestamp", 0) for t in trades)
    period_days = (ts[-1] - ts[0]) / 86400 if len(ts) > 1 else 0

    sizes_sorted = sorted(sizes)
    median_size = sizes_sorted[len(sizes_sorted) // 2] if sizes_sorted else 0

    return {
        "trades": len(trades),
        "markets": len(by_market),
        "closed_markets": n_closed,
        "realized_pnl": round(realized, 2),
        "open_shares": round(open_shares, 0),
        "period_days": round(period_days, 1),
        "median_size": round(median_size, 1),
        "median_price": round(sum(prices) / len(prices), 3) if prices else 0,
    }


def rank_all(verbose: bool = True) -> list[dict]:
    """Полный анализ всех погодных трейдеров + ранжирование."""
    profiles = get_all_profiles()
    results = []
    for p in profiles:
        stats = analyze_wallet(p["wallet"])
        row = {
            "wallet": p["wallet"],
            "name": p["name"],
            "strategy": p["strategy"],
            "top_city": p["top_city"],
            **stats,
        }
        results.append(row)

    # Ранжирование по realized PnL
    results.sort(key=lambda x: x.get("realized_pnl", 0), reverse=True)
    return results


if __name__ == "__main__":
    rows = rank_all()
    print(f"{'Имя':24s} {'стратегия':9s} {'PnL':>8s} {'сделки':>6s} {'рынки':>6s} "
          f"{'период':>7s} {'мед.ставка':>10s} {'мед.цена':>8s}")
    print("-" * 95)
    for r in rows:
        print(f"{r['name'][:24]:24s} {r['strategy']:9s} "
              f"${r.get('realized_pnl',0):>7,.2f} {r.get('trades',0):>6} "
              f"{r.get('markets',0):>6} {r.get('period_days',0):>6}д "
              f"{r.get('median_size',0):>9,.0f} {r.get('median_price',0):>7,.3f}")
