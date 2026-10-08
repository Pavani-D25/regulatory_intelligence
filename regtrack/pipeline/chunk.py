"""Chunk + embed: 'linked' -> 'chunked' -> 'embedded' -> 'done'.

Clause-level chunks from English pages, split at clause numbers (1, 1.2, 6.12.3), ANNEX headings and
notification paragraphs. Boilerplate (committee lists, status charts, Gazette mastheads, printer lines) is kept
but flagged. Filter columns are copied from the document so vector search can filter without joins.
OFF_TOPIC documents get no chunks. Hindi is never embedded.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

import psycopg

from regtrack import llm
from regtrack.db import vec_literal
from regtrack.models.enums import DocClass
from regtrack.pipeline.dbutil import set_stage
from regtrack.pipeline.text import PageText, load_pages

log = logging.getLogger(__name__)
MAX_CHARS = 1800
MIN_CHARS = 120
CLAUSE = re.compile(r"^\s*((?:\d{1,2}\.){0,4}\d{1,2}\.?)\s+([A-Z][^\n]{2,120})?", re.M)
ANNEX = re.compile(r"^\s*(ANNEX(?:URE)?\s*[\-:]?\s*[A-Z0-9]{1,3})\b[^\n]*", re.M | re.I)
NOTIF_PARA = re.compile(r"^\s*(\(\d{1,2}\)|\d{1,2}\.)\s+", re.M)
BOILER = re.compile(r"composition\s+of\s+(?:the\s+)?(?:AISC|committee|panel)|status\s+chart\s+of\s+the\s+standard|"
                    r"members?\s+of\s+(?:the\s+)?(?:AISC|committee)|REGISTERED\s+No\.|Gazette\s+of\s+India|"
                    r"Uploaded\s+by\s+Dte\.\s+of\s+Printing|Digitally\s+signed\s+by|PUBLISHED\s+BY\s+AUTHORITY|"
                    r"Printed\s+by\s+the\s+Manager|Controller\s+of\s+Publications|Representing|Convener", re.I)


@dataclass
class Chunk:
    index: int
    clause_no: str | None
    heading: str | None
    page_from: int
    page_to: int
    content: str
    is_boilerplate: bool


def _lines_with_pages(pages: list[PageText]) -> list[tuple[int, str]]:
    out = []
    for p in pages:
        for ln in p.text.splitlines():
            out.append((p.page, ln))
    return out


def chunk_pages(pages: list[PageText], notification: bool = False) -> list[Chunk]:
    eng = [p for p in pages if p.is_english]
    if not eng:
        return []
    lines = _lines_with_pages(eng)
    splitter = NOTIF_PARA if notification else CLAUSE
    chunks: list[Chunk] = []
    cur: list[tuple[int, str]] = []
    clause, heading = None, None

    def flush() -> None:
        nonlocal cur
        text = re.sub(r"[ \t]+", " ", "\n".join(ln for _, ln in cur)).strip()
        if len(text) >= 20:
            # long clauses are cut at paragraph boundaries
            parts = [text] if len(text) <= MAX_CHARS else _cut(text)
            for part in parts:
                chunks.append(Chunk(len(chunks), clause, heading, cur[0][0], cur[-1][0], part,
                                    bool(BOILER.search(part[:600]))))
        cur = []

    for pg, ln in lines:
        m = ANNEX.match(ln) or splitter.match(ln)
        if m and cur and len("\n".join(x for _, x in cur)) >= MIN_CHARS:
            flush()
            clause = m.group(1).strip().rstrip(".")
            heading = (m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else ln.strip())[:200]
        elif m and not cur:
            clause = m.group(1).strip().rstrip(".")
            heading = (m.group(2).strip() if m.lastindex and m.lastindex >= 2 and m.group(2) else ln.strip())[:200]
        cur.append((pg, ln))
    if cur:
        flush()
    return chunks


def _cut(text: str) -> list[str]:
    out, buf = [], ""
    for para in re.split(r"\n\s*\n|(?<=\.)\n", text):
        if len(buf) + len(para) > MAX_CHARS and buf:
            out.append(buf.strip())
            buf = ""
        while len(para) > MAX_CHARS:
            out.append(para[:MAX_CHARS])
            para = para[MAX_CHARS:]
        buf += para + "\n"
    if buf.strip():
        out.append(buf.strip())
    return out


def stage_chunk(conn: psycopg.Connection, f: dict) -> str:
    pages = load_pages(f["sha256"])
    for df in conn.execute("SELECT * FROM document_file WHERE file_id=%s AND (is_best_copy OR role='consolidated_segment')",
                           (f["id"],)).fetchall():
        doc = conn.execute("SELECT * FROM document WHERE id=%s", (df["document_id"],)).fetchone()
        if doc["doc_class"] == DocClass.OFF_TOPIC:
            continue
        a, b = df["page_from"] or 1, df["page_to"] or (pages[-1].page if pages else 1)
        sel = [p for p in pages if a <= p.page <= b]
        chunks = chunk_pages(sel, notification=doc["doc_class"].startswith("NOTIFICATION"))
        old = [r["content"] for r in conn.execute(
            "SELECT content FROM chunk WHERE document_id=%s AND file_id=%s ORDER BY chunk_index", (doc["id"], f["id"]))]
        if old and old != [c.content for c in chunks]:
            # the document's page range changed (e.g. a re-split found another amendment): rebuild its chunks
            conn.execute("DELETE FROM chunk WHERE document_id=%s AND file_id=%s", (doc["id"], f["id"]))
        write_chunks(conn, doc, f["id"], chunks, offset_for(conn, doc["id"], f["id"]))
    set_stage(conn, f["id"], "chunked")
    return "chunked"


def offset_for(conn: psycopg.Connection, doc_id: int, file_id: int) -> int:
    """TAP has many files per document: each file's chunks get their own index range."""
    row = conn.execute("SELECT min(chunk_index) AS m FROM chunk WHERE document_id=%s AND file_id=%s", (doc_id, file_id)).fetchone()
    if row["m"] is not None:
        return row["m"]
    row = conn.execute("SELECT coalesce(max(chunk_index)+1, 0) AS n FROM chunk WHERE document_id=%s", (doc_id,)).fetchone()
    return row["n"]


