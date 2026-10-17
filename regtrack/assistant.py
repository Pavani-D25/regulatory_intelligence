"""Ask-AI history (v4B assistant_* tables): each question and its answer are kept, with the chunks the answer
was built from as citations. There are no user logins yet, so conversations have no user (user_id NULL)."""

from __future__ import annotations

import psycopg


def record_exchange(conn: psycopg.Connection, question: str, answer: str, hits: list[dict],
                    conversation_id: int | None = None) -> int:
    """Store one question and answer; returns the conversation id (a new conversation unless a known one is given).
    hits: search results with id (the chunk), regulation_id and score."""
    if conversation_id is not None:
        row = conn.execute("SELECT id FROM assistant_conversations WHERE id=%s", (conversation_id,)).fetchone()
        conversation_id = row["id"] if row else None
    if conversation_id is None:
        conversation_id = conn.execute("INSERT INTO assistant_conversations DEFAULT VALUES RETURNING id").fetchone()["id"]
    conn.execute("INSERT INTO assistant_messages (conversation_id, role, content) VALUES (%s,'user',%s)",
                 (conversation_id, question))
    mid = conn.execute("INSERT INTO assistant_messages (conversation_id, role, content) VALUES (%s,'assistant',%s) "
                       "RETURNING id", (conversation_id, answer)).fetchone()["id"]
    for h in hits:
        score = h.get("score")
        conn.execute("INSERT INTO assistant_message_citations (message_id, regulation_id, document_chunk_id, score) "
                     "VALUES (%s,%s,%s,%s)",
                     (mid, h.get("regulation_id"), h.get("id"),
                      round(max(min(float(score), 99.0), -99.0), 4) if score is not None else None))
    return conversation_id


def conversation(conn: psycopg.Connection, conversation_id: int) -> list[dict]:
    """The messages of one conversation in order, each answer with the regulations and clauses it cited."""
    msgs = conn.execute("SELECT id, role, content, created_at FROM assistant_messages WHERE conversation_id=%s "
                        "ORDER BY id", (conversation_id,)).fetchall()
    out = []
    for m in msgs:
        cites = conn.execute(
            """SELECT g.external_code AS canonical_id, c.clause_no, c.page_from, c.page_to, x.score
               FROM assistant_message_citations x LEFT JOIN regulations g ON g.id = x.regulation_id
               LEFT JOIN document_chunks c ON c.id = x.document_chunk_id WHERE x.message_id=%s ORDER BY x.id""",
            (m["id"],)).fetchall()
        out.append({**m, "citations": [dict(c) for c in cites]})
    return out
