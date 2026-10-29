"""`python -m regtrack.cli llm-smoke` — test LM Studio the moment the URL arrives, on 10 documents only.

1. reachability + the models LM Studio serves; 2. one structured-output ping;
3. Qwen extraction (+ the identity/status/date double check) on 10 documents across classes — results are written
   like a normal pipeline run unless --dry-run;
4. embeddings for those documents' chunks: the dimension is checked against EMBED_DIM and the vector(N) column first
   (a mismatch stops before anything is written).
Exit code 0 = all good, 1 = something failed, 2 = LLM not reachable (nothing written).
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from regtrack import llm
from regtrack.config import get_settings
from regtrack.db import connect, vec_literal
from regtrack.pipeline import repo

CLASS_MIX = [  # (doc_class, how many) — notifications and AIS standards dominate the Qwen work
    ("NOTIFICATION_FINAL", 2),
    ("NOTIFICATION_DRAFT", 1),
    ("NOTIFICATION_ORDER", 1),
    ("NOTIFICATION_EXTENSION", 1),
    ("AIS_STANDARD", 2),
    ("AIS_AMENDMENT", 1),
    ("AIS_DRAFT", 1),
    ("CIRCULAR_OM", 1),
]


class _Ping(BaseModel):
    answer: str
    number: int


PICK_SQL = (
    """SELECT d.*, df.page_from, df.page_to, fo.checksum_sha256 AS sha256, fo.storage_path, fo.id AS file_id
               FROM ("""
    + repo.REG_SQL
    + """) d JOIN document_parts df ON df.regulation_id=d.id AND df.is_best_copy
               JOIN documents fo ON fo.id=df.document_id
               WHERE {cls} coalesce((d.extraction->>'llm_pending')::boolean, true)
                 AND d.canonical_id !~ '^(NOTIF|AIS-UNIDENTIFIED)-' AND coalesce(fo.text_layer, true)
                 AND d.doc_class <> 'OFF_TOPIC' AND NOT (d.id = ANY(%s))
               ORDER BY d.in_scope DESC NULLS LAST, d.doc_date DESC NULLS LAST, d.id LIMIT %s"""
)


def pick_documents(conn, n: int = 10) -> list[dict]:
    """A fixed mix of classes (newest, in-scope first), topped up from any pending document."""
    out: list[dict] = []
    for dc, k in CLASS_MIX:
        out += conn.execute(PICK_SQL.replace("{cls}", "d.doc_class=%s AND"), (dc, [d["id"] for d in out], k)).fetchall()
    if len(out) < n:
        out += conn.execute(PICK_SQL.replace("{cls}", ""), ([d["id"] for d in out], n - len(out))).fetchall()
    return out[:n]


def column_dim(conn) -> int | None:
    r = conn.execute(
        """SELECT atttypmod FROM pg_attribute WHERE attrelid='document_chunks'::regclass AND attname='embedding'"""
    ).fetchone()
    return r["atttypmod"] if r and r["atttypmod"] > 0 else None


def run(n: int = 10, dry_run: bool = False, max_chunks: int = 40) -> int:
    from regtrack.pipeline import extract as X
    from regtrack.pipeline.text import english_text, load_pages

    s = get_settings()
    print(
        f"LLM_BASE_URL={s.llm_base_url}  LLM_MODEL={s.llm_model}  EMBED_MODEL={s.embed_model}  EMBED_DIM={s.embed_dim}"
    )
    ok, detail = llm.reachable(force=True)
    print(f"[{'OK ' if ok else 'FAIL'}] reachable: {detail}")
    if not ok:
        print("LM Studio is not reachable - nothing was written. Set LLM_BASE_URL (ngrok URL + /v1) in .env and retry.")
        return 2
    failures = 0
    t = time.time()
    try:
        r = llm.structured(_Ping, "Reply in JSON.", "Return answer='pong' and number=42.", timeout=120)
        good = r.answer.lower().startswith("pong") and r.number == 42
        print(f"[{'OK ' if good else 'FAIL'}] structured output ({time.time() - t:.1f}s): {r!r}")
        failures += not good
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] structured output: {type(e).__name__}: {str(e)[:300]}")
        return 1

    with connect() as conn:
        docs = pick_documents(conn, n)
        print(f"\nQwen extraction on {len(docs)} documents{' (dry run: nothing written)' if dry_run else ''}:")
        agree = {"number": [], "date": [], "status": []}
        for d in docs:
            pages = load_pages(d["sha256"])
            eng = english_text(pages, d["page_from"], d["page_to"])
            t = time.time()
            try:
                res = X.llm_extract(d, eng)
                filled = sorted(k for k, v in res.data.model_dump(exclude_none=True).items() if v not in ([], {}))
                check = X.double_check(d, eng, d["data"] or {})
                for k, v in check.items():
                    if v is not None:
                        agree[k].append(v)
                print(
                    f"  [OK ] {d['canonical_id']:<28} {d['doc_class']:<22} {time.time() - t:5.1f}s  "
                    f"subject={res.subject!r:.60}  categories={res.vehicle_categories}  fields={len(filled)}  "
                    f"identity-check={check}"
                )
                if not dry_run:
                    df = {"page_from": d["page_from"], "page_to": d["page_to"], "is_best_copy": True}
                    doc = repo.get_document(conn, d["id"])
                    X.extract_document(
                        conn,
                        doc,
                        df,
                        {"sha256": d["sha256"], "storage_path": d["storage_path"], "id": d["file_id"]},
                        pages,
                        [],
                        use_llm=True,
                    )
                    conn.commit()
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  [FAIL] {d['canonical_id']:<28} {type(e).__name__}: {str(e)[:200]}")
        for k, v in agree.items():
            if v:
                print(f"  agreement {k}: {sum(v)}/{len(v)}")

        print("\nEmbeddings:")
        chunks = conn.execute(
            "SELECT id, heading, content FROM document_chunks WHERE regulation_id = ANY(%s) AND NOT is_boilerplate "
            "ORDER BY id LIMIT %s",
            ([d["id"] for d in docs], max_chunks),
        ).fetchall()
        if not chunks:
            print("  no chunks for these documents")
            return 1 if failures else 0
        try:
            t = time.time()
            vecs = llm.embed([(c["heading"] + "\n" if c["heading"] else "") + c["content"] for c in chunks])
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {type(e).__name__}: {str(e)[:300]}")
            return 1
        dim, col = len(vecs[0]), column_dim(conn)
        print(
            f"  {len(vecs)} chunks in {time.time() - t:.1f}s, dimension {dim} (EMBED_DIM={s.embed_dim}, column vector({col}))"
        )
        if dim != s.embed_dim or (col and dim != col):
            print(
                f"  [FAIL] dimension mismatch: set EMBED_DIM={dim} and add db/migrations/0002_embedding_dim.sql "
                f"(ALTER TABLE chunk ALTER COLUMN embedding TYPE vector({dim}); recreate the HNSW index). Nothing written."
            )
            return 1
        if not dry_run:
            for c, v in zip(chunks, vecs, strict=True):
                conn.execute("UPDATE chunk SET embedding=%s::vector WHERE id=%s", (vec_literal(v), c["id"]))
            conn.commit()
            print(f"  [OK ] wrote {len(vecs)} embeddings")
    print(
        "\nSmoke test",
        "PASSED" if not failures else f"had {failures} failure(s)",
        "- next: python -m regtrack.cli run  (processes everything pending)",
    )
    return 1 if failures else 0
