# Global Money-Flow Monitor — Operator Runbook

Plain-language steps for the owner are in `START_HERE.md` at the repository root. Links and steps for every free provider and key are in `docs/CONNECT_DATA_PROVIDERS.md`. This page is the technical companion.

## Normal operation
- `Daily money-flow refresh` (`.github/workflows/daily.yml`) runs from schedules at 02:07 and 13:37 UTC (07:37 and 19:07 IST), every day. Backup schedules at 04:37 and 16:07 UTC (10:07 and 21:37 IST) run only if `docs/status.json` does not already show a complete snapshot for that morning or evening session (`scripts/should_run.py`). A skipped backup still costs about one billed minute.
- **Run workflow** (workflow_dispatch) starts a run by hand. A manual run always runs. A push or merge to `main` does not start a run.
- Steps: gate, collect (up to 3 whole attempts, 60 s and 120 s apart), validate the feed, top up history (`--mode update`, may fail without failing the run), sync the dashboard files, commit and push (up to 4 attempts), write a plain-language run summary, upload artifacts on failure.
- GitHub's scheduling is best-effort. Use the feed's **actual collection time** (`generated_at_utc`, and `collected_at_utc` per item), never the scheduled time, for freshness. The dashboard banner is green to 20 hours, amber to 48 hours, red beyond that.
- PRs run `Global monitor checks` (`.github/workflows/tests.yml`).
- `Load official history` (`.github/workflows/history.yml`) is manual only. It loads or repairs `data/history/v1/`.

## Data sources and keys
- FRED: if the Actions secret `FRED_API_KEY` is set, the FRED API is tried first, then the keyless CSV, then the DBnomics mirror. The key is redacted from any error text and scrubbed from every JSON file written. It must never be committed, printed or placed in `status.json`.
- Groq and OpenRouter (optional secrets `GROQ_API_KEY` and `OPENROUTER_API_KEY`): Groq is tried first, then OpenRouter. They tag official headlines (up to 12 small requests, paced 8 seconds apart) and write the executive summary (1 request, plus one retry after a 429 answer that honours `Retry-After`). Groq's free plan allowed 30 requests a minute, 1,000 a day, 8,000 tokens a minute and 200,000 tokens a day (checked 22 November 2026). Model names are set in code (`backend/news_classifier.py`, `backend/exec_summary.py`) and listed in `config/models.yaml`. If a provider retires a model, the AI step falls back to rule-written text and says so; update the name in code.
- Every outbound request uses the shared client in `backend/net.py`: 3 attempts with growing waits, `Retry-After` honoured, and a per-host breaker that stops retrying a host after two fully failed calls in the same run.
- `docs/status.json` carries `run_slot` (morning/evening/backup/manual), `completed_at_utc`, `needs_retry` and `official_source_problems`. If an official source keeps failing, `needs_retry` stays true and the backup slots will keep running, which adds billed minutes (my estimate: roughly 12 a day) until the source recovers.

## Actions minutes (cost)
GitHub Free personal accounts include 2,000 Actions minutes a month for private repositories, and every job is rounded up to a whole minute (GitHub Docs, checked 22 November 2026). My estimate is about 10 to 15 minutes a day for two main runs plus two mostly skipped backups, so roughly 300 to 450 minutes a month. It is an estimate, because the workflow has not yet run on GitHub. Check the real figure on GitHub's billing page after the first week. Each job also has a hard time limit (25 minutes for the daily refresh, 20 for history), which caps the cost of a stuck run. The 8-second pacing between AI requests adds about 1.5 minutes to a run when a Groq key is set.

**Decision, 22 November 2026:** the free private-repository minutes for the month were used up, so the owner makes the repository public. Standard GitHub-hosted runners are free for public repositories, so the cost becomes zero. If the repository is kept private instead, minutes beyond the free allowance cost $0.006 a minute on the standard Linux runner, about $1.80 to $2.70 a month at the estimate above (GitHub Docs, checked 22 November 2026).

