import sqlite3

from collector import _save_profile, profile_from_trades
from query import query_profiles


def test_query_min_pnl_and_strategy(monkeypatch, tmp_path):
    db = tmp_path / "p.db"
    monkeypatch.setattr("collector.DB_PATH", db)
    monkeypatch.setattr("query.WEATHER_MIN_RATIO", 0.3)

    def fake_trades(n, price=0.3):
        now = 1_700_000_000
        return [{"side": "BUY", "price": price, "size": 1,
                 "timestamp": now, "title":
                 "Will the highest temperature in London be 22°C on August 19?"}
                for _ in range(n)]

    a = profile_from_trades(fake_trades(10, 0.3))
    a["pnl"] = 5000
    a["strategy"] = "ladder"
    _save_profile("0x" + "a" * 40, a, name="A")

    b = profile_from_trades(fake_trades(10, 0.35))
    b["pnl"] = 10
    b["strategy"] = "value"
    _save_profile("0x" + "b" * 40, b, name="B")

    rows = query_profiles(min_pnl=1000, strategy="ladder", sort="pnl", limit=10)
    assert len(rows) == 1
    assert rows[0]["name"] == "A"
    assert rows[0]["trades_30d"] is not None
