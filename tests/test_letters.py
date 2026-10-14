"""Motivation letters must be specific, honest and free of stock phrases."""
import re

import pytest
from werkzeug.datastructures import MultiDict

from jobhunter import letters, settings
from jobhunter.config import load_config
from jobhunter.web.app import create_app

CFG = load_config("config.example.yaml")
CFG["profile"].update(name="Caz Ramaker", email="caz@example.com", phone="+31 6 12345678", linkedin="linkedin.com/in/caz")

ADYEN = dict(company="Adyen N.V.", title="Backend Engineer", location="Amsterdam", description="""About the role
Adyen processes payments for thousands of businesses worldwide.
You will design and build scalable payment APIs that handle millions of requests per day.
You will work with C#, .NET, Azure and SQL, and operate your services in production.
Requirements
2+ years of experience building backend services
We offer a competitive salary.""")
LOGISTIEK = dict(company="Logistiek Groep B.V.", title="Medior .NET Developer", location="Utrecht", description="""Wie zijn wij
Wij bouwen software voor logistiek en distributie voor onze klanten in de supply chain.
Je gaat nieuwe functionaliteit ontwikkelen in C# en .NET en bouwen aan REST API's op Azure.
Je werkt samen met product owners en je verbetert de prestaties van bestaande systemen.
Wat wij vragen
3 jaar ervaring met C# en SQL, ervaring met Azure is een pre.
Wij bieden een goed salaris en veel ontwikkelmogelijkheden en wij zoeken een collega die met ons mee groeit.""")
BOOKING = dict(company="Booking.com", title="Software Engineer II", location="Amsterdam",
               description="Python and Java. Docker. Kafka. Kafka. Kafka event streaming. Build services for travel booking.")
HEALTH = dict(company="MedTech GmbH", title="Developer", location="Utrecht",
              description="Build clinical software for hospitals.\nYou will develop Vue frontends and maintain C# APIs for patient data.\nRequirements: degree.")
NODESC = dict(company="Mystery BV", title="Software Engineer", location="Amsterdam", description="")
JOBS = [ADYEN, LOGISTIEK, BOOKING, HEALTH, NODESC]

STOCK = letters.BANNED + ["gedreven", "enthousiast", "dynamische", "teamplayer", "uitdagende", "ideale kandidaat", "i am thrilled",
                          "i am excited", "ik ben erg", "perfect match", "great opportunity"]


