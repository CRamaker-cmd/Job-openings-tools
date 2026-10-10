"""Adapters for the applicant-tracking systems many big companies publish their jobs through.

Each has a public, unauthenticated JSON endpoint, which is far more reliable than scraping HTML.
Response shapes are kept in small ``parse_*`` helpers so they can be unit-tested offline.
"""
from __future__ import annotations

from typing import Iterator

from ..models import RawJob
from .base import Scraper, html_to_text, parse_dt


# ------------------------------------------------------------------ Greenhouse
class Greenhouse(Scraper):
    """https://boards-api.greenhouse.io/v1/boards/<board>/jobs

    The list is small (no descriptions); the full text is fetched per job only for postings that pass
    the title/location prefilter. Much lighter than ``?content=true``, which ships every description of
    every job (many MB for big boards) just to throw most of them away.
    """

    def _api(self) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{self.entry['board']}/jobs"

    def fetch(self) -> Iterator[RawJob]:
        for j in self.get_json(self._api()).get("jobs", []):
            yield self.parse(j)

    def parse(self, j: dict) -> RawJob:
        return RawJob(
            source="greenhouse", origin=self.origin, company=self.name,
            title=j.get("title", ""), url=j.get("absolute_url", ""),
            location=(j.get("location") or {}).get("name", ""),
            external_id=str(j.get("id", "")),
            description=html_to_text(j.get("content", "")),  # only present if the API included it
            posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
            # "updated_at" changes whenever the company edits the text, so it can't tell us about re-posts
            extra={} if j.get("first_published") else {"date_unreliable": True},
        )

    def enrich(self, job: RawJob) -> None:
        d = self.get_json(f"{self._api()}/{job.external_id}", params={"pay_transparency": "true"})
        job.description = html_to_text(d.get("content", ""))
        for r in d.get("pay_input_ranges") or []:  # present when the company publishes pay ranges
            if str(r.get("currency_type", "")).upper() == "EUR" and r.get("max_cents"):
                job.salary_min, job.salary_max = int(r.get("min_cents", 0)) // 100 or None, int(r["max_cents"]) // 100


# ------------------------------------------------------------------ Lever
class Lever(Scraper):
    """https://api.lever.co/v0/postings/<site>?mode=json  (use api.eu.lever.co for EU sites)"""

    def fetch(self) -> Iterator[RawJob]:
        host = "api.eu.lever.co" if self.entry.get("eu") else "api.lever.co"
        data = self.get_json(f"https://{host}/v0/postings/{self.entry['site']}", params={"mode": "json"})
        for j in data:
            yield self.parse(j)

    def parse(self, j: dict) -> RawJob:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or [cats.get("location", "")]
        job = RawJob(
            source="lever", origin=self.origin, company=self.name,
            title=j.get("text", ""), url=j.get("hostedUrl", ""),
            location=" / ".join(l for l in locs if l),
            external_id=j.get("id", ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("description", "")),
            posted_at=parse_dt(j.get("createdAt")),
        )
        sr = j.get("salaryRange") or {}
        if sr.get("currency") == "EUR" and "year" in sr.get("interval", "").lower():
            job.salary_min, job.salary_max = int(sr.get("min", 0)) or None, int(sr.get("max", 0)) or None
        return job


# ------------------------------------------------------------------ Ashby
class Ashby(Scraper):
    """https://api.ashbyhq.com/posting-api/job-board/<board>?includeCompensation=true"""

    def fetch(self) -> Iterator[RawJob]:
        data = self.get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{self.entry['board']}",
            params={"includeCompensation": "true"},
        )
        for j in data.get("jobs", []):
            if j.get("isListed", True):
                yield self.parse(j)

    def parse(self, j: dict) -> RawJob:
        loc = j.get("location", "")
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        if addr.get("addressCountry"):
            loc = f"{loc}, {addr['addressCountry']}"
        for sec in j.get("secondaryLocations") or []:
            loc += f" / {sec.get('location', '')}"
        job = RawJob(
            source="ashby", origin=self.origin, company=self.name,
            title=j.get("title", ""), url=j.get("jobUrl", ""), location=loc,
            external_id=j.get("id", ""),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml", "")),
            posted_at=parse_dt(j.get("publishedAt")),
        )
        comp = (j.get("compensation") or {})
        for comp_tier in comp.get("compensationTiers") or []:
            for c in comp_tier.get("components") or []:
                if c.get("compensationType") == "Salary" and c.get("currencyCode") == "EUR" \
                        and "year" in c.get("interval", "").lower():
                    job.salary_min, job.salary_max = c.get("minValue"), c.get("maxValue")
        return job


