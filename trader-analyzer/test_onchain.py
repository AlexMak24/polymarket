"""On-chain withdrawal/flow stats tests."""

from onchain import flow, is_usdc_or_eth, reconcile, withdrawal_stats


def _wd(amount, ts, *, to="0xdead", typ="WITHDRAWAL", currency="USDC"):
    return {"type": typ, "usdcSize": amount, "timestamp": ts,
            "to": to, "currency": currency}


def test_withdrawal_basic_aggregation():
    activity = [
        _wd(100.0, 1_700_000_000),
        _wd(250.5, 1_700_000_000 + 86400),
        _wd(49.5, 1_700_000_000 + 2 * 86400),
    ]
    s = withdrawal_stats(activity)
    assert s["count"] == 3
    assert s["total"] == 400.0
    assert s["period_days"] == 2.0
    assert s["first_at"] and s["last_at"]


def test_ignores_deposits_and_non_withdrawals():
    activity = [
        _wd(100.0, 1_700_000_000),
        {"type": "DEPOSIT", "usdcSize": 500.0, "timestamp": 1_700_000_000},
        {"type": "TRADE", "usdcSize": 10.0, "timestamp": 1_700_000_000},
    ]
    s = withdrawal_stats(activity)
    assert s["count"] == 1
    assert s["total"] == 100.0


def test_currency_filter_usdc_eth():
    activity = [
        _wd(100.0, 1_700_000_000, currency="USDC"),
        _wd(2.0, 1_700_000_000 + 1, currency="ETH"),
        _wd(3.0, 1_700_000_000 + 2, currency="USDT"),
    ]
    assert withdrawal_stats(activity)["total"] == 105.0
    assert withdrawal_stats(activity, currency="USDC")["total"] == 100.0
    assert withdrawal_stats(activity, currency="ETH")["total"] == 2.0
    assert withdrawal_stats(activity)["currencies"] == ["ETH", "USDC", "USDT"]


def test_destinations_unique():
    activity = [
        _wd(10.0, 1_700_000_000, to="0xaaa"),
        _wd(10.0, 1_700_000_000 + 1, to="0xaaa"),
        _wd(10.0, 1_700_000_000 + 2, to="0xbbb"),
    ]
    s = withdrawal_stats(activity)
    assert s["n_destinations"] == 2
    assert s["destinations"] == ["0xaaa", "0xbbb"]


def test_empty_and_malformed_input():
    assert withdrawal_stats([])["count"] == 0
    assert withdrawal_stats([None, "x", 5])["total"] == 0.0
    assert withdrawal_stats([])["period_days"] == 0.0
    assert withdrawal_stats([])["first_at"] is None


def test_millis_timestamp_normalized():
    s = withdrawal_stats([
        _wd(50.0, 1_700_000_000_000),  # millis
        _wd(50.0, 1_700_000_000_000 + 86_400_000),
    ])
    assert s["count"] == 2
    assert s["period_days"] == 1.0


def test_field_name_variants():
    # amount in `size`, destination in `transactionHash`, type lowercase
    s = withdrawal_stats([
        {"type": "withdrawal", "size": "75.25", "timestamp": 1_700_000_000,
         "transactionHash": "0xhash1"},
    ])
    assert s["count"] == 1
    assert s["total"] == 75.25
    assert s["destinations"] == ["0xhash1"]


def test_is_usdc_or_eth():
    assert is_usdc_or_eth("USDC")
    assert is_usdc_or_eth("eth")
    assert is_usdc_or_eth("USDC.E")
    assert not is_usdc_or_eth("USDT")


def _dep(amount, ts, *, typ="DEPOSIT", currency="USDC"):
    return {"type": typ, "usdcSize": amount, "timestamp": ts, "currency": currency}


def test_flow_in_out_net():
    activity = [
        _dep(1000.0, 1_700_000_000),
        _dep(500.0, 1_700_000_000 + 1),
        _wd(400.0, 1_700_000_000 + 2),
        _wd(100.0, 1_700_000_000 + 3),
    ]
    f = flow(activity)
    assert f["in"]["count"] == 2
    assert f["in"]["total"] == 1500.0
    assert f["out"]["count"] == 2
    assert f["out"]["total"] == 500.0
    assert f["net"]["total"] == 1000.0
    assert f["net"]["currencies"] == {"USDC": 1000.0}
    assert len(f["deposits"]) == 2
    assert len(f["withdrawals"]) == 2


def test_flow_multi_currency_net():
    activity = [
        _dep(10.0, 1, currency="ETH"),
        _wd(4.0, 2, currency="ETH"),
        _dep(100.0, 3, currency="USDC"),
    ]
    f = flow(activity)
    assert f["net"]["currencies"] == {"ETH": 6.0, "USDC": 100.0}
    assert f["net"]["total"] == 106.0


def test_flow_ignores_unknown_types():
    f = flow([
        _dep(100.0, 1),
        {"type": "TRADE", "usdcSize": 10.0, "timestamp": 2},
        None,
        "junk",
    ])
    assert f["in"]["count"] == 1
    assert f["out"]["count"] == 0
    assert f["net"]["total"] == 100.0


def test_flow_empty():
    f = flow([])
    assert f["in"]["total"] == 0.0
    assert f["out"]["total"] == 0.0
    assert f["net"]["total"] == 0.0
    assert f["net"]["currencies"] == {}


def test_reconcile_match_diverged_unknown():
    assert reconcile(1000.0, 999.5)["verdict"] == "matched"
    assert reconcile(1000.0, 500.0)["verdict"] == "diverged"
    r = reconcile(1000.0, None)
    assert r["verdict"] == "unknown" and r["pnl"] is None and r["delta"] is None
    assert reconcile(1000.0, 999.5)["delta"] == 0.5
