"""The last look before publishing: do the files about to go live belong together?"""
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

import backend.run_daily as engine

ROOT = Path(__file__).resolve().parent.parent


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = load_script("check_published_data")
sync_site = load_script("sync_site")


def put(folder, relative, text):
    path = Path(folder) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def test_a_healthy_set_of_files_passes(tmp_path, published_tree, capsys):
    published_tree(tmp_path)
    assert checker.check(tmp_path) == []
    assert checker.main(["--root", str(tmp_path)]) == 0
    assert "belong together" in capsys.readouterr().out


def test_it_changes_nothing(tmp_path, published_tree):
    published_tree(tmp_path)
    before = snapshot(tmp_path)
    checker.check(tmp_path)
    checker.main(["--root", str(tmp_path)])
    assert snapshot(tmp_path) == before


def test_a_repository_without_history_folders_is_fine(tmp_path, published_tree):
    published_tree(tmp_path)
    for folder in ("data/history", "docs/history", "frontend/history"):
        for item in sorted((tmp_path / folder).rglob("*"), reverse=True):
            item.unlink() if item.is_file() else item.rmdir()
        (tmp_path / folder).rmdir()
    assert checker.check(tmp_path) == []


def test_the_same_change_everywhere_still_passes(tmp_path, published_tree):
    """A new run replaces every copy together; that must never look like a problem."""
    published_tree(tmp_path, day="2026-11-23", stamp="2026-11-23T16:10:42+05:30")
    published_tree(tmp_path, day="2026-11-24", stamp="2026-11-24T07:40:00+05:30")
    assert checker.check(tmp_path) == []


# ------------------------------------------------------------------ one thing wrong at a time

def damage_the_feed_everywhere(tmp_path):
    """The feed breaks its own rules, but all copies agree (so only the rules check can see it)."""
    feed = json.loads((tmp_path / "data/feed/v1/latest.json").read_text())
    feed["score"] = 70
    text = json.dumps(feed, indent=2) + "\n"
    for relative in ("data/feed/v1/latest.json", "docs/feed/v1/latest.json",
                     "frontend/feed/v1/latest.json", "data/feed/v1/daily/2026-11-23.json"):
        put(tmp_path, relative, text)


def remove(tmp_path, relative):
    (tmp_path / relative).unlink()


CASES = [
    ("feed breaks its own rules", damage_the_feed_everywhere, "does not pass its own rules"),
    ("feed is not readable", lambda t: [put(t, r, "{not json") for r in (
        "data/feed/v1/latest.json", "docs/feed/v1/latest.json", "frontend/feed/v1/latest.json",
        "data/feed/v1/daily/2026-11-23.json")], "does not pass its own rules"),
    ("main feed missing", lambda t: remove(t, "data/feed/v1/latest.json"),
     "main data file is missing"),
    ("docs copy of the feed differs",
     lambda t: put(t, "docs/feed/v1/latest.json", "{}\n"),
     "docs/feed/v1/latest.json is not the same"),
    ("frontend copy of the feed is missing",
     lambda t: remove(t, "frontend/feed/v1/latest.json"),
     "frontend/feed/v1/latest.json is missing"),
    ("dated copy of the feed differs",
     lambda t: put(t, "data/feed/v1/daily/2026-11-23.json", "{}\n"),
     "dated copy of the data file (data/feed/v1/daily/2026-11-23.json) is not the same"),
    ("dated copy of the feed is missing",
     lambda t: remove(t, "data/feed/v1/daily/2026-11-23.json"),
     "dated copy of the data file is missing"),
    ("status copies differ",
     lambda t: put(t, "frontend/status.json", '{"status": "ok"}\n'),
     "frontend/status.json is not the same"),
    ("status file missing", lambda t: remove(t, "docs/status.json"),
     "status file (docs/status.json) is missing"),
    ("status file is not an object", lambda t: [put(t, r, "[]\n") for r in (
        "docs/status.json", "frontend/status.json", "data/health/2026-11-23.json")],
     "not the kind of file expected"),
    ("status says the run failed", lambda t: [put(t, r, json.dumps(
        {"as_of_ist": "2026-11-23T16:10:42+05:30", "status": "failed"})) for r in (
        "docs/status.json", "frontend/status.json", "data/health/2026-11-23.json")],
     "says the run failed"),
    ("status and feed from different runs", lambda t: [put(t, r, json.dumps(
        {"as_of_ist": "2026-11-23T09:01:44+05:30", "status": "ok"})) for r in (
        "docs/status.json", "frontend/status.json", "data/health/2026-11-23.json")],
     "come from different runs"),
    ("dated health report differs",
     lambda t: put(t, "data/health/2026-11-23.json", '{"status": "ok"}\n'),
     "dated health report (data/health/2026-11-23.json) is not the same"),
    ("dated health report missing", lambda t: remove(t, "data/health/2026-11-23.json"),
     "dated health report is missing"),
    ("history copy has a changed file",
     lambda t: put(t, "docs/history/v1/fred/DGS2.csv", "observation_date,DGS2\n2026-11-12,9.99\n"),
     "docs/history/v1 does not match data/history/v1 (different: fred/DGS2.csv)"),
    ("history copy lacks a file", lambda t: remove(t, "frontend/history/v1/manifest.json"),
     "frontend/history/v1 does not match data/history/v1 (missing: manifest.json)"),
    ("history copy has a leftover file",
     lambda t: put(t, "docs/history/v1/fred/OLD.csv", "x\n"),
     "not in data/history/v1: fred/OLD.csv"),
]


