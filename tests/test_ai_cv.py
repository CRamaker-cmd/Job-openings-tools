"""AI agent (Claude via the official SDK, mocked: no network) and CV upload."""
import io
import zipfile
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from jobhunter import ai, cv
from jobhunter.config import load_config
from jobhunter.db import DB
from jobhunter.filters import evaluate
from jobhunter.models import RawJob
from jobhunter.web.app import create_app

KEY = "sk-ant-test-SECRET-KEY-1234567890"
CFG = load_config("config.example.yaml")
CFG["profile"].update(name="Caz Ramaker", email="caz@example.com", cv_text="CV: Medior Software Engineer at GS1 Nederland. Built REST APIs in C#.")
JOB = dict(company="Adyen N.V.", title="Backend Engineer", location="Amsterdam, Netherlands",
           description="You will design and build scalable payment APIs that handle millions of requests per day. C#, Azure.")
LETTER = ("Dear Adyen team,\n\n" + " ".join(["I build payment APIs in C# and Azure and handle large request volumes every day."] * 12) +
          "\n\nKind regards,\nCaz Ramaker")


# ------------------------------------------------------------------ fake SDK
class FakeMessages:
    def __init__(self, outer, beta):
        self.outer, self.beta = outer, beta

    def create(self, **kw):
        self.outer.calls.append({"beta": self.beta, **kw})
        if self.outer.raises:
            exc = self.outer.raises.pop(0) if isinstance(self.outer.raises, list) else self.outer.raises
            if exc:
                raise exc
        blocks = [SimpleNamespace(type="thinking", thinking="", text=None), SimpleNamespace(type="text", text=self.outer.reply)]
        return SimpleNamespace(content=blocks, stop_reason=self.outer.stop, model=self.outer.model_out, _request_id="req_123",
                               usage=SimpleNamespace(input_tokens=7000, output_tokens=420))


class FakeClient:
    def __init__(self, **init):
        self.init = init
        self.beta = SimpleNamespace(messages=FakeMessages(self, True))
        self.messages = FakeMessages(self, False)


@pytest.fixture
def fake(monkeypatch):
    state = SimpleNamespace(calls=[], raises=None, reply=f"<letter>{LETTER}</letter>", stop="end_turn", model_out="claude-opus-5-5", inits=[])

    def factory(**init):
        c = FakeClient(**init)
        c.calls = state.calls
        c.raises = state.raises
        c.reply, c.stop, c.model_out = state.reply, state.stop, state.model_out
        state.inits.append(init)
        return c
    monkeypatch.setattr(anthropic, "Anthropic", factory)
    for v in ("JOBHUNTER_AI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    return state


def cfg_ai(**ai_over):
    cfg = load_config("config.example.yaml")
    cfg["profile"].update(CFG["profile"])
    cfg["ai"].update({"enabled": True, "api_key": KEY, **ai_over})
    return cfg


def status_error(cls, code, headers=None, message="boom"):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(code, request=req, headers=headers or {}), body=None)


# ------------------------------------------------------------------ the prompt
def test_prompt_is_strict_complete_and_language_aware():
    system, user = ai.build_messages(cfg_ai(), JOB, "en", extra="Mention that I love their open-source work.")
    assert "NOTHING else" in system and "<letter>" in system and "Nothing before <letter>" in system and "no markdown" in system.lower()
    for must in ("220 to 280 words", "Never invent employers", "ONLY the <letter>...</letter> block", "Dear Adyen team,", "Kind regards,",
                 "Caz Ramaker", "payment APIs", "Mention that I love their open-source work.", "Medior Software Engineer at GS1 Nederland",
                 "I want to grow into an engineer", "tens of thousands", "passionate"):      # last two: the user's facts + the banned-phrase list
        assert must in user, must
    assert "Adyen N.V." not in user.split("=== JOB ===")[1].split("Title:")[0]               # legal suffix dropped
    assert "CV: Medior Software Engineer at GS1" in user                                     # the CV text is included in full
    nl_system, nl_user = ai.build_messages(cfg_ai(), JOB, "nl")
    assert "Beste team van Adyen," in nl_user and "Met vriendelijke groet," in nl_user and "Language: Dutch" in nl_user
    assert "Ik heb de performance" in nl_user or "Ik leidde de ontwikkeling" in nl_user      # Dutch achievements are used
    assert "(none)" in nl_user.split("=== EXTRA INSTRUCTIONS")[1]


