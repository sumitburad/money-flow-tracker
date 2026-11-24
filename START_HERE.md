# Start here — a plain guide for Sumit

You do not need to read or write any code. This page lists every step that needs a person. Everything else happens by itself. Links and steps for every key and provider are in `docs/CONNECT_DATA_PROVIDERS.md`.

## What happens on its own

- Twice a day the system collects official money-flow data (US interest rates, dollar and rupee rates, central-bank balance sheets, futures positions, official news headlines), the dates of coming releases (inflation, jobs, Fed meetings) and market and company news headlines from major business publishers. It also reads daily prices and volumes in memory to work out where money is moving in and out, then updates the dashboard.
- Times (India): **7:37 am** and **7:07 pm**, every day.
- If one of those runs is late or fails, a **backup run** starts by itself at **10:07 am** or **9:37 pm**. The backup only does real work if the main run did not finish properly.
- Every data source is tried three times, and the whole collection is tried up to three times, before the system gives up for that run. If it still fails, the dashboard keeps showing the previous good data, clearly dated.
- It never places an order, never saves or publishes share prices, and never stores a password.

## What is new on the dashboard (22 November 2026)

- **Executive summary** (near the top of the page): a few plain sentences on where money is moving. A free AI (Google Gemini if you save its key, otherwise OpenRouter) writes it from the dashboard's own categories, and code checks it. If no AI key is saved, or the AI answer fails the checks, a rule-written summary is shown and the badge says so. Read it as a draft. It is never advice.
- **Money-flow windows**: for every tracked item, whether money is moving **in** or **out** over the last day, the last week and the last month. Price up with volume up is **inflow**. Price down with volume up is **outflow**. Price up with volume down is shown as *inflow fading*, and price down with volume down as *outflow fading*.
- **Rotation map**: the same signals grouped into markets, sectors, bonds, currencies, metals, energy, crypto and real estate, with a verdict for each group and whether the picture is improving or weakening.
- More items are tracked (73 instead of 50): Taiwan, Korea, Brazil, India, AI, global property, short bonds, inflation-linked bonds, emerging-market bonds, the dollar, euro, yen, pound, gold, silver and eight Indian ETFs.
- Volume shows how busy trading is. It is not a measure of money actually moved. Day readings are noisy; week and month readings are steadier. Currencies show no verdict because spot currency data has no volume.

**Added later on 22 November 2026**

- **Risk-on or risk-off banner** (at the very top): the mood of the markets in plain words, for this month and for this week. It runs eight simple checks: are most stock markets rising, are the fear gauges falling, is the dollar weakening, are Bitcoin and Ether rising, are riskier bonds beating safe bonds, are growth sectors beating steady ones, are small companies beating large ones, and is copper beating gold. **Risk-on** means most checks show investors comfortable owning riskier things. **Risk-off** means most show them defensive. **Mixed** means no clear lean. It describes what already happened. It is never a signal to buy or sell. Open **See the 8 checks behind this** to see every vote.
- **Coming events**: cards for the next US inflation (CPI), PCE inflation, producer prices, jobs and economic growth releases, and Fed meetings. Dates only, never a forecast of the result. The release dates come from FRED's own calendar (your FRED key is used). The Fed meeting dates are a list typed into the system. On 22 November 2026 I compared it with the Fed's own website: all 2026 dates and the 2027 dates the Fed has published (it calls the 2027 dates tentative, so they can still move). The list runs to 30 November 2027, and the Data quality box warns before it runs out.
- **Inflation charts**: CPI and PCE, all items and core, shown as the change from a year earlier, inside **Official history**. They appear after the one-click history load in Step 3.
- **Market and company news**: headlines from major business publishers about US and India markets, interest rates and inflation, AI and chips, commodities and currencies, crypto, and about 20 big companies (for example Micron, Nvidia and Reliance). Only the headline, the publisher's name, the time and a link to the publisher are kept. The executive summary uses them to explain stories such as a company's results. A headline is not proof that a price moved because of it. The news comes from the publishers' own free news feeds (the same ones news-reader apps use). The free news index used before (GDELT) would not answer GitHub's computers.

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

**Done and proven (22 November 2026).** The first runs failed to start. After you updated the setting and saved it, a run started and finished normally, so this step is complete.

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

## What the first real run showed (22 November 2026), and what this update fixes

The first run on GitHub's computers worked from start to finish in about 4 minutes. Five years of official history loaded, the coming-events calendar filled in and the risk banner worked. Four things did not, and each has a fix in this update:

