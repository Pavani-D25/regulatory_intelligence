"""Filtered vector search over chunks (DB_DESIGN query: category, in_scope, is_current filters).

Only the query is embedded at read time. If the embedding endpoint is down, a trigram/ILIKE text search over
the same filtered chunks is used instead (marked mode='text').
"""

from __future__ import annotations

import psycopg

from regtrack import llm
from regtrack.db import vec_literal


def search(conn: psycopg.Connection, q: str, category: str | None = None, in_scope: bool | None = True,
           is_current: bool | None = None, doc_class: str | None = None, limit: int = 10) -> dict:
    where = ["NOT c.is_boilerplate"]
    args: list = []
    if category:
        where.append("c.vehicle_categories && %s")
        args.append([category, "ALL"])
    if in_scope is not None:
        where.append("c.in_scope = %s")
        args.append(in_scope)
    if is_current is not None:
        where.append("(c.is_current = %s OR c.doc_class LIKE 'NOTIFICATION%%')")
        args.append(is_current)
    if doc_class:
        where.append("c.doc_class = %s")
        args.append(doc_class)
    w = " AND ".join(where)
    cols = ("c.id, d.canonical_id, c.doc_class, c.clause_no, c.heading, c.page_from, c.page_to, "
            "left(c.content, 600) AS content, d.official_title, d.subject, d.doc_date")
    try:
        vec = llm.embed([q])[0]
        rows = conn.execute(
            f"SELECT {cols}, 1 - (c.embedding <=> %s::vector) AS score FROM chunk c JOIN document d ON d.id=c.document_id "
            f"WHERE {w} AND c.embedding IS NOT NULL ORDER BY c.embedding <=> %s::vector LIMIT %s",
            [vec_literal(vec), *args, vec_literal(vec), limit]).fetchall()
        mode = "vector"
    except llm.LLMUnavailable as e:
        terms = [t for t in q.split() if len(t) > 2][:8] or [q]
        like = " AND ".join(["c.content ILIKE %s"] * len(terms))
        rows = conn.execute(
            f"SELECT {cols}, similarity(c.content, %s) AS score FROM chunk c JOIN document d ON d.id=c.document_id "
            f"WHERE {w} AND {like} ORDER BY score DESC, c.id LIMIT %s",
            [q, *args, *[f"%{t}%" for t in terms], limit]).fetchall()
        mode = f"text (embeddings unavailable: {str(e)[:80]})"
    return {"query": q, "mode": mode, "results": [dict(r) for r in rows]}
