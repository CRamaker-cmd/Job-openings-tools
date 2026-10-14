"""Optional: let an AI model write a fully customised motivation letter ("Agent Customize").

Works with any provider you choose in Settings -> AI agent:

* ``anthropic``: Claude through the official Anthropic SDK;
* ``openai``: any endpoint that speaks the common OpenAI-style ``/chat/completions`` API, which covers OpenAI, Gemini, Mistral,
  Groq, OpenRouter, and models you run yourself (Ollama, LM Studio, vLLM, llama.cpp ...). A key is optional for local models.

When you press the button ONE request is sent with everything the model needs: the posting, your profile, achievements and CV text.
The prompt is strict (the reply must be exactly one ``<letter>`` block) and the reply is parsed defensively (only what is inside the
tags is kept), so no preamble or chatter ever reaches the letter box, whichever model answers.

The API key lives in the app's database (or the JOBHUNTER_AI_API_KEY environment variable), is never shown again and never appears
in a page or an error message.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import requests

from . import letters

PROVIDERS = {
    "anthropic": "Claude (Anthropic API)",
    "openai": "OpenAI-compatible endpoint (OpenAI, Gemini, Mistral, OpenRouter, your own model, ...)",
}
DEFAULT_MODEL = {"anthropic": "claude-opus-5-5"}      # other providers have no sensible default: the user names the model
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = {"anthropic": 16000, "openai": 4000}
MIN_LETTER_WORDS = 80


class AIError(Exception):
    """A failure with a message that is safe and useful to show the user (never contains the API key)."""


@dataclass
class Reply:
    """What a provider returned, in one shape."""
    text: str
    model: str
    request_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    stop: str = ""                # "end", "length" (cut off) or "refusal"


@dataclass
class AIResult:
    letter: str
    model: str
    request_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tidied: bool = False          # True when the reply wasn't wrapped in <letter> tags and had to be cleaned up


# ---------------------------------------------------------------- configuration
def _conf(cfg: dict) -> dict:
    return cfg.get("ai") or {}


def provider(cfg: dict) -> str:
    p = _conf(cfg).get("provider")
    return p if p in PROVIDERS else "anthropic"


def api_key(cfg: dict) -> str:
    key = os.environ.get("JOBHUNTER_AI_API_KEY") or _conf(cfg).get("api_key") or ""
    if not key and provider(cfg) == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY", "")         # the Anthropic SDK's own convention
    return key.strip()


def key_from_environment(cfg: dict) -> bool:
    return bool(os.environ.get("JOBHUNTER_AI_API_KEY") or (provider(cfg) == "anthropic" and os.environ.get("ANTHROPIC_API_KEY")))


def model_name(cfg: dict) -> str:
    return (_conf(cfg).get("model") or "").strip() or DEFAULT_MODEL.get(provider(cfg), "")


def host_label(cfg: dict) -> str:
    """Where the request goes, for the 'what is sent' notes in the UI."""
    if provider(cfg) == "anthropic":
        return "Anthropic"
    return urlparse(_conf(cfg).get("base_url") or "").netloc or "your AI endpoint"


def ready(cfg: dict) -> bool:
    """The Agent Customize button is shown when the agent is switched on and can be reached:
    Claude needs a key; an OpenAI-compatible endpoint needs a URL and a model (a key is optional: local models need none)."""
    c = _conf(cfg)
    if not c.get("enabled"):
        return False
    if provider(cfg) == "anthropic":
        return bool(api_key(cfg))
    return bool((c.get("base_url") or "").strip() and model_name(cfg))


# ---------------------------------------------------------------- the prompt
SYSTEM = """You are a ghostwriter. You produce exactly ONE motivation letter for ONE job application, using only facts the candidate provides.

