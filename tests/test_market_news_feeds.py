"""Market news from the publishers' own feeds (RSS / Atom). No network: every answer is a stand-in."""
import copy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from backend.feed_contract import validate_market_news
from backend.market_news import (FEED_HEADERS, MAX_FEED_BYTES, build_market_news, default_feed_http,
                                 explain_feed_error, load_config, read_feed, strip_markup, topics_in)
from backend.net import RetryingHttp

SHIPPED = load_config()
NOW = datetime(2026, 11, 22, 13, 37, tzinfo=timezone.utc)

CNBC = {"id": "cnbc_finance", "domain": "cnbc.com", "theme": "us_markets",
        "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"}
CNBC_TECH = {"id": "cnbc_technology", "domain": "cnbc.com", "theme": "ai_chips",
             "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html"}
WSJ = {"id": "wsj_markets", "domain": "wsj.com", "theme": "us_markets",
       "url": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"}
ET = {"id": "et_markets", "domain": "economictimes.indiatimes.com", "theme": "india_markets",
      "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"}
ET2 = {"id": "et_stocks", "domain": "economictimes.indiatimes.com", "theme": "india_markets",
       "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"}
ET3 = {"id": "et_more", "domain": "economictimes.indiatimes.com", "theme": "india_markets",
       "url": "https://economictimes.indiatimes.com/news/rssfeeds/1.cms"}


def when(hours_ago):
    return NOW - timedelta(hours=hours_ago)


def link(domain, slug):
    host = domain if domain.startswith("economictimes") else "www." + domain
    return "https://%s/%s" % (host, slug)


def item(title, url, hours_ago=3, with_time=True):
    stamp = "<pubDate>%s</pubDate>" % format_datetime(when(hours_ago), usegmt=True) if with_time else ""
    return "<item><title>%s</title><link>%s</link>%s<guid>%s</guid></item>" % (title, url, stamp, url)


def rss(*items):
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Feed</title>'
            + "".join(items) + "</channel></rss>").encode()


def atom(title, url, hours_ago=3):
    return ('<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom">'
            "<title>Feed</title><entry><title>%s</title><link href=\"%s\" rel=\"alternate\"/>"
            "<id>%s</id><updated>%s</updated></entry></feed>"
            % (title, url, url, when(hours_ago).strftime("%Y-%m-%dT%H:%M:%SZ"))).encode()


class Reply:
    def __init__(self, raw=b"", status=200, headers=None):
        self.status_code = status
        self.content = raw
        self.headers = headers or {}


class FeedFake:
    """Answers each feed address from a dict (a reply, or an exception to raise); records the requests."""

    attempts = 2

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        self.calls.append({"url": url, "params": params, "timeout": timeout, "headers": headers})
        answer = self.answers.get(url)
        if answer is None:
            raise requests.ConnectionError("no such feed in this test")
        if isinstance(answer, Exception):
            raise answer
        return answer


def feeds_cfg(*feeds, **settings):
    cfg = copy.deepcopy(SHIPPED)
    cfg["feeds"]["list"] = [dict(f) for f in feeds]
    cfg["feeds"].update(settings)
    return cfg


def run(cfg, answers, **kwargs):
    fake, pauses = FeedFake(answers), []
    block, health = build_market_news(cfg, NOW, feed_http=fake, sleep=pauses.append, **kwargs)
    return block, health, pauses, fake


def valid(block):
    validate_market_news(block)
    return block


# ------------------------------------------------------------------ reading one feed

def test_a_feed_is_asked_honestly_and_only_headline_link_and_time_are_read():
    good = link("cnbc.com", "2026/11/22/micron.html")
    fake = FeedFake({CNBC["url"]: Reply(rss(
        item("Micron results beat forecasts on AI memory demand", good, 2)))})
    rows = read_feed(fake, CNBC, SHIPPED["feeds"])
    assert rows == [{"title": "Micron results beat forecasts on AI memory demand", "link": good, "seen": when(2)}]
    call = fake.calls[0]
    assert call["url"] == CNBC["url"] and call["params"] is None
    assert call["headers"] == FEED_HEADERS and call["timeout"] == tuple(SHIPPED["feeds"]["timeout_seconds"])
    agent = FEED_HEADERS["User-Agent"]
    assert "money-flow-monitor" in agent and "github.com/sumitburad/money-flow-tracker" in agent
    assert "Mozilla" not in agent                         # no pretending to be a browser
    assert "application/rss+xml" in FEED_HEADERS["Accept"]


