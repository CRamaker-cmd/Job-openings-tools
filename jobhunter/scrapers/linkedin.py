"""LinkedIn via its public *guest* job-search endpoints (no login, no account at risk).

Note: LinkedIn's terms forbid automated scraping. This is built for low-volume personal use:
a handful of requests per run, with delays, and it stops at the first sign of throttling.
Never add your LinkedIn credentials/cookies here.
"""
from __future__ import annotations

import logging
import re
from typing import Iterator

from bs4 import BeautifulSoup

from ..http import polite_sleep
from ..models import RawJob
from .base import Scraper, html_to_text, parse_dt

log = logging.getLogger(__name__)

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


class Throttled(Exception):
    pass


class LinkedIn(Scraper):
    deactivate_grace_days = 30  # a search only shows a rolling window, so be slow to retire jobs

    def __init__(self, cfg: dict, entry=None):
        super().__init__(cfg, {"name": "LinkedIn"})
        self.lc = cfg["linkedin"]

    def _get(self, url: str, **kw):
        r = self.http.get(url, timeout=30, **kw)
        if r.status_code in (429, 999) or r.status_code == 403:
            raise Throttled(f"LinkedIn answered {r.status_code}; stopping to stay polite")
        r.raise_for_status()
        return r

    @staticmethod
    def parse_cards(markup: str) -> list[RawJob]:
        soup = BeautifulSoup(markup, "html.parser")
        jobs = []
        for card in soup.select("div.base-card") or soup.select("li"):
            link = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
            title = card.select_one(".base-search-card__title")
            if not (link and title):
                continue
            company = card.select_one(".base-search-card__subtitle")
            loc = card.select_one(".job-search-card__location")
            when = card.select_one("time")
            urn = (card.select_one("[data-entity-urn]") or card).get("data-entity-urn", "")
            m = re.search(r"(\d{6,})", urn) or re.search(r"-(\d{6,})\?", link["href"] + "?")
            jobs.append(RawJob(
                source="linkedin", origin="LinkedIn",
                company=company.get_text(" ", strip=True) if company else "",
                title=title.get_text(" ", strip=True),
                url=link["href"].split("?")[0],
                location=loc.get_text(" ", strip=True) if loc else "",
                external_id=m.group(1) if m else "",
                posted_at=parse_dt(when.get("datetime")) if when else None,
            ))
        return jobs

    def fetch(self) -> Iterator[RawJob]:
        lc, seen = self.lc, set()
        for query in lc["queries"]:
            for page in range(lc["pages_per_query"]):
                params = {
                    "keywords": query, "location": lc["location"], "start": page * 25,
                    "f_E": ",".join(str(x) for x in lc["experience_levels"]),
                    "f_TPR": f"r{int(lc['window_days']) * 86400}", "sortBy": "DD",
                }
                polite_sleep(lc["delay_seconds"])
                cards = self.parse_cards(self._get(SEARCH, params=params).text)
                if not cards:
                    break
                for job in cards:
                    if job.external_id not in seen:
                        seen.add(job.external_id)
                        yield job

    def enrich(self, job: RawJob) -> None:
        if not job.external_id:
            return
        polite_sleep(self.lc["delay_seconds"])
        soup = BeautifulSoup(self._get(DETAIL.format(id=job.external_id)).text, "html.parser")
        body = soup.select_one(".show-more-less-html__markup, .description__text")
        if body:
            job.description = html_to_text(str(body))
        sal = soup.select_one(".compensation__salary, .salary")
        if sal:
            job.description += "\n" + sal.get_text(" ", strip=True)
