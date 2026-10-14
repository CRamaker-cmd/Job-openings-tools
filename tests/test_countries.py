"""Several countries: location matching, per-country minimums in local currency, other currencies, LinkedIn per country."""
import pytest
from werkzeug.datastructures import MultiDict

from jobhunter import countries, money, settings
from jobhunter.config import load_config
from jobhunter.db import DB
from jobhunter.filters import evaluate, location_ok
from jobhunter.models import RawJob
from jobhunter.pay import parse_pay
from jobhunter.runner import run_scraper
from jobhunter.salary import Estimator
from jobhunter.scrapers import build_scrapers, source_names
from jobhunter.scrapers.base import Scraper


def cfg_for(*codes, **search):
    cfg = load_config("config.example.yaml")
    cfg["search"]["countries"] = list(codes)
    cfg["search"].update(search)
    return cfg


def job(loc, desc="", company="Nobody BV", title="Software Engineer", **kw):
    return RawJob(source="linkedin", origin="LinkedIn", company=company, title=title, url="u", location=loc, description=desc, **kw)


# ------------------------------------------------------------------ which jobs count as "in my countries"
def test_location_matches_only_selected_countries():
    nl, de, both = cfg_for("NL"), cfg_for("DE"), cfg_for("NL", "DE")
    for loc, cfgs_ok in [("Amsterdam, North Holland, Netherlands", (nl, both)), ("Berlin, Germany", (de, both)),
                         ("München, Bayern, Deutschland", (de, both)), ("London, England, United Kingdom", ())]:
        for c in (nl, de, both):
            assert location_ok(loc, c, strict=True) == (c in cfgs_ok), (loc, c["search"]["countries"])
    assert not location_ok("Hannover, Germany", nl, strict=True)          # 'nl' is never found inside other words
    assert not location_ok("Remote", nl, strict=True) and location_ok("Remote", cfg_for("NL", include_remote=True), strict=True)


def test_country_is_detected_and_stored():
    assert countries.detect_country("Utrecht, Netherlands", cfg_for("NL", "DE")) == "NL"
    assert countries.detect_country("Hamburg", cfg_for("NL", "DE")) == "DE"
    assert countries.detect_country("Remote") == ""
    cfg = cfg_for("NL", "DE")
    assert evaluate(job("Berlin, Germany", "Python"), cfg).country == "DE"


# ------------------------------------------------------------------ per-country minimum, in the country's own currency
def test_per_country_minimum_is_in_local_currency():
    cfg = cfg_for("NL", "GB", min_salary_by_country={"GB": 70000})      # £70,000 = ~€80,500 at the default 1.15
    assert countries.min_salary_for(cfg, "NL") == 90000                   # no entry: the general (EUR) minimum
    assert countries.min_salary_for(cfg, "GB") == round(70000 * 1.15)
    ok = evaluate(job("London, United Kingdom", "Salary £75,000 - £85,000 per year"), cfg)       # ~€86-98k, above £70k
    low = evaluate(job("London, United Kingdom", "Salary £55,000 - £62,000 per year"), cfg)      # ~€63-71k: below
    assert ok.ok and ok.country == "GB" and ok.pay_confidence == "stated"
    assert not low.ok and "pays up to" in low.reject
    assert "£" in " ".join(ok.reasons) and "€" not in " ".join(ok.reasons)   # shown in the job's own currency


def test_without_a_country_entry_the_general_minimum_applies_to_every_currency():
    cfg = cfg_for("NL", "GB")                                               # general minimum: EUR 90k = ~£78k
    assert not evaluate(job("London, United Kingdom", "Salary £70,000 - £75,000 per year"), cfg).ok      # £75k = €86k < €90k
    assert evaluate(job("London, United Kingdom", "Salary £75,000 - £82,000 per year"), cfg).ok          # £82k = €94k


