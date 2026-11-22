# Research handover — 2026-11-21

Scope set by Sumit: R-1 backfill from 2021-11-22; R-3 point-in-time check; R-2 draft score scheme. Build owns all price (OHLCV) data; no price data fetched or committed.

## R-3 — point-in-time check on feed records (done)
Script (scratch, not committed): checks every `data/feed/v1/daily/*.json` and `latest.json` for observation dates after `run_date_ist` and `fetched_at` after `generated_at_utc`.
- Result: 0 look-ahead violations across 2026-11-15 to 2026-11-18. `latest.json` is identical to the 2026-11-18 snapshot.
- Gap 1: item-level records carry `observation_date` and `observed_at` but no collection time (`fetched_at`). Only `macro` series have `fetched_at_utc`. A downstream point-in-time filter cannot tell when an item was actually collected. Not changed, since the feed contract must stay stable. Proposed fix (additive, needs sign-off): add `collected_at_utc` per item.
- Gap 2: 35 `macro_liquidity` family records cite `https://m0.com/data/fed-balance-sheet` with method `official_macro_context`. M0.com is a third-party mirror (config/sources.yaml marks `no_official_origin_claim: true`), so the "official" label is inaccurate for those rows. Flagged, not changed.

## R-1 — official-source backfill from 2021-11-22 (blocked, not run)
- FRED (`fred.stlouisfed.org`), U.S. Treasury (`home.treasury.gov`) and CFTC (`www.cftc.gov`) are refused by the egress proxy with HTTP 403. This is an allowlist block, not a transient error. Not worked around.
- DBnomics mirror (`api.db.nomics.world`), the repo's documented fallback for DGS2/DGS10, was unreachable (no response).
- Action needed: allow those hosts for this session (claude.ai Settings > Capabilities, or the org admin), then rerun the backfill from 2021-11-22.
- Note: `docs/RUNBOOK.md` has no items labelled R-1 or R-3. These were taken from the task description.

## R-2 — draft score scheme (draft only, not implemented)
Conflicts with the current design: README says "No ranking, composite conviction" and `backend/feed_contract.py` forbids `score`, `rank`, `conviction` and `confidence_score` fields. Any scheme therefore needs a decision from Sumit before it touches the feed. Draft direction, kept outside the feed: per-family states (supportive / neutral / opposing / not_available) counted into a separate, unpublished diagnostic table, with no numeric score exported.

## Open items
1. Allow FRED / Treasury / CFTC (and DBnomics) egress, then run R-1 from 2021-11-22.
2. Decide on `collected_at_utc` per item (R-3 gap 1).
3. Correct the M0.com "official" labelling (R-3 gap 2).
4. Decide whether R-2 may proceed given the no-score rule.
5. Sheet Plan status line not posted: no Sheets tool is available in this session.

## Update — 2026-11-22
- Allowlist: Sumit says FRED, Treasury, CFTC and DBnomics were allowed. Retry still fails (no response) for all four. R-1 remains BLOCKED. Re-test before running the backfill from 2021-11-22.
- collected_at_utc: approved by Sumit as an additive per-item field. Not implemented yet. It needs a reviewed change to `run_daily.py` and tests, and must not alter existing fields.
- R-2: Sumit asked whether it can go ahead given the no-score rule. Sumit's answer is not recorded in the repo. Until a reviewed PR changes the rule, R-2 stays an unpublished diagnostic outside the feed, with no score in the feed contract.
- Sheet Plan tab: appended one status row (Plan!A47). Existing rows untouched.

## Update — 2026-11-22 (second pass): daily automation, history loader, dashboard
Sumit asked for a daily refresh that runs without fail or in one click, free-tier options for missing sources, and plain-language instructions. Branch `research/reliable-daily-refresh`, not merged yet.

Built
- `backend/net.py`: one shared web client (3 tries, growing waits, `Retry-After`, per-host breaker). Secrets are redacted from errors and scrubbed from every JSON file written.
- FRED API path (secret `FRED_API_KEY`) with the keyless CSV and DBnomics as fallbacks.
- Feed: optional `collected_at_utc` per item (additive, schema stays 1.0), checked in `backend/feed_contract.py`. `docs/status.json` gains `run_slot`, `completed_at_utc`, `needs_retry`, `official_source_problems`. R-3 gap 1 is closed.
- `daily.yml` rewritten: main slots 02:07 and 13:37 UTC, backup slots 04:37 and 16:07 UTC gated by `scripts/should_run.py`, collection retried up to 3 times, history top-up, site sync, push with retries, plain-language run summary. The workflow was manual-only since 2026-11-18, so merging switches the schedule back on.
- `history.yml`: one-click "Load official history".
- R-1 loader: `scripts/backfill_official.py` and `config/history.yaml` (FRED, Treasury par curve, CFTC TFF; start 2021-11-22). Every row has `available_from_estimate`. A failed series keeps its previous good file. No price data of any kind.
- Dashboard: freshness banner (green to 20 h, amber to 48 h, red beyond) and an "Official history" section with one chart per series, hover and keyboard tooltips, 1 year / 3 years / since start, table view and CSV link. Copied to `frontend/` for Vercel.
- `START_HERE.md` (plain language), README and RUNBOOK updated. They had said the repo is public and described the pre-pause schedule; the API shows the repo is private.

Tested
- 91 unit tests pass; actionlint and shellcheck are clean.
- The dashboard was checked in headless Chrome (25 checks, desktop and phone, all banner states, no-history state) against synthetic history made in /tmp. The synthetic data was not committed.
- Found and fixed while testing: a series that never loaded was labelled `kept_previous` on the second failed run, and a partial `--only` run dropped the other groups from the manifest.

Not tested
- Any live network call. The sandbox proxy blocks FRED, Treasury, CFTC and DBnomics. The first GitHub run is the real test. R-1 data is therefore not loaded yet; run "Load official history" after the merge.

Open items
1. CFTC name patterns probably miss Nasdaq-100 and the 10-year note (now named like "UST 10Y NOTE"). After the first history run, read `data/history/v1/cftc/contracts_seen.json` and fix `CFTC_MARKETS`. The dashboard shows these as "name did not match" until then.
2. R-3 gap 2 (35 records labelled official that cite m0.com) is unchanged.
3. R-2 is not implemented and the no-score rule stands. Existing categorical labels may already meet "bullish / neutral / bearish per asset"; Sumit to confirm.
4. `needs_retry` loop: if an official source stays blocked, the backup slots run every day (estimate: about 12 extra billed minutes a day).
5. Actions minutes: GitHub Free gives 2,000 a month on private repos. Estimate 300 to 450 a month; check the real figure after a week.
6. The old Next.js app in `global-money-flow-tracker.zip` was not rebuilt. The static dashboard on Vercel already does the job and needs no server.
7. Free sources: FRED key (wired in), Groq and Upstox analytics token (already supported, optional), NSDL FPI reports (needs Sumit's decision on automated download), DBnomics (no key; RBI and PBOC proxies unverified and not wired).
