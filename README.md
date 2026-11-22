# Global Money-Flow Monitor (evidence-based)

A free-tier, scheduled, **read-only** public-market research monitor driven by the owner's 15 November 2026 build manual. This replaces the earlier score-based experiment. No ranking, composite conviction, portfolio recommendations or order execution is supported.

**New here? Read `START_HERE.md`** (plain-language steps for the owner). Technical operation is in `docs/RUNBOOK.md`.

## Connected deployment

- GitHub account: repository \`sumitburad/money-flow-tracker\`.
- Automated checks: \`.github/workflows/tests.yml\` on PRs.
- Research: `.github/workflows/daily.yml` runs at about **07:37 IST** and **19:07 IST** every day, with backup slots at **10:07 IST** and **21:37 IST** that only do work when the main run did not leave a complete snapshot. Each source is tried three times and the whole collection up to three times. `workflow_dispatch` (the **Run workflow** button) starts a run in one click. GitHub schedules may be delayed. A push or merge to `main` does not start a run.
- History: `.github/workflows/history.yml` (**Load official history**, one click) loads `data/history/v1/`. See the section below.
- Dashboard: `docs/index.html` with `docs/feed/v1/latest.json`. `scripts/sync_site.py` copies the page, feed, status and history files into `frontend/`, and Vercel deploys `main` automatically (the Vercel site requires Vercel sign-in). GitHub Pages is not used. The page shows a Fresh / Late / Stale banner from the feed's own collection time.
- Executive text: \`briefs/YYYY-MM-DD/executive.md\` and \`reports/latest_report.md\`.
- Review-only social drafts: \`briefs/YYYY-MM-DD/linkedin.txt\` and \`x_thread.txt\`.
- Immutable date snapshots: \`data/labels/YYYY-MM-DD.json\`, \`data/news/YYYY-MM-DD.json\` and \`data/feed/v1/daily/YYYY-MM-DD.json\`.
- Official-source raw archives (compressed): \`data/raw/YYYY-MM-DD/*.gz\`. Unofficial vendor price arrays are **not** committed or republished.

## Reusable contract for trading and investing systems

\`data/feed/v1/latest.json\` is a versioned, machine-readable research feed. A duplicate is copied to \`docs/feed/v1/latest.json\`. The contract lives in \`backend/feed_contract.py\`; downstream clients must call \`load_feed(path, max_age_hours=...)\` and reject stale, malformed or uncited signals.

Each item also carries an optional `collected_at_utc` (when this system collected it), added 2026-11-22. The field is additive and the schema stays `1.0`; the `docs/status.json` health file additionally carries `run_slot`, `completed_at_utc`, `needs_retry` and `official_source_problems`.

Each instrument contains a stable \`id\`, \`symbol\`, \`group\`, \`region\`, \`currency\`, \`label\`, \`tag\`, \`agreement\`, freshness and the full six-family cited evidence object. Official FRED values have a separate \`macro\` area with observation dates, fetch times, source links and raw-file hashes. Source publication dates and collection times are distinct.

**The feed does not authorize paper or real orders.** It contains no broker account, INDmoney raw data, positions, credentials or raw unofficial-market OHLCV data. Trading backtests must continue to use independently licensed/authorized timestamped market histories, and guard against look-ahead bias. If a downstream system imports this feed, it should use **only records that were published and available by the simulated decision time**.

## Official history (R-1)

`data/history/v1/` holds official-source history from **2021-11-22** (approved by the owner): FRED series (US 2Y and 10Y yields, overnight reverse repo, broad dollar index, INR per USD, Fed, ECB and BOJ balance sheets, US M2, Treasury General Account, effective federal funds rate, 10-year minus 2-year yield-curve slope, 10-year breakeven inflation and the unemployment rate; run **Load official history** once to pick up the four added on 2026-11-22), the US Treasury par yield curve (3M, 2Y, 10Y, 30Y) and CFTC asset-manager futures positions. **No price data of any kind** (no OHLCV, no quotes) is fetched or written; the Build side owns prices.

- Files are plain CSV: `observation_date,value,available_from_estimate`. CFTC files use `report_date,contract,asset_mgr_long,asset_mgr_short,asset_mgr_net,open_interest,available_from_estimate`. `manifest.json` lists every series with source, row count, first and last date, how it was fetched and its status (`ok`, `kept_previous`, `missing`, `no_matching_contract`).
- `available_from_estimate` is a conservative publication-lag guess, not a true vintage date. Values are the **current vintage**; later revisions are not tracked. A backtest must filter on this column and never on the observation date.
- Built by `scripts/backfill_official.py`, loaded in one click by the **Load official history** workflow, and topped up by the daily refresh (`--mode update`). A failed series keeps its previous good file. `config/history.yaml` sets the start date, the series and the lag rules.
- `cftc/contracts_seen.json` lists every contract name CFTC returned. If a market shows `no_matching_contract`, correct `CFTC_MARKETS` in `backend/advanced_sources.py` using that list. The exchanges renamed the contracts in February 2022, so each market lists its old and its new name (fixed after the first live run, which found only the dollar index).
- Copies are mirrored to `docs/history/v1` and `frontend/history/v1` for the dashboard.
- Inflation as the change from a year earlier (added 2026-11-22): `CPI_YOY`, `CPI_CORE_YOY`, `PCE_YOY` and `PCE_CORE_YOY` are calculated from the FRED price indexes CPIAUCNS, CPILFENS, PCEPI and PCEPILFE (`fred_yoy` in `config/history.yaml`; manifest `method: year_on_year_percent`). Only the calculated change is stored, not the index. The dashboard draws one two-line chart for CPI and one for PCE.

## Money-flow windows, rotation and executive summary (2026-11-22)

Everything here is additive: the feed schema stays `1.0`, the six-family labels are unchanged, and only categories are published (no price, volume or percentage).

- **Per-item flow windows** (`flow_windows` on every item): a day, week and month signal from the rule *price up and volume up = inflow; price down and volume up = outflow; price up and volume down = inflow_fading; price down and volume down = outflow_fading; flat = unclear; no volume = not_available*, plus a `trend` (improving, weakening, steady, mixed) read from month to week to day. The windows compare the latest 1, 5 and 20 sessions with the equal period before. Settings: `config/flow_windows.yaml`. Code: `backend/flow_windows.py`. Rules: `config/label_rules.md`.
- **Rotation** (top-level `rotation`): the tracked items grouped into buckets (markets, sectors, size and style, bonds, currencies, metals, energy, crypto, real estate). Each bucket gets a verdict per window (inflow_led, outflow_led, mixed, not_enough_data), a trend, and the items moving into or out of it. Currencies show no verdict because spot currency data has no volume.
- **Executive summary** (top-level `executive_summary`): a short dashboard text written by a free-tier model (Groq when its key exists, then OpenRouter; this deployment has only an OpenRouter key) from a digest of categories and names only, validated by code, or written by rules if no model answer passes. It is labelled `ai_validated` or `rules_only`, is always marked for human review, and never sets a market label (`backend/exec_summary.py`). Since the second pass it also sees the risk tone, the coming-event names with plain timing words, and the market headlines (marked untrusted).
- Volume is a participation proxy, not a measured fund flow. The 23 research proxies added on 2026-11-22 (more country, sector, bond, currency, gold and silver ETFs, and eight NSE ETFs) need live checks; the dashboard's Data quality box lists any that return nothing.
- Links and steps for every free provider and key: `docs/CONNECT_DATA_PROVIDERS.md`.

## Risk banner, events calendar and market news (2026-11-22, second pass)

Three more additive blocks in the feed (`regime`, `calendar`, `market_news`). The schema stays `1.0`, the six-family labels and the no-score rule are unchanged, and none of them can fail a run or start the backup slots. Operation, failure notes and what is unverified are in `docs/RUNBOOK.md`.

- **Risk-on / risk-off banner** (`regime`): eight rule checks (stock markets, fear gauges, dollar, crypto, junk versus government bonds, growth versus defensive sectors, small versus large companies, copper versus gold) voted for the last 5 and last 20 sessions from the closes already read in memory. Label: `risk_on` or `risk_off` when at least 5 checks have data, at least 60% lean one way and at most 1 the other; else `mixed`; else `not_enough_data`. Only words and counts are published (no price, return or score), the contract validator recomputes the label from the votes, and a model never sets it. Settings: `config/regime.yaml`. Code: `backend/regime.py`. Rules: `config/label_rules.md`.
- **Coming events** (`calendar`): CPI, PCE, producer prices, jobs, GDP and retail-sales release dates from FRED's release calendar (needs `FRED_API_KEY`), plus a built-in Fed meeting list that was compared with federalreserve.gov on 2026-11-22 and runs to 2027-11-30. Dates only, never a forecast. Settings: `config/events.yaml`. Code: `backend/events_calendar.py`.
- **Market and company news** (`market_news`): headlines from 14 listed business publishers about US and India markets, rates and inflation, AI and chips, commodities and currencies, crypto and 20 watch-list companies, from the keyless GDELT index. Only headline, publisher, link and time are kept. Settings: `config/market_news.yaml` (`enabled: false` switches it off). Code: `backend/market_news.py`.
- Everything above was tested with stand-in network answers only (the build sandbox cannot reach FRED, GDELT or OpenRouter). On 2026-11-22 the FRED release names and request settings, the Fed list, OpenRouter's free limits (20 a minute, 50 a day below about $10 of credit) and GDELT's open-use statement were compared with the providers' own pages. The first live run (2026-11-22) proved that FRED, the Treasury, CFTC and Yahoo answer GitHub's runners and that the 4-minute daily refresh works end to end. It also found four faults, fixed in the live-run fixes pull request: CFTC contract names (only the dollar matched), Japan's balance sheet and two false stale warnings, empty AI answers (a "thinking" model used its whole token limit; `backend/ai_reply.py`), and news questions that timed out at 25 s (now 45 s with a 330 s budget). The second live run (after that pull request was merged) proved the CFTC, Japan and stale-warning fixes, but the AI summary and tags were still blank (the random free router kept picking thinking models) and the news index answered HTTP 429 ("too many requests") to the first two questions. The AI and news fixes pull request therefore (1) names free models that answer directly, chosen once per run from OpenRouter's own model list, with automatic backups (`backend/free_models.py`, `config/ai_models.yaml`; back to the random router if the list cannot be read), (2) tries each news question up to three times with waits of 10 s and 20 s and records what the index said, and (3) tidies one rule-written sentence. The third live run (2026-11-22, about 16:50 IST, started by the owner, without those fixes) again left the AI summary blank (the random router landed on a thinking model; tagging worked only by luck of the pick), answered only 2 of 6 news questions, and showed that only 1 of the 200 headlines came from a listed publisher, because the questions did not ask for those publishers. The same pull request therefore also (4) adds every listed publisher's website to each news question (`source.publisher_filter` in `config/market_news.yaml`), turns that filter off for the run and says so if the index refuses it, and records in `status.json` how many headlines came back, were dropped and why (`dropped`, `top_other_sites`, `publisher_filter`, `queries_skipped`). Still unproven until the next live run: that those fixes work, and whether the news index accepts the publisher filter.

## Reliability

- Every web request goes through one shared client (`backend/net.py`): three tries with growing waits, `Retry-After` honoured, and a host is skipped for the rest of the run after two fully failed calls.
- The workflow retries the whole collection up to three times, then validates the feed, tops up history, syncs the dashboard and pushes with its own retries.
- Backup schedules run only if `docs/status.json` does not show a complete snapshot for that session (`scripts/should_run.py`).
- Every run writes a plain-language summary to its run page (`scripts/summarize_run.py`).
- Secrets live only in GitHub Actions secrets. They are redacted from error text and scrubbed from every JSON file written.

## Inputs, limits and alternatives

- Research-only, existing unofficial price interface: yfinance. Data availability is best effort, provider terms may restrict collection and redistribution, and published output excludes quotes. Unsupported/stale symbols stay present and receive \`not_available\` evidence.
- Official macro: the FRED API when the optional `FRED_API_KEY` secret is set (a free key), otherwise the keyless FRED CSV; either way individual time series and raw response SHA-256. For 2Y/10Y U.S. Treasury yields only, a keyless DBnomics mirror of official Federal Reserve H.15 series is attempted on direct FRED failure. Macro collection continues when individual series fail. Source note: the original seven FRED CSV requests timed out in the first production run. For DGS2/DGS10 only, the source-coded keyless DBnomics Federal Reserve H.15 mirror is a traceable fallback; other fields remain unavailable rather than being silently imputed. Missing Indian mid/small-cap index-provider symbols were replaced with explicitly named, listed ETF proxies (MID150BEES.NS and SMALLADD.NS), not mislabeled as the original indices.
- News: Fed and ECB official RSS headlines with source links. Market and company headlines come from the keyless GDELT news index and only from 14 listed publishers (headline, publisher, link and time only). Headline direction remains unconfirmed until independently validated by actual market reactions.
- \`config/universe.yaml\`: stable ID, region, group, symbol, currency, primary and fallback for 73 cross-asset research proxies (50 at launch, 23 added on 2026-11-22). Symbols are candidates and need live provider checks.
- \`config/sources.yaml\`: source provenance and fallback declarations.
- \`config/models.yaml\`: documents the optional free-tier AI helpers: news tagging (Groq, then OpenRouter) and the executive summary. \`config/ai_models.yaml\` steers which free OpenRouter models are asked (chosen from OpenRouter's own list once per run; the random router is the fallback). Without keys they are off and rule-written text is shown, clearly labelled. Deterministic code always owns labels and numerical observations; a model never sets a label.

The manual's wider source coverage (NSE/NSDL actual FPI-DII, CFTC positioning, sector constituent breadth, ECB/RBI/BOJ/PBOC monetary aggregates, verified release calendars) is tracked as outstanding, not silently synthesized. A volume participation proxy must **never** be interpreted as net investor fund flows.

## Local quality checks

\`\`\`bash
python -m pip install -r backend/requirements.txt
python -m pytest -q tests
python -m backend.run_daily --sample 4
python scripts/validate_feed.py data/feed/v1/latest.json
python scripts/backfill_official.py --dry-run --out /tmp/history_preview   # history loader; writes nothing
\`\`\`

\`--sample\` is for a bounded smoke run; the scheduled job always covers the full configured universe. Current publishing requires at least one usable market proxy or official macro series. If all fail, the previous feed remains intact, a failure status is written and the workflow fails.

## Production acceptance gates

This first delivery is the read-only engineering foundation, **not** the end of the manual's nine-phase acceptance and shadow-validation process. Before treating conclusions as validated: reach 95% recent coverage of the configured set; verify provider terms, 10 dated hand-reviewed labels, 50 tagged headlines, source consistency and the 4–6-week private shadow review. Do not describe an unpassed gate as complete.

See \`docs/RUNBOOK.md\` for troubleshooting, provenance, public-data restrictions and how to add new proxies.

**Freshness gate:** Every series carries `freshness`, `last_good_date` and `allowed_age`. A successful mirror fetch does not make an old economic observation current. Daily stale observations remain viewable for historical research but are explicitly unavailable for live reasoning. The dashboard shows current vs stale separately.

**Additional official daily yield observations:** `UST_PAR_2Y` and `UST_PAR_10Y` come from the U.S. Treasury keyless annual CSV, archived and labeled explicitly as *Treasury par yield curve*. They are **not** substitutes for the separate Federal Reserve H.15 `DGS2` and `DGS10` yields; the two definitions remain distinct in the versioned feed. The latest observed date and source-age rule apply independently.

## Second-generation evidence inputs (2026-11-15)
- **CFTC** official TFF futures-only asset-manager positions: net-position *change*, Tuesday observation, conservative release lag, separate from institutional equity cash flow.
- **US breadth proxy**: RSP vs SPY and QQEW vs QQQ relative 20-day return. This is **not** constituent advance/decline breadth, and does not reveal direct fund flows.
- **Global liquidity**: direct ECB ILM SDMX weekly Eurosystem total assets, FRED/DBnomics attributed fallbacks, BOJ monthly asset data, official US Treasury par yields. RBI and PBOC remain explicitly not available until correctly defined, publicly accessible, authorized series and terms are confirmed. Never interpret mismatched definitions as comparable money stocks.
- **India participant flows**: no unattended NSE scraping (terms prohibit it). Optional read-only Upstox analytics token returns only NSE equity cash participant directions in INR, and cannot be relabelled final NSDL FPI investments. NSDL/CDSL final is unavailable without verified authorized report access. No broker amounts or tokens leave the GitHub runner.
- **AI news tagging**: optional free Groq/OpenRouter secret, strict JSON schema checker and no-math claims; unsupported calls fall back to conspicuously labelled non-AI keyword rules. News never sets market labels without independent price confirmation. Both classification and official source audit are logged in the versioned research feed.

Any secrets must be provisioned by the repo owner in GitHub Actions secrets, not pasted into the chat or committed. Without the optional credentials, the system continues in an honest degraded research mode. Passing software tests is not proof of full verified institution-flow coverage or human-reviewed classifier accuracy.
