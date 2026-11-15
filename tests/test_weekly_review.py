from datetime import date
import json
from pathlib import Path

from scripts.weekly_review import generate_review


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_weekly_review_detects_unstable_history(tmp_path):
    values = ("Bullish", "Bearish", "Bullish", "Bearish", "Bullish")
    days = ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13")
    for day, label in zip(days, values):
        write_json(tmp_path / "data/labels" / (day + ".json"),
                   {"items": [{"id": "sp500", "item": "S&P 500", "label": label}]})
        write_json(tmp_path / "data/health" / (day + ".json"),
                   {"status": "degraded", "price_proxies_current": 40,
                    "items_configured": 50, "missing": ["mid"],
                    "errors": [{"source": "test", "error": "timeout"}]})
    review, markdown = generate_review(tmp_path, date(2026, 11, 15))
    assert review["label_days_found"] == 5
    assert "sp500" in review["unstable_label_ids"]
    assert "review as Neutral/Mixed" in review["unstable_label_ids"]["sp500"]["message"]
    assert "Source health" in markdown
    assert "predictive" in markdown


def test_no_snapshots_no_invented_data(tmp_path):
    review, markdown = generate_review(tmp_path, date(2026, 11, 15))
    assert review["label_days_found"] == 0
    assert review["latest_label_counts"]["Bullish"] == 0
    assert "data unavailable" in markdown