def test_an_atom_feed_is_read_too_and_its_updated_time_is_used():
    url = link("business-standard.com", "markets/story-1")
    rows = read_feed(FeedFake({ET["url"]: Reply(atom("Sensex ends higher on bank gains", url, 4))}), ET,
                     SHIPPED["feeds"])
    assert rows == [{"title": "Sensex ends higher on bank gains", "link": url, "seen": when(4)}]


def test_an_entry_without_a_time_has_no_time_and_is_not_given_one():
    rows = read_feed(FeedFake({CNBC["url"]: Reply(rss(item("No time given in this entry", link("cnbc.com", "a"),
                                                         with_time=False)))}), CNBC, SHIPPED["feeds"])
    assert rows[0]["seen"] is None


@pytest.mark.parametrize("reply,message", [
    (Reply(b"<html><head><title>Access Denied</title></head><body>no</body></html>"),
     "not a news feed (it said: Access Denied)"),
    (Reply(b"<!DOCTYPE html><html><body>Just a moment...</body></html>"), "not a news feed"),
    (Reply(b""), "not a news feed"),
    (Reply(b'{"articles": []}'), "not a news feed"),
    (Reply(b"Forbidden", status=403), "HTTP 403 (it said: Forbidden)"),
    (Reply(b"", status=503), "HTTP 503"),
    (Reply(b"x" * (MAX_FEED_BYTES + 1)), "larger than expected"),
    (Reply(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss version="2.0">'
           b"<channel><title>&b;</title></channel></rss>"), "entity declarations"),
])
def test_an_answer_that_is_not_a_usable_feed_is_refused_in_plain_words(reply, message):
    with pytest.raises(Exception, match=message.replace("(", r"\(").replace(")", r"\)")):
        read_feed(FeedFake({CNBC["url"]: reply}), CNBC, SHIPPED["feeds"])


def test_text_an_error_page_says_is_cleaned_before_it_is_shown():
    page = b"<html><title>Blocked https://secret.example/x?api_key=abc123456789</title></html>"
    with pytest.raises(ValueError) as caught:
        read_feed(FeedFake({CNBC["url"]: Reply(page)}), CNBC, SHIPPED["feeds"])
    assert "api_key=abc" not in str(caught.value) and "https://" not in str(caught.value)


@pytest.mark.parametrize("exc,expected", [
    (requests.ReadTimeout("slow"), "no answer within 20 seconds (2 tries)"),
    (requests.ConnectTimeout("slow"), "could not be reached within 8 seconds (2 tries)"),
    (requests.ConnectionError("down"), "could not connect (2 tries)"),
    (requests.HTTPError("the feed answered HTTP 403"), "the feed answered HTTP 403"),
    (KeyError("x"), "KeyError"),
])
def test_feed_errors_are_one_plain_sentence(exc, expected):
    assert explain_feed_error(exc, SHIPPED["feeds"], FeedFake({})) == expected


def test_an_entry_without_a_title_or_a_link_is_dropped_and_counted_not_a_crash():
    xml = ('<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>'
           "<item><link>%s</link><pubDate>%s</pubDate></item>"
           "<item><title>A headline with no link at all in it</title><pubDate>%s</pubDate></item>"
           "</channel></rss>") % (link("cnbc.com", "a"), format_datetime(when(2), usegmt=True),
                                  format_datetime(when(2), usegmt=True))
    block, health, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(xml.encode())})
    valid(block)
    assert block["stories"] == [] and block["status"] == "ok"
    assert health["dropped"] == {"not_a_listed_publisher": 1, "unusable_headline": 1}
    assert health["feeds"]["results"][0]["items"] == 2 and health["feeds"]["results"][0]["usable"] == 0


