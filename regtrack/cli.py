"""Command line: python -m regtrack.cli <command>.

  check                 DB / pgvector / LLM / structured output / embedding dimension
  migrate               apply db/migrations + db/seeds (idempotent)
  schemas               export JSON Schemas from the Pydantic models
  import-seed           Phase 2: import SEED_CORPUS_DIR (read-only) into storage + DB
  run [--stage S] [--limit N]   run pipeline stages on pending files (resumable)
  crawl [SOURCE]        run the current country's live crawlers once (India: MORTH_API, ARAI_AIS, EGAZETTE, INDIACODE)
  schedule              start the 6-hour scheduler (blocking)
  rederive-mandates [--doc ID] [--apply]   after a mandate-parser fix: correct open mandate versions (dry run first)
  report                write reports/VALIDATION_REPORT.md
  api                   start the read-only FastAPI server
  db start|stop|status  the local PostgreSQL server (PG_BIN / PG_DATA in .env; not used with Docker)
  storage-upload [--limit N] [--switch]   one-time upload of local originals to S3/MinIO
  snapshot-export [--with-files]          database dump (+ files zip) to share with a collaborator
  snapshot-import FILE --yes              load a .dump (replaces the database) or a files .zip
"""

from __future__ import annotations

import argparse
import logging
import sys

from pydantic import BaseModel


class _Ping(BaseModel):
    answer: str
    number: int


def cmd_check(_args) -> int:
    from regtrack import llm
    from regtrack.config import get_settings
    from regtrack.db import connect, is_reachable, pgvector_installed

    s = get_settings()
    ok_all = True

    def line(name: str, ok: bool, detail: str) -> None:
        nonlocal ok_all
        ok_all &= ok
        print(f"[{'OK ' if ok else 'FAIL'}] {name:<26} {detail}")

    ok, detail = is_reachable()
    line("DB reachable", ok, detail)
    if ok:
        with connect(autocommit=True) as c:
            v = pgvector_installed(c)
        line("pgvector installed", bool(v) and "not yet" not in (v or ""), v or "not available")
    else:
        line("pgvector installed", False, "skipped (no DB)")

    ok, detail = llm.reachable(force=True)
    line("LLM reachable", ok, f"{s.llm_base_url} -> {detail}")
    if ok:
        try:
            r = llm.structured(_Ping, "Reply in JSON.", "Return answer='pong' and number=42.", timeout=120)
            line("structured output", r.answer.lower().startswith("pong") and r.number == 42, repr(r))
        except Exception as e:  # noqa: BLE001
            line("structured output", False, f"{type(e).__name__}: {str(e)[:200]}")
        try:
            vec = llm.embed(["seat belt reminder for M1 vehicles"])[0]
            line("embedding", True, f"model={s.embed_model} dim={len(vec)} (EMBED_DIM={s.embed_dim})")
            if len(vec) != s.embed_dim:
                print(f"  !! EMBED_DIM={s.embed_dim} but the model returns {len(vec)}: update .env and vector(N)")
                ok_all = False
        except Exception as e:  # noqa: BLE001
            line("embedding", False, f"{type(e).__name__}: {str(e)[:200]}")
    else:
        line("structured output", False, "skipped (LLM unreachable)")
        line("embedding", False, "skipped (LLM unreachable)")
    print(f"STORAGE_DIR={s.storage_dir}  SEED_CORPUS_DIR={s.seed_corpus_dir} (exists={s.seed_corpus_dir.exists()})")
    return 0 if ok_all else 1


def cmd_migrate(args) -> int:
    from regtrack.migrate import migrate

    for line in migrate(until=args.until):
        print(line)
    return 0


def cmd_schemas(_args) -> int:
    from regtrack.models import export_schemas

    print(f"wrote {len(export_schemas())} schema files")
    return 0


def cmd_import_seed(args) -> int:
    from regtrack.sources.seed_corpus import import_seed

    print(import_seed(limit=args.limit))
    return 0


def cmd_run(args) -> int:
    from regtrack.pipeline.runner import run_pipeline

    print(run_pipeline(stages=args.stage, limit=args.limit, workers=args.workers))
    return 0


def cmd_rederive_mandates(args) -> int:
    from regtrack.db import connect
    from regtrack.pipeline.link import rederive_mandates

    with connect() as conn:
        out = rederive_mandates(conn, apply=args.apply, docs=args.doc or None)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    for o in out:
        print(o)
    print(f"{len(out)} change(s)" + ("" if args.apply else " (dry run: --apply to write)"))
    return 0


def cmd_crawl(args) -> int:
    from regtrack.scheduler import crawlers, run_source

    for code in args.sources or list(crawlers()):
        print(code, run_source(code, process=not args.no_process))
    return 0


