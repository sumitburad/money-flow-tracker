# Global Money-Flow Monitor — Operator Runbook

Plain-language steps for the owner are in `START_HERE.md` at the repository root. This page is the technical companion.

## Normal operation
- `Daily money-flow refresh` (`.github/workflows/daily.yml`) runs from schedules at 02:07 and 13:37 UTC (07:37 and 19:07 IST), every day. Backup schedules at 04:37 and 16:07 UTC (10:07 and 21:37 IST) run only if `docs/status.json` does not already show a complete snapshot for that morning or evening session (`scripts/should_run.py`). A skipped backup still costs about one billed minute.
- **Run workflow** (workflow_dispatch) starts a run by hand. A manual run always runs. A push or merge to `main` does not start a run.
- Steps: gate, collect (up to 3 whole attempts, 60 s and 120 s apart), validate the feed, top up history (`--mode update`, may fail without failing the run), sync the dashboard files, commit and push (up to 4 attempts), write a plain-language run summary, upload artifacts on failure.
- GitHub's scheduling is best-effort. Use the feed's **actual collection time** (`generated_at_utc`, and `collected_at_utc` per item), never the scheduled time, for freshness. The dashboard banner is green to 20 hours, amber to 48 hours, red beyond that.
- PRs run `Global monitor checks` (`.github/workflows/tests.yml`).
- `Load official history` (`.github/workflows/history.yml`) is manual only. It loads or repairs `data/history/v1/`.

## Data sources and keys
- FRED: if the Actions secret `FRED_API_KEY` is set, the FRED API is tried first, then the keyless CSV, then the DBnomics mirror. The key is redacted from any error text and scrubbed from every JSON file written. It must never be committed, printed or placed in `status.json`.
- Every outbound request uses the shared client in `backend/net.py`: 3 attempts with growing waits, `Retry-After` honoured, and a per-host breaker that stops retrying a host after two fully failed calls in the same run.
- `docs/status.json` carries `run_slot` (morning/evening/backup/manual), `completed_at_utc`, `needs_retry` and `official_source_problems`. If an official source keeps failing, `needs_retry` stays true and the backup slots will keep running, which adds billed minutes (my estimate: roughly 12 a day) until the source recovers.

## Actions minutes (cost)
GitHub Free personal accounts include 2,000 Actions minutes a month for private repositories, and every job is rounded up to a whole minute (GitHub Docs, checked 22 November 2026). My estimate is about 10 to 15 minutes a day for two main runs plus two mostly skipped backups, so roughly 300 to 450 minutes a month. It is an estimate, because the workflow has not yet run on GitHub. Check the real figure on GitHub's billing page after the first week. Each job also has a hard time limit (25 minutes for the daily refresh, 20 for history), which caps the cost of a stuck run.

## On failures
1. Open the repo Actions page and the failed run. The run summary box lists, in plain words, status, collection time, current items, macro series and problems. Do not infer completion from a scheduled trigger.
2. Check `docs/status.json` and `data/health/YYYY-MM-DD.json`. The latter contains missing universe IDs and categorical provider errors.
3. If all inputs failed, no new feed or label is produced. The previous `latest.json` remains, clearly dated, and the dashboard banner turns amber, then red.
4. A price-only failure should not be covered by a macro figure. Missing direct fund flow always caps the related asset at Neutral/Mixed.
5. On unofficial price-provider blocks, **do not** bypass captchas, authentication or terms. Use authorized alternate histories for private research; do not copy them into the repo.
6. Review daily `data/feed/v1/latest.json`, and compare stale dates with official market calendars. Saturday morning may contain Friday's U.S. close; Indian exchanges can be shut. Note that `data/feed/v1/daily/YYYY-MM-DD.json` is overwritten by a later run on the same IST date.
7. Use a reviewed PR and green tests to change rules. Never change past archived labels in order to improve historical results.

## Official history (`data/history/v1/`)
- Start date 2021-11-22, set in `config/history.yaml`. Official-source data only; no price data. Plain CSV per series plus `manifest.json`.
- `available_from_estimate` is a conservative publication-lag estimate, not a vintage date. Values are the current vintage; later revisions are not tracked. Backtests must filter on this column.
- Manifest statuses: `ok`; `kept_previous` (today's download failed, the earlier good file is still there); `missing` (never loaded); `no_matching_contract` (CFTC data was fetched but no contract matched the name pattern).
- If a CFTC market shows `no_matching_contract`, open `data/history/v1/cftc/contracts_seen.json`, find the real contract name, and correct `CFTC_MARKETS` in `backend/advanced_sources.py`. The 10-year note contract now appears to be named like "UST 10Y NOTE", which the current pattern probably misses. This is unverified until the first live run.
- Run **Load official history** again to repair gaps. It is safe to repeat; it rewrites only files whose content changed.

## Security and reuse
The repository is **private** (checked 22 November 2026), but write as if it could become public. Never commit API keys, SSH private keys, OAuth secrets, broker tokens, account identifiers, orders, proprietary historical price tables or non-public research outputs. Existing EC2 read-only deployment and broker credentials must stay isolated in `india-algo-trader`.

Only the research feed and history files are intended for cross-project consumption. Use `backend/feed_contract.py` for validation and retain each dated snapshot and fetch timestamp. The feed contract is additive only: `collected_at_utc` is an optional per-item field and the schema stays `1.0`. A paper/live trading system needs a separate source-authority and timing approval before a signal is admitted to decision logic.

## Manual acceptance before wider circulation
- Check source terms and 95% coverage; log unresolved symbols.
- Compare 10 historical labels with blinded manual reviews.
- Independently review 50 event classifications and their observed confirmation.
- Verify all narrative claims are traceable to source data or headlines.
- Review 4–6 weeks of shadow runs and test hindsight/look-ahead barriers.
- Human-review all LinkedIn/X text before posting. Nothing auto-posts.
