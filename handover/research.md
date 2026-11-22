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

## Update — 2026-11-22 (fourth pass): events calendar, risk banner, inflation charts, market and company news, OpenRouter-only AI
Sumit made the repository public, set the Actions rules ("Allow sumitburad, and select non-sumitburad, actions and reusable workflows" and "Require actions to be pinned to a full-length commit SHA"), saved `FRED_API_KEY` and `OPENROUTER_API_KEY`, and said Groq sign-up does not work for him. He approved four additions. Work is on branch `research/events-regime-news`, stacked on `research/flow-rotation-summary` (PR #11). Nothing is merged. Standing rules kept: Build owns all price (OHLCV) data and none is fetched or committed here; the feed contract stays additive (schema 1.0; no score, rank, conviction, current_price, raw_ohlcv or key fields); secrets only in Actions secrets; dashboard-only monitoring; the INDstocks token never enters this repository; `plan/investing-system-plan.md` untouched.

Built
- Risk-on / risk-off banner: top-level `regime` (`config/regime.yaml`, `backend/regime.py`, `validate_regime` in `backend/feed_contract.py`). Eight rule checks voted for 5 and 20 completed sessions from the closes the flow windows already hold (new shared helpers `typical_move`, `price_direction`, `completed_closes` in `backend/flow_windows.py`; flow behaviour unchanged). Label from a published rule (at least 5 checks with data, at least 60% one way and at most 1 the other). Words and counts only. The contract recomputes the tally and label. A model never sets it. Addendum in `config/label_rules.md`.
- Coming events: top-level `calendar` (`config/events.yaml`, `backend/events_calendar.py`). FRED `releases/dates` matched by release name, plus a built-in FOMC list flagged `checked_against_official_site: false` with `covers_through: 2026-12-31` and an advisory when the horizon passes it. Dates only.
- Inflation charts: CPI and PCE year-on-year (`CPI_YOY`, `CPI_CORE_YOY`, `PCE_YOY`, `PCE_CORE_YOY`) calculated in `scripts/backfill_official.py` from CPIAUCNS, CPILFENS, PCEPI and PCEPILFE (`fred_yoy` in `config/history.yaml`). Two two-line charts on the dashboard. Needs one run of **Load official history**.
- Market and company news: top-level `market_news` (`config/market_news.yaml`, `backend/market_news.py`, `validate_market_news`). GDELT DOC 2.0 `artlist`, keyless; 10 questions (6 themes, 4 company groups) 5.5 s apart; 14 allowed publishers; English; 72 h; headline, publisher, link and time only; 36 stories at most. Fail-soft with `enabled: false` as a switch.
- Executive summary now also sees the risk tone, the coming-event names with plain timing words and the news headlines (marked untrusted); `drivers_view` limit is 80 words. Validation is unchanged.
- OpenRouter-only AI: headline tagging is batched (5 headlines per request, at most 3 requests) so a refresh makes about 4 requests. A 429 answer waits once as asked (`retry_after_seconds`, `post_with_one_429_retry` in `backend/net.py`).
- Dashboard: banner, **Coming events**, **Market and company news**, `ago()` singular fix, two inflation charts, Data quality notes for the three new blocks. `scripts/summarize_run.py` adds **Risk tone**, **Coming events** and **Market news** lines to the run page (tests in `tests/test_summarize_run.py`).
- Docs: START_HERE (plain language, new Step 1b for the "Allow actions created by GitHub" tick box), `docs/CONNECT_DATA_PROVIDERS.md` (OpenRouter is the AI; new Step 7), README, RUNBOOK, `config/label_rules.md`, `config/models.yaml`.

Tested
- 393 unit tests pass; actionlint and shellcheck are clean.
- An offline end-to-end run of `backend.run_daily.main()` with stand-in FRED, GDELT and OpenRouter answers (every other address failing with an error text that contains the keys) passed 30 checks: the feed validates (also through `scripts/validate_feed.py`); `regime`, `calendar` and `market_news` are present; the AI summary was accepted and had been shown the tone, events and news; the briefs and both social drafts carry the tone sentence; the news questions were 5.5 s apart; neither key appears in any output file or in the run log; no forbidden key is in the feed.
- A headless Chrome run on the produced `docs/` passed on a laptop and a phone width: no console errors, no sideways scroll, banner with 8 checks, six event cards, company stories first, executive summary badge, Data quality notes. Separate headless runs covered the empty, no-FRED-key, down, switched-off and hostile-headline cases.

Not tested (the sandbox cannot reach these hosts)
- Live FRED release calendar (release names, `include_release_dates_with_no_data`, `realtime_end`), live GDELT (response shape, query behaviour, terms of use), live OpenRouter (answers and free limits; limits from memory: about 20 a minute and 50 a day below $10 credit), the 23 new Yahoo tickers, and live FRED, Treasury, CFTC and DBnomics calls. Six page reads (OpenRouter limits, FRED release-calendar documentation, the Federal Reserve meeting calendar, GDELT's API page, GDELT's terms, Gemini limits) needed Sumit's approval and were not retried.
- The FOMC date list was typed from memory and ends 2026-12-31. Check it against federalreserve.gov, then set `checked_against_official_site: true`.

Open items
1. Actions: with "Require actions to be pinned" on, a run starts only if every `uses:` line is pinned **and** "Allow actions created by GitHub" is ticked. PR #11's check showed `startup_failure`. PR #12 (workflow pins only, base `main`) fixes the pins for `main`; until it is merged and the box is ticked, the scheduled refresh on `main` will not start. Sumit has to approve the merges. Nothing is merged without his word.
2. After the first live run read the Data quality box and the run summary: unmatched FRED release names, news questions that failed, unavailable tickers, and `cftc/contracts_seen.json`.
3. If OpenRouter's free allowance proves too small, options are an OpenRouter credit top-up of a few dollars (raises the daily allowance) or Gemini's free tier (limits not verified). The rule-written summary is the safe fallback in the meantime.
4. Still unbuilt from the June dashboard gap list: sortable asset table, journal page, crypto extras, theme toggle.

## Update — 2026-11-22 (fifth pass): merges, and the unverified items checked against the providers' own pages
Merged on 2026-11-22 at Sumit's request, in the order he gave: PR #12 (`db7c395`, workflow pins only), PR #11 (`5e3ff68`, flow windows, rotation map, AI summary, 73-item universe) and PR #13 (`8082ccc`, risk banner, calendar, news, OpenRouter-only AI). On the merged `main`: 393 tests pass, actionlint is clean, no `uses:` line is unpinned. So "Nothing is merged" in the fourth-pass entry above is out of date. The GitHub checks on all three PRs showed `startup_failure`, which fits an unticked "Allow actions created by GitHub" box (START_HERE Step 1b) but is not proven; until that box is ticked the scheduled refresh on `main` will not start.

Sumit approved reading six pages. The page-reading tool refused five of them (OpenRouter limits, FRED `releases/dates` guide, Fed FOMC calendar, GDELT blog, GDELT About) with a provenance error and was not retried; the Gemini page opened. Search results from the same official sites supplied the facts below. Search shows only part of a page, so anything cut off is marked as such.
- Fed FOMC dates: all eight 2026 decision days in `config/events.yaml` match the Fed's pages. The Fed's 2027 schedule (revised 2026-11-12 and called tentative) is 26-27 Jan, 16-17 Mar, 27-28 Apr, 8-9 Jun, 27-28 Jul, 14-15 Sep, 26-27 Oct (a policy-strategy meeting with no rate decision) and 16-17 Nov. The list now holds the seven 2027 decision days, `checked_against_official_site: true`, new `checked_on: "2026-11-22"` and `covers_through: "2027-11-30"`. The 16-17 Nov date is from the Fed's calendar page; the press-release text I could see stopped before it.
- FRED `releases/dates`: the request settings and the answer shape (`release_dates`, `release_id`, `release_name`, `date`) match the code. All six release names match FRED's release-calendar pages (CPI id 10, PCE "Personal Income and Outlays" id 54, PPI id 46, jobs id 50, GDP id 53, retail sales id 9). Not tested live.
- OpenRouter: free (`:free`) models are capped at 20 requests a minute and 50 a day, 1,000 a day after about $10 of credit, and failed requests count. Read on the pricing and free-models pages, not on the limits page. A refresh makes about 4 requests and there are two real runs a day plus two backups that run only when needed, so 8 to 16 a day; each manual run adds about 4.
- GDELT: the DOC API is rate limited (no number on the pages I could read, so 5.5 s spacing stays a cautious assumption) and searches a rolling window of about three months. Its About page says its datasets are free for unlimited and unrestricted use, commercial included; the rest of that paragraph was cut off, so a credit requirement is not ruled out (the dashboard already names GDELT with a link).
- Gemini: its rate-limit page (updated 2026-10-28) lists no free-tier numbers and points to AI Studio.

Changed on branch `research/verify-sources` (docs, one config file and one small code change; no feed or workflow change): the Fed list above; `backend/events_calendar.py` shows "Checked against the official site on <date>." from the new optional `checked_on` key (only a plain date is ever shown); tests pin the official 2026 and 2027 lists; guides (`docs/CONNECT_DATA_PROVIDERS.md`, `docs/RUNBOOK.md`, `START_HERE.md`, README, `config/label_rules.md`) now state the confirmed limits and what is still unproven.

Still unverified until the first live run: a live FRED call with the real key from GitHub's runners, GDELT's exact JSON answer shape and whether it answers GitHub's runners, the free AI models actually answering, the 23 new Yahoo tickers, and live Treasury, CFTC and DBnomics calls.

Open items
1. Sumit ticks "Allow actions created by GitHub" (START_HERE Step 1b), then presses **Run workflow** on the daily refresh and once on **Load official history** for the inflation charts. Claude does not start runs unasked.
2. After the first live run read the Data quality box and the run summary lines (Risk tone, Coming events, Market news).
3. Re-check the Fed list if the Fed announces a schedule change, and add 2028 before 2027-10-16 (when the "list ends" advisory starts).
4. Someone should read the full GDELT terms paragraph for any credit wording.
