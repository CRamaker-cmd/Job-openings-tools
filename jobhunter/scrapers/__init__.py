from __future__ import annotations

import logging

from .ats import Ashby, Greenhouse, Jibe, Lever, SmartRecruiters, Workday
from .base import Scraper
from .browser import Browser, playwright_available
from .custom import Amazon, Uber
from .linkedin import LinkedIn

log = logging.getLogger(__name__)

REGISTRY: dict[str, type[Scraper]] = {
    "greenhouse": Greenhouse,
    "lever": Lever,
    "ashby": Ashby,
    "smartrecruiters": SmartRecruiters,
    "workday": Workday,
    "jibe": Jibe,
    "amazon": Amazon,
    "uber": Uber,
    "browser": Browser,
}


def _entries(cfg: dict):
    """Enabled company entries that can actually run here (browser ones need the optional install)."""
    for entry in cfg["companies"]:
        if entry.get("disabled"):
            continue
        if entry["ats"] not in REGISTRY:
            raise ValueError(f"{entry['name']}: unknown ats '{entry['ats']}' (known: {', '.join(REGISTRY)})")
        if entry["ats"] == "browser" and not playwright_available():
            log.warning("skipping %s: browser scraping needs 'pip install -r requirements-browser.txt'", entry["name"])
            continue
        yield entry


def source_names(cfg: dict) -> list[str]:
    """Names of everything that gets scraped (used by the scheduler). Same rules as build_scrapers."""
    names = [e["name"] for e in _entries(cfg)]
    return names + (["LinkedIn"] if cfg["linkedin"]["enabled"] else [])


def build_scrapers(cfg: dict, only: str | None = None, exact: bool = False) -> list[Scraper]:
    out: list[Scraper] = [REGISTRY[e["ats"]](cfg, e) for e in _entries(cfg)]
    if cfg["linkedin"]["enabled"]:
        out.append(LinkedIn(cfg))
    if only:
        match = (lambda n: n.lower() == only.lower()) if exact else (lambda n: only.lower() in n.lower())
        out = [s for s in out if match(s.name)]
    return out
