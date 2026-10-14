# User guide

Job Hunter finds **software jobs in the countries you pick** (the Netherlands by default) on company career sites and LinkedIn, removes what doesn't
fit you, ranks the rest, and gives you one dashboard to review, apply and keep track. It runs on your own machine
(designed for a Raspberry Pi) and costs nothing: no paid APIs, no accounts.

The dashboard also has a built-in **Help** page covering the same ground in short form.

## 1. First start

1. Open the dashboard: `http://<your-pi>.local:8585` (port is set in `config.yaml`, see [Settings](SETTINGS.md)).
2. The **Getting started** checklist at the top of the Jobs page walks you through:
   - **Settings → Profile**: name, email, phone, LinkedIn, a 2-3 sentence pitch and your **skills with weights**
     (1 = nice to have, 2 = solid, 3 = core stack). Skills decide how jobs rank; the rest feeds your motivation letters.
   - **Companies**: the employers searched directly. Defaults are included; add or remove any (section 5).
   - **Scrape now**: optional, refreshes every company straight away. Otherwise the app already works through the
     companies on its own, one at a time, so jobs appear gradually over the first 10-20 minutes (**Settings → Schedule**).
   - **Status**: shows which sources worked. Failed ones usually need a small fix (see [Troubleshooting](TROUBLESHOOTING.md)).

## 2. The Jobs page (dashboard)

