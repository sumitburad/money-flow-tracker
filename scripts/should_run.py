"""Decide whether a scheduled refresh is needed. Uses only the Python standard library.

The daily workflow has two main slots and two backup slots (times are IST):

    07:37  morning   -> always runs
    10:07  morning backup -> runs only if the morning refresh is missing or needed a retry
    19:07  evening   -> always runs
    21:37  evening backup -> same rule as the morning backup

A backup run costs about one minute when it is not needed, so the safety net is cheap.
A click on "Run workflow" always runs.

Usage (inside the workflow):
    python3 scripts/should_run.py --event "$EVENT" --schedule "$SCHEDULE"
It prints a plain-language reason and writes ``run=true|false`` and
``slot=primary|backup|manual`` to $GITHUB_OUTPUT when that file exists.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IST = timezone(timedelta(hours=5, minutes=30))
# cron text (UTC) -> session. Keep in step with .github/workflows/daily.yml.
PRIMARY = {"7 2 * * *": "morning", "37 13 * * *": "evening"}
BACKUP = {"37 4 * * *": "morning", "7 16 * * *": "evening"}
EVENING_STARTS_AT_HOUR = 13  # IST hour when the evening session begins


def session_of(moment_ist):
    return "morning" if moment_ist.hour < EVENING_STARTS_AT_HOUR else "evening"


def read_status(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_stamp(text):
    try:
        stamp = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else None


def decide(event, schedule, status, now_utc):
    """Return (run: bool, slot: str, reason: str)."""
    if event != "schedule":
        return True, "manual", "You started this run yourself, so it always runs."
    if schedule in PRIMARY:
        return True, "primary", "Main %s slot: always runs." % PRIMARY[schedule]
    if schedule not in BACKUP:
        return True, "primary", "Unrecognised schedule %r: running to be safe." % schedule
    session = BACKUP[schedule]
    now_ist = now_utc.astimezone(IST)
    last = parse_stamp((status or {}).get("as_of_ist"))
    if (status and last and status.get("status") in ("ok", "degraded")
            and last.astimezone(IST).date() == now_ist.date()
            and session_of(last.astimezone(IST)) == session):
        if not status.get("needs_retry"):
            return (False, "backup",
                    "The %s refresh already worked today (%s IST). Nothing to do."
                    % (session, last.astimezone(IST).strftime("%H:%M")))
        if status.get("run_slot") == "backup":
            return (False, "backup",
                    "The backup already ran once for this %s session. Not repeating." % session)
        return (True, "backup",
                "The %s refresh worked but a data source needed a retry. Trying again." % session)
    return (True, "backup",
            "No successful %s refresh found today, so this backup run is needed." % session)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default="workflow_dispatch")
    parser.add_argument("--schedule", default="")
    parser.add_argument("--status", default=str(ROOT / "docs" / "status.json"))
    parser.add_argument("--now", default=None, help="ISO time, for testing only")
    args = parser.parse_args(argv)
    now = parse_stamp(args.now) if args.now else datetime.now(timezone.utc)
    run, slot, reason = decide(args.event, args.schedule.strip(),
                               read_status(args.status), now)
    print(("RUN: " if run else "SKIP: ") + reason)
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("run=%s\nslot=%s\n" % ("true" if run else "false", slot))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("**%s** %s\n\n" % ("Running." if run else "Skipped.", reason))
    return 0


if __name__ == "__main__":
    sys.exit(main())
