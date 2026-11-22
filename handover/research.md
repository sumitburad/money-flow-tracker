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
Sumit asked for a daily refresh that runs without fail or in one click, free-tier options for missing sources, and plain-language instructions. Delivered from branch `research/reliable-daily-refresh` as a pull request. Sumit approved the push and the merge on 2026-11-22.

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

Not tested when this was written (before the first GitHub run)
- Any live network call. The sandbox proxy blocks FRED, Treasury, CFTC and DBnomics. The first GitHub run is the real test. R-1 data was not loaded at that point; run "Load official history" if the dashboard's Official history section is empty.

Open items
1. CFTC name patterns probably miss Nasdaq-100 and the 10-year note (now named like "UST 10Y NOTE"). After the first history run, read `data/history/v1/cftc/contracts_seen.json` and fix `CFTC_MARKETS`. The dashboard shows these as "name did not match" until then.
2. R-3 gap 2 (35 records labelled official that cite m0.com) is unchanged.
3. R-2 is not implemented and the no-score rule stands. Existing categorical labels may already meet "bullish / neutral / bearish per asset"; Sumit to confirm.
4. `needs_retry` loop: if an official source stays blocked, the backup slots run every day (estimate: about 12 extra billed minutes a day).
5. Actions minutes: GitHub Free gives 2,000 a month on private repos. Estimate 300 to 450 a month; check the real figure after a week.
6. The old Next.js app in `global-money-flow-tracker.zip` was not rebuilt. The static dashboard on Vercel already does the job and needs no server.
7. Free sources: FRED key (wired in), Groq and Upstox analytics token (already supported, optional), NSDL FPI reports (needs Sumit's decision on automated download), DBnomics (no key; RBI and PBOC proxies unverified and not wired).

## Update — 2026-11-22 (third pass): money-flow windows, rotation, executive summary
Sumit asked for day, week and month money-flow checks across all asset classes, a sector and asset rotation view, an AI executive summary on the dashboard, a gap check against the earlier dashboards, and links and steps for the free providers. He also decided to make this repository public so that GitHub Actions stays free. Work is on branch `research/flow-rotation-summary`. Nothing is pushed until Sumit approves.

Built (all additive: the feed schema stays 1.0, the six-family labels and the no-score rule are unchanged)
- Flow windows: per-item `flow_windows` with day, week and month signals (inflow, outflow, inflow_fading, outflow_fading, unclear, not_available) and a `trend`. Rule: price up and volume up = inflow; price down and volume up = outflow; flat = unclear. The windows compare the latest 1, 5 and 20 sessions with the equal period before. An unfinished session is skipped (per-market close times; 24-hour markets use the last full day). Only categories are published, because Yahoo data may not be redistributed. Code `backend/flow_windows.py`, settings `config/flow_windows.yaml`, rules in `config/label_rules.md`.
- Rotation: top-level `rotation` with 9 buckets, a verdict and trend per window, the items moving into or out of each bucket, and coverage (items without volume). Currencies get no verdict because spot currency data has no volume. VIX is excluded.
- Executive summary: top-level `executive_summary`, written by Groq (openai/gpt-oss-120b, low reasoning), then OpenRouter (openrouter/free), else by rules. The model sees categories and names only. A strict validator decides whether to accept the answer. It is labelled `ai_validated` or `rules_only`, and `human_review_required` is always true. Code `backend/exec_summary.py`.
- Universe 50 to 73 items: US-listed ETFs for Taiwan, Korea, Brazil, India, an AI theme, global REITs, short Treasuries, TIPS, EM bonds, the dollar, euro, yen and pound, gold and silver, and eight NSE ETFs (NIFTYBEES, BANKBEES, ITBEES, PHARMABEES, CONSUMBEES, PSUBNKBEES, INFRABEES, GOLDBEES). New optional per-item `session_market` (China follows the US session; spot currencies and the dollar index are 24H).
- History: FRED DFF, T10Y2Y, T10YIE and UNRATE added to `config/history.yaml`. Run "Load official history" once to load them.
- Dashboard: "Executive summary" and "Money-flow windows" sections, and a small day, week and month strip on each record. The news classifier now waits 8 seconds between requests and uses low reasoning, to stay inside Groq's free limits.
- Docs: `docs/CONNECT_DATA_PROVIDERS.md` (links and steps for every free provider), plus START_HERE, README, RUNBOOK and `config/label_rules.md` updates.

India broker candles (not built here)
- Daily candles from the Indian broker API are a separate, private request to the Build side (Sheet Plan tab, row R-5). The broker token and its data stay out of this public repository and its secrets. Only categories could ever be shared back into this feed.

Tested
- 150 unit tests pass. An offline end-to-end run of `backend.run_daily.main()` with stand-in network calls produced a feed that validates with 73 items and no price, volume or percentage number inside `flow_windows` or `rotation`; a fake key never reached any output file. A headless Chrome check of the new sections passed on desktop and phone, and an old feed without the new blocks still renders.

Not tested (the sandbox has no live network to these hosts)
- The 23 new tickers on Yahoo, live Groq and OpenRouter answers, and live FRED, Treasury, CFTC and DBnomics calls. After the first run, open the dashboard's Data quality box and read "Unavailable items".

Open items
1. After the first run: fix or drop any new ticker that returns nothing; read `data/history/v1/cftc/contracts_seen.json` (second-pass item 1).
2. The Groq and OpenRouter model names live in code. If a provider retires one, the AI step falls back to rules and says so. A repository variable for the model names would remove the code change; not built.
3. Dashboard gaps against the June dashboard and the old Next.js app, ranked, are in the Project doc `plan/free-data-sources.md`: an events calendar, a regime banner, CPI and PCE year-on-year charts, market news beyond the Fed and ECB feeds, a sortable asset table, a journal page, crypto extras and a theme toggle.
4. A keyless backup price source (Twelve Data or Financial Modeling Prep free tiers) is only needed if Yahoo blocks the runner. The Gemini free tier is a possible second AI; its limits were not verified.
