"""Topic classifier tests."""

from topic import (
    CANONICAL_TOPICS,
    TOPICS,
    canonical_topic,
    classify_topic,
    topic_distribution,
    topic_distribution_fine,
    topic_ratio,
    top_topic,
)


def test_weather_topic_via_parser():
    assert classify_topic("Will the highest temperature in London be 22°C on August 19?") == "weather"
    assert classify_topic("Will it rain in Amsterdam on August 14?") == "weather"
    assert classify_topic("Will Super Typhoon Dolphin hit China?") == "weather"


def test_weather_topic_from_event_plus_outcome():
    # degree lives in the outcome, not the title
    assert classify_topic("Highest temperature in Hong Kong on August 19", "25°C") == "weather"


def test_sports_topic():
    assert classify_topic("Will the Lakers win the NBA championship?") == "sports"
    assert classify_topic("Who will win the 2026 World Cup?") == "sports"


def test_politics_topic():
    assert classify_topic("Will Trump win the 2028 presidential election?") == "politics"
    assert classify_topic("Will the Senate confirm the nominee?") == "politics"


def test_crypto_topic():
    assert classify_topic("Will Bitcoin exceed $150k this year?") == "crypto"
    assert classify_topic("Will Ethereum price be above $10,000 on December 31?") == "crypto"


def test_economics_topic():
    assert classify_topic("Will the Fed cut interest rates in September?") == "economics"
    assert classify_topic("Will US CPI come in above 3%?") == "economics"


def test_science_topic():
    assert classify_topic("Will SpaceX land on Mars before 2030?") == "science"
    assert classify_topic("Will a new pandemic be declared by the WHO?") == "science"


def test_world_topic():
    assert classify_topic("Will the Russia-Ukraine war end this year?") == "world"
    assert classify_topic("Will NATO expand to include Ukraine?") == "world"


def test_pop_culture_topic():
    assert classify_topic("Will the movie break the box office record?") == "pop_culture"
    assert classify_topic("Who will win the Grammy for album of the year?") == "pop_culture"


def test_business_topic():
    assert classify_topic("Will Tesla report record earnings this quarter?") == "business"
    assert classify_topic("Will Apple complete the acquisition by 2027?") == "business"


def test_other_fallback():
    assert classify_topic("Will this completely unknown thing happen?") == "other"
    assert classify_topic("") == "other"


def test_word_boundary_no_false_weather():
    # "rain" inside "Ukraine" must NOT classify as weather (BET-4).
    assert classify_topic("Will the Russia-Ukraine war end this year?") == "world"
    assert classify_topic("Will China outgrow the US?") == "world"


def test_distribution_and_ratio():
    trades = [
        {"title": "Will the highest temperature in London be 22°C on August 19?"},
        {"title": "Will it rain in Paris on August 19?"},
        {"title": "Will Bitcoin exceed $150k this year?"},
        {"title": "Will Bitcoin exceed $200k this year?"},
        {"title": "Will the Fed cut rates?"},
    ]
    dist = topic_distribution(trades)
    assert dist["weather"] == 2
    assert dist["crypto"] == 2
    assert dist["other"] == 1  # economics collapses into other
    assert set(dist.keys()) == set(CANONICAL_TOPICS)
    assert top_topic(trades) == "weather"
    assert topic_ratio(trades, "weather") == 0.4
    assert topic_ratio(trades, "crypto") == 0.4
    assert topic_ratio(trades, "economics") == 0.2  # canonicalized to other
    assert top_topic([]) is None


def test_canonical_collapse():
    assert canonical_topic("economics") == "other"
    assert canonical_topic("world") == "other"
    assert canonical_topic("business") == "other"
    assert canonical_topic("weather") == "weather"
    assert canonical_topic("pop_culture") == "pop_culture"
    # fine-grained still exposes the raw 10 tags
    trades = [{"title": "Will the Fed cut rates?"}, {"title": "Will Bitcoin hit $100k?"}]
    fine = topic_distribution_fine(trades)
    assert fine["economics"] == 1
    assert fine["crypto"] == 1
    assert set(fine.keys()) == set(TOPICS)


def test_top_topic_tie_returns_one_of_leaders():
    trades = [
        {"title": "Will Bitcoin exceed $150k?"},
        {"title": "Will the Fed cut rates?"},
    ]
    # canonical: crypto=1, other=1 (economics->other). Deterministic first max.
    assert top_topic(trades) in {"crypto", "other"}


# C3 gold-set: labelled (title, outcome, canonical) — accuracy must be >= 0.80.
_GOLD_SET = [
    ("Highest temperature in London on August 19", "25°C", "weather"),
    ("Will it rain in Amsterdam on August 14?", "", "weather"),
    ("Will Super Typhoon Dolphin hit Japan?", "", "weather"),
    ("Who will win the 2026 World Cup?", "", "sports"),
    ("Will the Lakers win the NBA championship?", "", "sports"),
    ("Will Real Madrid win La Liga?", "", "sports"),
    ("Will Trump win the 2028 presidential election?", "", "politics"),
    ("Will the Senate confirm the nominee?", "", "politics"),
    ("Will the Prime Minister resign?", "", "politics"),
    ("Will Bitcoin exceed $150k this year?", "", "crypto"),
    ("Will Ethereum price be above $10,000?", "", "crypto"),
    ("Will Solana reach $500?", "", "crypto"),
    ("Will SpaceX land on Mars before 2030?", "", "science"),
    ("Will a new pandemic be declared by the WHO?", "", "science"),
    ("Will NASA launch the Artemis mission?", "", "science"),
    ("Who will win the Grammy for album of the year?", "", "pop_culture"),
    ("Will the movie break the box office record?", "", "pop_culture"),
    ("Will the Oscar go to the favorite?", "", "pop_culture"),
    ("Will the Fed cut interest rates in September?", "", "other"),
    ("Will Tesla report record earnings?", "", "other"),
    ("Will the Russia-Ukraine war end this year?", "", "other"),
]


def test_gold_set_accuracy():
    correct = sum(
        1 for title, outcome, expected in _GOLD_SET
        if canonical_topic(classify_topic(title, outcome)) == expected
    )
    accuracy = correct / len(_GOLD_SET)
    assert accuracy >= 0.80, f"gold-set accuracy {accuracy:.2f} < 0.80"
