"""Chunk + embed: 'linked' -> 'chunked' -> 'embedded' -> 'done'.

Clause-level chunks from English pages, split at clause numbers (1, 1.2, 6.12.3), ANNEX headings and
notification paragraphs. Boilerplate (committee lists, status charts, Gazette mastheads, printer lines) is kept
but flagged. Filter columns are copied from the regulation so vector search can filter without joins.
Stored in document_chunks (v4B); the keyword index (tsv) is computed by the database (migration 0009).
OFF_TOPIC documents get no chunks. Hindi is never embedded.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import psycopg

from regtrack import country, llm
from regtrack.config import get_settings
from regtrack.db import vec_literal
from regtrack.models.enums import DocClass
from regtrack.pipeline import repo as R
from regtrack.pipeline.dbutil import set_stage
from regtrack.pipeline.text import PageText, load_pages

log = logging.getLogger(__name__)
MAX_CHARS = 1800
MIN_CHARS = 120
CLAUSE = re.compile(r"^\s*((?:\d{1,2}\.){0,4}\d{1,2}\.?)\s+([A-Z][^\n]{2,120})?", re.M)
ANNEX = re.compile(r"^\s*(ANNEX(?:URE)?\s*[\-:]?\s*[A-Z0-9]{1,3})\b[^\n]*", re.M | re.I)
NOTIF_PARA = re.compile(r"^\s*(\(\d{1,2}\)|\d{1,2}\.)\s+", re.M)
BOILER = re.compile(
    r"composition\s+of\s+(?:the\s+)?(?:AISC|committee|panel)|status\s+chart\s+of\s+the\s+standard|"
    r"members?\s+of\s+(?:the\s+)?(?:AISC|committee)|REGISTERED\s+No\.|Gazette\s+of\s+India|"
    r"Uploaded\s+by\s+Dte\.\s+of\s+Printing|Digitally\s+signed\s+by|PUBLISHED\s+BY\s+AUTHORITY|"
    r"Printed\s+by\s+the\s+Manager|Controller\s+of\s+Publications|Representing|Convener",
    re.I,
)


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


LOCAL_SCRIPT_COUNTRIES = {"TH", "MY"}  # their documents are in Thai / Malay: every text page is chunked
THAI_CHAR = re.compile("[ก-๛]")


def chunk_language(text: str) -> str:
    """'th' for a mostly-Thai passage, else 'en' (English, and Malay in Latin script)."""
    return "th" if len(THAI_CHAR.findall(text)) > len(re.findall(r"[A-Za-z]", text)) else "en"


def chunk_pages(pages: list[PageText], notification: bool = False, all_scripts: bool = False) -> list[Chunk]:
    """English pages (India: Hindi pages are never chunked), or with all_scripts every page with text (Thai, Malay)."""
    eng = (
        [p for p in pages if p.chars and p.lang not in ("hi", "hi_legacy", "empty")]
        if all_scripts
        else [p for p in pages if p.is_english]
    )
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
                chunks.append(
                    Chunk(len(chunks), clause, heading, cur[0][0], cur[-1][0], part, bool(BOILER.search(part[:600])))
                )
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
    for df in R.parts_of_file(conn, f["id"], readable_only=True):
        doc = R.get_document(conn, df["document_id"])
        if doc["doc_class"] == DocClass.OFF_TOPIC:
            continue
        a, b = df["page_from"] or 1, df["page_to"] or (pages[-1].page if pages else 1)
        sel = [p for p in pages if a <= p.page <= b]
        chunks = chunk_pages(
            sel,
            notification=doc["doc_class"].startswith("NOTIFICATION"),
            all_scripts=(doc.get("country") or "").upper() in LOCAL_SCRIPT_COUNTRIES,
        )
        old = [
            r["content"]
            for r in conn.execute(
                "SELECT content FROM document_chunks WHERE regulation_id=%s AND document_id=%s ORDER BY chunk_index",
                (doc["id"], f["id"]),
            )
        ]
        if old and old != [c.content for c in chunks]:
            # the document's page range changed (e.g. a re-split found another amendment): rebuild its chunks
            # an Ask AI answer that cited one of the old chunks keeps its regulation, loses only the chunk link
            conn.execute(
                """UPDATE assistant_message_citations SET document_chunk_id=NULL WHERE document_chunk_id IN
                            (SELECT id FROM document_chunks WHERE regulation_id=%s AND document_id=%s)""",
                (doc["id"], f["id"]),
            )
            conn.execute("DELETE FROM document_chunks WHERE regulation_id=%s AND document_id=%s", (doc["id"], f["id"]))
        write_chunks(conn, doc, f["id"], chunks, offset_for(conn, doc["id"], f["id"]))
    set_stage(conn, f["id"], "chunked")
    return "chunked"


def offset_for(conn: psycopg.Connection, doc_id: int, file_id: int) -> int:
    """TAP has many files per document: each file's chunks get their own index range."""
    row = conn.execute(
        "SELECT min(chunk_index) AS m FROM document_chunks WHERE regulation_id=%s AND document_id=%s", (doc_id, file_id)
    ).fetchone()
    if row["m"] is not None:
        return row["m"]
    row = conn.execute(
        "SELECT coalesce(max(chunk_index)+1, 0) AS n FROM document_chunks WHERE regulation_id=%s", (doc_id,)
    ).fetchone()
    return row["n"]


