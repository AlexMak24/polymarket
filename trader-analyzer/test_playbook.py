from collector import is_playbook_profile


def test_playbook_keeps_ladder_drops_certain():
    assert is_playbook_profile({
        "weather_ratio": 0.9, "strategy": "ladder", "city_concentration": 0.2,
    })
    assert is_playbook_profile({
        "weather_ratio": 0.8, "strategy": "momentum", "city_concentration": 0.3,
    })
    assert not is_playbook_profile({
        "weather_ratio": 0.9, "strategy": "certain", "city_concentration": 0.9,
    })
    assert not is_playbook_profile({
        "weather_ratio": 0.1, "strategy": "ladder", "city_concentration": 1.0,
    })