OUTPUT CONTRACT (strict; your reply is parsed by software):
- Reply with the finished letter wrapped in <letter> and </letter> tags, and NOTHING else.
- Nothing before <letter>. Nothing after </letter>.
- No greeting to the user, no "Here is", no explanation, no notes, no questions, no alternatives, no word count.
- No markdown: no bold, no headings, no bullet points, no code fences, no quotation marks around the letter.
- Inside the tags: only the letter itself, as plain paragraphs separated by one blank line."""

FORBIDDEN = ", ".join(f'"{w}"' for w in letters.BANNED)
_LEVELS = {3: "core", 2: "solid", 1: "nice to have"}


def build_messages(cfg: dict, job: dict, language: str, extra: str = "") -> tuple[str, str]:
    """-> (system prompt, user message). Everything the model needs is in the user message."""
    p = cfg["profile"]
    lang_name = {"nl": "Dutch", "en": "English"}[language]
    company = letters.clean_company(job.get("company", ""))
    salutation = f"Beste team van {company}," if language == "nl" else f"Dear {company} team,"
    signoff = "Met vriendelijke groet," if language == "nl" else "Kind regards,"
    ambition = (p.get("ambition_nl") if language == "nl" and p.get("ambition_nl") else p.get("ambition")) \
        or "(not provided: keep this paragraph short and factual)"
    achievements = "\n".join(
        f"- [{', '.join(a.get('tags', []))}] {text}"
        for a in p.get("achievements") or [] if (text := (a.get(language) or a.get("en") or "").strip())) or "(none provided)"
    skills = ", ".join(f"{k} ({_LEVELS.get(int(v), 'solid')})" for k, v in (p.get("skills") or {}).items()) or "(none listed)"
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
Skills: {skills}
Ambition: {ambition}
Achievements (tags in brackets):
{achievements}

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
_RULE = re.compile(r"[-*_=`]{3,}")
_THINK = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S | re.I)      # reasoning models (DeepSeek-R1, Qwen, ...) show their thinking


def _trim(lines: list[str], junk: re.Pattern, from_start: bool) -> list[str]:
    idx = (lambda: 0) if from_start else (lambda: -1)
    while lines and (not lines[idx()].strip() or junk.match(lines[idx()].strip()) or _RULE.fullmatch(lines[idx()].strip())):
        lines.pop(idx())
    return lines


def extract_letter(reply: str) -> tuple[str, bool]:
    """-> (letter, tidied). The letter is whatever is inside <letter> tags; if the model ignored the format, strip the usual
    preamble / sign-off chatter and markdown instead (tidied=True)."""
    reply = _THINK.sub("", reply)
    m = re.search(r"<letter>(.*?)</letter>", reply, re.S | re.I)
    tidied = m is None
    if m:
        text = m.group(1)
    else:
        opened = re.search(r"<letter>(.*)", reply, re.S | re.I)         # opening tag present, closing one missing
        lines = (opened.group(1) if opened else reply).splitlines()
        text = "\n".join(_trim(_trim(lines, _PREAMBLE, True), _POSTAMBLE, False))
    text = re.sub(r"```[a-z]*|\*\*|__|(?m:^#{1,6}\s+)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip().strip('"“”').strip()
    if len(text.split()) < MIN_LETTER_WORDS:
        raise AIError("The agent's answer didn't look like a letter (too short). Try again, or add instructions in the box.")
    return text + "\n", tidied


# ---------------------------------------------------------------- providers
def _call_anthropic(cfg: dict, system: str, user: str) -> Reply:
    import anthropic  # imported only when used, so the app stays light when the agent is off

    model = model_name(cfg)
    client = anthropic.Anthropic(api_key=api_key(cfg), timeout=float(_conf(cfg).get("timeout_seconds") or 180), max_retries=2)
    params = dict(model=model, max_tokens=MAX_TOKENS["anthropic"], system=system, messages=[{"role": "user", "content": user}])
    try:
        try:   # the model may decline some requests; the server can then retry on a fallback model (beta, default form)
            msg = client.beta.messages.create(**params, betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"})
        except anthropic.BadRequestError as e:
            if not re.search(r"fallback|beta", str(e), re.I):
                raise
            msg = client.messages.create(**params)      # this account/model doesn't take the fallback option: plain request
    except anthropic.NotFoundError:
        raise AIError(f"The model '{model}' was not found. Check the model name in Settings → AI agent.") from None
    except anthropic.AuthenticationError:
        raise AIError("The API key was rejected. Check it in Settings → AI agent.") from None
    except anthropic.PermissionDeniedError:
        raise AIError("This API key is not allowed to use that model.") from None
    except anthropic.BadRequestError as e:
        raise AIError(f"The request was rejected: {getattr(e, 'message', 'bad request')[:200]}") from None
    except anthropic.RateLimitError as e:
        wait = e.response.headers.get("retry-after", "") if getattr(e, "response", None) is not None else ""
        raise AIError(f"Rate limited by the API. Try again in {wait} seconds." if wait.isdigit() else "Rate limited by the API. Try again in a minute.") from None
    except anthropic.APIConnectionError:   # includes timeouts
        raise AIError("Could not reach the API (network error or timeout). Check the internet connection and try again.") from None
    except anthropic.APIStatusError as e:
        raise AIError(f"The API returned an error ({e.status_code}). Try again in a moment.") from None
    usage = getattr(msg, "usage", None)
    return Reply(text="".join(b.text for b in msg.content if getattr(b, "type", "") == "text"), model=getattr(msg, "model", model),
                 request_id=getattr(msg, "_request_id", "") or "", input_tokens=getattr(usage, "input_tokens", 0) or 0,
                 output_tokens=getattr(usage, "output_tokens", 0) or 0, stop="refusal" if msg.stop_reason == "refusal"
                 else "length" if msg.stop_reason == "max_tokens" else "end")


def _post(url: str, headers: dict, body: dict, timeout: float) -> requests.Response:
    try:
        return requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.exceptions.Timeout:
        raise AIError(f"{urlparse(url).netloc} took too long to answer. Raise the timeout in Settings → AI agent (local models can be slow).") from None
    except requests.exceptions.RequestException:
        raise AIError(f"Could not reach {urlparse(url).netloc}. Check the URL and that the server is running"
                      " (inside Docker, 'localhost' is the container itself: use the machine's address).") from None


def _message_text(content) -> str:
    """The reply text as a string: servers return a plain string, or a list of {"type": "text", "text": ...} parts."""
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def _call_openai(cfg: dict, system: str, user: str) -> Reply:
    c = _conf(cfg)
    base = (c.get("base_url") or "").strip().rstrip("/")
    url = base if base.endswith("/chat/completions") else base + "/chat/completions"
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key(cfg)}"} if api_key(cfg) else {})}
    body = {"model": model_name(cfg), "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": MAX_TOKENS["openai"]}
    timeout = float(c.get("timeout_seconds") or 180)
    r = _post(url, headers, body, timeout)
    if r.status_code == 400 and "max_completion_tokens" in r.text:       # newer OpenAI models renamed the parameter
        body["max_completion_tokens"] = body.pop("max_tokens")
        r = _post(url, headers, body, timeout)
    if r.status_code in (401, 403):
        raise AIError("The endpoint rejected the API key. Check it in Settings → AI agent.")
    if r.status_code == 404:
        raise AIError(f"Not found: check the endpoint URL and the model name '{model_name(cfg)}' in Settings → AI agent.")
    if r.status_code == 429:
        raise AIError("Rate limited by the API. Try again in a minute.")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = str((r.json().get("error") or {}).get("message", ""))[:200] if isinstance(r.json(), dict) else ""
        except ValueError:
            pass
        raise AIError(f"The endpoint returned an error ({r.status_code}){': ' + detail if detail else ''}.")
    try:
        data = r.json()
        choice = data["choices"][0]
        text = _message_text(choice["message"].get("content"))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        raise AIError("The endpoint answered, but not in the OpenAI chat format. Check that the URL is its /v1 chat endpoint.") from None
    usage = data.get("usage") or {}
    finish = choice.get("finish_reason") or ""
    return Reply(text=text, model=str(data.get("model") or model_name(cfg)), request_id=str(data.get("id") or ""),
                 input_tokens=usage.get("prompt_tokens") or 0, output_tokens=usage.get("completion_tokens") or 0,
                 stop="length" if finish == "length" else "refusal" if finish == "content_filter" else "end")


_CALLERS: dict[str, Callable[[dict, str, str], Reply]] = {"anthropic": _call_anthropic, "openai": _call_openai}


def generate(cfg: dict, job: dict, language: str, extra: str = "") -> AIResult:
    if not ready(cfg):
        raise AIError("The AI agent is not set up. Switch it on and complete the settings in Settings → AI agent.")
    system, user = build_messages(cfg, job, language, extra)
    reply = _CALLERS[provider(cfg)](cfg, system, user)
    if reply.stop == "refusal":
        raise AIError("The model declined to write this letter. Try rewording the extra instructions.")
    if reply.stop == "length":
        raise AIError("The answer was cut off. Try again, or use a model with a longer reply limit.")
    letter, tidied = extract_letter(reply.text)
    return AIResult(letter=letter, model=reply.model, request_id=reply.request_id, input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens, tidied=tidied)