def test_markup_is_taken_out_of_titles():
    assert strip_markup("<b>Wall Street</b> ends <i>higher</i>").split() == ["Wall", "Street", "ends", "higher"]
    assert strip_markup(None) == ""


def test_topics_are_found_from_whole_words_only():
    themes = SHIPPED["themes"]
    assert topics_in("Nifty ends higher as Sensex gains", themes) == ["india_markets"]
    assert topics_in("Wall Street ends higher as chip stocks rally", themes) == ["us_markets", "ai_chips"]
    assert topics_in("Goldman Sachs raises its outlook", themes) == []          # "gold" is not "Goldman"
    assert topics_in("Bitcoin slides as the US dollar firms", themes) == ["commodities_fx", "crypto"]
    assert topics_in("Weekend reading list for investors", themes) == []


# ------------------------------------------------------------------ the whole step

def test_a_run_keeps_only_listed_fresh_plain_https_headlines_with_their_reasons():
    rows = [
        item("Micron results beat forecasts on AI memory demand", link("cnbc.com", "micron"), 2),
        item("<![CDATA[<b>Wall Street ends higher as chip stocks rally</b>]]>", link("cnbc.com", "wall-street"), 1),
        item("A story on a site that is not listed anywhere", "https://www.example.org/story", 1),
        item("Listed publisher but an unencrypted link", "http://www.cnbc.com/old-link", 1),
        item("Very old story about the stock market", link("cnbc.com", "old"), 100),
        item("Story with a publication time far ahead", link("cnbc.com", "future"), -5),
        item("Story with no time given at all in feed", link("cnbc.com", "notime"), with_time=False),
        item("Too short", link("cnbc.com", "short"), 1),
    ]
    block, health, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rss(*rows))})
    valid(block)
    assert block["status"] == "ok" and block["queries"] == {"asked": 1, "answered": 1}
    titles = {s["title"]: s for s in block["stories"]}
    assert set(titles) == {"Micron results beat forecasts on AI memory demand",
                           "Wall Street ends higher as chip stocks rally"}
    micron = titles["Micron results beat forecasts on AI memory demand"]
    assert set(micron) == {"id", "title", "publisher", "url", "seen_at_utc", "topics", "companies"}
    assert micron["publisher"] == "CNBC" and micron["url"] == link("cnbc.com", "micron")
    assert micron["companies"] == ["Micron"] and micron["topics"] == ["ai_chips", "companies"]
    assert micron["seen_at_utc"] == when(2).isoformat()
    assert titles["Wall Street ends higher as chip stocks rally"]["topics"] == ["ai_chips", "us_markets"]
    assert health["articles_seen"] == 8 and health["from_listed_publishers"] == 6 and health["kept"] == 2
    assert health["dropped"] == {"listed_publisher_but_link_not_plain_https": 1, "no_time_in_feed": 1,
                                 "not_a_listed_publisher": 1, "older_than_limit": 1,
                                 "time_in_the_future": 1, "unusable_headline": 1}
    assert health["top_other_sites"] == [{"site": "example.org", "headlines": 1}]
    assert "publisher_filter" not in health                 # the news index was not used
    assert health["feeds"]["results"] == [
        {"id": "cnbc_finance", "publisher": "CNBC", "status": "ok", "items": 8, "usable": 2}]
    assert health["advisories"] == ["1 headlines from listed publishers were skipped because their link "
                                    "was not a plain https link."]


def test_the_block_names_the_feeds_as_its_source_and_the_links_stay_https():
    block, _, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rss(
        item("Wall Street ends higher as chip stocks rally", link("cnbc.com", "x"))))})
    assert block["source"]["id"] == "publisher_feeds"
    assert block["source"]["name"] == "The publishers' own news feeds"
    assert block["source"]["url"].startswith("https://github.com/sumitburad/money-flow-tracker")
    assert all(s["url"].startswith("https://") for s in block["stories"])