@pytest.mark.parametrize("what,damage,expected", CASES, ids=[c[0] for c in CASES])
def test_each_kind_of_mismatch_is_caught_in_plain_words(tmp_path, published_tree, what, damage, expected):
    published_tree(tmp_path)
    damage(tmp_path)
    problems = checker.check(tmp_path)
    assert any(expected in line for line in problems), problems
    assert checker.main(["--root", str(tmp_path)]) == 1


def test_it_reports_everything_wrong_not_just_the_first_thing(tmp_path, published_tree, capsys):
    published_tree(tmp_path)
    put(tmp_path, "docs/feed/v1/latest.json", "{}\n")
    put(tmp_path, "docs/history/v1/fred/OLD.csv", "x\n")
    assert checker.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "2 problems" in out
    assert "docs/feed/v1/latest.json" in out and "OLD.csv" in out


def test_many_history_differences_are_summarised(tmp_path, published_tree):
    published_tree(tmp_path)
    for number in range(8):
        put(tmp_path, "data/history/v1/fred/S%d.csv" % number, "a\n")
    (problem,) = [p for p in checker.check(tmp_path) if "history copy docs/history/v1" in p]
    assert "and 5 more" in problem


def test_a_hybrid_of_two_runs_is_caught_even_when_the_rules_pass(tmp_path, published_tree):
    """23 Nov in miniature: the data file is from one run, the status file from another."""
    published_tree(tmp_path, stamp="2026-11-23T09:01:44+05:30")
    newer = json.dumps({"as_of_ist": "2026-11-23T09:10:44+05:30", "status": "degraded"}) + "\n"
    for relative in ("docs/status.json", "frontend/status.json", "data/health/2026-11-23.json"):
        put(tmp_path, relative, newer)
    problems = checker.check(tmp_path)
    assert len(problems) == 1 and "different runs" in problems[0]


def test_the_tally_mistake_of_23_nov_is_caught(tmp_path, published_tree):
    """The real failure: a risk-on/risk-off tally that no longer matches the individual checks."""
    spec = importlib.util.spec_from_file_location("regime_helpers", ROOT / "tests" / "test_regime.py")
    regime_helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regime_helpers)
    block = regime_helpers.good()
    block["windows"]["week"]["tally"]["risk_on"] -= 1
    block["windows"]["week"]["tally"]["neutral"] += 1
    published_tree(tmp_path, regime=block)
    (problem,) = checker.check(tmp_path)
    assert "tally does not match the checks" in problem


# ------------------------------------------------------------------ the files it looks at are the right ones

def test_the_file_lists_match_what_the_website_sync_copies():
    pairs = {tuple(pair) for pair in sync_site.FILES}
    assert (checker.FEED_COPIES[1], checker.FEED_COPIES[2]) in pairs
    assert tuple(checker.STATUS_COPIES) in pairs
    assert checker.HISTORY_SOURCE == sync_site.HISTORY_SOURCE
    assert tuple(checker.HISTORY_COPIES) == tuple(sync_site.HISTORY_COPIES)


def test_the_file_lists_match_what_a_daily_run_writes():
    written = inspect.getsource(engine.publish)
    for relative in (checker.FEED_COPIES[0], checker.FEED_COPIES[1], checker.STATUS_COPIES[0],
                     checker.DATED_FEED_FOLDER + "/", checker.DATED_HEALTH_FOLDER + "/"):
        assert relative in written, relative


def test_it_runs_as_a_plain_command(tmp_path, published_tree):
    published_tree(tmp_path)
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_published_data.py"),
                          "--root", str(tmp_path)], capture_output=True, text=True)
    assert ran.returncode == 0 and "belong together" in ran.stdout
    (tmp_path / "docs/feed/v1/latest.json").write_text("{}\n")
    ran = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_published_data.py"),
                          "--root", str(tmp_path)], capture_output=True, text=True)
    assert ran.returncode == 1 and "do not belong together" in ran.stdout


def test_the_checked_in_files_pass_the_check():
    """The repository as it stands must itself be publishable."""
    assert checker.check(ROOT) == []
