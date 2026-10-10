from __future__ import annotations

import logging
from dataclasses import dataclass

from . import filters
from .db import DB, now_iso
from .salary import Estimator
from .scrapers import build_scrapers
from .scrapers.base import Scraper
from .scrapers.linkedin import Throttled

log = logging.getLogger(__name__)


@dataclass
class Stats:
    seen: int = 0
    kept: int = 0
    new: int = 0


def run_scraper(scraper: Scraper, cfg: dict, db: DB, started: str, estimator=None) -> Stats:
    stats = Stats()
    for raw in scraper.fetch():
        stats.seen += 1
        if not filters.prefilter(raw, cfg):
            continue
        if not raw.description:
            try:
                scraper.enrich(raw)
            except Throttled:
                raise
            except Exception as e:  # one bad posting shouldn't sink the whole source
                log.warning("%s: could not load details for %r: %s", scraper.name, raw.title, e)
        ev = filters.evaluate(raw, cfg)
        if not ev.ok:
            log.debug("%s: drop %r (%s)", scraper.name, raw.title, ev.reject)
            continue
        if estimator and ev.salary_max is None:  # no pay in the posting: look up what's usually paid
            est = estimator.estimate(raw.company, ev.level)
            if est:
                ev = filters.evaluate(raw, cfg, estimate=est)
        stats.kept += 1
        stats.new += db.upsert(raw, ev, started)
    return stats


def run_all(cfg: dict, db: DB, only: str | None = None) -> list[tuple[str, Stats | Exception]]:
    started = now_iso()
    results = []
    estimator = Estimator(cfg, db)
    for scraper in build_scrapers(cfg, only):
        log.info("scraping %s ...", scraper.name)
        try:
            stats = run_scraper(scraper, cfg, db, started, estimator)
        except Exception as e:
            log.error("%s failed: %s", scraper.name, e)
            db.record_run(started, scraper.origin, False, error=str(e)[:300])
            results.append((scraper.name, e))
            continue
        db.deactivate_unseen(scraper.origin, started, scraper.deactivate_grace_days)
        db.record_run(started, scraper.origin, True, stats.seen, stats.kept, stats.new)
        log.info("%s: %d listed, %d relevant, %d new", scraper.name, stats.seen, stats.kept, stats.new)
        results.append((scraper.name, stats))
    return results
