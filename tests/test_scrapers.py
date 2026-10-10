import html

from jobhunter.config import load_config
from jobhunter.scrapers.ats import Ashby, Greenhouse, Jibe, Lever, SmartRecruiters, Workday
from jobhunter.scrapers.custom import Amazon, Uber
from jobhunter.scrapers.linkedin import LinkedIn

cfg = load_config("config.example.yaml")


def test_greenhouse():
    s = Greenhouse(cfg, {"name": "Adyen", "board": "adyen"})
    j = s.parse({"id": 1, "title": "Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/adyen/jobs/1",
                 "location": {"name": "Amsterdam"}, "updated_at": "2026-10-01T10:00:00-04:00",
                 "content": html.escape("<p>You know <b>C#</b>.</p><ul><li>3+ years of experience</li></ul>")})
    assert j.location == "Amsterdam" and "C#" in j.description and "<" not in j.description
    assert j.posted_at.year == 2026


def test_greenhouse_is_two_step_and_light():
    s = Greenhouse(cfg, {"name": "Adyen", "board": "adyen"})
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw.get("params")))
        if url.endswith("/jobs"):  # the list: tiny, no descriptions
            return {"jobs": [{"id": 7, "title": "Backend Engineer", "absolute_url": "u", "location": {"name": "Amsterdam"}}]}
        return {"content": html.escape("<p>Python</p>"),
                "pay_input_ranges": [{"currency_type": "EUR", "min_cents": 9000000, "max_cents": 11000000}]}

    s.get_json = fake_get
    [job] = list(s.fetch())
    assert job.description == "" and calls == [("https://boards-api.greenhouse.io/v1/boards/adyen/jobs", None)]  # no content=true
    s.enrich(job)
    assert job.description == "Python" and (job.salary_min, job.salary_max) == (90000, 110000)


def test_lever_with_salary():
    s = Lever(cfg, {"name": "Palantir", "site": "palantir"})
    j = s.parse({"id": "abc", "text": "Software Engineer", "hostedUrl": "https://jobs.lever.co/palantir/abc",
                 "categories": {"location": "Amsterdam", "allLocations": ["Amsterdam", "London"]},
                 "descriptionPlain": "Build things", "createdAt": 1790000000000,
                 "salaryRange": {"min": 90000, "max": 120000, "currency": "EUR", "interval": "per-year-salary"}})
    assert j.location == "Amsterdam / London" and (j.salary_min, j.salary_max) == (90000, 120000)


def test_ashby():
    s = Ashby(cfg, {"name": "X", "board": "x"})
    j = s.parse({"id": "1", "title": "Engineer", "jobUrl": "u", "location": "Amsterdam", "descriptionPlain": "d",
                 "publishedAt": "2026-10-01T00:00:00.000+00:00",
                 "compensation": {"compensationTiers": [{"components": [
                     {"compensationType": "Salary", "currencyCode": "EUR", "interval": "1 YEAR",
                      "minValue": 80000, "maxValue": 100000}]}]}})
    assert j.salary_max == 100000


def test_smartrecruiters():
    s = SmartRecruiters(cfg, {"name": "Bosch", "company_id": "BoschGroup"})
    j = s.parse({"id": "99", "name": "Developer", "location": {"city": "Eindhoven", "country": "nl"},
                 "releasedDate": "2026-10-02T08:00:00.000Z", "ref": "https://api/x"})
    assert j.location == "Eindhoven, NL" and j.url.endswith("/99")


def test_workday():
    s = Workday(cfg, {"name": "Adobe", "tenant": "adobe", "wd": "wd5", "site": "external_experienced"})
    j = s.parse({"title": "Software Developer", "externalPath": "/job/Amsterdam/Dev_R1", "locationsText": "2 Locations"})
    assert j.url == "https://adobe.wd5.myworkdayjobs.com/external_experienced/job/Amsterdam/Dev_R1"


def test_jibe():
    s = Jibe(cfg, {"name": "Booking.com", "host": "jobs.booking.com"})
    j = s.parse({"slug": "123-dev", "req_id": "123", "title": "Software Engineer", "city": "Amsterdam",
                 "country": "Netherlands", "description": "<p>Hi</p>", "posted_date": "2026-09-30T00:00:00+00:00"})
    assert j.location == "Amsterdam, Netherlands" and j.url.endswith("/jobs/123-dev")


def test_amazon():
    j = Amazon(cfg, {"name": "Amazon"}).parse({
        "id_icims": "3001", "title": "Software Development Engineer II", "job_path": "/en/jobs/3001/sde",
        "normalized_location": "Amsterdam, NH, NLD", "description": "<b>Build</b>",
        "basic_qualifications": "3+ years of professional software development experience",
        "posted_date": "October 3, 2026"})
    assert j.url == "https://www.amazon.jobs/en/jobs/3001/sde" and j.posted_at.month == 10


def test_uber():
    j = Uber(cfg, {"name": "Uber"}).parse({"id": 55, "title": "Software Engineer", "description": "d",
                                           "location": {"city": "Amsterdam", "country": "NLD"}})
    assert j.url.endswith("/55/") and j.location == "Amsterdam, NLD"


LINKEDIN_HTML = """
<li><div class="base-card" data-entity-urn="urn:li:jobPosting:4012345678">
<a class="base-card__full-link" href="https://nl.linkedin.com/jobs/view/software-engineer-at-adyen-4012345678?trk=x"></a>
<h3 class="base-search-card__title"> Software Engineer </h3>
<h4 class="base-search-card__subtitle"><a>Adyen</a></h4>
<span class="job-search-card__location">Amsterdam, North Holland, Netherlands</span>
<time datetime="2026-10-07">2 days ago</time></div></li>
"""


def test_linkedin_cards():
    [j] = LinkedIn.parse_cards(LINKEDIN_HTML)
    assert (j.company, j.title, j.external_id) == ("Adyen", "Software Engineer", "4012345678")
    assert "?" not in j.url and j.posted_at.day == 7