1. **Futures positions showed only the dollar.** The exchanges renamed three contracts in 2022 and the system was still looking for the old names. It now knows both names, and it raises a note if a market ever goes quiet again.
2. **Japan's central-bank balance sheet was missing, and two numbers were wrongly marked "behind on dates"** (the rupee rate and the US money supply). Those numbers are published in batches, so a gap of a week or two is normal. Each now has an allowed gap that matches how often it really appears, and Japan's figure is read from FRED directly.
3. **The AI summary came out blank.** The free AI spends part of its allowed length "thinking" before it writes, and it ran out of room. It now gets much more room, one automatic second try, and if it still fails the dashboard says exactly why, in plain words, in the Data quality box.
4. **The news step gave up after two slow answers.** The news index was reachable but slow. The system now waits up to a minute for each answer, stops after five minutes in total so the refresh is never held up, and explains any problem in plain words.

These are only confirmed after the next real run, so read the Data quality box then, as the next section explains.

## What the second and third real runs showed (22 November 2026), and what the next update changes

Both runs proved that the futures positions, Japan's balance sheet and the false "behind on dates" warnings are fixed, and that all 73 prices are current. Two things were still wrong:

1. **The AI summary was blank again.** The free AI picks one free model at random each time, and it kept landing on models that spend all their allowed length thinking. (The headline tags worked in the third run only because the random pick happened to be lucky.) The next update names free models that answer directly, chosen from OpenRouter's own list, with backups. If that list cannot be read, it goes back to the random pick, and the Data quality box says why.
2. **The news was thin.** The news index sometimes answers "too many requests", so only 2 of 6 questions were answered in the third run. And of the 200 headlines it sent, only 1 came from the business publishers we use, because we were not asking for them by name. The next update waits and tries again, asks for the listed publishers by name, and says in plain words what the index replied. If the index will not take that request, the program asks again without it and tells you so.

These are only confirmed after the next real run.

## What the later real runs showed (22 and 23 November 2026), and what this update changes

Five real refreshes in a row tried the AI, and the summary worked in only one of them. The cause was found in the model list on your OpenRouter account: **every free model on it has a "thinking" setting**. The previous rule was "never use thinking models", so the list was always empty and the program went back to OpenRouter's random pick, which kept landing on models that send blank answers. The models that did answer were all thinking models. Two of them (nemotron-3-ultra and particle-1) answered every time they were asked. A few others answered some of the time. Two NVIDIA models, one very small model and one called flint sent blank answers almost every time.

This update is waiting for your OK as a pull request. Nothing changes until you approve it. It does three things:

1. **Thinking models are allowed**, with the ones that worked so far tried first and the ones that never worked left out by name. They are asked to think only briefly and are given more room to answer.
2. **The dashboard shows which models it saw.** In the **Data quality** box you will see which models were asked, a fold-out list of every free model it saw with the reason each was used or skipped, and a line saying what each model did in that run (answers used, answers that failed the checks, blank answers).
3. **Google Gemini can be added as a second, steadier free AI** (Step 4b in `docs/CONNECT_DATA_PROVIDERS.md`). If you save a Gemini key, it is asked before OpenRouter. If Gemini is busy, refuses the key or sends an answer that fails the checks, the program carries on with OpenRouter as before. Without a key nothing changes.

The rules for what the AI may say are the same as before: it sees only categories and names, never prices, and its answer is thrown away unless it passes the same checks. Nothing here is confirmed until a real run uses it, so read the **Data quality** box after the first refresh.

## The news was still empty on 23 November, and what the news update changes (24 November 2026)

On 23 November the **Market and company news** box was empty. The free news index we used (GDELT) did not answer GitHub's computers in any of the four to six real tries: it said "too many requests", or did not answer within 45 seconds. Waiting longer or asking more politely did not help, so this update stops depending on it.

Instead the system now reads the **news feeds that the publishers themselves put out for readers** (the "RSS" feeds that news-reader apps use). There are 16, from CNBC, The Wall Street Journal, MarketWatch, The Economic Times, Business Standard, BusinessLine and Mint. From each headline it keeps only the headline, the publisher's name, the time and a link back to the publisher. No article text. The old GDELT code is still there, switched off; one word in the settings file turns it back on.

Three things to know:

