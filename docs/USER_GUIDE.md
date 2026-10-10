# User guide

Job Hunter finds **software jobs in the Netherlands** on company career sites and LinkedIn, removes what doesn't
fit you, ranks the rest, and gives you one dashboard to review, apply and keep track. It runs on your own machine
(designed for a Raspberry Pi) and costs nothing: no paid APIs, no accounts.

The dashboard also has a built-in **Help** page covering the same ground in short form.

## 1. First start

1. Open the dashboard: `http://<your-pi>.local:8585` (port is set in `config.yaml`, see [Settings](SETTINGS.md)).
2. The **Getting started** checklist at the top of the Jobs page walks you through:
   - **Settings → Profile**: name, email, phone, LinkedIn, a 2-3 sentence pitch and your **skills with weights**
     (1 = nice to have, 2 = solid, 3 = core stack). Skills decide how jobs rank; the rest fills the cover letter.
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
| `🌱 big co, under 90k` | Below your usual minimum but at/above the **big-company floor** (default €70k) at a **Tier 1** company: kept on purpose for the career potential. Applies to any job title. |
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
2. On the job's **Details** page copy the **cover-letter draft** (built from your profile and template; always read and
   personalise it) and use **My snippets** to copy your name, email, phone, LinkedIn and pitch into form fields.
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
| Profile & cover letter | Your details, pitch, cover-letter template, skills and weights |
| Matching | Minimum salary, big-company floor & which tiers count, max years asked, max age, remote, what "in the Netherlands" means |
| LinkedIn search | On/off, search terms, experience levels, time window, pages, politeness delay |
| Pay lookups | Web search for typical pay on/off and limits; your own pay data per company |
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
