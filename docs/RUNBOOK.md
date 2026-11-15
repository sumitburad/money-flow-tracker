# Global Money-Flow Monitor — Operator Runbook

## Normal operation
The GitHub Actions job \`Global money-flow daily research\` starts from schedules at 02:00 UTC and 13:30 UTC Monday–Saturday (07:30 and 19:00 IST). GitHub's scheduling is best-effort, so use the feed's **actual fetch time**, never the scheduled time, for freshness. PRs run \`Global monitor checks\`.

## On failures
1. Check the repo Actions page and the failed step; do not infer completion from a scheduled trigger.
2. Check \`docs/status.json\` and \`data/health/YYYY-MM-DD.json\`. The latter contains missing universe IDs and categorical provider errors.
3. If all inputs failed, no new feed or label is produced. The previous \`latest.json\` remains, clearly dated.
4. A price-only failure should not be covered by a macro figure. Missing direct fund flow always caps the related asset at Neutral/Mixed.
5. On unofficial price-provider blocks, **do not** bypass captchas, authentication or terms. Use authorized alternate histories for private research; do not copy them into a public repo.
6. Review daily \`data/feed/v1/latest.json\`, and compare stale dates with official market calendars. Saturday morning may contain Friday's U.S. close; Indian exchanges can be shut.
7. Use a reviewed PR and green tests to change rules. Never change past archived labels in order to improve historical results.

## Security and reuse
The repository is **public**. Never commit API keys, SSH private keys, OAuth secrets, broker tokens, account identifiers, orders, proprietary historical price tables or non-public research outputs. Existing EC2 read-only deployment and broker credentials must stay isolated in \`india-algo-trader\`.

Only the public research feed is intended for cross-project consumption. Use \`backend/feed_contract.py\` for validation and retain each dated snapshot and fetch timestamp. A paper/live trading system needs a separate source-authority and timing approval before a signal is admitted to decision logic.

## Manual acceptance before wider circulation
- Check source terms and 95% coverage; log unresolved symbols.
- Compare 10 historical labels with blinded manual reviews.
- Independently review 50 event classifications and their observed confirmation.
- Verify all narrative claims are traceable to source data or headlines.
- Review 4–6 weeks of shadow runs and test hindsight/look-ahead barriers.
- Human-review all LinkedIn/X text before posting. Nothing auto-posts.
