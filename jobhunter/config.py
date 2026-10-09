from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

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
        # skill -> weight (1-3). Matched against job title + description.
        "skills": {},
    },
    "search": {
        "country_keywords": [
            "netherlands", "nederland", "amsterdam", "rotterdam", "utrecht",
            "eindhoven", "the hague", "den haag", "almere", "amstelveen",
            "delft", "leiden", "haarlem", "hilversum", "schiphol", "nl",
        ],
        "include_remote": False,
        "max_years_required": 4,
        "min_salary": 90000,
        "max_age_days": 60,
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
            "software engineer", "software developer", "backend developer",
            "full stack developer", ".NET developer", "C# developer", "python developer",
        ],
        "location": "Netherlands",
        # LinkedIn experience levels: 2=Entry, 3=Associate, 4=Mid-Senior
        "experience_levels": [2, 3, 4],
        "window_days": 7,
        "pages_per_query": 3,
        "delay_seconds": 3.0,
    },
    "companies": [],
    "manual_links": [],
    "cover_letter": (
        "Dear {company} hiring team,\n\n"
        "I'm excited to apply for the {title} role. I'm a software engineer with "
        "{years} years of experience building and operating production services, "
        "most recently as a Medior Software Engineer at GS1 Nederland.\n\n"
        "{pitch}\n\n"
        "{skills_line}\n\n"
        "I'd love to talk about how I can contribute to {company}.\n\n"
        "Kind regards,\n{name}\n{email} | {phone}\n{linkedin}\n"
    ),
    "web": {"host": "0.0.0.0", "port": 8080},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else ROOT / "config.yaml"
    user: dict = {}
    if path.exists():
        user = yaml.safe_load(path.read_text()) or {}
    cfg = _merge(DEFAULTS, user)
    db = Path(cfg["db_path"])
    if not db.is_absolute():
        cfg["db_path"] = str(ROOT / db)
    return cfg
