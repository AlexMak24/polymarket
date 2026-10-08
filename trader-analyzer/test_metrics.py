from datetime import datetime, timezone

from metrics import activity_stats, trade_ts


def test_trade_ts_millis_and_seconds():
    assert trade_ts({"timestamp": 1_700_000_000}) == 1_700_000_000
    assert trade_ts({"timestamp": 1_700_000_000_000}) == 1_700_000_000


def test_activity_stats_last_month():
    now = datetime.now(timezone.utc).timestamp()
    trades = [
        {"timestamp": now - 3600, "side": "BUY", "size": 10, "price": 0.4},
        {"timestamp": now - 2 * 86400, "side": "BUY", "size": 5, "price": 0.2},
        {"timestamp": now - 40 * 86400, "side": "BUY", "size": 100, "price": 0.5},
    ]
    stats = activity_stats(trades, window_days=30)
    assert stats["trades_30d"] == 2
    assert stats["buys_30d"] == 2
    assert stats["volume_30d"] == 5.0  # 10*0.4 + 5*0.2
    assert stats["active_days_30d"] >= 1
    assert stats["trades_per_month"] > 0
    assert stats["last_trade_at"]
