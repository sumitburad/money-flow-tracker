# Start here — a plain guide for Sumit

You do not need to read or write any code. This page lists every step that needs a person. Everything else happens by itself. Links and steps for every key and provider are in `docs/CONNECT_DATA_PROVIDERS.md`.

## What happens on its own

- Twice a day the system collects official money-flow data (US interest rates, dollar and rupee rates, central-bank balance sheets, futures positions, official news headlines), the dates of coming releases (inflation, jobs, Fed meetings) and market and company news headlines from major business publishers. It also reads daily prices and volumes in memory to work out where money is moving in and out, then updates the dashboard.
- Times (India): **7:37 am** and **7:07 pm**, every day.
- If one of those runs is late or fails, a **backup run** starts by itself at **10:07 am** or **9:37 pm**. The backup only does real work if the main run did not finish properly.
- Every data source is tried three times, and the whole collection is tried up to three times, before the system gives up for that run. If it still fails, the dashboard keeps showing the previous good data, clearly dated.
- It never places an order, never saves or publishes share prices, and never stores a password.

## What is new on the dashboard (22 November 2026)

- **Executive summary** (near the top of the page): a few plain sentences on where money is moving. A free AI (OpenRouter) writes it from the dashboard's own categories, and code checks it. If no AI key is saved, or the AI answer fails the checks, a rule-written summary is shown and the badge says so. Read it as a draft. It is never advice.
- **Money-flow windows**: for every tracked item, whether money is moving **in** or **out** over the last day, the last week and the last month. Price up with volume up is **inflow**. Price down with volume up is **outflow**. Price up with volume down is shown as *inflow fading*, and price down with volume down as *outflow fading*.
- **Rotation map**: the same signals grouped into markets, sectors, bonds, currencies, metals, energy, crypto and real estate, with a verdict for each group and whether the picture is improving or weakening.
- More items are tracked (73 instead of 50): Taiwan, Korea, Brazil, India, AI, global property, short bonds, inflation-linked bonds, emerging-market bonds, the dollar, euro, yen, pound, gold, silver and eight Indian ETFs.
- Volume shows how busy trading is. It is not a measure of money actually moved. Day readings are noisy; week and month readings are steadier. Currencies show no verdict because spot currency data has no volume.

**Added later on 22 November 2026**

- **Risk-on or risk-off banner** (at the very top): the mood of the markets in plain words, for this month and for this week. It runs eight simple checks: are most stock markets rising, are the fear gauges falling, is the dollar weakening, are Bitcoin and Ether rising, are riskier bonds beating safe bonds, are growth sectors beating steady ones, are small companies beating large ones, and is copper beating gold. **Risk-on** means most checks show investors comfortable owning riskier things. **Risk-off** means most show them defensive. **Mixed** means no clear lean. It describes what already happened. It is never a signal to buy or sell. Open **See the 8 checks behind this** to see every vote.
- **Coming events**: cards for the next US inflation (CPI), PCE inflation, producer prices, jobs and economic growth releases, and Fed meetings. Dates only, never a forecast of the result. The release dates come from FRED's own calendar (your FRED key is used). The Fed meeting dates are a list typed into the system. On 22 November 2026 I compared it with the Fed's own website: all 2026 dates and the 2027 dates the Fed has published (it calls the 2027 dates tentative, so they can still move). The list runs to 30 November 2027, and the Data quality box warns before it runs out.
- **Inflation charts**: CPI and PCE, all items and core, shown as the change from a year earlier, inside **Official history**. They appear after the one-click history load in Step 3.
- **Market and company news**: headlines from major business publishers about US and India markets, interest rates and inflation, AI and chips, commodities and currencies, crypto, and about 20 big companies (for example Micron, Nvidia and Reliance). Only the headline, the publisher's name, the time and a link to the publisher are kept. The executive summary uses them to explain stories such as a company's results. A headline is not proof that a price moved because of it. The news comes from GDELT, a free public news index that needs no key.

