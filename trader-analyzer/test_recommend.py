from datetime import datetime, timezone, timedelta

from recommend import filter_recent


def test_filter_recent_keeps_fresh_trades():
    now = datetime.now(timezone.utc).timestamp()
    trades = [
        {"timestamp": now - 3600, "title": "fresh"},
        {"timestamp": now - 10 * 86400, "title": "stale"},
        {"timestamp": int((now - 1800) * 1000), "title": "millis"},
    ]
    recent = filter_recent(trades, hours=48)
    titles = {t["title"] for t in recent}
    assert titles == {"fresh", "millis"}