def test_a_headline_with_no_keyword_takes_the_theme_of_its_feed_and_a_keyword_beats_the_feed_theme():
    rows = rss(item("Nifty ends higher as Sensex gains for a third day", link("cnbc.com", "nifty"), 1),
               item("Weekend reading list for patient investors", link("cnbc.com", "reading"), 2))
    block, _, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rows)})
    by_title = {s["title"]: s["topics"] for s in valid(block)["stories"]}
    assert by_title["Nifty ends higher as Sensex gains for a third day"] == ["india_markets"]
    assert by_title["Weekend reading list for patient investors"] == ["us_markets"]


def test_the_same_headline_from_two_feeds_is_kept_once_with_both_topics():
    same = "Nvidia and Micron lead a global chip rally today"
    answers = {CNBC["url"]: Reply(rss(item(same, link("cnbc.com", "a")))),
               CNBC_TECH["url"]: Reply(rss(item(same.upper(), link("cnbc.com", "b"))))}
    block, health, _, _ = run(feeds_cfg(CNBC, CNBC_TECH), answers)
    assert len(valid(block)["stories"]) == 1 and health["dropped"]["same_headline_again"] == 1
    assert sorted(block["stories"][0]["companies"]) == ["Micron", "Nvidia"]
    assert block["stories"][0]["topics"] == ["ai_chips", "companies"]


def test_a_feed_that_fails_makes_the_news_partial_and_is_named():
    answers = {CNBC["url"]: Reply(rss(item("Wall Street ends higher as chip stocks rally", link("cnbc.com", "x")))),
               ET["url"]: Reply(b"Forbidden", status=403)}
    block, health, _, _ = run(feeds_cfg(CNBC, ET), answers)
    valid(block)
    assert block["status"] == "partial" and block["queries"] == {"asked": 2, "answered": 1}
    assert health["status"] == "partial" and health["queries_skipped"] == 0
    assert health["feeds"]["asked"] == 2 and health["feeds"]["answered"] == 1
    failed = health["feeds"]["results"][1]
    assert failed == {"id": "et_markets", "publisher": "The Economic Times", "status": "failed", "items": 0,
                      "usable": 0, "error": "the feed answered HTTP 403 (it said: Forbidden)"}
    assert health["errors"] == ["The Economic Times (et_markets): the feed answered HTTP 403 (it said: Forbidden)"]


def test_when_every_feed_fails_the_block_is_honestly_empty():
    answers = {CNBC["url"]: requests.ReadTimeout("slow"), ET["url"]: Reply(b"", status=403)}
    block, health, _, _ = run(feeds_cfg(CNBC, ET), answers)
    valid(block)
    assert block["status"] == "unavailable" and block["stories"] == []
    assert block["queries"] == {"asked": 2, "answered": 0} and health["kept"] == 0
    assert health["errors"][0].startswith("CNBC (cnbc_finance): no answer within 20 seconds")


def test_many_failing_feeds_give_a_short_error_list_and_a_full_per_feed_list():
    feeds = [dict(CNBC, id="f%d" % n, url="https://www.cnbc.com/id/%d/x" % n) for n in range(8)]
    block, health, _, _ = run(feeds_cfg(*feeds, pause_seconds=0), {})
    valid(block)
    assert len(health["errors"]) == 6 and health["errors"][-1].startswith("3 more feeds did not answer")
    assert len(health["feeds"]["results"]) == 8 and {r["status"] for r in health["feeds"]["results"]} == {"failed"}


def test_feeds_on_one_website_are_asked_a_pause_apart_and_other_websites_are_not_delayed():
    answers = {u["url"]: Reply(rss(item("Sensex ends higher on bank gains today", link(u["domain"], u["id"]))))
               for u in (CNBC, ET, ET2, WSJ)}
    _, _, pauses, fake = run(feeds_cfg(CNBC, ET, ET2, WSJ), answers)
    assert pauses == [SHIPPED["feeds"]["pause_seconds"]] and len(fake.calls) == 4


