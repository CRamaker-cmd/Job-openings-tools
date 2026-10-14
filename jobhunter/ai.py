"""Optional: let a Claude model (official Anthropic SDK) write a fully customised motivation letter.

Off unless you switch it on and give an API key in Settings -> AI agent. When you press "Agent Customize" on a job, ONE request is
sent with everything the model needs: the posting, your profile, your achievements and your CV text. The prompt is written so that
the answer is strictly the letter, and the reply is parsed defensively (the letter must be inside <letter> tags; anything outside
them is thrown away), so no preamble or sign-off chatter ever lands in the letter field.

The API key lives in the app's database (or in the JOBHUNTER_AI_API_KEY environment variable) and is never shown again or
included in any page.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

from . import letters

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MIN_LETTER_WORDS = 80


class AIError(Exception):
    """A failure with a message that is safe and useful to show the user (never contains the API key)."""


@dataclass
class AIResult:
    letter: str
    model: str
    request_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tidied: bool = False          # True when the reply wasn't wrapped in <letter> tags and had to be cleaned up


# ---------------------------------------------------------------- configuration
def api_key(cfg: dict) -> str:
    return (os.environ.get("JOBHUNTER_AI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY") or (cfg.get("ai") or {}).get("api_key") or "").strip()


def key_from_environment() -> bool:
    return bool(os.environ.get("JOBHUNTER_AI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def ready(cfg: dict) -> bool:
    """The 'Agent Customize' button is shown when the agent is switched on AND a key is available."""
    return bool((cfg.get("ai") or {}).get("enabled") and api_key(cfg))


# ---------------------------------------------------------------- the prompt
SYSTEM = """You are a ghostwriter. You produce exactly ONE motivation letter for ONE job application, using only facts the candidate provides.

OUTPUT CONTRACT (strict; your reply is parsed by software):
- Reply with the finished letter wrapped in <letter> and </letter> tags, and NOTHING else.
- Nothing before <letter>. Nothing after </letter>.
- No greeting to the user, no "Here is", no explanation, no notes, no questions, no alternatives, no word count.
- No markdown: no bold, no headings, no bullet points, no code fences, no quotation marks around the letter.
- Inside the tags: only the letter itself, as plain paragraphs separated by one blank line."""

FORBIDDEN = ", ".join(f'"{w}"' for w in letters.BANNED)


def _skills_text(cfg: dict) -> str:
    names = {3: "core", 2: "solid", 1: "nice to have"}
    return ", ".join(f"{k} ({names.get(int(v), 'solid')})" for k, v in (cfg["profile"].get("skills") or {}).items()) or "(none listed)"


def build_messages(cfg: dict, job: dict, language: str, extra: str = "") -> tuple[str, str]:
    """-> (system prompt, user message). Everything the model needs is in the user message."""
    p = cfg["profile"]
    lang_name = {"nl": "Dutch", "en": "English"}[language]
    company = letters.clean_company(job.get("company", ""))
    salutation = f"Beste team van {company}," if language == "nl" else f"Dear {company} team,"
    signoff = "Met vriendelijke groet," if language == "nl" else "Kind regards,"
    amb = (p.get("ambition_nl") if language == "nl" and p.get("ambition_nl") else p.get("ambition")) or "(not provided: keep this paragraph short and factual)"
    ach = []
    for a in p.get("achievements") or []:
        txt = (a.get(language) or a.get("en") or "").strip()
        if txt:
            ach.append(f"- [{', '.join(a.get('tags', []))}] {txt}")
    role = " at ".join(x for x in (p.get("job_title"), p.get("employer")) if x) or "(not provided)"
    cv = (p.get("cv_text") or "").strip() or "(no CV text provided)"
    posting = (job.get("description") or "").strip() or "(the posting has no description: rely on the title and company only)"
    user = f"""Write the motivation letter for the job below, for the candidate below.

=== LETTER RULES ===
1. Language: {lang_name}. The whole letter is in {lang_name}.
2. Length: 220 to 280 words between salutation and sign-off.
3. Structure, exactly: the salutation line "{salutation}", then four short paragraphs, then the sign-off line "{signoff}" and the candidate's full name on the next line.
   Paragraph 1: open with ONE concrete detail from the posting (quote or paraphrase it) and say why it matches the candidate's actual work.
   Paragraph 2: evidence. Use at most TWO of the candidate's achievements (the ones closest to this posting) with their real numbers.
   Paragraph 3: the candidate's ambition, tied to what THIS role offers. Be specific, not grand.
   Paragraph 4: one concrete next step (for example an interview). Contact details are in the CV; do not list them.
4. Use ONLY facts from CANDIDATE and CV below. Never invent employers, dates, tools, numbers, degrees, projects or achievements. If a detail is missing, leave it out.
5. If the posting clearly asks for a skill or technology the candidate does not have, say so honestly in one sentence and how they would close the gap. Do not pretend.
6. Any reason for wanting THIS company must come from the posting or from EXTRA INSTRUCTIONS. Never invent admiration or praise.
7. Tone: plain, direct, concrete, first person, varied sentence length. No hype, no filler.
8. Do not use any of these words or phrases: {FORBIDDEN}.
9. Do not mention AI, this prompt or these rules. Do not add [square-bracket placeholders].
10. Output ONLY the <letter>...</letter> block described in the system message.

