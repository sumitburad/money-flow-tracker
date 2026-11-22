"""The plain-language run summary: the new risk tone, events and news lines."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "summarize_run", Path(__file__).resolve().parent.parent / "scripts" / "summarize_run.py")
summarize_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summarize_run)


def good_status():
    return {
        "status": "degraded", "as_of_ist": "2026-11-22T19:07:00+05:30",
        "regime": {"status": "ok", "label": "risk_on", "short_term_label": "mixed",
                   "checks_with_data": {"week": 8, "month": 7}, "checks_total": 8},
        "calendar": {"status": "ok", "fred": {"status": "ok"}, "events": 6,
                     "advisories": ["one", "two"]},
        "market_news": {"status": "ok", "queries_asked": 10, "queries_answered": 10,
                        "kept": 24, "company_stories": 6},
    }


def test_good_run_lines_are_plain_words():
    text = summarize_run.build(good_status(), {})
    assert "- **Risk tone:** risk-on this month, mixed this week (7 of 8 checks had prices)" in text
    assert "- **Coming events:** 6 coming dates found (FRED calendar read live); 2 notes in the Data quality box" in text
    assert "- **Market news:** 24 headlines kept (6 about companies); 10 of 10 questions answered" in text
    assert "some failed" not in text


def test_old_status_file_without_the_blocks_adds_no_lines():
    text = summarize_run.build({"status": "ok"}, {})
    assert "Risk tone" not in text and "Coming events" not in text and "Market news" not in text


def test_problems_are_reported_without_alarm():
    status = good_status()
    status["regime"] = {"status": "unavailable"}
    status["calendar"] = {"status": "partial", "fred": {"status": "unavailable"}, "events": 1, "advisories": []}
    status["market_news"] = {"status": "unavailable"}
    text = summarize_run.build(status, {})
    assert "- **Risk tone:** could not be worked out this run" in text
    assert "FRED's calendar could not be read, so only Fed meetings are shown" in text
    assert "note" not in text.split("Coming events")[1].split("\n")[0]
    assert "the free news index could not be reached; the page says so" in text


def test_no_fred_key_and_news_switched_off():
    status = good_status()
    status["calendar"] = {"status": "partial", "fred": {"status": "not_configured"}, "events": 1,
                          "advisories": ["one"]}
    status["market_news"] = {"status": "disabled"}
    text = summarize_run.build(status, {})
    assert "1 coming date (Fed meetings only, because no FRED key is saved); 1 note in the Data quality box" in text
    assert "- **Market news:** switched off in the settings" in text


def test_partial_news_says_some_questions_failed():
    status = good_status()
    status["market_news"] = {"status": "partial", "queries_asked": 10, "queries_answered": 7,
                             "kept": 9, "company_stories": 2}
    text = summarize_run.build(status, {})
    assert "9 headlines kept (2 about companies); 7 of 10 questions answered (some failed)" in text


def test_odd_values_never_crash_the_summary():
    status = {"status": "ok", "regime": "oops", "calendar": ["x"], "market_news": 3}
    assert "Money-flow refresh result" in summarize_run.build(status, {})
