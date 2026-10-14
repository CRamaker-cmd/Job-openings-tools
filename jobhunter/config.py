from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "db_path": "data/jobs.db",
    "profile": {
        "name": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "location": "",
        "pitch": "",
        "years_experience": 3,
        # Material for the motivation letters (all optional; the letters get better the more of this is filled in)
        "job_title": "",              # e.g. "Medior Software Engineer"
        "employer": "",               # e.g. "GS1 Nederland"
        "ambition": "",               # where you want to grow: the heart of the letter
        "ambition_nl": "",            # same, in Dutch (optional)
        "achievements": [],           # [{tags: [...], en: "...", nl: "..."}] concrete things you did
        "letter_language": "auto",    # auto = match the posting; en; nl
        "cv_text": "",                # the text of your CV (read from your upload; editable)
        "cv_filename": "",            # name of the uploaded file
        # skill -> weight (1-3). Matched against job title + description.
        "skills": {},
    },
    "search": {
        "countries": ["NL"],              # which countries to search (see countries.py)
        "country_keywords": [],           # extra place words that count as "in one of my countries"
        "include_remote": False,
        "max_years_required": 4,
        "vacation_allowance_pct": 8,      # added to MONTHLY salaries (Dutch vakantiegeld); not added if the text says it's included
        "add_bonus": True,                # add a bonus / 13th month when the posting states one
        "show_unknown_pay": True,         # list jobs whose pay couldn't be determined (marked "pay unknown")
        "fx_to_eur": {"GBP": 1.15, "CHF": 1.05, "SEK": 0.09, "DKK": 0.134, "NOK": 0.087, "PLN": 0.23},
        # Minimum yearly gross pay per searched country, in THAT country's own currency:
        #   min = jobs that state less are dropped;  big = the lower minimum for companies of the "big" tiers below
        "pay_by_country": {"NL": {"min": 90000, "big": 70000}},
        "big_company_tiers": [1],           # company tiers (Companies page) that count as "big" for the lower minimum
        "max_age_days": 60,
        "repost_gap_days": 30,   # same role posted this many days apart = a new batch, not a duplicate
        "title_include": [
            r"software", r"developer", r"engineer", r"ontwikkelaar", r"programmeur",
            r"\bsde\b", r"\bswe\b", r"full.?stack", r"back.?end", r"front.?end",
        ],
        "title_exclude": [
            r"\bintern(ship)?\b", r"stagiair", r"werkstudent", r"apprentice", r"thesis",
            r"\bsales\b", r"solutions? (engineer|architect)", r"support engineer",
            r"customer", r"field engineer", r"hardware", r"mechanical", r"electrical",
            r"civil", r"manufacturing", r"process engineer", r"technician", r"data center",
            r"\brecruit", r"\bmanager\b", r"\bdirector\b", r"mechatronic", r"optical",
            r"\bsecurity (guard|officer)\b",
        ],
        # Too senior: skipped. (You asked for junior/medior only.)
        "title_too_senior": [
            r"\bsenior\b", r"\bsr\b", r"\bstaff\b", r"\bprincipal\b", r"\blead\b",
            r"\bhead\b", r"\bvp\b", r"\bdistinguished\b", r"\bfellow\b", r"\barchitect\b",
            r"\bexpert\b", r"(engineer|developer|sde|swe)\s*(iii|iv|v|3|4|5)\b",
            r"\bl[5-9]\b",
        ],
        "title_junior_markers": [
            r"\bjunior\b", r"\bjr\b", r"\bentry\b", r"\bgraduate\b", r"\bassociate\b",
            r"(engineer|developer|sde|swe)\s*(i|1)\b",
        ],
        "title_medior_markers": [
            r"\bmedior\b", r"\bmid[- ]?level\b", r"\bmid\b", r"\bintermediate\b",
            r"(engineer|developer|sde|swe)\s*(ii|2)\b",
        ],
    },
    "linkedin": {
        "enabled": True,
        "queries": [
            "software engineer", "junior software engineer", "junior developer",
            "software developer", "backend developer",
            "full stack developer", ".NET developer", "C# developer", "python developer",
        ],
        # LinkedIn experience levels: 2=Entry, 3=Associate, 4=Mid-Senior
        "experience_levels": [2, 3, 4],
        "window_days": 7,
        "pages_per_query": 3,
        "delay_seconds": 3.0,
    },
    "ai": {
        "enabled": False,             # show the "Agent Customize" button on jobs
        "provider": "anthropic",      # "anthropic" (Claude) or "openai" (any OpenAI-compatible endpoint, incl. local models)
        "base_url": "",               # openai provider only, e.g. http://192.168.1.20:11434/v1
        "api_key": "",                # write-only in the UI; or set the JOBHUNTER_AI_API_KEY environment variable
        "model": "",                  # empty = the provider's default (Claude: claude-opus-5-5); required for "openai"
        "timeout_seconds": 180,
    },
    "salary": {
        # Used only when a posting doesn't state pay.
        "online_lookup": True,        # quick web search for "<company> salary Netherlands"
        "max_lookups_per_run": 30,
        "cache_days": 45,
        "delay_seconds": 3.0,
        "benchmarks": {},             # extra/overriding {Company: {medior: [lo, hi]}} - see salary_benchmarks.yaml
    },
    "schedule": {
        "enabled": True,
        "every_hours": 24,               # every source is refreshed once per this many hours
        "spread": True,                  # one source at a time, evenly spread over those hours
        # Gentle mode: made for a Pi that also runs other things. A scrape just takes longer.
        "low_priority": True,             # lowest CPU priority for scraping (the dashboard stays responsive)
        "pause_between_sources": 15,      # seconds of rest between two companies
        "pause_between_requests": 0.5,    # seconds between detail-page requests
    },
    "browser": {
        "executable": None,           # path to chromium; None = Playwright's own download
        "delay_seconds": 2.0,
    },
    "companies": [],
    "manual_links": [],
    "web": {"host": "0.0.0.0", "port": 8585},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


