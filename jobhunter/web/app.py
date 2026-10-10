from __future__ import annotations

import csv
import io
import json
import logging
import threading

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, url_for

from ..db import DB, STATUSES
from ..runner import run_all

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
    text = cfg["cover_letter"].format(**fields)
    return "\n".join(l.rstrip() for l in text.splitlines()).replace("\n\n\n", "\n\n").strip() + "\n"


def create_app(cfg: dict) -> Flask:
    app = Flask(__name__)
    db = DB(cfg["db_path"])
    scrape_lock = threading.Lock()
    state = {"running": False}

    @app.template_filter("fromjson")
    def fromjson(s):
        return json.loads(s or "[]")

    @app.template_filter("salary")
    def salary(job):
        if job["salary_max"]:
            lo, hi = job["salary_min"] or job["salary_max"], job["salary_max"]
            return f"€{lo // 1000}k–{hi // 1000}k" if lo != hi else f"€{hi // 1000}k"
        return ""

    @app.template_filter("pay")
    def pay(job):
        """-> (css class, label, tooltip) describing where the pay figure comes from."""
        k = lambda n: f"{n // 1000}k"
        conf = job["pay_confidence"]
        if conf == "stated":
            lo, hi = job["salary_min"] or job["salary_max"], job["salary_max"]
            return "pay", f"€{k(lo)}–{k(hi)}" if lo != hi else f"€{k(hi)}", "Stated in the job posting"
        rng = f"€{k(job['est_min'])}–{k(job['est_max'])}" if job["est_max"] else ""
        note = job["pay_note"] or ""
        if conf == "estimated":
            return "pay", f"≈ {rng} typical", f"Reported pay for this company/level ({note}). Not in the posting."
        if conf == "growth":
            tail = f" ({rng})" if rng else f" (€{k(job['salary_min'] or job['salary_max'])}–{k(job['salary_max'])})"
            return "growth", "🌱 big co, under 90k" + tail, f"Below €90k, but kept on purpose: {note or 'big company with career potential'}"
        if conf == "low":
            return "bad", f"⚠ typically {rng}", f"Reported pay is below your minimum ({note})"
        if conf == "likely":
            return "pay", "💰 likely 90k+ (assumed)", "No pay data found; assumed from company size"
        return "", "pay unknown", "No pay in the posting and no data found"

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
        return render_template("index.html", jobs=jobs, f=f, companies=db.companies(),
                               counts=db.counts(), summary=db.summary(), statuses=STATUSES, running=state["running"])

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
        def work():
            try:
                run_all(cfg, DB(cfg["db_path"]))
            except Exception:
                log.exception("manual scrape failed")
            finally:
                state["running"] = False
                scrape_lock.release()

        if scrape_lock.acquire(blocking=False):
            state["running"] = True
            threading.Thread(target=work, daemon=True).start()
        return redirect(url_for("status"))

    @app.get("/status")
    def status():
        return render_template("status.html", runs=db.last_runs(), links=cfg["manual_links"],
                               running=state["running"], companies=cfg["companies"])

    @app.get("/profile")
    def profile():
        return render_template("profile.html", p=cfg["profile"])

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

    return app
