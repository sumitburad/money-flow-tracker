# Connect the free data and AI providers — a plain guide

Written 22 November 2026. You do not need to read or write code. Each step lists exactly what to click.
Only Step 1 is time-sensitive. The dashboard keeps working without the keys; the keys only make it more reliable or smarter.

## What to do, in order

| Step | What it gives you | Cost | Time |
|---|---|---|---|
| 1. Keep GitHub free (make the repository public) | The daily refresh keeps running | Free | 3 minutes |
| 2. FRED key | A more reliable way to read official US data | Free | 5 minutes |
| 3. Groq key | The AI executive summary and AI news tags | Free, no card | 5 minutes |
| 4. OpenRouter key | A second AI in case Groq is busy | Free, no card | 5 minutes |
| 5. INDstocks daily data | India prices and volume for the money-flow signals | Free with your existing account | Handled inside your private trading project |
| 6. Optional extras | Backup price sources, only if ever needed | Free tiers | Not needed now |

## How to save any key in GitHub (the same five clicks every time)

1. Open https://github.com/sumitburad/money-flow-tracker/settings/secrets/actions
2. Click **New repository secret**.
3. In **Name** type the exact name given in the step (capital letters, underscores, no spaces).
4. In **Secret** paste the key.
5. Click **Add secret**.

GitHub hides the key after you save it. If you ever paste a wrong key, repeat the five clicks with the same name; the new key replaces the old one.
Keep every key private. Do not paste it in chat, email or any file. The system never prints keys, and it removes them from every file it writes.

---

## Step 1 — Keep GitHub free

**What happened.** GitHub's free minutes for private repositories are used up for this month and renew on 1 December. The daily refresh needs those minutes, so it stays paused until then, or until you choose one of the options below.

| Option | Cost | Result | My view |
|---|---|---|---|
| **A. Make the repository public** | Free | GitHub does not charge for the minutes of public repositories on its standard computers, so the refresh runs every day without a limit | **Recommended** |
| B. Wait until 1 December | Free | The dashboard stays on old data for about 9 more days | Fine if you prefer not to publish |
| C. Pay GitHub | About $2 to $3 a month for this repository (at $0.006 a minute and my estimate of 300 to 450 minutes a month). The free minutes are shared by all your private repositories | Runs now | Fine if you want to stay private |
| D. Run the job on a computer of your own | Free if you already pay for one | Needs set-up, and it must never be the computer that holds your trading keys | Not recommended |

**What becomes visible if you go public.** Every file, every older commit on every branch, and the text of the run logs. On 22 November 2026 I scanned all 175 commits on every branch for the usual patterns of passwords, keys, tokens, private keys and server addresses, and found none. The repository holds code, settings, documents, the research feed (labels and categories, no price tables) and official-source history.
Older commits also show the email address used to make them. If that matters to you, open https://github.com/settings/emails and tick **Keep my email addresses private** before you switch. That protects new commits only; old ones stay as they are.
Your dashboard link stays behind your Vercel sign-in. Making the repository public does not make the dashboard public.

**Steps for Option A**

1. Open https://github.com/sumitburad/money-flow-tracker/settings
2. Scroll to the very bottom, to the red section called **Danger Zone**.
3. Click **Change repository visibility**, then **Change to public**, and follow GitHub's confirmation (it asks you to type the repository name).
4. Start the first refresh: open https://github.com/sumitburad/money-flow-tracker/actions/workflows/daily.yml, click **Run workflow**, then the green **Run workflow** button.
5. Wait about 10 minutes. A green tick means it worked. The dashboard banner turns green shortly after.

Optional safety setting (2 minutes): open https://github.com/sumitburad/money-flow-tracker/settings/actions and, in the part about workflows from fork pull requests, choose the option that requires approval for all outside collaborators. If you do not see it, skip it.

Your saved keys stay hidden after the switch. Never attach a "self-hosted runner" to a public repository, and never use a computer that holds your trading keys as one.

---

## Step 2 — FRED key (official US data)

FRED is the data library of the US Federal Reserve Bank of St. Louis. It supplies interest rates, the dollar, central-bank balance sheets and the long history on the dashboard.

1. Open https://fredaccount.stlouisfed.org/apikeys and make a free account (email and password).
2. Click **Request API Key**, write anything (for example "money flow dashboard") and submit. A 32-character key appears.
3. Save it in GitHub with the five clicks above. Name: `FRED_API_KEY`.

Without it the system falls back to FRED's public download page, which timed out in earlier runs, and then to a backup copy of the two main US Treasury yields.
The same key can later feed a calendar of release dates (jobs, inflation and so on). That is not wired in yet.

## Step 3 — Groq key (the AI that writes the executive summary)

Groq is the free AI service I recommend. It is already wired in. With one key it does two jobs: it tags the official headlines, and it writes the **Executive summary** at the top of the dashboard.

1. Open https://console.groq.com and sign up (a Google sign-in works). No card is asked on the free plan.
2. Open https://console.groq.com/keys and click **Create API Key**. Give it any name. Copy the key now, because Groq shows it only once.
3. Save it in GitHub with the five clicks above. Name: `GROQ_API_KEY`.

