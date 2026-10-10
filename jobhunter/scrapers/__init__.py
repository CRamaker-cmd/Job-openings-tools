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


def build_scrapers(cfg: dict, only: str | None = None) -> list[Scraper]:
    out: list[Scraper] = []
    for entry in cfg["companies"]:
        if entry.get("disabled"):
            continue
        cls = REGISTRY.get(entry["ats"])
        if cls is None:
            raise ValueError(f"{entry['name']}: unknown ats '{entry['ats']}' (known: {', '.join(REGISTRY)})")
        if entry["ats"] == "browser" and not playwright_available():
            log.warning("skipping %s: browser scraping needs 'pip install -r requirements-browser.txt'", entry["name"])
            continue
        out.append(cls(cfg, entry))
    if cfg["linkedin"]["enabled"]:
        out.append(LinkedIn(cfg))
    if only:
        out = [s for s in out if only.lower() in s.name.lower()]
    return out
