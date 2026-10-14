from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass

from . import filters
from .countries import selected
from .db import DB, now_iso
from .salary import Estimator
from .scrapers import build_scrapers
from .scrapers.base import Scraper
from .scrapers.linkedin import Throttled

log = logging.getLogger(__name__)


def lower_priority() -> None:
    """Give the calling thread the lowest CPU priority. On Linux the nice value is per thread and
    inherited by child processes (so a scraping Chromium is niced too). Harmless no-op elsewhere."""
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
    except (AttributeError, OSError):
        pass


@dataclass
class Stats:
    seen: int = 0    # postings the source listed
    known: int = 0   # already in the database (or already rejected): skipped without any further work
    kept: int = 0    # newly evaluated and relevant
    new: int = 0     # of those, newly saved


def assess(raw, cfg: dict, estimator=None):
    """Rules + score for one posting, looking up typical pay when the posting doesn't state any."""
    ev = filters.evaluate(raw, cfg)
    if ev.ok and ev.salary_max is None and estimator:
        est = estimator.estimate(raw.company, ev.level, ev.country or selected(cfg)[0].code)
        if est:
            ev = filters.evaluate(raw, cfg, estimate=est)
    return ev


def run_scraper(scraper: Scraper, cfg: dict, db: DB, started: str, estimator=None) -> Stats:
    """Only new postings cost anything: a posting already saved (or already rejected) is just marked
    'still listed'. To look at one again, delete it on the dashboard."""
    stats = Stats()
    for raw in scraper.fetch():
        stats.seen += 1
        known = db.find_known(raw, cfg["search"]["repost_gap_days"])
        if known is not None:
            db.touch_known(known, raw, started)
            stats.known += 1
            continue
        if db.is_rejected(raw):
            stats.known += 1
            continue
        if not filters.prefilter(raw, cfg):  # cheap: title/location only, nothing is fetched
            continue
        if not raw.description:
            time.sleep(cfg["schedule"]["pause_between_requests"])  # be gentle: one detail page at a time
            try:
                scraper.enrich(raw)
            except Throttled:
                raise
            except Exception as e:  # one bad posting shouldn't sink the whole source; it is retried next time
                log.warning("%s: could not load details for %r: %s", scraper.name, raw.title, e)
        ev = assess(raw, cfg, estimator)
        if not ev.ok:
            log.debug("%s: drop %r (%s)", scraper.name, raw.title, ev.reject)
            db.remember_rejected(raw, ev.reject)
            continue
        stats.kept += 1
        stats.new += db.upsert(raw, ev, started)
    return stats


def _raw_from_row(r):
    from datetime import datetime
    from .models import RawJob

    job = RawJob(source=r["source"], origin=r["origin"], company=r["company"], title=r["title"], url=r["url"],
                 location=r["location"] or "", external_id=r["external_id"] or "", description=r["description"] or "",
                 posted_at=datetime.fromisoformat(r["posted_at"]) if r["posted_at"] else None)
    if r["pay_confidence"] == "stated":  # may have come from a structured field rather than the text
        job.salary_min, job.salary_max = r["salary_min"], r["salary_max"]
    return job


def refresh_unknown_pay(cfg: dict, db: DB, estimator) -> int:
    """Jobs saved with 'pay unknown' are never fetched again, so give them another chance to get a pay estimate whenever the
    lookup budget allows (cached answers are free; new web searches are limited per run). Returns how many got pay data."""
    improved = 0
    rows = db.conn.execute(
        "SELECT * FROM jobs WHERE active=1 AND status IN ('new','starred') AND pay_confidence='unknown' "
        "ORDER BY first_seen DESC LIMIT 300").fetchall()
    for r in rows:
        ev = assess(_raw_from_row(r), cfg, estimator)
        if ev.ok and ev.pay_confidence != "unknown":
            db.update_scoring(r["id"], ev)
            improved += 1
    return improved


def rescore(cfg: dict, db: DB) -> tuple[int, int]:
    """Re-apply the current rules to jobs already saved, using only what is stored: no network at all.
    Returns (jobs re-scored, jobs moved to Hidden because they no longer pass). Starred/applied jobs are
    never moved. Called after rules change, because known jobs are otherwise never looked at again."""
    estimator = Estimator(cfg, db, allow_web=False)
    done = moved = 0
    for r in db.active_rows():
        job = _raw_from_row(r)
        ev = assess(job, cfg, estimator)
        if ev.ok:
            db.update_scoring(r["id"], ev)
            done += 1
        elif r["status"] == "new":
            db.set_status(r["id"], "hidden")
            moved += 1
    return done, moved


def run_source(scraper: Scraper, cfg: dict, db: DB, estimator: Estimator) -> "Stats | Exception":
    """Scrape one source and record the outcome. Never raises: a failing source must not affect others."""
    started = now_iso()
    log.info("scraping %s ...", scraper.name)
    try:
        stats = run_scraper(scraper, cfg, db, started, estimator)
    except Exception as e:
        log.error("%s failed: %s", scraper.name, e)
        db.record_run(started, scraper.origin, False, error=str(e)[:300])
        return e
    db.deactivate_unseen(scraper.origin, started, scraper.deactivate_grace_days)
    db.record_run(started, scraper.origin, True, stats.seen, stats.kept, stats.new, known=stats.known)
    try:
        got = refresh_unknown_pay(cfg, db, estimator)
        if got:
            log.info("%s: found pay data for %d previously unknown-pay jobs", scraper.name, got)
    except Exception:
        log.exception("refreshing unknown-pay jobs failed")
    log.info("%s: %d listed, %d already known, %d new", scraper.name, stats.seen, stats.known, stats.new)
    return stats


def run_all(cfg: dict, db: DB, only: str | None = None) -> list[tuple[str, "Stats | Exception"]]:
    """Scrape every source one after another (what 'Scrape now' and the CLI do)."""
    estimator = Estimator(cfg, db)
    if cfg["schedule"]["low_priority"]:
        lower_priority()
    results = []
    for n, scraper in enumerate(build_scrapers(cfg, only)):
        if n:
            time.sleep(cfg["schedule"]["pause_between_sources"])
        results.append((scraper.name, run_source(scraper, cfg, db, estimator)))
    return results


def run_one(cfg: dict, db: DB, name: str) -> None:
    """Scrape exactly one source by name (used by the trickle scheduler)."""
    if cfg["schedule"]["low_priority"]:
        lower_priority()
    for scraper in build_scrapers(cfg, name, exact=True):
        run_source(scraper, cfg, db, Estimator(cfg, db))
