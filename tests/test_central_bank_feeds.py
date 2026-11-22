"""The Fed and ECB headline feeds: a failed feed says which HTTP status it got."""
import requests

from backend import run_daily as rd

RSS = (b"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>t</title>"
       b"<item><title>Federal Reserve issues FOMC statement</title>"
       b"<link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261107a.htm</link></item>"
       b"</channel></rss>")


ECB_RSS = RSS.replace(b"Federal Reserve issues FOMC statement", b"ECB decides on interest rates").replace(
    b"https://www.federalreserve.gov/newsevents/pressreleases/monetary20261107a.htm",
    b"https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp261030.en.html")


class Reply:
    def __init__(self, status=200, content=RSS):
        self.status_code, self.content = status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP %s" % self.status_code, response=self)


def run(monkeypatch, tmp_path, answer):
    monkeypatch.setattr(rd, "ROOT", tmp_path)
    monkeypatch.setattr(rd.HTTP, "get", answer)
    return rd.collect_news("2026-11-22")


def test_a_refused_feed_names_the_http_status(monkeypatch, tmp_path):
    entries, errors = run(monkeypatch, tmp_path, lambda url, **kw: Reply(403, b"Access denied"))
    assert entries == []
    assert errors == [{"source": "Federal Reserve", "error": "HTTPError (HTTP 403)"},
                      {"source": "European Central Bank", "error": "HTTPError (HTTP 403)"}]


def test_one_bad_feed_does_not_stop_the_other(monkeypatch, tmp_path):
    def answer(url, **kw):
        return Reply(503, b"") if "federalreserve.gov" in url else Reply(content=ECB_RSS)
    entries, errors = run(monkeypatch, tmp_path, answer)
    assert errors == [{"source": "Federal Reserve", "error": "HTTPError (HTTP 503)"}]
    assert [e["publisher"] for e in entries] == ["European Central Bank"]


def test_a_failure_with_no_http_status_keeps_the_plain_error_name(monkeypatch, tmp_path):
    def answer(url, **kw):
        raise requests.ConnectionError("down")
    entries, errors = run(monkeypatch, tmp_path, answer)
    assert entries == [] and [e["error"] for e in errors] == ["ConnectionError", "ConnectionError"]


def test_an_odd_status_value_is_not_printed(monkeypatch, tmp_path):
    class Odd(requests.HTTPError):
        def __init__(self):
            super().__init__("odd")
            self.response = type("R", (), {"status_code": "<b>x</b>"})()

    def answer(url, **kw):
        raise Odd()
    _, errors = run(monkeypatch, tmp_path, answer)
    assert [e["error"] for e in errors] == ["Odd", "Odd"]


def test_good_feeds_are_collected_as_before(monkeypatch, tmp_path):
    entries, errors = run(monkeypatch, tmp_path,
                          lambda url, **kw: Reply(content=RSS if "federalreserve.gov" in url else ECB_RSS))
    assert errors == [] and [e["publisher"] for e in entries] == ["Federal Reserve", "European Central Bank"]
    assert all(e["url"].startswith("https://") and e["direction"] == "unclear" for e in entries)


def test_the_same_headline_from_both_feeds_is_kept_once(monkeypatch, tmp_path):
    entries, errors = run(monkeypatch, tmp_path, lambda url, **kw: Reply())
    assert errors == [] and len(entries) == 1