# ------------------------------------------------------------------ reading the reply: only the letter comes out
@pytest.mark.parametrize("reply,tidied", [
    (f"<letter>{LETTER}</letter>", False),
    (f"Sure! Here is your letter:\n\n<letter>\n{LETTER}\n</letter>\n\nLet me know if you'd like changes!", False),
    (f"<letter>{LETTER}", True),                                                                  # closing tag missing
    (f"Here's the letter:\n\n{LETTER}\n\nI hope this helps! Let me know if you want it shorter.", True),   # ignored the format
    (f"```\n{LETTER}\n```", True),
    (f"**Subject**\n{LETTER}".replace("**Subject**\n", "") + "\n---", True),
])
def test_extract_letter_removes_everything_around_it(reply, tidied):
    letter, was_tidied = ai.extract_letter(reply)
    assert letter.startswith("Dear Adyen team,") and letter.rstrip().endswith("Caz Ramaker")
    for bloat in ("Sure", "Here is", "Here's", "Let me know", "I hope", "```", "<letter>", "---"):
        assert bloat not in letter
    assert was_tidied is tidied


def test_markdown_is_stripped_and_junk_replies_are_rejected():
    assert "**" not in ai.extract_letter("<letter>**Dear team,**\n\n" + "word " * 100 + "</letter>")[0]
    with pytest.raises(ai.AIError):
        ai.extract_letter("I'm sorry, I can't help with that.")
    with pytest.raises(ai.AIError):
        ai.extract_letter("<letter>Too short.</letter>")


# ------------------------------------------------------------------ the request
def test_request_uses_the_sdk_the_default_model_and_the_documented_shape(fake):
    res = ai.generate(cfg_ai(), JOB, "en", "be concrete")
    assert res.letter.startswith("Dear Adyen team") and res.model == "claude-opus-5-5" and res.request_id == "req_123"
    assert (res.input_tokens, res.output_tokens) == (7000, 420) and not res.tidied
    init = fake.inits[0]
    assert init["api_key"] == KEY and init["timeout"] >= 60 and init["max_retries"] == 2
    call = fake.calls[0]
    assert call["beta"] and call["betas"] == ["server-side-fallback-2026-07-01"] and call["extra_body"] == {"fallbacks": "default"}
    assert call["model"] == "claude-opus-5-5" and call["max_tokens"] >= 16000
    assert call["system"] == ai.SYSTEM and call["messages"][0]["role"] == "user" and "be concrete" in call["messages"][0]["content"]
    for unsupported in ("temperature", "top_p", "top_k", "thinking", "prefill"):             # rejected (400) by current models
        assert unsupported not in call
    assert ai.generate(cfg_ai(model="claude-sonnet-5-5"), JOB, "en").model == "claude-opus-5-5"   # reported model comes from the API
    assert fake.calls[1]["model"] == "claude-sonnet-5-5"                                      # the model setting is honoured


def test_falls_back_to_a_plain_request_if_the_beta_option_is_rejected(fake):
    fake.raises = [status_error(anthropic.BadRequestError, 400, message="unknown beta header: fallbacks")]
    res = ai.generate(cfg_ai(), JOB, "en")
    assert res.letter and [c["beta"] for c in fake.calls] == [True, False]
    assert "betas" not in fake.calls[1] and "extra_body" not in fake.calls[1]


@pytest.mark.parametrize("exc,expect", [
    (lambda: status_error(anthropic.AuthenticationError, 401), "key was rejected"),
    (lambda: status_error(anthropic.NotFoundError, 404), "was not found"),
    (lambda: status_error(anthropic.PermissionDeniedError, 403), "not allowed"),
    (lambda: status_error(anthropic.RateLimitError, 429, {"retry-after": "42"}), "42 seconds"),
    (lambda: status_error(anthropic.InternalServerError, 500), "(500)"),
    (lambda: anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "Could not reach"),
])
def test_errors_become_clear_messages_and_never_leak_the_key(fake, exc, expect):
    fake.raises = [exc()]
    with pytest.raises(ai.AIError) as e:
        ai.generate(cfg_ai(), JOB, "en")
    assert expect in str(e.value) and KEY not in str(e.value)


