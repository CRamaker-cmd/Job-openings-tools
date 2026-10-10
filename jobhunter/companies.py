"""Describes how each kind of career site is configured, for the Companies page.

A company entry is a dict, e.g. ``{"name": "Adyen", "ats": "greenhouse", "board": "adyen", "tier": 1}``.
``ATS`` drives the add/edit form (which fields to show, which are required, where to find the value).
"""
from __future__ import annotations

from typing import Any

# field: (key, label, required, help)
ATS: dict[str, dict] = {
    "greenhouse": {
        "label": "Greenhouse",
        "how": "Open the company's job board; the address looks like boards.greenhouse.io/<b>board</b> "
               "or job-boards.greenhouse.io/<b>board</b>.",
        "fields": [("board", "Board name", True, "e.g. adyen")],
    },
    "lever": {
        "label": "Lever",
        "how": "Address looks like jobs.lever.co/<b>site</b>. European customers may use jobs.eu.lever.co.",
        "fields": [("site", "Site name", True, "e.g. palantir"), ("eu", "EU region (jobs.eu.lever.co)", False, "")],
    },
    "ashby": {
        "label": "Ashby",
        "how": "Address looks like jobs.ashbyhq.com/<b>board</b>.",
        "fields": [("board", "Board name", True, "e.g. ramp")],
    },
    "smartrecruiters": {
        "label": "SmartRecruiters",
        "how": "Address looks like jobs.smartrecruiters.com/<b>CompanyId</b>.",
        "fields": [("company_id", "Company ID", True, "e.g. BoschGroup")],
    },
    "workday": {
        "label": "Workday",
        "how": "Address looks like <b>tenant</b>.<b>wd5</b>.myworkdayjobs.com/<b>site</b>/... - copy the three parts.",
        "fields": [("tenant", "Tenant", True, "e.g. adobe"), ("wd", "Server (wd1, wd3, wd5, ...)", True, "e.g. wd5"),
                   ("site", "Site name", True, "e.g. external_experienced"),
                   ("search", "Search words", False, "default: software")],
    },
    "jibe": {
        "label": "Jibe / iCIMS career site",
        "how": "Career sites such as jobs.booking.com whose search results come from /api/jobs.",
        "fields": [("host", "Career-site host", True, "e.g. jobs.booking.com"),
                   ("keywords", "Search words", False, "default: software")],
    },
    "amazon": {"label": "Amazon (own site)", "how": "Built in - nothing to fill in.", "fields": []},
    "uber": {"label": "Uber (own site)", "how": "Built in - nothing to fill in.", "fields": []},
    "browser": {
        "label": "Any other site (browser)",
        "how": "For sites without a feed. Search on the site with your filters, copy the results-page address, then "
               "open any job and copy what its address has in common (e.g. <code>/jobs/\\d+</code>). "
               "Needs the optional browser install (see the Help page).",
        "fields": [("url", "Results page address (with your filters)", True, "https://..."),
                   ("link_pattern", "Job-link pattern (regex)", True, r"e.g. /jobs/\d+"),
                   ("next", "'Next page' button selector", False, "optional, e.g. button[aria-label='Next']"),
                   ("max_pages", "Max pages", False, "default 5")],
    },
}

TIER_LABELS = {1: "Tier 1: big / high-paying", 2: "Tier 2: decent, check the range"}


def validate(form) -> tuple[dict[str, Any], list[str]]:
    """Form -> company dict. Returns (entry, errors)."""
    errors: list[str] = []
    name = form.get("name", "").strip()
    ats = form.get("ats", "")
    if not name:
        errors.append("Name is required.")
    if ats not in ATS:
        errors.append("Choose a type of career site.")
        return {}, errors
    try:
        tier = int(form.get("tier", 1))
        if tier not in (1, 2):
            raise ValueError
    except ValueError:
        errors.append("Tier must be 1 or 2.")
        tier = 1
    entry: dict[str, Any] = {"name": name, "ats": ats, "tier": tier}
    for key, label, required, _ in ATS[ats]["fields"]:
        val = form.get(key, "").strip()
        if key == "eu":
            if key in form:
                entry["eu"] = True
            continue
        if key == "max_pages" and val:
            if not val.isdigit() or not 1 <= int(val) <= 50:
                errors.append("Max pages must be a number from 1 to 50.")
            else:
                entry[key] = int(val)
            continue
        if key == "link_pattern" and val:
            import re
            try:
                re.compile(val)
            except re.error as e:
                errors.append(f"Job-link pattern is not a valid regex ({e}).")
        if required and not val:
            errors.append(f"{label} is required.")
        elif val:
            entry[key] = val
    if form.get("disabled"):
        entry["disabled"] = True
    return entry, errors
