#!/usr/bin/env bash
# Save newly collected data into the repository and publish it.
# - Only machine-made data files are ever committed (never code or settings).
# - If another update landed first, it tries again (up to 4 times).
set -euo pipefail

MESSAGE="${1:-research: publish sourced money-flow snapshot}"
PATHS=(data briefs reports docs/feed docs/status.json docs/history frontend)

git config user.name "money-flow-bot"
git config user.email "money-flow-bot@users.noreply.github.com"

existing=()
for p in "${PATHS[@]}"; do
  if [ -e "$p" ]; then existing+=("$p"); fi
done
git add -A -- "${existing[@]}"

if git diff --cached --quiet; then
  echo "Nothing new to publish."
  exit 0
fi
git commit -m "$MESSAGE"

for attempt in 1 2 3 4; do
  strategy=""
  if [ "$attempt" -ge 3 ]; then
    strategy="-X theirs"   # after repeated clashes, keep the freshly collected files
  fi
  # shellcheck disable=SC2086
  if git pull --rebase --autostash $strategy origin main && git push origin HEAD:main; then
    echo "Published on attempt ${attempt}."
    exit 0
  fi
  echo "Publish attempt ${attempt} did not go through; trying again shortly."
  git rebase --abort 2>/dev/null || true
  sleep $((attempt * 5))
done
echo "Could not publish after 4 attempts." >&2
exit 1