def test_refusals_cut_offs_and_missing_setup(fake):
    fake.stop = "refusal"
    with pytest.raises(ai.AIError, match="declined"):
        ai.generate(cfg_ai(), JOB, "en")
    fake.stop = "max_tokens"
    with pytest.raises(ai.AIError, match="cut off"):
        ai.generate(cfg_ai(), JOB, "en")
    fake.stop = "end_turn"
    sent_before = len(fake.calls)
    with pytest.raises(ai.AIError, match="not set up"):
        ai.generate(cfg_ai(enabled=False), JOB, "en")
    with pytest.raises(ai.AIError, match="not set up"):
        ai.generate(cfg_ai(api_key=""), JOB, "en")
    assert len(fake.calls) == sent_before                                                       # nothing was sent when not set up


def test_key_resolution_and_ready(monkeypatch):
    for v in ("JOBHUNTER_AI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert ai.ready(cfg_ai()) and not ai.ready(cfg_ai(enabled=False)) and not ai.ready(cfg_ai(api_key=""))
    monkeypatch.setenv("JOBHUNTER_AI_API_KEY", "from-env-key-1234567890")
    assert ai.api_key(cfg_ai()) == "from-env-key-1234567890" and ai.ready(cfg_ai(api_key=""))   # environment wins, key not needed in the DB
    assert not ai.ready(cfg_ai(enabled=False, api_key=""))                                      # still needs to be switched on


# ------------------------------------------------------------------ the dashboard
@pytest.fixture
def app_env(tmp_path, fake, full_form):
    (tmp_path / "config.yaml").write_text(f"db_path: {tmp_path}/a.db\n")
    cfg = load_config(tmp_path / "config.yaml")
    cfg["profile"].update(name="Caz", cv_text="my cv text " * 10)
    db = DB(cfg["db_path"])
    raw = RawJob(source="x", origin="x", company="Adyen N.V.", title="Backend Engineer", url="u", location="Amsterdam, Netherlands",
                 external_id="1", description=JOB["description"])
    db.upsert(raw, evaluate(raw, cfg), "2026-10-14T00:00:00+00:00")
    c = create_app(cfg).test_client()
    return cfg, db, c, db.list_jobs(pay="all")[0]["id"], full_form


def all_pages(c, jid):
    return "".join(c.get(u).data.decode() for u in ("/", f"/job/{jid}", "/settings/ai", "/settings/profile", "/help", "/status", "/companies", "/profile"))


def test_agent_button_appears_only_when_set_up_and_the_key_is_never_shown(app_env):
    cfg, db, c, jid, full_form = app_env
    assert 'id="agent-btn"' not in c.get(f"/job/{jid}").data.decode() and "Connect an AI agent" in c.get(f"/job/{jid}").data.decode()
    assert c.post(f"/api/job/{jid}/agent", json={}).status_code == 400                           # not set up: clear error, nothing sent
    form = full_form(cfg, "ai", **{"ai.enabled": "on", "ai.api_key": KEY, "ai.model": "claude-opus-5-5"})
    assert b"Saved" in c.post("/settings/ai", data=form, follow_redirects=True).data
    assert cfg["ai"]["api_key"] == KEY and cfg["ai"]["enabled"] is True
    pages = all_pages(c, jid)
    assert 'id="agent-btn"' in pages and KEY not in pages and "SECRET-KEY" not in pages          # write-only: never rendered anywhere
    assert "a key is saved" in c.get("/settings/ai").data.decode()
    # an empty key box keeps the saved key; the remove box clears it
    c.post("/settings/ai", data={**full_form(cfg, "ai", **{"ai.enabled": "on", "ai.api_key": None}), "ai.api_key": ""})
    assert cfg["ai"]["api_key"] == KEY
    c.post("/settings/ai", data={**full_form(cfg, "ai", **{"ai.enabled": "on"}), "ai.api_key": "", "ai.api_key__clear": "on"})
    assert cfg["ai"]["api_key"] == "" and 'id="agent-btn"' not in c.get(f"/job/{jid}").data.decode()
    assert b"look like an API key" in c.post("/settings/ai", data={**form, "ai.api_key": "has spaces in it"}, follow_redirects=True).data


def test_agent_endpoint_returns_only_the_letter(app_env, fake):
    cfg, db, c, jid, full_form = app_env
    cfg["ai"].update(enabled=True, api_key=KEY)
    fake.reply = f"Sure, here you go!\n\n<letter>{LETTER}</letter>\n\nHope that helps."
    r = c.post(f"/api/job/{jid}/agent", json={"extra": "Mention my open-source work", "lang": "en"})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and j["letter"].startswith("Dear Adyen team") and "Sure" not in j["letter"] and "Hope that" not in j["letter"]
    assert j["words"] > 80 and j["tokens"] == {"in": 7000, "out": 420} and j["model"] == "claude-opus-5-5"
    assert KEY not in r.data.decode()
    sent = fake.calls[-1]["messages"][0]["content"]
    assert "Mention my open-source work" in sent and "design and build scalable payment APIs" in sent and "my cv text" in sent
    # failures come back as readable errors, not stack traces
    fake.raises = [status_error(anthropic.AuthenticationError, 401)]
    bad = c.post(f"/api/job/{jid}/agent", json={})
    assert bad.status_code == 502 and "key was rejected" in bad.get_json()["error"] and KEY not in bad.data.decode()
    assert c.post("/api/job/9999/agent", json={}).status_code == 404


# ------------------------------------------------------------------ CV upload
def make_docx(paragraphs):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def make_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs = ["<</Type/Catalog/Pages 2 0 R>>", "<</Type/Pages/Kids[3 0 R]/Count 1>>",
            "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
            f"<</Length {len(stream)}>>\nstream\n{stream}\nendstream", "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<</Root 1 0 R/Size {len(objs) + 1}>>\nstartxref\n{xref}\n%%EOF\n".encode()


TEXT = "Caz Ramaker. Medior Software Engineer at GS1 Nederland. I build REST APIs in C# and run them on Azure."


@pytest.mark.parametrize("name,data", [("cv.txt", TEXT.encode()), ("cv.md", ("# CV\n\n" + TEXT).encode()),
                                       ("cv.docx", make_docx([TEXT, "Skills: C#, Azure"])), ("cv.pdf", make_pdf(TEXT))])
def test_cv_text_is_extracted_from_every_supported_format(name, data):
    out = cv.extract_text(name, data)
    assert "Medior Software Engineer at GS1 Nederland" in out and "REST APIs" in out


@pytest.mark.parametrize("name,data,msg", [
    ("cv.exe", b"MZ" * 50, "Upload a PDF"), ("cv.pdf", b"not a pdf at all" * 5, "doesn't look like a PDF"),
    ("cv.docx", b"not a zip" * 10, "Word"), ("cv.txt", b"", "empty"), ("cv.txt", b"too short", "No readable text"),
    ("cv.pdf", make_pdf(""), "No readable text"), ("cv.txt", b"x" * (cv.MAX_BYTES + 1), "larger than"),
    ("cv.txt", (b"word " * 20000), "too long"),
])
def test_cv_problems_give_a_message_the_user_can_act_on(name, data, msg):
    with pytest.raises(cv.CVError, match=msg):
        cv.extract_text(name, data)


def test_cv_upload_replace_download_and_remove(app_env):
    cfg, db, c, jid, full_form = app_env
    r = c.post("/profile/cv", data={"cv": (io.BytesIO(make_docx([TEXT])), "My CV.docx")}, content_type="multipart/form-data", follow_redirects=True)
    assert b"CV read" in r.data and cfg["profile"]["cv_filename"] == "My CV.docx" and "GS1 Nederland" in cfg["profile"]["cv_text"]
    page = c.get("/settings/profile").data.decode()
    assert "My CV.docx" in page and "words read" in page and "GS1 Nederland" in page          # shown, and the text is editable below
    assert c.get("/profile/cv/file").status_code == 200
    # a bad upload changes nothing
    r = c.post("/profile/cv", data={"cv": (io.BytesIO(b"nope"), "cv.exe")}, content_type="multipart/form-data", follow_redirects=True)
    assert b"Upload a PDF" in r.data and cfg["profile"]["cv_filename"] == "My CV.docx"
    # the stored text is editable like any setting and is what the agent receives
    form = full_form(cfg, "profile", **{"profile.cv_text": "My edited CV text for the agent"})
    c.post("/settings/profile", data=form)
    assert cfg["profile"]["cv_text"] == "My edited CV text for the agent"
    c.post("/profile/cv/remove")
    assert cfg["profile"]["cv_filename"] == "" and cfg["profile"]["cv_text"] == "" and c.get("/profile/cv/file").status_code == 404


# ------------------------------------------------------------------ OpenAI-compatible endpoints (local models etc.)
def oa_cfg(**over):
    c = cfg_ai(provider="openai", base_url="http://10.0.0.5:11434/v1/", model="llama3.1:8b", api_key="")
    c["ai"].update(over)
    return c


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload = status, payload
        self.text = text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def oa_ok(content=LETTER, finish="stop"):
    return FakeResponse(200, {"id": "x1", "model": "llama3.1:8b", "choices": [{"message": {"content": content}, "finish_reason": finish}],
                              "usage": {"prompt_tokens": 900, "completion_tokens": 300}})


@pytest.fixture
def posts(monkeypatch):
    calls, queue = [], []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "body": json, "timeout": timeout})
        return queue.pop(0)

    monkeypatch.setattr(ai.requests, "post", fake_post)
    return SimpleNamespace(calls=calls, queue=queue)