LEGACY_PAY_KEYS = ("min_salary", "big_company_min_salary", "min_salary_by_country", "big_company_min_by_country")


def _legacy_pay_rows(get, base_rows: dict) -> Optional[dict]:
    """Settings from before pay was one table (separate minimum / big-company / per-country fields) -> the new rows."""
    mn, big = get("min_salary"), get("big_company_min_salary")
    by, byb = get("min_salary_by_country") or {}, get("big_company_min_by_country") or {}
    if mn is None and big is None and not by and not byb:
        return None
    nl = dict(base_rows.get("NL") or {"min": 90000, "big": 70000})
    rows = {**base_rows, "NL": {"min": mn if mn is not None else nl["min"], "big": big if big is not None else nl["big"]}}
    for code, v in by.items():
        rows[code] = {"min": v, "big": byb.get(code, round(v * rows["NL"]["big"] / max(rows["NL"]["min"], 1), -3))}
    return rows


def load_base(path: str | Path | None = None) -> dict[str, Any]:
    """Defaults + config.yaml, WITHOUT the settings edited on the dashboard."""
    if path:
        path = Path(path)
    else:  # no config.yaml (e.g. a fresh Docker container): fall back to the shipped example, which has the company list
        path = ROOT / "config.yaml"
        if not path.exists() and (ROOT / "config.example.yaml").exists():
            path = ROOT / "config.example.yaml"
    user: dict = {}
    if path.exists():
        user = yaml.safe_load(path.read_text()) or {}
    cfg = _merge(DEFAULTS, user)
    user_search = user.get("search") or {}
    if "pay_by_country" not in user_search:        # an older config.yaml: convert its pay settings
        rows = _legacy_pay_rows(user_search.get, cfg["search"]["pay_by_country"])
        if rows:
            cfg["search"]["pay_by_country"] = rows
    for k in LEGACY_PAY_KEYS:
        cfg["search"].pop(k, None)
    # Docker/containers: point at the system Chromium without editing any file
    exe = os.environ.get("JOBHUNTER_CHROMIUM")
    if exe and not cfg["browser"].get("executable"):
        cfg["browser"]["executable"] = exe
    db = Path(cfg["db_path"])
    if not db.is_absolute():
        cfg["db_path"] = str(ROOT / db)
    cfg["_config_path"] = str(path)
    return cfg


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """The effective config: base + settings edited on the dashboard (stored in the DB)."""
    from .settings import apply_overrides, read_overrides

    cfg = load_base(path)
    ov = read_overrides(cfg["db_path"])
    if "search.pay_by_country" not in ov:           # settings saved before pay became one table
        rows = _legacy_pay_rows(lambda k: ov.get("search." + k), cfg["search"]["pay_by_country"])
        if rows:
            ov["search.pay_by_country"] = rows
    apply_overrides(cfg, {k: v for k, v in ov.items() if k.split(".")[-1] not in LEGACY_PAY_KEYS})
    return cfg
