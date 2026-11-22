"""Public, read-only global money-flow RESEARCH monitor.

Important: Yahoo Finance is an unofficial research input inherited from the
existing tracker. Its raw quotes/price histories are not redistributed. The
public feed contains categorical evidence only, not market price tables.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import logging
import math
import os
import re
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import quote

import feedparser
import numpy as np
import pandas as pd
import requests
import yaml

from backend.events_calendar import (brief_lines, build_calendar,
                                     load_config as load_events_config)
from backend.flow_windows import (build_rotation, completed_closes, compute_flow_windows,
                                  not_available as flow_not_available)
from backend.market_news import (build_market_news, digest_market_news,
                                 load_config as load_news_config)
from backend.net import HTTP, scrub_secrets
from backend.regime import (build_regime, health_of as regime_health,
                            load_config as load_regime_config, regime_sentence)

ROOT = Path(__file__).resolve().parent.parent
FAMILIES = ("money_flow", "price_trend", "breadth", "positioning",
            "macro_liquidity", "news")
VALID_STATES = {"supportive", "neutral", "opposing", "not_available"}
IST = timezone(timedelta(hours=5, minutes=30))
LOG = logging.getLogger("moneyflow")
# Error sources that mean "a primary official data source failed this run".
# (Stale-but-fetched series, "macro_stale:...", are deliberately not included.)
OFFICIAL_SOURCE_PROBLEM = re.compile(r"^(fred:|fred_api|macro:|us_treasury|cftc_tff)")


def now_utc():
    return datetime.now(timezone.utc)


def save_json(path, obj):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    # Safety net: a configured API key or token can never be written to a file.
    path.write_text(scrub_secrets(text), encoding="utf-8")


def read_yaml(path):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def na(reason="Independent evidence unavailable"):
    return {"state": "not_available", "evidence": reason, "source": None}


def state_record(state, evidence, source, observed_at, method=None):
    assert state in VALID_STATES
    result = {"state": state, "evidence": evidence,
              "source": source, "observed_at": observed_at}
    if method:
        result["method"] = method
    return result


def trading_days_old(observation_date, today):
    """Weekday proxy; exchange-specific holidays may extend the safe window."""
    return max(0, int(np.busday_count(observation_date, today)))


def source_fresh(observation_date, today, allowed_weekdays=2):
    try:
        d = date.fromisoformat(str(observation_date)[:10])
        return d <= today and trading_days_old(d, today) <= allowed_weekdays
    except (TypeError, ValueError):
        return False


def calculate_trend(close, as_of=None):
    """Deterministic, categorical price check; not a prediction."""
    close = pd.Series(close, dtype=float).dropna()
    if as_of is not None:
        close = close.iloc[:as_of]
    if len(close) < 201:
        return "not_available"
    last = float(close.iloc[-1])
    ma50 = float(close.tail(50).mean())
    ma200 = float(close.tail(200).mean())
    past20 = float(close.iloc[-21])
    if last > ma50 and last > ma200 and last > past20:
        return "supportive"
    if last < ma50 and last < ma200 and last < past20:
        return "opposing"
    return "neutral"


def calculate_volume_flow(close, volume, as_of=None):
    """Directional volume PARTICIPATION only; never an institutional flow."""
    c = pd.Series(close, dtype=float)
    v = pd.Series(volume, dtype=float)
    if as_of is not None:
        c, v = c.iloc[:as_of], v.iloc[:as_of]
    if len(c) < 22 or len(v) != len(c):
        return "not_available"
    changes = c.diff().tail(20)
    vol = v.tail(20)
    if vol.isna().any() or (vol <= 0).any():
        return "not_available"
    up = float(vol[changes > 0].sum())
    down = float(vol[changes < 0].sum())
    if up <= 0 or down <= 0:
        return "neutral"
    ratio = up / down
    if ratio >= 1.2:
        return "supportive"
    if ratio <= 0.8:
        return "opposing"
    return "neutral"


def assign_label(families):
    """Exact label policy; missing data never implies a directional label."""
    flow = families["money_flow"]["state"]
    trend = families["price_trend"]["state"]
    available = [x["state"] for x in families.values()
                 if x["state"] in ("supportive", "opposing")]
    positive = available.count("supportive")
    negative = available.count("opposing")
    other = [families[k]["state"] for k in FAMILIES
             if k not in ("money_flow", "price_trend")]
    if flow == trend == "supportive" and "supportive" in other and negative == 0:
        label = "Bullish"
        count = positive
    elif flow == trend == "opposing" and "opposing" in other and positive == 0:
        label = "Bearish"
        count = negative
    else:
        label = "Neutral/Mixed"
        count = max(positive, negative)
    agreement = "Strong" if count >= 5 else "Moderate" if count >= 3 else "Weak"
    return label, agreement


def momentum_tag(close, volume):
    """Compare categorical evidence at two prior horizons, no composite score."""
    c = pd.Series(close, dtype=float)
    v = pd.Series(volume, dtype=float)
    if len(c) < 225:
        return "Steady"
    states = []
    for offset in (0, 5, 20):
        end = None if offset == 0 else -offset
        x = calculate_trend(c, end)
        y = calculate_volume_flow(c, v, end)
        states.append((x, y))
    order = {"opposing": -1, "neutral": 0, "supportive": 1}
    if any(s not in order for pair in states for s in pair):
        return "Steady"
    if all(order[states[0][i]] >= order[states[j][i]]
           for j in (1, 2) for i in (0, 1)) and any(
           order[states[0][i]] > order[states[j][i]]
           for j in (1, 2) for i in (0, 1)):
        return "Strengthening"
    if all(order[states[0][i]] <= order[states[j][i]]
           for j in (1, 2) for i in (0, 1)) and any(
           order[states[0][i]] < order[states[j][i]]
           for j in (1, 2) for i in (0, 1)):
        return "Weakening"
    return "Steady"


def fetch_yfinance(asset):
    """Uses only transient historical values; NEVER exports vendor quotes."""
    import yfinance as yf
    symbol = asset["symbol"]
    frame = yf.download(symbol, period="2y", interval="1d",
                        auto_adjust=False, progress=False, threads=False,
                        timeout=15)
    if frame is None or frame.empty:
        raise ValueError("no historical observations")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    if "Close" not in frame:
        raise ValueError("Close column missing")
    frame = frame.dropna(subset=["Close"]).sort_index()
    if len(frame) < 2:
        raise ValueError("fewer than two observations")
    observation_date = frame.index[-1].date().isoformat()
    source = "https://finance.yahoo.com/quote/" + quote(symbol, safe="") + "/history/"
    return frame, observation_date, source


FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations"
FETCH_HEADERS = {"User-Agent": "money-flow-monitor/1.0 (research)"}
FETCH_TIMEOUT = (6, 20)  # seconds to connect, seconds to read


def _archive_raw(run_day, name, raw):
    raw_path = ROOT / "data" / "raw" / run_day / name
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wb") as handle:
        handle.write(raw)
    return raw_path


def fetch_fred(series_id, run_day):
    """Official FRED data. Uses the free API key when FRED_API_KEY is set, else the
    public CSV export. If the key path fails for any reason, the CSV path is tried."""
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        try:
            return fetch_fred_api(series_id, run_day, key)
        except Exception as exc:  # key rejected, host down, odd payload: use the CSV
            LOG.warning("FRED API unusable for %s (%s); trying public CSV",
                        series_id, type(exc).__name__)
    return fetch_fred_csv(series_id, run_day)


def fetch_fred_api(series_id, run_day, api_key):
    """FRED JSON API (free key). Never puts the key in an error message or a file."""
    resp = HTTP.get(FRED_API_URL, params={
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "sort_order": "desc", "limit": 60, "observation_end": run_day},
        timeout=FETCH_TIMEOUT, headers=FETCH_HEADERS)
    if resp.status_code != 200:
        raise requests.HTTPError("FRED API answered HTTP %s" % resp.status_code)
    raw = resp.content
    if len(raw) > 2_000_000 or len(raw) < 20:
        raise ValueError("unexpected FRED API payload size")
    rows = json.loads(raw).get("observations")
    if not isinstance(rows, list):
        raise ValueError("unexpected FRED API payload shape")
    values = []
    for row in rows:
        try:
            observed = date.fromisoformat(str(row["date"])[:10])
            number = float(row["value"])  # FRED writes "." for a missing value
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append({"observation_date": observed.isoformat(), "value": number})
    values = sorted(values, key=lambda r: r["observation_date"])[-20:]
    if not values:
        raise ValueError("no numeric FRED API observations")
    raw_path = _archive_raw(run_day, series_id + ".api.json.gz", raw)
    return {"id": series_id, "latest": values[-1], "recent": values,
            "fetched_at_utc": now_utc().isoformat(),
            "source": "https://fred.stlouisfed.org/series/" + series_id,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_file": str(raw_path.relative_to(ROOT)),
            "fetch_path": "fred_api"}


def fetch_fred_csv(series_id, run_day):
    """Official free CSV export. Preserve exact response bytes before parsing."""
    resp = HTTP.get(FRED_CSV_URL, params={"id": series_id},
                    timeout=FETCH_TIMEOUT, headers=FETCH_HEADERS)
    resp.raise_for_status()
    raw = resp.content
    if len(raw) > 4_000_000 or len(raw) < 12:
        raise ValueError("unexpected FRED payload size")
    raw_path = _archive_raw(run_day, series_id + ".csv.gz", raw)
    table = pd.read_csv(io.BytesIO(raw))
    date_col = "observation_date" if "observation_date" in table else "DATE"
    if date_col not in table or series_id not in table:
        raise ValueError("unexpected FRED headers")
    table[series_id] = pd.to_numeric(table[series_id], errors="coerce")
    table = table.dropna(subset=[series_id])
    if table.empty:
        raise ValueError("no numeric FRED observations")
    table[date_col] = pd.to_datetime(table[date_col], errors="coerce")
    table = table.dropna(subset=[date_col]).sort_values(date_col)
    values = [{"observation_date": row[date_col].date().isoformat(),
               "value": float(row[series_id])}
              for _, row in table.tail(20).iterrows()]
    return {"id": series_id, "latest": values[-1],
            "recent": values, "fetched_at_utc": now_utc().isoformat(),
            "source": "https://fred.stlouisfed.org/series/" + series_id,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "raw_file": str(raw_path.relative_to(ROOT)),
            "fetch_path": "fred_csv"}


# Series that the source publishes in a batch, so being days or weeks behind is normal and
# not a failure: how many calendar days old a value may be and still count as current. Each
# limit is the longest normal gap between releases plus a few days of slack for holidays.
CALENDAR_DAY_LIMITS = {
    "DEXINUS": 12,            # the Fed's H.10 table comes out weekly (Mondays) for the week before
    "M2SL": 90,               # monthly, dated the 1st; the next value comes out in the 4th week
    "JPNASSETS": 80,          # Bank of Japan total assets, monthly
    "BOJ_TOTAL_ASSETS": 80,   # the same series under the dashboard's own name
}


def annotate_macro_freshness(series_id, record, today):
    """Mark source age according to the observed series' actual reporting frequency.

    A mirrored but old observation is still usable for history, NOT a live
    macro confirmation. The age is measured from observation day, never fetch day.
    """
    observation = record.get("latest", {}).get("observation_date")
    frequency = record.get("frequency")
    monthly = frequency == "monthly" or series_id in ("M2SL", "JPNASSETS")
    weekly = frequency == "weekly" or series_id in (
        "WALCL", "WTREGEN", "ECBASSETSW", "ECB_ILM_TOTAL_ASSETS")
    try:
        observed_day = date.fromisoformat(str(observation)[:10])
    except (TypeError, ValueError):
        observed_day = None
    if series_id in CALENDAR_DAY_LIMITS or monthly:
        limit = CALENDAR_DAY_LIMITS.get(series_id, 45)
        allowed = "%d calendar days" % limit
        current = observed_day is not None and (today - observed_day).days <= limit and observed_day <= today
    else:
        days = 10 if weekly else 2
        allowed = str(days) + " weekday sessions (exchange holidays require review)"
        current = source_fresh(observation, today, days)
    return {**record, "freshness": "current" if current else "stale",
            "last_good_date": observation,
            "allowed_age": allowed}


def fetch_boj_total_assets(run_day):
    """Bank of Japan total assets (monthly), from FRED itself.

    FRED (free key, then its public CSV) comes first. The DBnomics copy of the same series is only
    the fallback, because it was the one that failed from GitHub's computers (HTTP error); it is
    clearly marked as a mirror when it is used."""
    try:
        record = fetch_fred("JPNASSETS", run_day)
    except Exception:
        from backend.advanced_sources import fetch_fred_mirror
        record = fetch_fred_mirror("JPNASSETS", ROOT, run_day)
    return {**record, "id": "BOJ_TOTAL_ASSETS", "source_series_id": "JPNASSETS",
            "frequency": "monthly", "unit": "hundred_million_yen",
            "description": "Bank of Japan total assets (monthly, via FRED)"}


def macro_family(asset, macro, today):
    if asset["asset_type"] not in ("equity", "crypto", "bond"):
        return na("Macro effect varies by asset; no verified mapping")
    sheet = macro.get("WALCL")
    if not sheet or sheet.get("freshness") != "current" or len(sheet.get("recent", [])) < 5:
        return na("Fed balance sheet series unavailable")
    series = sheet["recent"]
    day = sheet["latest"]["observation_date"]
    if not source_fresh(day, today, 10):
        return na("Fed balance sheet observation stale; latest " + day)
    a, b = series[-1]["value"], series[-5]["value"]
    if a > b:
        state = "supportive" if asset["asset_type"] in ("equity", "crypto") else "neutral"
        reason = "Fed assets expanded over four observations; contextual hypothesis, not proven asset flow"
    elif a < b:
        state = "opposing" if asset["asset_type"] in ("equity", "crypto") else "neutral"
        reason = "Fed assets contracted over four observations; contextual hypothesis, not proven asset flow"
    else:
        state, reason = "neutral", "Fed assets unchanged over four observations"
    return state_record(state, reason, sheet["source"], day, "official_macro_context")


def assess(asset, today, macro, positioning=None, breadth=None, flow_cfg=None, now=None,
           closes_sink=None):
    families = {name: na() for name in FAMILIES}
    symbol = asset["symbol"]
    result = {"id": asset["id"], "item": asset["name"], "group": asset["group"],
              "region": asset["region"], "currency": asset["currency"],
              "symbol": symbol, "asset_type": asset["asset_type"],
              "proxy_is_not_direct_flow": True}
    try:
        bars, observation_date, source = fetch_yfinance(asset)
        result["observation_date"] = observation_date
        result["price_source"] = source
        if not source_fresh(observation_date, today):
            families["price_trend"] = na("Price proxy stale; last session " + observation_date)
            families["money_flow"] = na("Price/volume proxy stale; last session " + observation_date)
            tag = "Steady"
            result["freshness"] = "stale"
            result["flow_windows"] = flow_not_available(
                "Price history stale; last session " + observation_date)
        else:
            state = calculate_trend(bars["Close"])
            flow = calculate_volume_flow(bars["Close"],
                                         bars["Volume"] if "Volume" in bars else [])
            if state == "not_available":
                families["price_trend"] = na("Insufficient 200-session price history")
            else:
                families["price_trend"] = state_record(
                    state, "Close and 50/200-session trend confirmation",
                    source, observation_date, "price_trend")
            if flow == "not_available":
                families["money_flow"] = na("Trading volume insufficient; no measured fund flow")
            else:
                families["money_flow"] = state_record(
                    flow, "Up-session versus down-session volume over 20 observations; NOT net institutional flow",
                    source, observation_date, "volume_participation_proxy")
            tag = momentum_tag(bars["Close"],
                               bars["Volume"] if "Volume" in bars else [])
            result["freshness"] = "current"
            if closes_sink is not None and flow_cfg is not None:
                # The risk-on / risk-off banner reads closes already fetched for this item:
                # no extra download, and nothing from here is published as a number.
                try:
                    closes = completed_closes(bars, asset, now or now_utc(), flow_cfg)
                    if closes is not None:
                        closes_sink[asset["id"]] = closes
                except Exception:
                    pass
            if flow_cfg is not None:
                # Day / week / month "price up on rising volume" check. Categories only;
                # a failure here must never stop the rest of the item from being published.
                try:
                    result["flow_windows"] = compute_flow_windows(
                        bars, asset, now or now_utc(), flow_cfg)
                except Exception as exc:
                    result["flow_windows"] = flow_not_available(
                        "Flow windows could not be calculated (" + type(exc).__name__ + ")")
        result["volume_observed"] = families["money_flow"]["state"] != "not_available"
    except Exception as exc:
        tag = "Steady"
        result["freshness"] = "unavailable"
        result["observation_date"] = None
        result["source_error"] = type(exc).__name__ + ": " + str(exc)[:140]
        result["volume_observed"] = False
        result["flow_windows"] = flow_not_available("Price history unavailable this run")
    # When this item's own market evidence was gathered (observation dates stay
    # separate). Lets a downstream reader prove it only used what was known by then.
    result["collected_at_utc"] = now_utc().isoformat()
    families["macro_liquidity"] = macro_family(asset, macro, today)
    families["breadth"] = na("No independently sourced constituent breadth")
    families["positioning"] = na("No verified CFTC/positioning series mapped")
    families["news"] = na("Headline impact not confirmed by next-session prices")
    if breadth and breadth.get("observation_date") and source_fresh(
            breadth["observation_date"], today):
        families["breadth"] = state_record(
            breadth["state"], breadth["evidence"], breadth["source"],
            breadth["observation_date"], breadth["method"])
    if positioning and positioning.get("observation_date") and source_fresh(
            positioning["observation_date"], today, 10):
        families["positioning"] = state_record(
            positioning["state"], positioning["evidence"], positioning["source"],
            positioning["observation_date"], "cftc_asset_manager_futures_only_weekly")
    elif positioning:
        families["positioning"] = na("CFTC positioning report stale; last " +
                                    str(positioning.get("observation_date")))
    label, agreement = assign_label(families)
    result.update(label=label, tag=tag, agreement=agreement, families=families)
    result["reason"] = ("Data: " + families["money_flow"]["evidence"] + "; " +
                        families["price_trend"]["evidence"] +
                        ". Reading: " + label + " under documented rules.")
    return result


def collect_news(run_day):
    urls = [
        ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
        ("European Central Bank", "https://www.ecb.europa.eu/rss/press.html"),
    ]
    seen, entries, errors = set(), [], []
    for publisher, url in urls:
        try:
            response = HTTP.get(url, timeout=FETCH_TIMEOUT,
                                headers={"User-Agent": "money-flow-monitor/1.0"})
            response.raise_for_status()
            if len(response.content) > 2_000_000:
                raise ValueError("news response too large")
            raw_path = ROOT / "data" / "raw" / run_day / (publisher.replace(" ", "_") + ".xml.gz")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(raw_path, "wb") as handle:
                handle.write(response.content)
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError("invalid news XML")
            for entry in parsed.entries[:15]:
                title = str(entry.get("title", "")).strip()[:250]
                link = str(entry.get("link", "")).strip()
                if not title or not link.startswith("https://"):
                    continue
                key = hashlib.sha256((title.lower() + "|" + link).encode()).hexdigest()[:16]
                if key in seen:
                    continue
                seen.add(key)
                title_low = title.lower()
                kind = "rates" if any(s in title_low for s in ("rate", "policy", "monetary")) else (
                    "inflation" if "inflation" in title_low else "other")
                entries.append({"headline_id": key, "title": title,
                                "publisher": publisher, "url": link,
                                "event_type": kind, "impact": "unconfirmed",
                                "direction": "unclear", "data": "Headline only",
                                "reading": "No verified causal market reaction"})
        except Exception as exc:
            errors.append({"source": publisher, "error": type(exc).__name__})
    return entries[:30], errors


def context_brief(feed, news):
    items = feed["items"]
    pos = [a for a in items if a["label"] == "Bullish"]
    neg = [a for a in items if a["label"] == "Bearish"]
    sources = sorted({v["source"] for a in items
                      for v in a["families"].values() if v.get("source")})
    def lines(rows):
        return "\n".join("- " + a["item"] + ": " + a["label"] + " (" +
                         a["tag"] + "); " + a["families"]["money_flow"]["evidence"] +
                         "; " + a["families"]["price_trend"]["evidence"] +
                         " [source](" + (a.get("price_source") or
                                         "https://fred.stlouisfed.org/") + ")"
                         for a in rows[:3]) or "- No qualifying directional signal; data may be incomplete."
    date_string = feed["as_of_ist"]
    summary = feed.get("executive_summary")
    summary_block = ""
    if summary:
        how = ("AI-written, rule-checked" if summary.get("method") == "ai_validated"
               else "rule-based, no AI used")
        summary_block = ("\n## Executive summary (" + how + ")\n" + summary["headline"] +
                         "\n\n" + summary["rotation_view"] + "\n")
    tone = regime_sentence(feed.get("regime"))
    tone_block = ("\n## Risk tone\n" + tone + "\n") if tone else ""
    upcoming = brief_lines(feed.get("calendar"))
    watch_next = ("\n".join(upcoming) if upcoming else
                  "Check official central-bank release calendars. Scheduled dates are not inferred when unavailable.")
    top = news[:3]
    drivers = "\n".join("- " + x["title"] + " — unconfirmed; [source](" +
                        x["url"] + ")" for x in top) or "- No validated new catalysts."
    return f"""# Global Money-Flow Brief | {date_string}

