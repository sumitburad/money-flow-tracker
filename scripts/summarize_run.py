"""Write a short plain-language result of the last refresh to the run page.

Reads docs/status.json and data/feed/v1/latest.json (standard library only).
The text goes to $GITHUB_STEP_SUMMARY when set, otherwise to the screen.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


TONE_WORDS = {"risk_on": "risk-on", "risk_off": "risk-off", "mixed": "mixed",
              "not_enough_data": "not enough data"}


def new_feature_lines(status):
    """Plain-language lines for the risk banner, the events calendar and the market news.

    Each block is optional, so a status file from an older run simply adds no line.
    """
    lines = []
    regime = status.get("regime")
    if isinstance(regime, dict):
        if regime.get("status") == "ok":
            with_data = regime.get("checks_with_data") or {}
            lines.append("- **Risk tone:** %s this month, %s this week (%s of %s checks had prices)" % (
                TONE_WORDS.get(regime.get("label"), "unknown"),
                TONE_WORDS.get(regime.get("short_term_label"), "unknown"),
                with_data.get("month", "?"), regime.get("checks_total", "?")))
        else:
            lines.append("- **Risk tone:** could not be worked out this run")
    calendar = status.get("calendar")
    if isinstance(calendar, dict) and calendar.get("status") != "not_available":
        fred = (calendar.get("fred") or {}).get("status")
        found = calendar.get("events", 0)
        dates = "%s coming %s" % (found, "date" if found == 1 else "dates")
        if fred == "ok":
            text = dates + " found (FRED calendar read live)"
        elif fred == "not_configured":
            text = dates + " (Fed meetings only, because no FRED key is saved)"
        else:
            text = dates + " (FRED's calendar could not be read, so only Fed meetings are shown)"
        notes = len(calendar.get("advisories") or [])
        lines.append("- **Coming events:** " + text + (
            "; %d note%s in the Data quality box" % (notes, "" if notes == 1 else "s") if notes else ""))
    news = status.get("market_news")
    if isinstance(news, dict) and news.get("status") != "not_available":
        state = news.get("status")
        if state == "disabled":
            lines.append("- **Market news:** switched off in the settings")
        elif state == "unavailable":
            lines.append("- **Market news:** the free news index could not be reached; the page says so")
        else:
            lines.append("- **Market news:** %s headlines kept (%s about companies); %s of %s questions answered%s" % (
                news.get("kept", 0), news.get("company_stories", 0), news.get("queries_answered", "?"),
                news.get("queries_asked", "?"), "" if state == "ok" else " (some failed)"))
    return lines


def build(status, feed):
    macro = (feed or {}).get("macro") or {}
    paths = Counter(v.get("fetch_path", "other") for v in macro.values())
    state = {"ok": "OK", "degraded": "OK, with some data gaps", "failed": "FAILED"}.get(
        status.get("status"), "unknown")
    lines = ["### Money-flow refresh result", "",
             "- **Result:** " + state,
             "- **Collected at (IST):** " + str(status.get("as_of_ist", "unknown")),
             "- **Market items with fresh data:** %s of %s" % (
                 status.get("price_proxies_current", "?"), status.get("items_configured", "?")),
             "- **Official macro series up to date:** %s of %s" % (
                 status.get("macro_series_current", "?"), status.get("macro_series_available", "?"))]
    if status.get("macro_series_stale"):
        lines.append("- **Behind on dates:** " + ", ".join(status["macro_series_stale"]))
    lines.append("- **FRED connection:** %d via your free key, %d via the public page" % (
        paths.get("fred_api", 0), paths.get("fred_csv", 0)))
    flow = status.get("flow_windows") or {}
    if flow.get("items_with_signal") is not None:
        lines.append("- **Day/week/month money-flow signals:** %s of %s items have a volume signal" % (
            flow.get("items_with_signal"), flow.get("items_in_rotation")))
    summary = (status.get("executive_summary") or {}).get("method")
    if summary:
        lines.append("- **Executive summary:** " + {
            "ai_validated": "written by AI and rule-checked",
            "rules_only": "rule-based (no AI answer was used)"}.get(summary, summary))
    lines.extend(new_feature_lines(status))
    problems = status.get("official_source_problems", 0)
    if problems:
        lines.append("- **Official-source problems this run:** %d (a backup run tries again later)" % problems)
    if status.get("status") == "failed":
        lines.append("- Nothing new was published; the previous data stays on the dashboard.")
    return "\n".join(lines) + "\n"


def main():
    text = build(load(ROOT / "docs" / "status.json"),
                 load(ROOT / "data" / "feed" / "v1" / "latest.json"))
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
