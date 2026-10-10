import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jobhunter.config import load_config
from jobhunter.scrapers.browser import Browser, playwright_available

CHROMIUM = os.environ.get("JOBHUNTER_CHROMIUM", "/opt/pw-browsers/chromium")
pytestmark = pytest.mark.skipif(not (playwright_available() and os.path.exists(CHROMIUM)),
                                reason="needs playwright + a chromium binary")

# A JS-rendered, obfuscated-class job list with 2 pages and a "next" button, like the real sites.
PAGES = {
    "/search": """<html><body><div id=app></div><script>
      const pages=[[["Software Engineer II","Amsterdam, Netherlands","/jobs/1001"],["Staff Engineer","Amsterdam, Netherlands","/jobs/1002"]],
                   [["Junior Developer","Berlin, Germany","/jobs/1003"],["Backend Engineer","Utrecht, Netherlands","/jobs/1004"]]];
      let p=0;function draw(){document.getElementById('app').innerHTML=pages[p].map(j=>
        `<div class="x9f"><div class="q1"><a class="zz" href="${j[2]}"><span>${j[0]}</span></a></div><div class="q2">${j[1]}</div></div>`).join('')
        +'<button id="n" aria-label="Next page">Next</button>';
        document.getElementById('n').onclick=()=>{if(p<1){p++;draw()}}}
      setTimeout(draw,300);</script></body></html>""",
    "/jobs/1001": "<html><body><main><h1>Software Engineer II</h1><p>Amsterdam, Netherlands</p><p>Use C# and Azure. 2+ years of experience.</p></main></body></html>",
    "/jobs/1004": "<html><body><main><h1>Backend Engineer</h1><p>Build APIs in Python.</p></main></body></html>",
}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write((body or "").encode())

    def log_message(self, *a):
        pass


def test_browser_scrape_pages_and_details():
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    cfg = load_config("config.example.yaml")
    cfg["browser"].update(executable=CHROMIUM, delay_seconds=0)
    s = Browser(cfg, {"name": "Acme", "url": base + "/search", "link_pattern": r"/jobs/\d+", "next": "#n", "max_pages": 3})
    jobs = []
    for j in s.fetch():
        if j.title == "Software Engineer II":
            s.enrich(j)
        jobs.append(j)
    srv.shutdown()
    assert [j.title for j in jobs] == ["Software Engineer II", "Staff Engineer", "Junior Developer", "Backend Engineer"]
    assert jobs[0].location == "Amsterdam, Netherlands" and "Azure" in jobs[0].description
    assert jobs[3].location == "Utrecht, Netherlands" and jobs[2].location == ""  # non-NL card must not borrow a neighbour's location
