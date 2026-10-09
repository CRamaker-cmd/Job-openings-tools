from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Iterator, Optional

from bs4 import BeautifulSoup

from ..http import make_session
from ..models import RawJob


def html_to_text(raw: str) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) -> readable plain text."""
    if not raw:
        return ""
    if "&lt;" in raw and "<" not in raw:
        raw = html.unescape(raw)
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all(["br", "li", "p", "div", "h1", "h2", "h3", "h4"]):
        br.append("\n")
    text = soup.get_text(" ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_dt(value) -> Optional[datetime]:
    """Accepts ISO strings, epoch seconds or epoch milliseconds."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 1e11 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        s = str(value).strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.strptime(s, "%B %d, %Y")  # Amazon: "March 3, 2026"
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError):
        return None


class Scraper:
    """One scraper = one source (a company career site or a LinkedIn search)."""

    #: set to a number of days to keep jobs "active" after they stop appearing (LinkedIn)
    deactivate_grace_days = 0

    def __init__(self, cfg: dict, entry: Optional[dict] = None):
        self.cfg = cfg
        self.entry = entry or {}
        self.http = make_session()
        self.name: str = self.entry.get("name", self.__class__.__name__)

    @property
    def origin(self) -> str:
        return self.name

    def fetch(self) -> Iterator[RawJob]:
        raise NotImplementedError

    def enrich(self, job: RawJob) -> None:
        """Fetch the full description. Only called for jobs that passed the cheap prefilter."""

    # helpers
    def get_json(self, url: str, **kw):
        r = self.http.get(url, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def post_json(self, url: str, payload: dict, **kw):
        r = self.http.post(url, json=payload, timeout=30, **kw)
        r.raise_for_status()
        return r.json()
