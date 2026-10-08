from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_source_has_no_embedded_proxy_user():
    for name in ("config.py", "api.py", "scrape_sources.py", "snowball.py", "market_scrape.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "user341407" not in text, name