def test_openai_compatible_request_needs_no_key_and_builds_the_url(posts):
    posts.queue.append(oa_ok("<think>hmm</think><letter>" + LETTER + "</letter>"))
    cfg = oa_cfg()
    assert ai.ready(cfg) and ai.host_label(cfg) == "10.0.0.5:11434"
    res = ai.generate(cfg, JOB, "en")
    call = posts.calls[0]
    assert call["url"] == "http://10.0.0.5:11434/v1/chat/completions"
    assert "Authorization" not in call["headers"] and call["body"]["model"] == "llama3.1:8b" and call["timeout"] == 180
    assert res.letter.strip() == LETTER and res.input_tokens == 900


def test_openai_key_is_sent_as_bearer_and_never_leaks(posts):
    posts.queue.append(FakeResponse(401, {"error": {"message": "bad"}}))
    with pytest.raises(ai.AIError) as e:
        ai.generate(oa_cfg(api_key=KEY), JOB, "en")
    assert posts.calls[0]["headers"]["Authorization"] == f"Bearer {KEY}" and KEY not in str(e.value)


def test_openai_retries_with_max_completion_tokens(posts):
    posts.queue += [FakeResponse(400, {"error": {}}, text="Unsupported parameter: 'max_tokens' ... use 'max_completion_tokens'"), oa_ok()]
    ai.generate(oa_cfg(), JOB, "en")
    assert "max_tokens" not in posts.calls[1]["body"] and posts.calls[1]["body"]["max_completion_tokens"] == ai.MAX_TOKENS["openai"]


