"""Wallet portrait tests (offline — synthetic trades/activity)."""

from datetime import datetime, timezone

from portrait import build_portrait, normalize_trade

_NOW = datetime.now(timezone.utc).timestamp()


def _buy(title, price=0.30, ts=None, outcome=None):
    t = {"side": "BUY", "price": price, "size": 10, "title": title,
         "timestamp": ts if ts is not None else _NOW, "conditionId": "cid-1"}
    if outcome:
        t["outcome"] = outcome
    return t


def test_portrait_combines_everything():
    trades = [
        _buy("Will the highest temperature in London be 22°C on August 19?"),
        _buy("Will the highest temperature in London be 23°C on August 19?"),
        _buy("Will the highest temperature in London be 24°C on August 19?"),
        _buy("Will Bitcoin exceed $150k this year?"),
    ]
    activity = [
        {"type": "WITHDRAWAL", "usdcSize": 120.0, "timestamp": 1_700_000_000,
         "to": "0xdest", "currency": "USDC"},
    ]
    p = build_portrait("0xabc", name="Test", trades=trades,
                       activity=activity, pnl=42.0)

    assert p["strategy"] == "ladder"
    assert p["top_topic"] == "weather"
    assert p["topics"]["weather"] == 3
    assert p["topics"]["crypto"] == 1
    assert p["withdrawals"]["count"] == 1
    assert p["withdrawals"]["total"] == 120.0
    assert p["history_count"] == 4
    assert p["history"][0]["topic"] == "weather"
    assert p["history"][3]["topic"] == "crypto"
    assert p["pnl"] == 42.0
    assert p["profile"]["buy_trades"] == 4
    assert p["activity"]["trades_30d"] == 4


def test_portrait_empty_trades():
    p = build_portrait("0xabc", trades=[])
    assert p["strategy"] == "unknown"
    assert p["top_topic"] is None
    assert p["withdrawals"]["count"] == 0
    assert p["history_count"] == 0


def test_normalize_trade_topic_and_fields():
    t = _buy("Will the Fed cut interest rates?", outcome="Yes", ts=1_700_000_000)
    n = normalize_trade(t)
    assert n["topic"] == "economics"
    assert n["side"] == "BUY"
    assert n["outcome"] == "Yes"
    assert n["conditionId"] == "cid-1"
    assert n["timestamp"] == 1_700_000_000
