from discover import parse_polycopy_traders, merge_traders


def test_parse_polycopy_escaped_rsc():
    html = (
        r'initialTraders\":[{\"wallet\":\"0x6ff2cb14da8be7eb57541d250a0196c5f295f140\",'
        r'\"displayName\":\"jjavi\",\"pnl\":1},{\"wallet\":\"0x044f334595a7fd42c143e11c8ec47f23c8d1d1f1\",'
        r'\"displayName\":\"gghff\",\"pnl\":2}]'
    )
    rows = parse_polycopy_traders(html)
    assert len(rows) == 2
    assert rows[0]["name"] == "jjavi"
    assert rows[0]["address"].startswith("0x6ff2")


def test_merge_traders_unions_sources():
    a = [{"address": "0x" + "a" * 40, "name": "X", "source": "weatherbot"}]
    b = [{"address": "0x" + "a" * 40, "name": None, "source": "polycopy"}]
    merged = merge_traders([a, b])
    assert len(merged) == 1
    assert merged[0]["name"] == "X"
    assert merged[0]["sources"] == ["weatherbot", "polycopy"]
    already = merge_traders([merged, [{"address": "0x" + "a" * 40, "name": "X", "source": "live-markets"}]])
    assert "live-markets" in already[0]["sources"]