@pytest.mark.parametrize("resp,expect", [
    (FakeResponse(404, text="nope"), "Not found"),
    (FakeResponse(429, text="slow"), "Rate limited"),
    (FakeResponse(500, {"error": {"message": "model crashed"}}), "model crashed"),
    (FakeResponse(200, {"unexpected": True}), "OpenAI chat format"),
    (oa_ok(finish="length"), "cut off"),
    (oa_ok(finish="content_filter"), "declined"),
])
def test_openai_errors_become_clear_messages(posts, resp, expect):
    posts.queue.append(resp)
    with pytest.raises(ai.AIError, match=expect):
        ai.generate(oa_cfg(), JOB, "en")


def test_openai_needs_url_and_model_but_not_a_key():
    assert not ai.ready(oa_cfg(base_url="")) and not ai.ready(oa_cfg(model="")) and ai.ready(oa_cfg())


def test_unreachable_server_message_mentions_docker(monkeypatch):
    def boom(*a, **k):
        raise ai.requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(ai.requests, "post", boom)
    with pytest.raises(ai.AIError, match="Docker"):
        ai.generate(oa_cfg(), JOB, "en")


def test_prompt_endpoint_and_light_overview_rows(app_env):
    cfg, db, c, jid, _ = app_env
    page = c.get(f"/job/{jid}").get_data(as_text=True)
    assert "aiprompt" not in page                                    # the prompt is built on demand, not embedded in every page
    body = c.get(f"/api/job/{jid}/prompt?lang=en").get_json()["prompt"]
    assert "Adyen" in body and len(body) > 500
    assert "description" not in db.list_jobs(pay="all", light=True)[0].keys()
    assert db.count_jobs(pay="all") == len(db.list_jobs(pay="all"))
