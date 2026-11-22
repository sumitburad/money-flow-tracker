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
from collections import Counter
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

def publisher_group(cfg):
    """The "only these websites" part of a question, e.g. (domain:reuters.com OR domain:cnbc.com).

    GDELT's ``domain:`` matches any site whose name contains the text, so look-alike sites can still
    come back; every link is checked again against the listed publishers (``publisher_for``)."""
    domains = [str(p.get("domain", "")).strip().lower() for p in cfg.get("publishers", [])]
    domains = [d for d in domains if d]
    return "(" + " OR ".join("domain:" + d for d in domains) + ")" if domains else ""


def build_questions(cfg, filtered=None):
    """(id, name, query) for every theme, then the company names in small groups.

    With ``filtered`` true (the default is ``source.publisher_filter`` in the settings) each question
    also asks only for the listed publishers. Without it the news index returns its 100 most relevant
    headlines from anywhere, and in the live run of 22 November 2026 only 1 of 200 came from a
    listed publisher."""
    source = cfg["source"]
    if filtered is None:
        filtered = bool(source.get("publisher_filter", False))
    extra = " ".join(part for part in ((source.get("query_suffix") or "").strip(),
                                       publisher_group(cfg) if filtered else "") if part)
    questions = [(t["id"], t["name"], (t["query"] + (" " + extra if extra else "")).strip())
                 for t in cfg["themes"]]
    size = max(1, int(cfg.get("company_query_size", 8)))
    names = []
    for company in cfg.get("companies", []):
        names.extend([company["name"]] + list(company.get("aliases", [])))
    for start in range(0, len(names), size):
        group = " OR ".join('"%s"' % n for n in names[start:start + size])
        questions.append(("companies", "Company news",
                          ("(" + group + ")" + (" " + extra if extra else "")).strip()))
    return questions[:int(source.get("max_queries", 10))]


def _plain(text, limit=90):
    """Text from a server made safe to show: no markup, no web addresses, no secrets, short."""
    text = re.sub(r"https?://\S+", " ", re.sub(r"<[^>]*>", " ", str(text or "")))
    return redact(" ".join(text.split()))[:limit]


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
    text = _plain(text)
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
        raise ValueError("news index did not answer with JSON: " + _plain(text, 60))
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


def _listed_link_refused(url, publishers):
    """True when a link points at a listed website but is not a plain https link (so it was skipped)."""
    try:
        host = (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in (str(p["domain"]).lower() for p in publishers))


def _site_of(article):
    """The website an article came from (letters, digits, dots and hyphens only), or ""."""
    pattern = r"[a-z0-9][a-z0-9.\-]{1,60}"
    name = str(article.get("domain") or "").strip().lower()
    if not re.fullmatch(pattern, name):
        try:
            name = (urlparse(str(article.get("url") or "")).hostname or "").lower()
        except ValueError:
            name = ""
    if name.startswith("www."):                     # www.yahoo.com and yahoo.com are one site
        name = name[4:]
    return name if re.fullmatch(pattern, name) else ""


def _filter_problem(number, articles, failure):
    """Why the publisher filter looks refused, or "".

    Only two things count: an answer that is not JSON (the index rejected the question) and an empty
    answer to the very first, broad question. A busy or slow index says nothing about the filter."""
    if failure is not None:
        if isinstance(failure, ValueError) and str(failure).startswith("news index did not answer with JSON"):
            return redact(str(failure))[:120]
        return ""
    if number == 0 and not articles:
        return "it answered the first, broad question with no headlines at all"
    return ""


