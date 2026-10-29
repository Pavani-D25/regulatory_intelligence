"""Data access for the pipeline on the v4B tables (docs/SCHEMA_V4B.md).

The pipeline's logic works with two kinds of records, in its original vocabulary:
  a *file*      sha256, ext, mime, size_bytes, pdf_meta, page_count, text_layer, stage …
  a *document*  canonical_id, doc_class, status, issuer, official_title, subject, doc_date, vehicle_categories[],
                domains[], data, extraction …
This module is the one place that maps them to the v4B tables:
  file            -> documents
  document        -> regulations (+ regulation_authorities, regulation_vehicle_categories, regulation_domains)
  pages in a file -> document_parts
  listings        -> raw_ingestion_records (+ sources)
Writes only touch values that differ, so a re-run with nothing new writes nothing (CLAUDE.md rule 7).
"""

from __future__ import annotations

import logging
import re

import psycopg

from regtrack import country
from regtrack.db import Jsonb
from regtrack.pipeline.classify import ISSUERS as _CLASSIFY_ISSUERS
from regtrack.pipeline.dbutil import _norm, update_if_changed

log = logging.getLogger(__name__)
JSON_COLS = {"data", "relevance", "extraction"}


def _json(k: str, v):
    return Jsonb(v) if k in JSON_COLS and isinstance(v, (dict, list)) else v


def region_id(conn: psycopg.Connection, cc: str | None = None) -> int:
    return conn.execute("SELECT id FROM regions WHERE code=%s", (country.code(cc),)).fetchone()["id"]


# ====================================================================== files (documents)
FILE_SQL = """SELECT d.id, d.checksum_sha256 AS sha256, d.file_ext AS ext, d.mime_type AS mime, d.storage_path,
                     d.file_size_bytes AS size_bytes, d.page_count, d.text_layer, d.scanned_pages, d.ocr_engine,
                     d.ocr_confidence, d.language_mix, d.metadata AS pdf_meta, d.stage, d.stage_error,
                     d.downloaded_at AS first_seen_at, r.code AS country
              FROM documents d JOIN regions r ON r.id = d.region_id"""
FILE_COLS = {
    "sha256": "checksum_sha256",
    "ext": "file_ext",
    "mime": "mime_type",
    "size_bytes": "file_size_bytes",
    "pdf_meta": "metadata",
    "first_seen_at": "downloaded_at",
}


def get_file(conn: psycopg.Connection, file_id: int) -> dict | None:
    return conn.execute(FILE_SQL + " WHERE d.id=%s", (file_id,)).fetchone()


def files_at_stage(conn: psycopg.Connection, stage: str, limit: int | None = None) -> list[dict]:
    q = FILE_SQL + f" WHERE d.stage=%s AND {country.region_sql('d')} ORDER BY d.id" + (" LIMIT %s" if limit else "")
    return conn.execute(q, (stage, limit) if limit else (stage,)).fetchall()


def update_file(conn: psycopg.Connection, file_id: int, values: dict) -> bool:
    return update_if_changed(conn, "documents", {"id": file_id}, {FILE_COLS.get(k, k): v for k, v in values.items()})


# ====================================================================== listings (raw_ingestion_records)
LISTING_SQL = """SELECT s.code, r.listing_title, r.listing_date, r.listing_category, r.payload AS listing_raw,
                        r.document_id AS file_id
                 FROM raw_ingestion_records r JOIN sources s ON s.id = r.source_id"""


def listings_of_file(conn: psycopg.Connection, file_id: int) -> list[dict]:
    return conn.execute(LISTING_SQL + " WHERE r.document_id=%s ORDER BY r.id", (file_id,)).fetchall()


def listings_of_document(conn: psycopg.Connection, doc_id: int) -> list[dict]:
    """Listings of every file that holds this document."""
    return conn.execute(
        LISTING_SQL + " JOIN document_parts p ON p.document_id = r.document_id WHERE p.regulation_id=%s ORDER BY r.id",
        (doc_id,),
    ).fetchall()


