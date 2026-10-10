"""Built-in scheduler: the web server scrapes on the interval chosen on the Schedule page."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)


def is_due(now: datetime, last_started: Optional[str], every_hours: float, enabled: bool) -> bool:
    """True when automatic scraping is on and the last run is older than the interval (or never happened)."""
    if not enabled:
        return False
    if not last_started:
        return True
    last = datetime.fromisoformat(last_started)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last >= timedelta(hours=every_hours)


def start(cfg: dict, last_started: Callable[[], Optional[str]], trigger: Callable[[], bool],
          first_delay: float = 45, tick: float = 60) -> threading.Thread:
    """Poll once a minute (so a changed interval takes effect quickly) and trigger a scrape when due."""
    def loop():
        time.sleep(first_delay)
        while True:
            try:
                s = cfg["schedule"]
                if is_due(datetime.now(timezone.utc), last_started(), s["every_hours"], s["enabled"]):
                    log.info("scheduled scrape starting")
                    trigger()
            except Exception:
                log.exception("scheduler error")
            time.sleep(tick)

    t = threading.Thread(target=loop, name="scheduler", daemon=True)
    t.start()
    return t
