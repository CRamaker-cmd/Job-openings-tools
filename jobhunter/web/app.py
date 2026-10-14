from __future__ import annotations

import csv
import io
import itertools
import json
import logging
import os
import threading
import time

from flask import (Flask, Response, send_file, abort, flash, jsonify, redirect, render_template, request,
                   url_for)

from .. import companies as co
from .. import scheduler, settings
from ..config import load_base
from .. import money
from .. import ai, cv, letters
from ..countries import COUNTRIES, currency_of, min_salary_for, pay_row, primary_country, selected, suggest_row
from ..db import DB, STATUSES
from ..runner import rescore, run_all, run_one
from ..scrapers import REGISTRY, source_names
from ..scrapers.browser import playwright_available

log = logging.getLogger(__name__)


def create_app(cfg: dict, scheduler_enabled: bool = False) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.urandom(16)
    app.config["MAX_CONTENT_LENGTH"] = cv.MAX_BYTES + 512 * 1024    # uploads are limited to the CV size  # only signs the one-request "saved!" messages
    db = DB(cfg["db_path"])
    lock = threading.Lock()
    state = {"running": False, "what": ""}

    # ------------------------------------------------------------ scraping control
    def start_job(work, label: str) -> bool:
        """Run `work(db)` in the background, one job at a time. False if something is already running."""
        if not lock.acquire(blocking=False):
            return False
        state["running"], state["what"] = True, label

        def run():
            try:
                work(DB(cfg["db_path"]))
            except Exception:
                log.exception("scrape failed")
            finally:
                state["running"], state["what"] = False, ""
                lock.release()

        threading.Thread(target=run, name="scrape", daemon=True).start()
        return True

    def start_scrape() -> bool:
        """Everything now, one source after another ('Scrape now')."""
        return start_job(lambda d: run_all(cfg, d), "all sources")

    def start_one(name: str) -> bool:
        """A single source (used by the background scheduler)."""
        return start_job(lambda d: run_one(cfg, d, name), name)

    if scheduler_enabled:
        scheduler.start(cfg, lambda: source_names(cfg), db.last_run_by_origin, start_one)

    # ------------------------------------------------------------ template helpers
    @app.template_filter("flag")
    def flag(code):
        c = COUNTRIES.get(code or "")
        return f"{c.flag} {c.code}" if c else "🌍 remote"

    @app.template_filter("fromjson")
    def fromjson(s):
        return json.loads(s or "[]")

    @app.template_filter("pay")
    def pay(job):
        """-> (css class, label, tooltip) describing where the pay figure comes from, in the job's own currency."""
        cur = currency_of(job["country"] or "")
        loc = lambda eur: money.to_local(eur, cur, cfg)
        rng = lambda lo, hi: money.rng(loc(lo), loc(hi), cur)
        floor = money.fmt(loc(min_salary_for(cfg, job["country"] or primary_country(cfg))), cur)
        conf = job["pay_confidence"]
        if conf == "stated":
            lo, hi = job["salary_min"] or job["salary_max"], job["salary_max"]
            return "pay", rng(lo, hi), job["pay_note"] or "Stated in the job posting"
        est = rng(job["est_min"], job["est_max"]) if job["est_max"] else ""
        note = job["pay_note"] or ""
        if conf == "estimated":
            return "pay", f"≈ {est} typical", f"Reported pay for this company/level ({note}). Not in the posting."
        if conf == "growth":
            tail = f" ({est})" if est else f" ({rng(job['salary_min'] or job['salary_max'], job['salary_max'])})"
            return "growth", f"🌱 big co, under {floor}" + tail, \
                f"Below your usual minimum, but kept on purpose: {note or 'big company with career potential'}"
        if conf == "low":
            return "bad", f"⚠ typically {est}", f"Reported pay is below your minimum ({note})"
        if conf == "likely":
            return "pay", f"💰 likely {floor}+ (assumed)", "No pay data found; assumed from company size"
        return "", "pay unknown", "No pay in the posting and no data found"

    @app.context_processor
    def inject():
        pc = primary_country(cfg)
        cur = currency_of(pc)
        return {"running": state["running"], "running_what": state["what"],
                "min_label": money.fmt(pay_row(cfg, pc)["min"], cur), "big_label": money.fmt(pay_row(cfg, pc)["big"], cur)}

    def setup_steps():
        p = cfg["profile"]
        runs = db.last_runs()
        return [
            (bool(p["name"] and p["email"] and p.get("ambition") and p.get("achievements")),
             "Fill in your profile: name, email, skills, plus your ambition and a few achievements, which make the "
             "motivation letters personal", url_for("settings_page", section="profile")),
            (bool(cfg["companies"]), "Check the companies list: add the employers you care about",
             url_for("companies_page")),
            (db.last_run_started() is not None, "Run the first scrape (press Scrape now, or wait for the schedule)", None),
            (bool(runs) and not any(not r["ok"] for r in runs),
             "Check that every source worked (some company feeds may need fixing)", url_for("status")),
        ]

    # ------------------------------------------------------------ dashboard
    @app.get("/")
    def index():
        f = {
            "status": request.args.get("status", "open"),
            "q": request.args.get("q", "").strip(),
            "company": request.args.get("company", ""),
            "min_score": int(request.args.get("min_score") or 0),
            "pay": request.args.get("pay", "good"),
            "level": request.args.get("level", ""),
            "sort": request.args.get("sort", "score"),
            "country": request.args.get("country", ""),
        }
        su = cfg["search"]["show_unknown_pay"]
        codes = [c.code for c in selected(cfg)]
        if f["country"] not in codes:
            f["country"] = ""
        jobs = db.list_jobs(**f, show_unknown=su, countries=codes)
        steps = setup_steps()
        return render_template("index.html", jobs=jobs, f=f, companies=db.companies(),
                               counts=db.counts(), summary=db.summary(su), statuses=STATUSES,
                               steps=steps, setup_done=all(s[0] for s in steps),
                               hidden_by_pay=len(db.list_jobs(**{**f, "pay": "all"}, show_unknown=su, countries=codes)) - len(jobs),
                               countries=[COUNTRIES[c] for c in codes], country_counts=db.country_counts())

    @app.get("/job/<int:job_id>")
    def job_page(job_id):
        job = db.get(job_id)
        if job is None:
            abort(404)
        lang = request.args.get("lang") if request.args.get("lang") in ("en", "nl") else None
        letter = letters.generate(cfg, dict(job), variant=request.args.get("v", type=int), language=lang)
        return render_template("job.html", job=job, letter=letter, lang=lang or "auto", p=cfg["profile"], statuses=STATUSES,
                               ai_prompt=letters.build_prompt(cfg, dict(job), letter.language),
                               profile_ready=bool(cfg["profile"].get("achievements") and cfg["profile"].get("ambition")),
                               ai_ready=ai.ready(cfg), ai_model=cfg["ai"].get("model") or ai.DEFAULT_MODEL, has_cv=bool(cfg["profile"].get("cv_text")))

    @app.post("/api/job/<int:job_id>/status")
    def api_status(job_id):
        status = (request.get_json(silent=True) or {}).get("status", "")
        if status not in STATUSES or db.get(job_id) is None:
            abort(400)
        db.set_status(job_id, status)
        return jsonify(ok=True, status=status)

    @app.post("/api/job/<int:job_id>/delete")
    def api_delete(job_id):
        if db.get(job_id) is None:
            abort(404)
        db.delete_job(job_id)
        return jsonify(ok=True)

    ai_lock = threading.Lock()

    @app.post("/api/job/<int:job_id>/agent")
    def api_agent(job_id):
        """Ask the AI agent to write the letter for this job. Returns {ok, letter, model, tokens} or {ok: false, error}."""
        job = db.get(job_id)
        if job is None:
            abort(404)
        if not ai.ready(cfg):
            return jsonify(ok=False, error="The AI agent is not set up. Switch it on and add an API key in Settings → AI agent."), 400
        body = request.get_json(silent=True) or {}
        lang = body.get("lang") if body.get("lang") in ("en", "nl") else None
        language = lang or (cfg["profile"].get("letter_language") if cfg["profile"].get("letter_language") in ("en", "nl") else None) \
            or letters.detect_language(job["description"] or "")
        if not ai_lock.acquire(blocking=False):
            return jsonify(ok=False, error="The agent is already writing a letter. Wait for it to finish."), 429
        try:
            res = ai.generate(cfg, dict(job), language, str(body.get("extra", ""))[:3000])
        except ai.AIError as e:
            return jsonify(ok=False, error=str(e)), 502
        except Exception:
            log.exception("AI agent failed")
            return jsonify(ok=False, error="Something went wrong while contacting the agent. See the app log."), 500
        finally:
            ai_lock.release()
        log.info("AI letter for job %s by %s (request %s, %s in / %s out tokens)", job_id, res.model, res.request_id, res.input_tokens, res.output_tokens)
        return jsonify(ok=True, letter=res.letter, model=res.model, tidied=res.tidied,
                       words=len(res.letter.split()), tokens={"in": res.input_tokens, "out": res.output_tokens})

    @app.post("/api/job/<int:job_id>/notes")
    def api_notes(job_id):
        if db.get(job_id) is None:
            abort(404)
        db.set_notes(job_id, (request.get_json(silent=True) or {}).get("notes", "")[:5000])
        return jsonify(ok=True)

    @app.post("/scrape")
    def scrape_now():
        if not start_scrape():
            flash("A scrape is already running.", "info")
        else:
            flash("Scrape started. New jobs appear on the dashboard as they are found - refresh in a minute or two.", "ok")
        return redirect(request.referrer or url_for("status"))

    @app.get("/status")
    def status():
        return render_template("status.html", runs=db.last_runs(), links=cfg["manual_links"],
                               companies=cfg["companies"], schedule=cfg["schedule"],
                               last_run=db.last_run_started())

    @app.get("/profile")
    def profile():
        return render_template("profile.html", p=cfg["profile"])

    @app.get("/help")
    def help_page():
        return render_template("help.html", cfg=cfg, browser_ok=playwright_available(), picked_countries=selected(cfg))

    @app.get("/export.csv")
    def export():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["score", "status", "company", "title", "country", "location", "level", "pay", "url"])
        for r in db.list_jobs(status=request.args.get("status", "open"), pay="all"):
            w.writerow([r["score"], r["status"], r["company"], r["title"], r["country"], r["location"],
                        r["level"], r["pay_confidence"], r["url"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=jobs.csv"})

    # ------------------------------------------------------------ settings
    def base_cfg():
        return load_base(cfg["_config_path"])

    def apply_rule_change(section: str) -> str:
        """Jobs we already have are never re-fetched, so after the rules change we re-score them locally
        (no network). Dropped postings get another look at the next scrape."""
        if section in ("matching", "pay", "advanced", "profile"):
            db.clear_rejected()
            done, moved = rescore(cfg, db)
            msg = f"Re-scored {done} job{'s' if done != 1 else ''} with the new rules"
            return msg + (f"; {moved} no longer fit and moved to Hidden." if moved else ".")
        return "Applies from the next scrape."

    @app.get("/settings")
    def settings_index():
        return redirect(url_for("settings_page", section="profile"))

    @app.route("/settings/<section>", methods=["GET", "POST"])
    def settings_page(section):
        sec = settings.SECTION_BY_ID.get(section)
        if sec is None:
            abort(404)
        form_values = None
        if request.method == "POST":
            values, errors = settings.validate_section(sec, request.form, cfg)
            if errors:
                for e in errors:
                    flash(e, "err")
                form_values = {f.path: request.form.get(f.path, "") for f in sec.fields}
            else:
                settings.save_values(db, cfg, base_cfg(), values)
                flash("Saved. " + apply_rule_change(section), "ok")
                return redirect(url_for("settings_page", section=section))
        base = base_cfg()
        rows = []
        for f in sec.fields:
            cur = settings.get_path(cfg, f.path)
            default = settings.get_path(base, f.path)
            rows.append({
                "f": f, "value": cur,
                "text": form_values[f.path] if form_values else settings.to_text(f, cur),
                "default_text": settings.to_text(f, default) if f.kind in ("int", "float", "bool", "text") else "",
                "modified": cur != default,
                "has_value": bool(cur) if f.kind == "secret" else False,
            })
        ticked = {c.code for c in selected(cfg)}
        if form_values is not None:                       # a failed save: keep what was typed
            ticked = set(request.form.getlist("search.countries"))
        pay_rows = []
        for c in COUNTRIES.values():
            saved = (cfg["search"].get("pay_by_country") or {}).get(c.code)
            row = saved or suggest_row(cfg, c.code)
            if form_values is not None and request.form.get(f"pay.{c.code}.min"):
                row = {"min": request.form.get(f"pay.{c.code}.min"), "big": request.form.get(f"pay.{c.code}.big", "")}
            pay_rows.append({"c": c, "min": row["min"], "big": row["big"], "ticked": c.code in ticked,
                             "symbol": money.sym(c.currency).strip()})
        return render_template("settings.html", sec=sec, rows=rows, sections=settings.SECTIONS,
                               n_modified=sum(r["modified"] for r in rows), picked=selected(cfg), pay_rows=pay_rows,
                               ai_env_key=ai.key_from_environment(),
                               cfg_profile=cfg["profile"])

    @app.post("/settings/<section>/reset")
    def settings_reset(section):
        sec = settings.SECTION_BY_ID.get(section)
        if sec is None:
            abort(404)
        settings.reset_paths(db, cfg, base_cfg(), settings.section_paths(sec))
        flash(f"'{sec.title}' reset to defaults.", "ok")
        return redirect(url_for("settings_page", section=section))

    # ------------------------------------------------------------ CV upload
    @app.post("/profile/cv")
    def cv_upload():
        f = request.files.get("cv")
        if f is None or not f.filename:
            flash("Choose a file first.", "err")
            return redirect(url_for("settings_page", section="profile"))
        data = f.read()
        try:
            text = cv.extract_text(f.filename, data)
        except cv.CVError as e:
            flash(str(e), "err")
            return redirect(url_for("settings_page", section="profile"))
        name = cv.save_file(cfg, f.filename, data)
        settings.save_values(db, cfg, base_cfg(), {"profile.cv_text": text, "profile.cv_filename": f.filename[:120]})
        flash(f"CV read: {len(text.split())} words from {name}. Check the text below and fix anything odd.", "ok")
        return redirect(url_for("settings_page", section="profile"))

    @app.post("/profile/cv/remove")
    def cv_remove():
        cv.remove_file(cfg)
        settings.save_values(db, cfg, base_cfg(), {"profile.cv_text": "", "profile.cv_filename": ""})
        flash("CV removed.", "ok")
        return redirect(url_for("settings_page", section="profile"))

    @app.get("/profile/cv/file")
    def cv_file():
        path = cv.stored_file(cfg)
        if path is None:
            abort(404)
        return send_file(path, as_attachment=True, download_name=cfg["profile"].get("cv_filename") or path.name)

    # ------------------------------------------------------------ companies
    def save_companies(items: list) -> None:
        settings.save_values(db, cfg, base_cfg(), {"companies": items})
        rescore(cfg, db)  # tiers can change pay assumptions of jobs already saved

    @app.get("/companies")
    def companies_page():
        edit = request.args.get("edit")
        entry, idx = None, None
        if edit == "new":
            entry = {"tier": 1}
        elif edit is not None and edit.isdigit() and int(edit) < len(cfg["companies"]):
            idx, entry = int(edit), cfg["companies"][int(edit)]
        modified = cfg["companies"] != base_cfg()["companies"]
        return render_template("companies.html", items=cfg["companies"], ats=co.ATS, tiers=co.TIER_LABELS,
                               entry=entry, idx=idx, modified=modified, browser_ok=playwright_available(),
                               runs={r["origin"]: r for r in db.last_runs()})

    @app.post("/companies/save")
    def companies_save():
        entry, errors = co.validate(request.form)
        idx = request.form.get("idx", "")
        if errors:
            for e in errors:
                flash(e, "err")
            return redirect(url_for("companies_page", edit=idx if idx != "" else "new"))
        items = [dict(c) for c in cfg["companies"]]
        if idx.isdigit() and int(idx) < len(items):
            old = items[int(idx)]
            # keep settings the form doesn't show (e.g. a browser entry's click 'steps')
            keep = {k: v for k, v in old.items() if k not in {"name", "ats", "tier", "disabled",
                                                              *(k2 for k2, *_ in co.ATS[entry["ats"]]["fields"])}}
            items[int(idx)] = {**entry, **keep} if old.get("ats") == entry["ats"] else entry
        else:
            items.append(entry)
        save_companies(items)
        flash(f"Saved {entry['name']}. Use 'Test' to check it can be read.", "ok")
        return redirect(url_for("companies_page"))

    @app.post("/companies/<int:i>/delete")
    def companies_delete(i):
        items = [dict(c) for c in cfg["companies"]]
        if i >= len(items):
            abort(404)
        gone = items.pop(i)
        save_companies(items)
        flash(f"Removed {gone['name']}. Jobs already collected stay on the dashboard until they expire.", "ok")
        return redirect(url_for("companies_page"))

    @app.post("/companies/<int:i>/toggle")
    def companies_toggle(i):
        items = [dict(c) for c in cfg["companies"]]
        if i >= len(items):
            abort(404)
        if items[i].get("disabled"):
            items[i].pop("disabled")
        else:
            items[i]["disabled"] = True
        save_companies(items)
        return redirect(url_for("companies_page"))

    @app.post("/companies/reset")
    def companies_reset():
        settings.reset_paths(db, cfg, base_cfg(), ["companies"])
        flash("Companies reset to the defaults from config.yaml.", "ok")
        return redirect(url_for("companies_page"))

    @app.post("/companies/<int:i>/test")
    def companies_test(i):
        """Fetch the first postings of one company so you can see whether the setup works."""
        if i >= len(cfg["companies"]):
            abort(404)
        entry = cfg["companies"][i]
        if entry["ats"] == "browser" and not playwright_available():
            return jsonify(ok=False, message="Browser scraping isn't installed (see Help).")
        t0 = time.time()
        try:
            scraper = REGISTRY[entry["ats"]](cfg, entry)
            jobs = list(itertools.islice(scraper.fetch(), 50))
        except Exception as e:
            return jsonify(ok=False, message=f"{type(e).__name__}: {str(e)[:200]}")
        took = f"{time.time() - t0:.0f}s"
        if not jobs:
            return jsonify(ok=False, message=f"Reached the site but found 0 jobs ({took}). Check the details above.")
        sample = ", ".join(j.title for j in jobs[:2])
        return jsonify(ok=True, message=f"Works: {len(jobs)}{'+' if len(jobs) == 50 else ''} postings found ({took}), "
                                        f"e.g. {sample}")

    return app
