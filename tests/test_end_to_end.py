from jobhunter.config import load_config
from jobhunter.db import DB
from jobhunter.models import RawJob
from jobhunter.runner import run_scraper
from jobhunter.scrapers.base import Scraper
from jobhunter.web.app import create_app


class Fake(Scraper):
    def __init__(self, cfg, name, source, jobs):
        super().__init__(cfg, {"name": name})
        self.src, self.jobs = source, jobs

    def fetch(self):
        for t, loc, desc in self.jobs:
            yield RawJob(source=self.src, origin=self.name, company="Adyen", title=t, url=f"http://{self.src}/{t}",
                         location=loc, description=desc)


def test_pipeline_and_web(tmp_path):
    cfg = load_config("config.example.yaml")
    cfg["db_path"] = str(tmp_path / "t.db")
    db = DB(cfg["db_path"])
    jobs = [("Software Engineer", "Amsterdam", "C# and Azure, 2+ years of experience"),
            ("Senior Software Engineer", "Amsterdam", ""), ("Software Engineer", "Paris, France", "")]
    stats = run_scraper(Fake(cfg, "LinkedIn", "linkedin", jobs), cfg, db, "2026-10-09T00:00:00+00:00")
    assert (stats.seen, stats.kept, stats.new) == (3, 1, 1)
    # same job later from the company site: de-duplicated, company URL wins
    run_scraper(Fake(cfg, "Adyen", "greenhouse", jobs), cfg, db, "2026-10-10T00:00:00+00:00")
    rows = db.list_jobs(pay="all")
    assert len(rows) == 1 and rows[0]["source"] == "greenhouse"

    app = create_app(cfg)
    c = app.test_client()
    assert b"Software Engineer" in c.get("/").data
    jid = rows[0]["id"]
    page = c.get(f"/job/{jid}").data
    assert b"Motivation letter draft" in page and b"Adyen" in page
    assert c.post(f"/api/job/{jid}/status", json={"status": "applied"}).status_code == 200
    assert db.get(jid)["applied_at"] and not db.list_jobs(status="open")
    assert c.post(f"/api/job/{jid}/status", json={"status": "bogus"}).status_code == 400
    assert c.get("/status").status_code == 200 and c.get("/profile").status_code == 200
    assert c.get("/export.csv?status=all").data.startswith(b"score,")
