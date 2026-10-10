from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .filters import Evaluation
from .models import RawJob, fingerprint

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    origin TEXT NOT NULL,
    external_id TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
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
        """Insert or refresh a job. Returns True if it is new."""
        ts = ts or now_iso()
        fp = fingerprint(job.company, job.title, job.location)
        row = self.conn.execute("SELECT id, source FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
        reasons = json.dumps(ev.reasons)
        posted = job.posted_at.isoformat() if job.posted_at else None
        pay = (ev.salary_min, ev.salary_max, ev.pay_confidence, ev.est_min, ev.est_max,
               ev.pay_source, ev.pay_note, ev.level, ev.score, reasons)
        if row is None:
            self.conn.execute(
                """INSERT INTO jobs (salary_min, salary_max, pay_confidence, est_min, est_max, pay_source,
                   pay_note, level, score, reasons, fingerprint, source, origin, external_id, company,
                   title, location, url, description, posted_at, first_seen, last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?, ?,?,?,?,?,?,?,?,?,?,?,?)""",
                pay + (fp, job.source, job.origin, job.external_id, job.company, job.title,
                       job.location, job.url, job.description, posted, ts, ts),
            )
            self.conn.commit()
            return True
        # Same job already known: refresh. A company-site copy replaces a LinkedIn copy.
        better = SOURCE_PRIORITY.get(job.source, 1) > SOURCE_PRIORITY.get(row["source"], 1)
        sql = """UPDATE jobs SET active=1, last_seen=?, salary_min=?, salary_max=?, pay_confidence=?,
                 est_min=?, est_max=?, pay_source=?, pay_note=?, level=?, score=?, reasons=?"""
        args = (ts,) + pay
        if better:
            sql += ", source=?, origin=?, external_id=?, url=?, description=?, location=?"
            args += (job.source, job.origin, job.external_id, job.url, job.description, job.location)
        self.conn.execute(sql + " WHERE id=?", args + (row["id"],))
        self.conn.commit()
        return False

    def deactivate_unseen(self, origin: str, run_started: str, grace_days: int = 0) -> None:
        cutoff = (datetime.fromisoformat(run_started) - timedelta(days=grace_days)).isoformat(timespec="seconds")
        self.conn.execute(
            "UPDATE jobs SET active=0 WHERE origin=? AND last_seen < ?", (origin, cutoff)
        )
        self.conn.commit()

    def record_run(self, started: str, origin: str, ok: bool, seen=0, kept=0, new=0, error=None) -> None:
        self.conn.execute(
            "INSERT INTO runs (started, origin, ok, seen, kept, new, error) VALUES (?,?,?,?,?,?,?)",
            (started, origin, int(ok), seen, kept, new, error),
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
        if pay == "good":
            where.append("pay_confidence IN ('stated','estimated','likely','growth')")
        if level:
            where.append("level=?")
            args.append(level)
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

    def companies(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT company FROM jobs WHERE active=1 ORDER BY company COLLATE NOCASE")]

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM jobs WHERE active=1 GROUP BY status"):
            out[r["status"]] = r["c"]
        return out

    def summary(self) -> dict:
        """Headline numbers for the dashboard."""
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        q = lambda sql, *a: self.conn.execute(sql, a).fetchone()[0]
        good = "pay_confidence IN ('stated','estimated','likely','growth')"
        return {
            "new_24h": q(f"SELECT COUNT(*) FROM jobs WHERE active=1 AND status='new' AND first_seen>=? AND {good}", day_ago),
            "top": q(f"SELECT COUNT(*) FROM jobs WHERE active=1 AND status IN ('new','starred') AND score>=75 AND {good}"),
            "applied": q("SELECT COUNT(*) FROM jobs WHERE status IN ('applied','interview')"),
            "last_run": q("SELECT MAX(started) FROM runs"),
        }

    def last_run_started(self) -> Optional[str]:
        return self.conn.execute("SELECT MAX(started) FROM runs").fetchone()[0]

    def last_runs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT r.* FROM runs r JOIN (SELECT origin, MAX(id) mid FROM runs GROUP BY origin) m
               ON r.id = m.mid ORDER BY r.ok, r.origin COLLATE NOCASE"""
        ).fetchall()
