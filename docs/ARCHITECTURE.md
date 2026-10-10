# Architecture (for developers)

```
 sources ──► scrapers ──► prefilter ─► enrich (details) ─► evaluate ─► (pay estimate) ─► evaluate ─► SQLite ──► Flask UI
 (feeds, browser, LinkedIn)   title+location only   description      rules + score       salary.py                   settings, companies, help
```

Pure Python 3.11+, SQLite, Flask + waitress, `requests` + BeautifulSoup; Playwright is an optional extra.
No frontend build step; templates are server-rendered with a few lines of vanilla JS.

## Modules (`jobhunter/`)
| Module | Role |
|---|---|
| `config.py` | Defaults, `load_base()` (defaults + `config.yaml`) and `load_config()` (base + dashboard overrides from the DB). |
| `settings.py` | **The settings spec** (`SECTIONS` of `Field`s): drives the forms, parsing/validation and the generated docs; storage of overrides (`settings` table, one row per dotted path; values equal to the base aren't stored). |
| `companies.py` | Per-career-site-type field spec and validation for the Companies page. |
| `models.py` | `RawJob` dataclass and `fingerprint()` (company+title+city) used to de-duplicate across sources. |
| `filters.py` | Pure functions: `title_ok`, `location_ok`, `parse_salary`, `years_required`, `evaluate()` → `Evaluation` (reject reason, score, level, pay confidence, reasons). Everything about "is this job relevant / how good". |
| `salary.py` | `Estimator`: reported-pay table (`salary_benchmarks.yaml`) → cached web-search lookup (DuckDuckGo result snippets, parsed for EUR figures) → `None`. |
| `scrapers/` | `Scraper` base (`fetch()` yields `RawJob`, optional `enrich()`); `ats.py` (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Jibe), `custom.py` (Amazon, Uber), `linkedin.py` (public guest search), `browser.py` (Playwright, link-pattern based). `REGISTRY` in `__init__.py` maps the `ats:` name to a class. |
| `runner.py` | Orchestrates one scrape: for each scraper → prefilter → enrich → evaluate → estimate pay → upsert; records per-source results; one failing source never stops the rest. |
| `db.py` | SQLite access: jobs, runs, salary cache, settings; `upsert` merges duplicates (a company-site copy replaces a LinkedIn copy, status/notes are kept). |
| `scheduler.py` | `is_due()` + a daemon thread inside the web process that triggers scrapes per *Settings → Schedule*. |
| `web/app.py` | Flask app factory `create_app(cfg, scheduler_enabled)`: dashboard, job pages, settings, companies, help, status, CSV. Holds the **live `cfg` dict**; saving a setting mutates it, so changes apply instantly. |
| `cli.py` | `scrape`, `check`, `serve`, `export`. |

## Key design decisions
- **One live config dict** shared by the web app, the scheduler thread and scrape runs; dashboard edits mutate it and persist to the DB so the separate CLI process sees the same values (`load_config`).
- **Rules are data, not code**: seniority, role and location rules are regex lists in settings; `filters.py` only applies them.
- **Prefer public JSON feeds** over HTML scraping; the browser scraper finds job links by URL pattern because class names on big sites are obfuscated and change.
- **Be a polite client**: delays, retry/backoff, caching of salary lookups, stop on throttling, a per-run cap on web searches.
- **Honest data**: every pay figure carries its source (`stated | estimated | assumed | growth | low | unknown`) shown in the UI.

## Data model (SQLite)
`jobs` (one row per de-duplicated job: fields, `score`, `pay_confidence`, `est_min/max`, `pay_source/note`, `status`, `notes`, `applied_at`, `active`) ·
`runs` (per-source result of each scrape) · `salary_cache` (web lookups) · `settings` (dashboard overrides). Schema upgrades are additive (`DB._migrate`).

## Adding things
- **A career-site type**: subclass `Scraper` (`fetch` → `RawJob`s, optionally `enrich`), register it in `scrapers/__init__.py`, add its form fields to `companies.ATS`, add a parser test with a sample payload.
- **A setting**: add a `Field` in `settings.SECTIONS`, read it via `cfg[...]`, run `python tools/gen_settings_doc.py`. The form, validation and docs follow automatically.
- **A pay data point**: edit `salary_benchmarks.yaml` (or use *Pay lookups* in the UI).

## Tests
`python -m pytest` (≈55 tests): filters/salary parsing, per-source parsers on sample payloads, the whole pipeline into SQLite, web routes (settings, companies, applying), scheduler, the browser scraper against a local JS-rendered page (skipped without Playwright/Chromium; set `JOBHUNTER_CHROMIUM`), and a check that `docs/SETTINGS.md` is up to date.
Network access is never needed. Live endpoint checks are done on the target machine with `python -m jobhunter check`.
