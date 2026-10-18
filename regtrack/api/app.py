"""Read-only API. No LLM calls at read time except embedding the search query.
Every query shows one country: ?country= if given, else the COUNTRY setting (regtrack/country.py).
Reads the v4B tables through regtrack/api/sql.py, which keeps the response shape the dashboard was built on.

    uvicorn regtrack.api.app:app      (or: python -m regtrack.cli api)
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from regtrack import country
from regtrack.api import sql as S
from regtrack.api.params import CountryParam, resolve_country
from regtrack.db import connect
from regtrack.models.enums import IN_SCOPE_CATEGORIES
from regtrack.pipeline.search import search as chunk_search
from regtrack.storage import open_local

app = FastAPI(title="RegTrack India", version="0.1.0",
              description="Indian vehicle regulations (ARAI AIS, MoRTH Gazette, e-Gazette, India Code) - read only")
# the dashboard (Vite dev server / preview) calls this API from the browser
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                                                  "http://localhost:4173", "http://127.0.0.1:4173"],
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"], expose_headers=["Content-Disposition"])

DOC_COLS_BASE = ("id, canonical_id, doc_class, series, number, year, part, revision, amendment_no, corrigendum_no, "
                 "family_key, version_seq, is_current, official_title, subject, issuer, status, doc_date, "
                 "doc_date_precision, nature, vehicle_categories, usage, powertrains, domains, in_scope")
# ai_pending: the Qwen pass has not run yet for this document (deterministic fields only)
DOC_COLS = DOC_COLS_BASE + ", coalesce((extraction->>'llm_pending')::boolean, false) AS ai_pending"


def _rows(sql: str, args: list | tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


@app.get("/health")
def health() -> dict:
    return {"ok": True, "documents": _rows(f"SELECT count(*) AS n FROM regulations g WHERE {country.region_sql('g')}")[0]["n"]}


# ---------------------------------------------------------------- vehicle view
COND_SQL = """
  AND (m.conditions->'{k}'->>'lte' IS NULL OR %s::numeric IS NULL OR (m.conditions->'{k}'->>'lte')::numeric >= %s::numeric)
  AND (m.conditions->'{k}'->>'lt'  IS NULL OR %s::numeric IS NULL OR (m.conditions->'{k}'->>'lt')::numeric  >  %s::numeric)
  AND (m.conditions->'{k}'->>'gte' IS NULL OR %s::numeric IS NULL OR (m.conditions->'{k}'->>'gte')::numeric <= %s::numeric)
  AND (m.conditions->'{k}'->>'gt'  IS NULL OR %s::numeric IS NULL OR (m.conditions->'{k}'->>'gt')::numeric  <  %s::numeric)"""


@app.get("/vehicles/applicable")
def vehicles_applicable(category: str = Query(..., examples=["L2"]), engine_cc: float | None = None,
                        power_kw: float | None = None, gvw_kg: float | None = None, seats: float | None = None,
                        powertrain: str | None = None, usage: str | None = None, on: date | None = None,
                        include_drafts: bool = False, include_future: bool = False, cc: CountryParam = None) -> dict:
    """Mandates for a vehicle on a date, with the standards behind each and their current versions."""
    cc = resolve_country(cc)
    on = on or date.today()
    cats = [category.upper(), "ALL"]
    args: list = [cats]
    sql = ["SELECT m.*, d.external_code AS source_canonical_id, d.title AS source_title "
           f"FROM {S.mandates(cc)} m JOIN regulations d ON d.id=m.source_doc_id WHERE m.vehicle_categories && %s"]
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
    sql.append("ORDER BY m.implementation_date NULLS LAST, m.legal_basis, m.id")
    with connect() as conn:
        mandates = [dict(r) for r in conn.execute(" ".join(sql), args).fetchall()]
        for m in mandates:
            m["standards"] = []
            for ref in m["standard_refs"] or []:
                fam = ref.split("(Rev")[0] if ref.startswith("AIS-") else None
                cur = conn.execute(f"SELECT {DOC_COLS} FROM {S.docs(cc)} d WHERE family_key=%s AND is_current",
                                   (fam,)).fetchone() if fam else None
                amds = conn.execute("SELECT external_code AS canonical_id, published_date AS doc_date FROM regulations g "
                                    f"WHERE family_key=%s AND {country.region_sql('g', cc)} "
                                    "AND local_class IN ('AIS_AMENDMENT','AIS_CORRIGENDUM') ORDER BY version_seq",
                                    (fam,)).fetchall() if fam else []
                m["standards"].append({"ref": ref, "current_version": dict(cur) if cur else None,
                                       "amendments": [dict(a) for a in amds]})
    return {"query": {"category": category, "engine_cc": engine_cc, "powertrain": powertrain, "on": on},
            "in_scope_category": category.upper() in IN_SCOPE_CATEGORIES, "count": len(mandates), "mandates": mandates}


# ---------------------------------------------------------------- documents
@app.get("/documents")
def documents(year: int | None = None, category: str | None = None, doc_class: str | None = None,
              domain: str | None = None, in_scope: bool | None = None, nature: str | None = None,
              status: str | None = None, is_current: bool | None = None, q: str | None = None,
              limit: int = Query(100, le=1000), offset: int = 0, cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    where, args = ["true"], []
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
    total = _rows(f"SELECT count(*) AS n FROM {S.docs(cc)} d WHERE {w}", args)[0]["n"]
    rows = _rows(f"SELECT {DOC_COLS} FROM {S.docs(cc)} d WHERE {w} ORDER BY doc_date DESC NULLS LAST, canonical_id "
                 f"LIMIT %s OFFSET %s", [*args, limit, offset])
    return {"total": total, "limit": limit, "offset": offset, "documents": rows}


@app.get("/documents/{canonical_id:path}")
def document(canonical_id: str, cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        d = conn.execute(
            f"""SELECT d.*, dc.sub_type, CASE WHEN g.title_native IS NOT NULL THEN g.title END AS title_en,
                       coalesce((SELECT array_agg(DISTINCT u ORDER BY u) FROM regulation_vehicle_categories l
                                 JOIN vehicle_categories vc ON vc.id=l.vehicle_category_id, unnest(vc.un_codes) u
                                 WHERE l.regulation_id=d.id), '{{}}') AS vehicle_categories_un
                FROM {S.docs(cc)} d JOIN regulations g ON g.id=d.id
                LEFT JOIN document_classes dc ON dc.region_id=g.region_id AND dc.code=g.local_class
                WHERE d.canonical_id=%s""", (canonical_id,)).fetchone()
        if not d:
            raise HTTPException(404, f"{canonical_id} not found")
        files = conn.execute(
            """SELECT p.regulation_id AS document_id, p.document_id AS file_id, p.page_from, p.page_to,
                      (p.language_pages->'en'->>0)::int AS english_page_from, (p.language_pages->'en'->>1)::int AS english_page_to,
                      p.part_label, CASE p.role WHEN 'other_language_only' THEN 'hindi_only' ELSE p.role END AS role,
                      p.is_best_copy, p.language_pages, fo.checksum_sha256 AS sha256, fo.file_ext AS ext, fo.file_size_bytes AS size_bytes,
                      fo.page_count, fo.text_layer, fo.ocr_engine,
                      (SELECT json_agg(json_build_object('source', so.code, 'title', s.listing_title, 'date', s.listing_date,
                                                         'url', s.source_url) ORDER BY s.id)
                       FROM raw_ingestion_records s JOIN sources so ON so.id=s.source_id WHERE s.document_id=fo.id) AS sightings
               FROM document_parts p JOIN documents fo ON fo.id=p.document_id WHERE p.regulation_id=%s
               ORDER BY p.is_best_copy DESC, p.page_from""", (d["id"],)).fetchall()
        rel_out = conn.execute("SELECT r.type, coalesce(t.external_code, r.to_ref) AS target, "
                               "r.to_regulation_id IS NOT NULL AS resolved, r.details, r.method, r.requires_reapproval "
                               "FROM regulation_relations r LEFT JOIN regulations t ON t.id=r.to_regulation_id "
                               "WHERE r.from_regulation_id=%s ORDER BY r.type, r.id", (d["id"],)).fetchall()
        rel_in = conn.execute("SELECT r.type, f.external_code AS source, r.details FROM regulation_relations r "
                              "JOIN regulations f ON f.id=r.from_regulation_id WHERE r.to_regulation_id=%s "
                              "ORDER BY r.type, f.published_date, r.id", (d["id"],)).fetchall()
        mandates = conn.execute("SELECT id, mandate_key, legal_basis, subject, standard_refs, vehicle_categories, "
                                f"implementation_date, valid_from, valid_to, is_draft FROM {S.mandates(cc)} m "
                                "WHERE source_doc_id=%s ORDER BY mandate_key", (d["id"],)).fetchall()
        flags = conn.execute("SELECT rule, details, created_at FROM quality_flags WHERE entity='regulation' "
                             "AND entity_id=%s AND resolved_at IS NULL", (d["id"],)).fetchall()
    out = dict(d)
    out["ai_pending"] = bool((d["extraction"] or {}).get("llm_pending"))
    out.update(files=[dict(f) for f in files], relations_out=[dict(r) for r in rel_out],
               relations_in=[dict(r) for r in rel_in], mandates=[dict(m) for m in mandates],
               quality_flags=[dict(f) for f in flags])
    return out


@app.get("/families/{family_key:path}/versions")
def family_versions(family_key: str, cc: CountryParam = None) -> dict:
    rows = _rows(f"SELECT {DOC_COLS} FROM {S.docs(resolve_country(cc))} d WHERE family_key=%s "
                 "ORDER BY version_seq NULLS LAST, doc_date", (family_key,))
    if not rows:
        raise HTTPException(404, f"family {family_key} not found")
    with connect() as conn:
        for r in rows:
            r["files"] = [dict(x) for x in conn.execute(
                "SELECT fo.checksum_sha256 AS sha256, CASE p.role WHEN 'other_language_only' THEN 'hindi_only' "
                "ELSE p.role END AS role, p.is_best_copy, p.page_from, p.page_to, p.part_label, "
                "(SELECT min(s.listing_date) FROM raw_ingestion_records s WHERE s.document_id=fo.id) AS listed "
                "FROM document_parts p JOIN documents fo ON fo.id=p.document_id WHERE p.regulation_id=%s", (r["id"],))]
    return {"family_key": family_key, "current": next((r["canonical_id"] for r in rows if r["is_current"]), None),
            "versions": rows}


@app.get("/changes")
def changes(since: datetime | None = None, limit: int = Query(200, le=2000), cc: CountryParam = None) -> dict:
    rows = _rows(f"SELECT e.id, e.event_type, e.document_id, e.mandate_id, e.detected_at, e.summary, e.impact, e.details, "
                 f"e.review_status, e.country, d.external_code AS canonical_id FROM {S.changes(resolve_country(cc))} e "
                 "LEFT JOIN regulations d ON d.id=e.document_id WHERE e.detected_at >= %s "
                 "ORDER BY e.detected_at DESC LIMIT %s",
                 (since or datetime(1970, 1, 1), limit))
    return {"since": since, "count": len(rows), "changes": rows}


@app.get("/search")
def search(q: str, category: str | None = None, in_scope: bool | None = None, is_current: bool | None = None,
           doc_class: str | None = None, limit: int = Query(10, le=50), cc: CountryParam = None) -> dict:
    cc = resolve_country(cc)
    with connect() as conn:
        return chunk_search(conn, q, category, in_scope, is_current, doc_class, limit, cc=cc)


# ---------------------------------------------------------------- vendor share pack
def share_pack_documents(conn, category: str, on: date, technical_only: bool = True, engine_cc: float | None = None,
                         powertrain: str | None = None, usage: str | None = None, cc: str | None = None) -> list[dict]:
    """Documents behind the vehicle's mandates (in force on `on` or upcoming) + current AIS standards for the category."""
    cc = country.code(cc)
    sel = vehicles_applicable(category=category, engine_cc=engine_cc, power_kw=None, gvw_kg=None, seats=None,
                              powertrain=powertrain, usage=usage, on=on, include_drafts=False, include_future=True, cc=cc)
    ids = {m["source_doc_id"] for m in sel["mandates"]} | {i for m in sel["mandates"] for i in (m["standard_doc_ids"] or [])}
    cats = [category.upper(), "ALL"]
    return [dict(r) for r in conn.execute(
        f"""SELECT {', '.join('d.' + c.strip() for c in DOC_COLS_BASE.split(','))}
            FROM {S.docs(cc)} d
            WHERE (d.id = ANY(%s) OR (d.vehicle_categories && %s AND d.is_current AND d.doc_class LIKE 'AIS_%%'))
              AND d.doc_class <> 'OFF_TOPIC'
              {"AND (d.nature='technical' OR d.nature IS NULL)" if technical_only else ""}
            ORDER BY d.doc_class, d.canonical_id""", (list(ids), cats)).fetchall()]


