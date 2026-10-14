from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .countries import detect_country
from .filters import Evaluation
from .models import RawJob, fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,   -- unique key of this row (opening identity)
    fp TEXT,                            -- company+title+city: same value for reposts of the same role
    source TEXT NOT NULL,
    origin TEXT NOT NULL,
    external_id TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    country TEXT,                       -- ISO code ('' = unknown/remote)
    url TEXT NOT NULL,
    description TEXT,
    posted_at TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    salary_min INTEGER,
    salary_max INTEGER,
    pay_confidence TEXT,
    level TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    reasons TEXT,
    status TEXT NOT NULL DEFAULT 'new',   -- new | starred | applied | interview | rejected | hidden
    notes TEXT DEFAULT '',
    applied_at TEXT
);
CREATE TABLE IF NOT EXISTS rejected (   -- postings we looked at and dropped; not re-fetched until they expire
    key TEXT PRIMARY KEY, reason TEXT, seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS salary_cache (
    key TEXT PRIMARY KEY, lo INTEGER, hi INTEGER, n INTEGER, fetched TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    path TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, active, score DESC);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT NOT NULL,
    origin TEXT NOT NULL,
    ok INTEGER NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0,
    kept INTEGER NOT NULL DEFAULT 0,
    known INTEGER NOT NULL DEFAULT 0,
    new INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
"""

STATUSES = ("new", "starred", "applied", "interview", "rejected", "hidden")
SOURCE_PRIORITY = {"linkedin": 0}  # anything else (company site) wins when the same job appears twice


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        have = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        for col, typ in (("est_min", "INTEGER"), ("est_max", "INTEGER"),
                         ("pay_source", "TEXT"), ("pay_note", "TEXT")):
            if col not in have:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
        have_runs = {r["name"] for r in self.conn.execute("PRAGMA table_info(runs)")}
        if "fp" not in have:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN fp TEXT")
            self.conn.execute("UPDATE jobs SET fp = fingerprint WHERE fp IS NULL")  # older rows: key was the base fingerprint
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fp ON jobs(fp)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_src_ext ON jobs(source, external_id)")
        if "country" not in have:
            self.conn.execute("ALTER TABLE jobs ADD COLUMN country TEXT")
        for r in self.conn.execute("SELECT id, location FROM jobs WHERE country IS NULL").fetchall():
            self.conn.execute("UPDATE jobs SET country=? WHERE id=?", (detect_country(r["location"] or ""), r["id"]))
        # LinkedIn used to be one source; it is now one per country. Existing jobs/runs were all Netherlands.
        self.conn.execute("UPDATE jobs SET origin='LinkedIn NL' WHERE origin='LinkedIn'")
        self.conn.execute("UPDATE runs SET origin='LinkedIn NL' WHERE origin='LinkedIn'")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_country ON jobs(country)")
        if "known" not in have_runs:
            self.conn.execute("ALTER TABLE runs ADD COLUMN known INTEGER NOT NULL DEFAULT 0")
        self.conn.commit()

    # ---------------------------------------------------------- salary lookup cache
    def salary_cache_get(self, key: str, max_age_days: int):
        row = self.conn.execute("SELECT * FROM salary_cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched"])
        if age > timedelta(days=max_age_days if row["lo"] else min(max_age_days, 14)):
            return None
        return row["lo"], row["hi"], row["n"]

    def salary_cache_put(self, key: str, lo: int, hi: int, n: int) -> None:
        self.conn.execute("INSERT OR REPLACE INTO salary_cache VALUES (?,?,?,?,?)", (key, lo, hi, n, now_iso()))
        self.conn.commit()

    # ---------------------------------------------------------- writes
    def upsert(self, job: RawJob, ev: Evaluation, ts: Optional[str] = None) -> bool:
        """Save a posting we don't know yet (callers check ``find_known`` first). Returns True if inserted."""
        ts = ts or now_iso()
        reasons = json.dumps(ev.reasons)
        posted = job.posted_at.isoformat() if job.posted_at else None
        key = self._row_key(job)
        pay = (ev.salary_min, ev.salary_max, ev.pay_confidence, ev.est_min, ev.est_max,
               ev.pay_source, ev.pay_note, ev.level, ev.score, reasons, ev.country)
        try:
            self.conn.execute(
                """INSERT INTO jobs (salary_min, salary_max, pay_confidence, est_min, est_max, pay_source,
                   pay_note, level, score, reasons, country, fingerprint, fp, source, origin, external_id, company,
                   title, location, url, description, posted_at, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                pay + (key, fingerprint(job.company, job.title, job.location), job.source, job.origin, job.external_id,
                       job.company, job.title, job.location, job.url, job.description, posted, ts, ts),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:  # exactly this opening is already stored: just refresh it
            self.conn.execute(
                """UPDATE jobs SET active=1, last_seen=?, salary_min=?, salary_max=?, pay_confidence=?, est_min=?,
                   est_max=?, pay_source=?, pay_note=?, level=?, score=?, reasons=?, country=? WHERE fingerprint=?""",
                (ts,) + pay + (key,))
            self.conn.commit()
            return False

    # ---------------------------------------------------------- incremental scraping
    REJECT_MEMORY_DAYS = 30

    # -- what makes two postings "the same opening"? -------------------------------------------------
    # * same source + same id            -> same opening, unless it was posted much later (a re-post)
    # * same source, NEW id              -> a different opening (a new batch of the same role)
    # * other source, or no id at all    -> same opening if company+title+city match AND the posting dates
    #                                       are close (or one is unknown); far apart = a new batch
    # The gap is `search.repost_gap_days`. Dates a source can't vouch for (extra["date_unreliable"], e.g.
    # Greenhouse's "last edited") are never used to call something a re-post.
    @staticmethod
    def _day(job: RawJob) -> str:
        return job.posted_at.date().isoformat() if job.posted_at else ""

    @classmethod
    def _row_key(cls, job: RawJob) -> str:
        who = f"{job.source}:{job.external_id}" if job.external_id else ""
        return "|".join([fingerprint(job.company, job.title, job.location), who, cls._day(job)])

    @classmethod
    def _reject_key(cls, job: RawJob) -> str:
        reliable = "" if job.extra.get("date_unreliable") else cls._day(job)
        return (f"id:{job.source}:{job.external_id}@{reliable}" if job.external_id
                else f"fp:{fingerprint(job.company, job.title, job.location)}@{cls._day(job)}")

    @staticmethod
    def _same_batch(job: RawJob, posted_iso: Optional[str], gap_days: int, trust_date: bool = True) -> bool:
        if not trust_date or job.posted_at is None or not posted_iso:
            return True  # can't tell them apart by date -> treat as the same opening
        theirs = datetime.fromisoformat(posted_iso)
        mine = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
        theirs = theirs if theirs.tzinfo else theirs.replace(tzinfo=timezone.utc)
        return abs((mine - theirs).days) <= gap_days

    def find_known(self, job: RawJob, gap_days: int = 30):
        """The saved row for this exact opening if we already have it, else None (see the rules above)."""
        trust = not job.extra.get("date_unreliable")
        if job.external_id:
            for row in self.conn.execute("SELECT id, source, posted_at FROM jobs WHERE source=? AND external_id=?",
                                         (job.source, job.external_id)):
                if self._same_batch(job, row["posted_at"], gap_days, trust):
                    return row
        fp = fingerprint(job.company, job.title, job.location)
        # same role seen via another site (or, without ids, via the same one)
        q = "SELECT id, source, posted_at FROM jobs WHERE fp=?" + (" AND source<>?" if job.external_id else "")
        for row in self.conn.execute(q, (fp, job.source) if job.external_id else (fp,)):
            if self._same_batch(job, row["posted_at"], gap_days):
                return row
        return None

    def is_rejected(self, job: RawJob) -> bool:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.REJECT_MEMORY_DAYS)).isoformat(timespec="seconds")
        return self.conn.execute("SELECT 1 FROM rejected WHERE key=? AND seen>=?", (self._reject_key(job), cutoff)).fetchone() is not None

    def remember_rejected(self, job: RawJob, reason: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO rejected VALUES (?,?,?)", (self._reject_key(job), reason, now_iso()))
        self.conn.commit()

    def clear_rejected(self) -> None:
        """Called when matching rules change, so dropped postings get a fresh look."""
        self.conn.execute("DELETE FROM rejected")
        self.conn.commit()

    def touch_known(self, row, job: RawJob, ts: str) -> None:
        """A posting we already have: just note it is still listed. No re-fetching, no re-scoring.
        (Exception: a company-site copy replaces the link of a LinkedIn copy.)"""
        if SOURCE_PRIORITY.get(job.source, 1) > SOURCE_PRIORITY.get(row["source"], 1):
            self.conn.execute(
                """UPDATE jobs SET active=1, last_seen=?, source=?, origin=?, external_id=?, url=?,
                   description=CASE WHEN ?<>'' THEN ? ELSE description END WHERE id=?""",
                (ts, job.source, job.origin, job.external_id, job.url, job.description, job.description, row["id"]))
        else:
            self.conn.execute("UPDATE jobs SET active=1, last_seen=? WHERE id=?", (ts, row["id"]))
        self.conn.commit()

    def delete_job(self, job_id: int) -> None:
        """Remove a job entirely. If it is still listed at the source, the next scrape sees it as new again."""
        self.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        self.conn.commit()

    def active_rows(self):
        return self.conn.execute("SELECT * FROM jobs WHERE active=1").fetchall()

    def update_scoring(self, job_id: int, ev: Evaluation) -> None:
        self.conn.execute(
            """UPDATE jobs SET salary_min=?, salary_max=?, pay_confidence=?, est_min=?, est_max=?, pay_source=?,
               pay_note=?, level=?, score=?, reasons=?, country=? WHERE id=?""",
            (ev.salary_min, ev.salary_max, ev.pay_confidence, ev.est_min, ev.est_max, ev.pay_source,
             ev.pay_note, ev.level, ev.score, json.dumps(ev.reasons), ev.country, job_id))
        self.conn.commit()

    def deactivate_unseen(self, origin: str, run_started: str, grace_days: int = 0) -> None:
        cutoff = (datetime.fromisoformat(run_started) - timedelta(days=grace_days)).isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE jobs SET active=0 WHERE origin=? AND last_seen < ?", (origin, cutoff)
        )
        self.conn.commit()

    def record_run(self, started: str, origin: str, ok: bool, seen=0, kept=0, new=0, error=None, known=0) -> None:
        self.conn.execute(
            "INSERT INTO runs (started, origin, ok, seen, kept, new, error, known) VALUES (?,?,?,?,?,?,?,?)",
            (started, origin, int(ok), seen, kept, new, error, known),
        )
        self.conn.commit()

    def set_status(self, job_id: int, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(status)
        applied = now_iso() if status == "applied" else None
        self.conn.execute(
            "UPDATE jobs SET status=?, applied_at=COALESCE(?, applied_at) WHERE id=?",
            (status, applied, job_id),
        )
        self.conn.commit()

    def set_notes(self, job_id: int, notes: str) -> None:
        self.conn.execute("UPDATE jobs SET notes=? WHERE id=?", (notes, job_id))
        self.conn.commit()

    # ---------------------------------------------------------- reads
    def get(self, job_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    def list_jobs(
        self,
        status: str = "open",
        q: str = "",
        company: str = "",
        min_score: int = 0,
        pay: str = "good",
        level: str = "",
        show_unknown: bool = True,
        country: str = "",
        countries: Optional[list] = None,
        sort: str = "score",
        include_inactive: bool = False,
    ) -> list[sqlite3.Row]:
        where, args = [], []  # type: list[str], list[Any]
        if not include_inactive:
            where.append("active=1")
        if status == "open":
            where.append("status IN ('new','starred')")
        elif status != "all":
            where.append("status=?")
            args.append(status)
        if q:
            where.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)")
            args += [f"%{q}%"] * 3
        if company:
            where.append("company=?")
            args.append(company)
        if min_score:
            where.append("score>=?")
            args.append(min_score)
        if pay == "good":  # pay that is fine, or (default) not known: the minimum only applies when pay is known
            ok = "'stated','estimated','likely','growth'" + (",'unknown'" if show_unknown else "")
            where.append(f"pay_confidence IN ({ok})")
        if level:
            where.append("level=?")
            args.append(level)
        if country:
            where.append("country=?")
            args.append(country)
        elif countries:  # only the countries currently searched (+ jobs whose country is unknown, e.g. remote)
            where.append(f"(country IN ({','.join('?' * len(countries))}) OR country='' OR country IS NULL)")
            args += list(countries)
        order = {
            "score": "score DESC, first_seen DESC",
            "new": "first_seen DESC",
            "posted": "COALESCE(posted_at, first_seen) DESC",
            "company": "company COLLATE NOCASE, score DESC",
        }.get(sort, "score DESC")
        sql = "SELECT * FROM jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order} LIMIT 1000"
        return self.conn.execute(sql, args).fetchall()

    def country_counts(self) -> dict[str, int]:
        return {r[0] or "": r[1] for r in self.conn.execute(
            "SELECT country, COUNT(*) FROM jobs WHERE active=1 AND status IN ('new','starred') GROUP BY country")}

    def companies(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT company FROM jobs WHERE active=1 ORDER BY company COLLATE NOCASE")]

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM jobs WHERE active=1 GROUP BY status"):
            out[r["status"]] = r["c"]
        return out

    def summary(self, show_unknown: bool = True) -> dict:
        """Headline numbers for the dashboard."""
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        good = "pay_confidence IN ('stated','estimated','likely','growth'" + (",'unknown'" if show_unknown else "") + ")"
        return {
            "new_24h": q(f"SELECT COUNT(*) FROM jobs WHERE active=1 AND status='new' AND first_seen>=? AND {good}", day_ago),
            "top": q(f"SELECT COUNT(*) FROM jobs WHERE active=1 AND status IN ('new','starred') AND score>=75 AND {good}"),
            "applied": q("SELECT COUNT(*) FROM jobs WHERE status IN ('applied','interview')"),
            "last_run": q("SELECT MAX(started) FROM runs"),
        }

    def last_run_by_origin(self) -> dict[str, tuple[str, bool]]:
        """{source name: (when its latest run started, whether it succeeded)}"""
        rows = self.conn.execute(
            """SELECT r.origin, r.started, r.ok FROM runs r
               JOIN (SELECT origin, MAX(id) mid FROM runs GROUP BY origin) m ON r.id = m.mid""")
        return {r["origin"]: (r["started"], bool(r["ok"])) for r in rows}

    def last_run_started(self) -> Optional[str]:
        return self.conn.execute("SELECT MAX(started) FROM runs").fetchone()[0]

    def last_runs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT r.* FROM runs r JOIN (SELECT origin, MAX(id) mid FROM runs GROUP BY origin) m
               ON r.id = m.mid ORDER BY r.ok, r.origin COLLATE NOCASE"""
        ).fetchall()