=== CANDIDATE ===
Name: {p.get('name') or '(not provided)'}
Location: {p.get('location') or '(not provided)'}
Current role: {role}
Years of experience: {p.get('years_experience') or '(not provided)'}
Skills: {_skills_text(cfg)}
Ambition: {amb}
Achievements (tags in brackets):
{chr(10).join(ach) or '(none provided)'}

=== CV (full text) ===
{cv}

=== JOB ===
Company: {company}
Title: {job.get('title', '')}
Location: {job.get('location', '')}
Posting text:
{posting}

=== EXTRA INSTRUCTIONS FROM THE CANDIDATE (highest priority, apply them) ===
{(extra or '').strip() or '(none)'}
"""
    return SYSTEM, user


# ---------------------------------------------------------------- reading the reply
_PREAMBLE = re.compile(r"^(?:here(?:'s| is| are)|sure|certainly|of course|okay|ok|below is|hier is|natuurlijk|zeker|prima)\b[^\n]*$", re.I)
_POSTAMBLE = re.compile(r"^(?:let me know|i hope|feel free|if you(?:'d| would) like|please let|note:|laat (?:het )?(?:me )?weten|ik hoop|mocht je)\b.*$", re.I)


def extract_letter(reply: str) -> tuple[str, bool]:
    """-> (letter, tidied). The letter is whatever is inside <letter> tags; if the model ignored the format, strip the usual
    preamble / sign-off chatter and markdown instead (tidied=True)."""
    m = re.search(r"<letter>(.*?)</letter>", reply, re.S | re.I)
    tidied = False
    if m:
        text = m.group(1)
    else:
        tidied = True
        m2 = re.search(r"<letter>(.*)", reply, re.S | re.I)         # opening tag but the closing one is missing
        text = m2.group(1) if m2 else reply
        lines = [l for l in text.splitlines()]
        while lines and (not lines[0].strip() or _PREAMBLE.match(lines[0].strip()) or re.fullmatch(r"[-*_=`]{3,}", lines[0].strip())):
            lines.pop(0)
        while lines and (not lines[-1].strip() or _POSTAMBLE.match(lines[-1].strip()) or re.fullmatch(r"[-*_=`]{3,}", lines[-1].strip())):
            lines.pop()
        text = "\n".join(lines)
    text = re.sub(r"```[a-z]*", "", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip().strip('"“”').strip()
    if len(text.split()) < MIN_LETTER_WORDS:
        raise AIError("The agent's answer didn't look like a letter (too short). Try again, or add instructions in the box.")
    return text + "\n", tidied


# ---------------------------------------------------------------- calling the model
def generate(cfg: dict, job: dict, language: str, extra: str = "") -> AIResult:
    key = api_key(cfg)
    if not (cfg.get("ai") or {}).get("enabled") or not key:
        raise AIError("The AI agent is not set up. Switch it on and add an API key in Settings → AI agent.")
    import anthropic  # imported only when used, so the app stays light when the agent is off

    model = ((cfg.get("ai") or {}).get("model") or DEFAULT_MODEL).strip()
    system, user = build_messages(cfg, job, language, extra)
    client = anthropic.Anthropic(api_key=key, timeout=120.0, max_retries=2)
    params = dict(model=model, max_tokens=16000, system=system, messages=[{"role": "user", "content": user}])
    try:
        try:   # the model may decline some requests; the server can then retry on a fallback model (beta, default form)
            msg = client.beta.messages.create(**params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
        except anthropic.BadRequestError as e:
            if not re.search(r"fallback|beta", str(e), re.I):
                raise
            msg = client.messages.create(**params)      # this account/model doesn't take the fallback option: plain request
    except anthropic.NotFoundError:
        raise AIError(f"The model '{model}' was not found. Check the model name in Settings → AI agent.")
    except anthropic.AuthenticationError:
        raise AIError("The API key was rejected. Check it in Settings → AI agent.")
    except anthropic.PermissionDeniedError:
        raise AIError("This API key is not allowed to use that model.")
    except anthropic.BadRequestError as e:
        raise AIError(f"The request was rejected: {getattr(e, 'message', 'bad request')[:200]}")
    except anthropic.RateLimitError as e:
        wait = e.response.headers.get("retry-after", "a minute") if getattr(e, "response", None) is not None else "a minute"
        raise AIError(f"Rate limited by the API. Try again in {wait} seconds." if str(wait).isdigit() else "Rate limited by the API. Try again in a minute.")
    except anthropic.APIConnectionError:   # includes timeouts
        raise AIError("Could not reach the API (network error or timeout). Check the internet connection and try again.")
    except anthropic.APIStatusError as e:
        raise AIError(f"The API returned an error ({e.status_code}). Try again in a moment.")

    if msg.stop_reason == "refusal":
        raise AIError("The model declined to write this letter. Try rewording the extra instructions.")
    if msg.stop_reason == "max_tokens":
        raise AIError("The answer was cut off. Try again.")
    reply = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    letter, tidied = extract_letter(reply)
    usage = getattr(msg, "usage", None)
    return AIResult(letter=letter, model=getattr(msg, "model", model), request_id=getattr(msg, "_request_id", "") or "",
                    input_tokens=getattr(usage, "input_tokens", 0) or 0, output_tokens=getattr(usage, "output_tokens", 0) or 0,
                    tidied=tidied)