def test_big_company_floor_per_country():
    cfg = cfg_for("NL", "CH", min_salary_by_country={"CH": 120000}, big_company_min_by_country={"CH": 100000},
                  big_company_tiers=[1])
    cfg["companies"] = [{"name": "Google", "ats": "browser", "tier": 1}]
    # CHF 105k: under the CHF 120k minimum but over the CHF 100k big-company floor -> kept as 'growth' at a big company
    g = evaluate(job("Zürich, Switzerland", "Salary CHF 105,000 - CHF 108,000 per year", company="Google"), cfg)
    assert g.ok and g.pay_confidence == "growth" and g.country == "CH"
    assert not evaluate(job("Zürich, Switzerland", "Salary CHF 105,000 - CHF 108,000 per year", company="Nobody AG"), cfg).ok
    assert not evaluate(job("Zürich, Switzerland", "Salary CHF 90,000 - CHF 95,000 per year", company="Google"), cfg).ok
    # no explicit floor: scaled in proportion (70/90 of the country minimum)
    cfg2 = cfg_for("CH", min_salary_by_country={"CH": 120000})
    assert countries.big_floor_for(cfg2, "CH") == round(120000 * 1.05 * 70000 / 90000)


def test_holiday_pay_is_only_added_in_the_netherlands():
    cfg = cfg_for("NL", "DE")
    assert parse_pay("€5.000 per Monat", cfg, "NL").lo == 64800           # x12 + 8 % (Dutch vakantiegeld)
    assert parse_pay("€5.000 pro Monat", cfg, "DE").lo == 60000           # Germany: x12 only, and German period words work
    assert parse_pay("£4,500 per month", cfg, "GB").lo == round(4500 * 12 * 1.15)
    assert parse_pay("SEK 55 000 - 70 000 per månad", cfg, "SE").lo == round(55000 * 12 * 0.09)


def test_money_formatting_and_conversion():
    cfg = load_config("config.example.yaml")
    assert money.fmt(95000, "EUR") == "€95k" and money.fmt(60000, "GBP") == "£60k" and money.fmt(120000, "CHF") == "CHF 120k"
    assert money.rng(60000, 75000, "GBP") == "£60–75k" and money.fmt(5500) == "€5,500"
    assert money.to_local(115000, "GBP", cfg) == pytest.approx(100000)
    cfg["search"]["fx_to_eur"] = {"GBP": 1.20}
    assert money.to_eur(100000, "GBP", cfg) == pytest.approx(120000)       # exchange rates are a setting


# ------------------------------------------------------------------ settings
def test_per_country_settings_parse_and_validate():
    f = {x.path: x for s in settings.SECTIONS for x in s.fields}
    p = lambda path, text: settings.parse(f[path], MultiDict({path: text}))
    assert p("search.min_salary_by_country", "GB: £70,000\nde: 80.000\nCH: 120000 CHF\nSE: SEK 700 000") == \
           {"GB": 70000, "DE": 80000, "CH": 120000, "SE": 700000}
    for bad in ("GB: 70000 EUR", "XX: 70000", "GB: lots", "GB: €70000", "GB 70000"):
        with pytest.raises(ValueError):
            p("search.min_salary_by_country", bad)
    assert settings.parse(f["search.countries"], MultiDict([("search.countries", "NL"), ("search.countries", "DE")])) == ["NL", "DE"]
    with pytest.raises(ValueError):
        settings.parse(f["search.countries"], MultiDict())                 # at least one country


# ------------------------------------------------------------------ scrapers and the database
def test_linkedin_is_one_source_per_country_and_feeds_use_all_countries():
    cfg = cfg_for("NL", "DE")
    assert [n for n in source_names(cfg) if n.startswith("LinkedIn")] == ["LinkedIn NL", "LinkedIn DE"]
    li = [s for s in build_scrapers(cfg) if s.name.startswith("LinkedIn")]
    assert [s.country.linkedin_location for s in li] == ["Netherlands", "Germany"]
    from jobhunter.scrapers.custom import Amazon, Uber
    assert [c.iso3 for c in Amazon(cfg, {"name": "Amazon"}).countries()] == ["NLD", "DEU"]


