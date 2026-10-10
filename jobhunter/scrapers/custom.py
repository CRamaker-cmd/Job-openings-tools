"""Companies that run their own career-site API (Amazon, Uber)."""
from __future__ import annotations

from typing import Iterator

from ..models import RawJob
from .base import Scraper, html_to_text, parse_dt


class Amazon(Scraper):
    """https://www.amazon.jobs/en/search.json — public JSON behind the careers search page."""

    def fetch(self) -> Iterator[RawJob]:
        offset = 0
        while True:
            data = self.get_json("https://www.amazon.jobs/en/search.json", params={
                "base_query": self.entry.get("query", "software"),
                "country[]": "NLD", "category[]": "software-development",
                "result_limit": 100, "offset": offset, "sort": "recent",
            })
            jobs = data.get("jobs", [])
            for j in jobs:
                yield self.parse(j)
            offset += len(jobs)
            if not jobs or offset >= data.get("hits", 0) or offset >= 500:
                break

    def parse(self, j: dict) -> RawJob:
        desc = "\n\n".join(html_to_text(j.get(k, "")) for k in
                           ("description", "basic_qualifications", "preferred_qualifications"))
        return RawJob(
            source="amazon", origin=self.origin, company="Amazon",
            title=j.get("title", ""), url="https://www.amazon.jobs" + j.get("job_path", ""),
            location=j.get("normalized_location") or j.get("location", ""),
            external_id=str(j.get("id_icims") or j.get("id", "")), description=desc,
            posted_at=parse_dt(j.get("posted_date")),
        )


class Uber(Scraper):
    """https://www.uber.com/api/loadSearchJobsResults — what the careers page itself calls."""

    def fetch(self) -> Iterator[RawJob]:
        page = 0
        while True:
            data = self.post_json(
                "https://www.uber.com/api/loadSearchJobsResults?localeCode=en",
                {"params": {"location": [{"country": "NLD"}], "department": ["Engineering"]},
                 "page": page, "limit": 50},
                headers={"x-csrf-token": "x"},
            )
            d = data.get("data") or {}
            results = d.get("results", [])
            for j in results:
                yield self.parse(j)
            total = (d.get("totalResults") or {}).get("low", 0)
            page += 1
            if not results or page * 50 >= total or page >= 10:
                break

    def parse(self, j: dict) -> RawJob:
        loc = j.get("location") or {}
        return RawJob(
            source="uber", origin=self.origin, company="Uber",
            title=j.get("title", ""),
            url=f"https://www.uber.com/global/en/careers/list/{j.get('id', '')}/",
            location=", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
            external_id=str(j.get("id", "")), description=html_to_text(j.get("description", "")),
            posted_at=parse_dt(j.get("creationDate")),
        )
