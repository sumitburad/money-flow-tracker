"""Backup-slot decisions for the daily refresh."""
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "should_run", Path(__file__).resolve().parent.parent / "scripts" / "should_run.py")
should_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(should_run)

decide = should_run.decide
MORNING_PRIMARY, MORNING_BACKUP = "7 2 * * *", "37 4 * * *"
EVENING_PRIMARY, EVENING_BACKUP = "37 13 * * *", "7 16 * * *"


def at(text):  # UTC time
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def status(ist_time, state="degraded", needs_retry=False, slot="primary"):
    return {"as_of_ist": ist_time + "+05:30", "status": state,
            "needs_retry": needs_retry, "run_slot": slot}


def test_manual_click_always_runs():
    run, slot, _ = decide("workflow_dispatch", "", status("2026-11-23T07:40:00"), at("2026-11-23T05:00:00"))
    assert run and slot == "manual"


def test_primary_slots_always_run():
    for cron in (MORNING_PRIMARY, EVENING_PRIMARY):
        run, slot, _ = decide("schedule", cron, status("2026-11-23T07:40:00"), at("2026-11-23T02:07:00"))
        assert run and slot == "primary"


def test_morning_backup_skips_after_a_good_morning_run():
    run, slot, reason = decide("schedule", MORNING_BACKUP, status("2026-11-23T07:40:00"),
                               at("2026-11-23T04:37:00"))
    assert not run and slot == "backup" and "already worked" in reason


def test_morning_backup_runs_when_morning_run_is_missing():
    # latest snapshot is from yesterday evening
    run, _, _ = decide("schedule", MORNING_BACKUP, status("2026-11-22T19:10:00"),
                       at("2026-11-23T04:37:00"))
    assert run


def test_morning_backup_runs_when_no_status_file():
    assert decide("schedule", MORNING_BACKUP, None, at("2026-11-23T04:37:00"))[0]


def test_backup_does_not_count_a_failed_status_as_success():
    run, _, _ = decide("schedule", MORNING_BACKUP,
                       status("2026-11-23T07:40:00", state="failed"), at("2026-11-23T04:37:00"))
    assert run


def test_backup_retries_once_when_primary_needed_a_retry():
    run, _, reason = decide("schedule", MORNING_BACKUP,
                            status("2026-11-23T07:40:00", needs_retry=True, slot="primary"),
                            at("2026-11-23T04:37:00"))
    assert run and "retry" in reason


def test_backup_does_not_repeat_forever():
    run, _, _ = decide("schedule", MORNING_BACKUP,
                       status("2026-11-23T10:10:00", needs_retry=True, slot="backup"),
                       at("2026-11-23T04:50:00"))
    assert not run


def test_evening_backup_looks_only_at_the_evening_session():
    # a good morning run must NOT excuse a missing evening run
    run, _, _ = decide("schedule", EVENING_BACKUP, status("2026-11-23T07:40:00"),
                       at("2026-11-23T16:07:00"))
    assert run
    run, _, _ = decide("schedule", EVENING_BACKUP, status("2026-11-23T19:12:00"),
                       at("2026-11-23T16:07:00"))
    assert not run


def test_unknown_schedule_runs_to_be_safe():
    assert decide("schedule", "1 1 * * *", status("2026-11-23T07:40:00"), at("2026-11-23T04:37:00"))[0]


def test_cli_writes_github_outputs(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    summary = tmp_path / "summary.md"
    path = tmp_path / "status.json"
    path.write_text(json.dumps(status("2026-11-23T07:40:00")))
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    should_run.main(["--event", "schedule", "--schedule", MORNING_BACKUP,
                     "--status", str(path), "--now", "2026-11-23T04:37:00+00:00"])
    assert out.read_text() == "run=false\nslot=backup\n"
    assert "Skipped." in summary.read_text()
    assert capsys.readouterr().out.startswith("SKIP:")


def test_schedules_match_the_workflow_file():
    text = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "daily.yml").read_text()
    for cron in (MORNING_PRIMARY, MORNING_BACKUP, EVENING_PRIMARY, EVENING_BACKUP):
        assert '"%s"' % cron in text, cron
