"""6-hour schedule: each source crawls on its own interval (source.schedule_hours); every crawl is followed by
a pipeline run that moves new files through all stages. Runs never fail because the LLM is down.

    python -m regtrack.cli schedule          # blocking APScheduler loop
    python -m regtrack.cli crawl MORTH_API   # one run now (what Windows Task Scheduler calls)

The loop writes app_settings 'scheduler_heartbeat' every 5 minutes so the portal can show whether it is alive, and
skips scheduled crawls while app_settings 'auto_sync' is 'false' (the Admin switch). Manual runs are not affected.
Only the current country's sources (regtrack/country.py) are scheduled or crawled.
"""

from __future__ import annotations

import logging
import threading

from regtrack import country
from regtrack.db import connect

log = logging.getLogger(__name__)
_lock = threading.Lock()  # one pipeline run at a time


# source code -> module in regtrack.sources, per country (Thai crawlers are added here when they exist)
CRAWLERS_BY_COUNTRY: dict[str, dict[str, str]] = {
    "IN": {"MORTH_API": "morth", "ARAI_AIS": "arai", "EGAZETTE": "egazette", "INDIACODE": "indiacode"},
    "TH": {"TH_TISI_MANDATORY": "thailand_tisi", "TH_LOCAL": "local_import"},
    # one module for the five JPJ / DOE pages: its crawl(code) takes the source code
    "MY": {c: "malaysia" for c in ("MY_JPJ_VTA", "MY_JPJ_CTA", "MY_JPJ_AED", "MY_DOE_EMISSION", "MY_DOE_VTA_GUIDE",
                                     "MY_JPJ_ACTS", "MY_DOE_REGS")} | {"MY_LOCAL": "local_import"},
}
CRAWLERS = CRAWLERS_BY_COUNTRY["IN"]  # India's; code that runs crawls uses crawlers()


def crawlers(cc: str | None = None) -> dict[str, str]:
    """The crawlers of the current country (or of `cc`)."""
    return CRAWLERS_BY_COUNTRY.get(country.code(cc), {})
HEARTBEAT_MIN = 5


def crawl_source(code: str, cc: str | None = None) -> dict:
    mods = crawlers(cc)
    if code not in mods:
        raise ValueError(f"no crawler for {code} in country {country.code(cc)}")
    import importlib

    mod = importlib.import_module(f"regtrack.sources.{mods[code]}")
    return mod.crawl(code) if getattr(mod, "CRAWLS_BY_CODE", False) else mod.crawl()


PIPELINE_LOCK = 774201  # pg advisory lock: one pipeline run at a time across processes (scheduler, API sync)


def run_pipeline_locked() -> dict:
    with _lock, connect() as lk:
        from regtrack.pipeline.runner import run_pipeline

        lk.execute("SELECT pg_advisory_lock(%s)", (PIPELINE_LOCK,))
        try:
            return run_pipeline()
        finally:
            lk.execute("SELECT pg_advisory_unlock(%s)", (PIPELINE_LOCK,))


def run_source(code: str, process: bool = True, cc: str | None = None) -> dict:
    out = {"crawl": crawl_source(code, cc)}
    if process:
        out["pipeline"] = run_pipeline_locked()
    return out


def run_all(on_step=None, cc: str | None = None) -> dict:
    """Crawl every source one after another (a failing source does not stop the others), then one pipeline run."""
    out: dict = {"crawl": {}, "errors": {}}
    for code in crawlers(cc):
        if on_step:
            on_step(code)
        try:
            out["crawl"][code] = crawl_source(code, cc)
        except Exception as e:  # noqa: BLE001
            log.exception("crawl %s failed", code)
            out["errors"][code] = f"{type(e).__name__}: {e}"[:300]
    if on_step:
        on_step("pipeline")
    out["pipeline"] = run_pipeline_locked()
    return out


def main() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    sched = BlockingScheduler(timezone="Asia/Kolkata")
    with connect() as conn:
        sources = conn.execute("SELECT code, sync_frequency_minutes FROM sources WHERE sync_frequency_minutes > 0 "
                               f"AND is_active AND {country.region_sql()} AND code = ANY(%s) ORDER BY id",
                               (list(crawlers()),)).fetchall()
    for i, s in enumerate(sources):
        hours = min(s["sync_frequency_minutes"] / 60, 6)
        sched.add_job(_scheduled_run, "interval", hours=hours, args=[s["code"]], id=s["code"],
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=_staggered(i))
        log.info("scheduled %s every %sh", s["code"], hours)
    # pipeline catch-up every hour: picks up files left behind while the LLM / embeddings were offline
    sched.add_job(_catch_up, "interval", hours=1, id="pipeline", max_instances=1, coalesce=True)
    # scheduled reports (portal: Reports > Schedules) whose date has come
    sched.add_job(_reports, "interval", hours=1, id="reports", max_instances=1, coalesce=True, next_run_time=_staggered(-2))
    sched.add_job(heartbeat, "interval", minutes=HEARTBEAT_MIN, id="heartbeat", next_run_time=_staggered(-1))
    sched.start()


def _reports() -> None:
    from regtrack.api.workspace import run_due_schedules

    try:
        for name in run_due_schedules():
            log.info("scheduled report written: %s", name)
    except Exception:  # noqa: BLE001  a report failure must not stop the scheduler
        log.exception("scheduled reports failed")


def heartbeat() -> None:
    with connect() as conn:
        conn.execute("INSERT INTO app_settings (key, value) VALUES ('scheduler_heartbeat', to_jsonb(now()::text)) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value")
        conn.commit()


def auto_sync_enabled() -> bool:
    with connect() as conn:
        r = conn.execute("SELECT value #>> '{}' AS value FROM app_settings WHERE key='auto_sync'").fetchone()
    return not r or r["value"] != "false"


def _scheduled_run(code: str) -> None:
    if not auto_sync_enabled():
        log.info("auto_sync is off: skipping scheduled crawl of %s", code)
        return
    run_source(code)


def _staggered(i: int):
    from datetime import datetime, timedelta

    return datetime.now() + timedelta(minutes=2 + 10 * i) if i >= 0 else datetime.now()


def _catch_up() -> None:
    if _lock.acquire(blocking=False):
        try:
            with connect() as lk:
                if not lk.execute("SELECT pg_try_advisory_lock(%s) AS ok", (PIPELINE_LOCK,)).fetchone()["ok"]:
                    return
                try:
                    from regtrack.pipeline.runner import run_pipeline

                    run_pipeline()
                finally:
                    lk.execute("SELECT pg_advisory_unlock(%s)", (PIPELINE_LOCK,))
        finally:
            _lock.release()
