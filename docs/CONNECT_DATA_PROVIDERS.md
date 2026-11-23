# Connect the free data and AI providers — a plain guide

Written 22 November 2026 and updated on 23 November 2026. You do not need to read or write code. Each step lists exactly what to click.
The dashboard keeps working without the keys; the keys only make it more reliable or smarter. Steps 1, 2 and 4 are already done on your side. Step 3 (Groq) is skipped because its sign-up page did not work for you. Step 4b (Google Gemini) is a new, optional second AI.

## What to do, in order

| Step | What it gives you | Cost | Time |
|---|---|---|---|
| 1. Keep GitHub free (make the repository public) | The daily refresh keeps running | Free | Done |
| 2. FRED key | A more reliable way to read official US data, and the calendar of coming release dates | Free | Done |
| 3. Groq key | A faster AI for the executive summary and news tags | Free, no card | Skipped: sign-up did not work for you. Not needed |
| 4. OpenRouter key | The AI that writes the executive summary and tags headlines | Free, no card | Done |
| 4b. Google Gemini key | A second, steadier free AI, asked before OpenRouter | Free tier, no card as far as I could check | Optional, about 5 minutes |
| 5. INDstocks daily data | India prices and volume for the money-flow signals | Free with your existing account | Handled inside your private trading project |
| 6. Optional extras | Backup price sources, only if ever needed | Free tiers | Not needed now |
| 7. New feeds (calendar, news) | Coming events, market and company news | Free, no extra key | Nothing to do. Read it so you know where the data comes from |

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
The same key also reads FRED's calendar of coming release dates (inflation, jobs, growth). That is wired in; see Step 7. Without the key the calendar shows only the Fed meetings.

## Step 3 — Groq key (optional; skipped because its sign-up page did not work for you)

On 22 November 2026 the Groq sign-up did not work for you, so skip this step. Nothing depends on it: OpenRouter (Step 4) does the same two jobs. If Groq's sign-up starts working later and you want a faster AI, follow the steps below. The system would then try Groq first and OpenRouter second.

Groq is a free AI service. It is already wired in. With one key it does two jobs: it tags the official headlines, and it writes the **Executive summary** on the dashboard.

1. Open https://console.groq.com and sign up (a Google sign-in works). No card is asked on the free plan.
2. Open https://console.groq.com/keys and click **Create API Key**. Give it any name. Copy the key now, because Groq shows it only once.
3. Save it in GitHub with the five clicks above. Name: `GROQ_API_KEY`.

**How much it uses.** Each refresh makes about 4 small AI requests: up to 3 for headline tags (five headlines in each request) and 1 for the summary. On 22 November 2026, Groq's free plan allowed 30 requests a minute, 1,000 requests a day, 8,000 tokens a minute and 200,000 tokens a day. The system spaces its requests to stay inside that. Limits can change, so look at https://console.groq.com/docs/rate-limits if a run ever reports that the AI was busy.

**What the AI is allowed to do.** It sees only categories and names (for example "inflow-led" or "improving"), never prices. Its answer is thrown away unless it has no numbers, no buy or sell or advice wording, no links, and only names that exist on the dashboard. If it fails, a plain rule-written summary is shown and the badge says "Rule-based summary · no AI was used in this refresh", so the two can never be mistaken for each other.

## Step 4 — OpenRouter key (the AI in use; done)

OpenRouter is a switchboard to many AI models, including free ones. With no Groq key, it is the only AI the system uses. You saved `OPENROUTER_API_KEY` on 22 November 2026. The steps stay here in case the key ever has to be replaced.

1. Open https://openrouter.ai and sign in.
2. Open https://openrouter.ai/keys and create a key. Do not add money or a card; the free models need neither.
3. Save it in GitHub. Name: `OPENROUTER_API_KEY`.

**What it does.** It tags headlines and writes the **Executive summary**, in at most 4 small requests per refresh (up to 3 for headline tags, 5 headlines each, and 1 for the summary). OpenRouter's `openrouter/free` option picks one free model at random for each request, and in the first two real runs it kept landing on "thinking" models that sent back blank answers. So the program now does the choosing itself. Once per refresh it reads the list of models your account may use, keeps the free ones with a big enough size and room for a full answer, and names up to three of them in the request. Models that answer directly come first. Models that "think" before answering fill the places that are left, and they are asked to think only briefly and given more room (see "The thinking models" below). The first is asked; if it is busy or fails, OpenRouter automatically tries the next. Only models whose names end in `:free` are ever named, so a backup can never cost money. If the list cannot be read, or holds no suitable free model, the program goes back to `openrouter/free` exactly as before. Either way, the **Data quality** box has a line starting "AI models:" (which free models were asked) or a warning that says in plain words why none could be chosen. The steering words are in `config/ai_models.yaml`; you never need to edit it. The summary is checked by code every time, so a weaker model only means the rule-written summary is shown that day.

