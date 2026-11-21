# Handover Summary

## Built
- **Excel trackers**: `Global_Money_Flow_Tracker.xlsx` through `_v8.xlsx` in `/mnt/user-data/outputs/`, with sheets for Exec Summary, Day-Over-Day, Signal Dashboard, Sector Deep Dive, COT, ETF Flows, Crypto On-Chain, and Journal. Builder scripts are `/home/claude/v4_tracker.py` to `v8.py`.
- **HTML dashboards**: `dashboard_v8.html` and daily briefs `dashboard_june17/18/19/22/23/24/26.html`, plus `monetise_roadmap.html`. The June 25 file write errored and was superseded by June 26.
- **Other drafts**: a LinkedIn post for CFOs/CEOs and a master prompt for the website.
- **Next.js 14 app**: `/home/claude/money-flow-tracker`, zipped as `global-money-flow-tracker.zip`.
  - Data modules in `lib/data-sources/` (fetch-client, fmp, fred, coingecko, twelvedata, cftc, newsapi)
  - `lib/utils/regime.ts` with `classifyYieldTrendOnly` and `classifyRegimeFull`
  - 7 API routes
  - Pages: dashboard, sectors, macro, crypto, cot, journal
  - Vercel cron in `vercel.json`

## Strategies and backtest results
None were run in this conversation. The only logic is a rule-based regime heuristic (DXY × 10Y yield) and a 0–10 signal score. Portfolio allocations were untested frameworks. There are no backtest numbers.

## Broker and infrastructure
- No broker is involved.
- **Deploy**: GitHub and Vercel (cron `0 11 * * 1-5` UTC).
- **Data APIs**: Financial Modeling Prep, FRED, CoinGecko, Twelve Data, CFTC Socrata (no key needed), NewsAPI.
- The sandbox had no outbound network.

## Decisions made
- No hardcoded or simulated data in the website. Failures show "Data unavailable".
- All data-source functions return `DataResult<T>` and never throw. API routes keep a try/catch as a second layer.
- The regime banner shows yield trend only, because no DXY feed is wired.
- The journal is hand-written MDX, not API-driven.
- Vercel KV is unused, and unused dependencies were removed.

## Open issues
- **Build never verified**: `npm install` and `next build` were never run. Dependency versions were pinned from memory.
- **`react-markdown`**: its use inside a Server Component is untested.
- **Unverified symbols**: the FMP index symbols (`^GSPC` etc.) and the Twelve Data `WTI/USD` symbol are unconfirmed.
- **Unwired features**: NewsAPI has no UI, and DXY is not wired.
- **Stale and approximate data**: Excel and HTML figures are dated June 2026 and partly approximated from search snippets, so they are now stale (today is Nov 21, 2026).
- **Estimated values**: some Day-Over-Day values were estimated.

## Next steps
1. Unzip locally, then run `npm install && npm run build` and fix any errors.
2. Push to GitHub and import into Vercel.
3. Add the env vars from `.env.local.example`. FMP, FRED, Twelve Data, and `CRON_SECRET` are the minimum.
4. Trigger `/api/cron/refresh` once to confirm each source returns `ok: true`.
5. Add DXY via Twelve Data and switch the banner to `classifyRegimeFull`.
6. Wire a news panel to `getMarketHeadlines`.
7. Refresh or retire the stale June 2026 spreadsheets and dashboards.
