"""Tests for live Polymarket weather title formats."""

from city_parser import parse_market, parse_outcome, parse_trade


def test_between_fahrenheit_range():
    info = parse_market(
        "Will the highest temperature in New York City be between 86-87°F on August 19?"
    )
    assert info["kind"] == "temperature"
    assert info["city"] == "New York City"
    assert info["degree"] == 86
    assert info["unit"] == "F"
    assert info["range"] == [86, 87]
    info = parse_market(
        "Will the highest temperature in London be 22°C on August 19?"
    )
    assert info["kind"] == "temperature"
    assert info["city"] == "London"
    assert info["type"] == "highest"
    assert info["degree"] == 22
    assert info["unit"] == "C"
    assert info["bound"] is None
    assert info["date"] == "August 19"
    assert info["date_iso"].endswith("-08-19")


def test_or_below_edge_bucket():
    info = parse_market(
        "Will the highest temperature in London be 20°C or below on August 19?"
    )
    assert info["degree"] == 20
    assert info["bound"] == "below"
    assert info["city"] == "London"


def test_or_higher_edge_bucket():
    info = parse_market(
        "Will the highest temperature in London be 30°C or higher on August 19?"
    )
    assert info["degree"] == 30
    assert info["bound"] == "higher"


def test_fahrenheit_and_spaces():
    info = parse_market(
        "Will the lowest temperature in New York be 80 °F on August 19?"
    )
    assert info["city"] == "New York"
    assert info["degree"] == 80
    assert info["unit"] == "F"
    assert info["type"] == "lowest"


def test_event_level_without_degree():
    info = parse_market("Highest temperature in London on August 19")
    assert info["kind"] == "temperature"
    assert info["city"] == "London"
    assert info["degree"] is None
    assert info["date"] == "August 19"


def test_parse_trade_merges_outcome_bucket():
    info = parse_trade({
        "title": "Highest temperature in London on August 19",
        "outcome": "20°C or below",
        "side": "BUY",
    })
    assert info["kind"] == "temperature"
    assert info["city"] == "London"
    assert info["degree"] == 20
    assert info["bound"] == "below"
    assert info["unit"] == "C"


def test_old_nyc_reach_format():
    info = parse_market("Will NYC reach 80°F on March 22?")
    assert info["kind"] == "temperature"
    assert info["city"] == "NYC"
    assert info["degree"] == 80
    assert info["unit"] == "F"
    assert info["type"] == "highest"


def test_rain_and_storm():
    rain = parse_market("Will it rain in Amsterdam on August 14?")
    assert rain["kind"] == "rain"
    assert rain["city"] == "Amsterdam"
    storm = parse_market("Will Super Typhoon Dolphin hit China?")
    assert storm["kind"] == "storm"


def test_outcome_only():
    assert parse_outcome("21°C")["degree"] == 21
    assert parse_outcome("30°C or higher")["bound"] == "higher"
