"""Built-in scheduler: the web server keeps every source fresh in the background, one at a time.

Why "trickle" instead of one big scrape: the target is a Raspberry Pi that also runs other services.
Spreading the work (e.g. 22 sources over 24 hours = one source roughly every hour) means CPU and RAM
never spike, and only one source is ever running. A source that has never been scraped (fresh install,
newly added company) is done right away, back to back, so the dashboard fills quickly.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

RETRY_AFTER_FAILURE_HOURS = 6  # a failed source is retried sooner than a full cycle, but not hammered


def _dt(iso: str) -> datetime:
    d = datetime.fromisoformat(iso)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def pick_next(now: datetime, sources: list[str], last: dict[str, tuple[str, bool]], cycle_hours: float,
              gap_seconds: float, spread: bool = True) -> Optional[str]:
    """Which source to scrape right now, or None.

    * every source is refreshed once per ``cycle_hours`` (sooner after a failure);
    * never-scraped sources go first and failed ones are retried; both only wait ``gap_seconds``;
    * routine refreshes, if ``spread``, are spaced ``cycle / number-of-sources`` apart.
    """
    if not sources:
        return None
    cycle = timedelta(hours=cycle_hours)
    due: list[tuple[datetime, str]] = []
    for name in sources:
        if name not in last:
            due.append((datetime.min.replace(tzinfo=timezone.utc), name))  # never run: most overdue
            continue
        started, ok = last[name]
        wait = cycle if ok else min(cycle, timedelta(hours=RETRY_AFTER_FAILURE_HOURS))
        if now - _dt(started) >= wait:
            due.append((_dt(started), name))
    if not due:
        return None
    due.sort()
    name = due[0][1]
    latest_any = max((_dt(s) for s, _ in last.values()), default=None)
    healthy = name in last and last[name][1]  # only routine refreshes of working sources are spaced out
    slot = cycle / len(sources) if (healthy and spread) else timedelta(0)
    gap = max(timedelta(seconds=gap_seconds), slot)
    if latest_any is not None and now - latest_any < gap:
        return None
    return name


def start(cfg: dict, sources: Callable[[], list[str]], last_runs: Callable[[], dict],
          trigger: Callable[[str], bool], first_delay: float = 45, tick: float = 60) -> threading.Thread:
    """Check once a minute (so changed settings take effect quickly) and run at most one source per check."""
    def loop():
        time.sleep(first_delay)
        while True:
            try:
                s = cfg["schedule"]
                if s["enabled"]:
                    name = pick_next(datetime.now(timezone.utc), sources(), last_runs(), s["every_hours"],
                                     s["pause_between_sources"], s.get("spread", True))
                    if name:
                        trigger(name)  # returns False if a scrape is already running; we simply ask again next tick
            except Exception:
                log.exception("scheduler error")
            time.sleep(tick)

    t = threading.Thread(target=loop, name="scheduler", daemon=True)
    t.start()
    return t