# ------------------------------------------------------------------ SmartRecruiters
class SmartRecruiters(Scraper):
    """https://api.smartrecruiters.com/v1/companies/<id>/postings  (description needs a 2nd call)"""

    def fetch(self) -> Iterator[RawJob]:
        cid, offset = self.entry["company_id"], 0
        while True:
            data = self.get_json(
                f"https://api.smartrecruiters.com/v1/companies/{cid}/postings",
                params={"country": "nl", "limit": 100, "offset": offset},
            )
            items = data.get("content", [])
            for j in items:
                yield self.parse(j)
            offset += len(items)
            if not items or offset >= data.get("totalFound", 0):
                break

    def parse(self, j: dict) -> RawJob:
        loc = j.get("location") or {}
        cid = (j.get("company") or {}).get("identifier", self.entry["company_id"])
        return RawJob(
            source="smartrecruiters", origin=self.origin, company=self.name,
            title=j.get("name", ""),
            url=f"https://jobs.smartrecruiters.com/{cid}/{j.get('id', '')}",
            location=", ".join(x for x in (loc.get("city"), loc.get("country", "").upper()) if x),
            external_id=j.get("id", ""), posted_at=parse_dt(j.get("releasedDate")),
            extra={"ref": j.get("ref", "")},
        )

    def enrich(self, job: RawJob) -> None:
        d = self.get_json(job.extra["ref"]) if job.extra.get("ref") else {}
        sections = ((d.get("jobAd") or {}).get("sections") or {})
        parts = [html_to_text(s.get("text", "")) for s in sections.values() if isinstance(s, dict)]
        job.description = "\n\n".join(p for p in parts if p)
        job.url = d.get("postingUrl", job.url)


# ------------------------------------------------------------------ Workday
class Workday(Scraper):
    """POST https://<tenant>.<wd>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs

    config: tenant, site, wd (e.g. "wd5"), optional search (default "software")
    """

    PAGE = 20

    def _base(self) -> str:
        e = self.entry
        return f"https://{e['tenant']}.{e.get('wd', 'wd5')}.myworkdayjobs.com"

    def fetch(self) -> Iterator[RawJob]:
        e, offset = self.entry, 0
        url = f"{self._base()}/wday/cxs/{e['tenant']}/{e['site']}/jobs"
        while True:
            data = self.post_json(url, {
                "appliedFacets": {}, "limit": self.PAGE, "offset": offset,
                "searchText": e.get("search", "software"),
            })
            posts = data.get("jobPostings", [])
            for j in posts:
                yield self.parse(j)
            offset += len(posts)
            if not posts or offset >= data.get("total", 0) or offset >= 400:
                break

    def parse(self, j: dict) -> RawJob:
        e, path = self.entry, j.get("externalPath", "")
        return RawJob(
            source="workday", origin=self.origin, company=self.name,
            title=j.get("title", ""), url=f"{self._base()}/{e['site']}{path}",
            location=j.get("locationsText", ""), external_id=(j.get("bulletFields") or [""])[0],
            extra={"path": path},
        )

    def enrich(self, job: RawJob) -> None:
        e = self.entry
        d = self.get_json(f"{self._base()}/wday/cxs/{e['tenant']}/{e['site']}{job.extra['path']}")
        info = d.get("jobPostingInfo") or {}
        job.description = html_to_text(info.get("jobDescription", ""))
        locs = [info.get("location", "")] + list(info.get("additionalLocations") or [])
        job.location = " / ".join(l for l in locs if l) or job.location
        job.posted_at = parse_dt(info.get("startDate"))
        job.url = info.get("externalUrl", job.url)


# ------------------------------------------------------------------ Jibe (iCIMS career sites)
class Jibe(Scraper):
    """https://<host>/api/jobs?page=N&limit=100&keywords=..  e.g. jobs.booking.com

    config: host, optional keywords/location
    """

    def fetch(self) -> Iterator[RawJob]:
        host, page = self.entry["host"], 1
        while True:
            params = {"page": page, "limit": 100, "keywords": self.entry.get("keywords", "software"),
                      "location": self.entry.get("location", "Netherlands")}
            data = self.get_json(f"https://{host}/api/jobs", params=params)
            jobs = data.get("jobs", [])
            for j in jobs:
                yield self.parse(j.get("data", j))
            if not jobs or page * 100 >= data.get("totalCount", 0) or page >= 10:
                break
            page += 1

    def parse(self, d: dict) -> RawJob:
        host = self.entry["host"]
        loc = d.get("full_location") or ", ".join(x for x in (d.get("city"), d.get("country")) if x)
        slug = d.get("slug") or d.get("req_id", "")
        return RawJob(
            source="jibe", origin=self.origin, company=self.name,
            title=d.get("title", ""),
            url=d.get("apply_url") or d.get("canonical_url") or f"https://{host}/jobs/{slug}",
            location=loc, external_id=str(d.get("req_id", slug)),
            description=html_to_text(d.get("description", "") + " " + d.get("qualifications", "")),
            posted_at=parse_dt(d.get("posted_date") or d.get("create_date")),
        )