def test_jobs_from_two_countries_are_stored_filtered_and_unselected_countries_hidden(tmp_path):
    cfg = cfg_for("NL", "DE")
    cfg["db_path"] = str(tmp_path / "c.db"); cfg["schedule"]["pause_between_requests"] = 0; cfg["salary"]["online_lookup"] = False
    db = DB(cfg["db_path"])

    class Two(Scraper):
        def fetch(self):
            yield job("Amsterdam, Netherlands", "Python and Docker. Salary €95.000 - €100.000", external_id="1", company="A BV")
            yield job("Berlin, Germany", "Python and Docker. Salary €92.000 - €99.000", external_id="2", company="B GmbH")
    run_scraper(Two(cfg, {"name": "X"}), cfg, db, "2026-10-14T00:00:00+00:00", Estimator(cfg, db))
    assert {r["country"] for r in db.list_jobs(pay="all")} == {"NL", "DE"}
    assert [r["country"] for r in db.list_jobs(pay="all", country="DE")] == ["DE"]
    assert [r["country"] for r in db.list_jobs(pay="all", countries=["NL"])] == ["NL"]       # DE no longer searched: hidden
    assert db.country_counts() == {"NL": 1, "DE": 1}


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "old.db")
    con.executescript("""CREATE TABLE jobs (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
        origin TEXT NOT NULL, external_id TEXT, company TEXT NOT NULL, title TEXT NOT NULL, location TEXT, url TEXT NOT NULL,
        description TEXT, posted_at TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        salary_min INTEGER, salary_max INTEGER, pay_confidence TEXT, level TEXT, score INTEGER NOT NULL DEFAULT 0, reasons TEXT,
        status TEXT NOT NULL DEFAULT 'new', notes TEXT DEFAULT '', applied_at TEXT);
        CREATE TABLE runs (id INTEGER PRIMARY KEY, started TEXT NOT NULL, origin TEXT NOT NULL, ok INTEGER NOT NULL,
        seen INTEGER DEFAULT 0, kept INTEGER DEFAULT 0, new INTEGER DEFAULT 0, error TEXT);
        INSERT INTO jobs (fingerprint, source, origin, company, title, location, url, first_seen, last_seen)
        VALUES ('f','linkedin','LinkedIn','Adyen','Engineer','Amsterdam, Netherlands','u','t','t');
        INSERT INTO runs (started, origin, ok) VALUES ('t','LinkedIn',1);""")
    con.commit(); con.close()
    db = DB(str(tmp_path / "old.db"))
    row = db.conn.execute("SELECT country, origin FROM jobs").fetchone()
    assert (row["country"], row["origin"]) == ("NL", "LinkedIn NL")           # existing jobs were all Netherlands
    assert db.conn.execute("SELECT origin FROM runs").fetchone()[0] == "LinkedIn NL"


def test_dashboard_shows_country_filter_and_local_currency(tmp_path, full_form):
    from jobhunter.web.app import create_app
    cfg = cfg_for("NL", "GB", min_salary_by_country={"GB": 70000})
    cfg["db_path"] = str(tmp_path / "w.db"); cfg["_config_path"] = "config.example.yaml"
    db = DB(cfg["db_path"])
    db.upsert(job("London, United Kingdom", "Salary £75,000 - £85,000 per year", external_id="9", company="UKCo"),
              evaluate(job("London, United Kingdom", "Salary £75,000 - £85,000 per year", company="UKCo"), cfg), "2026-10-14T00:00:00+00:00")
    c = create_app(cfg).test_client()
    page = c.get("/").data.decode()
    assert "£75–85k" in page and "🇬🇧" in page and 'name="country"' in page            # local currency, flag, country filter
    assert c.get("/?country=NL").data.decode().count('class="job') == 0                  # filtering by another country
    s = c.get("/settings/matching").data.decode()
    assert "GBP" in s and "Your countries and their currency" in s
