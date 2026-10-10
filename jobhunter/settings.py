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


# ---------------------------------------------------------------- spec
@dataclass
class Field:
    path: str                     # dotted path into the config, e.g. "search.min_salary"
    label: str
    kind: str                     # text | textarea | int | float | bool | lines | regex_lines | choices | skills | benchmarks
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = ""
    choices: list = field(default_factory=list)   # [(value, label)] for kind == "choices"
    group: str = ""               # sub-heading shown above the field
    placeholder: str = ""


@dataclass
class Section:
    id: str
    title: str
    intro: str
    fields: list[Field]


SECTIONS: list[Section] = [
    Section("profile", "Profile & cover letter",
            "Your details are used to fill the cover-letter draft and the copy-paste snippets. "
            "The skills list drives the match score: a job that mentions your skills ranks higher.",
            [
                Field("profile.name", "Full name", "text", group="About you"),
                Field("profile.email", "Email", "text"),
                Field("profile.phone", "Phone", "text"),
                Field("profile.linkedin", "LinkedIn URL", "text"),
                Field("profile.github", "GitHub URL", "text"),
                Field("profile.location", "Location", "text", placeholder="Almere, Netherlands"),
                Field("profile.years_experience", "Years of experience", "int", min=0, max=40,
                      help="Used in the cover letter ({years})."),
                Field("profile.pitch", "Short pitch", "textarea",
                      help="2-3 sentences about your best work. Inserted into the cover letter as {pitch}.",
                      group="Cover letter"),
                Field("cover_letter", "Cover-letter template", "textarea",
                      help="Placeholders: {company} {title} {years} {pitch} {skills_line} {name} {email} {phone} {linkedin}. "
                           "The draft on each job page is built from this - always read it before sending."),
                Field("profile.skills", "Skills and weights", "skills", group="Skills",
                      help="One per line as  Skill: weight  (weight 1 = nice to have, 2 = solid, 3 = your core stack). "
                           "Matched against the job title and description."),
            ]),
    Section("matching", "Matching: pay, experience, location",
            "What counts as a job worth showing. Jobs that fail these rules are not saved at all.",
            [
                Field("search.min_salary", "Minimum salary", "int", min=0, max=500000, unit="€ / year",
                      help="Postings that STATE a salary below this are dropped. When no salary is stated, the pay "
                           "is estimated instead (see 'Pay lookups'). Jobs at big companies may go lower, see next.",
                      group="Pay"),
                Field("search.big_company_min_salary", "Lower minimum for big companies", "int", min=0, max=500000,
                      unit="€ / year",
                      help="For companies you marked as 'big' (below), this lower minimum applies instead, for any job "
                           "title. Those jobs are shown with a 🌱 'under 90k' label. Set equal to the minimum to disable."),
                Field("search.big_company_tiers", "Which company tiers count as 'big'", "choices",
                      choices=[(1, "Tier 1: big / high-paying (Booking, Adyen, Amazon, ...)"),
                               (2, "Tier 2: decent, but check the range")],
                      help="A company's tier is set on the Companies page. LinkedIn jobs from companies "
                           "you haven't added there are never treated as big."),
                Field("search.max_years_required", "Maximum years of experience asked", "int", min=0, max=20,
                      unit="years", group="Experience",
                      help="Postings that ask for more years of experience than this are dropped. "
                           "Title words like 'Senior', 'Staff', 'Lead' are filtered separately (see Advanced)."),
                Field("search.max_age_days", "Ignore postings older than", "int", min=1, max=365, unit="days"),
                Field("search.include_remote", "Include remote jobs", "bool", group="Location",
                      help="Off = only jobs located in the Netherlands. On = also keep jobs whose location says 'Remote' "
                           "(from any country)."),
                Field("search.country_keywords", "Words that mean 'in the Netherlands'", "lines",
                      help="One per line. A job's location must contain one of these words."),
            ]),
    Section("linkedin", "LinkedIn search",
            "LinkedIn's public (logged-out) job search, used to find jobs at companies that aren't on your Companies "
            "list. It never uses your LinkedIn account. LinkedIn's terms forbid scraping, so keep volume low.",
            [
                Field("linkedin.enabled", "Search LinkedIn", "bool"),
                Field("linkedin.queries", "Search terms", "lines",
                      help="One per line. Each is searched separately, so more terms = more requests = slower."),
                Field("linkedin.location", "Location", "text"),
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
    Section("schedule", "Schedule",
            "How often the app looks for new jobs by itself. You can always press 'Scrape now' on the dashboard.",
            [
                Field("schedule.enabled", "Scrape automatically", "bool"),
                Field("schedule.every_hours", "Every", "int", min=1, max=168, unit="hours",
                      help="Job boards rarely change faster than every few hours; 6-12 is plenty."),
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
    if value is None:
        return ""
    if f.kind in ("lines", "regex_lines"):
        return "\n".join(str(v) for v in value)
    if f.kind == "skills":
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    if f.kind == "benchmarks":
        return "\n".join(f"{c} | {lvl} | {lo} | {hi}" for c, d in value.items()
                         for lvl, (lo, hi) in d.items() if lvl in ("junior", "medior"))
    return str(value)


def parse(f: Field, form) -> Any:
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
            valid = {c for c, _ in f.choices}
            vals = sorted({int(x) for x in form.getlist(f.path)})
            if not set(vals) <= valid:
                raise ValueError("unknown choice")
            return vals
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


def validate_section(section: Section, form) -> tuple[dict[str, Any], list[str]]:
    values, errors = {}, []
    for f in section.fields:
        try:
            values[f.path] = parse(f, form)
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
