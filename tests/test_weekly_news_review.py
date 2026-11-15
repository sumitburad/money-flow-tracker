from datetime import date
import json
from backend.news_classifier import classify_headlines
from scripts.weekly_review import generate_review


def test_weekly_news_review_queue_is_not_false_approval(tmp_path):
    date_dir=tmp_path/"data"/"news"
    date_dir.mkdir(parents=True)
    (date_dir/"2026-11-15.json").write_text(json.dumps([
       {"headline_id":str(i),"title":"Rate decision","url":"https://example.org",
        "classification":{"classifier":"deterministic_rules_NOT_AI"}}
       for i in range(27)]))
    review,text=generate_review(tmp_path,date(2026,11,15))
    assert len(review["sample_news_for_human_review"])==20
    assert review["news_review_completed"] is False
    assert review["sample_news_for_human_review"][0]["human_review_status"]=="pending"