@app.get("/share-pack")
def share_pack(category: str, on: date | None = None, engine_cc: float | None = None, powertrain: str | None = None,
               usage: str | None = None, technical_only: bool = True, cc: CountryParam = None) -> StreamingResponse:
    """Zip of best-copy originals + manifest.csv for a vehicle selection (category [+ cc, powertrain, usage])."""
    cc = resolve_country(cc)
    on = on or date.today()
    buf = io.BytesIO()
    with connect() as conn:
        docs = share_pack_documents(conn, category, on, technical_only, engine_cc, powertrain, usage, cc=cc)
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
                        """SELECT fo.checksum_sha256 AS sha256, fo.file_ext AS ext, fo.storage_path, p.page_from, p.page_to,
                                  CASE p.role WHEN 'other_language_only' THEN 'hindi_only' ELSE p.role END AS role,
                                  (SELECT string_agg(DISTINCT s.source_url, ' ') FROM raw_ingestion_records s
                                   WHERE s.document_id=fo.id) AS urls
                           FROM document_parts p JOIN documents fo ON fo.id=p.document_id
                           WHERE p.regulation_id=%s AND p.is_best_copy""", (d["id"],)).fetchall():
                    safe = "".join(ch if ch.isalnum() or ch in "-_.()" else "_" for ch in d["canonical_id"])
                    name = f"{d['doc_class']}/{safe}__{f['sha256'][:12]}.{f['ext']}"
                    local = open_local(f["storage_path"])
                    if f["sha256"] not in added and local.exists():
                        z.write(local, name)
                        added.add(f["sha256"])
                    w.writerow([d["canonical_id"], d["doc_class"], d["official_title"] or d["subject"], d["doc_date"],
                                d["status"], d["family_key"], d["version_seq"], d["is_current"],
                                " ".join(d["vehicle_categories"] or []), name, f["sha256"],
                                f"{f['page_from']}-{f['page_to']}", f["role"], f["urls"]])
            z.writestr("manifest.csv", manifest.getvalue())
    buf.seek(0)
    parts = [category.upper()] + ([f"{int(engine_cc)}cc"] if engine_cc else []) + ([powertrain] if powertrain else []) \
        + ([usage] if usage else [])
    fname = f"regtrack_share_pack_{'_'.join(parts)}_{on.isoformat()}.zip"
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------------------------------------------------------------- dashboard helpers
@app.get("/files/{sha256}")
def original_file(sha256: str, download: bool = False) -> FileResponse:
    """The original file exactly as stored (write-once); inline by default, ?download=true to save it."""
    rows = _rows("SELECT checksum_sha256 AS sha256, file_ext AS ext, mime_type AS mime, storage_path FROM documents "
                 "WHERE checksum_sha256=%s", (sha256,))
    if not rows:
        raise HTTPException(404, "unknown file")
    f = rows[0]
    p = open_local(f["storage_path"])
    if not p.exists():
        raise HTTPException(410, "original not in storage")
    media = {"pdf": "application/pdf", "htm": "text/html", "csv": "text/csv",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}.get(f["ext"]) \
        or f["mime"] or "application/octet-stream"
    return FileResponse(p, media_type=media, filename=f"{sha256[:16]}.{f['ext']}",
                        content_disposition_type="attachment" if download else "inline")


