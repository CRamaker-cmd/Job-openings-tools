# Job Hunter

A small self-hosted job board for a Raspberry Pi. It collects **junior / medior software-engineering
jobs in the Netherlands** from LinkedIn and from big-tech career sites, drops everything that is too
senior or pays below your minimum, ranks what's left against your skills, and gives you a web page
to review, apply and track.

## What it does

- **Sources**
  - Company career sites through their public JSON feeds: Greenhouse, Lever, Ashby, SmartRecruiters,
    Workday, Jibe (Booking.com) + Amazon and Uber's own APIs. Add a company with one line of YAML.
  - LinkedIn's public (logged-out) job search - low volume, with delays; see the note below.
  - Google, Meta, Apple, Microsoft & co. have no usable public feed, so the *Sources* page has
    pre-filtered saved-search links for them.
- **Filtering** - drops senior/staff/principal/lead/manager, interns, non-software roles, jobs outside
  NL, postings asking for more than `max_years_required` years, and postings that *state* a salary
  below `min_salary` (reads EUR ranges incl. monthly figures from the description).
- **Ranking (0-100)** - junior/medior wording, your skills (weighted, from `config.yaml`), stated
  salary, company tier, freshness. Same job on LinkedIn and the company site is merged (company link wins).
- **Pay column** - `€95k-120k` (stated in the posting), `💰 likely 90k+` (company is in your tier-1
  list) or `pay unknown`. The default view hides *unknown*; switch the "Pay" filter to see them.
- **Applying** - **Apply ↗** opens the posting and asks if you want to mark it applied. Each job page
  has a cover-letter draft built from your profile (copy button), notes, and status tracking
  (star / applied / interview / rejected / hide). *My snippets* has copy-buttons for form fields.
- **Pi-friendly** - SQLite, no browser/Selenium, ~tens of MB RAM. A systemd timer scrapes every 6 h.

## Setup (Raspberry Pi)

```bash
git clone https://github.com/CRamaker-cmd/Job-openings-tools && cd Job-openings-tools
cp config.example.yaml config.yaml && nano config.yaml   # your name/email/phone/LinkedIn + pitch
./deploy/install.sh                                       # venv, systemd web service + 6-hourly timer
.venv/bin/python -m jobhunter check                       # IMPORTANT: which company feeds respond?
```

Open `http://<pi-hostname>.local:8080`. There is no login - keep it on your home network, don't port-forward it.

Manual use: `python -m jobhunter scrape [--only adyen]`, `serve`, `check`, `export > jobs.csv`.

## Tuning

Everything lives in `config.yaml`: `min_salary`, `max_years_required`, `include_remote`, skills and
weights, LinkedIn queries, companies (`tier: 1` = pays 90k+, `disabled: true` to skip one).
To find a company's board: Greenhouse `boards.greenhouse.io/<board>`, Lever `jobs.lever.co/<site>`,
Ashby `jobs.ashbyhq.com/<board>`, Workday `<tenant>.<wdN>.myworkdayjobs.com/<site>`.

## Honest caveats

- The company slugs/endpoints in `config.example.yaml` were written from public knowledge and **could not
  be tested live** (the dev sandbox blocks job sites). Parsers are unit-tested on API-shaped fixtures;
  run `check` on the Pi and fix/disable whatever fails. Failing sources never break the others.
- Company feeds change without notice; the *Sources* page shows the last result per source.
- **LinkedIn's terms forbid scraping.** This uses only the logged-out endpoints, a few requests per run
  with delays, and stops on throttling. It never uses your account/cookies - keep it that way. It may break
  or get the Pi's IP temporarily blocked; the company-site sources work without it (`linkedin.enabled: false`).
- "Likely 90k+" is a guess based on the company, not a fact. Junior/medior bands at some big techs in NL
  are below 90k - check the posted range (EU pay-transparency rules mean many postings now have one).
- The cover letter is a template. Read and personalise it before sending.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest
```
