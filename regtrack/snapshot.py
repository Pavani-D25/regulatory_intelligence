"""Share the database (and optionally the stored files) with a collaborator, so they do not have to rebuild it.

  python -m regtrack.cli snapshot-export                    -> data/snapshots/regtrack_<date>.dump   (database only)
  python -m regtrack.cli snapshot-export --with-files       -> also regtrack_files_<date>.zip (originals + page text)
  python -m regtrack.cli snapshot-import <file.dump|file.zip> --yes

The database dump is enough for the portal, search and Ask AI. The files zip adds "Open original PDF" and lets the
pipeline re-read documents. Stored file paths from another machine are found again by their sha256 name
(storage.open_local), so the dump works in any folder. Uses the local pg_dump / pg_restore when PostgreSQL runs on
the machine (PG_BIN in .env, regtrack/localdb.py), otherwise the ones inside the Docker container.
"""

from __future__ import annotations

import os
import subprocess
import zipfile
from datetime import date
from pathlib import Path

from regtrack import localdb
from regtrack.config import ROOT, get_settings

CONTAINER = os.getenv("REGTRACK_DB_CONTAINER", "regtrack-db")
SNAP_DIR = ROOT / "data" / "snapshots"


def _pg(program: str, args: list[str], **kw) -> subprocess.CompletedProcess:
    """Run pg_dump / pg_restore against the regtrack database: local programs, or inside the Docker container."""
    if localdb.local_mode():
        cmd = [localdb.tool(program), "--dbname", get_settings().psycopg_dsn, *args]
    else:
        cmd = ["docker", "exec", "-i", CONTAINER, program, "-U", "regtrack", "--dbname", "regtrack", *args]
    return subprocess.run(cmd, check=True, **kw)


def export(with_files: bool = False, out_dir: Path = SNAP_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = out_dir / f"regtrack_{date.today():%Y-%m-%d}.dump"
    with dump.open("wb") as fh:  # streamed: the dump never sits in memory
        _pg("pg_dump", ["-Fc", "-Z", "6"], stdout=fh)
    out = [dump]
    if with_files:
        s = get_settings()
        z = out_dir / f"regtrack_files_{date.today():%Y-%m-%d}.zip"
        with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:  # PDFs are compressed already
            for base, arc in ((s.storage_dir, "raw"), (s.text_dir, "text")):
                if base.exists():
                    for p in base.rglob("*"):
                        if p.is_file() and not p.name.startswith(".tmp"):
                            zf.write(p, f"{arc}/{p.relative_to(base).as_posix()}")
        out.append(z)
    return out


def import_(path: Path) -> str:
    if path.suffix.lower() == ".zip":
        s = get_settings()
        n = 0
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                top, _, rest = info.filename.partition("/")
                if info.is_dir() or top not in ("raw", "text") or not rest or ".." in rest.split("/"):
                    continue
                dst = (s.storage_dir if top == "raw" else s.text_dir) / rest
                if dst.exists():
                    continue  # write-once: never overwrite a stored original
                dst.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, dst.open("wb") as fh:
                    while chunk := src.read(1 << 20):
                        fh.write(chunk)
                n += 1
        return f"{n} files added under {s.storage_dir.parent}"
    with path.open("rb") as fh:
        # --clean replaces what is in the database with the snapshot; ownership is not carried over
        _pg("pg_restore", ["--clean", "--if-exists", "--no-owner", "--single-transaction"], stdin=fh)
    return f"database restored from {path.name}"
