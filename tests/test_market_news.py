import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from backend.feed_contract import NEWS_MAX_STORIES, validate_feed, validate_market_news
from backend.market_news import (HEADERS, ask, build_market_news, build_questions, clean_title,
                                 companies_in, default_http, digest_market_news, load_config,
                                 parse_seen, publisher_for)
from backend.net import RetryingHttp

CFG = load_config()
NOW = datetime(2026, 11, 22, 13, 37, tzinfo=timezone.utc)
FORBIDDEN_STORY_KEYS = {"text", "body", "content", "summary", "image", "socialimage", "score", "rank"}


def stamp(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y%m%dT%H%M%SZ")


def article(title, host="reuters.com", hours_ago=3, path=None, language="English", **extra):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    row = {"url": "https://www.%s/%s" % (host, path or slug), "title": title,
           "seendate": stamp(hours_ago), "domain": host, "language": language,
           "sourcecountry": "United States", "socialimage": "https://img.example.org/x.jpg"}
    row.update(extra)
    return row


class Reply:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.content = raw if raw is not None else json.dumps(payload).encode()
        self.headers = {}


class Fake:
    """Answers each question in turn; records what was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout, "headers": headers})
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def ok(*articles):
    return Reply({"articles": list(articles)})


def run(replies, cfg=CFG):
    pauses = []
    block, health = build_market_news(cfg, NOW, http=Fake(replies), sleep=pauses.append)
    return block, health, pauses


# ------------------------------------------------------------------ links and titles

@pytest.mark.parametrize("url,expected", [
    ("https://www.reuters.com/markets/story-1", "Reuters"),
    ("https://reuters.com/x", "Reuters"),
    ("https://economictimes.indiatimes.com/markets/a", "The Economic Times"),
    ("https://m.cnbc.com/2026/11/22/a.html", "CNBC"),
    ("https://www.reuters.com:443/x", "Reuters"),
    ("http://www.reuters.com/x", None),                          # not https
    ("https://reuters.com.evil.example/x", None),                # look-alike host
    ("https://evilreuters.com/x", None),
    ("https://notreuters.com/x", None),
    ("https://reuters.com@evil.example/x", None),                # login part hides the real host
    ("https://user:pw@reuters.com/x", None),
    ("https://www.reuters.com:8443/x", None),
    ("https://www.reuters.com/a b", None),                       # space
    ("https://www.reuters.com/a\"b", None),
    ("https://www.reuters.com/<script>", None),
    ("https://www.reuters.com/" + "a" * 600, None),               # too long
    ("javascript:alert(1)", None),
    ("//www.reuters.com/x", None),
    ("", None), (None, None), (5, None),
    ("https://www.example.org/x", None),
    ("https://indiatimes.com/x", None),                          # only the listed host, not its parent
])
def test_only_plain_https_links_to_listed_publishers_pass(url, expected):
    assert publisher_for(url, CFG["publishers"]) == expected


def test_a_bad_port_does_not_crash():
    assert publisher_for("https://www.reuters.com:99999/x", CFG["publishers"]) is None


def test_titles_are_cleaned_and_shortened():
    assert clean_title("Micron &amp; Nvidia  surge\n on AI demand", 220) == "Micron & Nvidia surge on AI demand"
    assert clean_title("A‮B headline that is long enough", 220) == "A B headline that is long enough"
    assert clean_title("x" * 400, 50) == "x" * 50 + "…"
    assert clean_title("Too short", 220) == ""
    assert clean_title(None, 220) == ""
    assert "\x00" not in clean_title("Bad\x00char headline here ok", 220)


def test_seen_time_is_read_as_utc():
    assert parse_seen("20261122T083000Z") == datetime(2026, 11, 22, 8, 30, tzinfo=timezone.utc)
    assert parse_seen("2026-11-22") is None
    assert parse_seen(None) is None


@pytest.mark.parametrize("title,expected", [
    ("Micron results beat forecasts", ["Micron"]),
    ("micron stock jumps", ["Micron"]),
    ("Micronesia signs trade deal", []),                       # a different word
    ("Micron Technology guides higher", ["Micron"]),
    ("Nvidia and AMD lead chip rally", ["Nvidia", "AMD"]),
    ("Hamdan visits Dubai", []),                                # AMD inside another word
    ("Meta Platforms plans new AI chips", ["Meta"]),
    ("Google parent Alphabet falls", ["Alphabet"]),            # one company, two names, listed once
    ("Wall Street ends higher", []),
    ("TCS wins deal", ["TCS"]),
])
def test_company_names_must_appear_as_whole_words(title, expected):
    assert sorted(companies_in(title, CFG["companies"])) == sorted(expected)


# ------------------------------------------------------------------ the questions

def test_questions_are_the_themes_then_company_groups():
    questions = build_questions(CFG)
    ids = [q[0] for q in questions]
    assert ids[:len(CFG["themes"])] == [t["id"] for t in CFG["themes"]]
    assert set(ids[len(CFG["themes"]):]) == {"companies"}
    assert len(questions) <= CFG["source"]["max_queries"]
    company_questions = [q for q in questions if q[0] == "companies"]
    assert company_questions and all(q[2].startswith('("') for q in company_questions)
    assert '"Micron"' in company_questions[0][2] and '"Micron Technology"' in company_questions[0][2]


def test_the_question_cap_and_the_suffix_are_applied():
    cfg = copy.deepcopy(CFG)
    cfg["source"]["max_queries"] = 3
    cfg["source"]["query_suffix"] = "sourcelang:english"
    questions = build_questions(cfg)
    assert len(questions) == 3 and all(q[2].endswith(" sourcelang:english") for q in questions)


def test_company_names_are_split_into_small_groups():
    cfg = copy.deepcopy(CFG)
    cfg["company_query_size"] = 2
    cfg["source"]["max_queries"] = 99
    groups = [q for q in build_questions(cfg) if q[0] == "companies"]
    assert all(q[2].count(" OR ") <= 1 for q in groups)


def test_ask_sends_the_documented_parameters_and_reads_articles():
    fake = Fake([ok(article("Micron results beat forecasts"))])
    rows = ask(fake, CFG["source"], '("Micron")')
    assert len(rows) == 1
    call = fake.calls[0]
    assert call["url"] == "https://api.gdeltproject.org/api/v2/doc/doc"
    assert call["params"] == {"query": '("Micron")', "mode": "artlist", "format": "json",
                              "maxrecords": 100, "timespan": "48h", "sort": "hybridrel"}
    assert call["headers"] == HEADERS and call["timeout"] == (10, 45)


@pytest.mark.parametrize("reply,expected", [
    (Reply(raw=b""), []), (Reply(raw=b"  \n"), []), (Reply({}), []), (Reply({"articles": []}), []),
])
def test_ask_treats_an_empty_answer_as_no_matches(reply, expected):
    assert ask(Fake([reply]), CFG["source"], "x") == expected


@pytest.mark.parametrize("reply,message", [
    (Reply(raw=b"Your query was too short."), "JSON"),
    (Reply(status=503, raw=b"busy"), "HTTP 503"),
    (Reply(status=429, raw=b""), "HTTP 429"),
    (Reply([1, 2]), "shape"),
    (Reply({"articles": "none"}), "shape"),
    (Reply(raw=b"x" * 3_100_000), "size"),
])
def test_ask_refuses_an_unexpected_answer(reply, message):
    with pytest.raises(Exception, match=message):
        ask(Fake([reply]), CFG["source"], "x")


# ------------------------------------------------------------------ the whole build

def test_a_normal_run_keeps_only_listed_english_recent_headlines():
    rows = [
        article("Wall Street ends higher as chip stocks rally", "reuters.com", 2),
        article("Nvidia and Micron lead a global chip rally", "cnbc.com", 1),
        article("Local blog says markets will crash", "randomblog.example", 1),
        article("Marché en hausse après les résultats", "reuters.com", 1, language="French"),
        article("Very old story about the stock market", "reuters.com", 100),
        article("Story from the future about stock markets", "reuters.com", -5),
        article("Short", "reuters.com", 1),
        {"url": "https://www.reuters.com/no-date", "title": "Story with no date at all here", "language": "English"},
    ]
    block, health, _ = run([ok(*rows)] + [Reply({})] * 20)
    titles = [s["title"] for s in block["stories"]]
    assert titles == ["Nvidia and Micron lead a global chip rally", "Wall Street ends higher as chip stocks rally"]
    assert block["status"] == "ok" and health["status"] == "ok"
    assert health["articles_seen"] == len(rows)


def test_a_headline_is_kept_once_and_remembers_every_theme_it_matched():
    same = article("Nvidia results lift the stock market", "cnbc.com", 2)
    copy_of_it = dict(same, url="https://www.cnbc.com/other-link")
    replies = [ok(same), Reply({}), Reply({}), ok(copy_of_it)] + [Reply({})] * 20
    block, _, _ = run(replies)
    assert len(block["stories"]) == 1
    assert block["stories"][0]["topics"] == ["ai_chips", "us_markets"]
    assert block["stories"][0]["companies"] == ["Nvidia"]


def test_a_company_question_keeps_only_headlines_that_name_the_company():
    n_themes = len(CFG["themes"])
    replies = [Reply({})] * n_themes + [ok(
        article("Micron results beat forecasts on AI memory demand", "reuters.com", 2),
        article("Some unrelated technology story about devices", "reuters.com", 2))] + [Reply({})] * 5
    block, _, _ = run(replies)
    assert [s["title"] for s in block["stories"]] == ["Micron results beat forecasts on AI memory demand"]
    assert block["stories"][0]["companies"] == ["Micron"]
    assert block["stories"][0]["topics"] == ["companies"]


def test_a_company_in_a_theme_headline_is_recognised_too():
    block, _, _ = run([ok(article("Micron surges after results", "marketwatch.com", 2))] + [Reply({})] * 20)
    assert block["stories"][0]["companies"] == ["Micron"]
    assert block["stories"][0]["topics"] == ["us_markets"]


def test_newest_first_and_each_story_has_only_the_allowed_fields():
    rows = [article("Older story about the stock market today", "reuters.com", 20),
            article("Newest story about the stock market now", "cnbc.com", 1),
            article("Middle story about the stock market here", "ft.com", 9)]
    block, _, _ = run([ok(*rows)] + [Reply({})] * 20)
    assert [s["seen_at_utc"] for s in block["stories"]] == sorted(
        (s["seen_at_utc"] for s in block["stories"]), reverse=True)
    for story in block["stories"]:
        assert set(story) == {"id", "title", "publisher", "url", "seen_at_utc", "topics", "companies"}
        assert not FORBIDDEN_STORY_KEYS & set(story)
        assert story["url"].startswith("https://")


def test_one_publisher_cannot_fill_the_page_and_company_stories_are_capped():
    cfg = copy.deepcopy(CFG)
    cfg["limits"].update(max_stories=8, max_company_stories=3, max_per_publisher=2)
    rows = [article("Reuters market story number %d about stocks" % i, "reuters.com", i + 1) for i in range(6)]
    rows += [article("CNBC market story number %d about stocks" % i, "cnbc.com", i + 1) for i in range(6)]
    rows += [article("Nvidia story number %d about the chip race" % i, "ft.com", i + 1) for i in range(6)]
    block, _, _ = run([ok(*rows)] + [Reply({})] * 20, cfg)
    publishers = [s["publisher"] for s in block["stories"]]
    assert all(publishers.count(p) <= 2 for p in set(publishers))
    assert len(block["stories"]) <= 6                      # three listed publishers, two each
    assert sum(1 for s in block["stories"] if s["companies"]) <= 3


def test_the_total_is_capped():
    cfg = copy.deepcopy(CFG)
    cfg["limits"].update(max_stories=5, max_per_publisher=99)
    rows = [article("Market story number %d about the stock market" % i, "reuters.com", i + 1) for i in range(20)]
    block, _, _ = run([ok(*rows)] + [Reply({})] * 20, cfg)
    assert len(block["stories"]) == 5


def test_the_program_waits_between_questions_but_not_before_the_first():
    block, health, pauses = run([Reply({})] * 20)
    asked = health["queries_asked"]
    assert asked == len(build_questions(CFG)) and len(pauses) == asked - 1
    assert set(pauses) == {CFG["source"]["pause_seconds"]}


# ------------------------------------------------------------------ when the source misbehaves

def test_some_questions_failing_gives_a_partial_block_and_a_note():
    replies = [ok(article("Stock market story that is long enough", "reuters.com", 2)),
               Reply(raw=b"Your query was too short."), Reply(status=503, raw=b""),
               requests.ConnectionError("down")] + [Reply({})] * 20
    block, health, _ = run(replies)
    assert block["status"] == "partial" and health["status"] == "partial"
    assert len(block["stories"]) == 1
    assert len(health["errors"]) == 3
    assert block["queries"]["answered"] < block["queries"]["asked"]


def test_every_question_failing_gives_an_empty_unavailable_block():
    block, health, _ = run([requests.ConnectionError("down")])
    assert block["status"] == "unavailable" and block["stories"] == []
    assert health["status"] == "unavailable" and health["queries_answered"] == 0
    validate_market_news(block)


def test_a_source_that_keeps_failing_is_dropped_after_two_failures():
    calls = []

    def fetcher(url, **kw):
        calls.append(url)
        raise requests.ConnectionError("down")
    http = RetryingHttp(attempts=2, backoff=0.0, jitter=False, sleep=lambda s: None, fetcher=fetcher)
    block, health = build_market_news(CFG, NOW, http=http, sleep=lambda s: None)
    assert len(calls) == 4                         # two questions, two tries each; then it gives up
    assert health["queries_asked"] == 3 and health["queries_answered"] == 0
    assert any("failed twice" in e for e in health["errors"])
    assert block["status"] == "unavailable"


def test_the_default_http_waits_longer_than_the_five_seconds_the_source_asks_for():
    http = default_http()
    assert http.attempts == 3 and http.backoff >= 10.0 and http.max_delay >= 30.0


def test_the_switch_turns_the_feature_off_without_calling_the_source():
    cfg = copy.deepcopy(CFG)
    cfg["enabled"] = False
    fake = Fake([Reply({})])
    block, health = build_market_news(cfg, NOW, http=fake, sleep=lambda s: None)
    assert block["status"] == "disabled" and block["stories"] == [] and fake.calls == []
    assert health["status"] == "disabled"
    validate_market_news(block)


def test_no_listed_publisher_is_reported_so_the_list_can_be_fixed():
    rows = [article("Stock market story from an unlisted site", "randomblog.example", 2)]
    block, health, _ = run([ok(*rows)] + [Reply({})] * 20)
    assert block["stories"] == [] and block["status"] == "ok"
    assert any("no headline came from a listed publisher" in a for a in health["advisories"])


def test_an_answer_with_no_headlines_is_reported():
    block, health, _ = run([Reply({})] * 20)
    assert block["status"] == "ok" and block["stories"] == []
    assert any("no headlines" in a for a in health["advisories"])


def test_a_broken_settings_file_never_raises():
    block, health = build_market_news({"enabled": True}, NOW, http=Fake([Reply({})]), sleep=lambda s: None)
    assert health["status"] == "unavailable" and health["errors"]
    assert block is None


def test_garbage_inside_the_answer_is_skipped():
    rows = ["text", None, 5, {"title": "no url at all but a long title"},
            {"url": ["x"], "title": "list as url but a long title"},
            article("Valid stock market story with enough words", "reuters.com", 2)]
    block, _, _ = run([ok(*rows)] + [Reply({})] * 20)
    assert [s["title"] for s in block["stories"]] == ["Valid stock market story with enough words"]


def test_a_key_or_secret_never_appears_in_the_block_or_the_notes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-value-123456")
    block, health, _ = run([Reply(raw=b"error mentions sk-or-secret-value-123456 here")] + [Reply({})] * 20)
    assert "sk-or-secret-value-123456" not in json.dumps(block) + json.dumps(health)


# ------------------------------------------------------------------ patience and the time budget

class Clock:
    """A pretend clock: time only moves when the program sleeps or the news index takes its time."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class SlowFake(Fake):
    """Answers like Fake, but each answer (or failure) takes ``takes`` seconds on the pretend clock."""

    def __init__(self, replies, clock, takes):
        super().__init__(replies)
        self.clock, self.takes = clock, takes

    def get(self, url, **kw):
        self.clock.now += self.takes
        return super().get(url, **kw)


def timed(replies, takes, cfg=CFG):
    clock = Clock()
    block, health = build_market_news(cfg, NOW, http=SlowFake(replies, clock, takes),
                                      sleep=clock.sleep, clock=clock)
    return block, health, clock


def test_a_slow_but_working_news_index_is_waited_for_and_the_real_times_are_recorded():
    story = ok(article("Stock market story that is long enough", "reuters.com", 2))
    block, health, clock = timed([story] + [Reply({})] * 20, takes=20.0)
    assert health["status"] == "ok" and health["queries_skipped"] == 0
    assert health["slowest_answer_seconds"] == 20.0
    questions = len(build_questions(CFG))
    assert health["seconds"] == round(questions * 20.0 + (questions - 1) * CFG["source"]["pause_seconds"], 1)
    assert health["seconds"] < CFG["source"]["total_seconds"]          # a normal run fits the budget
    assert len(block["stories"]) == 1


def test_the_time_budget_stops_new_questions_and_says_so_in_plain_words():
    cfg = copy.deepcopy(CFG)
    cfg["source"]["total_seconds"] = 100
    block, health, clock = timed([Reply({})] * 20, takes=30.0, cfg=cfg)
    # 30 s, pause, 30 s, pause, 30 s = 101 s: no time is left for a fourth question
    assert health["queries_asked"] == 3 and health["queries_answered"] == 3
    assert health["queries_skipped"] == len(build_questions(cfg)) - 3
    assert health["status"] == "partial" and block["status"] == "partial"
    [note] = health["errors"]
    assert note.startswith("The news step stopped after 101 seconds") and "were not asked" in note
    validate_market_news(block)


def test_a_dead_news_index_costs_less_than_the_budget_and_the_refresh_goes_on():
    source = CFG["source"]
    connect, read = source["timeout_seconds"]
    default = default_http()
    worst = default.breaker_after * (default.attempts * read + default.backoff * (default.attempts - 1))
    assert worst <= source["total_seconds"] <= 600      # well inside the 25 minutes the job is given


def test_a_timeout_is_explained_without_web_addresses_or_library_words():
    jargon = "HTTPSConnectionPool(host='api.gdeltproject.org', port=443): Read timed out. (read timeout=45)"
    for failure, expected in ((requests.ReadTimeout(jargon), "no answer from the news index within 45 seconds"),
                              (requests.ConnectTimeout(jargon), "could not reach the news index within 10 seconds"),
                              (requests.ConnectionError(jargon), "could not connect to the news index")):
        block, health, _ = run([failure])
        assert health["errors"][0] == expected, failure
        assert "gdelt" not in health["errors"][0].lower() and "Pool" not in health["errors"][0]


def test_the_note_says_how_many_tries_were_made_when_the_http_helper_retries():
    def fetcher(url, **kw):
        raise requests.ReadTimeout("slow")
    http = RetryingHttp(attempts=2, backoff=0.0, jitter=False, sleep=lambda s: None, fetcher=fetcher)
    block, health = build_market_news(CFG, NOW, http=http, sleep=lambda s: None)
    assert health["errors"][0] == "no answer from the news index within 45 seconds (2 tries)"
    assert any("failed twice" in e for e in health["errors"])


def test_the_answers_the_program_writes_itself_are_kept_as_they_are():
    block, health, _ = run([Reply(status=429, raw=b""), Reply(raw=b"Your query was too short.")] + [Reply({})] * 20)
    assert health["errors"][0] == "news index answered HTTP 429"
    assert health["errors"][1].startswith("news index did not answer with JSON: Your query was too short")


# ------------------------------------------------------------------ the contract

def good_block():
    rows = [article("Nvidia and Micron lead a global chip rally", "cnbc.com", 1),
            article("Wall Street ends higher as chip stocks rally", "reuters.com", 2)]
    return run([ok(*rows)] + [Reply({})] * 20)[0]


def minimal_feed(**extra):
    fam = {"state": "not_available", "evidence": "none", "source": None}
    item = {"id": "x", "item": "T", "group": "g", "symbol": "T", "region": "US",
            "currency": "USD", "label": "Neutral/Mixed", "tag": "Steady",
            "agreement": "Weak", "freshness": "current",
            "families": {name: dict(fam) for name in ("money_flow", "price_trend", "breadth",
                                                      "positioning", "macro_liquidity", "news")}}
    feed = {"schema_version": "1.0", "usage": "research_only_not_order_authorization",
            "items": [item], "macro": {}}
    feed.update(extra)
    return feed


def test_a_good_block_passes_and_an_old_feed_still_does():
    validate_market_news(good_block())
    assert validate_feed(minimal_feed())
    assert validate_feed(minimal_feed(market_news=good_block()))


@pytest.mark.parametrize("edit,message", [
    (lambda b: b.update(status="great"), "status"),
    (lambda b: b.update(as_of_utc="2026-11-22T13:37:00"), "timezone"),
    (lambda b: b.update(as_of_utc="yesterday"), "timestamp"),
    (lambda b: b.pop("source"), "source"),
    (lambda b: b["source"].update(url="http://www.gdeltproject.org/"), "https"),
    (lambda b: b["queries"].update(answered=99), "queries"),
    (lambda b: b["queries"].update(asked=-1), "queries"),
    (lambda b: b.update(themes="x"), "themes"),
    (lambda b: b.update(watchlist=[1]), "watchlist"),
    (lambda b: b.update(stories={}), "stories"),
    (lambda b: b["stories"].append(copy.deepcopy(b["stories"][0])), "duplicate"),
    (lambda b: b["stories"][0].update(url="http://www.reuters.com/x"), "https"),
    (lambda b: b["stories"][0].update(url="javascript:alert(1)"), "https"),
    (lambda b: b["stories"][0].update(title=""), "title"),
    (lambda b: b["stories"][0].update(title="x" * (300 + 1)), "too long"),
    (lambda b: b["stories"][0].update(seen_at_utc="2026-11-22T10:00:00"), "timezone"),
    (lambda b: b["stories"][0].update(topics=["made_up"]), "unknown topic"),
    (lambda b: b["stories"][0].update(companies=["Not Listed Inc"]), "watchlist"),
    (lambda b: b["stories"][0].update(topics="x"), "topics"),
    (lambda b: b.pop("notice"), "notice"),
    (lambda b: b.update(stories=b["stories"] * 40), "short list"),
])
def test_contract_rejects_a_malformed_block(edit, message):
    block = good_block()
    edit(block)
    with pytest.raises(ValueError, match=message):
        validate_market_news(block)


def test_an_unavailable_source_cannot_carry_headlines():
    block = good_block()
    block["status"] = "unavailable"
    with pytest.raises(ValueError, match="cannot carry"):
        validate_market_news(block)


def test_forbidden_fields_are_still_refused_inside_the_block():
    block = good_block()
    block["stories"][0]["score"] = 5
    with pytest.raises(ValueError, match="forbidden"):
        validate_feed(minimal_feed(market_news=block))


# ------------------------------------------------------------------ for the summary

def test_the_summary_sees_company_stories_first_and_one_publisher_at_a_time():
    rows = [article("Stock market story one from Reuters today", "reuters.com", 1),
            article("Stock market story two from Reuters today", "reuters.com", 2),
            article("Stock market story three from CNBC today", "cnbc.com", 3),
            article("Micron results beat forecasts on AI memory demand", "ft.com", 4)]
    block = run([ok(*rows)] + [Reply({})] * 20)[0]
    digest = digest_market_news(block, limit=3)
    assert len(digest) == 3
    assert digest[0]["headline"].startswith("Micron results") and digest[0]["companies"] == ["Micron"]
    assert {d["publisher"] for d in digest} == {"Financial Times", "Reuters", "CNBC"}
    assert all(set(d) == {"headline", "publisher", "companies", "topics"} for d in digest)


def test_the_summary_gets_nothing_from_a_source_that_failed():
    assert digest_market_news(None) == []
    assert digest_market_news({"status": "unavailable", "stories": []}) == []
    assert digest_market_news({"status": "disabled", "stories": []}) == []


def test_long_headlines_are_shortened_for_the_summary():
    rows = [article("A" * 10 + " stock market " + "very long " * 30, "reuters.com", 1)]
    block = run([ok(*rows)] + [Reply({})] * 20)[0]
    assert len(digest_market_news(block)[0]["headline"]) <= 140


# ------------------------------------------------------------------ the settings file

def test_settings_are_consistent():
    source, limits = CFG["source"], CFG["limits"]
    assert source["url"].startswith("https://") and source["home_page"].startswith("https://")
    assert float(source["pause_seconds"]) >= 5.0
    assert 1 <= source["max_records"] <= 250
    assert source["sort"] in {"hybridrel", "datedesc", "dateasc", "toneasc", "tonedesc"}
    assert re.fullmatch(r"\d+(min|h|d|w)", source["timespan"])
    assert len(source["timeout_seconds"]) == 2
    connect, read = source["timeout_seconds"]
    assert connect >= 5 and read >= 45                  # the news index is often slow; 25 seconds was too short
    assert limits["max_stories"] <= NEWS_MAX_STORIES
    assert 0 < limits["max_company_stories"] <= limits["max_stories"]
    assert limits["max_per_publisher"] >= 1 and limits["max_age_hours"] > 0
    ids = [t["id"] for t in CFG["themes"]]
    assert len(ids) == len(set(ids)) and "companies" not in ids
    for theme in CFG["themes"]:
        query = theme["query"]
        assert theme["name"] and "&" not in query
        words = re.findall(r"[A-Za-z]+", re.sub(r'"[^"]*"', "", query).replace(" OR ", " "))
        assert all(len(w) >= 3 for w in words), theme["id"]
    assert source["max_queries"] >= len(ids) + 1
    domains = [p["domain"] for p in CFG["publishers"]]
    assert len(domains) == len(set(domains)) and all(d == d.lower() and "/" not in d for d in domains)
    names = [c["name"] for c in CFG["companies"]]
    assert len(names) == len(set(names))
    assert all(len(n) >= 3 for c in CFG["companies"] for n in [c["name"]] + c.get("aliases", []))


def test_a_full_default_run_makes_no_more_questions_than_the_cap_and_takes_a_bounded_time():
    questions = build_questions(CFG)
    assert len(questions) <= CFG["source"]["max_queries"]
    assert (len(questions) - 1) * CFG["source"]["pause_seconds"] < 90


# ------------------------------------------------------------------ what the news index says when it refuses

class Busy:
    """A refusing answer with text and a Retry-After header, like the news index's own 429."""

    def __init__(self, text, status=429, retry_after=None):
        self.status_code = status
        self.content = text.encode() if isinstance(text, str) else text
        self.headers = {"Retry-After": retry_after} if retry_after is not None else {}


def refusal(reply):
    with pytest.raises(requests.HTTPError) as caught:
        ask(Fake([reply]), CFG["source"], "x")
    return str(caught.value)


def test_a_busy_answer_carries_the_servers_own_words_so_a_wait_can_be_told_from_a_block():
    text = refusal(Busy("Please limit requests to one every 5 seconds or contact kleinsteinhaus@gmail.com"))
    assert text.startswith("news index answered HTTP 429 (it said: Please limit requests to one every 5 seconds")


def test_a_wait_the_server_asks_for_is_reported_in_seconds():
    assert refusal(Busy("Slow down", retry_after="7")) == (
        "news index answered HTTP 429 (it said: Slow down; it asked for a wait of 7 seconds)")
    assert refusal(Busy("", retry_after="12")) == (
        "news index answered HTTP 429 (it asked for a wait of 12 seconds)")


def test_a_wait_written_as_a_date_is_ignored_instead_of_breaking_the_note():
    assert refusal(Busy("", retry_after="Sun, 22 Nov 2026 13:40:00 GMT")) == "news index answered HTTP 429"


def test_an_empty_refusal_says_only_the_status():
    assert refusal(Busy("")) == "news index answered HTTP 429"
    assert refusal(Busy(b"", status=503)) == "news index answered HTTP 503"


def test_markup_and_web_addresses_are_removed_from_what_the_server_said():
    text = refusal(Busy("<html><body><h1>Too Many Requests</h1> see https://example.org/help?x=1 now</body></html>"))
    assert "<" not in text and "http" not in text.split("HTTP", 1)[1] and "example.org" not in text
    assert text == "news index answered HTTP 429 (it said: Too Many Requests see now)"


def test_what_the_server_said_is_cut_to_ninety_characters():
    text = refusal(Busy("x" * 500))
    said = text.split("it said: ", 1)[1].rstrip(")")
    assert len(said) == 90


def test_a_secret_in_what_the_server_said_is_hidden(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "abcd1234efgh5678")
    text = refusal(Busy("bad request: api_key=abcd1234efgh5678 and again abcd1234efgh5678"))
    assert "abcd1234efgh5678" not in text and "***" in text


def test_text_that_cannot_be_read_never_breaks_the_note():
    assert refusal(Busy(b"\xff\xfe\x00bad bytes", status=502)).startswith("news index answered HTTP 502")

    class Odd:
        status_code, headers, content = 500, None, None
    assert refusal(Odd()) == "news index answered HTTP 500"


def test_the_note_for_a_busy_index_reaches_the_health_record_in_plain_words():
    block, health, _ = run([Busy("Please limit requests to one every 5 seconds.")])
    assert health["errors"][0].startswith("news index answered HTTP 429 (it said: Please limit requests")
    assert "gdelt" not in health["errors"][0].lower()


def test_a_too_many_requests_answer_is_waited_out_and_then_the_question_is_answered():
    waits, answers = [], [Busy("Please limit requests to one every 5 seconds"),
                          ok(article("Stock market story that is long enough", "reuters.com", 2))]
    http = RetryingHttp(attempts=3, backoff=10.0, max_delay=30.0, jitter=False, sleep=waits.append,
                        fetcher=lambda url, **kw: answers.pop(0))
    rows = ask(http, CFG["source"], "x")
    assert len(rows) == 1 and waits == [10.0]               # one wait of ten seconds, then success


def test_a_wait_the_server_asks_for_is_respected_up_to_thirty_seconds():
    waits, calls = [], []

    def fetcher(url, **kw):
        calls.append(url)
        return Busy("slow down", retry_after="25") if len(calls) < 3 else ok()
    http = RetryingHttp(attempts=3, backoff=10.0, max_delay=30.0, jitter=False, sleep=waits.append, fetcher=fetcher)
    ask(http, CFG["source"], "x")
    assert waits == [25.0, 25.0]          # the server's 25 s beats our own 10 s and 20 s


def test_a_long_wait_the_server_asks_for_is_capped_at_thirty_seconds():
    waits = []
    http = RetryingHttp(attempts=2, backoff=10.0, max_delay=30.0, jitter=False, sleep=waits.append,
                        fetcher=lambda url, **kw: Busy("slow down", retry_after="600"))
    with pytest.raises(requests.HTTPError, match="asked for a wait of 600 seconds"):
        ask(http, CFG["source"], "x")
    assert waits == [30.0]


def test_a_real_requests_answer_is_read_the_same_way():
    real = requests.Response()
    real.status_code = 429
    real._content = b"<p>Please limit requests to one every 5 seconds.</p>"
    real.headers["Retry-After"] = "5"
    assert refusal(real) == ("news index answered HTTP 429 "
                             "(it said: Please limit requests to one every 5 seconds.; it asked for a wait of 5 seconds)")
