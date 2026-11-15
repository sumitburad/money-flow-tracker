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
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from urllib.parse import quote

import feedparser
import numpy as np
import pandas as pd
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
FAMILIES = ("money_flow", "price_trend", "breadth", "positioning",
            "macro_liquidity", "news")
VALID_STATES = {"supportive", "neutral", "opposing", "not_available"}
IST = timezone(timedelta(hours=5, minutes=30))
LOG = logging.getLogger("moneyflow")


def now_utc():
    return datetime.now(timezone.utc)


def save_json(path, obj):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


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


def fetch_fred(series_id, run_day):
    """Official free CSV export. Preserve exact response bytes before parsing."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    resp = requests.get(url, params={"id": series_id}, timeout=20,
                        headers={"User-Agent": "money-flow-monitor/1.0 (research)"})
    resp.raise_for_status()
    raw = resp.content
    if len(raw) > 4_000_000 or len(raw) < 12:
        raise ValueError("unexpected FRED payload size")
    raw_path = ROOT / "data" / "raw" / run_day / (series_id + ".csv.gz")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wb") as handle:
        handle.write(raw)
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
            "raw_file": str(raw_path.relative_to(ROOT))}


def macro_family(asset, macro, today):
    if asset["asset_type"] not in ("equity", "crypto", "bond"):
        return na("Macro effect varies by asset; no verified mapping")
    sheet = macro.get("WALCL")
    if not sheet or len(sheet.get("recent", [])) < 5:
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


def assess(asset, today, macro):
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
        result["volume_observed"] = families["money_flow"]["state"] != "not_available"
    except Exception as exc:
        tag = "Steady"
        result["freshness"] = "unavailable"
        result["observation_date"] = None
        result["source_error"] = type(exc).__name__ + ": " + str(exc)[:140]
        result["volume_observed"] = False
    families["macro_liquidity"] = macro_family(asset, macro, today)
    families["breadth"] = na("No independently sourced constituent breadth")
    families["positioning"] = na("No verified CFTC/positioning series mapped")
    families["news"] = na("Headline impact not confirmed by next-session prices")
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
            response = requests.get(url, timeout=15,
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
    top = news[:3]
    drivers = "\n".join("- " + x["title"] + " — unconfirmed; [source](" +
                        x["url"] + ")" for x in top) or "- No validated new catalysts."
    return f"""# Global Money-Flow Brief | {date_string}

**Headline:** Independently confirmed flows are limited; unsupported signals remain Neutral/Mixed.

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
Check official central-bank release calendars. Scheduled dates are not inferred when unavailable.

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
    into = [x["item"] for x in feed["items"] if x["label"] == "Bullish"][:2]
    out = [x["item"] for x in feed["items"] if x["label"] == "Bearish"][:2]
    (p / "linkedin.txt").write_text(
        "Global money-flow monitor — " + feed["as_of_ist"] +
        "\n\nData: Supportive evidence: " + (", ".join(into) or "not independently confirmed") +
        ". Opposing evidence: " + (", ".join(out) or "not independently confirmed") +
        ".\n\nReading: Volume patterns are not direct fund flows. Verify source freshness and the six evidence families before making financial decisions." +
        "\n\nFor CEO, CFO and Treasury readers, watch monetary conditions, liquidity and cross-market confirmation." +
        "\n\nSources and observation dates: see the evidence dashboard. Informational only, not advice.\n",
        encoding="utf-8")
    (p / "x_thread.txt").write_text(
        "1/ Global money flow | " + feed["as_of_ist"] + ". Categorical, evidence-based signals; no scores.\n\n" +
        "2/ Supportive: " + (", ".join(into) or "not confirmed") + "; opposing: " +
        (", ".join(out) or "not confirmed") + ".\n\n" +
        "3/ Drivers require next-session confirmation; headlines alone do not establish a directional move.\n\n" +
        "4/ Finance leaders: treat Fed liquidity as context, not measured allocation into assets.\n\n" +
        "5/ Observe freshness and full source citations on the dashboard. Informational only; human approval required.\n",
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
    series = read_yaml("config/sources.yaml")["macro_series"]
    macro, errors = {}, []
    for sid in series:
        try:
            macro[sid] = fetch_fred(sid, day)
        except Exception as exc:
            errors.append({"source": "fred:" + sid,
                           "error": type(exc).__name__ + ": " + str(exc)[:110]})
    news, news_errors = collect_news(day)
    errors.extend(news_errors)
    today = now_ist.date()
    items = []
    for asset in universe:
        LOG.info("Checking %s", asset["id"])
        record = assess(asset, today, macro)
        items.append(record)
        if record.get("source_error"):
            errors.append({"source": "price:" + asset["id"],
                           "error": record["source_error"]})
    fresh = sum(x.get("freshness") == "current" for x in items)
    usable = bool(macro) or fresh > 0
    health = {
        "as_of_ist": now_ist.isoformat(),
        "status": "degraded" if errors or fresh < len(items) else "ok",
        "items_configured": len(items), "price_proxies_current": fresh,
        "macro_series_available": len(macro),
        "missing": [x["id"] for x in items if x["freshness"] != "current"],
        "errors": errors, "vendor_price_exported": False,
        "publication": "categorical_research_only",
        "note": "No privately licensed price tables, broker data, or portfolio records published."
    }
    if not usable:
        health["status"] = "failed"
        save_json("docs/status.json", health)
        raise RuntimeError("No usable market or macro sources: previous feed retained")
    feed = {
        "schema_version": "1.0", "generated_at_utc": current.isoformat(),
        "as_of_ist": now_ist.isoformat(), "run_date_ist": day,
        "methodology": "six-family deterministic rules, not a score",
        "provider_license": "Public feed excludes unofficial-vendor price tables",
        "usage": "research_only_not_order_authorization",
        "macro": macro, "items": items,
        "drivers": news, "health": {"status": health["status"],
                                    "price_proxies_current": fresh,
                                    "items_configured": len(items)},
        "source_manifest": "config/sources.yaml"
    }
    publish(feed, news, health)
    LOG.info("Published %s of %s current proxies, %s macro series",
             fresh, len(items), len(macro))


if __name__ == "__main__":
    main()