def mark_listings_classified(conn: psycopg.Connection, file_id: int) -> int:
    """After classification: the listings of a file record the verdict (relevant or not) and the main regulation."""
    main = conn.execute(
        """SELECT p.regulation_id FROM document_parts p WHERE p.document_id=%s
           ORDER BY (p.role = 'main') DESC, p.is_best_copy DESC, p.page_from, p.regulation_id LIMIT 1""",
        (file_id,),
    ).fetchone()
    relevant = conn.execute(
        """SELECT EXISTS (SELECT 1 FROM document_parts p JOIN regulations g ON g.id = p.regulation_id
                          WHERE p.document_id=%s AND g.doc_type IS DISTINCT FROM 'OFF_TOPIC'
                            AND g.local_class <> 'OFF_TOPIC') AS v""",
        (file_id,),
    ).fetchone()["v"]
    reg = main["regulation_id"] if main else None
    cur = conn.execute(
        """UPDATE raw_ingestion_records SET classification_method='rules', classification_verdict=%s, regulation_id=%s
           WHERE document_id=%s AND (classification_method IS DISTINCT FROM 'rules'
                 OR classification_verdict IS DISTINCT FROM %s OR regulation_id IS DISTINCT FROM %s)""",
        (relevant, reg, file_id, relevant, reg),
    )
    return cur.rowcount


# ====================================================================== documents (regulations)
def authority_code(issuer: str) -> str:
    """'AISC/ARAI' -> 'AISC_ARAI' (the same rule as migration 0007)."""
    return re.sub(r"[^A-Za-z0-9]+", "_", issuer).strip("_").upper()[:20]


ISSUER_BY_CODE = {authority_code(name): name for name, _rx in _CLASSIFY_ISSUERS}
# the short issuer name the pipeline reads from document headers ("MoRTH", "AISC/ARAI"); other authorities by name
ISSUER_SQL = "CASE a.code " + " ".join(f"WHEN '{c}' THEN '{n}'" for c, n in ISSUER_BY_CODE.items()) + " ELSE a.name END"
REG_SQL = (
    """
SELECT g.id, g.external_code AS canonical_id, g.local_class AS doc_class, g.legal_status AS status,
       g.title AS official_title, g.summary AS subject, g.published_date AS doc_date,
       g.published_date_precision AS doc_date_precision, """
    + ISSUER_SQL
    + """ AS issuer,
       g.series, g.number, g.year, g.part, g.revision, g.amendment_no, g.corrigendum_no, g.family_key, g.version_seq,
       g.is_current, g.nature, g.usage, g.powertrains, g.in_scope, g.relevance, g.data, g.extraction, g.language,
       g.effective_date, g.doc_type, g.doc_role, g.legal_force, g.local_type, rg.code AS country,
       g.created_at, g.updated_at,
       coalesce((SELECT array_agg(vc.code ORDER BY vc.code) FROM regulation_vehicle_categories l
                 JOIN vehicle_categories vc ON vc.id = l.vehicle_category_id WHERE l.regulation_id = g.id), '{}')
         AS vehicle_categories,
       coalesce((SELECT array_agg(lower(dm.code) ORDER BY l.is_primary DESC, dm.code) FROM regulation_domains l
                 JOIN domains dm ON dm.id = l.domain_id WHERE l.regulation_id = g.id), '{}') AS domains
FROM regulations g JOIN regions rg ON rg.id = g.region_id
LEFT JOIN regulatory_authorities a ON a.id = g.authority_id"""
)
REG_COLS = {
    "canonical_id": "external_code",
    "doc_class": "local_class",
    "status": "legal_status",
    "official_title": "title",
    "subject": "summary",
    "doc_date": "published_date",
    "doc_date_precision": "published_date_precision",
}
LINKED = ("vehicle_categories", "domains", "issuer")


def _doc(row) -> dict | None:
    return dict(row) if row is not None else None


def get_document(conn: psycopg.Connection, doc_id: int) -> dict | None:
    return _doc(conn.execute(REG_SQL + " WHERE g.id=%s", (doc_id,)).fetchone())


def find_document(conn: psycopg.Connection, canonical_id: str, cc: str | None = None) -> dict | None:
    return _doc(
        conn.execute(
            REG_SQL + f" WHERE g.external_code=%s AND {country.region_sql('g', cc)}", (canonical_id,)
        ).fetchone()
    )


def _same(k: str, a, b) -> bool:
    if k == "vehicle_categories":
        return sorted(set(a or [])) == sorted(set(b or []))
    if k == "domains":  # only the primary (first) topic has an order
        a, b = list(a or []), list(b or [])
        return (a[:1], sorted(set(a))) == (b[:1], sorted(set(b)))
    return _norm(a) == _norm(b)


def insert_document(conn: psycopg.Connection, canonical_id: str, values: dict) -> int:
    cols: dict = {"region_id": region_id(conn), "external_code": canonical_id}
    for k, v in values.items():
        if k not in LINKED:
            cols[REG_COLS.get(k, k)] = _json(k, v)
    new = conn.execute(
        f"INSERT INTO regulations ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) RETURNING id",
        list(cols.values()),
    ).fetchone()["id"]
    _set_links(conn, new, {k: v for k, v in values.items() if k in LINKED})
    return new


