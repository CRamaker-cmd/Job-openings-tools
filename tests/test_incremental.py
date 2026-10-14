"""Only new postings cost anything; known and previously rejected ones are skipped."""
import pytest

from helpers import set_pay
from jobhunter.config import load_config
from jobhunter.db import DB
from jobhunter.models import RawJob
from jobhunter.runner import rescore, run_scraper
from jobhunter.salary import Estimator
from jobhunter.scrapers.base import Scraper
from jobhunter.web.app import create_app


class Src(Scraper):
    """Lists postings WITHOUT descriptions (like Greenhouse/Workday), and counts detail requests."""

    def __init__(self, cfg, name, source, items):
        super().__init__(cfg, {"name": name})
        self.src, self.items, self.detail_calls = source, items, []

    def fetch(self):
        for ext, title, _desc in self.items:
            yield RawJob(source=self.src, origin=self.name, company="Adyen", title=title, url=f"http://{self.src}/{ext}",
                         location="Amsterdam, Netherlands", external_id=ext)

    def enrich(self, job):
        self.detail_calls.append(job.external_id)
        job.description = dict((e, d) for e, _, d in self.items)[job.external_id]


@pytest.fixture
def env(tmp_path):
    cfg = load_config("config.example.yaml")
    cfg["db_path"] = str(tmp_path / "i.db")
    cfg["schedule"]["pause_between_requests"] = 0
    cfg["salary"]["online_lookup"] = False
    db = DB(cfg["db_path"])
    return cfg, db, Estimator(cfg, db)


ITEMS = [("1", "Software Engineer", "Python and Docker. 2+ years of experience."),
         ("2", "Backend Engineer", "Needs 9+ years of experience."),   # will be rejected after its details are read
         ("3", "Staff Engineer", "x")]                                  # rejected by title alone: no request at all


def test_known_and_rejected_postings_are_not_fetched_again(env):
    cfg, db, est = env
    s = Src(cfg, "Adyen", "greenhouse", ITEMS)
    st = run_scraper(s, cfg, db, "2026-10-10T00:00:00+00:00", est)
    assert (st.seen, st.known, st.new) == (3, 0, 1) and s.detail_calls == ["1", "2"]   # "3" never needed a request

    s2 = Src(cfg, "Adyen", "greenhouse", ITEMS)
    st = run_scraper(s2, cfg, db, "2026-10-11T00:00:00+00:00", est)
    assert s2.detail_calls == [] and (st.known, st.new) == (2, 0)                      # nothing fetched, nothing re-scored
    assert db.list_jobs(pay="all")[0]["last_seen"].startswith("2026-10-11")           # but still marked as listed

    # a job that disappears from the source is deactivated; the others stay
    db.deactivate_unseen("Adyen", "2026-10-12T00:00:00+00:00")
    assert db.list_jobs(pay="all") == []


def test_delete_makes_the_app_look_at_a_job_again(env):
    cfg, db, est = env
    run_scraper(Src(cfg, "Adyen", "greenhouse", ITEMS), cfg, db, "2026-10-10T00:00:00+00:00", est)
    [row] = db.list_jobs(pay="all")
    db.set_status(row["id"], "hidden")
    s = Src(cfg, "Adyen", "greenhouse", ITEMS)
    run_scraper(s, cfg, db, "2026-10-11T00:00:00+00:00", est)
    assert s.detail_calls == [] and db.list_jobs(status="hidden", pay="all")            # hidden stays hidden, never re-checked
    db.delete_job(row["id"])
    s = Src(cfg, "Adyen", "greenhouse", ITEMS)
    st = run_scraper(s, cfg, db, "2026-10-12T00:00:00+00:00", est)
    assert st.new == 1 and s.detail_calls == ["1"]                                     # back as a new job, re-checked


def test_company_site_copy_replaces_linkedin_link_without_refetching(env):
    cfg, db, est = env
    li = Src(cfg, "LinkedIn", "linkedin", [("9", "Software Engineer", "Python and Docker.")])
    run_scraper(li, cfg, db, "2026-10-10T00:00:00+00:00", est)
    gh = Src(cfg, "Adyen", "greenhouse", [("1", "Software Engineer", "ignored")])
    run_scraper(gh, cfg, db, "2026-10-10T01:00:00+00:00", est)
    [row] = db.list_jobs(pay="all")
    assert gh.detail_calls == [] and row["source"] == "greenhouse" and row["url"] == "http://greenhouse/1"


