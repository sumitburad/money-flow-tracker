"""Market and company news: headlines from a free news index, shown as published.

Why this exists: the executive summary and the dashboard should be able to point at the
story behind a move (for example a chip company's results), not only at Fed and ECB
press releases.

What is kept: the headline, the publisher's name, a link and the time. No article text.
Only publishers listed in ``config/market_news.yaml`` are used and every link must point
to one of their websites over https. Nothing here is a verdict: a headline is never
claimed to have moved a market.

Nothing here can stop the daily refresh. Every failure becomes a note in the health
report, and a source that is down gives an honest empty block, never made-up headlines.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml

from backend.net import HostCircuitOpen, RetryingHttp, redact

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "market_news.yaml"
HEADERS = {"User-Agent": "money-flow-monitor/1.0 (research)"}
NOTICE = ("Headlines are shown as published, with a link to the publisher. They are not verified "
          "here, and a headline is not proof that a price moved because of it.")
LANGUAGES = {"english", "eng", "en"}
SAFE_URL = re.compile(r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
MAX_URL = 500
MIN_TITLE = 12


def load_config(path=None):
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def default_http():
    """The news index asks for one request every five seconds and answers HTTP 429 ("too many
    requests") when it is busy, which on shared servers such as GitHub's can happen at the very
    first question. So a question is tried up to three times, waiting 10 s and then 20 s (or what
    the index asks for, at most 30 s). After two questions that fail all three tries, the step stops."""
    return RetryingHttp(attempts=3, backoff=10.0, max_delay=30.0, breaker_after=2)


# ------------------------------------------------------------------ cleaning

def parse_seen(text):
    """'20261122T083000Z' -> an aware UTC time, or None."""
    try:
        return datetime.strptime(str(text), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def clean_title(text, limit):
    text = html.unescape(str(text or ""))
    text = re.sub(r"[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text if len(text) >= MIN_TITLE else ""


def publisher_for(url, publishers):
    """The publisher's name if ``url`` is a plain https link to a listed website, else None."""
    if not isinstance(url, str) or len(url) > MAX_URL or not SAFE_URL.fullmatch(url):
        return None
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or parsed.username or parsed.password or port not in (None, 443):
        return None
    host = (parsed.hostname or "").lower()
    for item in publishers:
        domain = item["domain"].lower()
        if host == domain or host.endswith("." + domain):
            return item["name"]
    return None


def companies_in(title, companies):
    """Watchlist companies whose name (or alias) appears in the headline itself."""
    found = []
    for company in companies:
        for name in [company["name"]] + list(company.get("aliases", [])):
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", title, re.I):
                found.append(company["name"])
                break
    return found


def _norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


# ------------------------------------------------------------------ the questions

def build_questions(cfg):
    """(id, name, query) for every theme, then the company names in small groups."""
    source = cfg["source"]
    suffix = (source.get("query_suffix") or "").strip()
    questions = [(t["id"], t["name"], (t["query"] + (" " + suffix if suffix else "")).strip())
                 for t in cfg["themes"]]
    size = max(1, int(cfg.get("company_query_size", 8)))
    names = []
    for company in cfg.get("companies", []):
        names.extend([company["name"]] + list(company.get("aliases", [])))
    for start in range(0, len(names), size):
        group = " OR ".join('"%s"' % n for n in names[start:start + size])
        questions.append(("companies", "Company news",
                          ("(" + group + ")" + (" " + suffix if suffix else "")).strip()))
    return questions[:int(source.get("max_queries", 10))]


def _said(response):
    """What a refusing server said, as one plain clause such as " (it said: ...)", or "".

    This tells a "too many requests" answer from a block. Markup and web addresses are removed and
    anything that looks like a secret is redacted; at most 90 characters are kept."""
    text = getattr(response, "text", None)
    if not isinstance(text, str):
        try:
            text = bytes(getattr(response, "content", b"") or b"").decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            text = ""
    text = re.sub(r"https?://\S+", " ", re.sub(r"<[^>]*>", " ", text))
    text = redact(" ".join(text.split()))[:90]
    clauses = []
    if text:
        clauses.append("it said: " + text)
    headers = getattr(response, "headers", None) or {}
    try:
        wait = float(headers.get("Retry-After"))
        clauses.append("it asked for a wait of %d seconds" % round(wait))
    except (TypeError, ValueError):
        pass
    return " (" + "; ".join(clauses) + ")" if clauses else ""


def ask(http, source, query):
    response = http.get(source["url"], params={
        "query": query, "mode": "artlist", "format": "json",
        "maxrecords": int(source["max_records"]), "timespan": source["timespan"],
        "sort": source["sort"]}, timeout=tuple(source["timeout_seconds"]), headers=HEADERS)
    if response.status_code != 200:
        raise requests.HTTPError("news index answered HTTP %s%s" % (response.status_code, _said(response)))
    raw = response.content
    if len(raw) > 3_000_000:
        raise ValueError("unexpected news index response size")
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("news index did not answer with JSON: " + redact(text[:60]))
    if not isinstance(data, dict):
        raise ValueError("unexpected news index shape")
    articles = data.get("articles")
    if articles is None:
        return []                       # no matches
    if not isinstance(articles, list):
        raise ValueError("unexpected news index shape")
    return articles


def explain_error(exc, source, http=None):
    """One plain sentence for a failed question: no web addresses and no library jargon."""
    connect, read = (list(source.get("timeout_seconds") or [10, 60]) + [60, 60])[:2]
    tries = getattr(http, "attempts", 1)
    twice = " (%d tries)" % tries if isinstance(tries, int) and tries > 1 else ""
    if isinstance(exc, requests.ReadTimeout):
        return "no answer from the news index within %d seconds%s" % (read, twice)
    if isinstance(exc, requests.ConnectTimeout):
        return "could not reach the news index within %d seconds%s" % (connect, twice)
    if isinstance(exc, requests.ConnectionError):
        return "could not connect to the news index" + twice
    if isinstance(exc, (requests.HTTPError, ValueError)):
        return redact(str(exc))[:200]            # our own plain sentences, e.g. "news index answered HTTP 429"
    return type(exc).__name__


# ------------------------------------------------------------------ the build

def _select(stories, limits):
    ordered = sorted(stories.values(), key=lambda s: s["seen_at_utc"], reverse=True)
    per_publisher, chosen = {}, []

    def take(story):
        if per_publisher.get(story["publisher"], 0) >= limits["max_per_publisher"]:
            return
        per_publisher[story["publisher"]] = per_publisher.get(story["publisher"], 0) + 1
        chosen.append(story)

    for story in ordered:
        if story["companies"] and len(chosen) < limits["max_company_stories"]:
            take(story)
    for story in ordered:
        if len(chosen) >= limits["max_stories"]:
            break
        if story not in chosen:
            take(story)
    chosen.sort(key=lambda s: s["seen_at_utc"], reverse=True)
    return chosen[:limits["max_stories"]]


def _block(cfg, status, now, asked, answered, stories):
    return {"status": status, "as_of_utc": now.isoformat(),
            "source": {"id": cfg["source"]["id"], "name": cfg["source"]["name"],
                       "url": cfg["source"]["home_page"]},
            "queries": {"asked": asked, "answered": answered},
            "themes": [{"id": t["id"], "name": t["name"]} for t in cfg["themes"]] +
                      [{"id": "companies", "name": "Company news"}],
            "watchlist": [c["name"] for c in cfg.get("companies", [])],
            "stories": stories, "notice": NOTICE}


def build_market_news(cfg, now, *, http=None, sleep=time.sleep, clock=time.monotonic):
    """Returns (block for the feed, health notes). Never raises.

    The whole step stops asking new questions after ``source.total_seconds`` so a slow news index
    can never hold the refresh up. ``health["seconds"]`` and ``health["slowest_answer_seconds"]``
    show how long it really took, so the waiting times can be tuned from facts."""
    health = {"status": "ok", "queries_asked": 0, "queries_answered": 0, "queries_skipped": 0,
              "articles_seen": 0, "from_listed_publishers": 0, "kept": 0, "company_stories": 0,
              "seconds": 0.0, "slowest_answer_seconds": 0.0, "errors": [], "advisories": []}
    started = clock()
    try:
        if not cfg.get("enabled", True):
            health["status"] = "disabled"
            return _block(cfg, "disabled", now, 0, 0, []), health
        http = http or default_http()
        source, limits = cfg["source"], cfg["limits"]
        oldest = now - timedelta(hours=float(limits["max_age_hours"]))
        newest = now + timedelta(hours=1)
        found = {}
        questions = build_questions(cfg)
        budget = float(source.get("total_seconds", 300))
        for number, (theme_id, _name, query) in enumerate(questions):
            if number:
                if clock() - started + float(source["pause_seconds"]) >= budget:
                    health["queries_skipped"] = len(questions) - number
                    health["errors"].append(
                        "The news step stopped after %d seconds to keep the refresh on time; "
                        "%d of %d questions were not asked." % (round(clock() - started),
                                                                health["queries_skipped"], len(questions)))
                    break
                sleep(float(source["pause_seconds"]))
            health["queries_asked"] += 1
            asked_at = clock()
            try:
                articles = ask(http, source, query)
            except HostCircuitOpen:
                health["errors"].append("The news index failed twice, so the remaining questions were skipped.")
                break
            except Exception as exc:
                health["errors"].append(explain_error(exc, source, http))
                continue
            health["slowest_answer_seconds"] = max(health["slowest_answer_seconds"],
                                                   round(clock() - asked_at, 1))
            health["queries_answered"] += 1
            for article in articles:
                if not isinstance(article, dict):
                    continue
                health["articles_seen"] += 1
                language = str(article.get("language") or "").strip().lower()
                if language and language not in LANGUAGES:
                    continue
                url = article.get("url")
                publisher = publisher_for(url, cfg["publishers"])
                if not publisher:
                    continue
                health["from_listed_publishers"] += 1
                title = clean_title(article.get("title"), int(limits["max_title_chars"]))
                seen = parse_seen(article.get("seendate"))
                if not title or seen is None or not oldest <= seen <= newest:
                    continue
                companies = companies_in(title, cfg.get("companies", []))
                if theme_id == "companies" and not companies:
                    continue
                key = _norm(title)
                if key in found:
                    if theme_id not in found[key]["topics"]:
                        found[key]["topics"].append(theme_id)
                    continue
                found[key] = {
                    "id": hashlib.sha256((title.lower() + "|" + url).encode()).hexdigest()[:16],
                    "title": title, "publisher": publisher, "url": url,
                    "seen_at_utc": seen.isoformat(), "topics": [theme_id], "companies": companies}
        stories = _select(found, limits)
        for story in stories:
            story["topics"] = sorted(story["topics"])
        asked, answered = health["queries_asked"], health["queries_answered"]
        status = "unavailable" if answered == 0 else (
            "ok" if answered == asked and not health["queries_skipped"] else "partial")
        health["seconds"] = round(clock() - started, 1)
        health.update(status=status, kept=len(stories),
                      company_stories=sum(1 for s in stories if s["companies"]))
        if answered and health["articles_seen"] and not health["from_listed_publishers"]:
            health["advisories"].append(
                "The news index answered, but no headline came from a listed publisher. "
                "Check the publisher list in config/market_news.yaml.")
        if answered and not health["articles_seen"]:
            health["advisories"].append("The news index answered but returned no headlines.")
        return _block(cfg, status, now, asked, answered, stories if answered else []), health
    except Exception as exc:                       # never stop the daily refresh
        health["status"] = "unavailable"
        health["seconds"] = round(clock() - started, 1)
        health["errors"].append(type(exc).__name__ + ": " + redact(str(exc))[:90])
        try:
            return _block(cfg, "unavailable", now, health["queries_asked"],
                          health["queries_answered"], []), health
        except Exception:
            return None, health


# ------------------------------------------------------------------ for the summary

def digest_market_news(block, limit=10):
    """A few headlines for the AI summary: company stories first, one publisher at a time."""
    if not block or block.get("status") not in ("ok", "partial"):
        return []
    queues = {}
    for story in sorted(block["stories"], key=lambda s: (not s["companies"], -_stamp(s))):
        queues.setdefault(story["publisher"], []).append(story)
    chosen = []
    while len(chosen) < limit and any(queues.values()):
        for queue in queues.values():
            if queue and len(chosen) < limit:
                chosen.append(queue.pop(0))
    return [{"headline": s["title"][:140], "publisher": s["publisher"],
             "companies": s["companies"], "topics": s["topics"]} for s in chosen]


def _stamp(story):
    try:
        return datetime.fromisoformat(story["seen_at_utc"]).timestamp()
    except ValueError:
        return 0.0
