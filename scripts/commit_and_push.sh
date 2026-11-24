#!/usr/bin/env bash
# Publish this run's results to the main branch, safely.
#
#   1. Save the run's files as one commit.
#   2. Look at what is on GitHub's main branch right now.
#   3. If somebody else published meanwhile, carry on ONLY when they changed completely
#      different files. If both changed the same file, stop and publish nothing: a
#      half-and-half mix of two runs is worse than one missing refresh.
#      (This replaces the old "merge and let the newer side win" behaviour, which on
#      23 Nov 2026 produced a data file that failed its own rules.)
#   4. Check that the files about to go live belong together
#      (scripts/check_published_data.py). If not, stop and publish nothing.
#   5. Push. If GitHub says someone got in first, go back to step 2 (up to 4 tries).
#
# Exit codes: 0 = published, or nothing to publish
#             1 = could not publish (GitHub unreachable or busy); the run can be repeated
#             2 = stopped on purpose to protect the dashboard; the previous good data stays
#
# Optional settings, used by the tests:
#   PUBLISH_CHECK          command to run instead of scripts/check_published_data.py
#   PUBLISH_PAUSE_SECONDS  base wait between tries (default 5; the waits are 1x, 2x, 3x)
set -euo pipefail

MESSAGE="${1:-research: publish sourced money-flow snapshot}"
PATHS=(data briefs reports docs/feed docs/status.json docs/history frontend)
MAX_ATTEMPTS=4
PAUSE_SECONDS="${PUBLISH_PAUSE_SECONDS:-5}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(git rev-parse --show-toplevel)"
ROOT="$(pwd)"

run_check() {
  if [ -n "${PUBLISH_CHECK:-}" ]; then
    bash -c "$PUBLISH_CHECK"
  else
    python3 "$HERE/check_published_data.py" --root "$ROOT"
  fi
}

pause() {  # pause <attempt number>: wait a little longer after each failed try
  if [ "$1" -lt "$MAX_ATTEMPTS" ]; then
    sleep $(( $1 * PAUSE_SECONDS ))
  fi
}

stop_for_safety() {  # stop_for_safety <what happened> [details]
  local headline="$1" details="${2:-}"
  echo "::error title=Publishing stopped to protect the dashboard::${headline}"
  echo "${headline}" >&2
  if [ -n "$details" ]; then
    echo "${details}" >&2
  fi
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "### Publishing was stopped on purpose"
      echo
      echo "${headline}"
      echo
      echo "Nothing was published, so the dashboard still shows the last good data."
      echo "The next scheduled refresh, or a click on Run workflow, will try again."
      if [ -n "$details" ]; then
        echo
        echo '```'
        echo "${details}"
        echo '```'
      fi
    } >> "$GITHUB_STEP_SUMMARY"
  fi
  exit 2
}

git config user.name "money-flow-bot"
git config user.email "money-flow-bot@users.noreply.github.com"

existing=()
for p in "${PATHS[@]}"; do
  if [ -e "$p" ]; then
    existing+=("$p")
  fi
done
git add -A -- "${existing[@]}"
if git diff --cached --quiet; then
  echo "Nothing new to publish."
  exit 0
fi

START="$(git rev-parse HEAD)"   # the version this run started from
git commit -m "$MESSAGE"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "Publish attempt ${attempt} of ${MAX_ATTEMPTS}."

  if ! git fetch --quiet origin "+refs/heads/main:refs/remotes/origin/main"; then
    echo "Could not reach GitHub to see what is on the main branch; trying again shortly."
    pause "$attempt"
    continue
  fi

  # The run must have started from something already published, so that the commit made
  # above is the only thing waiting to go out (never a side branch's unfinished work).
  if ! git merge-base --is-ancestor "$START" origin/main; then
    stop_for_safety "This run did not start from the main branch's published version, so it published nothing."
  fi

  if ! git merge-base --is-ancestor origin/main HEAD; then
    # Somebody published while this run was working.
    base="$(git merge-base HEAD origin/main)"
    ours="$(git diff --name-only --no-renames "$base" HEAD | sort)"
    theirs="$(git diff --name-only --no-renames "$base" origin/main | sort)"
    shared="$(comm -12 <(printf '%s\n' "$ours") <(printf '%s\n' "$theirs"))"
    if [ -n "$shared" ]; then
      count="$(printf '%s\n' "$shared" | wc -l | tr -d ' ')"
      stop_for_safety "Another update reached the main branch while this run was working, and it changed ${count} of the same file(s) as this run. Mixing the two could leave a half-and-half data file, so this run published nothing." "Files changed by both:
${shared}"
    fi
    echo "The main branch moved on, but only in other files. Carrying on from the newer version."
    if ! git rebase --autostash origin/main; then
      git rebase --abort 2>/dev/null || true
      echo "Could not carry on from the newer version; trying again shortly."
      pause "$attempt"
      continue
    fi
  fi

  # A last look at exactly what is about to be pushed.
  if ! check_output="$(run_check 2>&1)"; then
    stop_for_safety "The final check found that the files about to go live do not belong together, so this run published nothing." "${check_output}"
  fi
  echo "${check_output}"

  if git push origin HEAD:main; then
    echo "Published on attempt ${attempt}."
    exit 0
  fi
  echo "GitHub did not accept the push (someone may have published first); trying again shortly."
  pause "$attempt"
done

echo "Could not publish after ${MAX_ATTEMPTS} attempts." >&2
exit 1