def build_market_news(cfg, now, *, http=None, sleep=time.sleep, clock=time.monotonic):
    """Returns (block for the feed, health notes). Never raises.

    The whole step stops asking new questions after ``source.total_seconds`` so a slow news index
    can never hold the refresh up. ``health["seconds"]`` and ``health["slowest_answer_seconds"]``
    show how long it really took, so the waiting times can be tuned from facts.

    Each question asks only for the listed publishers when ``source.publisher_filter`` is on. If the
    index rejects that (not JSON), or answers the first question with nothing at all, the filter is
    turned off for the rest of the run, the question is asked again without it, and a note says so.
    ``health["dropped"]`` and ``health["top_other_sites"]`` say why headlines were not kept."""
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
        plain = build_questions(cfg, filtered=False)
        narrowed = build_questions(cfg, filtered=True)
        use_filter = bool(source.get("publisher_filter", False)) and narrowed != plain
        health["publisher_filter"] = "on" if use_filter else "off"
        questions = plain                       # same ids and order with or without the filter
        budget = float(source.get("total_seconds", 300))
        dropped, other_sites = Counter(), Counter()
        for number, (theme_id, _name, _query) in enumerate(questions):
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
            articles, failure, asked_at = [], None, clock()
            for again in (False, True):
                asked_at = clock()
                try:
                    articles, failure = ask(http, source, (narrowed if use_filter else plain)[number][2]), None
                except HostCircuitOpen as exc:
                    articles, failure = [], exc
                    break
                except Exception as exc:
                    articles, failure = [], exc
                problem = _filter_problem(number, articles, failure) if use_filter and not again else ""
                if not problem:
                    break
                use_filter = False
                health["publisher_filter"] = "switched off during this refresh"
                health["advisories"].append(
                    "The news index did not take the publisher filter (%s), so the filter was turned off "
                    "for the rest of this refresh and the question was asked again without it." % problem)
                sleep(float(source["pause_seconds"]))        # the index asks for a pause between requests
            if isinstance(failure, HostCircuitOpen):
                health["queries_skipped"] = len(questions) - number - 1        # asked + skipped = planned
                health["errors"].append("The news index failed twice, so the remaining questions were skipped.")
                break
            if failure is not None:
                health["errors"].append(explain_error(failure, source, http))
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
                    dropped["not_english"] += 1
                    continue
                url = article.get("url")
                publisher = publisher_for(url, cfg["publishers"])
                if not publisher:
                    if _listed_link_refused(url, cfg["publishers"]):
                        dropped["listed_publisher_but_link_not_plain_https"] += 1
                    else:
                        dropped["not_a_listed_publisher"] += 1
                        site = _site_of(article)
                        if site:
                            other_sites[site] += 1
                    continue
                health["from_listed_publishers"] += 1
                title = clean_title(article.get("title"), int(limits["max_title_chars"]))
                seen = parse_seen(article.get("seendate"))
                if not title or seen is None or not oldest <= seen <= newest:
                    dropped["unusable_headline_or_time"] += 1
                    continue
                companies = companies_in(title, cfg.get("companies", []))
                if theme_id == "companies" and not companies:
                    dropped["company_not_named_in_headline"] += 1
                    continue
                key = _norm(title)
                if key in found:
                    dropped["same_headline_again"] += 1
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
        health["dropped"] = {k: v for k, v in sorted(dropped.items()) if v}
        health["top_other_sites"] = [{"site": site, "headlines": count} for site, count in
                                     sorted(other_sites.items(), key=lambda kv: (-kv[1], kv[0]))[:5]]
        seen_n, listed_n = health["articles_seen"], health["from_listed_publishers"]
        if answered and seen_n and not listed_n:
            health["advisories"].append(
                "The news index answered, but no headline came from a listed publisher. "
                "Check the publisher list in config/market_news.yaml.")
        elif answered and seen_n >= 20 and listed_n * 10 < seen_n:
            others = ", ".join("%s (%d)" % (x["site"], x["headlines"]) for x in health["top_other_sites"][:3])
            health["advisories"].append(
                "Only %d of %d headlines came from the listed publishers%s." %
                (listed_n, seen_n, "; most of the others came from " + others if others else ""))
        if dropped["listed_publisher_but_link_not_plain_https"]:
            health["advisories"].append(
                "%d headlines from listed publishers were skipped because their link was not a plain https link."
                % dropped["listed_publisher_but_link_not_plain_https"])
        if answered and not seen_n:
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
