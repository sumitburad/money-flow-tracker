"""scripts/commit_and_push.sh, tried against real throw-away git repositories.

A bare folder plays GitHub ("origin") and every clone plays one workflow run. Nothing here
touches the network or the real repository.

The story these tests keep safe: on 23 Nov 2026 two runs overlapped. The second one carried
on from an old copy of the repository, git merged its files with the first run's hunk by hunk,
and the result was a data file that mixed the two runs and failed its own rules.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "commit_and_push.sh"
WORKFLOWS = ROOT / ".github" / "workflows"

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None,
                                reason="these tests need git and bash")

FEED = "data/feed/v1/latest.json"
FEED_COPIES = (FEED, "docs/feed/v1/latest.json", "frontend/feed/v1/latest.json")
REAL_CHECK = object()  # "use the real scripts/check_published_data.py"


def feed_text(week="risk_on", month="risk_on"):
    """A data file with the week reading near the top and the month reading near the bottom,
    so two runs that change one each are different hunks that git would merge without a word."""
    lines = ["{", '  "week": "%s",' % week]
    lines += ['  "filler_%d": %d,' % (n, n) for n in range(12)]
    lines += ['  "month": "%s"' % month, "}"]
    return "\n".join(lines) + "\n"


START_FILES = {
    FEED: feed_text(), "docs/feed/v1/latest.json": feed_text(),
    "frontend/feed/v1/latest.json": feed_text(),
    "docs/status.json": '{"status": "ok"}\n', "frontend/status.json": '{"status": "ok"}\n',
    "data/raw/2026-11-22/old.json": "{}\n",
    "data/reviews/weekly/w0.json": "{}\n",
    "backend/code.py": "print('v1')\n",
    "docs/index.html": "<html>v1</html>\n", "frontend/index.html": "<html>v1</html>\n",
}


class World:
    """GitHub (a bare repository) plus any number of workflow runs (clones of it)."""

    def __init__(self, base, start=None):
        self.base = Path(base)
        self.home = self.base / "home"
        self.home.mkdir()
        self.origin = self.base / "origin.git"
        self.git(self.base, "init", "--bare", "--quiet", str(self.origin))
        self.git(self.origin, "symbolic-ref", "HEAD", "refs/heads/main")
        seed = self.base / "seed"
        self.git(self.base, "clone", "--quiet", str(self.origin), str(seed))
        self.git(seed, "checkout", "--quiet", "-B", "main")
        if start:
            start(seed)
        else:
            for relative, text in START_FILES.items():
                self.write(seed, relative, text)
        self.git(seed, "add", "-A")
        self.git(seed, "commit", "--quiet", "-m", "start")
        self.git(seed, "push", "--quiet", "origin", "HEAD:main")

    def env(self, **extra):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "PUBLISH_PAUSE_SECONDS": "0",
               "GIT_AUTHOR_NAME": "Someone", "GIT_AUTHOR_EMAIL": "someone@example.com",
               "GIT_COMMITTER_NAME": "Someone", "GIT_COMMITTER_EMAIL": "someone@example.com"}
        env.update(extra)
        return env

    def git(self, folder, *args, check=True):
        done = subprocess.run(["git", *args], cwd=folder, env=self.env(),
                              capture_output=True, text=True)
        if check and done.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), done.stderr))
        return done.stdout

    def clone(self, name):
        folder = self.base / name
        self.git(self.base, "clone", "--quiet", str(self.origin), str(folder))
        return folder

    @staticmethod
    def write(folder, relative, text):
        path = Path(folder) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def land(self, folder, relative, text, message="a change lands"):
        """Someone commits and pushes straight to main (like a merged pull request)."""
        self.git(folder, "pull", "--quiet", "--rebase", "origin", "main")
        self.write(folder, relative, text)
        self.git(folder, "add", "-A")
        self.git(folder, "commit", "--quiet", "-m", message)
        self.git(folder, "push", "--quiet", "origin", "HEAD:main")

    def publish(self, folder, message="research: test publish", check="true", summary=None, **extra):
        env = self.env(**extra)
        if check is not REAL_CHECK:
            env["PUBLISH_CHECK"] = check
        if summary is not None:
            env["GITHUB_STEP_SUMMARY"] = str(summary)
        return subprocess.run(["bash", str(SCRIPT), message], cwd=folder, env=env,
                              capture_output=True, text=True, timeout=120)

    def on_main(self, relative):
        return self.git(self.origin, "show", "main:" + relative)

    def main_tip(self):
        return self.git(self.origin, "rev-parse", "main").strip()

    def main_log(self):
        return self.git(self.origin, "log", "--format=%s", "main").split("\n")[:-1]

    def rebase_in_progress(self, folder):
        git_dir = Path(folder) / ".git"
        return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def a_run_that_changes(world, name, **settings):
    """A run that rewrote the data file (all three copies) with the given week/month readings."""
    folder = world.clone(name)
    for relative in FEED_COPIES:
        world.write(folder, relative, feed_text(**settings))
    return folder


# ---------------------------------------------------------------------------------- the normal day

def test_a_normal_run_publishes(world):
    run = a_run_that_changes(world, "run", week="risk_off")
    done = world.publish(run, message="research: today")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "Published on attempt 1" in done.stdout
    assert world.main_log()[0] == "research: today"
    assert world.on_main(FEED) == feed_text(week="risk_off")


def test_a_run_with_nothing_new_publishes_nothing_and_skips_the_check(world, tmp_path):
    log = tmp_path / "check.log"
    run = world.clone("run")
    done = world.publish(run, check='echo ran >> "%s"' % log)
    assert done.returncode == 0 and "Nothing new to publish" in done.stdout
    assert world.main_log() == ["start"]
    assert not log.exists()


def test_only_the_published_folders_are_committed(world):
    run = a_run_that_changes(world, "run", week="risk_off")
    world.write(run, "backend/code.py", "print('edited in the middle of a run')\n")
    world.write(run, "notes.txt", "scratch\n")
    done = world.publish(run)
    assert done.returncode == 0, done.stdout + done.stderr
    assert world.on_main("backend/code.py") == "print('v1')\n"
    assert world.git(world.origin, "ls-tree", "-r", "--name-only", "main", "notes.txt") == ""


# ---------------------------------------------------------------------------------- somebody else published first

def test_a_code_only_change_that_landed_meanwhile_is_carried_over(world):
    run = a_run_that_changes(world, "run", week="risk_off")
    world.land(world.clone("merger"), "backend/code.py", "print('v2')\n", "a pull request is merged")
    done = world.publish(run)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "only in other files" in done.stdout
    assert world.on_main("backend/code.py") == "print('v2')\n"
    assert world.on_main(FEED) == feed_text(week="risk_off")
    assert world.main_log()[:2] == ["research: test publish", "a pull request is merged"]


def test_two_runs_that_changed_different_files_both_get_published(world):
    run_a = world.clone("run_a")
    world.write(run_a, "data/raw/2026-11-23/a.json", '{"run": "a"}\n')
    run_b = world.clone("run_b")
    world.write(run_b, "data/reviews/weekly/w1.json", '{"run": "b"}\n')
    assert world.publish(run_b, message="run b").returncode == 0
    done = world.publish(run_a, message="run a")
    assert done.returncode == 0, done.stdout + done.stderr
    assert world.on_main("data/raw/2026-11-23/a.json") == '{"run": "a"}\n'
    assert world.on_main("data/reviews/weekly/w1.json") == '{"run": "b"}\n'
    assert world.main_log()[:2] == ["run a", "run b"]


def test_23_nov_two_runs_that_changed_the_same_file_in_different_places_are_not_mixed(world, tmp_path):
    """Git alone would merge these without a conflict and make a data file that is half of each."""
    run_a = a_run_that_changes(world, "run_a", week="risk_off")      # changes the week reading
    run_b = a_run_that_changes(world, "run_b", month="neutral")      # changes the month reading
    assert world.publish(run_b, message="run b").returncode == 0
    published = world.main_tip()
    summary = tmp_path / "summary.md"

    done = world.publish(run_a, message="run a", summary=summary)

    assert done.returncode == 2, done.stdout + done.stderr
    assert world.main_tip() == published                              # nothing was pushed
    for relative in FEED_COPIES:
        assert world.on_main(relative) == feed_text(month="neutral")  # still exactly run b's file
    assert FEED in done.stderr and "published nothing" in done.stderr
    assert "Publishing was stopped on purpose" in summary.read_text()
    assert not world.rebase_in_progress(run_a)                        # the run's folder is left tidy


def test_two_runs_that_changed_the_same_line_are_not_mixed_either(world):
    run_a = a_run_that_changes(world, "run_a", week="risk_off")
    run_b = a_run_that_changes(world, "run_b", week="neutral")
    assert world.publish(run_b).returncode == 0
    published = world.main_tip()
    done = world.publish(run_a)
    assert done.returncode == 2
    assert world.main_tip() == published
    assert world.on_main(FEED) == feed_text(week="neutral")


def test_it_names_the_files_both_runs_changed(world, tmp_path):
    run_a = a_run_that_changes(world, "run_a", week="risk_off")
    world.write(run_a, "data/raw/2026-11-23/only_a.json", "{}\n")
    world.land(world.clone("other"), "docs/feed/v1/latest.json", feed_text(month="neutral"))
    done = world.publish(run_a, summary=tmp_path / "s.md")
    assert done.returncode == 2
    assert "docs/feed/v1/latest.json" in done.stderr
    assert "only_a.json" not in done.stderr.split("Files changed by both:")[1]


def test_a_run_that_did_not_start_from_published_work_is_refused(world):
    """For instance a run started from a side branch that has unfinished commits of its own."""
    run = world.clone("run")
    world.write(run, "backend/code.py", "print('unfinished')\n")
    world.git(run, "commit", "--quiet", "-am", "unfinished work, never published")
    world.write(run, "data/raw/2026-11-23/a.json", "{}\n")
    done = world.publish(run)
    assert done.returncode == 2
    assert "did not start from" in done.stderr
    assert world.main_log() == ["start"]


def test_a_file_deleted_by_one_run_and_edited_by_another_is_refused(world):
    run_a = world.clone("run_a")
    world.write(run_a, "data/raw/2026-11-22/old.json", '{"edited": true}\n')
    run_b = world.clone("run_b")
    (run_b / "data/raw/2026-11-22/old.json").unlink()
    assert world.publish(run_b).returncode == 0
    published = world.main_tip()
    assert world.publish(run_a).returncode == 2
    assert world.main_tip() == published


def test_other_unsaved_changes_in_the_folder_survive_a_catch_up(world):
    run = world.clone("run")
    world.write(run, "data/raw/2026-11-23/a.json", "{}\n")
    world.write(run, "backend/code.py", "print('local edit that is not part of the publish')\n")
    world.land(world.clone("merger"), "backend/other.py", "print('x')\n")
    done = world.publish(run)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (run / "backend/code.py").read_text() == "print('local edit that is not part of the publish')\n"
    assert world.on_main("backend/code.py") == "print('v1')\n"
    assert world.git(run, "stash", "list") == ""


def test_it_works_when_started_from_a_subfolder(world):
    run = a_run_that_changes(world, "run", week="risk_off")
    done = world.publish(run / "docs")
    assert done.returncode == 0, done.stdout + done.stderr
    assert world.on_main(FEED) == feed_text(week="risk_off")


def test_a_push_that_already_reached_github_is_not_an_error(world):
    """If an earlier push got through but its reply was lost, going round again must end well."""
    run = a_run_that_changes(world, "run", week="risk_off")
    done = world.publish(run, check="git push -q origin HEAD:main")   # the 'earlier push'
    assert done.returncode == 0, done.stdout + done.stderr
    assert world.main_log() == ["research: test publish", "start"]


# ---------------------------------------------------------------------------------- the last look

def test_a_failing_check_stops_the_publish_and_says_why(world, tmp_path):
    run = a_run_that_changes(world, "run", week="risk_off")
    summary = tmp_path / "summary.md"
    done = world.publish(run, check="echo 'the status file is from another run'; exit 1", summary=summary)
    assert done.returncode == 2
    assert world.main_log() == ["start"]
    assert "the status file is from another run" in done.stderr
    text = summary.read_text()
    assert "stopped on purpose" in text and "the status file is from another run" in text
    assert "last good data" in text


def test_the_check_looks_at_the_final_files_not_the_files_before_catching_up(world, tmp_path):
    """The check must see the merged result: it fails only if the carried-over change is present."""
    run = a_run_that_changes(world, "run", week="risk_off")
    world.land(world.clone("merger"), "backend/code.py", "print('v2')\n")
    done = world.publish(run, check="grep -q v2 backend/code.py && echo 'saw the newer code' && exit 1")
    assert done.returncode == 2 and "saw the newer code" in done.stderr


def _stub_that_lets_a_commit_land(world, tmp_path, other, fail_on_second_look=False):
    log = tmp_path / "check.log"
    stub = tmp_path / "stub_check.sh"
    second = ('if [ "$count" -ge 2 ]; then echo "second look failed"; exit 1; fi\n'
              if fail_on_second_look else "")
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'echo looked >> "%(log)s"\n'
        'count=$(wc -l < "%(log)s")\n'
        'if [ "$count" -eq 1 ]; then\n'          # first look: somebody publishes right now
        '  cd "%(other)s"\n'
        "  git pull -q --rebase origin main\n"
        '  echo "late" >> backend/code.py\n'
        '  git commit -q -am "late code change"\n'
        "  git push -q origin HEAD:main\n"
        "fi\n"
        "%(second)s"
        "exit 0\n" % {"log": log, "other": other, "second": second})
    return log, "bash %s" % stub


def test_a_change_landing_between_the_check_and_the_push_means_looking_again(world, tmp_path):
    run = a_run_that_changes(world, "run", week="risk_off")
    log, check = _stub_that_lets_a_commit_land(world, tmp_path, world.clone("late"))
    done = world.publish(run, check=check)
    assert done.returncode == 0, done.stdout + done.stderr
    assert log.read_text().count("looked") == 2            # checked again on the newer files
    assert "Publish attempt 2 of 4" in done.stdout and "Published on attempt 2" in done.stdout
    assert world.main_log()[:2] == ["research: test publish", "late code change"]


def test_if_the_second_look_fails_nothing_of_this_run_is_published(world, tmp_path):
    run = a_run_that_changes(world, "run", week="risk_off")
    _, check = _stub_that_lets_a_commit_land(world, tmp_path, world.clone("late"), fail_on_second_look=True)
    done = world.publish(run, check=check)
    assert done.returncode == 2
    assert world.main_log() == ["late code change", "start"]
    assert world.on_main(FEED) == feed_text()


def test_it_gives_up_after_four_tries_when_github_cannot_be_reached(world):
    run = a_run_that_changes(world, "run", week="risk_off")
    world.git(run, "remote", "set-url", "origin", str(world.base / "no-such-place.git"))
    done = world.publish(run)
    assert done.returncode == 1
    assert "Publish attempt 4 of 4" in done.stdout
    assert "Could not publish after 4 attempts" in done.stderr


# ---------------------------------------------------------------------------------- with the real checker

def healthy_start(published_tree):
    def start(seed):
        published_tree(seed, day="2026-11-22", stamp="2026-11-22T21:59:18+05:30")
    return start


def test_a_complete_update_passes_the_real_check_and_is_published(tmp_path, published_tree):
    world = World(tmp_path, start=healthy_start(published_tree))
    run = world.clone("run")
    published_tree(run, day="2026-11-23", stamp="2026-11-23T16:10:42+05:30")
    done = world.publish(run, check=REAL_CHECK)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "belong together" in done.stdout
    assert "2026-11-23T16:10:42+05:30" in world.on_main("docs/status.json")


def test_a_half_finished_update_is_stopped_by_the_real_check(tmp_path, published_tree):
    world = World(tmp_path, start=healthy_start(published_tree))
    run = world.clone("run")
    published_tree(run, day="2026-11-23", stamp="2026-11-23T16:10:42+05:30")
    # only the website copy of the status file was left from an older run
    world.write(run, "frontend/status.json", '{"as_of_ist": "2026-11-22T21:59:18+05:30"}\n')
    done = world.publish(run, check=REAL_CHECK)
    assert done.returncode == 2
    assert "frontend/status.json is not the same" in done.stderr
    assert world.main_log() == ["start"]


# ---------------------------------------------------------------------------------- the script and the workflows

def test_the_old_merge_and_let_the_newer_side_win_behaviour_is_gone():
    text = SCRIPT.read_text()
    for banned in ("-X theirs", "-Xtheirs", "--strategy-option", "pull --rebase"):
        assert banned not in text, banned


def test_the_script_is_executable_bash_that_parses():
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash")
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.parametrize("workflow", ["daily.yml", "history.yml"])
def test_the_publishing_workflows_start_from_the_newest_main(workflow):
    """A run that waited its turn must not start from the (old) commit that triggered it."""
    job = next(iter(yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"].values()))
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["ref"] == "main"
    assert checkout["with"]["fetch-depth"] == 0
    assert any("commit_and_push.sh" in step.get("run", "") for step in job["steps"])
