from datetime import datetime, timedelta, timezone

import pytest

from jobhunter.config import load_config
from jobhunter.filters import evaluate, location_ok, parse_salary, title_ok, title_level, years_required
from jobhunter.models import RawJob, fingerprint


@pytest.fixture(scope="module")
def cfg():
    return load_config("config.example.yaml")


def job(**kw):
    base = dict(source="greenhouse", origin="Adyen", company="Adyen", title="Software Engineer",
                url="http://x", location="Amsterdam, Netherlands", description="")
    base.update(kw)
    return RawJob(**base)


@pytest.mark.parametrize("title,ok", [
    ("Software Engineer", True), ("Junior .NET Developer", True), ("Backend Engineer (Go)", True),
    ("Software Development Engineer II", True), ("Medior Full Stack Developer", True),
    ("Senior Software Engineer", False), ("Staff Software Engineer", False),
    ("Principal Engineer", False), ("Software Development Engineer III", False),
    ("Engineering Manager", False), ("Sales Engineer", False), ("Solutions Architect", False),
    ("Software Engineer Intern", False), ("Hardware Engineer", False), ("Account Executive", False),
    ("Tech Lead, Payments", False),
])
def test_title_ok(cfg, title, ok):
    assert title_ok(title, cfg)[0] is ok


def test_levels(cfg):
    assert title_level("Junior Developer", cfg) == "junior"
    assert title_level("Software Development Engineer I", cfg) == "junior"
    assert title_level("Software Development Engineer II", cfg) == "medior"
    assert title_level("Medior Developer", cfg) == "medior"
    assert title_level("Software Engineer", cfg) == "unspecified"


def test_location(cfg):
    assert location_ok("Amsterdam, Netherlands", cfg)
    assert location_ok("Amsterdam", cfg, strict=True)
    assert not location_ok("London, UK", cfg, strict=True)
    assert not location_ok("Remote - US", cfg, strict=True)
    assert location_ok("3 Locations", cfg) and not location_ok("3 Locations", cfg, strict=True)
    assert not location_ok("Berlin, Germany", cfg)
    assert not location_ok("Hannover, Germany", cfg)  # 'nl' must not match inside words


@pytest.mark.parametrize("text,expected", [
    ("Salary: €95,000 - €120,000 per year", (95000, 120000)),
    ("between € 4.500 and € 6.000 per maand", (58320, 77760)),   # x12 + 8% holiday pay
    ("EUR 90k - 110k", (90000, 110000)),
    ("€90 - 110k", (90000, 110000)),
    ("Pay range €85.000", (85000, 85000)),
    ("€45 per hour", (None, None)),
    ("a bonus of €5000", (None, None)),
    ("no money talk here", (None, None)),
])
def test_salary(text, expected):
    assert parse_salary(text) == expected


def test_years():
    assert years_required("3+ years of professional experience") == 3
    assert years_required("5-8 years of experience with Java") == 5
    assert years_required("You have 7+ years working with distributed systems") == 7
    assert years_required("Founded 20 years ago, we are great") is None


def test_evaluate_good_job(cfg):
    ev = evaluate(job(description="You know C# and .NET on Azure. 2+ years of experience."), cfg)
    assert ev.ok and ev.pay_confidence == "likely" and ev.score >= 70
    assert {"C#", ".NET", "Azure"} <= set(ev.matched_skills)


def test_evaluate_rejects(cfg):
    assert evaluate(job(location="London, UK"), cfg).reject == "not in your selected countries"
    assert "years" in evaluate(job(description="8+ years of experience required"), cfg).reject
    assert "pays" in evaluate(job(description="Salary €50.000 - €60.000"), cfg).reject
    old = datetime.now(timezone.utc) - timedelta(days=200)
    assert evaluate(job(posted_at=old), cfg).reject == "too old"


def test_unknown_company_ranks_below_known(cfg):
    a = evaluate(job(company="Adyen"), cfg)
    b = evaluate(job(company="Random Consultancy BV"), cfg)
    assert b.pay_confidence == "unknown" and a.score > b.score
    stated = evaluate(job(company="Random Consultancy BV", description="€95.000 - €110.000"), cfg)
    assert stated.pay_confidence == "stated"


def test_fingerprint_dedupes_across_sources():
    a = fingerprint("Adyen", "Software Engineer", "Amsterdam, North Holland, Netherlands")
    b = fingerprint("adyen", "Software  Engineer", "Amsterdam")
    assert a == b
