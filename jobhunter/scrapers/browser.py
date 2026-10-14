"""Generic headless-browser scraper for career sites that have no public feed (Google, Meta, Apple, ...).

It loads the search page (filters go in the URL and/or in `steps` that fill/click like a person would),
finds job links by URL pattern - not by CSS class names, which these sites obfuscate and change -
pages through results, and opens each relevant posting to read its description.

Needs the optional extra:  pip install -r requirements-browser.txt && playwright install chromium
(on a Pi you can instead `sudo apt install chromium` and set  browser.executable: /usr/bin/chromium).

Config example:
  - name: Apple
    ats: browser
    url: https://jobs.apple.com/en-nl/search?location=netherlands-NLD&team=software-and-services-SFTWR
    link_pattern: "/details/\\d+"          # regex the job-link href must match
    next: "button[aria-label='Next Page']"  # optional "next page" control
    max_pages: 5
    steps:                                   # optional, run after load
      - {click: "button:has-text('Accept')"}
      - {fill: ["input[name=q]", "software engineer"]}
      - {press: "Enter"}
      - {wait: 1500}
"""
from __future__ import annotations

import importlib.util
import logging
import re
from typing import Iterator

from ..countries import keywords_for
from ..http import polite_sleep
from ..models import RawJob
from .base import Scraper

log = logging.getLogger(__name__)

# Runs inside the page. For every <a> whose href matches the pattern, climb to the card that
# contains it and report title / location / url.
EXTRACT_JS = """
([pattern, keywords]) => {
  const re = new RegExp(pattern), seen = new Set(), out = [];
  const kw = keywords.map(k => k.toLowerCase());
  const hasLoc = t => kw.some(k => new RegExp('(^|[^a-z])' + k.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '([^a-z]|$)').test(t.toLowerCase()));
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.href;
    if (!re.test(href) || seen.has(href.split('?')[0])) continue;
    seen.add(href.split('?')[0]);
    const lines = t => t.split('\\n').map(s => s.trim()).filter(Boolean);
    let title = (a.getAttribute('aria-label') || lines(a.innerText)[0] || '').trim();
    // climb to the card around this link, but never into a container holding other job links
    let card = a;
    while (card.parentElement && card.parentElement.innerText.length < 600) {
      const hrefs = [...card.parentElement.querySelectorAll('a[href]')].filter(x => re.test(x.href)).map(x => x.href.split('?')[0]);
      if (new Set(hrefs).size > 1) break;
      card = card.parentElement;
    }
    const loc = lines(card.innerText).find(l => l !== title && l.length < 120 && hasLoc(l)) || '';
    if (!title) { const h = card.querySelector('h1,h2,h3,h4'); title = h ? h.innerText.trim() : ''; }
    if (title) out.push({title, url: href.split('#')[0], location: loc});
  }
  return out;
}
"""

MAIN_TEXT_JS = "() => (document.querySelector('main, [role=main], article') || document.body).innerText"


class BrowserUnavailable(RuntimeError):
    pass


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None      # cheap: doesn't import the package


class Browser(Scraper):
    def __init__(self, cfg: dict, entry=None):
        super().__init__(cfg, entry)
        if not playwright_available():
            raise BrowserUnavailable("playwright is not installed (pip install -r requirements-browser.txt)")
        self.bc = cfg["browser"]
        self._detail = None

    # --------------------------------------------------------------
    def _run_steps(self, page) -> None:
        for step in self.entry.get("steps", []):
            try:
                if "click" in step:
                    page.click(step["click"], timeout=4000)
                elif "fill" in step:
                    page.fill(step["fill"][0], step["fill"][1], timeout=4000)
                elif "press" in step:
                    page.keyboard.press(step["press"])
                elif "wait" in step:
                    page.wait_for_timeout(int(step["wait"]))
            except Exception as e:  # cookie banners etc. are optional; don't fail the run on them
                log.debug("%s: step %s skipped (%s)", self.name, step, str(e)[:80])

    def _load_all(self, page) -> None:
        """Scroll so lazily-loaded result lists render."""
        for _ in range(4):
            page.mouse.wheel(0, 6000)
            page.wait_for_timeout(400)

    def fetch(self) -> Iterator[RawJob]:
        from playwright.sync_api import sync_playwright

        e = self.entry
        pattern = e["link_pattern"]
        kws = keywords_for(self.cfg)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, executable_path=self.bc.get("executable"),
                args=["--no-sandbox", "--disable-dev-shm-usage",      # /dev/shm is tiny on a Pi
                      "--disable-gpu", "--disable-extensions", "--mute-audio", "--no-first-run",
                      "--disable-background-networking", "--disable-sync", "--disable-translate",
                      "--renderer-process-limit=1",                     # one renderer: less RAM
                      "--js-flags=--max-old-space-size=192"],
            )
            ctx = browser.new_context(locale="en-GB", viewport={"width": 1280, "height": 800})
            # We only read text: don't download images, video, audio or fonts (saves RAM, CPU and bandwidth)
            ctx.route("**/*", lambda route: route.abort()
                      if route.request.resource_type in ("image", "media", "font") else route.continue_())
            page, self._detail = ctx.new_page(), ctx.new_page()
            try:
                for url in e.get("urls") or [e["url"]]:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2000)
                    self._run_steps(page)
                    seen: set[str] = set()
                    for _ in range(int(e.get("max_pages", 5))):
                        self._load_all(page)
                        found = page.evaluate(EXTRACT_JS, [pattern, kws])
                        fresh = [j for j in found if j["url"] not in seen]
                        if not fresh:
                            break
                        for j in fresh:
                            seen.add(j["url"])
                            yield RawJob(source="browser", origin=self.origin, company=self.name,
                                         title=j["title"], url=j["url"], location=j["location"],
                                         external_id=re.sub(r"\D", "", j["url"].split("?")[0])[-12:])
                        nxt = e.get("next")
                        if not nxt or not page.locator(nxt).first.is_visible():
                            break
                        page.locator(nxt).first.click()
                        polite_sleep(self.bc["delay_seconds"])
            finally:
                browser.close()
                self._detail = None

    def enrich(self, job: RawJob) -> None:
        if self._detail is None:
            return
        polite_sleep(self.bc["delay_seconds"])
        self._detail.goto(job.url, wait_until="domcontentloaded", timeout=45000)
        self._detail.wait_for_timeout(1500)
        text = self._detail.evaluate(MAIN_TEXT_JS)
        job.description = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not job.location:  # listing didn't show one: take the first line that names an NL place
            kws = keywords_for(self.cfg)
            for line in job.description.splitlines()[:60]:
                if len(line) < 120 and any(re.search(rf"(?<![\w]){re.escape(k)}(?![\w])", line, re.I) for k in kws):
                    job.location = line.strip()
                    break