def test_a_website_that_failed_twice_is_not_asked_again_but_other_websites_still_are():
    asked = []

    def fetch(url, params=None, timeout=None, headers=None, **kw):
        asked.append(url)
        if "economictimes" in url:
            raise requests.ConnectionError("blocked")
        return Reply(rss(item("Wall Street ends higher as chip stocks rally", link("cnbc.com", "x"))))

    http = RetryingHttp(attempts=1, backoff=0, sleep=lambda s: None, fetcher=fetch, jitter=False, breaker_after=2)
    block, health = build_market_news(feeds_cfg(ET, ET2, ET3, CNBC), NOW, feed_http=http, sleep=lambda s: None)
    valid(block)
    assert [r["status"] for r in health["feeds"]["results"]] == ["failed", "failed", "skipped", "ok"]
    assert len(asked) == 3                                    # the third economictimes feed was never requested
    assert block["queries"] == {"asked": 3, "answered": 1} and health["queries_skipped"] == 1
    assert block["status"] == "partial"
    assert "already failed twice" in health["feeds"]["results"][2]["error"]
    assert len(block["stories"]) == 1


def test_the_step_stops_asking_new_feeds_at_its_time_limit():
    ticks = iter(range(0, 10_000, 100))
    answers = {u["url"]: Reply(rss(item("Wall Street ends higher as chip stocks rally", link(u["domain"], u["id"]))))
               for u in (CNBC, WSJ, ET)}
    block, health, _, fake = run(feeds_cfg(CNBC, WSJ, ET, total_seconds=150), answers, clock=lambda: next(ticks))
    valid(block)
    assert len(fake.calls) == 1 and block["queries"] == {"asked": 1, "answered": 1}
    assert health["queries_skipped"] == 2 and block["status"] == "partial"
    assert [r["status"] for r in health["feeds"]["results"]] == ["ok", "skipped", "skipped"]
    assert "stopped after" in health["errors"][0] and "2 of 3 feeds were not asked" in health["errors"][0]


def test_a_feed_with_no_entries_counts_as_answered_but_is_flagged():
    block, health, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rss())})
    valid(block)
    assert block["status"] == "ok" and block["stories"] == []
    assert health["feeds"]["results"][0]["status"] == "empty"
    assert any("CNBC (cnbc_finance) answered but had no headlines" in a for a in health["advisories"])


def test_only_the_newest_entries_of_a_feed_are_read():
    rows = [item("Headline number %d about the stock market" % n, link("cnbc.com", "h%d" % n), hours_ago=n + 1)
            for n in range(6)]
    block, health, _, _ = run(feeds_cfg(CNBC, max_items_per_feed=2), {CNBC["url"]: Reply(rss(*reversed(rows)))})
    assert sorted(s["title"] for s in valid(block)["stories"]) == [
        "Headline number 0 about the stock market", "Headline number 1 about the stock market"]
    assert health["articles_seen"] == 2 and health["feeds"]["results"][0]["items"] == 6


def test_many_headlines_are_trimmed_to_the_limits_and_one_publisher_cannot_fill_the_page():
    rows = [item("Headline number %02d about the stock market" % n, link("cnbc.com", "h%d" % n), hours_ago=n % 40 + 1)
            for n in range(60)]
    wsj = [item("Wall Street update number %02d for investors" % n, link("wsj.com", "w%d" % n), hours_ago=n % 40 + 1)
           for n in range(60)]
    cfg = feeds_cfg(CNBC, WSJ, max_items_per_feed=60)
    block, _, _, _ = run(cfg, {CNBC["url"]: Reply(rss(*rows)), WSJ["url"]: Reply(rss(*wsj))})
    valid(block)
    per = {}
    for s in block["stories"]:
        per[s["publisher"]] = per.get(s["publisher"], 0) + 1
    assert max(per.values()) <= cfg["limits"]["max_per_publisher"] and len(block["stories"]) == 12


def test_company_stories_are_kept_first_and_stay_on_the_watchlist():
    rows = [item("Nvidia and AMD lead a chip rally on Friday", link("cnbc.com", "chips"), 5),
            item("Plain market story that is long enough here", link("cnbc.com", "plain"), 1)]
    block, _, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rss(*rows))})
    story = [s for s in valid(block)["stories"] if s["companies"]][0]
    assert sorted(story["companies"]) == ["AMD", "Nvidia"] and "companies" in story["topics"]


