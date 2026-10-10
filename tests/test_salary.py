from jobhunter.config import load_config
from jobhunter.db import DB
from jobhunter.filters import evaluate
from jobhunter.models import RawJob
from jobhunter.salary import Estimator, PayEstimate, aggregate, parse_snippets

SERP = """
<div class="result"><a class="result__a">Software Engineer salary at Acme Corp | Glassdoor</a>
<a class="result__snippet">The estimated total pay for a Software Engineer at Acme Corp is €82,000 per year in the
Netherlands, with a base salary range of €62K - €95K.</a></div>
<div class="result"><a class="result__a">Acme Corp salaries - Indeed</a>
<a class="result__snippet">Average Acme Corp software engineer salary in Amsterdam: € 6.000 per maand.</a></div>
<div class="result"><a class="result__a">Other Co salary</a><a class="result__snippet">Other Co pays €150,000 per year.</a></div>
<div class="result"><a class="result__a">Acme Corp history</a><a class="result__snippet">Acme Corp was founded in 1999.</a></div>
"""


def cfg_(tmp_path, **sal):
    cfg = load_config("config.example.yaml")
    cfg["db_path"] = str(tmp_path / "s.db")
    cfg["salary"].update(sal)
    return cfg


def job(company="Acme Corp", **kw):
    d = dict(source="linkedin", origin="LinkedIn", company=company, title="Software Engineer", url="u",
             location="Amsterdam, Netherlands", description="Python and Docker")
    d.update(kw)
    return RawJob(**d)


def test_parse_snippets_filters_by_company_and_pay_words():
    found = parse_snippets(SERP, "Acme Corp")
    assert (62000, 95000) in found and (72000, 72000) in found and len(found) == 2  # monthly -> yearly
    assert aggregate(found) == (67000, 83500, 2)
    assert aggregate([]) is None


def test_benchmark_beats_web_and_junior_is_not_faked(tmp_path):
    cfg = cfg_(tmp_path, online_lookup=False)
    est = Estimator(cfg, DB(cfg["db_path"]))
    m = est.estimate("Booking.com B.V.", "medior")
    assert m.source == "benchmark" and m.hi >= 120000
    assert est.estimate("Adyen", "junior") is None  # no junior data -> don't reuse medior numbers
    assert est.estimate("Adyen", "unspecified").lo == 105000
    assert est.estimate("Nobody BV", "medior") is None


def test_user_benchmarks_override(tmp_path):
    cfg = cfg_(tmp_path, online_lookup=False, benchmarks={"Booking.com": {"medior": [50000, 60000]}})
    assert Estimator(cfg, DB(cfg["db_path"])).estimate("Booking.com", "medior").hi == 60000


def test_online_lookup_is_cached_and_stops_when_blocked(tmp_path):
    cfg = cfg_(tmp_path, delay_seconds=0)
    db = DB(cfg["db_path"])
    est = Estimator(cfg, db)
    calls = []

    class R:
        status_code, text = 200, SERP

    est.http.get = lambda *a, **k: (calls.append(1), R())[1]
    e1 = est.estimate("Acme Corp", "medior")
    assert (e1.lo, e1.hi, e1.source) == (67000, 83500, "online")
    est.estimate("Acme Corp", "medior")
    assert len(calls) == 1  # second call came from cache

    R.status_code, R.text = 202, ""  # bot check
    assert est.estimate("Other Co", "medior") is None and est.blocked
    est.estimate("Third Co", "medior")
    assert len(calls) == 2  # no further requests once blocked


def test_evaluate_with_estimates():
    cfg = load_config("config.example.yaml")
    ok = evaluate(job("Adyen"), cfg, estimate=PayEstimate(105000, 125000, "benchmark"))
    low = evaluate(job("Adyen"), cfg, estimate=PayEstimate(55000, 70000, "online"))
    assumed = evaluate(job("Adyen"), cfg)
    unknown = evaluate(job("Nobody BV"), cfg)
    assert (ok.pay_confidence, low.pay_confidence, assumed.pay_confidence, unknown.pay_confidence) == \
           ("estimated", "low", "likely", "unknown")
    assert ok.score > assumed.score > low.score  # data beats a guess; low pay is pushed down, not deleted
    stated = evaluate(job("Nobody BV", description="Salary €95.000 - €110.000"), cfg,
                      estimate=PayEstimate(40000, 50000, "online"))
    assert stated.pay_confidence == "stated"  # the posting itself always wins


def test_junior_at_big_company_skips_pay_minimum():
    cfg = load_config("config.example.yaml")
    low = PayEstimate(66000, 90000, "benchmark")
    # junior @ tier-1 company with below-minimum reported pay: kept, flagged "growth", not "low"
    jr = evaluate(job("Booking.com", title="Junior Software Engineer"), cfg, estimate=low)
    assert jr.ok and jr.pay_confidence == "growth" and "big company" in jr.reasons[-2] + jr.reasons[0]
    # same pay but medior, or junior at an unknown company: still penalised / unchanged
    assert evaluate(job("Booking.com", title="Software Engineer II"), cfg, estimate=low).pay_confidence == "low"
    assert evaluate(job("Nobody BV", title="Junior Software Engineer"), cfg, estimate=low).pay_confidence == "low"
    # a *stated* low salary is rejected normally, but kept for junior at a big company
    desc = "Salary €50.000 - €60.000 per year"
    assert not evaluate(job("Nobody BV", title="Junior Software Engineer", description=desc), cfg).ok
    assert not evaluate(job("Booking.com", title="Software Engineer II", description=desc), cfg).ok
    stated = evaluate(job("Booking.com", title="Junior Software Engineer", description=desc), cfg)
    assert stated.ok and stated.pay_confidence == "growth"
    # growth ranks below a genuinely well-paid match, above a low-pay one
    good = evaluate(job("Booking.com", title="Junior Software Engineer"), cfg, estimate=PayEstimate(95000, 120000, "benchmark"))
    assert good.score > jr.score
    # rule can be turned off
    cfg["search"]["junior_pay_waiver_tiers"] = []
    assert evaluate(job("Booking.com", title="Junior Software Engineer"), cfg, estimate=low).pay_confidence == "low"
