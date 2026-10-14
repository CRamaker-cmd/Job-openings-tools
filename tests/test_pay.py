"""Salary arithmetic: monthly -> yearly (x12, +8% holiday pay), bonuses, formats, currencies, and false positives."""
import pytest

from jobhunter.config import load_config
from jobhunter.pay import monthly_to_yearly, parse_pay, to_number

CFG = load_config("config.example.yaml")


@pytest.mark.parametrize("text,lo,hi", [
    # the user's rule: gross monthly x 12 x 1.08
    ("Salaris: € 5.500 - € 7.000 bruto per maand", 71280, 90720),
    ("Wij bieden tussen 5500 en 7000 euro per maand", 71280, 90720),
    ("Salary: €5,500 - €7,000 per month", 71280, 90720),
    ("€5,500.00/mo - €7,000.00/mo", 71280, 90720),
    ("5,500 - 7,000 EUR per month gross", 71280, 90720),
    ("€ 6.000 p.m. bruto", 77760, 77760),
    ("Salaris € 4.500 - € 6.000 (afhankelijk van ervaring)", 58320, 77760),     # no period: monthly
    # yearly figures are left alone
    ("€75,000.00/yr - €95,000.00/yr", 75000, 95000),
    ("€80k - €100k per year", 80000, 100000),
    ("EUR 90k - 110k", 90000, 110000),
    ("€90 - 110k", 90000, 110000),
    ("Salary range €85,000 - €105,000", 85000, 105000),
    ("Pay range €85.000", 85000, 85000),
    ("bruto jaarsalaris tussen € 70.000 en € 90.000", 70000, 90000),
    # bonus only when one is stated
    ("€ 6.000 bruto per maand excl. 8% vakantiegeld, plus 10% bonus", 85536, 85536),
    ("€5,000 per month and a bonus of €6,000 per year", 64800 + 6000, 64800 + 6000),
    ("€ 5.000 per maand + 13e maand", 69800, 69800),
    # holiday pay already included -> not added again
    ("€ 6.000 per maand incl. vakantiegeld", 72000, 72000),
    ("€ 70.000 per jaar excl. vakantiegeld", 75600, 75600),
    # other currencies are converted to EUR
    ("£60,000 - £75,000 per year", 69000, 86250),
    ("CHF 100k - 120k", 105000, 126000),
])
def test_parse_pay(text, lo, hi):
    p = parse_pay(text, CFG)
    assert p is not None, text
    assert (p.lo, p.hi) == (lo, hi), p.note


@pytest.mark.parametrize("text", [
    "€45 per hour", "a bonus of €5000", "€500 relocation allowance", "sign-on bonus of €10.000",
    "Founded in 2005, 3 years of experience, 40 hours a week", "our revenue is €2 million",
    "referral bonus €1.500", "no money talk here", "budget of €3.000 for learning",
])
def test_not_a_salary(text):
    assert parse_pay(text, CFG) is None, text


def test_settings_change_the_arithmetic():
    cfg = load_config("config.example.yaml")
    cfg["search"]["vacation_allowance_pct"] = 0
    assert parse_pay("€5.000 per maand", cfg).lo == 60000
    cfg["search"]["vacation_allowance_pct"] = 8
    cfg["search"]["add_bonus"] = False
    assert parse_pay("€5.000 per maand + 13e maand, 10% bonus", cfg).lo == 64800     # bonuses ignored when switched off


def test_note_explains_the_arithmetic():
    n = parse_pay("€5,500 - €7,000 per month plus 10% bonus", CFG).note
    assert "month" in n and "holiday pay" in n and "bonus" in n and "year" in n


def test_helpers():
    assert to_number("5.500") == 5500 and to_number("5,500.00") == 5500 and to_number("4.5") == 4.5 and to_number("5.500,50") == 5500.5
    assert monthly_to_yearly(5000, CFG) == pytest.approx(64800)


def test_monthly_salary_now_clears_the_minimum_correctly():
    """The user's case: a LinkedIn posting stating €7.000/month (= €90.7k/yr with holiday pay) must pass a 90k minimum,
    while €6.500/month (= €84.2k) must not, even though 12 x 7000 = 84k would have failed it before."""
    from jobhunter.filters import evaluate
    from jobhunter.models import RawJob
    mk = lambda d: RawJob(source="linkedin", origin="LinkedIn", company="Nobody BV", title="Software Engineer", url="u",
                          location="Amsterdam, Netherlands", description=d)
    assert evaluate(mk("Salaris € 6.000 - € 7.000 per maand"), CFG).ok
    assert not evaluate(mk("Salaris € 5.500 - € 6.500 per maand"), CFG).ok
