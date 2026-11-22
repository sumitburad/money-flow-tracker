# Start here — a plain guide for Sumit

You do not need to read or write any code. This page lists every step that needs a person. Everything else happens by itself. Links and steps for every key and provider are in `docs/CONNECT_DATA_PROVIDERS.md`.

## What happens on its own

- Twice a day the system collects official money-flow data (US interest rates, dollar and rupee rates, central-bank balance sheets, futures positions, official news headlines). It also reads daily prices and volumes in memory to work out where money is moving in and out, then updates the dashboard.
- Times (India): **7:37 am** and **7:07 pm**, every day.
- If one of those runs is late or fails, a **backup run** starts by itself at **10:07 am** or **9:37 pm**. The backup only does real work if the main run did not finish properly.
- Every data source is tried three times, and the whole collection is tried up to three times, before the system gives up for that run. If it still fails, the dashboard keeps showing the previous good data, clearly dated.
- It never places an order, never saves or publishes share prices, and never stores a password.

## What is new on the dashboard (22 November 2026)

- **Executive summary** (top of the page): a few plain sentences on where money is moving. A free AI (Groq) writes it from the dashboard's own categories, and code checks it. If no AI key is saved, or the AI answer fails the checks, a rule-written summary is shown and the badge says so. Read it as a draft. It is never advice.
- **Money-flow windows**: for every tracked item, whether money is moving **in** or **out** over the last day, the last week and the last month. Price up with volume up is **inflow**. Price down with volume up is **outflow**. Price up with volume down is shown as *inflow fading*, and price down with volume down as *outflow fading*.
- **Rotation map**: the same signals grouped into markets, sectors, bonds, currencies, metals, energy, crypto and real estate, with a verdict for each group and whether the picture is improving or weakening.
- More items are tracked (73 instead of 50): Taiwan, Korea, Brazil, India, AI, global property, short bonds, inflation-linked bonds, emerging-market bonds, the dollar, euro, yen, pound, gold, silver and eight Indian ETFs.
- Volume shows how busy trading is. It is not a measure of money actually moved. Day readings are noisy; week and month readings are steadier. Currencies show no verdict because spot currency data has no volume.

## One-time setup (about 10 minutes)

### Step 0 — Keep GitHub free: make the repository public (3 minutes)

GitHub's free minutes for private projects are used up until 1 December. Public projects get unlimited free minutes on GitHub's standard computers, so making this repository public keeps the daily refresh free. Your dashboard link stays behind your Vercel sign-in.

1. Open https://github.com/sumitburad/money-flow-tracker/settings and scroll to the red **Danger Zone** at the bottom.
2. Click **Change repository visibility**, choose **Change to public**, and confirm by typing the repository name.
3. Open https://github.com/sumitburad/money-flow-tracker/actions/workflows/daily.yml, click **Run workflow**, then the green **Run workflow** button.

Before you do this, read the "Keep GitHub free" part of `docs/CONNECT_DATA_PROVIDERS.md`. It explains what becomes visible and the other choices (wait until 1 December, or pay about $2 to $3 a month).

### Step 1 — Check that the daily schedule is on (1 minute)

The update has been merged, so the automatic schedule is on. To see it working, open https://github.com/sumitburad/money-flow-tracker/actions and look for runs called **Daily money-flow refresh**. A green tick means a run worked.

To pause it later: open https://github.com/sumitburad/money-flow-tracker/actions/workflows/daily.yml, click the **⋯** menu at the top right, then **Disable workflow**. To switch it back on, use the same menu and click **Enable workflow**.

### Step 2 — Get the free FRED key (optional but recommended, 5 minutes)

FRED is the data library of the US Federal Reserve Bank of St. Louis. Its public download page timed out in earlier runs. A free key uses a more reliable door. Without the key everything still works, but it may be slower or fail more often.

1. Open https://fredaccount.stlouisfed.org/apikeys and create a free account (email and password).
2. Click **Request API Key**, write anything in the description (for example "money flow dashboard") and submit. The key appears on the screen. It is 32 letters and numbers.
3. Copy the key.
4. Open https://github.com/sumitburad/money-flow-tracker/settings/secrets/actions and click **New repository secret**.
5. In **Name** type exactly `FRED_API_KEY`. In **Secret** paste the key. Click **Add secret**.

Keep the key private. Do not paste it in chat, email or any file. GitHub hides it after you save it, and the system never prints it.

### Step 3 — Load the five-year history (one click, 5 minutes)

If the **Official history** section on the dashboard already shows charts, skip this step. If you loaded it before 22 November 2026, run it once more to add four new series (policy interest rate, yield-curve slope, expected inflation and unemployment).

1. Open https://github.com/sumitburad/money-flow-tracker/actions/workflows/history.yml
2. Click **Run workflow** (a grey button on the right), then the green **Run workflow** button inside the small box.
3. Wait about 5 minutes and refresh the page. A green tick means it worked.
4. Open your dashboard (the Vercel link you normally use) and look at the section **Official history**.

This loads official data from 22 November 2021 onwards. You only need to do it once. The daily refresh keeps it up to date after that.

If you see a red cross, click the run and read the box called **Official history load**. It says in plain words which series failed. Run it again after an hour. Series that worked are kept.

## After the first refresh with the new features (2 minutes, once)

Open the dashboard and find the **Data quality** box. Under **Unavailable items** you may see a few of the 23 new items. That is expected for any ticker the free price source does not return. Copy that list to Claude and it will fix or remove them. Also check the badge above the **Executive summary**. **AI-written** means a Groq key is saved and its answer passed the checks. **Rule-based** means no key is saved, or the AI answer was rejected.

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
| FRED key | Yes | Step 2 above |
| AI executive summary and AI tagging of news headlines (Groq) | Free tier with limits, no card | Create a free account at console.groq.com, make a key, and save it in GitHub as a secret named `GROQ_API_KEY`, exactly like Step 2. Full steps are in `docs/CONNECT_DATA_PROVIDERS.md` |
| A second AI in case Groq is busy (OpenRouter) | Free models, no card | Make a key at openrouter.ai/keys and save it as `OPENROUTER_API_KEY`, exactly like Step 2 |
| India daily buyer and seller direction (Upstox read-only token) | Free, needs an Upstox account | Tell Claude when you want it. Your trading broker is not affected |
| India foreign-investor reports (NSDL) | Free, public | Needs your decision on automatic downloading. Ask Claude |
| India daily prices and volume from INDstocks | Free with your account | Stays inside your private trading project. Ask Claude. See `docs/CONNECT_DATA_PROVIDERS.md` |
