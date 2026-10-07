"""Read-only API. No LLM calls at read time except embedding the search query.

    uvicorn regtrack.api.app:app      (or: python -m regtrack.cli api)
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse

from regtrack.db import connect
from regtrack.models.enums import IN_SCOPE_CATEGORIES
from regtrack.pipeline.search import search as chunk_search

app = FastAPI(title="RegTrack India", version="0.1.0",
              description="Indian vehicle regulations (ARAI AIS, MoRTH Gazette, e-Gazette, India Code) - read only")

DOC_COLS = ("id, canonical_id, doc_class, series, number, year, part, revision, amendment_no, corrigendum_no, family_key, "
            "version_seq, is_current, official_title, subject, issuer, status, doc_date, doc_date_precision, nature, "
            "vehicle_categories, usage, powertrains, domains, in_scope")


def _rows(sql: str, args: list | tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "documents": _rows("SELECT count(*) AS n FROM document")[0]["n"]}


# ---------------------------------------------------------------- vehicle view
COND_SQL = """
  AND (m.conditions->'{k}'->>'lte' IS NULL OR %s IS NULL OR (m.conditions->'{k}'->>'lte')::numeric >= %s)
  AND (m.conditions->'{k}'->>'lt'  IS NULL OR %s IS NULL OR (m.conditions->'{k}'->>'lt')::numeric  >  %s)
  AND (m.conditions->'{k}'->>'gte' IS NULL OR %s IS NULL OR (m.conditions->'{k}'->>'gte')::numeric <= %s)
  AND (m.conditions->'{k}'->>'gt'  IS NULL OR %s IS NULL OR (m.conditions->'{k}'->>'gt')::numeric  <  %s)"""


@app.get("/vehicles/applicable")
def vehicles_applicable(category: str = Query(..., examples=["L2"]), engine_cc: float | None = None,
                        power_kw: float | None = None, gvw_kg: float | None = None, seats: float | None = None,
                        powertrain: str | None = None, usage: str | None = None, on: date | None = None,
                        include_drafts: bool = False, include_future: bool = False) -> dict:
    """Mandates for a vehicle on a date, with the standards behind each and their current versions."""
    on = on or date.today()
    cats = [category.upper(), "ALL"]
    args: list = [cats]
    sql = ["SELECT m.*, d.canonical_id AS source_canonical_id, d.official_title AS source_title FROM mandate m "
           "JOIN document d ON d.id=m.source_doc_id WHERE m.vehicle_categories && %s"]
    if not include_drafts:
        sql.append("AND NOT m.is_draft")
    if not include_future:
        sql.append("AND (m.implementation_date IS NULL OR m.implementation_date <= %s)")
        args.append(on)
    sql.append("AND (m.valid_from IS NULL OR m.valid_from <= %s) AND (m.valid_to IS NULL OR m.valid_to > %s)")
    args += [on, on]
    for k, v in (("engine_cc", engine_cc), ("power_kw", power_kw), ("gvw_kg", gvw_kg), ("seats", seats)):
        sql.append(COND_SQL.format(k=k))
        args += [v, v] * 4
    if powertrain:
        sql.append("AND (m.powertrains = '{}' OR m.powertrains && %s)")
        args.append([powertrain.lower(), "all"])
    if usage:
        sql.append("AND (m.usage = '{}' OR m.usage && %s)")
        args.append([usage.lower(), "all"])
    sql.append("ORDER BY m.implementation_date NULLS LAST, m.legal_basis")
    with connect() as conn:
        mandates = [dict(r) for r in conn.execute(" ".join(sql), args).fetchall()]
        for m in mandates:
            m["standards"] = []
            for ref in m["standard_refs"] or []:
                fam = ref.split("(Rev")[0] if ref.startswith("AIS-") else None
                cur = conn.execute(f"SELECT {DOC_COLS} FROM document WHERE family_key=%s AND is_current", (fam,)).fetchone() if fam else None
                amds = conn.execute("SELECT canonical_id, doc_date FROM document WHERE family_key=%s AND doc_class "
                                    "IN ('AIS_AMENDMENT','AIS_CORRIGENDUM') ORDER BY version_seq", (fam,)).fetchall() if fam else []
                m["standards"].append({"ref": ref, "current_version": dict(cur) if cur else None,
                                       "amendments": [dict(a) for a in amds]})
    return {"query": {"category": category, "engine_cc": engine_cc, "powertrain": powertrain, "on": on},
            "in_scope_category": category.upper() in IN_SCOPE_CATEGORIES, "count": len(mandates), "mandates": mandates}


# ---------------------------------------------------------------- documents
@app.get("/documents")
def documents(year: int | None = None, category: str | None = None, doc_class: str | None = None,
              domain: str | None = None, in_scope: bool | None = None, nature: str | None = None,
              status: str | None = None, is_current: bool | None = None, q: str | None = None,
              limit: int = Query(100, le=1000), offset: int = 0) -> dict:
    where, args = ["TRUE"], []
    if year:
        where.append("extract(year FROM doc_date) = %s")
        args.append(year)
    if category:
        where.append("vehicle_categories && %s")
        args.append([category.upper(), "ALL"])
    if doc_class:
        where.append("doc_class = %s")
        args.append(doc_class)
    if domain:
        where.append("%s = ANY(domains)")
        args.append(domain)
    if in_scope is not None:
        where.append("in_scope = %s")
        args.append(in_scope)
    if nature:
        where.append("nature = %s")
        args.append(nature)
    if status:
        where.append("status = %s")
        args.append(status)
    if is_current is not None:
        where.append("is_current = %s")
        args.append(is_current)
    if q:
        where.append("(canonical_id ILIKE %s OR official_title ILIKE %s OR subject ILIKE %s)")
        args += [f"%{q}%"] * 3
    w = " AND ".join(where)
    total = _rows(f"SELECT count(*) AS n FROM document WHERE {w}", args)[0]["n"]
    rows = _rows(f"SELECT {DOC_COLS} FROM document WHERE {w} ORDER BY doc_date DESC NULLS LAST, canonical_id "
                 f"LIMIT %s OFFSET %s", [*args, limit, offset])
    return {"total": total, "limit": limit, "offset": offset, "documents": rows}


@app.get("/documents/{canonical_id:path}")
def document(canonical_id: str) -> dict:
    with connect() as conn:
        d = conn.execute("SELECT * FROM document WHERE canonical_id=%s", (canonical_id,)).fetchone()
        if not d:
            raise HTTPException(404, f"{canonical_id} not found")
        files = conn.execute(
            """SELECT df.*, fo.sha256, fo.ext, fo.size_bytes, fo.page_count, fo.text_layer, fo.ocr_engine,
                      (SELECT json_agg(json_build_object('source', so.code, 'title', s.listing_title, 'date', s.listing_date,
                                                         'url', s.source_url))
                       FROM file_sighting s JOIN source so ON so.id=s.source_id WHERE s.file_id=fo.id) AS sightings
               FROM document_file df JOIN file_object fo ON fo.id=df.file_id WHERE df.document_id=%s
               ORDER BY df.is_best_copy DESC, df.page_from""", (d["id"],)).fetchall()
        rel_out = conn.execute("SELECT r.type, coalesce(t.canonical_id, r.to_ref) AS target, r.to_doc IS NOT NULL AS resolved, "
                               "r.details, r.method, r.requires_reapproval FROM doc_relation r LEFT JOIN document t ON t.id=r.to_doc "
                               "WHERE r.from_doc=%s ORDER BY r.type", (d["id"],)).fetchall()
        rel_in = conn.execute("SELECT r.type, f.canonical_id AS source, r.details FROM doc_relation r JOIN document f "
                              "ON f.id=r.from_doc WHERE r.to_doc=%s ORDER BY r.type, f.doc_date", (d["id"],)).fetchall()
        mandates = conn.execute("SELECT id, mandate_key, legal_basis, subject, standard_refs, vehicle_categories, "
                                "implementation_date, valid_from, valid_to, is_draft FROM mandate WHERE source_doc_id=%s "
                                "ORDER BY mandate_key", (d["id"],)).fetchall()
        flags = conn.execute("SELECT rule, details, created_at FROM quality_flag WHERE entity='document' AND entity_id=%s "
                             "AND resolved_at IS NULL", (d["id"],)).fetchall()
    out = dict(d)
    out.update(files=[dict(f) for f in files], relations_out=[dict(r) for r in rel_out],
               relations_in=[dict(r) for r in rel_in], mandates=[dict(m) for m in mandates],
               quality_flags=[dict(f) for f in flags])
    return out


@app.get("/families/{family_key:path}/versions")
def family_versions(family_key: str) -> dict:
    rows = _rows(f"SELECT {DOC_COLS} FROM document WHERE family_key=%s ORDER BY version_seq NULLS LAST, doc_date", (family_key,))
    if not rows:
        raise HTTPException(404, f"family {family_key} not found")
    with connect() as conn:
        for r in rows:
            r["files"] = [dict(x) for x in conn.execute(
                "SELECT fo.sha256, df.role, df.is_best_copy, df.page_from, df.page_to, df.part_label, "
                "(SELECT min(s.listing_date) FROM file_sighting s WHERE s.file_id=fo.id) AS listed "
                "FROM document_file df JOIN file_object fo ON fo.id=df.file_id WHERE df.document_id=%s", (r["id"],))]
    return {"family_key": family_key, "current": next((r["canonical_id"] for r in rows if r["is_current"]), None),
            "versions": rows}


@app.get("/changes")
def changes(since: datetime | None = None, limit: int = Query(200, le=2000)) -> dict:
    rows = _rows("SELECT e.*, d.canonical_id FROM change_event e LEFT JOIN document d ON d.id=e.document_id "
                 "WHERE e.detected_at >= %s ORDER BY e.detected_at DESC LIMIT %s",
                 (since or datetime(1970, 1, 1), limit))
    return {"since": since, "count": len(rows), "changes": rows}


@app.get("/search")
def search(q: str, category: str | None = None, in_scope: bool | None = True, is_current: bool | None = None,
           doc_class: str | None = None, limit: int = Query(10, le=50)) -> dict:
    with connect() as conn:
        return chunk_search(conn, q, category, in_scope, is_current, doc_class, limit)


# ---------------------------------------------------------------- vendor share pack
def share_pack_documents(conn, category: str, on: date, technical_only: bool = True) -> list[dict]:
    cats = [category.upper(), "ALL"]
    return [dict(r) for r in conn.execute(
        f"""WITH m AS (
              SELECT DISTINCT source_doc_id AS id FROM mandate WHERE NOT is_draft AND vehicle_categories && %s
                AND (valid_to IS NULL OR valid_to > %s)
              UNION SELECT DISTINCT unnest(standard_doc_ids) FROM mandate WHERE NOT is_draft AND vehicle_categories && %s
                AND (valid_to IS NULL OR valid_to > %s)
              UNION SELECT id FROM document WHERE vehicle_categories && %s AND is_current AND doc_class LIKE 'AIS_%%'
            )
            SELECT {', '.join('d.' + c.strip() for c in DOC_COLS.split(','))}
            FROM document d JOIN m ON m.id=d.id
            WHERE d.doc_class <> 'OFF_TOPIC' {"AND (d.nature='technical' OR d.nature IS NULL)" if technical_only else ""}
            ORDER BY d.doc_class, d.canonical_id""", (cats, on, cats, on, cats)).fetchall()]


@app.get("/share-pack")
def share_pack(category: str, on: date | None = None, technical_only: bool = True) -> StreamingResponse:
    """Zip of best-copy originals + manifest.csv for a vehicle category."""
    on = on or date.today()
    buf = io.BytesIO()
    with connect() as conn:
        docs = share_pack_documents(conn, category, on, technical_only)
        if not docs:
            raise HTTPException(404, f"no documents for category {category}")
        manifest = io.StringIO()
        w = csv.writer(manifest)
        w.writerow(["canonical_id", "doc_class", "title", "doc_date", "status", "family_key", "version_seq", "is_current",
                    "vehicle_categories", "file_in_zip", "sha256", "pages", "role", "source_urls"])
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            added: set[str] = set()
            for d in docs:
                for f in conn.execute(
                        """SELECT fo.sha256, fo.ext, fo.storage_path, df.page_from, df.page_to, df.role,
                                  (SELECT string_agg(DISTINCT s.source_url, ' ') FROM file_sighting s WHERE s.file_id=fo.id) AS urls
                           FROM document_file df JOIN file_object fo ON fo.id=df.file_id
                           WHERE df.document_id=%s AND df.is_best_copy""", (d["id"],)):
                    safe = "".join(ch if ch.isalnum() or ch in "-_.()" else "_" for ch in d["canonical_id"])
                    name = f"{d['doc_class']}/{safe}__{f['sha256'][:12]}.{f['ext']}"
                    if f["sha256"] not in added and Path(f["storage_path"]).exists():
                        z.write(f["storage_path"], name)
                        added.add(f["sha256"])
                    w.writerow([d["canonical_id"], d["doc_class"], d["official_title"] or d["subject"], d["doc_date"],
                                d["status"], d["family_key"], d["version_seq"], d["is_current"],
                                " ".join(d["vehicle_categories"] or []), name, f["sha256"],
                                f"{f['page_from']}-{f['page_to']}", f["role"], f["urls"]])
            z.writestr("manifest.csv", manifest.getvalue())
    buf.seek(0)
    fname = f"regtrack_share_pack_{category.upper()}_{on.isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