def write_chunks(conn: psycopg.Connection, doc: dict, file_id: int, chunks: list[Chunk], offset: int) -> int:
    n = 0
    for c in chunks:
        r = conn.execute(
            """INSERT INTO chunk (document_id, file_id, chunk_index, clause_no, heading, page_from, page_to, language,
                                  is_boilerplate, content, doc_class, family_key, vehicle_categories, domains, doc_year,
                                  status, is_current, in_scope)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'en',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (document_id, chunk_index) DO NOTHING RETURNING id""",
            (doc["id"], file_id, offset + c.index, c.clause_no, c.heading, c.page_from, c.page_to, c.is_boilerplate,
             c.content, doc["doc_class"], doc["family_key"], doc["vehicle_categories"] or [], doc["domains"] or [],
             doc["doc_date"].year if doc["doc_date"] else doc["year"], doc["status"], doc["is_current"],
             doc["in_scope"])).fetchone()
        n += bool(r)
    return n


def sync_chunk_filters(conn: psycopg.Connection) -> int:
    """Copy changed filter columns (is_current/status/categories/in_scope) from document to its chunks."""
    cur = conn.execute(
        """UPDATE chunk c SET doc_class=d.doc_class, family_key=d.family_key, vehicle_categories=d.vehicle_categories,
                  domains=d.domains, status=d.status, is_current=d.is_current, in_scope=d.in_scope
           FROM document d WHERE d.id=c.document_id AND (c.is_current IS DISTINCT FROM d.is_current
                OR c.status IS DISTINCT FROM d.status OR c.in_scope IS DISTINCT FROM d.in_scope
                OR c.vehicle_categories IS DISTINCT FROM d.vehicle_categories OR c.domains IS DISTINCT FROM d.domains
                OR c.family_key IS DISTINCT FROM d.family_key OR c.doc_class IS DISTINCT FROM d.doc_class)""")
    return cur.rowcount


# ---------------------------------------------------------------------- embeddings
def embed_pending(conn: psycopg.Connection, batch: int = 64, limit: int | None = None) -> int:
    """Embed chunks without a vector (non-boilerplate first). Raises nothing when the LLM is down."""
    done = 0
    while True:
        rows = conn.execute("SELECT id, content, heading FROM chunk WHERE embedding IS NULL ORDER BY is_boilerplate, id LIMIT %s",
                            (batch,)).fetchall()
        if not rows:
            break
        try:
            vecs = llm.embed([(r["heading"] + "\n" if r["heading"] else "") + r["content"] for r in rows])
        except llm.LLMUnavailable as e:
            log.info("embedding unavailable: %s", e)
            break
        for r, v in zip(rows, vecs, strict=True):
            conn.execute("UPDATE chunk SET embedding=%s::vector WHERE id=%s", (vec_literal(v), r["id"]))
        conn.commit()
        done += len(rows)
        if limit and done >= limit:
            break
    return done


def advance_embedded(conn: psycopg.Connection) -> int:
    """Files whose chunks all have vectors (or that have no chunks) move chunked -> embedded -> done."""
    cur = conn.execute(
        """UPDATE file_object f SET stage='done', stage_error=NULL WHERE f.stage IN ('chunked','embedded')
           AND NOT EXISTS (SELECT 1 FROM chunk c WHERE c.file_id=f.id AND c.embedding IS NULL)""")
    return cur.rowcount


def content_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