def test_text_in_a_feed_title_cannot_carry_markup_or_control_characters():
    rows = [item("&lt;script&gt;alert(1)&lt;/script&gt;Stocks rally as oil prices fall\x01\x02 again", link("cnbc.com", "z"))]
    block, _, _, _ = run(feeds_cfg(CNBC), {CNBC["url"]: Reply(rss(*rows))})
    title = valid(block)["stories"][0]["title"]
    assert "<" not in title and ">" not in title and "\x01" not in title


# ------------------------------------------------------------------ switching sources on and off

def test_with_both_sources_off_the_news_is_disabled():
    cfg = feeds_cfg(CNBC)
    cfg["feeds"]["enabled"] = False
    cfg["source"]["enabled"] = False
    block, health, _, fake = run(cfg, {})
    assert valid(block)["status"] == "disabled" and health["status"] == "disabled" and not fake.calls


def test_the_whole_feature_can_be_switched_off():
    cfg = feeds_cfg(CNBC)
    cfg["enabled"] = False
    block, health, _, fake = run(cfg, {CNBC["url"]: Reply(rss())})
    assert valid(block)["status"] == "disabled" and not fake.calls


def test_a_single_feed_can_be_switched_off():
    off = dict(WSJ, enabled=False)
    answers = {CNBC["url"]: Reply(rss(item("Wall Street ends higher as chip stocks rally", link("cnbc.com", "x")))),
               WSJ["url"]: Reply(rss(item("Wall Street ends lower as chip stocks fall", link("wsj.com", "x"))))}
    block, health, _, fake = run(feeds_cfg(CNBC, off), answers)
    assert [c["url"] for c in fake.calls] == [CNBC["url"]] and block["queries"] == {"asked": 1, "answered": 1}
    assert [r["id"] for r in health["feeds"]["results"]] == ["cnbc_finance"]


def test_no_enabled_feed_and_no_news_index_means_disabled():
    cfg = feeds_cfg(dict(CNBC, enabled=False))
    cfg["source"]["enabled"] = False
    assert run(cfg, {})[0]["status"] == "disabled"


class IndexFake:
    """The GDELT news index: one article for every question."""

    def __init__(self, article):
        self.article, self.calls = article, []

    def get(self, url, params=None, timeout=None, headers=None, **kw):
        self.calls.append(params["query"])
        reply = Reply(('{"articles": [%s]}' % self.article).encode())
        return reply


def test_the_feeds_and_the_news_index_can_both_be_used_and_their_counts_add_up():
    cfg = feeds_cfg(CNBC)
    cfg["source"]["enabled"] = True
    cfg["source"]["max_queries"] = 2
    cfg["source"]["publisher_filter"] = False
    stamp = when(2).strftime("%Y%m%dT%H%M%SZ")
    article = ('{"url": "https://www.reuters.com/markets/rates", "title": "Treasury yields climb before the Fed decision",'
               ' "seendate": "%s", "domain": "reuters.com", "language": "English"}' % stamp)
    index, pauses = IndexFake(article), []
    feed = FeedFake({CNBC["url"]: Reply(rss(item("Wall Street ends higher as chip stocks rally", link("cnbc.com", "x"))))})
    block, health = build_market_news(cfg, NOW, http=index, feed_http=feed, sleep=pauses.append)
    valid(block)
    assert block["queries"] == {"asked": 3, "answered": 3} and block["status"] == "ok"
    assert block["source"]["id"] == "publisher_feeds+gdelt_doc_2"
    assert {s["publisher"] for s in block["stories"]} == {"CNBC", "Reuters"}
    assert health["publisher_filter"] == "off" and len(index.calls) == 2
    assert health["feeds"]["asked"] == 1 and health["queries_asked"] == 3


