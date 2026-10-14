"""Settings you can edit from the dashboard.

How it fits together
--------------------
* ``config.yaml`` (+ built-in defaults) is the *base*.
* Values changed on the dashboard are stored in the ``settings`` table of the SQLite DB, one row per
  setting (``path`` like ``search.min_salary``), and layered on top of the base by ``load_config``.
  Both the web server and ``python -m jobhunter scrape`` therefore see the same settings.
* A setting equal to the base value is not stored, so "Reset to defaults" is just deleting rows.

Each dashboard page is described by a ``Section`` made of ``Field`` objects; the same spec drives the
form, the parsing/validation and the help text, so adding a setting is a one-entry change here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .countries import COUNTRIES


# ---------------------------------------------------------------- spec
@dataclass
class Field:
    path: str                     # dotted path into the config, e.g. "search.min_salary"
    label: str
    kind: str                     # secret | pay_table | text | textarea | int | float | bool | lines | regex_lines | choices | select | skills | benchmarks | fx | achievements
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = ""
    choices: list = field(default_factory=list)   # [(value, label)] for kind == "choices"
    group: str = ""               # sub-heading shown above the field
    placeholder: str = ""
    required: bool = False        # a "choices" field must have at least one box ticked


@dataclass
class Section:
    id: str
    title: str
    intro: str
    fields: list[Field]


SECTIONS: list[Section] = [
    Section("profile", "Profile & motivation letters",
            "Your details fill the copy-paste snippets. The rest is the raw material for the motivation letter on every job page: "
            "the more of your own facts it has, the more personal and specific each letter is. Skills also drive the match score.",
            [
                Field("profile.name", "Full name", "text", group="About you"),
                Field("profile.email", "Email", "text"),
                Field("profile.phone", "Phone", "text"),
                Field("profile.linkedin", "LinkedIn URL", "text"),
                Field("profile.github", "GitHub URL", "text"),
                Field("profile.location", "Location", "text", placeholder="Almere, Netherlands"),
                Field("profile.years_experience", "Years of experience", "int", min=0, max=40),
                Field("profile.pitch", "Short pitch (for application forms)", "textarea",
                      help="2-3 sentences, shown on the 'My snippets' page for forms that ask for a summary."),
                Field("profile.job_title", "Your current job title", "text", group="Material for motivation letters",
                      placeholder="Medior Software Engineer", help="Used as 'As a <title> at <employer>...'."),
                Field("profile.employer", "Your current employer", "text"),
                Field("profile.ambition", "Your ambition", "textarea",
                      help="The heart of every letter: where you want to grow and what kind of work you want to do more of, in your own "
                           "words (1-2 sentences, first person). Specific beats grand: 'I want to own the design of high-traffic "
                           "payment services' says more than 'I want to grow'."),
                Field("profile.ambition_nl", "Your ambition in Dutch (optional)", "textarea",
                      help="Used when a letter is written in Dutch. Empty = the English text is used."),
                Field("profile.achievements", "Concrete achievements", "achievements",
                      help="One per line:  tags :: English sentence || Nederlandse zin  (the Dutch part is optional). "
                           "Tags are the skills and topics involved, e.g.  API design, REST, C#, Azure :: I led the development of ... "
                           "Each letter uses the two achievements that overlap most with the posting, in your own words, and only names "
                           "skills that appear in their tags. Use real numbers and outcomes: they are what makes a letter specific."),
                Field("profile.letter_language", "Letter language", "select",
                      choices=[("auto", "Automatic: match the posting's language"), ("en", "Always English"), ("nl", "Always Dutch")]),
                Field("profile.cv_text", "CV text", "textarea", group="Your CV",
                      help="Read from the file you upload above; edit it freely (fix odd line breaks, remove what you'd rather not share). "
                           "It is sent to your AI agent only when you press 'Agent Customize' on a job, and never anywhere else."),
                Field("profile.skills", "Skills and weights", "skills", group="Skills",
                      help="One per line as  Skill: weight  (weight 1 = nice to have, 2 = solid, 3 = your core stack). "
                           "Matched against the job title and description. Letters only say you USE skills weighted 2 or 3."),
            ]),
    Section("matching", "Matching: countries, pay, experience",
            "What counts as a job worth showing. Jobs that fail these rules are not saved at all.",
            [
                Field("search.countries", "Countries to search", "choices", required=True,
                      choices=[(c.code, f"{c.flag} {c.name}") for c in COUNTRIES.values()], group="Where",
                      help="Tick one or more. Every source searches all ticked countries (LinkedIn once per country), and the "
                           "Jobs page gets a country filter. More countries = more requests = a slower refresh. "
                           "Company feeds are filtered by each job's location; 'Any other site' (browser) entries use the "
                           "country in their own address, so add one per country."),
                Field("search.include_remote", "Include remote jobs", "bool",
                      help="Off = only jobs located in the ticked countries. On = also keep jobs whose location says 'Remote' "
                           "(from any country)."),
                Field("search.country_keywords", "Extra place words (optional)", "lines",
                      help="One per line. Extra words that also count as 'in one of my countries', e.g. a small town. "
                           "The main cities and names of every country are already built in."),
                Field("search.pay_by_country", "Minimum pay per country", "pay_table", group="Pay",
                      help="One row per country you search, in that country's own currency, yearly gross. <b>Minimum</b>: postings that "
                           "STATE less are dropped (when no salary is stated, pay is estimated instead, see 'Pay lookups'). "
                           "<b>Big companies</b>: the lower minimum for companies you marked as 'big' on the Companies page: for them "
                           "any job title may pay somewhat less, because of the career potential. Monthly salaries are converted to "
                           "yearly first (see 'How salaries are calculated')."),
                Field("search.big_company_tiers", "Which company tiers count as 'big'", "choices",
                      choices=[(1, "Tier 1: big / high-paying (Booking, Adyen, Amazon, ...)"),
                               (2, "Tier 2: decent, but check the range")],
                      help="A company's tier is set on the Companies page. LinkedIn jobs from companies "
                           "you haven't added there are never treated as big. Untick all to turn the lower big-company minimum off."),
                Field("search.show_unknown_pay", "Show jobs whose pay I couldn't find", "bool",
                      help="Most postings state no salary and a web search doesn't always find one. On (recommended): such jobs are "
                           "listed, marked 'pay unknown' and ranked a little lower, because your minimum only applies when a "
                           "salary is known. Off: they are hidden until a pay estimate is found."),
                Field("search.vacation_allowance_pct", "Holiday pay added to monthly salaries", "int", min=0, max=20, unit="%",
                      group="How salaries are calculated",
                      help="Monthly gross x 12, plus this holiday allowance (Dutch vakantiegeld is 8 %), unless the posting says "
                           "it is already included. Set 0 to turn off."),
                Field("search.add_bonus", "Add stated bonuses", "bool",
                      help="Adds a bonus the posting actually states (e.g. '10% bonus', 'bonus of €5.000', '13th month'). "
                           "One-off sign-on or relocation money is never added, and nothing is added when no bonus is stated."),
                Field("search.max_years_required", "Maximum years of experience asked", "int", min=0, max=20,
                      unit="years", group="Experience",
                      help="Postings that ask for more years of experience than this are dropped. "
                           "Title words like 'Senior', 'Staff', 'Lead' are filtered separately (see Advanced)."),
                Field("search.max_age_days", "Ignore postings older than", "int", min=1, max=365, unit="days"),
                Field("search.repost_gap_days", "Treat a re-posted role as new after", "int", min=1, max=365, unit="days",
                      help="Companies re-open the same role for a new batch. A posting with the same title and company that "
                           "appears more than this many days after the one already saved counts as a NEW opening and is "
                           "checked again. A new posting ID always counts as new. Older postings are never re-fetched."),
            ]),
    Section("linkedin", "LinkedIn search",
            "LinkedIn's public (logged-out) job search, used to find jobs at companies that aren't on your Companies "
            "list. It searches each country ticked in Settings → Matching separately. It never uses your LinkedIn account. "
            "LinkedIn's terms forbid scraping, so keep volume low.",
            [
                Field("linkedin.enabled", "Search LinkedIn", "bool"),
                Field("linkedin.queries", "Search terms", "lines",
                      help="One per line. Each is searched separately, so more terms = more requests = slower."),
                Field("linkedin.experience_levels", "LinkedIn experience levels", "choices",
                      choices=[(1, "Internship"), (2, "Entry level"), (3, "Associate"), (4, "Mid-Senior level"),
                               (5, "Director")]),
                Field("linkedin.window_days", "Only jobs posted in the last", "int", min=1, max=30, unit="days"),
                Field("linkedin.pages_per_query", "Result pages per search term", "int", min=1, max=10,
                      help="25 jobs per page."),
                Field("linkedin.delay_seconds", "Pause between requests", "float", min=1, max=30, unit="seconds",
                      help="Keep this at 2 seconds or more to stay polite. The scraper stops by itself if LinkedIn pushes back."),
            ]),
    Section("pay", "Pay lookups (when a job doesn't state a salary)",
            "Most postings don't show a salary. For those, the app looks up what is typically paid for that "
            "company and level: first the reported-pay table, then a quick web search of Glassdoor / Levels.fyi / "
            "Indeed result snippets, and for big companies it may assume.",
            [
                Field("salary.online_lookup", "Search the web for typical pay", "bool",
                      help="Free, no account needed. Results are cached so only a few searches happen per run."),
                Field("salary.max_lookups_per_run", "Max web searches per scrape", "int", min=0, max=200),
                Field("salary.cache_days", "Remember results for", "int", min=1, max=365, unit="days"),
                Field("salary.delay_seconds", "Pause between searches", "float", min=0, max=30, unit="seconds"),
                Field("salary.benchmarks", "Your own pay data", "benchmarks",
                      help="Overrides everything else. One per line:  Company | junior or medior | low | high  "
                           "(yearly €, e.g.  Mollie | medior | 75000 | 95000 )."),
            ]),
    Section("ai", "AI agent (optional)",
            "Lets a Claude model write a fully customised motivation letter for a job: press <b>Agent Customize</b> on a job page and the "
            "letter box is filled with the result for you to check. <b>What is sent:</b> only when you press that button, the job posting, "
            "your profile, achievements and CV text go to Anthropic's API. Nothing is sent otherwise. <b>Cost:</b> pay-per-use on your own "
            "Anthropic account, typically a few cents per letter (check Anthropic's current pricing); set a spending limit on the key.",
            [
                Field("ai.enabled", "Enable the AI agent", "bool",
                      help="Adds the Agent Customize button to every job page (needs an API key below)."),
                Field("ai.api_key", "Anthropic API key", "secret",
                      help="Create one in the Anthropic Console (console.anthropic.com). It is stored in this app's database on your own "
                           "drive, never shown again and never included in any page. Prefer not to store it? Leave this empty and set the "
                           "JOBHUNTER_AI_API_KEY environment variable instead (docker: in your .env file). Leave the box empty to keep the saved key."),
                Field("ai.model", "Model", "text", placeholder="claude-opus-5-5",
                      help="Default claude-opus-5-5 (most capable). Cheaper options exist, e.g. claude-sonnet-5-5; use any model id your key can access."),
            ]),
    Section("schedule", "Schedule",
            "How the app keeps jobs fresh by itself, quietly in the background. You can always press 'Scrape now' to refresh everything immediately.",
            [
                Field("schedule.enabled", "Refresh jobs automatically", "bool"),
                Field("schedule.every_hours", "Refresh every company once every", "int", min=1, max=168, unit="hours",
                      help="A full refresh once a day (24) is plenty: job boards rarely change faster than that."),
                Field("schedule.spread", "Spread the work evenly", "bool",
                      help="On (recommended): one company at a time, spread over the whole period. With 22 companies "
                           "and 24 hours that is one every ~65 minutes, so the machine is never busy for long. "
                           "Off: everything is refreshed in one go when the period is up."),
                Field("schedule.low_priority", "Run at lowest CPU priority", "bool", group="Go easy on the machine",
                      help="Recommended when the machine also does other work (media server, Pi-hole, ...). "
                           "Scraping then only uses CPU that nothing else wants. It just takes longer."),
                Field("schedule.pause_between_sources", "Rest between companies", "int", min=0, max=600,
                      unit="seconds", help="Spreads the work out so it never runs as one big burst."),
                Field("schedule.pause_between_requests", "Pause between page requests", "float", min=0, max=10,
                      unit="seconds"),
            ]),
    Section("advanced", "Advanced: title rules & browser",
            "Regular expressions (case-insensitive, one per line) that decide which job titles are considered. "
            "You usually don't need to change these; the defaults are tuned for junior/medior software roles.",
            [
                Field("search.title_include", "Title must match one of", "regex_lines",
                      help="Jobs whose title matches none of these are not software roles.", group="Title rules"),
                Field("search.title_exclude", "Skip titles matching", "regex_lines",
                      help="Interns, sales engineers, hardware roles, managers, ..."),
                Field("search.title_too_senior", "Skip titles that are too senior", "regex_lines",
                      help="Senior, staff, principal, lead, architect, 'Engineer III', ..."),
                Field("search.title_junior_markers", "Title marks a junior role", "regex_lines"),
                Field("search.title_medior_markers", "Title marks a medior role", "regex_lines"),
                Field("search.fx_to_eur", "Exchange rates to euro", "fx", group="Other currencies",
                      help="Salaries in other currencies are converted with these rates so they can be compared with your minimum. "
                           "One per line as  GBP: 1.15  (1 unit of that currency in euro). Approximate is fine."),
                Field("browser.executable", "Browser program (optional)", "text", group="Browser scraping",
                      help="Path to Chromium, e.g. /usr/bin/chromium on a Raspberry Pi. Empty = Playwright's own download."),
                Field("browser.delay_seconds", "Pause between page loads", "float", min=0, max=30, unit="seconds"),
            ]),
]
SECTION_BY_ID = {s.id: s for s in SECTIONS}


# ---------------------------------------------------------------- dotted-path helpers
def get_path(cfg: dict, path: str, default=None):
    cur: Any = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(cfg: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = cfg
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


# ---------------------------------------------------------------- value <-> form text
def to_text(f: Field, value) -> str:
    """Config value -> text shown in the form."""
    if value is None or f.kind == "secret":
        return ""
    if f.kind in ("lines", "regex_lines"):
        return "\n".join(str(v) for v in value)
    if f.kind == "skills":
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    if f.kind == "achievements":
        return "\n".join(", ".join(a.get("tags", [])) + " :: " + a.get("en", "") + (" || " + a["nl"] if a.get("nl") else "") for a in value)
    if f.kind == "fx":
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    if f.kind == "benchmarks":
        return "\n".join(f"{c} | {lvl} | {lo} | {hi}" for c, d in value.items()
                         for lvl, (lo, hi) in d.items() if lvl in ("junior", "medior"))
    return str(value)


def parse(f: Field, form, current: Optional[dict] = None) -> Any:
    """Form data -> config value. Raises ValueError with a human message."""
    raw = form.get(f.path, "")
    k = f.kind
    try:
        if k == "bool":
            return f.path in form
        if k in ("text", "textarea"):
            return raw.strip() if k == "text" else raw.replace("\r\n", "\n").strip()
        if k in ("int", "float"):
            text = str(raw).strip()
            n = float(text.replace(",", ".")) if k == "float" else int(re.sub(r"[ .,_']", "", text))
            if (f.min is not None and n < f.min) or (f.max is not None and n > f.max):
                raise ValueError(f"must be between {f.min:g} and {f.max:g}")
            return n
        if k in ("lines", "regex_lines"):
            items = [l.strip() for l in raw.splitlines() if l.strip()]
            if k == "regex_lines":
                for pat in items:
                    re.compile(pat)
            return items
        if k == "choices":
            by_text = {str(c): c for c, _ in f.choices}             # values may be ints (levels, tiers) or strings (countries)
            got = form.getlist(f.path)
            if any(x not in by_text for x in got):
                raise ValueError("unknown choice")
            vals = [by_text[x] for x in by_text if x in got]       # keep the order of the list shown
            if f.required and not vals:
                raise ValueError("tick at least one")
            return vals
        if k == "secret":
            key = raw.strip()
            if key and (re.search(r"\s", key) or not 10 <= len(key) <= 400):
                raise ValueError("that doesn't look like an API key (no spaces, 10-400 characters)")
            return key
        if k == "pay_table":
            existing = dict(settings_get(current, f.path) or {})
            ticked = [c for c in form.getlist("search.countries") if c in COUNTRIES]
            for code in ticked:
                cur = COUNTRIES[code].currency
                vals = {}
                for key, label in (("min", "minimum"), ("big", "big-company minimum")):
                    txt = re.sub(r"[ .,_'€£]", "", form.get(f"pay.{code}.{key}", ""))
                    if not txt.isdigit() or not 1_000 <= int(txt) <= 100_000_000:
                        raise ValueError(f"{COUNTRIES[code].name}: the {label} must be a yearly amount in {cur}")
                    vals[key] = int(txt)
                if vals["big"] > vals["min"]:
                    raise ValueError(f"{COUNTRIES[code].name}: the big-company minimum can't be higher than the minimum")
                existing[code] = vals
            return existing
        if k == "select":
            if raw not in {c for c, _ in f.choices}:
                raise ValueError("unknown choice")
            return raw
        if k == "achievements":
            out_a: list[dict] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                tags, sep, rest = line.partition("::")
                en, _, nl = rest.partition("||")
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                if not sep or not tag_list or not en.strip():
                    raise ValueError(f"'{line[:60]}...': write  tags, comma separated :: the sentence  (optionally  || Dutch sentence)")
                item = {"tags": tag_list, "en": en.strip()}
                if nl.strip():
                    item["nl"] = nl.strip()
                out_a.append(item)
            return out_a
        if k == "fx":
            out_f: dict[str, float] = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                cur, sep, rate = line.partition(":")
                cur = cur.strip().upper()
                try:
                    r = float(rate.strip().replace(",", "."))
                except ValueError:
                    r = 0.0
                if not sep or not re.fullmatch(r"[A-Z]{3}", cur) or cur == "EUR" or not 0.0001 <= r <= 1000:
                    raise ValueError(f"'{line}': write  GBP: 1.15")
                out_f[cur] = r
            return out_f
        if k == "skills":
            out: dict[str, int] = {}
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                name, sep, w = line.rpartition(":")
                if not sep:  # no weight given
                    name, w = line, "1"
                name, w = name.strip(), (w.strip() or "1")
                if not w.isdigit() or not 1 <= int(w) <= 3 or not name:
                    raise ValueError(f"'{line}': write  Skill: 1, 2 or 3")
                out[name] = int(w)
            return out
        if k == "benchmarks":
            out_b: dict[str, dict] = {}
            for line in raw.splitlines():
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) != 4 or parts[1] not in ("junior", "medior"):
                    raise ValueError(f"'{line.strip()}': use  Company | junior or medior | low | high")
                lo, hi = int(parts[2].replace(".", "").replace(",", "")), int(parts[3].replace(".", "").replace(",", ""))
                if not 0 < lo <= hi:
                    raise ValueError(f"'{line.strip()}': low must be above 0 and not above high")
                out_b.setdefault(parts[0], {"basis": "total"})[parts[1]] = [lo, hi]
            return out_b
    except re.error as e:
        raise ValueError(f"not a valid pattern ({e})")
    except ValueError as e:
        msg = str(e)
        if msg.startswith("invalid literal") or msg.startswith("could not convert"):
            msg = "must be a number"
        raise ValueError(msg)
    raise ValueError(f"unsupported field kind {k}")


# ---------------------------------------------------------------- storage
TABLE = "CREATE TABLE IF NOT EXISTS settings (path TEXT PRIMARY KEY, value TEXT NOT NULL)"


def read_overrides(db_path: str) -> dict[str, Any]:
    """Raw read used by load_config (works before/without the DB class)."""
    p = Path(db_path)
    if not p.exists():
        return {}
    try:
        con = sqlite3.connect(str(p))
        try:
            return {k: json.loads(v) for k, v in con.execute("SELECT path, value FROM settings")}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def apply_overrides(cfg: dict, overrides: dict[str, Any]) -> None:
    for path, value in overrides.items():
        set_path(cfg, path, value)


def settings_get(cfg: Optional[dict], path: str):
    return get_path(cfg, path) if cfg else None


def validate_section(section: Section, form, current: Optional[dict] = None) -> tuple[dict[str, Any], list[str]]:
    values, errors = {}, []
    for f in section.fields:
        if f.kind == "secret":
            if form.get(f.path + "__clear"):
                values[f.path] = ""
                continue
            if not form.get(f.path, "").strip():
                continue                                  # left empty: keep the saved key
        try:
            values[f.path] = parse(f, form, current)
        except ValueError as e:
            errors.append(f"{f.label}: {e}")
    return values, errors


def save_values(db, cfg: dict, base: dict, values: dict[str, Any]) -> None:
    """Persist values (only those differing from the base) and apply them to the live cfg."""
    for path, value in values.items():
        if value == get_path(base, path):
            db.conn.execute("DELETE FROM settings WHERE path=?", (path,))
        else:
            db.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (path, json.dumps(value)))
        set_path(cfg, path, json.loads(json.dumps(value)))
    db.conn.commit()


def reset_paths(db, cfg: dict, base: dict, paths: list[str]) -> None:
    import copy
    for path in paths:
        db.conn.execute("DELETE FROM settings WHERE path=?", (path,))
        set_path(cfg, path, copy.deepcopy(get_path(base, path)))
    db.conn.commit()


def section_paths(section: Section) -> list[str]:
    return [f.path for f in section.fields]
