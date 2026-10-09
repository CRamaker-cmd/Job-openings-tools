from __future__ import annotations

from .ats import Ashby, Greenhouse, Jibe, Lever, SmartRecruiters, Workday
from .base import Scraper
from .custom import Amazon, Uber
from .linkedin import LinkedIn

REGISTRY: dict[str, type[Scraper]] = {
    "greenhouse": Greenhouse,
    "lever": Lever,
    "ashby": Ashby,
    "smartrecruiters": SmartRecruiters,
    "workday": Workday,
    "jibe": Jibe,
    "amazon": Amazon,
    "uber": Uber,
}


def build_scrapers(cfg: dict, only: str | None = None) -> list[Scraper]:
    out: list[Scraper] = []
    for entry in cfg["companies"]:
        if entry.get("disabled"):
            continue
        cls = REGISTRY.get(entry["ats"])
        if cls is None:
            raise ValueError(f"{entry['name']}: unknown ats '{entry['ats']}' (known: {', '.join(REGISTRY)})")
        out.append(cls(cfg, entry))
    if cfg["linkedin"]["enabled"]:
        out.append(LinkedIn(cfg))
    if only:
        out = [s for s in out if only.lower() in s.name.lower()]
    return out