## Flow windows, rotation and executive summary (added 2026-11-22)
- `config/flow_windows.yaml` holds the windows, the flat bands, the session-close times, the maximum data age and the bucket list. `backend/flow_windows.py` computes a day, week and month signal per item from the daily bars already read in memory, and a rotation block per bucket. Only categories reach the feed (`flow_windows` per item and a top-level `rotation`). No price, volume or percentage is written anywhere. The rules are in `config/label_rules.md`.
- The newest bar is used only once its market session is over (`session_complete_after_utc`; 24-hour markets use the last full day). A morning run can therefore show Asian markets for the day just closed and the US market for the previous US day. That is expected.
- `backend/exec_summary.py` builds the dashboard's executive summary. The model sees a digest of categories and names only. Its answer is validated (fields, length, no digits, no advice words, no links, only known names); otherwise a rule-written summary is used. The feed's `executive_summary.method` is `ai_validated` or `rules_only`, and `human_review_required` is always true.
- Health: the run's health block carries `flow_windows` (how many items have a signal and how many lack volume) and `executive_summary` (providers tried, answers rejected, reasons). The run summary box shows both in plain words.
- If a ticker returns nothing, the item shows as unavailable in the dashboard's Data quality box. The 23 tickers added on 2026-11-22 have not been tested live; read that box after the first run and fix or remove any that fail in `config/universe.yaml`. Every investable item must sit in exactly one bucket of `config/flow_windows.yaml`; a test fails otherwise, so change both files together.
- `config/universe.yaml` may set `session_market` on an item to choose which market's close decides whether its newest bar is complete (China is set to the US session, spot currencies and the dollar index to 24H).

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
- FRED series DFF (policy rate), T10Y2Y (yield-curve slope), T10YIE (10-year breakeven inflation) and UNRATE (unemployment, monthly, 35-day availability lag) were added on 2026-11-22. Run **Load official history** once to load them.
- `available_from_estimate` is a conservative publication-lag estimate, not a vintage date. Values are the current vintage; later revisions are not tracked. Backtests must filter on this column.
- Manifest statuses: `ok`; `kept_previous` (today's download failed, the earlier good file is still there); `missing` (never loaded); `no_matching_contract` (CFTC data was fetched but no contract matched the name pattern).
- If a CFTC market shows `no_matching_contract`, open `data/history/v1/cftc/contracts_seen.json`, find the real contract name, and correct `CFTC_MARKETS` in `backend/advanced_sources.py`. The 10-year note contract now appears to be named like "UST 10Y NOTE", which the current pattern probably misses. This is unverified until the first live run.
- Run **Load official history** again to repair gaps. It is safe to repeat; it rewrites only files whose content changed.

## Security and reuse
Owner decision (22 November 2026): the repository is made public so that GitHub's free minutes for public repositories apply. Treat everything committed, including older commits and run logs, as public. Never commit API keys, SSH private keys, OAuth secrets, broker tokens, account identifiers, orders, proprietary historical price tables or non-public research outputs. Broker credentials, trading-server details and any private market data stay in the private trading project and are never copied here. Never attach a self-hosted runner to this repository, and never use a machine that holds trading keys as a runner. In Settings, Actions, General, set approval for workflows from outside collaborators' fork pull requests to **Require approval for all outside collaborators**.

Actions rules set by the owner on 22 November 2026: only the owner's actions and selected others are allowed, and **Require actions to be pinned to a full-length commit SHA** is on. Therefore every `uses:` line in `.github/workflows/` carries a 40-character commit code with the version in a comment (checkout v4.4.0, setup-python v5.6.0, upload-artifact v4.6.2), and **Allow actions created by GitHub** must be ticked or no run will start. To update an action, read the new tag's commit with `git ls-remote --tags https://github.com/actions/<name>`, replace the code and the version comment, and run actionlint. A tag name such as `@v4` is refused by the repository rule.

Only the research feed and history files are intended for cross-project consumption. Use `backend/feed_contract.py` for validation and retain each dated snapshot and fetch timestamp. The feed contract is additive only: `collected_at_utc`, the per-item `flow_windows` block and the top-level `rotation` and `executive_summary` blocks are optional fields and the schema stays `1.0`. A paper/live trading system needs a separate source-authority and timing approval before a signal is admitted to decision logic.

## Manual acceptance before wider circulation
- Check source terms and 95% coverage; log unresolved symbols.
- Compare 10 historical labels with blinded manual reviews.
- Independently review 50 event classifications and their observed confirmation.
- Verify all narrative claims are traceable to source data or headlines.
- Review 4–6 weeks of shadow runs and test hindsight/look-ahead barriers.
- Human-review all LinkedIn/X text before posting. Nothing auto-posts.