**How much it uses.** Each refresh makes up to 13 small AI requests: up to 12 headline tags and 1 summary. On 22 November 2026, Groq's free plan allowed 30 requests a minute, 1,000 requests a day, 8,000 tokens a minute and 200,000 tokens a day. The system spaces its requests to stay inside that. Limits can change, so look at https://console.groq.com/docs/rate-limits if a run ever reports that the AI was busy.

**What the AI is allowed to do.** It sees only categories and names (for example "inflow-led" or "improving"), never prices. Its answer is thrown away unless it has no numbers, no buy or sell or advice wording, no links, and only names that exist on the dashboard. If it fails, a plain rule-written summary is shown and the badge says "Rule-based summary · no AI was used in this refresh", so the two can never be mistaken for each other.

## Step 4 — OpenRouter key (second AI, optional)

OpenRouter is a switchboard to many AI models, including free ones. The system tries it only if Groq fails.

1. Open https://openrouter.ai and sign in.
2. Open https://openrouter.ai/keys and create a key. Do not add money or a card; the free models need neither.
3. Save it in GitHub. Name: `OPENROUTER_API_KEY`.

Free models have their own daily limits. If you skip this step nothing breaks.

## "Grok or any other free AI?"

| AI | Free for automatic use? | Verdict |
|---|---|---|
| **Groq** (spelled differently from Grok) | Yes, a free plan with limits and no card | **Use this** |
| Grok by xAI (https://console.x.ai) | As far as I could check, its API is pay as you go with no dependable free plan | Not recommended unless you decide to pay |
| Google Gemini (https://aistudio.google.com/app/apikey) | A free tier exists, but I could not open Google's limits page, so I cannot quote the limits | Possible later; tell Claude and we add it after checking |
| ChatGPT or Claude chat windows | They need a person to type; the daily job cannot call them | Not suitable for automatic updates |

---

## Step 5 — INDstocks daily data (India prices and volume)

**What it can do.** Your INDstocks token can download daily, weekly and monthly candles (open, high, low, close, volume) for NSE and BSE shares, ETFs and indices, and for MCX commodities. That is what the "price up on rising volume" check needs for India. It would let the dashboard follow every Nifty 500 share and sector, not just a few ETFs.

**What it cannot do.** From its published documents it covers Indian markets only. I found no US shares, no currency pairs and no crypto, so those stay with the other sources. I have not confirmed its request limits or whether its data may be shown to others. Because of that, only categories (inflow, outflow and so on) should ever be published, never the prices.

**Where the token must live.** Your INDstocks token is renewed every day, so it must stay with your private trading project. Do **not** paste it into this repository's GitHub secrets. It would go stale the next morning, and this repository is public.
The safe design: your private trading project reads the candles, works out the same inflow or outflow categories, and shares only those categories (no prices) in a small file this dashboard can read.
The exact request for that is kept privately in your Claude Project notes and the Plan tab of your control sheet, not in this public repository. Nothing is needed from you except telling the trading-side window to go ahead.

## Step 6 — Optional extras (do not sign up yet)

None of these is wired in. They are listed so you know what exists. Sign up only if Claude asks you to.

| Provider | Free plan (as last checked) | Link | Note |
|---|---|---|---|
| Twelve Data | 8 requests a minute, 800 credits a day (checked 22 Nov 2026) | https://twelvedata.com/pricing | A possible backup if Yahoo blocks the daily run |
| Financial Modeling Prep | 250 requests a day (checked 22 Nov 2026) | https://site.financialmodelingprep.com/developer/docs | A possible backup for US prices |
| CoinGecko | A free plan exists (limits not re-checked) | https://www.coingecko.com/en/api/pricing | Crypto market size; not needed because Bitcoin and Ether already have volume |
| NewsAPI | Free plan is for development only (not re-checked) | https://newsapi.org/register | Not suitable for a daily production job |
| Upstox read-only token | Free with an Upstox account | Ask Claude first | Optional India buyer and seller direction. It is a separate read-only token, not your trading token |
| NSDL foreign-investor reports | Free, public | Ask Claude first | Needs your decision on automatic downloading |

A price backup would be used in memory to make categories, exactly like Yahoo today. Nothing would be saved or shown as a price table.

## How to check that a key works

1. Open https://github.com/sumitburad/money-flow-tracker/actions and click the newest **Daily money-flow refresh** run.
2. The box at the top says in plain words what happened. Find the line **Executive summary**. It ends with either "written by AI and rule-checked" or "rule-based (no AI answer was used)". The second is safe, but check that the key name is spelled exactly and that you saved it as a **repository secret**.
3. On the dashboard, the badge above the summary reads "✓ AI-written" with the provider and model, or "Rule-based summary".

## If a key leaks

Delete the key at the provider's website, create a new one and save it again with the same five clicks. Tell Claude. The old key stops working as soon as you delete it.
