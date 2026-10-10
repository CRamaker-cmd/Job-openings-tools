from __future__ import annotations

import argparse
import csv
import logging
import sys

from .config import load_config
from .db import DB
from .runner import run_all
from .scrapers import build_scrapers


def cmd_scrape(args, cfg):
    db = DB(cfg["db_path"])
    results = run_all(cfg, db, args.only)
    failed = 0
    for name, r in results:
        if isinstance(r, Exception):
            failed += 1
            print(f"  FAIL  {name}: {r}")
        else:
            print(f"  ok    {name}: {r.seen} listed, {r.kept} relevant, {r.new} new")
    print(f"{len(results) - failed}/{len(results)} sources ok")


def cmd_check(args, cfg):
    """Ping each source and report whether its endpoint still works (run this once on the Pi)."""
    bad = 0
    for s in build_scrapers(cfg, args.only):
        try:
            n = sum(1 for _ in s.fetch())
            print(f"  ok    {s.name}: {n} postings listed")
        except Exception as e:
            bad += 1
            print(f"  FAIL  {s.name}: {e}")
    sys.exit(1 if bad else 0)


def cmd_serve(args, cfg):
    from waitress import serve
    from .web.app import create_app
    host, port = cfg["web"]["host"], cfg["web"]["port"]
    print(f"Serving on http://{host}:{port}")
    try:
        serve(create_app(cfg), host=host, port=port)
    except OSError as e:
        sys.exit(f"Cannot listen on port {port} ({e.strerror}). Is something else (e.g. Pi-hole) using it? "
                 f"Set a free port in config.yaml under web: port:")


def cmd_export(args, cfg):
    db = DB(cfg["db_path"])
    rows = db.list_jobs(status=args.status, pay="all")
    w = csv.writer(sys.stdout)
    w.writerow(["score", "status", "company", "title", "location", "level", "pay", "url"])
    for r in rows:
        w.writerow([r["score"], r["status"], r["company"], r["title"], r["location"],
                    r["level"], r["pay_confidence"], r["url"]])


def main(argv=None):
    p = argparse.ArgumentParser(prog="jobhunter")
    p.add_argument("-c", "--config", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn, h in (("scrape", cmd_scrape, "fetch new jobs"),
                        ("check", cmd_check, "test that every source endpoint responds")):
        sp = sub.add_parser(name, help=h)
        sp.add_argument("--only", help="only sources whose name contains this")
        sp.set_defaults(fn=fn)
    sub.add_parser("serve", help="start the web UI").set_defaults(fn=cmd_serve)
    ex = sub.add_parser("export", help="CSV to stdout")
    ex.add_argument("--status", default="open")
    ex.set_defaults(fn=cmd_export)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    args.fn(args, load_config(args.config))