def test_rejected_memory_is_cleared_when_rules_change(env):
    cfg, db, est = env
    run_scraper(Src(cfg, "Adyen", "greenhouse", ITEMS), cfg, db, "2026-10-10T00:00:00+00:00", est)
    cfg["search"]["max_years_required"] = 12            # the user relaxes the rule...
    db.clear_rejected()                                 # ...which the dashboard does on save
    s = Src(cfg, "Adyen", "greenhouse", ITEMS)
    run_scraper(s, cfg, db, "2026-10-11T00:00:00+00:00", est)
    assert s.detail_calls == ["2"] and len(db.list_jobs(pay="all")) == 2               # the 9-years job now qualifies


def test_rescore_applies_new_rules_locally(env):
    cfg, db, est = env
    items = [("1", "Software Engineer", "Salary €95.000 - €100.000. Python."), ("2", "Backend Engineer", "Salary €95.000 - €99.000. Python.")]
    run_scraper(Src(cfg, "Nobody BV", "greenhouse", items), cfg, db, "2026-10-10T00:00:00+00:00", est)
    rows = {r["title"]: r for r in db.list_jobs(pay="all")}
    db.set_status(rows["Backend Engineer"]["id"], "starred")
    cfg["search"]["big_company_tiers"] = []              # (Src labels everything "Adyen", a big company: switch that exception off)
    set_pay(cfg, "NL", min=99000)                  # raise the bar: both postings still reach it (max 100k / 99k)
    done, moved = rescore(cfg, db)
    after = {r["title"]: r["status"] for r in db.list_jobs(status="all", pay="all")}
    assert after["Software Engineer"] == "new" and done == 2                            # both still pass
    set_pay(cfg, "NL", min=120000)                 # now neither does
    done, moved = rescore(cfg, db)
    after = {r["title"]: r["status"] for r in db.list_jobs(status="all", pay="all")}
    assert moved == 1 and after["Software Engineer"] == "hidden" and after["Backend Engineer"] == "starred"  # starred is never moved


def test_web_delete_and_rescore_message(env, full_form):
    cfg, db, est = env
    run_scraper(Src(cfg, "Adyen", "greenhouse", ITEMS), cfg, db, "2026-10-10T00:00:00+00:00", est)
    c = create_app(cfg).test_client()
    [row] = db.list_jobs(pay="all")
    assert b"Delete" in c.get(f"/job/{row['id']}").data
    assert c.post(f"/api/job/{row['id']}/delete").status_code == 200 and db.get(row["id"]) is None
    assert c.post("/api/job/999/delete").status_code == 404
    form = full_form(cfg, "matching")
    assert b"Re-scored" in c.post("/settings/matching", data=form, follow_redirects=True).data


# ---------------------------------------------------------------- re-posted openings ("a new batch")
from datetime import datetime, timedelta, timezone

D0 = datetime.now(timezone.utc) - timedelta(days=55)   # recent enough to pass the "too old" rule


class Posts(Scraper):
    """Yields postings with explicit ids/dates/sources, descriptions included (no detail calls)."""

    def __init__(self, cfg, name, source, posts):
        super().__init__(cfg, {"name": name})
        self.src, self.posts = source, posts

    def fetch(self):
        for ext, day_offset, extra in self.posts:
            yield RawJob(source=self.src, origin=self.name, company="Adyen", title="Software Engineer",
                         url=f"http://{self.src}/{ext or 'x'}", location="Amsterdam, Netherlands", external_id=ext,
                         description="Python and Docker. 2+ years of experience.", extra=extra,
                         posted_at=None if day_offset is None else D0 + timedelta(days=day_offset))


def scrape(env, source, posts, n):
    cfg, db, est = env
    return run_scraper(Posts(cfg, "X", source, posts), cfg, db, f"2026-10-{n:02d}T00:00:00+00:00", est)


def test_same_id_and_similar_date_is_the_same_opening(env):
    assert scrape(env, "lever", [("a1", 0, {})], 1).new == 1
    assert scrape(env, "lever", [("a1", 0, {})], 2).known == 1                 # untouched
    assert scrape(env, "lever", [("a1", 5, {})], 3).known == 1                 # date drifted a few days: still the same opening


def test_same_id_posted_much_later_is_a_new_batch(env):
    scrape(env, "lever", [("a1", 0, {})], 1)
    st = scrape(env, "lever", [("a1", 45, {})], 2)                             # same id, +45 days (> 30): re-posted
    assert st.new == 1 and len(env[1].list_jobs(pay="all")) == 2


