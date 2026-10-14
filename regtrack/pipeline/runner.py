"""Pipeline runner: moves every file forward from its file_object.stage (the resume point).

Each file/stage runs in its own transaction; a failure records stage_error and the run continues.
Stages run over all pending files before the next stage starts (classification settles best copies before
extraction; link replays notifications in date order so mandate versions come out right).
Only files of the current country (regtrack/country.py) are picked; other countries' files keep their stage.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from regtrack import country
from regtrack.db import connect
from regtrack.pipeline import chunk as C
from regtrack.pipeline import events as E
from regtrack.pipeline import extract as X
from regtrack.pipeline import link as L
from regtrack.pipeline import resolve as R
from regtrack.pipeline import stages as S

log = logging.getLogger(__name__)
ALL_STAGES = ["text", "classify", "extract", "link", "chunk", "embed"]
SOURCE_STAGE = {"text": "downloaded", "classify": "text", "extract": "classified", "link": "parsed", "chunk": "linked"}


def _files(conn, stage: str, limit: int | None, order: str = "f.id") -> list[dict]:
    q = (f"SELECT f.* FROM file_object f WHERE f.stage=%s AND {country.sql('f')} ORDER BY {order}"
         + (" LIMIT %s" if limit else ""))
    return conn.execute(q, (stage, limit) if limit else (stage,)).fetchall()


def _run_one(fn, file_id: int) -> tuple[int, str | None]:
    with connect() as conn:
        f = conn.execute("SELECT * FROM file_object WHERE id=%s", (file_id,)).fetchone()
        try:
            fn(conn, f)
            conn.commit()
            return file_id, None
        except Exception as e:  # noqa: BLE001
            conn.rollback()
            msg = f"{type(e).__name__}: {str(e)[:400]}"
            log.exception("file %s failed in %s", file_id, fn.__name__)
            conn.execute("UPDATE file_object SET stage_error=%s WHERE id=%s", (msg, file_id))
            conn.commit()
            return file_id, msg


def _text_worker(file_id: int) -> tuple[int, str | None]:
    return _run_one(S.stage_text, file_id)


def run_stage(stage: str, limit: int | None = None, workers: int = 1) -> dict:
    t0 = time.time()
    ok = err = skipped = 0
    with connect() as conn:
        if stage == "link":
            # notifications in date order so mandate replays are chronological
            files = conn.execute(
                """SELECT f.id FROM file_object f LEFT JOIN document_file df ON df.file_id=f.id
                   LEFT JOIN document d ON d.id=df.document_id WHERE f.stage='parsed' AND """ + country.sql("f") + """
                   GROUP BY f.id ORDER BY min(d.doc_date) NULLS LAST, f.id""" + (f" LIMIT {int(limit)}" if limit else "")
            ).fetchall()
        else:
            files = _files(conn, SOURCE_STAGE[stage], limit)
        if stage == "classify":
            ready = [f for f in files if S.ready_for_classify(f)]
            skipped = len(files) - len(ready)
            files = ready
    ids = [f["id"] for f in files]
    fn = {"text": S.stage_text, "classify": S.stage_classify, "extract": X.stage_extract, "link": L.stage_link,
          "chunk": C.stage_chunk}[stage]
    if stage == "text" and workers > 1 and len(ids) > 1:
        with ProcessPoolExecutor(workers) as ex:
            for fu in as_completed([ex.submit(_text_worker, i) for i in ids]):
                _, e = fu.result()
                ok, err = ok + (e is None), err + (e is not None)
    else:
        for i, fid in enumerate(ids):
            _, e = _run_one(fn, fid)
            ok, err = ok + (e is None), err + (e is not None)
            if (i + 1) % 200 == 0:
                log.info("%s: %d/%d", stage, i + 1, len(ids))
    return {"stage": stage, "files": len(ids), "ok": ok, "errors": err, "waiting": skipped,
            "seconds": round(time.time() - t0, 1)}


def post_run() -> dict:
    with connect() as conn:
        out = {"refs_resolved": L.resolve_refs(conn)}
        S.tap_best_copies(conn)
        out["chunk_filters_synced"] = C.sync_chunk_filters(conn)
        out["flags_resolved"] = R.resolve_all(conn)
        conn.commit()
        out["llm_enriched"] = X.enrich_pending(conn)
        conn.commit()
        out["events"] = E.emit_events(conn)
        conn.commit()
    return out


def run_embed(limit: int | None = None) -> dict:
    with connect() as conn:
        n = C.embed_pending(conn, limit=limit)
        moved = C.advance_embedded(conn)
        conn.commit()
    return {"stage": "embed", "embedded_chunks": n, "files_done": moved}


def run_pipeline(stages: list[str] | None = None, limit: int | None = None, workers: int = 2) -> list[dict]:
    stages = stages or ALL_STAGES
    out = []
    for st in ALL_STAGES:
        if st not in stages:
            continue
        r = run_embed(limit) if st == "embed" else run_stage(st, limit, workers)
        log.info("%s", r)
        out.append(r)
    out.append(post_run())
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for r in run_pipeline():
        print(r)
