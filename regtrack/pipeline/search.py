"""Filtered vector search over document_chunks (DB_DESIGN query: category, in_scope, is_current filters).

Only the query is embedded at read time. If the embedding endpoint is down, a trigram/ILIKE text search over
the same filtered chunks is used instead (marked mode='text'); it uses the chunks' tsv index (migration 0009).
"""

from __future__ import annotations

import psycopg

from regtrack import country, llm
from regtrack.db import vec_literal


def search(conn: psycopg.Connection, q: str, category: str | None = None, in_scope: bool | None = True,
           is_current: bool | None = None, doc_class: str | None = None, limit: int = 10, cc: str | None = None,
           hybrid: bool = False, year: int | None = None) -> dict:
    """cc: country code (default: the COUNTRY setting); only that country's chunks are searched.
    hybrid: blend the vector ranking with the keyword ranking (see fuse); for questions, where an acronym or a
    technical term ('ABS') must find the clause that names it."""
    where = ["NOT c.is_boilerplate", country.region_sql("c", cc)]
    args: list = []
    if category:
        # the category and ALL, as this region's category ids
        where.append("c.vehicle_category_ids && ARRAY(SELECT vc.id FROM vehicle_categories vc "
                     "WHERE vc.region_id = c.region_id AND vc.code = ANY(%s))")
        args.append([category, "ALL"])
    if in_scope is not None:
        where.append("c.in_scope = %s")
        args.append(in_scope)
    if is_current is not None:
        where.append("(c.is_current = %s OR g.local_class LIKE 'NOTIFICATION%%')")
        args.append(is_current)
    if doc_class:
        where.append("g.local_class = %s")
        args.append(doc_class)
    if year:  # the regulation's publication year (the portal's year selector)
        where.append("extract(year FROM g.published_date) = %s")
        args.append(year)
    w = " AND ".join(where)
    cols = ("c.id, c.regulation_id, g.external_code AS canonical_id, g.local_class AS doc_class, c.clause_no, c.heading, "
            "c.page_from, c.page_to, left(c.content, 2000) AS content, g.title AS official_title, g.summary AS subject, "
            "g.published_date AS doc_date, g.effective_date")
    try:
        vec = llm.embed([q])[0]
        # the HNSW index returns its ~40 nearest chunks of ALL countries before the WHERE filter: a small country
        # (Thailand, Malaysia) or a narrow filter got 0 rows. Iterative scans (pgvector >= 0.8) keep scanning
        # until the filtered result is full.
        conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        n = max(limit, POOL) if hybrid else limit
        rows = conn.execute(
            f"SELECT {cols}, 1 - (c.embedding <=> %s::vector) AS score FROM document_chunks c "
            f"JOIN regulations g ON g.id=c.regulation_id "
            f"WHERE {w} AND c.embedding IS NOT NULL ORDER BY c.embedding <=> %s::vector LIMIT %s",
            [vec_literal(vec), *args, vec_literal(vec), n]).fetchall()
        mode = "vector"
        if hybrid:
            rows = fuse(rows, fulltext(conn, q, cols, w, args, POOL), limit)
            mode = "hybrid"
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
        "with", "from", "by", "do", "does", "my", "all", "any", "vehicles", "vehicle", "rules", "regulation", "regulations",
        # words of the question, not of the subject: in nearly every clause
        "requirement", "requirements", "required", "applicable", "apply", "applies", "mandatory", "rule", "when", "how",
        "need", "needs", "list", "tell", "explain", "there", "it", "be", "should", "must", "shall", "india", "indian"}
POOL = 40  # candidates per ranking before fusion
DRAFT_CLASSES = {"AIS_DRAFT", "NOTIFICATION_DRAFT"}
CATEGORY_CODES = {"l1", "l2", "l3", "l5", "m1", "m2", "m3", "n1", "n2", "n3"}


def fulltext(conn, q: str, cols: str, w: str, args: list, limit: int) -> list:
    """Ranked full-text search: each query word is a group of alternatives (acronym expansions) joined with OR,
    groups joined with AND; then the acronym groups alone (ABS -> 'anti-lock braking'); then OR across groups."""
    import re

    words = [t for t in re.findall(r"[A-Za-z0-9\-]+", q.lower()) if t not in STOP and t not in CATEGORY_CODES and len(t) > 1]
    if not words:
        words = [q]
    groups = []  # (tsquery SQL of one word and its alternatives, their values, is it a known acronym)
    for t in words[:8]:
        base = t if t in SYNONYMS else t.split("-")[0]  # "obd-ii" -> obd
        alts = [t] + SYNONYMS.get(base, []) + ([base] if base != t and base in SYNONYMS else [])
        groups.append(("(" + " || ".join(["phraseto_tsquery('english', %s)"] * len(alts)) + ")", alts, base in SYNONYMS))

    def tier(gs: list, joiner: str) -> tuple[str, list]:
        return joiner.join(g[0] for g in gs), [v for g in gs for v in g[1]]

    # all words; then only the specific ones (acronyms with expansions, e.g. ABS); then any word
    key = [g for g in groups if g[2]]
    tiers = [tier(groups, " && ")] + ([tier(key, " && ")] if key and len(key) < len(groups) else []) \
        + [tier(groups, " || ")]
    rows, seen = [], set()
    for tsq, ps in tiers:  # a better tier's matches rank above a weaker tier's; stop once the list is full
        for r in conn.execute(
                f"SELECT {cols}, ts_rank_cd(c.tsv, tsq) AS score "
                f"FROM document_chunks c JOIN regulations g ON g.id=c.regulation_id, ({'SELECT ' + tsq + ' AS tsq'}) qq "
                f"WHERE {w} AND c.tsv @@ qq.tsq ORDER BY score DESC, c.id LIMIT %s",
                [*ps, *args, limit - len(rows)]).fetchall():
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
        if len(rows) >= limit:
            break
    return rows


def fuse(vector: list, keyword: list, limit: int, k: int = 60) -> list:
    """Reciprocal rank fusion of the two rankings (a chunk high in both comes first); drafts count half, so a rule in
    force is preferred over a proposal saying the same thing."""
    score: dict[int, float] = {}
    row: dict[int, dict] = {}
    for ranking in (vector, keyword):
        for i, r in enumerate(ranking):
            score[r["id"]] = score.get(r["id"], 0.0) + 1.0 / (k + i + 1)
            row.setdefault(r["id"], dict(r))
    for cid, r in row.items():
        if r.get("doc_class") in DRAFT_CLASSES:
            score[cid] *= 0.5
    best = sorted(score, key=lambda cid: -score[cid])[:limit]
    return [{**row[cid], "score": round(score[cid], 4)} for cid in best]
