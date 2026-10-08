"""Command line: python -m regtrack.cli <command>.

  check                 DB / pgvector / LLM / structured output / embedding dimension
  migrate               apply db/migrations + db/seeds (idempotent)
  schemas               export JSON Schemas from the Pydantic models
  import-seed           Phase 2: import SEED_CORPUS_DIR (read-only) into storage + DB
  run [--stage S] [--limit N]   run pipeline stages on pending files (resumable)
  crawl [SOURCE]        run live crawlers once (MORTH_API, ARAI_AIS, EGAZETTE, INDIACODE)
  schedule              start the 6-hour scheduler (blocking)
  report                write reports/VALIDATION_REPORT.md
  api                   start the read-only FastAPI server
  storage-upload [--limit N] [--switch]   one-time upload of local originals to S3/MinIO
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


def cmd_migrate(_args) -> int:
    from regtrack.migrate import migrate

    for line in migrate():
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


def cmd_crawl(args) -> int:
    from regtrack.scheduler import run_source

    for code in args.sources or ["MORTH_API", "ARAI_AIS", "EGAZETTE", "INDIACODE"]:
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


def cmd_storage_upload(args) -> int:
    from regtrack.storage_upload import upload_all

    print(upload_all(limit=args.limit, switch=args.switch))
    if args.switch:
        print("storage_path now points to S3 for uploaded objects: set STORAGE_BACKEND=s3 in .env")
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
    sub.add_parser("migrate").set_defaults(fn=cmd_migrate)
    sub.add_parser("schemas").set_defaults(fn=cmd_schemas)
    sp = sub.add_parser("import-seed")
    sp.add_argument("--limit", type=int)
    sp.set_defaults(fn=cmd_import_seed)
    sp = sub.add_parser("run")
    sp.add_argument("--stage", action="append", help="text|classify|split|extract|link|chunk|embed (repeatable)")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--workers", type=int, default=2)
    sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("crawl")
    sp.add_argument("sources", nargs="*")
    sp.add_argument("--no-process", action="store_true")
    sp.set_defaults(fn=cmd_crawl)
    sub.add_parser("schedule").set_defaults(fn=cmd_schedule)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    sp = sub.add_parser("storage-upload", help="one-time upload of local originals to S3/MinIO")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--switch", action="store_true", help="rewrite file_object.storage_path to s3:// URIs")
    sp.set_defaults(fn=cmd_storage_upload)
    sp = sub.add_parser("api")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    sp.set_defaults(fn=cmd_api)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
