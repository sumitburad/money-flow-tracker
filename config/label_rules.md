# Versioned label policy — 2026-11-15
- States: supportive, neutral, opposing, not_available.
- Bullish: money flow and price trend supportive, at least one OTHER independent family supportive, no strongly opposing family.
- Bearish: money flow and price trend opposing, at least one OTHER independent family opposing, no strongly supportive family.
- Otherwise Neutral/Mixed. Missing money flow always caps the label at Neutral/Mixed.
- Agreement: Strong if 5+ independent available families agree on the directional state; Moderate 3–4; Weak otherwise.
- Money-flow proxy: up-day versus down-day **traded volume** in the last 20 observations; supportive if ratio >= 1.2, opposing if <= 0.8; mark as participation proxy and NEVER institutional net fund inflow.
- Price: supportive only if close above both 50/200-session averages AND above its price 20 sessions before; opposing only if below both and below 20-session lookback. Otherwise neutral.
- Macro: the Federal Reserve balance-sheet observation is contextual, supportive when four most recent weekly observations grow and opposing when they contract; never claim causation.
- Breadth, positioning and news unavailable unless independent audited evidence exists; never fill with simulated data.
- Five and twenty-session relative confirmation determines strengthening/weakening where data exists; otherwise steady.
- Missing inputs never count as supportive or opposing. No composite scores, rankings, numeric conviction or LLM-selected labels.
- Changes require tests, review and documented effective dates.

## Addendum — 2026-11-22: money-flow windows and rotation
This is an additive layer. The six-family label policy above is unchanged, and nothing below feeds the Bullish / Neutral-Mixed / Bearish label.
- Rule: price up and volume up = inflow; price down and volume up = outflow; price up and volume down = inflow_fading; price down and volume down = outflow_fading. A flat price or flat volume = unclear. Missing volume = not_available and is never estimated.
- Windows: day = the latest session against the one before; week = the latest 5 sessions against the 5 before; month = the latest 20 against the 20 before. Price compares the latest close with the close one window earlier. Volume compares the average volume of the latest window with the average of the window before it.
- Flat bands (`config/flow_windows.yaml`): price is flat when it moved less than 0.25 x the item's usual daily move (60 sessions) x the square root of the window length; volume is flat inside +/-10% (day) or +/-5% (week, month).
- The newest bar is used only after its market session has closed (24-hour markets such as crypto and spot currencies use the last full day). Data older than 3 weekdays is not_available.
- Trend per item: the signals sit on a scale (outflow < outflow_fading < unclear < inflow_fading < inflow) and are read from month to week to day. Windows without a signal are skipped; fewer than two usable windows = not_available. improving = the scale only rises or holds, and rises at least once; weakening = it only falls or holds, and falls at least once; steady = all equal; mixed = it goes both ways.
- Rotation: items sit in buckets (markets, sectors, size and style, bonds, currencies, metals, energy, crypto, real estate). A bucket is inflow_led when inflow items outnumber outflow items and make up at least 40% of the items with a usable signal, outflow_led likewise in reverse, otherwise mixed; fewer than 2 usable items = not_enough_data. The bucket trend is read the same way over its three verdicts. Currencies get no verdict because spot currency data has no volume. Risk gauges (VIX) are excluded.
- Only categories are published. No price, volume or percentage from these calculations is written to the feed, the dashboard or the briefs.
- Volume is a participation proxy, never net investor fund flow.

## Addendum — 2026-11-22: executive summary
- The dashboard's executive summary may be written by a free-tier language model (Groq, then OpenRouter). The model sees only a digest of categories and names, never prices or numbers.
- Its answer is rejected unless it uses only the allowed fields (headline, rotation_view, drivers_view, watch, evidence_refs), stays inside the word limits, has no digits (except 2-year, 10-year and M2), no buy, sell or advice wording, no links or markup, only names that exist in the feed, and a rotation view that names a tracked item or bucket.
- If no provider answer passes, a rule-written summary is shown. The feed labels it `ai_validated` (provider and model named) or `rules_only`, and `human_review_required` is always true. A model never sets a market label.

## Addendum — 2026-11-22 (second pass): risk tone, coming events and market news
Another additive layer. The six-family label policy is unchanged, and nothing below feeds the Bullish / Neutral-Mixed / Bearish label or the money-flow windows.
- **Risk tone** (`regime`) is a categorical reading of how markets behaved, never advice and never a prediction. It is set only by the rule below, using the checks in `config/regime.yaml`. No model, headline or person sets it.
- Checks: 8 simple checks, voted separately for the week (latest 5 completed sessions) and the month (latest 20). A trend check looks at the direction of its member markets (stock markets, fear gauges, dollar, crypto): it needs at least its `min_members` with data and a strict majority of them moving one way. A relative check compares the mean return of two baskets (junk versus government bonds, growth versus defensive sectors, small versus large companies, copper versus gold): it votes only when the gap is at least `min_gap_pct` (0.75 points for the week, 1.5 for the month). A vote is risk_on, risk_off, neutral or not_available. A fear gauge or the dollar moving down counts as risk_on.
- Label: with at least 5 checks that have data, `risk_on` (or `risk_off`) needs at least 60% of them leaning that way and at most 1 leaning the other way; anything else with at least 5 checks is `mixed`; fewer than 5 is `not_enough_data`. The headline label is the month's. The week's label is published as `short_term_label`. `shift` compares the week with the month (improving, weakening, steady, not_available).
- Only the words, the vote counts and the plain-language reading of each check are published. No price, no return, no gap figure and no score. The feed contract recomputes the counts and the label and rejects a block that does not match.
- Risk-on is not a signal to buy and risk-off is not a signal to sell. The dashboard says so next to the label.
- **Coming events** (`calendar`) are dates only, taken from FRED's release calendar or from the built-in Fed list in `config/events.yaml`. A date is never a forecast of the result. The built-in list is marked as not yet checked against the official site until someone checks it and changes the flag.
- **Market and company news** (`market_news`) are headlines shown as the publisher wrote them, from a fixed list of publishers, with a link. They are not verified here and are never used to set a label. A headline is not evidence that a price moved because of it. The executive summary may describe which stories are in the news, never claim that a headline moved a price.
