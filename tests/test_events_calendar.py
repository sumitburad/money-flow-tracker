import copy
import json
from datetime import date, timedelta

import pytest
import yaml

from backend.events_calendar import (build_calendar, digest_events, fetch_fred_release_dates,
                                     load_config)
from backend.feed_contract import validate_calendar

TODAY = date(2026, 11, 22)
SECRET = "supersecretfredkey1234"


class Answer:
    def __init__(self, rows=None, status=200, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps({"release_dates": rows}).encode()


class FredFake:
    """Plays back FRED pages; remembers what was asked."""

    def __init__(self, pages):
        self.pages, self.asked = list(pages), []

    def get(self, url, params=None, timeout=None, headers=None):
        self.asked.append(dict(params))
        return self.pages.pop(0) if self.pages else Answer([])


def row(name, day, rid=1):
    return {"release_id": rid, "release_name": name, "date": day}


def config(**changes):
    cfg = copy.deepcopy(load_config())
    cfg.update(changes)
    return cfg


def test_the_real_config_is_sound():
    cfg = load_config()
    ids = [r["id"] for r in cfg["releases"]] + [b["id"] for b in cfg["built_in"]]
    assert len(ids) == len(set(ids))
    for entry in cfg["releases"] + cfg["built_in"]:
        assert entry["importance"] in ("high", "medium") and entry["why"].strip()
        assert entry["category"] in ("inflation", "growth", "central_bank")
    fomc = next(b for b in cfg["built_in"] if b["id"] == "fomc")
    days = [date.fromisoformat(d) for d in fomc["dates"]]
    assert days == sorted(days) and len(set(days)) == len(days)
    assert all(d.weekday() == 2 for d in days)          # a decision is announced on a Wednesday
    assert max(days) <= date.fromisoformat(fomc["covers_through"])
    assert fomc["checked_against_official_site"] is False  # flip only after a person checks the page


def test_matching_filtering_sorting_and_days_away():
    cfg = config()
    page = Answer([
        row("Employment Situation", "2026-12-04"),
        row("consumer  price index", "2026-12-10"),            # case and spacing do not matter
        row("Personal Income and Outlays", "2026-12-23"),
        row("Some Other Release", "2026-12-05"),                # not configured: ignored
        row("Consumer Price Index", "2027-03-10"),              # beyond the window: ignored
    ])
    http = FredFake([page])
    block, health = build_calendar(cfg, TODAY, http=http, api_key=SECRET)
    names = [(e["id"], e["date"], e["days_away"]) for e in block["events"]]
    assert names == [("jobs", "2026-12-04", 12), ("fomc", "2026-12-09", 17),
                     ("cpi", "2026-12-10", 18), ("pce", "2026-12-23", 31)]
    assert {e["basis"] for e in block["events"]} == {"fred_release_calendar", "built_in_list"}
    assert health["fred"]["status"] == "ok" and health["fred"]["rows_seen"] == 4
    assert set(health["fred"]["unmatched_releases"]) == {"ppi", "gdp", "retail"}
    asked = http.asked[0]
    assert asked["include_release_dates_with_no_data"] == "true"      # future dates need this
    assert asked["realtime_start"] == "2026-11-22" and asked["sort_order"] == "asc"
    validate_calendar(block)


def test_pages_are_followed_until_the_window_is_covered():
    cfg = config()
    cfg["fred"]["page_size"] = 2
    first = Answer([row("Employment Situation", "2026-11-25"), row("Other", "2026-11-26")])
    second = Answer([row("Consumer Price Index", "2026-12-10"), row("Other", "2027-03-01")])
    third = Answer([row("Gross Domestic Product", "2026-12-20")])        # never asked for
    http = FredFake([first, second, third])
    block, health = build_calendar(cfg, TODAY, http=http, api_key=SECRET)
    assert [p["offset"] for p in http.asked] == [0, 2]                   # stopped once past the window
    assert {"jobs", "cpi"} <= {e["id"] for e in block["events"]}


def test_without_a_key_only_the_built_in_fed_list_is_shown():
    block, health = build_calendar(config(), TODAY, http=FredFake([]), api_key="")
    assert [e["id"] for e in block["events"]] == ["fomc"]
    fred = next(s for s in block["sources"] if s["id"] == "fred_release_calendar")
    assert fred["status"] == "not_configured" and health["status"] == "partial"
    validate_calendar(block)


def test_a_failing_fred_never_raises_and_never_leaks_the_key():
    class Broken:
        def get(self, url, params=None, **kw):
            raise RuntimeError("could not reach %s?api_key=%s" % (url, params["api_key"]))
    block, health = build_calendar(config(), TODAY, http=Broken(), api_key=SECRET)
    assert health["fred"]["status"] == "unavailable" and health["status"] == "partial"
    assert SECRET not in json.dumps(block) and SECRET not in json.dumps(health)
    assert [e["id"] for e in block["events"]] == ["fomc"]               # the built-in list still shows
    for page in (Answer(status=403), Answer(raw=b"not json"), Answer(raw=b'{"release_dates": 5}')):
        block, health = build_calendar(config(), TODAY, http=FredFake([page]), api_key=SECRET)
        assert health["fred"]["status"] == "unavailable"
        validate_calendar(block)


def test_the_fed_list_warns_when_it_runs_out_and_says_it_is_unchecked():
    cfg = config()
    block, health = build_calendar(cfg, TODAY, http=FredFake([Answer([])]), api_key=SECRET)
    fomc = next(s for s in block["sources"] if s["id"] == "built_in_fomc_list")
    # 22 Nov plus 45 days reaches into 2027, past the end of the list
    assert fomc["status"] == "needs_update" and fomc["checked_against_official_site"] is False
    assert any("FOMC list ends 2026-12-31" in a for a in health["advisories"])
    early = date(2026, 9, 1)                                             # window ends 16 Oct: covered
    block, health = build_calendar(cfg, early, http=FredFake([Answer([])]), api_key=SECRET)
    fomc = next(s for s in block["sources"] if s["id"] == "built_in_fomc_list")
    assert fomc["status"] == "ok"
    assert [e["date"] for e in block["events"] if e["id"] == "fomc"] == ["2026-09-16"]   # 28 Oct is past 16 Oct
    assert not any("FOMC" in a for a in health["advisories"])


def test_most_events_are_capped_and_a_meeting_today_counts_as_zero_days():
    cfg = config(max_events=2)
    day = date(2026, 12, 9)
    page = Answer([row("Employment Situation", "2026-12-09"), row("Consumer Price Index", "2026-12-09")])
    block, _ = build_calendar(cfg, day, http=FredFake([page]), api_key=SECRET)
    assert len(block["events"]) == 2
    assert [e["days_away"] for e in block["events"]] == [0, 0]
    assert [e["importance"] for e in block["events"]] == ["high", "high"]


def test_digest_uses_plain_words_not_dates():
    cfg = config()
    page = Answer([row("Consumer Price Index", "2026-11-23"), row("Employment Situation", "2026-12-04")])
    block, _ = build_calendar(cfg, TODAY, http=FredFake([page]), api_key=SECRET)
    rows = digest_events(block)
    assert rows[0] == {"name": "US consumer price inflation (CPI)", "when": "tomorrow",
                       "category": "inflation"}
    assert [r["when"] for r in rows] == ["tomorrow", "within two weeks", "within a month"]
    assert not any(ch.isdigit() for r in rows for ch in r["when"])


@pytest.mark.parametrize("mutate,message", [
    (lambda b: b["events"][0].update(basis="somebody_said"), "where its date comes from"),
    (lambda b: b["events"][0].update(days_away=-1), "days_away"),
    (lambda b: b["events"][0].update(days_away=99), "days_away"),
    (lambda b: b["events"][0].update(date="soon"), "date"),
    (lambda b: b["events"][0].update(source_url="http://plain.example"), "https"),
    (lambda b: b["events"][0].update(category="sports"), "category"),
    (lambda b: b["sources"][0].update(status="great"), "status"),
    (lambda b: b.update(notice=""), "notice"),
])
def test_contract_rejects_bad_calendars(mutate, message):
    block, _ = build_calendar(config(), TODAY, http=FredFake([Answer([])]), api_key=SECRET)
    validate_calendar(block)
    mutate(block)
    with pytest.raises(ValueError, match=message):
        validate_calendar(block)
