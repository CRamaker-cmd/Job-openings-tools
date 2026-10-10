from __future__ import annotations

import csv
import io
import itertools
import json
import logging
import os
import threading
import time

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   url_for)

from .. import companies as co
from .. import scheduler, settings
from ..config import load_base
from ..db import DB, STATUSES
from ..runner import run_all
from ..scrapers import REGISTRY
from ..scrapers.browser import playwright_available

log = logging.getLogger(__name__)


def cover_letter(cfg: dict, job) -> str:
    p = cfg["profile"]
    matched = json.loads(job["reasons"] or "[]")
    skills = [r.replace("matches ", "") for r in matched if r.startswith("matches ")]
    skills_line = (f"My experience with {skills[0]} maps directly to what you're looking for."
                   if skills else "")
    fields = dict(
        company=job["company"], title=job["title"], years=p["years_experience"],
        pitch=p["pitch"], skills_line=skills_line, name=p["name"], email=p["email"],
        phone=p["phone"], linkedin=p["linkedin"],
    )
    try:
        text = cfg["cover_letter"].format(**fields)
    except (KeyError, IndexError, ValueError):  # a typo'd {placeholder} in the template must not break the page
        text = cfg["cover_letter"]
    return "\n".join(l.rstrip() for l in text.splitlines()).replace("\n\n\n", "\n\n").strip() + "\n"


def create_app(cfg: dict, scheduler_enabled: bool = False) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.urandom(16)  # only signs the one-request "saved!" messages
    db = DB(cfg["db_path"])
    lock = threading.Lock()
    state = {"running": False}

    # ------------------------------------------------------------ scraping control
    def start_scrape() -> bool:
        """Start a scrape in the background. False if one is already running."""
        if not lock.acquire(blocking=False):
            return False
        state["running"] = True

        def work():
            try:
                run_all(cfg, DB(cfg["db_path"]))
            except Exception:
                log.exception("scrape failed")
            finally:
                state["running"] = False
                lock.release()

        threading.Thread(target=work, name="scrape", daemon=True).start()
        return True

    if scheduler_enabled:
        scheduler.start(cfg, db.last_run_started, start_scrape)

    # ------------------------------------------------------------ template helpers
    @app.template_filter("fromjson")
    def fromjson(s):
        return json.loads(s or "[]")

    @app.template_filter("pay")
    def pay(job):
        """-> (css class, label, tooltip) describing where the pay figure comes from."""
        k = lambda n: f"{n // 1000}k"
        conf = job["pay_confidence"]
        floor = k(cfg["search"]["min_salary"])
        if conf == "stated":
            lo, hi = job["salary_min"] or job["salary_max"], job["salary_max"]
            return "pay", f"€{k(lo)}–{k(hi)}" if lo != hi else f"€{k(hi)}", "Stated in the job posting"
        rng = f"€{k(job['est_min'])}–{k(job['est_max'])}" if job["est_max"] else ""
        note = job["pay_note"] or ""
        if conf == "estimated":
            return "pay", f"≈ {rng} typical", f"Reported pay for this company/level ({note}). Not in the posting."
        if conf == "growth":
            tail = f" ({rng})" if rng else f" (€{k(job['salary_min'] or job['salary_max'])}–{k(job['salary_max'])})"
            return "growth", f"🌱 big co, under {floor}" + tail, \
                f"Below your usual minimum, but kept on purpose: {note or 'big company with career potential'}"
        if conf == "low":
            return "bad", f"⚠ typically {rng}", f"Reported pay is below your minimum ({note})"
        if conf == "likely":
            return "pay", f"💰 likely {floor}+ (assumed)", "No pay data found; assumed from company size"
        return "", "pay unknown", "No pay in the posting and no data found"

    @app.context_processor
    def inject():
        return {"running": state["running"], "min_salary": cfg["search"]["min_salary"]}

    def setup_steps():
        p = cfg["profile"]
        runs = db.last_runs()
        return [
            (bool(p["name"] and p["email"]), "Fill in your profile (name, email, skills) so cover letters and "
             "skill matching work", url_for("settings_page", section="profile")),
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
        }
        jobs = db.list_jobs(**f)
        steps = setup_steps()
        return render_template("index.html", jobs=jobs, f=f, companies=db.companies(),
                               counts=db.counts(), summary=db.summary(), statuses=STATUSES,
                               steps=steps, setup_done=all(s[0] for s in steps),
                               hidden_by_pay=len(db.list_jobs(**{**f, "pay": "all"})) - len(jobs))

    @app.get("/job/<int:job_id>")
    def job_page(job_id):
        job = db.get(job_id)
        if job is None:
            abort(404)
        return render_template("job.html", job=job, letter=cover_letter(cfg, job),
                               p=cfg["profile"], statuses=STATUSES)

    @app.post("/api/job/<int:job_id>/status")
    def api_status(job_id):
        status = (request.get_json(silent=True) or {}).get("status", "")
        if status not in STATUSES or db.get(job_id) is None:
            abort(400)
        db.set_status(job_id, status)
        return jsonify(ok=True, status=status)

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
        return render_template("help.html", cfg=cfg, browser_ok=playwright_available())

    @app.get("/export.csv")
    def export():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["score", "status", "company", "title", "location", "level", "pay", "url"])
        for r in db.list_jobs(status=request.args.get("status", "open"), pay="all"):
            w.writerow([r["score"], r["status"], r["company"], r["title"], r["location"],
                        r["level"], r["pay_confidence"], r["url"]])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=jobs.csv"})

    # ------------------------------------------------------------ settings
    def base_cfg():
        return load_base(cfg["_config_path"])

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
            values, errors = settings.validate_section(sec, request.form)
            if errors:
                for e in errors:
                    flash(e, "err")
                form_values = {f.path: request.form.get(f.path, "") for f in sec.fields}
            else:
                settings.save_values(db, cfg, base_cfg(), values)
                flash("Saved. Changes apply immediately (to the next scrape for scraping settings).", "ok")
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
            })
        return render_template("settings.html", sec=sec, rows=rows, sections=settings.SECTIONS,
                               n_modified=sum(r["modified"] for r in rows))

    @app.post("/settings/<section>/reset")
    def settings_reset(section):
        sec = settings.SECTION_BY_ID.get(section)
        if sec is None:
            abort(404)
        settings.reset_paths(db, cfg, base_cfg(), settings.section_paths(sec))
        flash(f"'{sec.title}' reset to defaults.", "ok")
        return redirect(url_for("settings_page", section=section))

    # ------------------------------------------------------------ companies
    def save_companies(items: list) -> None:
        settings.save_values(db, cfg, base_cfg(), {"companies": items})

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
