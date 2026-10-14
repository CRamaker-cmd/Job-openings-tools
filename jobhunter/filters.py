"""Decides whether a job is relevant and how well it fits. Pure functions, easy to test."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from . import money
from .countries import big_floor_for, currency_of, detect_country, in_selected_country, min_salary_for, primary_country
from .models import RawJob
from .pay import parse_pay

AMBIGUOUS_LOCATION = re.compile(r"^\s*$|\b\d+\s+locations?\b|multiple|various|\bglobal\b", re.I)


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _word(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w])", re.I)


# ---------------------------------------------------------------- location

def location_ok(location: str, cfg: dict, strict: bool = False) -> bool:
    s = cfg["search"]
    loc = location or ""
    if in_selected_country(loc, cfg):
        return True
    if s["include_remote"] and re.search(r"remote", loc, re.I):
        return True
    if not strict and AMBIGUOUS_LOCATION.search(loc):
        return True
    return False


# ---------------------------------------------------------------- title

def title_ok(title: str, cfg: dict) -> tuple[bool, str]:
    s = cfg["search"]
    if not _any(s["title_include"], title):
        return False, "not a software role"
    if _any(s["title_exclude"], title):
        return False, "excluded role type"
    if _any(s["title_too_senior"], title):
        return False, "too senior"
    return True, ""


def title_level(title: str, cfg: dict) -> str:
    s = cfg["search"]
    if _any(s["title_junior_markers"], title):
        return "junior"
    if _any(s["title_medior_markers"], title):
        return "medior"
    return "unspecified"


# ---------------------------------------------------------------- salary

def parse_salary(text: str, cfg: Optional[dict] = None) -> tuple[Optional[int], Optional[int]]:
    """(low, high) yearly gross EUR found in free text, or (None, None). See pay.py for the rules."""
    p = parse_pay(text, cfg)
    return (p.lo, p.hi) if p else (None, None)


# ---------------------------------------------------------------- experience

_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:[-–]\s*\d{1,2}\s*)?(?:\+\s*)?(?:years?|yrs?|jaar|jaren)\b", re.I
)


def years_required(text: str) -> Optional[int]:
    """Smallest 'N years of experience' figure mentioned. None if not stated."""
    found = []
    for m in _YEARS.finditer(text or ""):
        ctx = text[max(0, m.start() - 80): m.end() + 80]
        if re.search(r"experience|ervaring|working|professional", ctx, re.I):
            n = int(m.group(1))
            if n <= 20:
                found.append(n)
    return min(found) if found else None


# ---------------------------------------------------------------- scoring

@dataclass
class Evaluation:
    ok: bool
    reject: str = ""
    score: int = 0
    level: str = "unspecified"
    pay_confidence: str = "unknown"  # stated | estimated | likely (assumed) | growth (big co, below usual min) | low | unknown
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    years: Optional[int] = None
    country: str = ""            # ISO code of the job's country ('' = unknown / remote)
    est_min: Optional[int] = None
    est_max: Optional[int] = None
    pay_source: str = ""
    pay_note: str = ""
    matched_skills: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def company_tier(company: str, cfg: dict) -> int:
    """0 = unknown company, 1 = configured big/high-paying, 2 = configured but mid-tier."""
    c = re.sub(r"[^a-z0-9]+", " ", company.lower()).strip()
    for entry in cfg.get("companies", []):
        n = re.sub(r"[^a-z0-9]+", " ", str(entry["name"]).lower()).strip()
        if n and (n == c or n in c or c in n and len(c) > 3):
            return int(entry.get("tier", 1))
    return 0


def prefilter(job: RawJob, cfg: dict) -> bool:
    """Cheap check on listing data only, before we spend a request on the description."""
    ok, _ = title_ok(job.title, cfg)
    return ok and location_ok(job.location, cfg, strict=False)


def evaluate(job: RawJob, cfg: dict, now: Optional[datetime] = None, estimate=None) -> Evaluation:
    s = cfg["search"]
    now = now or datetime.now(timezone.utc)

    ok, why = title_ok(job.title, cfg)
    if not ok:
        return Evaluation(False, why)
    if not location_ok(job.location, cfg, strict=True):
        return Evaluation(False, "not in your selected countries")
    if job.posted_at:
        posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        age = (now - posted).days
        if age > s["max_age_days"]:
            return Evaluation(False, "too old")
    else:
        age = None

    text = f"{job.title}\n{job.description}"
    years = years_required(job.description)
    if years is not None and years > s["max_years_required"]:
        return Evaluation(False, f"asks {years}+ years")

    level = title_level(job.title, cfg)
    tier = company_tier(job.company, cfg)
    # At big companies (career potential) a somewhat lower salary is acceptable: a lower floor applies.
    country = detect_country(job.location, cfg)
    pay_country = country or primary_country(cfg)           # unknown country (remote): the first searched country's rules
    cur = currency_of(pay_country)
    min_sal = min_salary_for(cfg, pay_country)
    big = tier in s["big_company_tiers"]
    floor = big_floor_for(cfg, pay_country) if big else min_sal
    show = lambda lo, hi: money.rng(money.to_local(lo, cur, cfg), money.to_local(hi, cur, cfg), cur)   # in the country's currency

    sal_min, sal_max, pay_note = job.salary_min, job.salary_max, ""
    if sal_min is None:
        found = parse_pay(job.description, cfg, country or None)
        if found:
            sal_min, sal_max, pay_note = found.lo, found.hi, found.note
    if sal_max is not None and sal_max < floor:
        return Evaluation(False, f"pays up to {sal_max}")

    ev = Evaluation(True, years=years, salary_min=sal_min, salary_max=sal_max, country=country)
    ev.pay_note = pay_note
    score = 30

    ev.level = level
    if ev.level in ("junior", "medior"):
        score += 15
        ev.reasons.append(f"{ev.level} role")
    else:
        score += 5

    if sal_max is not None:  # stated; if below the usual minimum we only get here via the big-company floor
        ev.pay_source = "posting"
        rng = show(sal_min, sal_max)
        if sal_max < min_sal:  # between the big-company floor and the normal minimum
            ev.pay_confidence = "growth"
            ev.pay_note = (pay_note + "; " if pay_note else "") + "below your usual minimum, accepted: big company with career potential"
            score += 5
            ev.reasons.append(f"big company, salary stated {rng}")
        else:
            ev.pay_confidence = "stated"
            score += 15
            ev.reasons.append(f"salary stated {rng}")
    elif estimate is not None:  # reported pay for this company/level beats guessing from company size
        ev.est_min, ev.est_max = estimate.lo, estimate.hi
        ev.pay_source, ev.pay_note = estimate.source, estimate.note
        rng = show(estimate.lo, estimate.hi)
        if (estimate.lo + estimate.hi) / 2 >= min_sal:  # midpoint, not the optimistic top end
            ev.pay_confidence = "estimated"
            score += 15
            ev.reasons.append(f"typically {rng} ({estimate.source})")
        elif big and (estimate.lo + estimate.hi) / 2 >= floor:
            ev.pay_confidence = "growth"
            ev.pay_note = f"{estimate.note}; below your usual minimum, accepted: big company with career potential"
            score += 5
            ev.reasons.append(f"big company, typically {rng} ({estimate.source})")
        else:
            ev.pay_confidence = "low"
            score -= 20
            ev.reasons.append(f"typically only {rng} ({estimate.source})")
    elif tier == 1:
        ev.pay_confidence, ev.pay_source = "likely", "assumed"
        ev.pay_note = "assumed: large international tech company"
        score += 10
        ev.reasons.append("high-paying company (assumed)")
    elif tier == 2:
        ev.pay_confidence, ev.pay_source = "likely", "assumed"
        score += 3
    else:
        score -= 10

    skill_pts = 0
    for skill, weight in cfg["profile"]["skills"].items():
        pat = _word(skill)
        if pat.search(text):
            ev.matched_skills.append(skill)
            skill_pts += 3 * int(weight)
            if pat.search(job.title):
                skill_pts += 4
    score += min(skill_pts, 25)
    if ev.matched_skills:
        ev.reasons.append("matches " + ", ".join(ev.matched_skills[:6]))

    if years is not None:
        score += 5 if years <= 2 else 0
    if age is not None:
        score += 10 if age <= 3 else 5 if age <= 14 else 0

    ev.score = max(0, min(100, score))
    return ev