1. **It is not proven yet.** I could not open these feeds from the build computer, so the update was tested with stand-in answers only. The feed addresses come from public feed directories that listed them as working in October and November 2026. Some may refuse GitHub's computers. If so, the **Data quality** box names each feed that failed and why, the page shows the headlines from the feeds that did answer, and the dead feeds are then removed or replaced.
2. **The publishers' terms.** Dow Jones (The Wall Street Journal, MarketWatch) allows its feeds for personal, non-commercial use, and the NBC family (which includes CNBC) says similar things on its feed pages. The dashboard is free and shows only the headline and a link, which is what feeds are made for. But if you ever charge for anything built on this page (your monetisation goal), those feeds must be switched off or the publisher asked first. The settings file has a note at the top and a one-line switch for each feed. This is your decision, not mine: if you are not comfortable now, say so and the feeds are switched off before the update is merged.
3. **Nothing for you to set up.** No new key, no new cost, no new account.

The update waits for your OK as a pull request. After you approve it and a refresh runs, read the **Data quality** box as described in the next section.

## After the first refresh with the new features (2 minutes, once)

Open the dashboard and find the **Data quality** box (the last section). Look at these five things and copy anything odd to Claude, which will fix it:

1. **Unavailable items**: a few of the 23 new items may be listed. That is expected for any ticker the free price source does not return.
2. **Coming events**: a note such as "No upcoming FRED date was found for…" means one release name needs correcting. Fix it by telling Claude. The Fed list note about 31 December 2026 is expected.
3. **Market news**: a line starting **News feed problem** names one publisher's feed that would not answer and says why (for example "the feed answered HTTP 403", which means the publisher refused our request). The page still shows the headlines from the feeds that did answer, and nothing else is affected. If none answers, the box says the news sources could not be reached. The line **News detail** says how many headlines came back, how many were from the listed publishers and how many were kept. Copy any **News feed problem** lines to Claude: dead feeds are then removed or replaced in one small update.
4. The badge above the **Executive summary**. **AI-written · openrouter** means the key works and the answer passed the checks. **Rule-based** means the key is missing, the free AI was busy, or its answer was rejected. Both are safe. When it is rule-based, the Data quality box now gives the reason in plain words (for example "empty reply from a model: it used all its room thinking", or "HTTP 429: the daily free limit is used up"). The line **Headline tagging** does the same for the news tags. A line starting **AI models:** names the free models the program asked, in order, and says which of them think briefly before answering, or, in a warning, says why none could be chosen (then it used OpenRouter's random pick, as before). Click **Free models seen on this account** to see every model it found and why each was used, kept as a spare or skipped. The line **What each AI model did this run** counts, for each model, the answers that were used, the ones that failed the checks and the blank ones (it also shows Gemini if you saved a key). If you see "No free model could be chosen", tell Claude: it may be a setting in your OpenRouter account.
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

Good to know: the free AI that writes the summary (OpenRouter) allows 50 requests a day, and each refresh uses about 4 (a bad day, when the AI is slow or busy and every step is retried once, can use up to 10). Two refreshes a day happen by themselves, so you have room for about eight extra clicks a day. If you press it more often, nothing breaks. The summary just switches to the rule-written version until the allowance resets the next day.

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
| AI executive summary and AI tagging of news headlines (OpenRouter) | Free models with limits, no card | Done: you saved `OPENROUTER_API_KEY`. It is the AI in use today, because Groq's sign-up did not work for you |
| Google Gemini (a second free AI, asked before OpenRouter) | Free tier with limits, no card. I could not confirm that it is open to accounts in India, so the key page will tell you | Optional: make a key at aistudio.google.com/app/apikey and save it as `GEMINI_API_KEY`, exactly like Step 2. Steps are in `docs/CONNECT_DATA_PROVIDERS.md`, Step 4b. Google's free tier may use what is sent to improve its products; the program sends only categories, names and public headlines. Do not paste the key in chat |
| Groq (a faster free AI) | Free tier with limits, no card | Optional, and only if its sign-up page starts working: make a key at console.groq.com and save it as `GROQ_API_KEY`, exactly like Step 2. It would then be used first. Skipping it costs nothing |
| India daily buyer and seller direction (Upstox read-only token) | Free, needs an Upstox account | Tell Claude when you want it. Your trading broker is not affected |
| India foreign-investor reports (NSDL) | Free, public | Needs your decision on automatic downloading. Ask Claude |
| India daily prices and volume from INDstocks | Free with your account | Stays inside your private trading project. Ask Claude. See `docs/CONNECT_DATA_PROVIDERS.md` |