@app.get("/families")
def families(q: str | None = None, limit: int = Query(200, le=1000), cc: CountryParam = None) -> dict:
    """Version families (AIS code, S.O. 1365 master table, TAP, ...) with their current version."""
    rows = _rows(
        """SELECT family_key, count(*) AS versions, max(doc_date) AS latest,
                  max(canonical_id) FILTER (WHERE is_current) AS current,
                  max(coalesce(official_title, subject)) FILTER (WHERE is_current) AS title,
                  bool_or(in_scope) AS in_scope
           FROM """ + S.docs(resolve_country(cc)) + """ d WHERE family_key IS NOT NULL
             AND (%s::text IS NULL OR family_key ILIKE %s OR coalesce(official_title, subject, '') ILIKE %s)
           GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT %s""", (q, f"%{q}%", f"%{q}%", limit))
    return {"count": len(rows), "families": rows}


@app.get("/meta")
def meta(cc: CountryParam = None) -> dict:
    """Filter options and headline numbers for the dashboard (one country)."""
    cc = resolve_country(cc)
    doc = country.region_sql("g", cc)
    with connect() as conn:
        stats = dict(conn.execute(
            f"""SELECT (SELECT count(*) FROM regulations g WHERE local_class<>'OFF_TOPIC' AND {doc}) AS documents,
                      (SELECT count(*) FROM regulations g WHERE in_scope AND {doc}) AS in_scope,
                      (SELECT count(*) FROM {S.mandates(cc)} m WHERE valid_to IS NULL AND NOT is_draft) AS open_mandates,
                      (SELECT count(*) FROM {S.changes(cc)} e WHERE detected_at > now() - interval '30 days') AS changes_30d,
                      (SELECT count(*) FROM regulations g WHERE (extraction->>'llm_pending')::boolean AND {doc}) AS ai_pending,
                      (SELECT max(finished_at) FROM {S.runs(cc)} r WHERE status IN ('ok','partial')) AS last_crawl""").fetchone())
        years = [dict(r) for r in conn.execute(
            "SELECT extract(year FROM published_date)::int AS year, count(*) AS n FROM regulations g "
            f"WHERE published_date IS NOT NULL AND local_class<>'OFF_TOPIC' AND {doc} GROUP BY 1 ORDER BY 1 DESC")]
        classes = [dict(r) for r in conn.execute(f"SELECT local_class AS doc_class, count(*) AS n FROM regulations g "
                                                 f"WHERE {doc} GROUP BY 1 ORDER BY 2 DESC, 1")]
        domains = [dict(r) for r in conn.execute(
            f"""SELECT lower(d.code) AS code, d.name AS label,
                       (SELECT count(*) FROM regulation_domains l JOIN regulations g ON g.id=l.regulation_id
                        WHERE l.domain_id=d.id AND {doc}) AS n
                FROM domains d ORDER BY 3 DESC""")]
        cats = [dict(r) for r in conn.execute(
            "SELECT code, label, code = ANY(%s) AS in_scope, un_codes FROM vehicle_categories v "
            f"WHERE {country.region_sql('v', cc)} ORDER BY code", (sorted(IN_SCOPE_CATEGORIES),))]
    return {"country": cc, "stats": stats, "years": years, "doc_classes": classes, "domains": domains, "categories": cats,
            "powertrains": ["petrol", "diesel", "cng", "lpg", "ethanol_flex", "hybrid", "bev", "hydrogen"],
            "usage": ["private", "transport"]}


# approved portal design (v2): dashboard, library, change monitor, compliance, impact, AI, reports, alerts, admin
from regtrack.api.portal import router as portal_router  # noqa: E402
from regtrack.api.workspace import router as workspace_router  # noqa: E402

app.include_router(portal_router)
app.include_router(workspace_router)  # teams and users, watches, Ask-AI history, report schedules
