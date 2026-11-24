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


def test_the_news_line_says_how_many_headlines_came_back_and_how_many_were_from_listed_publishers():
    status = good_status()
    status["market_news"] = {"status": "partial", "queries_asked": 6, "queries_answered": 2, "queries_skipped": 4,
                             "kept": 1, "company_stories": 0, "articles_seen": 200, "from_listed_publishers": 1,
                             "publisher_filter": "on"}
    line = [l for l in summarize_run.build(status, {}).splitlines() if "Market news" in l][0]
    assert line == ("- **Market news:** 1 headlines kept (0 about companies); 2 of 6 questions answered (some failed); "
                    "4 more not asked; the news index sent 200 headlines, 1 from the listed publishers")


def test_a_refused_publisher_filter_is_said_plainly():
    status = good_status()
    status["market_news"]["publisher_filter"] = "switched off during this refresh"
    line = [l for l in summarize_run.build(status, {}).splitlines() if "Market news" in l][0]
    assert line.endswith("the index refused the publisher filter, so it was turned off for this run")
    status["market_news"]["publisher_filter"] = "on"
    assert "refused" not in summarize_run.build(status, {})


def test_odd_values_inside_the_news_block_never_crash_the_summary():
    status = good_status()
    status["market_news"] = {"status": "partial", "kept": None, "queries_skipped": "x", "articles_seen": {"a": 1},
                             "from_listed_publishers": [], "publisher_filter": 7}
    assert "Market news" in summarize_run.build(status, {})


def test_odd_values_never_crash_the_summary():
    status = {"status": "ok", "regime": "oops", "calendar": ["x"], "market_news": 3}
    assert "Money-flow refresh result" in summarize_run.build(status, {})


# ------------------------------------------------------------------ the publishers' own news feeds

def feeds_status(**extra):
    news = {"status": "partial", "queries_asked": 16, "queries_answered": 13, "kept": 30, "company_stories": 9,
            "articles_seen": 400, "from_listed_publishers": 380,
            "feeds": {"asked": 16, "answered": 13, "results": [
                {"id": "cnbc_finance", "publisher": "CNBC", "status": "ok", "items": 30, "usable": 30},
                {"id": "wsj_markets", "publisher": "The Wall Street Journal", "status": "failed",
                 "items": 0, "usable": 0, "error": "the feed answered HTTP 403 (it said: Access Denied)"},
                {"id": "marketwatch_top", "publisher": "MarketWatch", "status": "failed",
                 "items": 0, "usable": 0, "error": "no answer within 20 seconds (2 tries)"},
                {"id": "mint_markets", "publisher": "Mint", "status": "skipped", "items": 0, "usable": 0,
                 "error": "not asked: this website failed twice"}]}}
    news.update(extra)
    status = good_status()
    status["market_news"] = news
    return status


def news_lines(status):
    text = summarize_run.build(status, {})
    return [l for l in text.splitlines() if "Market news" in l or "Feeds with a problem" in l]


def test_feed_news_says_feeds_and_names_the_ones_with_a_problem():
    assert news_lines(feeds_status()) == [
        "- **Market news:** 30 headlines kept (9 about companies); 13 of 16 news feeds answered (some failed); "
        "the feeds sent 400 headlines, 380 from the listed publishers",
        "  - Feeds with a problem: The Wall Street Journal (the feed answered HTTP 403 (it said: Access Denied)); "
        "MarketWatch (no answer within 20 seconds (2 tries)); Mint (not asked: this website failed twice)"]


def test_a_clean_feed_run_has_no_problem_line():
    status = feeds_status(status="ok", queries_answered=16)
    for row in status["market_news"]["feeds"]["results"]:
        row["status"] = "ok"
    lines = news_lines(status)
    assert lines == ["- **Market news:** 30 headlines kept (9 about companies); 16 of 16 news feeds answered; "
                     "the feeds sent 400 headlines, 380 from the listed publishers"]


def test_feeds_and_the_news_index_together_say_requests_and_sources():
    lines = news_lines(feeds_status(publisher_filter="on"))
    assert "13 of 16 news requests answered (some failed)" in lines[0]
    assert "the news sources sent 400 headlines" in lines[0]


def test_every_feed_failing_is_said_plainly_and_names_the_feeds():
    status = feeds_status(status="unavailable", queries_answered=0, kept=0, company_stories=0)
    lines = news_lines(status)
    assert lines[0] == "- **Market news:** none of the publishers' news feeds could be read; the page says so"
    assert lines[1].startswith("  - Feeds with a problem: The Wall Street Journal")


def test_a_long_feed_error_is_cut_short_and_only_four_feeds_are_named():
    status = feeds_status()
    status["market_news"]["feeds"]["results"] = [
        {"id": "f%d" % n, "publisher": "Publisher %d" % n, "status": "failed", "error": "x" * 300} for n in range(7)]
    line = news_lines(status)[1]
    assert line.count("Publisher ") == 4 and line.endswith("; and 3 more") and len(line) < 500


def test_odd_values_inside_the_feed_notes_never_crash_the_summary():
    for odd in ("x", 5, None, [1, None, "a"], {"results": "x"}, {"results": [1, None, {"status": "failed"}]}):
        status = feeds_status()
        status["market_news"]["feeds"] = odd
        assert "Market news" in summarize_run.build(status, {})
