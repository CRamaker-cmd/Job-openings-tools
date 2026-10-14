"""Motivation-letter drafts that are specific to the job, built from YOUR facts, not boilerplate.

How a letter is put together (no AI model, no cost, works offline):
  1. read the posting: its language, one concrete responsibility line (quoted as written), the skills it names that you have,
     the domain (payments, logistics, ...), and a skill it asks for that you do NOT have yet (stated honestly);
  2. pick the 2 achievements from your profile that overlap most with that posting and use them in your own words;
  3. add your ambition, tied to what the role offers;
  4. leave ONE bracketed sentence for you: why this company in particular. Nothing generic can replace that sentence.

Wording avoids the stock phrases that mark a letter as generic ("passionate", "fast-paced", "I am writing to apply", ...);
tests check that. No tool can promise to pass any recruiter's or ATS's AI screening: the strongest signals are real specifics
and your own words, which is why the letter is built from your facts and asks you to add and tweak.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------- small helpers
_LEGAL = re.compile(r"[,\s]+(?:b\.?v\.?|n\.?v\.?|gmbh|ag|inc\.?|ltd\.?|llc|s\.?a\.?|se|plc|oy|ab|a/s|holding)\s*$", re.I)


def clean_company(name: str) -> str:
    out = name.strip()
    for _ in range(2):
        out = _LEGAL.sub("", out).strip(" ,")
    return out or name


def _word(term: str) -> re.Pattern:
    return re.compile(r"(?<![\w])" + re.escape(term) + r"(?![\w+#])", re.I)


_NL_WORDS = set("en de het een voor met je wij we bij van op te zijn ook naar jouw ons onze die dat niet als om aan".split())
_EN_WORDS = set("the and for with you we our your are will to of in on is as be that this have not".split())


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zà-ÿ']+", (text or "").lower())
    if len(words) < 25:
        return "en"
    nl = sum(w in _NL_WORDS for w in words)
    en = sum(w in _EN_WORDS for w in words)
    return "nl" if nl > en * 1.15 else "en"


def _sentence(text: str) -> str:
    t = text.strip()
    return t if t[-1:] in ".!?" else t + "."


def _human_list(items: list[str], lang: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    last = "en" if lang == "nl" else "and"
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


# ---------------------------------------------------------------- reading the posting
DOMAINS = [  # (pattern, English phrase, Dutch phrase)
    (r"payment|checkout|acquir|\bpsp\b|fintech|banking|betaling", "payments", "betalingen"),
    (r"travel|booking|hotel|flight|accommodation|reizen|reis", "travel", "reizen"),
    (r"logistic|supply chain|warehouse|fulfil|logistiek|distributie", "logistics", "logistiek"),
    (r"e-?commerce|marketplace|retail|webshop", "e-commerce", "e-commerce"),
    (r"data platform|data pipeline|analytics|big data|databricks|spark|dataplatform", "data platforms", "dataplatforms"),
    (r"kubernetes|infrastructure|platform engineering|cloud native|cloudinfra", "cloud infrastructure", "cloudinfrastructuur"),
    (r"security|identity|authenticat|fraud|beveilig", "security", "beveiliging"),
    (r"health|medical|clinical|zorg", "healthcare", "zorg"),
    (r"mobility|ride|delivery|transport|mobiliteit", "mobility", "mobiliteit"),
    (r"machine learning|\bml\b|\bllm\b|\bai\b", "machine learning", "machine learning"),
    (r"observab|monitoring|reliability|\bsre\b|incident", "reliability", "betrouwbaarheid"),
    (r"search|recommend|ranking", "search and ranking", "zoeken en ranking"),
    (r"developer (?:tool|experience)|\bsdk\b|open source|devex", "developer tooling", "developer tooling"),
    (r"master data|product data|supply|gs1|erp|crm", "business data", "bedrijfsdata"),
]

TECH_DOMAINS = {"data platforms", "cloud infrastructure", "security", "machine learning", "reliability", "search and ranking",
                "developer tooling"}

# technologies a posting may ask for; if you don't list them it is stated as something to learn
TECH = ["kubernetes", "docker", "aws", "gcp", "azure", "terraform", "kafka", "spark", "golang", "rust", "kotlin", "java", "scala",
        "python", "typescript", "javascript", "react", "angular", "vue", "node.js", "graphql", "postgresql", "mongodb", "redis",
        "elasticsearch", "airflow", "microservices", "c++", "swift", "ruby", "php", "bicep", "cosmos db", "sql", "c#", ".net"]
ADJACENT = {"kubernetes": ["docker"], "aws": ["azure"], "gcp": ["azure"], "terraform": ["bicep"], "kafka": ["nservicebus"],
            "kotlin": ["java", "c#"], "java": ["c#"], "scala": ["c#", "java"], "golang": ["c#"], "react": ["vue", "angular"],
            "typescript": ["javascript"], "postgresql": ["sql"], "mongodb": ["cosmos db"], "spark": ["databricks"],
            "angular": ["vue"], "vue": ["angular"], "node.js": ["javascript"], "python": ["c#"]}

_VERBS_EN = r"(?:design|build|develop|own|maintain|scale|improve|implement|ship|operate|create|deliver|work on|contribute to|architect|shape|run|automate|migrate|integrate|optimi[sz]e|write)"
_VERBS_NL = r"(?:ontwerpen|bouwen|ontwikkelen|beheren|verbeteren|implementeren|opleveren|schalen|automatiseren|migreren|integreren|optimaliseren|schrijven|werken aan|meewerken aan)"
_LEAD_EN = re.compile(r"^(?:you(?:'ll| will)(?: be)?(?: responsible for)?|as a [\w\s-]+ you will|in this role,? you will|your (?:role|job) is to)\s+", re.I)
_LEAD_NL = re.compile(r"^(?:je gaat je bezighouden met|je gaat|jij gaat|je zult|je zal|je werkt aan|je zorgt voor|je bent verantwoordelijk voor|in deze rol ga je)\s+", re.I)
_STEMS_NL = re.compile(r"\b(?:ontwikkel|bouw|ontwerp|beheer|verbeter|implementeer|lever|schaal|automatiseer|migreer|integreer|optimaliseer|schrijf)\w*", re.I)
_REQUIREMENT = re.compile(r"years? of|jaar ervaring|\bexperience\b(?! with building)|degree|diploma|must|required|requirements|salary|salaris|"
                          r"benefits|we offer|wij bieden|ervaring met|opleiding|bachelor|master", re.I)


def _lines(description: str) -> list[str]:
    out = []
    for raw in re.split(r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z])", description or ""):
        line = re.sub(r"^[\s•\-–*·▪●]+", "", raw).strip()
        if line:
            out.append(line)
    return out


def extract_fragment(description: str, lang: str, interest_terms: list[str]) -> str:
    """One concrete responsibility from the posting, as an infinitive phrase ('design and build payment APIs').
    Requirements/benefits lines are skipped. Quoted as written, so it proves the posting was read."""
    verbs, lead = (_VERBS_NL, _LEAD_NL) if lang == "nl" else (_VERBS_EN, _LEAD_EN)
    best: tuple[int, str] | None = None
    for line in _lines(description):
        stripped = lead.sub("", line).strip()
        explicit = stripped != line.strip()
        if lang == "nl":   # the Dutch verb sits at the end, so accept an explicit "je gaat ..." line or any line with a work verb
            if not (explicit or _STEMS_NL.search(stripped)):
                continue
        elif not re.match(rf"{verbs}\b", stripped, re.I):
            continue
        words = stripped.split()
        if not 4 <= len(words) <= 26 or _REQUIREMENT.search(stripped):
            continue
        text = " ".join(words[:20]) if len(words) > 20 else stripped
        text = re.sub(r"[.;:,\s]+$", "", text)
        score = sum(1 for t in interest_terms if _word(t).search(text)) + (1 if explicit else 0)
        if best is None or score > best[0]:
            best = (score, text[:1].lower() + text[1:])
    return best[1] if best else ""


def analyse(job: dict, cfg: dict, lang: str) -> dict:
    """What the letter can say about THIS posting."""
    desc = job.get("description") or ""
    text = f"{job.get('title', '')}\n{desc}"
    skills = cfg["profile"].get("skills") or {}
    mine = {k.lower(): (k, w) for k, w in skills.items()}
    found: list[tuple[int, int, str]] = []
    for low, (name, weight) in mine.items():
        n = len(_word(low).findall(text))
        if n:
            found.append((int(weight), n, name))
    found.sort(reverse=True)
    shared = [n for w, _, n in found if w >= 2][:3]          # skills I rated solid/core: safe to say "I use these"

    domain, best_hits = None, 0.0
    for pat, en, nl in DOMAINS:
        hits = len(re.findall(pat, text, re.I)) * (1.0 if en in TECH_DOMAINS else 2.5)   # an industry says more than a technique
        if hits > best_hits:
            domain, best_hits = (en, nl), hits
    domain_txt = (domain[1] if lang == "nl" else domain[0]) if domain else ""

    fragment = extract_fragment(desc, lang, [n.lower() for _, _, n in found] + ([domain[0]] if domain else []))

    gap, gap_n = "", 0
    for term in TECH:
        if term in mine:
            continue
        n = len(_word(term).findall(text))
        if n > gap_n and (n >= 2 or _word(term).search(job.get("title", ""))):
            gap, gap_n = term, n
    adjacent = next((mine[a][0] for a in ADJACENT.get(gap, []) if a in mine), "")
    return {"shared": shared, "domain": domain_txt, "fragment": fragment, "gap": gap, "adjacent": adjacent,
            "gap_name": {"golang": "Go", "node.js": "Node.js", "gcp": "GCP", "aws": "AWS", "sql": "SQL"}.get(gap, gap.capitalize() if gap.islower() and len(gap) > 4 else gap)}


def pick_achievements(cfg: dict, job: dict, info: dict, n: int = 2) -> list[dict]:
    text = f"{job.get('title', '')}\n{job.get('description') or ''}".lower()
    items = cfg["profile"].get("achievements") or []
    scored = []
    for i, a in enumerate(items):
        score = 0
        for tag in a.get("tags", []):
            t = tag.lower()
            if _word(t).search(text):
                score += 3
            if tag in info["shared"]:
                score += 1
        scored.append((score, -i, a))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [a for _, _, a in scored[:n]]


# ---------------------------------------------------------------- wording
EN = {
    "open_fragment": [
        'One line in the {title} posting at {company} stood out: "{fragment}". As {role}, with {years} years of experience behind me, that is the kind of work I want more of.',
        'The {title} role at {company} asks for someone to {fragment}. I do closely related work as {role}, and I want to take it further.',
        'I am applying for the {title} role at {company}. The posting\'s description of the work, "{fragment}", matches what I do now as {role} and what I want to go deeper into.',
        'The {title} role at {company} describes the work as "{fragment}". That is close to my day-to-day as {role}, and it is the part I want to do more of.',
    ],
    "open_skills": [
        'I am applying for the {title} role at {company}. Its stack ({skills}) is the one I work in every day as {role}{domain_clause}.',
        'The {title} role at {company} lists {skills}. That is my daily toolset as {role}{domain_clause}.',
        '{company} is hiring a {title} to work with {skills}. I use exactly these as {role}{domain_clause}.',
        '{company} lists {skills} for the {title} role. These are the tools I reach for most as {role}{domain_clause}.',
    ],
    "domain_clause": ", and the posting's focus on {domain} is where I want to go deeper",
    "both": ["That work involved {skills}, which your posting names.", "That work rests on {skills}, the same tools your posting lists.",
             "It leaned heavily on {skills}, which your posting lists too.", "Day to day that meant {skills}, the same tools your posting asks for."],
    "second": ["Separately, ", "On another project, ", "Before that, "],
    "ambition_lead": ["Where I want to grow: ", "What I am working towards: ", "Looking ahead: "],
    "fit": ["The role combines {skills} with work in {domain}, which is the direction I want my next step to take.",
            "It pairs {skills} with work in {domain}, the direction I want my next step to take.",
            "I see this role as a step towards that: {skills} together with work in {domain}."],
    "fit_nodomain": ["The role combines {skills} with the kind of ownership I am looking for in my next step.",
                     "It combines {skills} with the kind of ownership I am looking for next."],
    "gap_adjacent": "I have not used {gap} in production yet; with my background in {adjacent} I expect to be productive with it quickly.",
    "gap_plain": "I have not used {gap} in production yet and would be glad to learn it on the job.",
    "placeholder": "[Your own sentence: what specifically draws you to {company}? A product, project or team you read about.]",
    "close": ["I would be happy to walk you through {topic} in more detail. You can reach me at {contact}; my CV is attached.",
              "In an interview I can go into {topic} in more detail. My CV is attached and I can be reached at {contact}.",
              "My CV is attached. I would welcome the chance to talk about {topic}; you can reach me at {contact}.",
              "I would value a conversation about {topic} and about what the team works on next. My CV is attached; I am reachable at {contact}."],
    "topic": "my work on {tag}",
    "signoff": "Kind regards,",
    "role_known": "{a} {title} at {employer}",
    "role_unknown": "a software engineer",
}
NL = {
    "open_fragment": [
        'In de vacature voor {title} bij {company} viel één regel me op: "{fragment}". Als {role}, met {years} jaar ervaring, is dat het soort werk waar ik meer van wil doen.',
        'Voor de rol van {title} bij {company} staat in de vacature: "{fragment}". Dat sluit aan bij mijn werk als {role}, en daar wil ik verder in groeien.',
        'Ik reageer op de vacature voor {title} bij {company}. Jullie omschrijving van het werk, "{fragment}", past bij wat ik nu doe als {role} en waar ik dieper in wil.',
        'De rol van {title} bij {company} omschrijft het werk als "{fragment}". Dat ligt dicht bij mijn dagelijks werk als {role}, en dat wil ik graag vaker doen.',
    ],
    "open_skills": [
        'Ik reageer op de vacature voor {title} bij {company}. De stack ({skills}) is die waarin ik dagelijks werk als {role}{domain_clause}.',
        'De rol van {title} bij {company} noemt {skills}. Dat is mijn dagelijkse gereedschap als {role}{domain_clause}.',
        '{company} zoekt een {title} die werkt met {skills}. Precies die gebruik ik als {role}{domain_clause}.',
        'Voor de rol van {title} noemt {company} {skills}. Daar werk ik het meest mee als {role}{domain_clause}.',
    ],
    "domain_clause": ", en de focus van de vacature op {domain} is waar ik dieper in wil",
    "both": ["Dat werk draaide om {skills}, zoals in jullie vacature staat.", "Dat werk rust op {skills}, dezelfde tools als in de vacature.",
             "Het draaide sterk op {skills}, die de vacature ook noemt.", "Dagelijks betekende dat {skills}, dezelfde tools waar de vacature om vraagt."],
    "second": ["", "", ""],
    "ambition_lead": ["Waar ik naartoe wil groeien: ", "Waar ik naartoe werk: ", "Vooruitkijkend: "],
    "fit": ["De rol combineert {skills} met werk in {domain}, precies de richting die ik voor mijn volgende stap wil.",
            "Het is een combinatie van {skills} en werk in {domain}, de richting die ik voor mijn volgende stap zoek.",
            "Ik zie deze rol als een stap daarnaartoe: {skills} samen met werk in {domain}."],
    "fit_nodomain": ["De rol combineert {skills} met de eigen verantwoordelijkheid die ik voor mijn volgende stap zoek.",
                     "Het is een combinatie van {skills} en de verantwoordelijkheid die ik nu zoek."],
    "gap_adjacent": "Met {gap} heb ik nog geen productie-ervaring; door mijn achtergrond in {adjacent} verwacht ik er snel mee uit de voeten te kunnen.",
    "gap_plain": "Met {gap} heb ik nog geen productie-ervaring en dat leer ik graag al werkend.",
    "placeholder": "[Jouw eigen zin: wat trekt je specifiek aan bij {company}? Een product, project of team waar je over las.]",
    "close": ["Ik vertel graag meer over {topic}. Je bereikt me via {contact}; mijn cv zit als bijlage bij deze reactie.",
              "In een gesprek ga ik graag dieper in op {topic}. Mijn cv is bijgevoegd en ik ben bereikbaar via {contact}.",
              "Mijn cv is bijgevoegd. Ik praat graag over {topic}; je bereikt me via {contact}.",
              "Ik praat graag door over {topic} en over waar het team mee bezig is. Mijn cv is bijgevoegd; je bereikt me via {contact}."],
    "topic": "mijn werk aan {tag}",
    "signoff": "Met vriendelijke groet,",
    "role_known": "{title} bij {employer}",
    "role_unknown": "software engineer",
}


@dataclass
class Letter:
    text: str
    language: str
    variant: int
    seed: int = 0
    used: dict = field(default_factory=dict)
    needs_input: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return len(self.text.split())


def _a(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def generate(cfg: dict, job: dict, variant: Optional[int] = None, language: Optional[str] = None) -> Letter:
    p = cfg["profile"]
    lang = language if language in ("en", "nl") else (p.get("letter_language") if p.get("letter_language") in ("en", "nl") else None)
    lang = lang or detect_language(job.get("description") or "")
    T = NL if lang == "nl" else EN
    company = clean_company(job.get("company", ""))
    title = job.get("title", "")
    info = analyse(job, cfg, lang)
    seed = variant if variant is not None else zlib.crc32(f"{company}|{title}".encode())
    # every slot picks its wording independently from the seed, so different jobs (and "another angle") give different combinations
    pick = lambda options, slot="": options[zlib.crc32(f"{seed}|{slot}|{len(options)}".encode()) % len(options)]

    # who I am
    job_title, employer = (p.get("job_title") or "").strip(), (p.get("employer") or "").strip()
    if job_title and employer:
        role = T["role_known"].format(a=_a(job_title), title=job_title, employer=employer)
    elif job_title:
        role = f"{_a(job_title)} {job_title}" if lang == "en" else job_title
    else:
        role = T["role_unknown"]
    years = str(p.get("years_experience") or "") or ("enkele" if lang == "nl" else "several")
    domain_clause = T["domain_clause"].format(domain=info["domain"]) if info["domain"] else ""
    skills_txt = _human_list(info["shared"], lang)

    # 1. opening: quote the posting if we found a responsibility line, else lead with the stack
    if info["fragment"]:
        opening = pick(T["open_fragment"], "open").format(title=title, company=company, fragment=info["fragment"], role=role, years=years)
    elif skills_txt:
        opening = pick(T["open_skills"], "open").format(title=title, company=company, skills=skills_txt, role=role, domain_clause=domain_clause)
    else:
        opening = (f"Ik reageer op de vacature voor {title} bij {company}. Ik werk als {role}." if lang == "nl"
                   else f"I am applying for the {title} role at {company}. I work as {role}.")

    # 2. evidence: two achievements, in the user's own words
    ach = pick_achievements(cfg, job, info, 2)
    texts = [_sentence((a.get(lang) or a.get("en") or "").strip()) for a in ach if (a.get(lang) or a.get("en"))]
    evidence = ""
    if texts:
        evidence = texts[0]
        if len(texts) > 1:
            second = texts[1]
            if lang == "en" and second.startswith("I "):
                second = pick(T["second"], "second") + second          # "Separately, I helped design ..." (the "I" stays a capital)
            evidence += " " + second
        tags = {t.lower() for a in ach for t in a.get("tags", [])}
        tied = [x for x in info["shared"] if x.lower() in tags]        # never claim a skill the achievements don't show
        if tied:
            evidence += " " + pick(T["both"], "both").format(skills=_human_list(tied, lang))
    elif p.get("pitch"):
        evidence = _sentence(p["pitch"])

    # 3. ambition, tied to the role, plus an honest gap, plus the one sentence only the user can write
    amb = (p.get("ambition_nl") if lang == "nl" and p.get("ambition_nl") else p.get("ambition") or "").strip()
    amb_parts = []
    if amb:
        amb_parts.append(_sentence(amb))
    if skills_txt:
        fit = (T["fit"] if info["domain"] else T["fit_nodomain"])
        amb_parts.append(pick(fit, "fit").format(skills=skills_txt, domain=info["domain"]))
    if info["gap"]:
        amb_parts.append((T["gap_adjacent"] if info["adjacent"] else T["gap_plain"]).format(gap=info["gap_name"], adjacent=info["adjacent"]))
    placeholder = T["placeholder"].format(company=company)
    amb_parts.append(placeholder)
    ambition_par = " ".join(amb_parts)

    # 4. close
    contact = " / ".join(x for x in (p.get("email"), p.get("phone")) if x) or ("mijn contactgegevens" if lang == "nl" else "my contact details")
    tag = (ach[0].get("tags") or [""])[0] if ach else ""
    topic = T["topic"].format(tag=tag) if tag else ("mijn werkervaring" if lang == "nl" else "my experience")
    closing = pick(T["close"], "close").format(topic=topic, contact=contact)

    signature = "\n".join(x for x in (T["signoff"], p.get("name"), p.get("linkedin")) if x)
    parts = [opening, evidence, ambition_par, closing]
    text = "\n\n".join(x for x in parts if x) + "\n\n" + signature + "\n"
    used = {"fragment": info["fragment"], "skills": info["shared"], "domain": info["domain"], "gap": info["gap_name"],
            "achievements": [a.get("tags", [""])[0] for a in ach]}
    return Letter(text=text, language=lang, variant=seed % 3, seed=seed, used=used, needs_input=[placeholder])


# ---------------------------------------------------------------- prompt for any AI assistant (free: paste it into a chat)
BANNED = ["passionate", "thrilled", "excited to apply", "fast-paced", "dynamic environment", "team player", "I am writing to apply",
          "perfect fit", "highly motivated", "proven track record", "results-driven", "synergy", "go-getter", "hit the ground running",
          "unique opportunity", "cutting-edge", "world-class", "leverage", "I believe I would be a great"]


def build_prompt(cfg: dict, job: dict, language: Optional[str] = None) -> str:
    p = cfg["profile"]
    lang = language if language in ("en", "nl") else (detect_language(job.get("description") or ""))
    name = {"en": "English", "nl": "Dutch"}[lang]
    info = analyse(job, cfg, lang)
    ach = pick_achievements(cfg, job, info, 3)
    facts = "\n".join(f"- {(a.get(lang) or a.get('en') or '').strip()}" for a in ach) or "- (none provided: ask me)"
    amb = (p.get("ambition_nl") if lang == "nl" and p.get("ambition_nl") else p.get("ambition") or "(not provided: ask me)")
    desc = (job.get("description") or "")[:3500]
    return f"""Write a motivation letter in {name} for the job below. It will be read by a human recruiter and possibly screened by software.

RULES
- 200 to 260 words, 3 to 4 short paragraphs, first person, plain and direct. No bullet points, no headings.
- Be specific to THIS role and company. Quote or paraphrase at least one concrete detail from the job text.
- Use ONLY the facts below. Do not invent employers, numbers, tools or achievements. If something is missing, write it in [square brackets] for me to fill in.
- Include my ambition and say honestly why this role is the right next step for it.
- If the job asks for a skill I don't list, say that plainly and how I'd close the gap, instead of pretending.
- Vary sentence length. Do not start with "I am writing to apply". Do not use these words or phrases: {", ".join(BANNED)}.
- End with one concrete next step. Sign with my name.

ABOUT ME
Name: {p.get('name') or '[name]'}
Current role: {p.get('job_title') or '[role]'} at {p.get('employer') or '[employer]'}; {p.get('years_experience') or '?'} years of experience
Skills: {', '.join((p.get('skills') or {}).keys())}
Ambition: {amb}
Concrete achievements:
{facts}

THE JOB
Company: {clean_company(job.get('company', ''))}
Title: {job.get('title', '')}
Location: {job.get('location', '')}
Posting text:
{desc or '(no description available)'}
"""
