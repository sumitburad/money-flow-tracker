from datetime import date
from backend.run_daily import annotate_macro_freshness


def test_stale_daily_mirror_is_marked_stale_even_if_just_fetched():
    record = {"latest": {"observation_date": "2026-11-09", "value": 4.5},
              "fetched_at_utc": "2026-11-15T08:11:24+00:00", "mirror": True}
    tagged = annotate_macro_freshness("DGS2", record, date(2026, 11, 15))
    assert tagged["freshness"] == "stale"
    assert tagged["last_good_date"] == "2026-11-09"
    assert "weekday" in tagged["allowed_age"]
    assert record.get("freshness") is None


def test_recent_daily_and_weekly_have_distinct_age_limits():
    today = date(2026, 11, 15)
    daily = {"latest": {"observation_date": "2026-11-13", "value": 4.5}}
    assert annotate_macro_freshness("DGS10", daily, today)["freshness"] == "current"
    weekly = {"latest": {"observation_date": "2026-11-04", "value": 7.0}}
    assert annotate_macro_freshness("WALCL", weekly, today)["freshness"] == "current"
    assert annotate_macro_freshness("DGS2", weekly, today)["freshness"] == "stale"


def test_monthly_freshness_is_calendar_bounded():
    today = date(2026, 11, 15)
    assert annotate_macro_freshness("M2SL", {
        "latest": {"observation_date": "2026-09-29", "value": 1.0}}, today)["freshness"] == "stale"
    assert annotate_macro_freshness("M2SL", {
        "latest": {"observation_date": "2026-10-01", "value": 1.0}}, today)["freshness"] == "current"