def shingles(text, n=5):
    w = re.findall(r"\w+", text.lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


@pytest.mark.parametrize("job", JOBS, ids=lambda j: j["company"])
@pytest.mark.parametrize("variant", [0, 1, 2, 7])
def test_no_stock_phrases_no_leftover_placeholders_sane_length(job, variant):
    L = letters.generate(CFG, job, variant=variant)
    low = L.text.lower()
    assert not [p for p in STOCK if p.lower() in low], L.text
    assert not re.search(r"\{[a-z_]+\}|None|\bnan\b", L.text), L.text            # no unfilled template fields
    assert 120 <= L.words <= 330, L.words
    assert L.text.count("[") == 1 and L.text.count("]") == 1                       # exactly one bracketed sentence for the user
    assert L.needs_input and clean(job) in L.text


def clean(job):
    return letters.clean_company(job["company"])


def test_letter_is_specific_to_the_posting():
    L = letters.generate(CFG, ADYEN, variant=0)
    assert "design and build scalable payment APIs that handle millions of requests per day" in L.text   # a real line, quoted
    assert "payments" in L.text and "Adyen" in L.text and "Adyen N.V." not in L.text                      # legal suffix dropped
    assert "Backend Engineer" in L.text
    assert L.used["domain"] == "payments"                                                                 # industry beats technique
    # a concrete, verifiable number from the user's own achievements
    assert re.search(r"tens of thousands|50,000|100k|GTIN", L.text)


def framing(text, cfg=CFG):
    """The wording that is NOT the user's own verbatim facts (achievements, ambition, signature): what the generator adds."""
    p = cfg["profile"]
    own = [a.get(k, "") for a in p["achievements"] for k in ("en", "nl")] + [p["ambition"], p["ambition_nl"], p["name"], p["linkedin"],
                                                                                   p["email"], p["phone"]]
    for o in own:
        if o:
            text = text.replace(o, " ")
    return text


def test_two_different_jobs_give_clearly_different_letters():
    for other in (HEALTH, BOOKING, LOGISTIEK):
        a, b = shingles(framing(letters.generate(CFG, ADYEN).text)), shingles(framing(letters.generate(CFG, other).text))
        assert len(a & b) / max(1, len(a | b)) < 0.35, f"framing for {other['company']} too similar to Adyen's"
    # and the whole letters differ in more than the user's own facts
    assert letters.generate(CFG, ADYEN).text != letters.generate(CFG, HEALTH).text


def test_variants_differ_but_keep_the_facts():
    texts = [letters.generate(CFG, ADYEN, variant=v).text for v in (0, 1, 2)]
    assert len(set(texts)) == 3
    assert len({t.split("\n\n")[0] for t in texts}) == 3                           # different openings


def test_never_claims_a_skill_the_achievements_do_not_show():
    cfg = load_config("config.example.yaml")
    cfg["profile"]["skills"] = {"C#": 3, "Python": 3}                              # Python is a skill, but in NO achievement
    cfg["profile"]["achievements"] = [{"tags": ["API design", "C#"], "en": "I built an API in C# for 50,000 users."}]
    job = dict(company="X", title="Engineer", location="A", description="Build services. You will build APIs in Python and C# for payments. Python and C# daily.")
    for v in range(6):
        t = letters.generate(cfg, job, variant=v).text
        tie = re.search(r"That work (?:involved|rests on)[^.]*\.|It leaned heavily on[^.]*\.", t)
        assert not tie or "Python" not in tie.group(0), t                          # "That work involved Python" would be a lie
        assert "C#" in t


def test_only_core_skills_are_claimed_as_daily_tools():
    cfg = load_config("config.example.yaml")
    cfg["profile"]["skills"] = {"Kubernetes": 1, "Docker": 3}                      # weight 1 = nice to have
    job = dict(company="X", title="Engineer", location="A", description="We use Kubernetes and Docker. You will build services on Kubernetes and Docker.")
    L = letters.generate(cfg, job, variant=0)
    own_words = re.sub(r'"[^"]*"', "", L.text)                                    # the posting's own quoted line may mention anything
    assert L.used["skills"] == ["Docker"] and "Kubernetes" not in own_words


def test_missing_skill_is_stated_honestly_with_the_closest_one():
    L = letters.generate(CFG, BOOKING, variant=0)
    assert L.used["gap"] == "Kafka" and "have not used Kafka in production yet" in L.text
    cfg = load_config("config.example.yaml")
    cfg["profile"]["skills"] = {"Azure": 3, "C#": 3}
    job = dict(company="X", title="Engineer", location="A", description="You will build services on AWS. AWS and AWS experience. C#.")
    t = letters.generate(cfg, job, variant=0).text
    assert "AWS in production yet; with my background in Azure" in t              # adjacent skill named, nothing invented


def test_language_follows_the_posting_and_uses_dutch_material():
    nl = letters.generate(CFG, LOGISTIEK)
    assert nl.language == "nl" and nl.text.count("Met vriendelijke groet") == 1
    assert "Ik leidde de ontwikkeling" in nl.text or "Ik heb de performance" in nl.text   # the Dutch version of the achievements
    assert "I led the development" not in nl.text
    assert "logistiek" in nl.text and "[Jouw eigen zin" in nl.text
    en = letters.generate(CFG, ADYEN)
    assert en.language == "en" and "Kind regards" in en.text
    assert letters.generate(CFG, ADYEN, language="nl").language == "nl"            # can be forced
    assert letters.detect_language(ADYEN["description"]) == "en" and letters.detect_language(LOGISTIEK["description"]) == "nl"


def test_works_without_a_description_or_profile_material():
    L = letters.generate(CFG, NODESC)
    assert "Mystery" in L.text and L.words > 60
    bare = load_config("config.example.yaml")
    bare["profile"].update(achievements=[], ambition="", job_title="", employer="", pitch="")
    t = letters.generate(bare, ADYEN).text
    assert "Adyen" in t and "[" in t and not re.search(r"\{[a-z_]+\}", t)


def test_ai_prompt_carries_the_rules_the_facts_and_the_posting():
    pr = letters.build_prompt(CFG, ADYEN)
    for must in ("Use ONLY the facts below", "payment APIs", "Ambition", "200 to 260 words", "Do not invent", "passionate", "Backend Engineer"):
        assert must in pr
    assert "tens of thousands" in pr                                               # the user's own achievements are included
    assert "Dutch" in letters.build_prompt(CFG, LOGISTIEK)


def test_achievements_setting_roundtrip_and_validation():
    f = next(x for s in settings.SECTIONS for x in s.fields if x.path == "profile.achievements")
    parsed = settings.parse(f, MultiDict({f.path: "API design, REST :: I built an API for 50,000 users. || Ik bouwde een API.\nperformance :: I made it fast."}))
    assert parsed == [{"tags": ["API design", "REST"], "en": "I built an API for 50,000 users.", "nl": "Ik bouwde een API."},
                      {"tags": ["performance"], "en": "I made it fast."}]
    assert settings.to_text(f, parsed).splitlines()[0] == "API design, REST :: I built an API for 50,000 users. || Ik bouwde een API."
    for bad in ("no separator here", ":: sentence without tags", "tag ::"):
        with pytest.raises(ValueError):
            settings.parse(f, MultiDict({f.path: bad}))


def test_job_page_shows_letter_controls(tmp_path, full_form):
    from jobhunter.db import DB
    from jobhunter.filters import evaluate
    from jobhunter.models import RawJob
    cfg = load_config("config.example.yaml")
    cfg["db_path"] = str(tmp_path / "l.db"); cfg["_config_path"] = "config.example.yaml"; cfg["profile"]["name"] = "Caz"
    db = DB(cfg["db_path"])
    raw = RawJob(source="x", origin="x", company="Adyen N.V.", title="Backend Engineer", url="u", location="Amsterdam, Netherlands",
                 external_id="1", description=ADYEN["description"])
    db.upsert(raw, evaluate(raw, cfg), "2026-10-14T00:00:00+00:00")
    c = create_app(cfg).test_client()
    jid = db.list_jobs(pay="all")[0]["id"]
    page = c.get(f"/job/{jid}").data.decode()
    assert "Motivation letter draft" in page and "Another angle" in page and "Copy prompt for an AI assistant" in page
    assert "Replace the [bracketed] sentence" in page and "payment APIs" in page
    nl = c.get(f"/job/{jid}?lang=nl").data.decode()
    assert "Met vriendelijke groet" in nl
    assert c.get(f"/job/{jid}?v=3").data != c.get(f"/job/{jid}?v=4").data           # another angle really changes the text
    form = full_form(cfg, "profile", **{"profile.achievements": "API :: I did a thing for 5 users.", "profile.letter_language": "nl"})
    assert b"Saved" in c.post("/settings/profile", data=form, follow_redirects=True).data
    assert cfg["profile"]["achievements"] == [{"tags": ["API"], "en": "I did a thing for 5 users."}] and cfg["profile"]["letter_language"] == "nl"
