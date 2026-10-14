"""Pay estimates for postings that don't state a salary.

Order of evidence (first hit wins):
  1. benchmarks   - jobhunter/salary_benchmarks.yaml, reported figures we looked up once
  2. cache        - earlier online lookups (stored in the DB, expire after `cache_days`)
  3. online       - a quick web search ("<company> software engineer salary Netherlands ...")
                    whose result snippets (Glassdoor, Levels.fyi, Indeed, ...) are scanned for EUR figures.
                    Free, needs no API key and never loads Glassdoor itself (which blocks bots).
Anything else -> None, and the caller falls back to "assumed" for tier-1 companies.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from bs4 import BeautifulSoup

from .countries import COUNTRIES
from .pay import parse_pay
from .http import make_session, polite_sleep
from .models import _norm

log = logging.getLogger(__name__)
BENCH_FILE = Path(__file__).with_name("salary_benchmarks.yaml")
SEARCH_URL = "https://html.duckduckgo.com/html/"
PAY_WORDS = ("salary", "salaries", "pay", "compensation", "earn", "salaris", "loon", "verdien")


@dataclass
class PayEstimate:
    lo: int
    hi: int
    source: str  # benchmark | online
    note: str = ""


def parse_snippets(markup: str, company: str, cfg: Optional[dict] = None, country: Optional[str] = None) -> list[tuple[int, int]]:
    """Pull (low, high) EUR yearly figures out of a search-results page, for snippets about `company`."""
    soup = BeautifulSoup(markup, "html.parser")
    name = _norm(company)
    found = []
    for res in soup.select(".result, .web-result"):
        text = res.get_text(" ", strip=True)
        low = text.lower()
        if name not in _norm(text) or not any(w in low for w in PAY_WORDS):
            continue
        p = parse_pay(text, cfg, country)  # monthly figures become yearly incl. holiday pay, other currencies become EUR
        if p:
            found.append((p.lo, p.hi))
    return found


def aggregate(found: list[tuple[int, int]]) -> Optional[tuple[int, int, int]]:
    if not found:
        return None
    return (int(statistics.median(l for l, _ in found)),
            int(statistics.median(h for _, h in found)), len(found))


class Estimator:
    def __init__(self, cfg: dict, db=None, allow_web: bool = True):
        self.cfg, self.db, self.allow_web = cfg, db, allow_web  # allow_web=False: tables + cache only, no network
        self.sc = cfg["salary"]
        self.http = make_session()
        self.lookups = 0
        self.blocked = False
        # The bundled table is Netherlands data; the user's own entries apply wherever they say.
        self.bench_nl = {_norm(k): v for k, v in (yaml.safe_load(BENCH_FILE.read_text()) or {}).items()}
        self.bench_user = {_norm(k): v for k, v in (self.sc.get("benchmarks") or {}).items()}

    # ------------------------------------------------------------
    def estimate(self, company: str, level: str, country: str = "NL") -> Optional[PayEstimate]:
        level = "junior" if level == "junior" else "medior"  # unspecified -> medior
        b = self._benchmark(company, level, country)
        if b:
            return b
        if not self.sc["online_lookup"] or not self.db:
            return None
        key = f"{_norm(company)}|{level}" + ("" if country == "NL" else f"|{country}")
        cached = self.db.salary_cache_get(key, self.sc["cache_days"])
        if cached is not None:
            lo, hi, n = cached
            return PayEstimate(lo, hi, "online", f"{n} web results") if lo else None
        if not self.allow_web or self.blocked or self.lookups >= self.sc["max_lookups_per_run"]:
            return None
        return self._lookup(company, level, key, country)

    def _benchmark(self, company: str, level: str, country: str) -> Optional[PayEstimate]:
        c = _norm(company)
        tables = [self.bench_user] + ([self.bench_nl] if country == "NL" else [])
        for name, entry in ((n, e) for t in tables for n, e in t.items()):
            if name and (name == c or name in c):
                rng = entry.get(level)
                if rng:
                    return PayEstimate(int(rng[0]), int(rng[1]), "benchmark",
                                       f"reported {entry.get('basis', 'total')} pay, {level}")
        return None

    def _lookup(self, company: str, level: str, key: str, country: str = "NL") -> Optional[PayEstimate]:
        self.lookups += 1
        role = "junior software engineer" if level == "junior" else "software engineer"
        place = COUNTRIES[country].name if country in COUNTRIES else "Netherlands"
        q = f"{company} {role} salary {place} glassdoor levels.fyi"
        polite_sleep(self.sc["delay_seconds"])
        try:
            r = self.http.get(SEARCH_URL, params={"q": q}, timeout=20)
            if r.status_code != 200 or "result" not in r.text:  # 202 = bot check; stop asking
                self.blocked = True
                log.warning("salary web search not available (HTTP %s); skipping further lookups", r.status_code)
                return None
        except Exception as e:
            self.blocked = True
            log.warning("salary web search failed: %s", e)
            return None
        agg = aggregate(parse_snippets(r.text, company, self.cfg, country))
        self.db.salary_cache_put(key, *(agg or (0, 0, 0)))  # cache misses too, so we don't retry daily
        if not agg:
            return None
        lo, hi, n = agg
        return PayEstimate(lo, hi, "online", f"{n} web results")
