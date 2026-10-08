"""Classifier strategy buckets, including former unknown value bettors."""

from classifier import classify_wallet, detect_ladders


def _buy(title, price, outcome=None):
    t = {"side": "BUY", "title": title, "price": price}
    if outcome:
        t["outcome"] = outcome
    return t


def test_ladder_on_edge_buckets():
    trades = [
        _buy("Will the highest temperature in London be 20°C or below on August 19?", 0.22),
        _buy("Will the highest temperature in London be 21°C on August 19?", 0.24),
        _buy("Will the highest temperature in London be 22°C on August 19?", 0.21),
        _buy("Will the highest temperature in London be 23°C on August 19?", 0.18),
    ]
    ladders = detect_ladders(trades)
    assert len(ladders) == 1
    profile = classify_wallet(trades)
    assert profile["strategy"] == "ladder"
    assert profile["top_city"] == "London"


def test_value_city_specialist():
    titles = [
        "Will the highest temperature in Seoul be 28°C on August 19?",
        "Will the highest temperature in Seoul be 27°C on August 18?",
        "Will the highest temperature in Seoul be 29°C on August 17?",
        "Will the highest temperature in Seoul be 26°C on August 16?",
    ]
    trades = [_buy(t, 0.32) for t in titles]
    profile = classify_wallet(trades)
    assert profile["strategy"] in {"specialist", "value"}
    assert profile["top_city"] == "Seoul"
    assert profile["median_entry"] == 0.32
    assert profile["city_concentration"] >= 0.55


def test_event_plus_outcome_ladder():
    trades = [
        _buy("Highest temperature in Hong Kong on August 19", 0.2, "25°C"),
        _buy("Highest temperature in Hong Kong on August 19", 0.2, "26°C"),
        _buy("Highest temperature in Hong Kong on August 19", 0.2, "27°C"),
    ]
    assert detect_ladders(trades)
    assert classify_wallet(trades)["strategy"] == "ladder"


def test_longshot_uses_ten_cents():
    trades = [
        _buy("Will the highest temperature in Miami be 34°C on August 19?", 0.03),
        _buy("Will the highest temperature in Miami be 35°C on August 18?", 0.04),
        _buy("Will the highest temperature in Dallas be 36°C on August 17?", 0.05),
    ]
    profile = classify_wallet(trades)
    assert profile["strategy"] == "longshot"
    assert profile["longshot_ratio"] == 1.0