def test_new_id_is_a_new_opening_even_with_identical_title(env):
    scrape(env, "lever", [("a1", 0, {})], 1)
    st = scrape(env, "lever", [("b2", 3, {})], 2)                              # same title/company/city, new id
    assert st.new == 1 and len(env[1].list_jobs(pay="all")) == 2
    assert scrape(env, "lever", [("a1", 0, {}), ("b2", 3, {})], 3).known == 2  # and both are recognised from now on


def test_unreliable_dates_never_make_a_repost(env):
    gh = {"date_unreliable": True}                                             # e.g. Greenhouse "last edited" timestamp
    scrape(env, "greenhouse", [("g1", 0, gh)], 1)
    assert scrape(env, "greenhouse", [("g1", 90, gh)], 2).known == 1           # edited 90 days later: NOT a repost


def test_without_ids_the_posting_date_decides(env):
    scrape(env, "browser", [("", 0, {})], 1)
    assert scrape(env, "browser", [("", 2, {})], 2).known == 1                 # close dates: same opening
    assert scrape(env, "browser", [("", 60, {})], 3).new == 1                  # two months later: a new batch
    assert scrape(env, "browser", [("", None, {})], 4).known == 1              # no date at all: can't tell, don't re-handle


def test_cross_site_copy_is_matched_by_title_and_date_not_id(env):
    scrape(env, "linkedin", [("li-1", 0, {})], 1)
    assert scrape(env, "greenhouse", [("gh-9", 2, {})], 2).known == 1          # same role on the company site, similar date
    st = scrape(env, "greenhouse", [("gh-10", 70, {})], 3)                     # same role months later: new batch
    assert st.new == 1


def test_rejected_repost_is_looked_at_again(env):
    cfg, db, est = env
    cfg["search"]["max_years_required"] = 0                                    # everything asking 2+ years is rejected
    scrape(env, "lever", [("a1", 0, {})], 1)
    assert db.list_jobs(pay="all") == []
    assert scrape(env, "lever", [("a1", 0, {})], 2).known == 1                 # remembered as rejected: not re-evaluated
    cfg["search"]["max_years_required"] = 4
    assert scrape(env, "lever", [("a1", 60, {})], 3).new == 1                  # re-posted 60 days later: checked again, now passes


# ---------------------------------------------------------------- jobs saved with unknown pay get another chance
def test_unknown_pay_jobs_are_retried_in_later_runs_within_the_lookup_budget(env):
    from jobhunter.runner import refresh_unknown_pay
    cfg, db, _ = env
    cfg["salary"]["online_lookup"], cfg["salary"]["max_lookups_per_run"], cfg["salary"]["delay_seconds"] = True, 3, 0

    def fake_estimator():
        est = Estimator(cfg, db)

        def fake_get(url, params=None, timeout=0):
            co = params["q"].split(" software engineer")[0]
            class R:
                status_code = 200
                text = f'<div class="result">{co} software engineer salary: average €96,000 per year</div>'
            return R()
        est.http.get = fake_get
        return est

    class Many(Scraper):
        def fetch(self):
            for i in range(8):
                yield RawJob(source="linkedin", origin="LinkedIn NL", company=f"Co{i} BV", title="Software Engineer", url=f"u{i}",
                             location="Amsterdam, Netherlands", external_id=str(i), description="Python and Docker.")
    cfg["salary"]["max_lookups_per_run"] = 0                                    # first run: web lookups unavailable
    run_scraper(Many(cfg, {"name": "L"}), cfg, db, "2026-10-14T00:00:00+00:00", fake_estimator())
    unknown = lambda: sum(1 for r in db.list_jobs(pay="all") if r["pay_confidence"] == "unknown")
    assert unknown() == 8
    assert len(db.list_jobs(pay="good", show_unknown=True)) == 8               # visible by default, marked "pay unknown"
    assert len(db.list_jobs(pay="good", show_unknown=False)) == 0              # ...and hideable with the setting

    cfg["salary"]["max_lookups_per_run"] = 3
    est = fake_estimator()
    assert refresh_unknown_pay(cfg, db, est) == 3 and est.lookups == 3          # budget respected
    assert unknown() == 5
    est2 = fake_estimator()
    assert refresh_unknown_pay(cfg, db, est2) == 3 and unknown() == 2           # the next run continues where the last stopped
    assert all(r["pay_confidence"] == "estimated" for r in db.list_jobs(pay="all") if r["pay_confidence"] != "unknown")
