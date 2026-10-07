"""6-hour schedule: each source crawls on its own interval (source.schedule_hours); every crawl is followed by
a pipeline run that moves new files through all stages. Runs never fail because the LLM is down.

    python -m regtrack.cli schedule          # blocking APScheduler loop
    python -m regtrack.cli crawl MORTH_API   # one run now (what Windows Task Scheduler calls)
"""

from __future__ import annotations

import logging
import threading

from regtrack.db import connect

log = logging.getLogger(__name__)
_lock = threading.Lock()  # one pipeline run at a time


def crawl_source(code: str) -> dict:
    if code == "MORTH_API":
        from regtrack.sources.morth import crawl
    elif code == "ARAI_AIS":
        from regtrack.sources.arai import crawl
    elif code == "EGAZETTE":
        from regtrack.sources.egazette import crawl
    elif code == "INDIACODE":
        from regtrack.sources.indiacode import crawl
    else:
        raise ValueError(f"no crawler for {code}")
    return crawl()


def run_source(code: str, process: bool = True) -> dict:
    out = {"crawl": crawl_source(code)}
    if process:
        with _lock:
            from regtrack.pipeline.runner import run_pipeline

            out["pipeline"] = run_pipeline()
    return out


def main() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="Asia/Kolkata")
    with connect() as conn:
        sources = conn.execute("SELECT code, schedule_hours FROM source WHERE schedule_hours > 0 "
                               "AND code IN ('MORTH_API','ARAI_AIS','EGAZETTE','INDIACODE') ORDER BY id").fetchall()
    for i, s in enumerate(sources):
        sched.add_job(run_source, "interval", hours=min(s["schedule_hours"], 6), args=[s["code"]], id=s["code"],
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=_staggered(i))
        log.info("scheduled %s every %sh", s["code"], s["schedule_hours"])
    # pipeline catch-up every hour: picks up files left behind while the LLM / embeddings were offline
    sched.add_job(_catch_up, "interval", hours=1, id="pipeline", max_instances=1, coalesce=True)
    sched.start()


def _staggered(i: int):
    from datetime import datetime, timedelta

    return datetime.now() + timedelta(minutes=2 + 10 * i)


def _catch_up() -> None:
    if _lock.acquire(blocking=False):
        try:
            from regtrack.pipeline.runner import run_pipeline

            run_pipeline()
        finally:
            _lock.release()