**Limits (checked on 22 November 2026).** OpenRouter's pricing page (https://openrouter.ai/pricing) and its free-models page (https://openrouter.ai/collections/free-models) say that free models are capped at 20 requests a minute and 50 requests a day. The daily cap rises to 1,000 once an account has bought about $10 of credit (a one-time purchase, not a subscription). If you followed these steps and added no money, 50 a day is the number that applies to you. OpenRouter's own guides add that a failed request still counts towards the day's total. I could not open the separate limits page itself, so these numbers come from those two pages.

Each refresh makes about 4 requests (up to 10 on a bad day, when a free model sends an empty answer or is busy and each step gets its one second try). The system makes two real refreshes a day, plus two backups that run only when needed. That is about 8 requests on an ordinary day and up to 20 on a bad one. Each time you press **Run workflow** by hand it adds about 4 more, so up to about eight manual clicks in a day fits. If the daily limit is ever used up, the system waits once and tries again; if that fails, the rule-written summary is shown and the badge says so. Nothing breaks. Adding $10 of credit would lift the cap to 1,000 a day, but it is not needed, and you can stay on the free plan.

**Empty answers (found on 22 November 2026).** Many free models "think" before they write, and the thinking counts against the same allowed length as the answer. In the first real run the summary came back blank because the model used up its allowance thinking. The system now allows much more length for OpenRouter, waits up to 75 seconds for the answer, and tries once more (asking the model to think less) if the first answer is blank or cut off. If it still fails, the **Data quality** box says why in plain words, for example "empty reply from <model>: it used all its room thinking" or "HTTP 429: busy, or the daily free limit is used up", and which model answered. Keys are never shown in these notes. Groq (if you ever connect it) already runs at its lowest thinking level, so it is not retried.

