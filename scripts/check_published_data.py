"""Check that the files about to be published belong together. Changes nothing.

scripts/commit_and_push.sh runs this just before every push to the main branch. If it
finds a problem, nothing is published and the previous good data stays on the dashboard.

What "belong together" means (every rule below is true by construction for a healthy run):

  1. The data file passes its own rules (backend/feed_contract.py), which includes
     recounting the risk-on / risk-off tally from the individual checks.
  2. The three copies of the data file (data/, docs/, frontend/) are identical, and so is
     the dated copy of that day's data file.
  3. The status file is the same in docs/ and frontend/, it does not say the run failed,
     it comes from the same run as the data file (same collection time), and the dated
     health report matches it.
  4. The history folders on the website match data/history/v1 file for file.

Usage:  python3 scripts/check_published_data.py [--root path/to/repository]
Prints plain sentences. Exit code 0 = fine, 1 = something does not match.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_ROOT))
from backend.feed_contract import load_feed  # noqa: E402

# Keep these in step with scripts/sync_site.py (a test compares the two).
FEED_COPIES = ("data/feed/v1/latest.json", "docs/feed/v1/latest.json",
               "frontend/feed/v1/latest.json")
STATUS_COPIES = ("docs/status.json", "frontend/status.json")
DATED_FEED_FOLDER = "data/feed/v1/daily"
DATED_HEALTH_FOLDER = "data/health"
HISTORY_SOURCE = "data/history/v1"
HISTORY_COPIES = ("docs/history/v1", "frontend/history/v1")

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHOW_AT_MOST = 3


def _read(root, relative):
    try:
        return (root / relative).read_bytes()
    except OSError:
        return None


def _reason(error):
    text = "%s: %s" % (type(error).__name__, error)
    return text if len(text) <= 220 else text[:217] + "..."


def _names(names):
    shown = ", ".join(names[:SHOW_AT_MOST])
    return shown + (" and %d more" % (len(names) - SHOW_AT_MOST) if len(names) > SHOW_AT_MOST else "")


def _json_object(raw, label, problems):
    """Parse raw bytes as a JSON object; add a plain sentence to ``problems`` if that fails."""
    if raw is None:
        problems.append("%s is missing." % label)
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        problems.append("%s cannot be read (%s)." % (label, _reason(error)))
        return None
    if not isinstance(value, dict):
        problems.append("%s is not the kind of file expected." % label)
        return None
    return value


def _folder_files(folder):
    return {item.relative_to(folder).as_posix(): item.read_bytes()
            for item in sorted(folder.rglob("*")) if item.is_file()}


def run_checks(root):
    """Return (problems, passed): plain sentences for what is wrong and for what was fine."""
    root = Path(root)
    problems, passed = [], []

    def section(label, work):
        """Run one group of checks; say it passed only if it added no problem."""
        before = len(problems)
        work()
        if len(problems) == before:
            passed.append(label)

    state = {"feed": None, "status": None, "day": None}
    main_copy = FEED_COPIES[0]
    main_bytes = _read(root, main_copy)

    def feed_follows_its_rules():
        if main_bytes is None:
            problems.append("The main data file is missing (%s)." % main_copy)
            return
        try:
            state["feed"] = load_feed(root / main_copy)
        except Exception as error:  # any failure at all means: do not publish
            problems.append("The main data file (%s) does not pass its own rules: %s."
                            % (main_copy, _reason(error)))
            # Still read it, so the other checks can say more than one thing is wrong.
            try:
                parsed = json.loads(main_bytes.decode("utf-8"))
                state["feed"] = parsed if isinstance(parsed, dict) else None
            except (UnicodeDecodeError, ValueError):
                state["feed"] = None
    section("the data file follows its own rules", feed_follows_its_rules)

    feed = state["feed"]
    day = feed.get("run_date_ist") if feed else None
    state["day"] = day if isinstance(day, str) and DAY.match(day) else None

    def feed_copies_agree():
        for relative in FEED_COPIES[1:]:
            other = _read(root, relative)
            if other is None:
                problems.append("The copy of the data file %s is missing." % relative)
            elif main_bytes is not None and other != main_bytes:
                problems.append("The copy of the data file %s is not the same as %s."
                                % (relative, main_copy))
        if feed is None:
            return
        if state["day"] is None:
            problems.append("The data file does not say which day it is for.")
            return
        dated = "%s/%s.json" % (DATED_FEED_FOLDER, state["day"])
        dated_bytes = _read(root, dated)
        if dated_bytes is None:
            problems.append("The dated copy of the data file is missing (%s)." % dated)
        elif dated_bytes != main_bytes:
            problems.append("The dated copy of the data file (%s) is not the same as %s."
                            % (dated, main_copy))
    section("the three copies of the data file, and the dated copy, are identical",
            feed_copies_agree)

    def status_belongs_to_the_feed():
        status_bytes = _read(root, STATUS_COPIES[0])
        status = _json_object(status_bytes, "The status file (%s)" % STATUS_COPIES[0], problems)
        state["status"] = status
        other = _read(root, STATUS_COPIES[1])
        if other is None:
            problems.append("The copy of the status file %s is missing." % STATUS_COPIES[1])
        elif status_bytes is not None and other != status_bytes:
            problems.append("The copy of the status file %s is not the same as %s."
                            % (STATUS_COPIES[1], STATUS_COPIES[0]))
        if status is None:
            return
        if status.get("status") == "failed":
            problems.append("The status file says the run failed, so it must not be published.")
        if feed is not None:
            feed_time, status_time = feed.get("as_of_ist"), status.get("as_of_ist")
            if not isinstance(feed_time, str) or not isinstance(status_time, str):
                problems.append("The data file or the status file has no collection time, so they "
                                "cannot be matched to one run.")
            elif feed_time != status_time:
                problems.append("The data file and the status file come from different runs "
                                "(data file %s, status file %s)." % (feed_time, status_time))
        if state["day"] is not None:
            health = "%s/%s.json" % (DATED_HEALTH_FOLDER, state["day"])
            health_bytes = _read(root, health)
            if health_bytes is None:
                problems.append("The dated health report is missing (%s)." % health)
            elif status_bytes is not None and health_bytes != status_bytes:
                problems.append("The dated health report (%s) is not the same as the status file."
                                % health)
    section("the status file matches its copy, is not a failure, and comes from the same run "
            "as the data file", status_belongs_to_the_feed)

    def history_copies_agree():
        source = root / HISTORY_SOURCE
        if not source.is_dir():
            return
        expected = _folder_files(source)
        for target in HISTORY_COPIES:
            folder = root / target
            actual = _folder_files(folder) if folder.is_dir() else {}
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            different = sorted(name for name in expected if name in actual
                               and actual[name] != expected[name])
            if missing or extra or different:
                parts = []
                if missing:
                    parts.append("missing: " + _names(missing))
                if different:
                    parts.append("different: " + _names(different))
                if extra:
                    parts.append("not in %s: %s" % (HISTORY_SOURCE, _names(extra)))
                problems.append("The history copy %s does not match %s (%s)."
                                % (target, HISTORY_SOURCE, "; ".join(parts)))
    section("the history folders on the website match data/history/v1", history_copies_agree)

    return problems, passed


def check(root=CODE_ROOT):
    """Just the list of problems (empty means the files belong together)."""
    return run_checks(root)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(CODE_ROOT),
                        help="the repository folder to check (default: this repository)")
    args = parser.parse_args(argv)
    problems, passed = run_checks(args.root)
    if problems:
        print("The files about to be published do not belong together (%d problem%s):"
              % (len(problems), "" if len(problems) == 1 else "s"))
        for problem in problems:
            print(" - " + problem)
        return 1
    print("The files about to be published belong together. Checked:")
    for line in passed:
        print(" - " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
