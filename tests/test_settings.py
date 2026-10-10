from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.datastructures import MultiDict

from jobhunter import settings
from jobhunter.config import load_base, load_config
from jobhunter.db import DB
from jobhunter.scheduler import is_due
from jobhunter.web.app import create_app


@pytest.fixture
def env(tmp_path):
    """A config.yaml + DB in a temp dir, like a real install."""
    (tmp_path / "config.yaml").write_text(
        f"db_path: {tmp_path}/j.db\ncompanies:\n  - {{name: Adyen, ats: greenhouse, board: adyen, tier: 1}}\n")
    cfg = load_config(tmp_path / "config.yaml")
    return tmp_path, cfg, create_app(cfg).test_client()


def test_parse_and_validation():
    f = {x.path: x for s in settings.SECTIONS for x in s.fields}
    assert settings.parse(f["search.min_salary"], MultiDict({"search.min_salary": "90.000"})) == 90000
    assert settings.parse(f["profile.skills"], MultiDict({"profile.skills": "C#: 3\n.NET:2\nDocker"})) == {"C#": 3, ".NET": 2, "Docker": 1}
    assert settings.parse(f["search.include_remote"], MultiDict({})) is False
    assert settings.parse(f["search.include_remote"], MultiDict({"search.include_remote": "on"})) is True
    assert settings.parse(f["linkedin.experience_levels"],
                          MultiDict([("linkedin.experience_levels", "3"), ("linkedin.experience_levels", "2")])) == [2, 3]
    for path, bad in [("search.min_salary", "lots"), ("search.max_years_required", "99"),
                      ("profile.skills", "C#: 9"), ("search.title_include", "(oops"),
                      ("salary.benchmarks", "Mollie | senior | 1 | 2"), ("schedule.every_hours", "0")]:
        with pytest.raises(ValueError):
            settings.parse(f[path], MultiDict({path: bad}))


def test_settings_persist_apply_live_and_reset(env):
    tmp, cfg, c = env
    form = {"search.min_salary": "85000", "search.big_company_min_salary": "65000", "search.max_years_required": "3",
            "search.max_age_days": "30", "search.country_keywords": "netherlands\namsterdam",
            "search.big_company_tiers": "1"}
    r = c.post("/settings/matching", data=form, follow_redirects=True)
    assert b"Saved" in r.data
    assert cfg["search"]["min_salary"] == 85000 and cfg["search"]["include_remote"] is False  # live in the running app
    # a *separate process* (the CLI scraper) sees it too, because it is stored in the DB
    assert load_config(tmp / "config.yaml")["search"]["min_salary"] == 85000
    assert load_config(tmp / "config.yaml")["search"]["country_keywords"] == ["netherlands", "amsterdam"]
    # invalid input saves nothing and shows the reason
    bad = c.post("/settings/matching", data={**form, "search.min_salary": "abc"}, follow_redirects=True)
    assert b"must be a number" in bad.data and cfg["search"]["min_salary"] == 85000
    # reset
    c.post("/settings/matching/reset")
    assert cfg["search"]["min_salary"] == 90000
    assert load_config(tmp / "config.yaml")["search"]["min_salary"] == 90000
    # values equal to the base default are not stored at all
    c.post("/settings/matching", data={**form, "search.min_salary": "90000", "search.big_company_min_salary": "70000",
                                       "search.max_years_required": "4", "search.max_age_days": "60",
                                       "search.country_keywords": "\n".join(load_base(tmp / "config.yaml")["search"]["country_keywords"])})
    assert settings.read_overrides(cfg["db_path"]).get("search.min_salary") is None


def test_every_settings_page_renders(env):
    _, cfg, c = env
    for s in settings.SECTIONS:
        r = c.get(f"/settings/{s.id}")
        assert r.status_code == 200 and s.title.encode().split(b"&")[0][:8] in r.data
    assert c.get("/settings/nope").status_code == 404
    for url in ("/help", "/companies", "/companies?edit=new", "/companies?edit=0", "/status", "/profile", "/"):
        assert c.get(url).status_code == 200, url


def test_profile_settings_change_cover_letter(env):
    _, cfg, c = env
    form = {"profile.name": "Caz", "profile.email": "c@x.nl", "profile.phone": "1", "profile.linkedin": "li",
            "profile.github": "", "profile.location": "Almere", "profile.years_experience": "3",
            "profile.pitch": "I build APIs.", "cover_letter": "Hi {company}, I am {name}. {pitch}",
            "profile.skills": "C#: 3"}
    assert b"Saved" in c.post("/settings/profile", data=form, follow_redirects=True).data
    assert cfg["profile"]["skills"] == {"C#": 3} and cfg["profile"]["name"] == "Caz"


def test_companies_add_edit_toggle_delete_reset(env):
    tmp, cfg, c = env
    assert b"Saved Mollie" in c.post("/companies/save", data={"name": "Mollie", "ats": "greenhouse", "board": "mollie", "tier": "2"},
                                     follow_redirects=True).data
    assert [x["name"] for x in cfg["companies"]] == ["Adyen", "Mollie"] and cfg["companies"][1]["tier"] == 2
    # missing required field -> error, nothing saved
    r = c.post("/companies/save", data={"name": "X", "ats": "workday", "tenant": "x"}, follow_redirects=True)
    assert b"Server" in r.data and len(cfg["companies"]) == 2
    # edit keeps untouched keys (browser 'steps' are not in the form)
    cfg["companies"].append({"name": "G", "ats": "browser", "url": "https://g", "link_pattern": "/j/\\d+", "tier": 1,
                             "steps": [{"wait": 5}]})
    settings.save_values(DB(cfg["db_path"]), cfg, load_base(tmp / "config.yaml"), {"companies": cfg["companies"]})
    c.post("/companies/save", data={"idx": "2", "name": "G2", "ats": "browser", "url": "https://g2", "link_pattern": "/j/\\d+", "tier": "1"})
    assert cfg["companies"][2]["name"] == "G2" and cfg["companies"][2]["steps"] == [{"wait": 5}]
    c.post("/companies/0/toggle")
    assert cfg["companies"][0]["disabled"] is True
    c.post("/companies/0/toggle")
    assert "disabled" not in cfg["companies"][0]
    c.post("/companies/1/delete")
    assert [x["name"] for x in cfg["companies"]] == ["Adyen", "G2"]
    assert [x["name"] for x in load_config(tmp / "config.yaml")["companies"]] == ["Adyen", "G2"]  # persisted
    c.post("/companies/reset")
    assert [x["name"] for x in cfg["companies"]] == ["Adyen"]


def test_company_test_button_reports_errors(env):
    _, cfg, c = env
    r = c.post("/companies/0/test")  # no network in tests -> must be a clean JSON error, not a 500
    assert r.status_code == 200 and r.get_json()["ok"] is False


def test_scheduler_is_due():
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    iso = lambda h: (now - timedelta(hours=h)).isoformat()
    assert is_due(now, None, 6, True)             # never ran
    assert not is_due(now, iso(2), 6, True)       # ran recently
    assert is_due(now, iso(7), 6, True)           # overdue
    assert not is_due(now, iso(99), 6, False)     # switched off
    assert is_due(now, iso(2), 1, True)           # shorter interval takes effect


def test_settings_doc_is_up_to_date():
    import subprocess, sys
    r = subprocess.run([sys.executable, "tools/gen_settings_doc.py", "--check"])
    assert r.returncode == 0, "docs/SETTINGS.md is stale: run  python tools/gen_settings_doc.py"