def test_feeds_that_were_not_asked_and_index_questions_that_were_not_asked_are_added_together():
    cfg = feeds_cfg(CNBC, WSJ, total_seconds=150)
    cfg["source"].update(enabled=True, max_queries=3, publisher_filter=False, pause_seconds=1, total_seconds=330)
    ticks = iter(range(0, 100_000, 100))
    block, health = build_market_news(cfg, NOW, http=IndexFake("{}"), feed_http=FeedFake({}),
                                      sleep=lambda s: None, clock=lambda: next(ticks))
    valid(block)
    asked, answered, skipped = health["queries_asked"], health["queries_answered"], health["queries_skipped"]
    assert asked + skipped == 2 + 3                            # every planned feed and question is counted once
    assert block["queries"]["asked"] == asked and block["status"] in ("partial", "unavailable")


# ------------------------------------------------------------------ the settings as shipped

def test_the_shipped_settings_read_the_publisher_feeds_and_leave_the_news_index_off():
    assert SHIPPED["enabled"] is True and SHIPPED["feeds"]["enabled"] is True
    assert SHIPPED["source"]["enabled"] is False
    assert SHIPPED["source"]["id"] == "gdelt_doc_2"            # the index code and settings are kept


def test_the_shipped_feed_list_is_sound():
    feeds, domains = SHIPPED["feeds"], [p["domain"] for p in SHIPPED["publishers"]]
    theme_ids = [t["id"] for t in SHIPPED["themes"]]
    assert len(feeds["list"]) >= 8
    ids = [f["id"] for f in feeds["list"]]
    assert len(ids) == len(set(ids)) and all(i == i.lower() and " " not in i for i in ids)
    urls = [f["url"] for f in feeds["list"]]
    assert len(urls) == len(set(urls)) and all(u.startswith("https://") and " " not in u for u in urls)
    for f in feeds["list"]:
        assert f["domain"] in domains, f["id"]                 # every feed belongs to a listed publisher
        assert f["theme"] in theme_ids, f["id"]
    assert feeds["home_page"].startswith("https://") and feeds["name"] and feeds["id"]
    connect, read = feeds["timeout_seconds"]
    assert 0 < connect <= 15 and 0 < read <= 40
    assert 0.5 <= feeds["pause_seconds"] <= 10 and 1 <= feeds["max_items_per_feed"] <= 100
    worst_one = default_feed_http().attempts * (connect + read) + 15       # tries plus the wait between them
    assert feeds["total_seconds"] + worst_one < 240            # the feeds step ends well inside the refresh


def test_every_theme_has_keywords_and_every_company_stays_on_the_watchlist():
    keywords = [w for t in SHIPPED["themes"] for w in t["keywords"]]
    assert all(t["keywords"] and all(isinstance(w, str) and len(w) >= 2 for w in t["keywords"])
               for t in SHIPPED["themes"])
    assert len(keywords) == len(set(w.lower() for w in keywords))   # a word belongs to one theme only


def test_a_full_default_run_with_every_shipped_feed_answering_stays_inside_the_limits_and_the_contract():
    cfg = copy.deepcopy(SHIPPED)
    answers = {}
    for n, f in enumerate(cfg["feeds"]["list"]):
        rows = [item("%s headline %02d about the stock market and chips" % (f["id"], k), link(f["domain"], "%s-%d" % (f["id"], k)),
                     hours_ago=k % 30 + 1) for k in range(40)]
        answers[f["url"]] = Reply(rss(*rows))
    block, health, pauses, fake = run(cfg, answers)
    valid(block)
    limits = cfg["limits"]
    assert len(fake.calls) == len(cfg["feeds"]["list"]) and block["status"] == "ok"
    assert len(block["stories"]) <= limits["max_stories"]
    per = {}
    for s in block["stories"]:
        per[s["publisher"]] = per.get(s["publisher"], 0) + 1
    assert max(per.values()) <= limits["max_per_publisher"]
    assert sum(pauses) < 60                                    # only same-website pauses
    assert len({s["id"] for s in block["stories"]}) == len(block["stories"])
    assert all(c["headers"] == FEED_HEADERS for c in fake.calls)