## One-time setup (about 10 minutes)

### Step 0 — Keep GitHub free: make the repository public (done)

You made the repository public on 22 November 2026, so GitHub's standard computers now run the daily refresh for free. Your dashboard link stays behind your Vercel sign-in. Nothing more to do here. What became visible, and the other choices you had, are in the "Keep GitHub free" part of `docs/CONNECT_DATA_PROVIDERS.md`.

### Step 1 — Check that the daily schedule is on (1 minute)

The update has been merged, so the automatic schedule is on. To see it working, open https://github.com/sumitburad/money-flow-tracker/actions and look for runs called **Daily money-flow refresh**. A green tick means a run worked.

To pause it later: open https://github.com/sumitburad/money-flow-tracker/actions/workflows/daily.yml, click the **⋯** menu at the top right, then **Disable workflow**. To switch it back on, use the same menu and click **Enable workflow**.

### Step 1b — One tick box in GitHub's "allowed actions" setting (2 minutes, once)

You turned on a strict safety rule, which is a good choice: every small helper program the daily job uses must be locked to one exact version. The job's helpers are locked that way. The job also uses three small helpers that GitHub itself makes (one fetches the files, one sets up Python, one saves reports). For any job to start, GitHub must be allowed to use its own helpers. If that box is not ticked, a run stops at once with the words **Startup failure**, before it does anything.

1. Open https://github.com/sumitburad/money-flow-tracker/settings/actions
2. Under **Actions permissions**, keep **Allow sumitburad, and select non-sumitburad, actions and reusable workflows**.
3. In the box that opens below it, tick **Allow actions created by GitHub**. Keep **Require actions to be pinned to a full-length commit SHA** ticked.
4. Click **Save**.

If the box was already ticked, there is nothing to do. If a run ever shows **Startup failure**, this is the first place to look.

### Step 2 — Get the free FRED key (done on 22 November 2026)

You have already saved `FRED_API_KEY`, so you can skip this step. The steps stay here in case the key ever has to be replaced. FRED is the data library of the US Federal Reserve Bank of St. Louis. Its public download page timed out in earlier runs, and the key uses a more reliable door. The same key now also reads the calendar of coming release dates. Without the key everything else still works, but it may be slower or fail more often, and the calendar shows only the Fed meetings.

1. Open https://fredaccount.stlouisfed.org/apikeys and create a free account (email and password).
2. Click **Request API Key**, write anything in the description (for example "money flow dashboard") and submit. The key appears on the screen. It is 32 letters and numbers.
3. Copy the key.
4. Open https://github.com/sumitburad/money-flow-tracker/settings/secrets/actions and click **New repository secret**.
5. In **Name** type exactly `FRED_API_KEY`. In **Secret** paste the key. Click **Add secret**.

Keep the key private. Do not paste it in chat, email or any file. GitHub hides it after you save it, and the system never prints it.

### Step 3 — Load the five-year history (one click, 5 minutes)

Run this once now if you have never run it, or if you ran it before 22 November 2026. It adds the inflation charts (CPI and PCE, as the change from a year earlier) and four more series (policy interest rate, yield-curve slope, expected inflation and unemployment). Until you run it, the **Official history** section is empty and the inflation charts are missing.

1. Open https://github.com/sumitburad/money-flow-tracker/actions/workflows/history.yml
2. Click **Run workflow** (a grey button on the right), then the green **Run workflow** button inside the small box.
3. Wait about 5 minutes and refresh the page. A green tick means it worked.
4. Open your dashboard (the Vercel link you normally use) and look at the section **Official history**.

This loads official data from 22 November 2021 onwards. You only need to do it once. The daily refresh keeps it up to date after that.

If you see a red cross, click the run and read the box called **Official history load**. It says in plain words which series failed. Run it again after an hour. Series that worked are kept.

## After the first refresh with the new features (2 minutes, once)