# filter copies of the regulation on each chunk, so search needs no joins (the same values 0007 copied)
FILTERS = """
SELECT g.id, g.region_id, g.doc_type, g.legal_status, g.is_current, g.in_scope,
       coalesce(extract(year FROM g.published_date)::int, g.year) AS year,
       coalesce((SELECT array_agg(l.vehicle_category_id ORDER BY l.vehicle_category_id)
                 FROM regulation_vehicle_categories l WHERE l.regulation_id = g.id), '{}') AS vehicle_category_ids,
       coalesce((SELECT array_agg(l.domain_id ORDER BY l.domain_id)
                 FROM regulation_domains l WHERE l.regulation_id = g.id), '{}') AS domain_ids
FROM regulations g"""
FILTER_COLS = (
    "region_id",
    "doc_type",
    "legal_status",
    "is_current",
    "in_scope",
    "year",
    "vehicle_category_ids",
    "domain_ids",
)


def write_chunks(conn: psycopg.Connection, doc: dict, file_id: int, chunks: list[Chunk], offset: int) -> int:
    flt = conn.execute(FILTERS + " WHERE g.id=%s", (doc["id"],)).fetchone()
    n = 0
    for c in chunks:
        r = conn.execute(
            f"""INSERT INTO document_chunks (regulation_id, document_id, chunk_index, clause_no, heading, page_from, page_to,
                                             language, is_boilerplate, content, {", ".join(FILTER_COLS)})
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,{", ".join(["%s"] * len(FILTER_COLS))})
               ON CONFLICT (regulation_id, chunk_index) DO NOTHING RETURNING id""",
            (
                doc["id"],
                file_id,
                offset + c.index,
                c.clause_no,
                c.heading,
                c.page_from,
                c.page_to,
                chunk_language(c.content),
                c.is_boilerplate,
                c.content,
                *[flt[k] for k in FILTER_COLS],
            ),
        ).fetchone()
        n += bool(r)
    return n


def sync_chunk_filters(conn: psycopg.Connection) -> int:
    """Copy changed filter values (current, status, scope, year, categories, topics, type) from regulations to chunks."""
    cur = conn.execute(
        f"""UPDATE document_chunks c SET {", ".join(f"{k}=f.{k}" for k in FILTER_COLS)}
            FROM ({FILTERS} WHERE {country.region_sql("g")}) f
            WHERE f.id = c.regulation_id
              AND ({" OR ".join(f"c.{k} IS DISTINCT FROM f.{k}" for k in FILTER_COLS)})"""
    )
    return cur.rowcount


# ---------------------------------------------------------------------- embeddings
def embed_pending(conn: psycopg.Connection, batch: int = 64, limit: int | None = None) -> int:
    """Embed chunks without a vector (non-boilerplate first). Raises nothing when the LLM is down."""
    done = 0
    while True:
        # EMBED_SCOPE=priority: only current, in-scope chunks (what the portal searches) - over a metered tunnel
        # the 120k-chunk history backlog would use up its bandwidth (ngrok free plan, ERR_NGROK_725)
        # in scope and in force: is_current is set only inside a version family, so a notification or a Malaysian law
        # (no family) counts unless superseded / withdrawn
        scope = (
            " AND in_scope AND (is_current OR legal_status NOT IN ('superseded','withdrawn'))"
            if get_settings().embed_scope == "priority"
            else ""
        )
        rows = conn.execute(
            f"SELECT id, content, heading FROM document_chunks c WHERE embedding IS NULL "
            f"AND language IN ('en','th') AND {country.region_sql('c')}{scope} "
            # what the portal searches first: current, in-scope text, then the rest
            "ORDER BY (in_scope AND (is_current OR legal_status NOT IN ('superseded','withdrawn'))) IS NOT TRUE, "
            "is_boilerplate, id LIMIT %s",
            (batch,),
        ).fetchall()
        if not rows:
            break
        try:
            vecs = llm.embed([(r["heading"] + "\n" if r["heading"] else "") + r["content"] for r in rows])
        except llm.LLMUnavailable as e:
            log.info("embedding unavailable: %s", e)
            break
        for r, v in zip(rows, vecs, strict=True):
            conn.execute("UPDATE document_chunks SET embedding=%s::vector WHERE id=%s", (vec_literal(v), r["id"]))
        conn.commit()
        done += len(rows)
        if limit and done >= limit:
            break
    return done


def advance_embedded(conn: psycopg.Connection) -> int:
    """Files whose English chunks all have vectors (or that have no chunks) move chunked -> embedded -> done."""
    cur = conn.execute(
        """UPDATE documents f SET stage='done', stage_error=NULL WHERE f.stage IN ('chunked','embedded')
           AND """
        + country.region_sql("f")
        + """ AND NOT EXISTS (SELECT 1 FROM document_chunks c
               WHERE c.document_id=f.id AND c.embedding IS NULL AND c.language IN ('en','th'))"""
    )
    return cur.rowcount
