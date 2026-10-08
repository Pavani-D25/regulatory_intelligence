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
        rows = fulltext(conn, q, cols, w, args, limit)
        mode = f"text (embeddings unavailable: {str(e)[:80]})"
    return {"query": q, "mode": mode, "results": [dict(r) for r in rows]}


# domain acronyms -> words used in the regulations (keyword search has no notion of meaning)
SYNONYMS = {
    "abs": ["anti-lock braking", "antilock"], "cbs": ["combined braking"], "aeb": ["emergency braking"],
    "esc": ["electronic stability"], "tpms": ["tyre pressure monitoring"], "ev": ["electric vehicle", "battery operated"],
    "bev": ["battery electric", "battery operated"], "cng": ["compressed natural gas"], "lpg": ["liquefied petroleum gas"],
    "hsrp": ["high security registration"], "puc": ["pollution under control"], "vlt": ["vehicle location tracking"],
    "obd": ["on-board diagnostic"], "drl": ["daytime running"], "seatbelt": ["seat belt"], "bs6": ["bharat stage vi"],
    "motorcycle": ["motor cycle", "two-wheeler"], "motorcycles": ["motor cycles", "two-wheelers"], "car": ["m1"],
    "scooter": ["two-wheeler", "motor cycle"],
}
STOP = {"for", "the", "and", "of", "in", "on", "to", "a", "an", "is", "are", "what", "which", "show", "me", "about",
        "with", "from", "by", "do", "does", "my", "all", "any", "vehicles", "vehicle", "rules", "regulation", "regulations"}
CATEGORY_CODES = {"l1", "l2", "l3", "l5", "m1", "m2", "m3", "n1", "n2", "n3"}


def fulltext(conn, q: str, cols: str, w: str, args: list, limit: int) -> list:
    """Ranked full-text search: each query word is a group of alternatives (acronym expansions) joined with OR,
    groups joined with AND; falls back to OR across groups when nothing matches all of them."""
    import re

    words = [t for t in re.findall(r"[A-Za-z0-9\-]+", q.lower()) if t not in STOP and t not in CATEGORY_CODES and len(t) > 1]
    if not words:
        words = [q]
    groups, params = [], []
    for t in words[:8]:
        alts = [t] + SYNONYMS.get(t, [])
        groups.append("(" + " || ".join(["phraseto_tsquery('english', %s)"] * len(alts)) + ")")
        params += alts
    rows = []
    for joiner in (" && ", " || "):
        tsq = joiner.join(groups)
        rows = conn.execute(
            f"SELECT {cols}, ts_rank_cd(to_tsvector('english', c.content), tsq) AS score "
            f"FROM chunk c JOIN document d ON d.id=c.document_id, ({'SELECT ' + tsq + ' AS tsq'}) qq "
            f"WHERE {w} AND to_tsvector('english', c.content) @@ qq.tsq ORDER BY score DESC, c.id LIMIT %s",
            [*params, *args, limit]).fetchall()
        if rows:
            break
    return rows