**Headline:** Independently confirmed flows are limited; unsupported signals remain Neutral/Mixed.
{summary_block}{tone_block}
## Where money is flowing
**Data — supportive evidence:**\n{lines(pos)}
**Data — opposing evidence:**\n{lines(neg)}

## What is driving it
{drivers}

## Liquidity check
**Data:** Official U.S. macro series and their dates appear in the feed's macro section.
**Reading:** Changes in central-bank balances are context, not a verified transfer into a named asset.

## What it means for you
- **CEO:** Consider only regions with independently confirmed directional evidence; other signals are mixed.
- **CFO:** Check rates and currency observation dates before updating assumptions.
- **Treasurer:** Separate liquidity changes from asset-specific flows; review stale-series alerts.

## Watch next
{watch_next}

_Data: [FRED](https://fred.stlouisfed.org/) and cited market-proxy sources. As of {date_string}. Public research, not investment advice. Draft for human review. No trade recommendations._
"""


def publish(feed, news, health):
    run_day = feed["run_date_ist"]
    save_json("data/feed/v1/latest.json", feed)
    save_json("data/feed/v1/daily/" + run_day + ".json", feed)
    save_json("docs/feed/v1/latest.json", feed)
    save_json("data/labels/" + run_day + ".json", {
        "as_of": feed["as_of_ist"], "items": feed["items"]})
    save_json("data/news/" + run_day + ".json", news)
    save_json("data/health/" + run_day + ".json", health)
    save_json("docs/status.json", health)
    # Replace legacy scored summary to avoid exposing misleading old numbers.
    save_json("data/latest_summary.json", {"schema_version": "1.0",
              "generated_at": feed["generated_at_utc"], "assets": feed["items"],
              "notice": "Legacy smart-money scores have been retired."})
    brief = context_brief(feed, news)
    p = ROOT / "briefs" / run_day
    p.mkdir(parents=True, exist_ok=True)
    (p / "executive.md").write_text(brief, encoding="utf-8")
    (ROOT / "reports" / "latest_report.md").write_text(brief, encoding="utf-8")
    flow_headline = (feed.get("executive_summary") or {}).get("headline", "")
    into = [x["item"] for x in feed["items"] if x["label"] == "Bullish"][:2]
    out = [x["item"] for x in feed["items"] if x["label"] == "Bearish"][:2]
    (p / "linkedin.txt").write_text(
        "Global money-flow monitor — " + feed["as_of_ist"] +
        "\n\nData: Supportive evidence: " + (", ".join(into) or "not independently confirmed") +
        ". Opposing evidence: " + (", ".join(out) or "not independently confirmed") +
        ".\n\n" + (("Flow rotation: " + flow_headline + "\n\n") if flow_headline else "") +
        ((regime_sentence(feed.get("regime")) + "\n\n") if feed.get("regime") else "") +
        "Reading: Volume patterns are not direct fund flows. Verify source freshness and the six evidence families before making financial decisions." +
        "\n\nFor CEO, CFO and Treasury readers, watch monetary conditions, liquidity and cross-market confirmation." +
        "\n\nSources and observation dates: see the evidence dashboard. Informational only, not advice.\n",
        encoding="utf-8")
    thread = ["Global money flow | " + feed["as_of_ist"] + ". Categorical, evidence-based signals; no scores.",
              "Supportive: " + (", ".join(into) or "not confirmed") + "; opposing: " +
              (", ".join(out) or "not confirmed") + "."]
    if flow_headline:
        thread.append("Flow rotation: " + flow_headline)
    if feed.get("regime"):
        thread.append(regime_sentence(feed["regime"]))
    thread += ["Drivers require next-session confirmation; headlines alone do not establish a directional move.",
               "Finance leaders: treat Fed liquidity as context, not measured allocation into assets.",
               "Observe freshness and full source citations on the dashboard. Informational only; human approval required."]
    (p / "x_thread.txt").write_text(
        "\n\n".join("%d/ %s" % (number, text) for number, text in enumerate(thread, 1)) + "\n",
        encoding="utf-8")
    # Retire the legacy, permanently generated HTML score table.
    (ROOT / "frontend" / "index.html").write_text(
        '<!doctype html><html><meta charset="utf-8"><title>Monitor migrated</title>'
        '<body><p>Scored tracker retired. See <a href="../docs/index.html">'
        'the evidence-based dashboard</a>.</p></body></html>\n', encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0,
                        help="Optional bounded smoke test, 0 covers configured universe")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    current = now_utc()
    now_ist = current.astimezone(IST)
    day = now_ist.date().isoformat()
    universe = read_yaml("config/universe.yaml")["assets"]
    if args.sample:
        universe = universe[:args.sample]
    source_config = read_yaml("config/sources.yaml")
    series = source_config["macro_series"]
    treasury_ids = source_config.get("treasury_par_series", {})
    macro, errors = {}, []
    from backend.macro_fallback import fetch_dbnomics_fed_yield
    from backend.m0_fallback import fetch_m0_fred_series
    from backend.advanced_sources import fetch_fred_mirror, fetch_ecb_assets
    for sid in series:
        try:
            macro[sid] = fetch_fred(sid, day)
        except Exception as exc:
            primary_error = type(exc).__name__
            try:
                macro[sid] = fetch_dbnomics_fed_yield(sid, day, ROOT)
                errors.append({"source": "fred:" + sid,
                               "error": "primary_" + primary_error + "; DBnomics mirror used"})
            except Exception as fallback_exc:
                try:
                    macro[sid] = fetch_fred_mirror(sid, ROOT, day)
                    errors.append({"source": "fred:" + sid,
                                   "error": "Primary and H15 fallback failed; clearly labelled DBnomics FRED mirror used"})
                except Exception as final_exc:
                    try:
                        macro[sid] = fetch_m0_fred_series(sid, ROOT, day)
                        errors.append({"source": "fred:" + sid,
                                       "error": "Official and DBnomics unavailable; attributed M0.com public secondary CSV used"})
                    except Exception as third_exc:
                        errors.append({"source": "macro:" + sid,
                                       "error": "FRED_" + primary_error + "; fallbacks_" +
                                                type(fallback_exc).__name__ + "_" +
                                                type(final_exc).__name__ + "_" +
                                                type(third_exc).__name__})
    if os.environ.get("FRED_API_KEY", "").strip() and not any(
            v.get("fetch_path") == "fred_api" for v in macro.values()):
        errors.append({"source": "fred_api",
                       "error": "FRED_API_KEY is set but the FRED API gave no data; public CSV used"})
    # Cross-central-bank liquidity: direct ECB first, then expressly attributed
    # FRED/DBnomics secondary; BOJ is a separate dated monthly series.
    for bank_id, mirror_id in (("ECB_ILM_TOTAL_ASSETS", "ECBASSETSW"),
                               ("BOJ_TOTAL_ASSETS", "JPNASSETS")):
        try:
            if bank_id == "ECB_ILM_TOTAL_ASSETS":
                macro[bank_id] = fetch_ecb_assets(ROOT, day)
            else:
                macro[bank_id] = fetch_boj_total_assets(day)
        except Exception as exc:
            try:
                if bank_id == "ECB_ILM_TOTAL_ASSETS":
                    macro[bank_id] = fetch_fred_mirror(mirror_id, ROOT, day)
                    macro[bank_id]["id"] = bank_id
                    macro[bank_id]["source_series_id"] = mirror_id
                    errors.append({"source": "ecb_direct", "error":
                                   "Failed (" + type(exc).__name__ + "), attributed FRED mirror used"})
                else:
                    errors.append({"source": "boj_assets", "error":type(exc).__name__})
            except Exception as fallback_error:
                errors.append({"source": "ecb_assets", "error":
                               type(exc).__name__ + ";" + type(fallback_error).__name__})
    from backend.treasury_rates import fetch_us_treasury_par_curve
    try:
        treasury_rates = fetch_us_treasury_par_curve(day, ROOT)
        for sid in treasury_ids:
            if sid in treasury_rates:
                macro[sid] = treasury_rates[sid]
            else:
                errors.append({"source": "us_treasury:" + sid,
                               "error": "official CSV missing valid observations"})
    except Exception as exc:
        errors.append({"source": "us_treasury_par_curve",
                       "error": type(exc).__name__ + ": " + str(exc)[:110]})
    today = now_ist.date()
    for sid, series_record in list(macro.items()):
        macro[sid] = annotate_macro_freshness(sid, series_record, today)
        if macro[sid]["freshness"] == "stale":
            errors.append({"source": "macro_stale:" + sid,
                           "error": "Last observation " + str(macro[sid]["last_good_date"]) +
                                    "; permitted " + macro[sid]["allowed_age"]})
    from backend.advanced_sources import fetch_cftc, cftc_gaps, breadth_from_equal_weight
    from backend.institutional_flows import institutional_status
    from backend.news_classifier import classify_headlines
    try:
        cftc = fetch_cftc(ROOT, day)
    except Exception as exc:
        cftc = {"entries": {}, "status": "unavailable",
                "source": "https://publicreporting.cftc.gov/Commitments-of-Traders",
                "error": type(exc).__name__}
        errors.append({"source": "cftc_tff", "error": type(exc).__name__})
    else:
        # Not an "official source problem" (no retry): the site answered, a market just did not match.
        for gap in cftc_gaps(cftc.get("entries"), {a["id"] for a in universe}):
            errors.append({"source": "cftc_market:" + gap, "error":
                           "No single matching futures contract with two recent weekly reports "
                           "(the exchange may have renamed it)"})
    breadth_records = {}
    for ident in ("sp500", "nasdaq100"):
        if ident not in {a["id"] for a in universe}:
            continue
        try:
            breadth_records[ident] = breadth_from_equal_weight(ident, day)
        except Exception as exc:
            errors.append({"source": "breadth:" + ident,
                           "error": type(exc).__name__})
    institution = institutional_status(day)
    if institution["nse_cash_via_authorized_broker"].get("status") not in (
            "observed_readonly_provider_not_nsdl_reconciled",):
        errors.append({"source":"institutional_flows",
                       "error": "Authorized NSE broker feed or final NSDL access unavailable"})
    news, news_errors = collect_news(day)
    errors.extend(news_errors)
    news, classifier_health = classify_headlines(news, universe)
    if classifier_health["model_classified"] == 0:
        errors.append({"source": "news_classifier",
                       "error": "No accepted AI responses; transparent deterministic tag fallback"})
    try:
        flow_cfg = read_yaml("config/flow_windows.yaml")
    except Exception as exc:
        flow_cfg = None
        errors.append({"source": "flow_windows_config", "error": type(exc).__name__})
    items = []
    closes = {}          # completed daily closes, read only by the risk-on / risk-off banner
    for asset in universe:
        LOG.info("Checking %s", asset["id"])
        record = assess(asset, today, macro,
                        positioning=cftc.get("entries", {}).get(asset["id"]),
                        breadth=breadth_records.get(asset["id"]),
                        flow_cfg=flow_cfg, now=current, closes_sink=closes)
        items.append(record)
        if record.get("source_error"):
            errors.append({"source": "price:" + asset["id"],
                           "error": record["source_error"]})
    rotation = None
    if flow_cfg is not None:
        try:
            rotation = build_rotation(items, flow_cfg)
        except Exception as exc:
            errors.append({"source": "flow_rotation",
                           "error": type(exc).__name__ + ": " + str(exc)[:110]})
    regime = None
    if flow_cfg is not None:
        try:
            regime = build_regime(closes, load_regime_config(), flow_cfg, current)
        except Exception as exc:
            errors.append({"source": "regime",
                           "error": type(exc).__name__ + ": " + scrub_secrets(str(exc))[:110]})
    fresh = sum(x.get("freshness") == "current" for x in items)
    macro_current = sum(v.get("freshness") == "current" for v in macro.values())
    macro_stale = sorted(k for k, v in macro.items() if v.get("freshness") != "current")
    macro_expectations = set(series) | set(treasury_ids) | {
        "ECB_ILM_TOTAL_ASSETS", "BOJ_TOTAL_ASSETS", "RBI_SYSTEM_LIQUIDITY", "PBOC_TOTAL_ASSETS"
    }
    liquidity_coverage = {}
    for region, sid, public_url in (
        ("US", "WALCL", "https://fred.stlouisfed.org/series/WALCL"),
        ("EU", "ECB_ILM_TOTAL_ASSETS",
         "https://data.ecb.europa.eu/data/datasets/ILM/ILM.W.U2.C.T000000.Z5.Z01"),
        ("JP", "BOJ_TOTAL_ASSETS", "https://fred.stlouisfed.org/series/JPNASSETS"),
        ("IN", "RBI_SYSTEM_LIQUIDITY", "https://data.rbi.org.in/"),
        ("CN", "PBOC_TOTAL_ASSETS", "http://www.pbc.gov.cn/en/")):
        observed = macro.get(sid)
        liquidity_coverage[region] = {
            "series_id": sid,
            "status": observed.get("freshness", "not_available") if observed else "not_available",
            "observation_date": observed.get("last_good_date") if observed else None,
            "source": observed.get("source", public_url) if observed else public_url,
            "note": "Not a complete cross-border money flow measurement",
        }
    usable = macro_current > 0 or fresh > 0
    official_problems = [e for e in errors if OFFICIAL_SOURCE_PROBLEM.match(e["source"])]
    health = {
        "as_of_ist": now_ist.isoformat(),
        "run_slot": os.environ.get("RUN_SLOT", "manual"),
        "completed_at_utc": now_utc().isoformat(),
        # True when a primary official source (FRED, Treasury, CFTC) failed and a
        # fallback or nothing was used: the backup schedule slot then tries again.
        "needs_retry": bool(official_problems),
        "official_source_problems": len(official_problems),
        "status": "degraded" if errors or fresh < len(items) else "ok",
        "items_configured": len(items), "price_proxies_current": fresh,
        "macro_series_available": len(macro),
        "macro_series_current": macro_current,
        "macro_series_stale": macro_stale,
        "macro_series_unavailable": sorted(macro_expectations - set(macro)),
        "liquidity_regions": liquidity_coverage,
        "cftc_markets_with_evidence": list(cftc.get("entries", {})),
        "institutional_flow_status": institution["nse_cash_via_authorized_broker"].get("status"),
        "ai_classification": classifier_health,
        "flow_windows": (rotation or {}).get("coverage", {"status": "not_available"}),
        "regime": regime_health(regime),
        "missing": [x["id"] for x in items if x["freshness"] != "current"],
        "errors": errors, "vendor_price_exported": False,
        "publication": "categorical_research_only",
        "note": "No privately licensed price tables, broker data, or portfolio records published."
    }
    if not usable:
        health["status"] = "failed"
        save_json("docs/status.json", health)
        raise RuntimeError("No usable market or macro sources: previous feed retained")
    # Calendar and market news use the network, so they come only after the run is known to be
    # worth publishing. Neither can stop the refresh: a failure becomes a note in the health report.
    calendar, calendar_health = None, {"status": "not_available"}
    try:
        calendar, calendar_health = build_calendar(
            load_events_config(), today, api_key=os.environ.get("FRED_API_KEY", ""))
        if calendar_health["fred"]["status"] == "unavailable":
            # A named source that failed. The name does not start with "fred" on purpose:
            # a missing calendar must not keep the backup refresh slots running.
            errors.append({"source": "calendar_fred",
                           "error": calendar_health["fred"].get("error", "unavailable")})
    except Exception as exc:
        errors.append({"source": "calendar",
                       "error": type(exc).__name__ + ": " + scrub_secrets(str(exc))[:110]})
    market_news, market_news_health = None, {"status": "not_available"}
    try:
        market_news, market_news_health = build_market_news(load_news_config(), current)
        if market_news_health["status"] == "unavailable":
            errors.append({"source": "market_news", "error": scrub_secrets(
                (market_news_health["errors"] or ["unavailable"])[0])[:110]})
    except Exception as exc:
        errors.append({"source": "market_news",
                       "error": type(exc).__name__ + ": " + scrub_secrets(str(exc))[:110]})
    health["calendar"] = calendar_health
    health["market_news"] = market_news_health
    if errors:
        health["status"] = "degraded"
    feed = {
        "schema_version": "1.0", "generated_at_utc": current.isoformat(),
        "as_of_ist": now_ist.isoformat(), "run_date_ist": day,
        "methodology": "six-family deterministic rules, not a score",
        "provider_license": "Public feed excludes unofficial-vendor price tables",
        "usage": "research_only_not_order_authorization",
        "macro": macro, "items": items,
        "drivers": news,
        "institutional_flows": institution,
        "positioning": cftc,
        "breadth_proxies": breadth_records,
        "liquidity_coverage": liquidity_coverage,
        "classification_health": classifier_health, "health": {"status": health["status"],
                                    "price_proxies_current": fresh,
                                    "items_configured": len(items),
                                    "macro_series_current": macro_current,
                                    "macro_series_stale": macro_stale},
        "source_manifest": "config/sources.yaml"
    }
    if rotation is not None:
        feed["rotation"] = rotation
    if regime is not None:
        feed["regime"] = regime
    if calendar is not None:
        feed["calendar"] = calendar
    if market_news is not None:
        feed["market_news"] = market_news
    from backend.exec_summary import build_executive_summary
    try:
        feed["executive_summary"], health["executive_summary"] = build_executive_summary(
            feed, macro_names={**source_config.get("macro_series", {}),
                               **source_config.get("treasury_par_series", {})},
            now=current)
    except Exception as exc:     # the summary is a bonus: it must never stop the refresh
        health["executive_summary"] = {"method": "failed", "reasons": [type(exc).__name__]}
    publish(feed, news, health)
    LOG.info("Published %s of %s current proxies, %s macro series",
             fresh, len(items), len(macro))


if __name__ == "__main__":
    main()