**Still blank after that (second real run, 22 November 2026).** The extra room and the "think less" retry were not enough: the random pick kept landing on thinking models (NVIDIA's Nemotron family) and the summary and the headline tags were still blank. That is why the program now names the free models itself, as described above. I could only test this against stand-in answers. It relies on OpenRouter's list having the shape its documentation describes, and on at least one free model that answers directly being open to your account. OpenRouter lists only the models your account's privacy settings allow, and free models may keep what they are sent, so if you have switched that kind of use off in your OpenRouter account, no free model may be listed. If the **Data quality** box says "No free model could be chosen", tell Claude and we will go through that setting together. I also could not find out whether OpenRouter counts a backup attempt as a separate request against the 50 a day; the numbers above assume it does not.

**The thinking models (live runs of 22 and 23 November 2026).** Five real refreshes tried the AI and the summary worked in only one. Your OpenRouter account lists a "thinking" setting for every one of its free models, so the old rule "skip models that think" left the list empty and the random pick did the work. Across the five runs, nemotron-3-ultra and particle-1 sent a usable answer every time they were asked (3 of 3 each). A few others (gemma-4-26b, dots-3, ernie-5.5-flash, nemotron-3-nano-omni) answered some of the time. Two NVIDIA models (nemotron-3.5-super-vl and nemotron-3.5-lightning), a very small one (lfm-3-1.7b) and flint sent blank answers in almost every case. So thinking models are now allowed, the ones that worked are tried first (`prefer_thinking` in `config/ai_models.yaml`), the two NVIDIA ones are left out by name, and the small and unknown-size ones are left out by the size rules. With the models seen so far the program should ask nemotron-3-ultra first, with particle-1 and gemma-4-26b as backups. This is my plan from the evidence; it is untested against the real service until the next real run. The **Data quality** box now shows the models asked, a fold-out list of every free model seen with the reason each was used or skipped, and what each model did in that run. If a model that used to work starts failing, the list shows it. To go back to the old rule, change `use_thinking_models` to `false` in `config/ai_models.yaml`.

**Privacy.** Free models may keep what they are sent. The system sends only category words, names and public business headlines. No price, no account, no key and nothing private leaves the repository.

## Step 4b — Google Gemini key (optional second AI)

Gemini is Google's AI. Its free tier is another source for the same two jobs (tagging headlines and writing the **Executive summary**). If you save a key, Gemini is asked **before** OpenRouter. If Gemini is busy, refuses the key or sends an answer that fails the checks, the program carries on with OpenRouter exactly as today. Without a key, nothing changes.

1. Open https://aistudio.google.com/app/apikey and sign in with a Google account.
2. Click **Create API key**. If it asks you to choose or create a project, choose **Create API key in new project**.
3. Copy the key. It starts with `AIza`.
4. Save it in GitHub with the five clicks above. Name: `GEMINI_API_KEY`.
5. Do **not** paste the key in chat. Tell Claude when it is saved; the next refresh (or one you start yourself) will use it, and the **Data quality** box will show a Gemini line under **What each AI model did this run**.

**What to know.**
- **Free tier and privacy.** Google's free tier may use what is sent to improve its products. The program sends only category words, names and public business headlines, the same as to OpenRouter. No price, no account and no key goes with them.
- **Limits.** Google gives limits per project and per model, and AI Studio shows the ones that apply to you. I could not find fixed free-tier numbers on Google's page, so I cannot state them here. The program asks Gemini about 4 times a refresh, and it keeps a list of up to three model names in `config/ai_models.yaml` (`gemini-flash-latest`, `gemini-3.5-flash`, `gemini-2.5-flash`). The next name is used only when the one before it fails, and every Gemini model has its own free allowance.
- **Your country.** I could not confirm that the free tier is open to accounts in India. If the key page or a later run says it is not, tell Claude. Nothing breaks: OpenRouter takes over.
- **Where the key goes.** Only to Google's own address (`generativelanguage.googleapis.com`), in a hidden request header, never in a web address, a file, a log or `status.json`. If Google refuses the key, the program stops asking Gemini for the rest of that refresh and says so in plain words in the **Data quality** box.
- **How to switch it off.** Remove the secret in GitHub, or set `enabled: false` in the `gemini` part of `config/ai_models.yaml`.

## "Grok or any other free AI?"

| AI | Free for automatic use? | Verdict |
|---|---|---|
| **OpenRouter free models** | Yes, free models with limits and no card | **In use** (Step 4) |
| **Groq** (spelled differently from Grok) | Yes, a free plan with limits and no card | Good, but its sign-up did not work for you, so it is skipped |
| Grok by xAI (https://console.x.ai) | As far as I could check, its API is pay as you go with no dependable free plan | Not recommended unless you decide to pay |
| Google Gemini (https://aistudio.google.com/app/apikey) | A free tier exists. Google's limits page (last updated 28 October 2026) lists no free-tier numbers and says to look up your own limits inside Google AI Studio. Free-tier content may be used to improve Google's products. I could not confirm that it is open in India | **Wired in as an optional second AI** (Step 4b). It is asked before OpenRouter once you save a key |
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

## Step 7 — The new feeds added on 22 November 2026 (nothing to sign up for)

These parts of the dashboard use data from places you have not met yet. None needs a new key.

| Part of the dashboard | Where the data comes from | Key | What to know |
|---|---|---|---|
| Coming events: inflation (CPI, PCE, producer prices), jobs, growth | FRED's release calendar (https://fred.stlouisfed.org/releases/calendar) | Your `FRED_API_KEY` | Dates only, never a forecast. On 22 November 2026 I checked that the six release names the system looks for match FRED's own calendar pages. If FRED changes a name later, the Data quality box says which one no longer matches |
| Coming events: Fed meetings | A list typed into the system, taken from the Fed's meeting calendar (https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) | None | On 22 November 2026 I compared the list with the Fed's own pages: all eight 2026 decision days and the 2027 days the Fed has published. The Fed calls its 2027 dates tentative and changed them on 12 November 2026, so they can still move. One 2027 meeting, 26 to 27 October, is for discussing strategy and has no rate decision, so it is left out. The list runs to 30 November 2027, and the Data quality box warns before it runs out |
| Market and company news | GDELT, a free public news index (https://www.gdeltproject.org/) | None | See the paragraph below |
| Risk-on or risk-off banner | The same daily prices already used for money flow | None | Nothing new is downloaded |
| Inflation charts (CPI, PCE) | FRED price indexes; the change from a year earlier is worked out here | Your `FRED_API_KEY` | Appear after the one-click history load (Step 3 of START_HERE) |

**About the news.** GDELT says its search service is rate-limited, but the pages I could read do not give the exact number. The figure people usually report is one request every five seconds, so the system asks its ten questions about 5.5 seconds apart, which takes a few minutes when the index is slow. It waits up to 45 seconds for each answer and stops asking after about five and a half minutes in total, so a slow news index can never hold up the refresh. Real runs on 22 November 2026 showed two different problems. First, two answers took longer than the old 25-second limit, so no news was shown; the limit was raised. Second, in the next run the index answered "HTTP 429" (too many requests) to the first two questions, before it had answered any. The index asks for one request every five seconds, but on shared computers like GitHub's other people's traffic may count against the same address, so I cannot tell from here whether the fault is ours. So a refused question is now tried up to three times, waiting 10 seconds and then 20 seconds (or the time the index asks for, at most 30 seconds), and when it still refuses, the **Data quality** box repeats what the index said. **Third real run (22 November 2026, about 4:50 pm India time, started by you from GitHub).** Only 2 of the 6 news questions were answered (the others got "too many requests"), and of the 200 headlines that did arrive only 1 came from the listed publishers. The reason is that the questions did not ask for those publishers by name: the index sent its 100 most relevant headlines from anywhere and the program threw the rest away afterwards. So every question now asks the index for the listed publishers only (their 14 websites are added to the question). If the index refuses that, meaning it answers with something that is not a list of headlines or answers the very first, broad question with nothing at all, the program turns the filter off for that refresh, asks the same question again without it, and says so in the **Data quality** box. A busy or slow index does not count as a refusal. The **Data quality** box now also says how many headlines came back, how many came from the listed publishers and how many were kept, and when most came from other sites it names the biggest ones. Nobody has yet seen how the real index reacts to the filter, so the next real run is its test; the fallback is automatic. If the news still fails in the next real run, the choices are the publishers' own free news feeds (each needs a licence check first) or a news service with a free key. That is your decision and I have built neither. It keeps only the headline, the publisher's name, the time and a link, and only from 14 well-known business publishers (Reuters, Associated Press, CNBC, Bloomberg, The Wall Street Journal, Financial Times, MarketWatch, Barron's, The Economic Times, Mint, Moneycontrol, Business Standard, BusinessLine and The Financial Express). Each headline is shown as the publisher wrote it and links to the publisher's page. No article text is copied. GDELT's About page (https://www.gdeltproject.org/about.html) says its data can be used without limit, commercially as well. I could only see the start of that paragraph, so I cannot rule out that it asks for a credit. The dashboard already names GDELT under the news and links to its home page. If you want the news off until a person has read the full terms, tell Claude; it is one switch.

**What is checked and what is not.** My workspace cannot reach FRED, GDELT or the Fed's site, so nothing here has been run against the real services yet. On 22 November 2026 I did compare these with the providers' own pages: FRED's release names and the settings the system sends it, the Fed's meeting dates, OpenRouter's free limits, and GDELT's open-use statement. **First real run (22 November 2026).** FRED, the US Treasury, CFTC and the price source all answered from GitHub's computers, and the whole refresh took about 4 minutes. Four faults were found and fixed in the live-run fixes update: futures positions (the exchanges had renamed three contracts), Japan's balance sheet and two false "behind on dates" warnings, blank AI answers, and news questions that timed out. **Second real run (22 November 2026, about 4:30 pm India time, after those fixes were merged).** Proven: the four futures markets now have positions (five years of weekly history), Japan's balance sheet is current, the false "behind on dates" warnings are gone and all 73 prices are current. Still failing: the AI (blank answers from thinking models) and the news (HTTP 429). **Third real run (22 November 2026, about 4:50 pm India time, started by you from GitHub; the AI and news update was not in it).** The official data and all 73 prices were fine again. The AI summary was blank again: the random free model it landed on used all its room thinking. Headline tagging worked this time (14 of 15 headlines tagged by AI), which was luck of the random pick. The news answered 2 of 6 questions and kept 1 headline, for the reason given above. The headline lists had the shape the program expects. This update targets all three. Still untested: whether the named free models answer and pass the checks, whether the longer news waits cure "too many requests", and whether the news index accepts the publisher filter. The next real run is the test. Read the **Data quality** box after it, as START_HERE explains.

## How to check that a key works

1. Open https://github.com/sumitburad/money-flow-tracker/actions and click the newest **Daily money-flow refresh** run.
2. The box at the top says in plain words what happened. Find the line **Executive summary**. It ends with either "written by AI and rule-checked" or "rule-based (no AI answer was used)". The second is safe, but check that the key name is spelled exactly and that you saved it as a **repository secret**.
3. In the same box, the lines **Risk tone**, **Coming events** and **Market news** say whether each new part worked. For example "10 of 10 questions answered" means the news index replied every time.
4. On the dashboard, the badge above the summary reads "✓ AI-written" with the provider and model, or "Rule-based summary".

## If a key leaks

Delete the key at the provider's website, create a new one and save it again with the same five clicks. Tell Claude. The old key stops working as soon as you delete it.