def update_document(conn: psycopg.Connection, doc_id: int, values: dict, touch: bool = False) -> bool:
    """Write the values that differ (legacy names), including the linked vehicle types, topics and issuer."""
    cur = get_document(conn, doc_id)
    if cur is None:
        return False
    changed = {k: v for k, v in values.items() if not _same(k, cur.get(k), v)}
    if not changed:
        return False
    cols = {REG_COLS.get(k, k): _json(k, v) for k, v in changed.items() if k not in LINKED}
    if cols:
        sets = ", ".join(f"{c}=%s" for c in cols) + (", updated_at=now()" if touch else "")
        conn.execute(f"UPDATE regulations SET {sets} WHERE id=%s", [*cols.values(), doc_id])
    links = {k: v for k, v in changed.items() if k in LINKED}
    if links:
        _set_links(conn, doc_id, links)
        if touch and not cols:
            conn.execute("UPDATE regulations SET updated_at=now() WHERE id=%s", (doc_id,))
    return True


def _set_links(conn: psycopg.Connection, doc_id: int, links: dict) -> None:
    region = conn.execute("SELECT region_id FROM regulations WHERE id=%s", (doc_id,)).fetchone()["region_id"]
    if "vehicle_categories" in links:
        codes = sorted(set(links["vehicle_categories"] or []))
        rows = conn.execute(
            "SELECT id, code FROM vehicle_categories WHERE region_id=%s AND code = ANY(%s)", (region, codes)
        ).fetchall()
        if len(rows) != len(codes):
            log.warning("document %s: unknown vehicle categories %s", doc_id, set(codes) - {r["code"] for r in rows})
        ids = [r["id"] for r in rows]
        conn.execute(
            "DELETE FROM regulation_vehicle_categories WHERE regulation_id=%s AND vehicle_category_id <> ALL(%s)",
            (doc_id, ids),
        )
        for i in ids:
            conn.execute("INSERT INTO regulation_vehicle_categories VALUES (%s,%s) ON CONFLICT DO NOTHING", (doc_id, i))
    if "domains" in links:
        codes = [c.upper() for c in dict.fromkeys(links["domains"] or [])]
        found = {
            r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM domains WHERE code = ANY(%s)", (codes,))
        }
        if len(found) != len(codes):
            log.warning("document %s: unknown topics %s", doc_id, set(codes) - set(found))
        ids = [found[c] for c in codes if c in found]
        conn.execute("DELETE FROM regulation_domains WHERE regulation_id=%s AND domain_id <> ALL(%s)", (doc_id, ids))
        # one primary: clear the others first (partial unique index), then set the first
        conn.execute(
            "UPDATE regulation_domains SET is_primary=false WHERE regulation_id=%s AND is_primary "
            "AND domain_id IS DISTINCT FROM %s",
            (doc_id, ids[0] if ids else None),
        )
        for n, i in enumerate(ids):
            conn.execute(
                """INSERT INTO regulation_domains (regulation_id, domain_id, is_primary) VALUES (%s,%s,%s)
                            ON CONFLICT (regulation_id, domain_id) DO UPDATE SET is_primary=EXCLUDED.is_primary
                            WHERE regulation_domains.is_primary IS DISTINCT FROM EXCLUDED.is_primary""",
                (doc_id, i, n == 0),
            )
    if "issuer" in links:
        issuer = links["issuer"]
        aid = None
        if issuer:
            code = authority_code(issuer)
            conn.execute(
                "INSERT INTO regulatory_authorities (region_id, code, name) VALUES (%s,%s,%s) "
                "ON CONFLICT (code) DO NOTHING",
                (region, code, issuer),
            )
            aid = conn.execute("SELECT id FROM regulatory_authorities WHERE code=%s", (code,)).fetchone()["id"]
        conn.execute(
            "UPDATE regulations SET authority_id=%s WHERE id=%s AND authority_id IS DISTINCT FROM %s",
            (aid, doc_id, aid),
        )
        conn.execute(
            "DELETE FROM regulation_authorities WHERE regulation_id=%s AND role='primary' "
            "AND authority_id IS DISTINCT FROM %s",
            (doc_id, aid),
        )
        if aid:
            conn.execute(
                """INSERT INTO regulation_authorities (regulation_id, authority_id, role) VALUES (%s,%s,'primary')
                            ON CONFLICT (regulation_id, authority_id) DO UPDATE SET role='primary'
                            WHERE regulation_authorities.role <> 'primary'""",
                (doc_id, aid),
            )