Open the dashboard and find the **Data quality** box (the last section). Look at these five things and copy anything odd to Claude, which will fix it:

1. **Unavailable items**: a few of the 23 new items may be listed. That is expected for any ticker the free price source does not return.
2. **Coming events**: a note such as "No upcoming FRED date was found for…" means one release name needs correcting. Fix it by telling Claude. The Fed list note about 31 December 2026 is expected.
3. **Market news**: a note that a question failed, or that no headline came from a listed publisher, means the free news index answered oddly. The page then shows what it has. Nothing else is affected.
4. The badge above the **Executive summary**. **AI-written · openrouter** means the key works and the answer passed the checks. **Rule-based** means the key is missing, the free AI was busy, or its answer was rejected. Both are safe.
5. The **Risk tone** banner at the top should show a month reading and a week reading. **Not enough data** means fewer than five of the eight checks had prices that day.

None of these new parts can stop the daily refresh. If any of them fails, the page says so and keeps going.

## Every day: nothing to do

Open the dashboard. The banner at the top tells you how fresh the data is:

| Banner | Meaning | What to do |
|---|---|---|
| Green **Fresh** | Updated in the last 20 hours | Nothing |
| Amber **Late** | 20 to 48 hours old, so a run was missed | Press **Refresh now** |
| Red **Stale** | More than 2 days old, or the data file could not be read | Press **Refresh now** |

## Refresh right now (one click)

1. Press **Refresh now** on the dashboard banner. It opens https://github.com/sumitburad/money-flow-tracker/actions/workflows/daily.yml
2. Click **Run workflow**, then the green **Run workflow** button.
3. Wait 5 to 10 minutes. The banner turns green 1 to 2 minutes after the run finishes, once the dashboard site has updated.

Good to know: the free AI that writes the summary allows 50 requests a day, and each refresh uses about 4. Two refreshes a day happen by themselves, so you have room for about eight extra clicks a day. If you press it more often, nothing breaks. The summary just switches to the rule-written version until the allowance resets the next day.

## If something looks wrong

1. Open https://github.com/sumitburad/money-flow-tracker/actions
2. A green tick is fine. A red cross means a run failed.
3. Click the red run. The box at the top of the page tells you in plain words what happened. Click **Re-run all jobs** (top right) to try again.
4. If two runs in a row fail, copy that box and paste it to Claude.

The very first run is the real test, because it has not yet been run on GitHub's computers. If it fails, the dashboard keeps the old data and the box tells you why.

## What it will not do

- It sends no alerts of its own, because you asked for dashboard-only checking. The banner and the Actions page are the warning signs. GitHub itself may email you when a run fails, depending on your GitHub notification settings.
- It does not tell you to buy or sell anything, and it does not touch your broker.
- It does not save or publish share prices. It reads daily prices and volumes only in memory to work out categories such as inflow or outflow, then discards them. Another part of the project keeps the real price history.

## Free upgrades for later (all optional)

| What | Free? | What you do |
|---|---|---|
| FRED key | Yes | Done (Step 2 above) |
| AI executive summary and AI tagging of news headlines (OpenRouter) | Free models with limits, no card | Done: you saved `OPENROUTER_API_KEY`. It is the only AI in use, because Groq's sign-up did not work for you |
| Groq (a faster free AI) | Free tier with limits, no card | Optional, and only if its sign-up page starts working: make a key at console.groq.com and save it as `GROQ_API_KEY`, exactly like Step 2. It would then be used first. Skipping it costs nothing |
| India daily buyer and seller direction (Upstox read-only token) | Free, needs an Upstox account | Tell Claude when you want it. Your trading broker is not affected |
| India foreign-investor reports (NSDL) | Free, public | Needs your decision on automatic downloading. Ask Claude |
| India daily prices and volume from INDstocks | Free with your account | Stays inside your private trading project. Ask Claude. See `docs/CONNECT_DATA_PROVIDERS.md` |
