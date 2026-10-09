from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawJob:
    """A posting as a scraper sees it, before filtering/scoring."""

    source: str  # e.g. "greenhouse", "linkedin"
    origin: str  # who we scraped it from, e.g. "Adyen" or "LinkedIn"
    company: str
    title: str
    url: str
    location: str = ""
    external_id: str = ""
    description: str = ""
    posted_at: Optional[datetime] = None
    salary_min: Optional[int] = None  # yearly, EUR
    salary_max: Optional[int] = None
    extra: dict = field(default_factory=dict)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def fingerprint(company: str, title: str, location: str) -> str:
    """Stable id used to de-duplicate the same job seen on LinkedIn and the company site."""
    city = _norm(location.split(",")[0]) if location else ""
    key = "|".join([_norm(company), _norm(title), city])
    return hashlib.sha1(key.encode()).hexdigest()
