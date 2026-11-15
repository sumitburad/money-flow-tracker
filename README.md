# Global Money-Flow Monitor (evidence-based)

A free-tier, scheduled, **read-only** public-market research monitor driven by the owner's 15 November 2026 build manual. This replaces the earlier score-based experiment. No ranking, composite conviction, portfolio recommendations or order execution is supported.

## Connected deployment

- GitHub account: repository \`sumitburad/money-flow-tracker\`.
- Automated checks: \`.github/workflows/tests.yml\` on PRs.
- Research: \`.github/workflows/daily.yml\`, about **07:30 IST** and **19:00 IST** Monday–Saturday; \`workflow_dispatch\` is also available. GitHub schedules may be delayed. Merge or push to \`main\` automatically starts a bootstrap run.
- Static dashboard: \`docs/index.html\` with \`docs/feed/v1/latest.json\`. For public hosted access, configure GitHub Pages to serve the **docs/** folder once. The GitHub connector cannot change repository Pages settings.
- Executive text: \`briefs/YYYY-MM-DD/executive.md\` and \`reports/latest_report.md\`.
- Review-only social drafts: \`briefs/YYYY-MM-DD/linkedin.txt\` and \`x_thread.txt\`.
- Immutable date snapshots: \`data/labels/YYYY-MM-DD.json\`, \`data/news/YYYY-MM-DD.json\` and \`data/feed/v1/daily/YYYY-MM-DD.json\`.
- Official-source raw archives (compressed): \`data/raw/YYYY-MM-DD/*.gz\`. Unofficial vendor price arrays are **not** committed or republished.

## Reusable contract for trading and investing systems

\`data/feed/v1/latest.json\` is a versioned, machine-readable research feed. A duplicate is copied to \`docs/feed/v1/latest.json\`. The contract lives in \`backend/feed_contract.py\`; downstream clients must call \`load_feed(path, max_age_hours=...)\` and reject stale, malformed or uncited signals.

Each instrument contains a stable \`id\`, \`symbol\`, \`group\`, \`region\`, \`currency\`, \`label\`, \`tag\`, \`agreement\`, freshness and the full six-family cited evidence object. Official FRED values have a separate \`macro\` area with observation dates, fetch times, source links and raw-file hashes. Source publication dates and collection times are distinct.

**The feed does not authorize paper or real orders.** It contains no broker account, INDmoney raw data, positions, credentials or raw unofficial-market OHLCV data. Trading backtests must continue to use independently licensed/authorized timestamped market histories, and guard against look-ahead bias. If a downstream system imports this feed, it should use **only records that were published and available by the simulated decision time**.

## Inputs, limits and alternatives

- Research-only, existing unofficial price interface: yfinance. Data availability is best effort, provider terms may restrict collection and redistribution, and published output excludes quotes. Unsupported/stale symbols stay present and receive \`not_available\` evidence.
- Official macro: keyless FRED CSV, individual time series and raw response SHA-256. For 2Y/10Y U.S. Treasury yields only, a keyless DBnomics mirror of official Federal Reserve H.15 series is attempted on direct FRED failure. Macro collection continues when individual series fail. Source note: the original seven FRED CSV requests timed out in the first production run. For DGS2/DGS10 only, the source-coded keyless DBnomics Federal Reserve H.15 mirror is a traceable fallback; other fields remain unavailable rather than being silently imputed. Missing Indian mid/small-cap index-provider symbols were replaced with explicitly named, listed ETF proxies (MID150BEES.NS and SMALLADD.NS), not mislabeled as the original indices.
- News: Fed and ECB official RSS headlines with source links. Headline direction remains unconfirmed until independently validated by actual market reactions.
- \`config/universe.yaml\`: stable ID, region, group, symbol, currency, primary and fallback for 50 cross-asset research proxies. Symbols are candidates and need live provider checks.
- \`config/sources.yaml\`: source provenance and fallback declarations.
- \`config/models.yaml\`: **template mode** initially. Optional model-based explanations are **not configured**; deterministic code always owns labels and numerical observations.

The manual's wider source coverage (NSE/NSDL actual FPI-DII, CFTC positioning, sector constituent breadth, ECB/RBI/BOJ/PBOC monetary aggregates, verified release calendars) is tracked as outstanding, not silently synthesized. A volume participation proxy must **never** be interpreted as net investor fund flows.

## Local quality checks

\`\`\`bash
python -m pip install -r backend/requirements.txt
python -m pytest -q tests
python -m backend.run_daily --sample 4
python scripts/validate_feed.py data/feed/v1/latest.json
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