- **Top strip**: new jobs in 24 h, strong matches (score 75+), starred, applied/interviewing, last scrape time, *Scrape now*.
- **Tabs**: Open (new + starred) · Starred · Applied · Interview · Rejected · Hidden · All.
- **Filters**: search text, company, level (junior/medior/unspecified), pay (OK or everything), minimum score, sort order.
- **Each row**: match score ring, title, company, location, posted date, source, a **pay label**, level and matched skills.
  Buttons: **Apply ↗** (opens the company's own page and then asks "mark as applied?"), **Details**, **★** star, **✕** hide.
- **"How to read this list"** (collapsible) explains scores and pay labels in place.

### The score (0-100)

| Points | For |
|---|---|
| +15 | junior or medior wording in the title (+5 if the level isn't stated) |
| up to +25 | skills from your profile found in the posting (weighted; extra if in the title) |
| +15 / +15 / +10 | pay stated / typical pay found / assumed (big company). Unknown pay at an unlisted company: -10 |
| +5 | big-company exception applied (pay under your usual minimum) |
| up to +10 | freshness (posted within 3 days +10, within 14 days +5) |
| +5 | experience requirement of 2 years or less |

Open a job to see its **"Why this score"** list.

### Pay labels

Most postings don't state a salary, so the app works down this list until it finds something:

| Label | Meaning |
|---|---|
| `€95k-120k` | **Stated** in the posting. Below your minimum → dropped (unless the big-company exception applies). |
| `≈ €105k-125k typical` | **Typical pay** for that company + level: the reported-pay table (`jobhunter/salary_benchmarks.yaml` plus your own entries), otherwise a quick web search of Glassdoor / Levels.fyi / Indeed result snippets (cached 45 days). Counts as fine when the **midpoint** of the range reaches your minimum. |
| `🌱 big co, under 90k` | Below your usual minimum but at/above the **big-company floor** (default €70k in the Netherlands) at a **Tier 1** company: kept on purpose for the career potential. Applies to any job title. |
| `💰 likely 90k+ (assumed)` | No data found, but it's a Tier 1 company, so assumed to pay well. A guess. |
| `⚠ typically €x-y` | Data says it pays too little. Hidden by default. |
| `pay unknown` | No data, not a Tier 1 company. Hidden by default (Pay → Everything shows them). |

Caveats: reported figures (Glassdoor, Levels.fyi, TechPays) are mostly **total compensation** (base + bonus + stock),
self-reported and sometimes old, so base salary is lower. Glassdoor itself blocks bots and forbids scraping; it is only
read through search-result snippets. If the search engine shows a bot check, lookups pause for that run.

## 3. Applying

The app **does not submit applications for you**: forms differ per company, sit behind logins and captchas, and
auto-submitting could send the wrong thing in your name. It makes applying quick instead:

1. **Apply ↗** (or *Open application page* on the job page) opens the company's own page.
2. On the job's **Details** page copy the **motivation letter** (see section 9; always read and personalise it) and use **My snippets** to copy your name, email, phone, LinkedIn and pitch into form fields.
3. Press **✓ I applied**. The job moves to the *Applied* tab with the date. Use *Interview* / *Rejected* as things progress,
   and the **Notes** box for contacts and dates.

**Hide** (✕) dismisses a job for good: it stays in the Hidden tab and is never looked at again. **Delete** (🗑, on a job's page
or in the Hidden tab) forgets a job completely: if it is still listed on the company's site, the next refresh picks it up again as
a new job and re-checks it. **CSV** (top right) exports the list.

## 4. Settings

All under **Settings** in the top bar, saved immediately, each page has *Reset to defaults*. Full list with defaults:
[SETTINGS.md](SETTINGS.md).

| Page | Use it to |
|---|---|
| Profile & motivation letters | Your details, ambition, achievements, CV upload, skills and weights |
| Matching | Countries, minimum pay per country (and the lower big-company minimum), which tiers count, max years asked, max age, remote |
| LinkedIn search | On/off, search terms, experience levels, time window, pages, politeness delay |
| Pay lookups | Web search for typical pay on/off and limits; your own pay data per company |
| AI agent | Optional letter writer: Claude, any OpenAI-compatible service, or your own local model |
| Schedule | Automatic scraping on/off and interval |
| Advanced | Title rules (regular expressions), browser options |

## 5. Companies

**Companies** lists the employers searched directly (their own career-site feeds). For each: name, **tier**
(1 = big / high-paying; 2 = decent) and how to read its career site. **Test** fetches the first postings so you know at
once whether it works; **Pause** skips a company without deleting it; **Edit**/**✕** change or remove it; *Restore
default list* undoes your edits. Jobs from LinkedIn are found in addition, even for employers not on the list.

To **add a company**: *+ Add a company*, pick the career-site type and follow the hint shown (e.g. for Greenhouse the
board name is the last part of `boards.greenhouse.io/<board>`). Supported types: Greenhouse, Lever, Ashby,
SmartRecruiters, Workday, Jibe (e.g. Booking.com), Amazon, Uber, and **any other site** via the headless browser.

### Sites without a feed (headless browser)

Google, Meta, Apple and Microsoft don't offer a public feed, so they use the *browser* type: the app opens the search page
with your filters (put them in the address), finds job links by URL pattern, pages through results and opens each relevant
job for the description. It needs an optional install:

```bash
pip install -r requirements-browser.txt && playwright install chromium     # or: sudo apt install chromium
```
(then set *Settings → Advanced → Browser program* to `/usr/bin/chromium` if you used apt) and a restart of the app.
Chromium needs roughly 300-500 MB RAM while running: use a Pi 4/5 with 4 GB or more. Without it these companies are
skipped with a note in the log.

The job-link patterns for Google/Meta/Apple/Microsoft are untested guesses (see Troubleshooting): use **Test**, and adjust
`link_pattern` if it finds nothing.

## 6. Status page

Shows the last result of each source (jobs listed / relevant / new, or the error), the schedule, and quick links to the same
career sites for searching manually.

## 7. Privacy and limits

- Everything stays on your machine: jobs, notes, settings in a local SQLite file (`data/jobs.db`).
- The dashboard has **no login**. Keep it on your home network and never port-forward it.
- LinkedIn's terms forbid scraping. The app uses only the logged-out public search with low volume and delays, stops when
  throttled, and never uses your account. It can still break or get your IP blocked for a while; turn it off in
  *Settings → LinkedIn search* if you prefer not to risk it.
- Company feeds change without notice. A failed source never stops the others.

## 8. How it stays light, and what counts as "new"

The app is meant to run quietly on a shared Raspberry Pi:

- **Once per cycle, one company at a time.** Every company is refreshed once every *N* hours (default 24, *Settings →
  Schedule*), evenly spread: with 22 companies that is about one an hour. A brand-new install or a newly added company is
  scraped right away, one after the other. It runs at the lowest CPU priority with pauses between requests, so it simply
  takes longer rather than using much.
- **Only new postings cost anything.** A posting that is already saved is only marked "still listed" (this is also how closed
  postings disappear). Nothing is fetched or re-scored for it. A posting that was looked at and rejected (too senior, asks
  too many years, pays too little, ...) is remembered for 30 days so it isn't fetched again either.
- **How "already saved" is decided.** Same company site + same posting ID = same opening. The same title posted again
  *with a new ID* is a **new opening** (companies re-open roles for a new batch). With the same ID or no ID, the **posting
  date** decides: a posting more than *N* days after the saved one (*Settings → Matching → "Treat a re-posted role as new
  after"*, default 30) is a new batch; close dates mean the same opening. The same role found on LinkedIn and on the company
  site is one job (matched on title/company/city + date). Dates a source can't vouch for (e.g. a "last edited" stamp) are
  never used to call something a re-post.
- **Changing a rule re-scores what you already have** (locally, no network): saving *Matching*, *Profile*, *Pay lookups* or
  *Advanced* settings re-applies them to saved jobs (those that no longer fit are moved to *Hidden*, never starred/applied
  ones) and gives previously rejected postings a fresh look at the next refresh.
- **To re-check one job yourself**, delete it (🗑): it returns as a new job if it is still listed.

Running it in Docker adds resource limits so the Pi's other services always win; see [DOCKER.md](DOCKER.md).

## 9. Motivation letters

Each job page has a letter draft built from **your own facts**, not boilerplate. Fill in *Settings → Profile → "Material for
motivation letters"* once: your **ambition** (where you want to grow, in your words), your **current title and employer**, and
a handful of concrete **achievements** (`tags :: English sentence || Nederlandse zin`, with real numbers and outcomes).

For every posting the app then:

1. **reads it**: language (English or Dutch), one concrete responsibility line (quoted as written), the skills it names that you
   rate solid or core, the industry (payments, travel, logistics, ...), and a technology it asks for that you do **not** list;
2. **picks the two achievements** that overlap most with the posting and uses them in your own words;
3. **only names skills that appear in those achievements' tags**, and only claims daily use of skills weighted 2 or 3;
4. **states a missing skill honestly** ("I have not used Kafka in production yet ...", naming your closest skill if you have one);
5. **ties your ambition to the role**, and ends with one concrete next step;
6. leaves **one [bracketed] sentence for you**: why *this* company in particular.

Buttons: **↻ Another angle** (same facts, different wording and a different mix of achievements), **language** (automatic, English,
Dutch), **Copy letter** (warns while the bracket is still there), and **Copy prompt for an AI assistant**: a prompt containing the
rules, your facts and the posting that you can paste into any AI chat (free) for a polished version.

**About "AI detection":** employers increasingly screen for generic text, and nothing can promise to pass that. What helps is what
this builds on: specific details, real numbers, your own words. Fill the bracketed sentence, change a phrase or two to sound like you,
and avoid sending near-identical letters to many companies. Stock phrases ("passionate", "fast-paced", "I am writing to apply" ...) are
never used (a test checks this).

## 10. Several countries and currencies

*Settings → Matching → Countries to search*: tick one or more (Netherlands is the default). Then:

- every source searches all ticked countries (LinkedIn once per country; company feeds are filtered by each job's location);
- the Jobs page gets a **Country** filter and a flag on each job; jobs from a country you later untick are hidden, not deleted;
- the **Minimum pay** table gets **one row per ticked country the moment you tick it**, with two columns: *Minimum pay* and
  *Minimum for big companies*, both **in that country's own currency** (€, £, CHF, SEK, ...). A new row is prefilled with your
  existing minimum converted to that currency (e.g. €90k → about £78k), so you only adjust it. Unticking a country hides its row
  but remembers the numbers;
- pay in any currency is converted with the **exchange rates in Settings → Advanced** (approximate defaults) and shown in the job's own currency;
- Dutch holiday pay (+8% on monthly salaries) is added **only** for jobs in the Netherlands;
- jobs with an unknown country (e.g. "Remote") use the first ticked country's row;
- "Any other site" (browser) entries use the country in their own address: add one per country; the bundled pay table is Netherlands data.

More countries means more requests and a slower refresh, so tick only the ones you will actually apply in.

## 11. How salaries are calculated

Everything is converted to a **yearly gross EUR-equivalent** before it is compared with your minimum (hover over a pay label to see the calculation):

| Posting says | Result |
|---|---|
| `€5.500 - €7.000 per maand` / `€5,500/mo` / `5500 en 7000 euro per maand` | monthly × 12 × 1.08 (holiday pay, NL only): €71.3k - €90.7k |
| `€ 6.000 p.m. incl. vakantiegeld` | × 12 only (already included) |
| `€6.000 per maand plus 10% bonus` / `€5.000 per maand + 13e maand` | the bonus / 13th month is added; nothing is added when no bonus is stated |
| `€4.500 - €6.000` (no period) | read as monthly, noted in the tooltip |
| `€80k - €100k per year`, `€75,000.00/yr` | used as is |
| `£60,000 - £75,000`, `CHF 100k - 120k` | converted to EUR with the exchange rates setting |
| `€45 per hour`, `sign-on bonus €10.000`, `relocation allowance €500` | not a salary: ignored |

If a posting states no salary, a typical figure is looked up (reported-pay table, then a web search) and **retried on later runs**
whenever lookup budget is available. Jobs whose pay is still unknown are **shown, marked "pay unknown"**
(*Settings → Matching → "Show jobs whose pay I couldn't find"*, on by default), because your minimum only applies when a salary is known.

## 12. Your CV

*Settings → Profile → Your CV*: upload a **PDF** (text-based), **Word (.docx)**, **.txt** or **.md** file (max 5 MB). The original is kept on
your own drive (next to the database) and its text is read and shown in an editable box: fix odd line breaks or remove anything you'd rather not
share. Scanned, image-only PDFs can't be read: paste the text into the box instead. The CV text is used only by the AI agent (section 13).

## 13. AI agent: "Agent Customize" (optional)

*Settings → AI agent*: switch it on, choose the **type of service** and fill in the details:

| Type | Fill in | Notes |
|---|---|---|
| **Claude (Anthropic API)** | API key (from console.anthropic.com), optional model | Default model `claude-opus-5-5`; `claude-sonnet-5-5` is cheaper. |
| **OpenAI-compatible** | Server address (up to `/v1`), model name, API key if the service wants one | Works with OpenAI, OpenRouter, Together, Groq, **and models on your own hardware**: Ollama (`http://host:11434/v1`), LM Studio, llama.cpp server, vLLM. Local models need no key. |

Inside Docker, `localhost` is the container itself: for a model running on the Pi or another machine use that machine's LAN address
(e.g. `http://192.168.1.20:11434/v1`). Small local models can be slow on a Pi: raise *Give up after* if letters time out.

Then every job page gets an **✨ Agent Customize** button next to the built-in letter. Press it and the app sends one request containing everything
needed: the job posting, your profile, skills, ambition, achievements and your **CV text**, plus anything you typed in the optional
*"tell the agent..."* box (for example why you like the company). The reply fills the letter box so you can check and edit it;
**↩ Back to the template draft** restores the earlier text.

How the answer is kept to the letter only:
- the prompt is strict: the reply must be exactly one `<letter>` block with no greeting, explanation, markdown or notes, the length, structure
  and language are fixed, and it may only use facts you provided (no invented employers, numbers or tools); a skill the job wants that you don't
  have is stated honestly; stock phrases are forbidden;
- the app only keeps what is inside the `<letter>` tags and throws everything else away; if the model ignored the format, the usual "Here is your
  letter..." / "Let me know if..." lines and markdown are stripped, and an answer that doesn't look like a letter is rejected with a message.

**Privacy and cost.** Nothing is sent unless you press the button, and then only to the address you configured (Anthropic's API, your chosen service, or your own machine).
Hosted services bill per use (typically a few cents per letter; check current pricing and set a **spending limit** on the key); a model on your own network is free.

**Keeping the key safe.** The key is stored in the app's database on your drive, is **write-only** (never shown again or included in any page,
leave the box empty to keep it, tick *Remove* to delete it) and never appears in error messages. To keep it out of the database entirely, set the
`JOBHUNTER_AI_API_KEY` environment variable (Docker: put it in `.env`) and leave the box empty. Remember the dashboard has **no login**: anyone on
your home network who can open it can press the button and use your credits, so keep it on a trusted network and never port-forward it.
