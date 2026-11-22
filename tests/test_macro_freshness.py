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
    monthly = {"frequency": "monthly"}               # any monthly series without its own limit: 45 days
    assert annotate_macro_freshness("SOME_MONTHLY", {**monthly,
        "latest": {"observation_date": "2026-09-29", "value": 1.0}}, today)["freshness"] == "stale"
    tagged = annotate_macro_freshness("SOME_MONTHLY", {**monthly,
        "latest": {"observation_date": "2026-10-01", "value": 1.0}}, today)
    assert tagged["freshness"] == "current" and tagged["allowed_age"] == "45 calendar days"


def _age(series_id, observed, today):
    record = annotate_macro_freshness(series_id, {"latest": {"observation_date": observed, "value": 1.0}}, today)
    return record["freshness"], record["allowed_age"]


def test_series_published_in_batches_get_limits_that_match_their_release_rhythm():
    # The Fed's H.10 table (rupee rate) comes out weekly, so on a Sunday the newest value is
    # from the Friday before last: that is normal, not a failure.
    assert _age("DEXINUS", "2026-11-13", date(2026, 11, 22)) == ("current", "12 calendar days")
    assert _age("DEXINUS", "2026-11-10", date(2026, 11, 22))[0] == "current"       # exactly 12 days
    assert _age("DEXINUS", "2026-11-09", date(2026, 11, 22))[0] == "stale"         # 13 days
    # M2 money stock: dated the 1st of the month, the next value arrives in the fourth week after.
    assert _age("M2SL", "2026-09-01", date(2026, 11, 22)) == ("current", "90 calendar days")
    assert _age("M2SL", "2026-08-24", date(2026, 11, 22))[0] == "current"          # exactly 90 days
    assert _age("M2SL", "2026-08-23", date(2026, 11, 22))[0] == "stale"            # 91 days
    # Bank of Japan total assets, under both of its names.
    for name in ("JPNASSETS", "BOJ_TOTAL_ASSETS"):
        assert _age(name, "2026-10-01", date(2026, 11, 22)) == ("current", "80 calendar days")
        assert _age(name, "2026-09-03", date(2026, 11, 22))[0] == "current"        # exactly 80 days
        assert _age(name, "2026-09-02", date(2026, 11, 22))[0] == "stale"          # 81 days


def test_a_date_in_the_future_or_a_missing_date_is_never_current():
    today = date(2026, 11, 22)
    assert _age("DEXINUS", "2026-11-23", today)[0] == "stale"
    assert _age("M2SL", "not-a-date", today)[0] == "stale"
    assert _age("JPNASSETS", None, today)[0] == "stale"


def test_boj_assets_come_from_fred_first_and_the_mirror_only_as_a_fallback(monkeypatch):
    import backend.advanced_sources as advanced
    import backend.run_daily as engine
    asked = []

    def fred(series_id, day):
        asked.append(("fred", series_id, day))
        return {"id": series_id, "latest": {"observation_date": "2026-10-01", "value": 7.0e6},
                "recent": [{"observation_date": "2026-10-01", "value": 7.0e6}],
                "source": "https://fred.stlouisfed.org/series/" + series_id, "fetch_path": "fred_api"}

    def mirror(series_id, root, day, **kw):
        asked.append(("mirror", series_id, day))
        return {"id": series_id, "latest": {"observation_date": "2026-10-01", "value": 7.0e6},
                "recent": [], "source": "https://api.db.nomics.world/v22/series/FRED/" + series_id,
                "mirror": True, "frequency": "monthly"}

    monkeypatch.setattr(engine, "fetch_fred", fred)
    monkeypatch.setattr(advanced, "fetch_fred_mirror", mirror)
    record = engine.fetch_boj_total_assets("2026-11-22")
    assert asked == [("fred", "JPNASSETS", "2026-11-22")]            # FRED answered, the mirror was not asked
    assert record["id"] == "BOJ_TOTAL_ASSETS" and record["source_series_id"] == "JPNASSETS"
    assert record["fetch_path"] == "fred_api" and record["frequency"] == "monthly"
    assert annotate_macro_freshness("BOJ_TOTAL_ASSETS", record, date(2026, 11, 22))["freshness"] == "current"

    def broken(series_id, day):
        raise RuntimeError("FRED unavailable")

    asked.clear()
    monkeypatch.setattr(engine, "fetch_fred", broken)
    record = engine.fetch_boj_total_assets("2026-11-22")
    assert asked == [("mirror", "JPNASSETS", "2026-11-22")]
    assert record["mirror"] is True and record["id"] == "BOJ_TOTAL_ASSETS"
