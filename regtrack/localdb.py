"""The PostgreSQL server on this machine (PG_BIN / PG_DATA in .env).

    python -m regtrack.cli db status      is it running?
    python -m regtrack.cli db start       start it (returns once it accepts connections)
    python -m regtrack.cli db stop

With PG_BIN empty these commands only say that it has to be set.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from regtrack.config import ROOT, get_settings

LOG = ROOT / "data" / "pglog" / "postgres.log"


def local_mode() -> bool:
    return get_settings().pg_bin is not None


def tool(name: str) -> str:
    """Full path of a PostgreSQL program (pg_ctl, pg_dump, pg_restore, psql)."""
    exe = name + (".exe" if os.name == "nt" else "")
    return str(get_settings().pg_bin / exe)


def _data() -> Path:
    data = get_settings().pg_data
    if data is None:
        raise RuntimeError("PG_DATA is not set in .env (the folder created by initdb)")
    return data


def status() -> bool:
    if not local_mode():
        return False
    return subprocess.run([tool("pg_ctl"), "-D", str(_data()), "status"], capture_output=True).returncode == 0


def start() -> str:
    if not local_mode():
        return "PG_BIN is not set in .env: the folder with pg_ctl, pg_dump… (README: Database)"
    if status():
        return f"already running ({_data()})"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    # Windows: a console without a window, in its own process group. With no console at all, pg_ctl's helper opens a
    # visible console window for the server, and closing that window (or Ctrl+C in it) stops the database.
    # No inherited handles either: the server outlives this terminal, and the caller does not hang.
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    r = subprocess.run(
        [tool("pg_ctl"), "-D", str(_data()), "-l", str(LOG), "-w", "-t", "60", "start"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    if r.returncode != 0 or not status():
        raise RuntimeError(f"the database did not start; see {LOG}")
    return f"started ({_data()}), log {LOG}"


def stop() -> str:
    if not local_mode():
        return "PG_BIN is not set in .env: the folder with pg_ctl, pg_dump… (README: Database)"
    if not status():
        return "not running"
    subprocess.run([tool("pg_ctl"), "-D", str(_data()), "-m", "fast", "-w", "stop"], check=True, capture_output=True)
    return "stopped"
