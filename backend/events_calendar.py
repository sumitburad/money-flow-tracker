"""Calendar of coming events: US data releases (read from FRED) and Fed meetings.

Why this exists: CPI, PCE, the jobs report and Fed meetings move markets, so the dashboard
shows when the next ones are due. It publishes dates only, never a forecast of the result.

Where the dates come from
  * FRED's release calendar (needs the free FRED_API_KEY). The names in config/events.yaml
    must match FRED's release names; unmatched ones are reported, not guessed.
  * A built-in Fed meeting list in the same config file. It is flagged as "not yet checked
    against federalreserve.gov" until a person checks it, and it warns when it runs out.

Nothing here can stop the daily refresh: every failure becomes a note in the health report.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import requests
import yaml

from backend.net import HTTP, redact

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "events.yaml"
FAR_FUTURE = "9999-12-31"
HEADERS = {"User-Agent": "money-flow-monitor/1.0 (research)"}
TIMEOUT = (6, 40)
IMPORTANCE_ORDER = {"high": 0, "medium": 1}
NOTICE = ("Dates come from the agencies' own calendars and can change. Confirm on the agency's "
          "website before relying on one. Only dates are shown, never a forecast of the result.")


def load_config(path=None):
    return yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _norm(text):
    return re.sub(r"\s+", " ", str(text)).strip().lower()


def fetch_fred_release_dates(http, api_key, start, end, cfg):
    """Every FRED release date from ``start`` to ``end``, as a list of (release name, date)."""
    found, seen = [], set()
    size = int(cfg["page_size"])
    for page in range(int(cfg["max_pages"])):
        # Never use raise_for_status() here: its message would contain the URL with the key.
        response = http.get(cfg["url"], params={
            "api_key": api_key, "file_type": "json",
            "realtime_start": start.isoformat(), "realtime_end": FAR_FUTURE,
            "include_release_dates_with_no_data": "true",
            "order_by": "release_date", "sort_order": "asc",
            "limit": size, "offset": page * size}, timeout=TIMEOUT, headers=HEADERS)
        if response.status_code != 200:
            raise requests.HTTPError("FRED release calendar answered HTTP %s" % response.status_code)
        raw = response.content
        if len(raw) > 4_000_000:
            raise ValueError("unexpected FRED release calendar size")
        rows = json.loads(raw).get("release_dates")
        if not isinstance(rows, list):
            raise ValueError("unexpected FRED release calendar shape")
        last_day = None
        for row in rows:
            try:
                day = date.fromisoformat(str(row["date"])[:10])
                name = str(row["release_name"])
            except (KeyError, TypeError, ValueError):
                continue
            last_day = day
            if start <= day <= end and (name, day) not in seen:
                seen.add((name, day))
                found.append((name, day))
        if len(rows) < size or (last_day is not None and last_day > end):
            break
    return found


def _event(entry, day, today, basis, source_url):
    return {"id": entry["id"], "name": entry["name"], "category": entry["category"],
            "importance": entry["importance"], "date": day.isoformat(),
            "days_away": (day - today).days, "basis": basis,
            "source_url": source_url, "why": entry["why"]}


def build_calendar(cfg, today, *, http=HTTP, api_key=""):
    """Returns (calendar block for the feed, health notes). Never raises."""
    horizon = int(cfg["horizon_days"])
    end = today + timedelta(days=horizon)
    events, sources, advisories = [], [], []
    health = {"status": "ok", "fred": {"status": "not_configured"}, "events": 0,
              "advisories": advisories}

    # ---- FRED release calendar
    releases = cfg.get("releases", [])
    wanted = {}
    for entry in releases:
        names = entry["fred_release"]
        for name in (names if isinstance(names, list) else [names]):
            wanted[_norm(name)] = entry
    fred = {"id": "fred_release_calendar", "url": cfg["fred"]["calendar_page"],
            "status": "not_configured",
            "note": "Needs the FRED_API_KEY secret; without it only the built-in Fed list is shown."}
    api_key = (api_key or "").strip()
    if api_key:
        try:
            rows = fetch_fred_release_dates(http, api_key, today, end, cfg["fred"])
            matched = set()
            for name, day in rows:
                entry = wanted.get(_norm(name))
                if entry:
                    events.append(_event(entry, day, today, "fred_release_calendar",
                                         cfg["fred"]["calendar_page"]))
                    matched.add(entry["id"])
            missing = [e["id"] for e in releases if e["id"] not in matched]
            fred.update(status="ok", note="Read live this refresh.")
            health["fred"] = {"status": "ok", "rows_seen": len(rows), "unmatched_releases": missing}
            if missing:
                advisories.append(
                    "No upcoming FRED date was found for: " + ", ".join(missing) +
                    ". Check the release names in config/events.yaml against FRED.")
        except Exception as exc:
            reason = type(exc).__name__ + ": " + redact(str(exc))[:80]
            fred.update(status="unavailable", note="FRED's calendar could not be read this run.",
                        error=type(exc).__name__)
            health["fred"] = {"status": "unavailable", "error": reason}
    sources.append(fred)

    # ---- built-in lists (Fed meetings)
    for item in cfg.get("built_in", []):
        covers = date.fromisoformat(str(item["covers_through"]))
        checked = bool(item.get("checked_against_official_site"))
        for text in item["dates"]:
            day = date.fromisoformat(str(text))
            if today <= day <= end:
                events.append(_event(item, day, today, "built_in_list", item["source_url"]))
        state = {"id": "built_in_" + item["id"] + "_list", "url": item["source_url"],
                 "status": "ok", "checked_against_official_site": checked,
                 "covers_through": covers.isoformat(),
                 "note": ("Checked against the official site." if checked else
                          "Not yet checked against the official site, so confirm each date there.")}
        if end > covers:
            state["status"] = "needs_update"
            state["note"] += " It has no dates after %s; add the next calendar." % covers.isoformat()
            advisories.append("The built-in %s list ends %s. Add the next year's dates to "
                              "config/events.yaml." % (item["id"].upper(), covers.isoformat()))
        sources.append(state)

    events.sort(key=lambda e: (e["date"], IMPORTANCE_ORDER.get(e["importance"], 9), e["name"]))
    events = events[:int(cfg.get("max_events", 24))]
    health["events"] = len(events)
    if health["fred"]["status"] != "ok":
        health["status"] = "partial" if events else "unavailable"
    block = {"as_of": today.isoformat(), "horizon_days": horizon, "events": events,
             "sources": sources, "notice": NOTICE}
    return block, health


def _when_words(days):
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 7:
        return "within a week"
    if days <= 14:
        return "within two weeks"
    if days <= 31:
        return "within a month"
    return "later"


def digest_events(block, limit=6):
    """Names and plain-word timing only, for the AI summary (no dates or numbers)."""
    rows = []
    for event in (block or {}).get("events", [])[:limit]:
        rows.append({"name": event["name"], "when": _when_words(event["days_away"]),
                     "category": event["category"]})
    return rows


def brief_lines(block, limit=4):
    """Bullet lines for the written brief: the next few dates, with the source named."""
    lines = []
    for event in (block or {}).get("events", [])[:limit]:
        when = ("today" if event["days_away"] <= 0 else
                "tomorrow" if event["days_away"] == 1 else "in %d days" % event["days_away"])
        source = ("FRED's release calendar" if event["basis"] == "fred_release_calendar"
                  else "a built-in list; confirm at " + event["source_url"])
        lines.append("- %s: %s (%s). Date from %s." % (event["name"], event["date"], when, source))
    return lines