def retire_document(conn: psycopg.Connection, doc_id: int) -> None:
    """A document left without any file and not the source of a rule version: links to it fall back to its code,
    its warnings are resolved as superseded, then it is removed (its parts, links and chunks go with it)."""
    conn.execute(
        """UPDATE regulation_relations SET to_regulation_id=NULL,
                      to_ref=coalesce(to_ref, (SELECT external_code FROM regulations WHERE id=%s))
                    WHERE to_regulation_id=%s""",
        (doc_id, doc_id),
    )
    conn.execute(
        """UPDATE quality_flags SET resolved_at=now(), details=coalesce(details,'{}'::jsonb) ||
                      '{"resolution": "document retired after re-classification"}'::jsonb
                    WHERE entity='regulation' AND entity_id=%s AND resolved_at IS NULL""",
        (doc_id,),
    )
    for table, col in (
        ("regulation_changes", "regulation_id"),
        ("raw_ingestion_records", "regulation_id"),
        ("compliance_requirements", "regulation_id"),
        ("alert_events", "regulation_id"),
        ("assistant_message_citations", "regulation_id"),
    ):
        conn.execute(f"UPDATE {table} SET {col}=NULL WHERE {col}=%s", (doc_id,))
    conn.execute(
        "DELETE FROM assistant_message_citations WHERE regulation_id IS NULL AND document_chunk_id IN "
        "(SELECT id FROM document_chunks WHERE regulation_id=%s)",
        (doc_id,),
    )
    conn.execute("DELETE FROM regulations WHERE id=%s", (doc_id,))


# ====================================================================== pages of a file (document_parts)
PART_SQL = """SELECT p.regulation_id AS document_id, p.document_id AS file_id, p.page_from, p.page_to,
                     (p.language_pages->'en'->>0)::int AS english_page_from,
                     (p.language_pages->'en'->>1)::int AS english_page_to, p.part_label,
                     CASE p.role WHEN 'other_language_only' THEN 'hindi_only' ELSE p.role END AS role, p.is_best_copy
              FROM document_parts p"""
ROLE_TO_V4 = {"hindi_only": "other_language_only"}


def parts_of_file(conn: psycopg.Connection, file_id: int, readable_only: bool = False) -> list[dict]:
    """The documents a file holds, by page; readable_only = best copies and consolidated segments."""
    extra = " AND (p.is_best_copy OR p.role = 'consolidated_segment')" if readable_only else ""
    return conn.execute(
        PART_SQL + f" WHERE p.document_id=%s{extra} ORDER BY p.page_from, p.regulation_id", (file_id,)
    ).fetchall()


def attach(
    conn: psycopg.Connection,
    doc_id: int,
    file_id: int,
    page_from: int = 1,
    page_to: int | None = None,
    eng: tuple[int | None, int | None] = (None, None),
    part_label: str | None = None,
    role: str = "main",
) -> None:
    pages = Jsonb({"en": [eng[0], eng[1]]}) if eng[0] is not None else None
    conn.execute(
        """INSERT INTO document_parts (regulation_id, document_id, page_from, page_to, language_pages, part_label, role)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (regulation_id, document_id, page_from) DO UPDATE
             SET page_to=EXCLUDED.page_to, language_pages=EXCLUDED.language_pages, part_label=EXCLUDED.part_label,
                 role=EXCLUDED.role
             WHERE (document_parts.page_to, document_parts.language_pages, document_parts.part_label, document_parts.role)
                   IS DISTINCT FROM (EXCLUDED.page_to, EXCLUDED.language_pages, EXCLUDED.part_label, EXCLUDED.role)""",
        (doc_id, file_id, page_from, page_to, pages, part_label, ROLE_TO_V4.get(str(role), str(role))),
    )


def detach(conn: psycopg.Connection, doc_id: int, file_id: int, page_from: int | None = None) -> None:
    """Remove a document's part(s) in a file, with the chunks read from it."""
    if page_from is None:
        conn.execute("DELETE FROM document_chunks WHERE regulation_id=%s AND document_id=%s", (doc_id, file_id))
        conn.execute("DELETE FROM document_parts WHERE regulation_id=%s AND document_id=%s", (doc_id, file_id))
    else:
        conn.execute("DELETE FROM document_chunks WHERE regulation_id=%s AND document_id=%s", (doc_id, file_id))
        conn.execute(
            "DELETE FROM document_parts WHERE regulation_id=%s AND document_id=%s AND page_from=%s",
            (doc_id, file_id, page_from),
        )