def cmd_schedule(_args) -> int:
    from regtrack.scheduler import main as sched_main

    sched_main()
    return 0


def cmd_report(_args) -> int:
    from regtrack.pipeline.report import write_validation_report

    print(write_validation_report())
    return 0


def cmd_llm_smoke(args) -> int:
    from regtrack.llm_smoke import run

    return run(n=args.n, dry_run=args.dry_run)


def cmd_resolve_flags(_args) -> int:
    from regtrack.db import connect
    from regtrack.pipeline.resolve import resolve_all

    with connect() as conn:
        print(resolve_all(conn))
        conn.commit()
    return 0


def cmd_storage_upload(args) -> int:
    from regtrack.storage_upload import upload_all

    print(upload_all(limit=args.limit, switch=args.switch))
    if args.switch:
        print("storage_path now points to S3 for uploaded objects: set STORAGE_BACKEND=s3 in .env")
    return 0


def cmd_snapshot_export(args) -> int:
    from regtrack.snapshot import export

    for path in export(with_files=args.with_files):
        print(f"{path}  ({path.stat().st_size / 1e6:,.0f} MB)")
    return 0


def cmd_snapshot_import(args) -> int:
    from pathlib import Path

    from regtrack.snapshot import import_

    path = Path(args.file)
    if not path.exists():
        print(f"not found: {path}")
        return 1
    if path.suffix.lower() != ".zip" and not args.yes:
        print("This replaces everything in the local database with the snapshot. Run again with --yes to continue.")
        return 1
    print(import_(path))
    return 0


def cmd_db(args) -> int:
    from regtrack import localdb

    if args.action == "status":
        if not localdb.local_mode():
            print("PG_BIN is not set: the database runs in Docker")
            return 0
        running = localdb.status()
        print("running" if running else "not running")
        return 0 if running else 1
    print(localdb.start() if args.action == "start" else localdb.stop())
    return 0


def cmd_api(args) -> int:
    import uvicorn

    uvicorn.run("regtrack.api.app:app", host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    p = argparse.ArgumentParser(prog="regtrack")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sp = sub.add_parser("migrate")
    sp.add_argument("--until", type=int, help="apply files up to this number only (e.g. 10)")
    sp.set_defaults(fn=cmd_migrate)
    sub.add_parser("schemas").set_defaults(fn=cmd_schemas)
    sp = sub.add_parser("import-seed")
    sp.add_argument("--limit", type=int)
    sp.set_defaults(fn=cmd_import_seed)
    sp = sub.add_parser("run")
    sp.add_argument("--stage", action="append", help="text|classify|split|extract|link|chunk|embed (repeatable)")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--workers", type=int, default=2)
    sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("rederive-mandates")
    sp.add_argument("--doc", action="append", help="limit the rule-obligation pass to this notification (repeatable)")
    sp.add_argument("--apply", action="store_true")
    sp.set_defaults(fn=cmd_rederive_mandates)
    sp = sub.add_parser("crawl")
    sp.add_argument("sources", nargs="*")
    sp.add_argument("--no-process", action="store_true")
    sp.set_defaults(fn=cmd_crawl)
    sub.add_parser("schedule").set_defaults(fn=cmd_schedule)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sp = sub.add_parser("llm-smoke", help="Qwen extraction + embeddings on 10 documents (test LM Studio)")
    sp.add_argument("--n", type=int, default=10)
    sp.add_argument("--dry-run", action="store_true", help="call the LLM but write nothing")
    sp.set_defaults(fn=cmd_llm_smoke)
    sub.add_parser("resolve-flags", help="resolve quality flags whose evidence settles them").set_defaults(
        fn=cmd_resolve_flags)
    sp = sub.add_parser("storage-upload", help="one-time upload of local originals to S3/MinIO")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--switch", action="store_true", help="rewrite documents.storage_path to s3:// URIs")
    sp.set_defaults(fn=cmd_storage_upload)
    sp = sub.add_parser("snapshot-export", help="database dump (+ files zip) to share with a collaborator")
    sp.add_argument("--with-files", action="store_true", help="also zip the stored originals and page text")
    sp.set_defaults(fn=cmd_snapshot_export)
    sp = sub.add_parser("snapshot-import", help="load a snapshot .dump (replaces the database) or files .zip")
    sp.add_argument("file")
    sp.add_argument("--yes", action="store_true", help="confirm replacing the database")
    sp.set_defaults(fn=cmd_snapshot_import)
    sp = sub.add_parser("db", help="start, stop or check the local PostgreSQL server")
    sp.add_argument("action", choices=["start", "stop", "status"])
    sp.set_defaults(fn=cmd_db)
    sp = sub.add_parser("api")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_api)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
