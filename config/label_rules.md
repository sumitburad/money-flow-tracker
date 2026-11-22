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
