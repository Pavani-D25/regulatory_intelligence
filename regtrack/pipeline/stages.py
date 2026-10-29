"""DB stages for one file: text -> classified (incl. split). Each function runs inside one transaction and
writes only what changed, so re-running with no upstream change writes zero rows.

Stage map (documents.stage, one stored file):
  downloaded --text--> text --classify+split--> classified --extract--> parsed --link--> linked
  --chunk--> chunked --embed--> embedded -> done
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import psycopg

from regtrack import country
from regtrack.db import Jsonb
from regtrack.models import model_for
from regtrack.models.enums import DocClass, FlagRule, Role
from regtrack.pipeline import ocr
from regtrack.pipeline import patterns as P
from regtrack.pipeline import repo as R
from regtrack.pipeline.analysis import FileAnalysis, identify
from regtrack.pipeline.classify import FileCtx
from regtrack.pipeline.dbutil import add_flag, set_stage
from regtrack.pipeline.identity import Identity, parse_arai_code
from regtrack.pipeline.split import ais_table_ref, amendment_gaps, split_ais, tap_part_label
from regtrack.pipeline.text import (
    PageText,
    extract_cached,
    garbled_pages,
    language_mix,
    load_pages,
    save_pages,
)
from regtrack.storage import open_local

log = logging.getLogger(__name__)
LOW_OCR = 0.6
OCR_PARTIAL_COUNTRIES = {"TH", "MY"}  # OCR the scanned pages of partly scanned PDFs too


# ====================================================================== text
def stage_text(conn: psycopg.Connection, f: dict, allow_ocr: bool = True) -> str:
    """Extract page text (cached by sha), OCR scanned pages, fill the documents row. Returns the new stage."""
    path = open_local(f["storage_path"])
    meta = extract_cached(f["sha256"], path, f["ext"])
    # PostgreSQL JSONB rejects NUL characters (seen in 'Adobe PSL ... for Canon\x00' producers)
    meta["pdf_meta"] = {k: v.replace("\x00", "") if isinstance(v, str) else v for k, v in (meta["pdf_meta"] or {}).items()}
    pages = load_pages(f["sha256"])
    engine, conf = f.get("ocr_engine"), f.get("ocr_confidence")
    if meta["error"]:
        R.update_file(conn, f["id"], {"pdf_meta": Jsonb({**meta["pdf_meta"], "error": meta["error"]})})
        set_stage(conn, f["id"], "failed", meta["error"][:500])
        return "failed"
    # Thailand / Malaysia: also the scanned pages of a PDF that has some text (TIS 2721: 133 of 141 pages are scans).
    # India keeps OCRing only fully scanned PDFs (its 319 partly scanned files are a separate, re-validated step).
    partial = (f.get("country") or "").upper() in OCR_PARTIAL_COUNTRIES
    need_ocr = (f["ext"] == "pdf" and (not meta["text_layer"] or partial) and meta["scanned_pages"] and not engine)
    if need_ocr and allow_ocr:
        eng = ocr.pick_engine(f.get("country"))
        if eng and ocr.can_ocr(eng, f.get("country")):
            engine, conf = ocr_pages(f, pages, meta["scanned_pages"], eng)
    lm = language_mix(pages)
    values = {"page_count": meta["page_count"], "text_layer": meta["text_layer"],
              "scanned_pages": meta["scanned_pages"], "language_mix": Jsonb(lm), "pdf_meta": Jsonb(meta["pdf_meta"]),
              "ocr_engine": engine, "ocr_confidence": conf, "mime": f.get("mime")}
    R.update_file(conn, f["id"], values)
    if engine and conf is not None and float(conf) < LOW_OCR:
        add_flag(conn, "document", f["id"], FlagRule.LOW_OCR_CONFIDENCE, {"engine": engine, "confidence": float(conf)})
    if need_ocr and not engine:
        add_flag(conn, "document", f["id"], FlagRule.OCR_PENDING, {"scanned_pages": len(meta["scanned_pages"])})
    set_stage(conn, f["id"], "text")
    return "text"


def ocr_pages(f: dict, pages: list[PageText], targets: list[int], engine: str) -> tuple[str | None, float | None]:
    """OCR the target pages in place (page text replaced when OCR gives more text). Saves the page store."""
    confs = []
    path = open_local(f["storage_path"])
    for pg in pages:
        if pg.page not in targets or pg.ocr:
            continue
        try:
            text, c = ocr.ocr_page(path, pg.page, engine, f.get("country"))
        except Exception as e:  # noqa: BLE001  one bad page must not stop the file
            log.warning("OCR failed %s p%s: %s", f["sha256"][:12], pg.page, e)
            continue
        if len(text.strip()) > pg.chars:
            pg.text, pg.ocr = text, engine
            pg.analyse()
            confs.append(c)
    attempted = any(p.page in targets for p in pages)
    if not confs:
        return (engine, 0.0) if attempted else (None, None)
    save_pages(f["sha256"], pages)
    return engine, round(sum(confs) / len(confs), 3)


# ====================================================================== classify (+ split)
def file_ctx(conn: psycopg.Connection, f: dict, pages: list[PageText] | None = None) -> FileCtx:
    rows = R.listings_of_file(conn, f["id"])
    folders, names, listings = [], [], []
    for r in rows:
        raw = r["listing_raw"] or {}
        if raw.get("folder") and raw["folder"] not in folders:
            folders.append(raw["folder"])
        if r["code"] == "LOCAL_SEED":
            names.append(r["listing_title"] or "")
        else:
            listings.append({"source": r["code"], "title": r["listing_title"], "date": r["listing_date"],
                             "category": r["listing_category"], "raw": raw})
            if r["code"] != "LOCAL_SEED" and raw.get("file_name"):
                names.append(raw["file_name"])
    if not folders:  # live-crawled files: map the source to the seed folder it would have landed in
        src = {x["source"] for x in listings}
        folders = ["07_AIS_Published_Standards" if "ARAI_AIS" in src else
                   "11_CMVR_TAP_Documents" if "ARAI_TAP" in src else
                   "02_CMVR_Amendments_Notifications" if "INDIACODE" in src else
                   "06_MoRTH_Circulars_Orders" if any((x.get("category") or "").startswith(("orders", "guidelines"))
                                                      for x in listings) else "05_MoRTH_Gazette_Notifications"]
    pages = pages if pages is not None else load_pages(f["sha256"])
    return FileCtx(f["id"], f["sha256"], f["ext"], folders, names, pages, f["page_count"] or len(pages),
                   bool(f["text_layer"]), list(f["scanned_pages"] or []), listings)


def ready_for_classify(f: dict) -> bool:
    """Scans wait at 'text' until OCR has run (or no OCR engine exists on this machine)."""
    if not f["page_count"]:
        return True  # empty or broken file: nothing to OCR
    return not (f["ext"] == "pdf" and f["text_layer"] is False and not f["ocr_engine"])


def stage_classify(conn: psycopg.Connection, f: dict) -> str:
    pages = load_pages(f["sha256"])
    ctx = file_ctx(conn, f, pages)
    fa = identify(ctx)
    # a notification whose header page has a garbled text layer: OCR the first pages once and retry
    if fa.cls.doc_class.is_notification and fa.identity is None and f["ext"] == "pdf":
        bad = [p for p in garbled_pages(pages[:4]) if p <= 4]
        eng = ocr.pick_engine(f.get("country")) if bad else None
        if eng:
            e, c = ocr_pages(f, pages, bad, eng)
            if e:
                ctx = file_ctx(conn, f, pages)
                fa = identify(ctx)
                R.update_file(conn, f["id"], {"ocr_engine": f.get("ocr_engine") or e, "language_mix": Jsonb(language_mix(pages))})
    write_documents(conn, f, ctx, fa)
    R.mark_listings_classified(conn, f["id"])
    set_stage(conn, f["id"], "classified")
    return "classified"


# ---------------------------------------------------------------------- document writes
def upsert_document(conn: psycopg.Connection, canonical_id: str, values: dict) -> tuple[int, bool]:
    """Insert a document (regulation) or fill the empty fields of an existing one. Returns (id, created)."""
    row = R.find_document(conn, canonical_id)
    if row is None:
        return R.insert_document(conn, canonical_id, values), True
    fill = {}
    for k, v in values.items():
        cur = row[k]
        empty = cur is None or cur == [] or cur == {}
        if k == "data" and isinstance(cur, dict) and isinstance(v, dict):
            # keep every existing key (later stages own them); only fill keys that are missing or empty
            merged = dict(cur)
            for kk, vv in v.items():
                if vv not in (None, [], {}) and cur.get(kk) in (None, [], {}):
                    merged[kk] = vv
            if merged != cur:
                fill[k] = Jsonb(merged)
        elif empty and v not in (None, [], {}):
            fill[k] = v
    if fill:
        R.update_document(conn, row["id"], fill, touch=True)
    return row["id"], False


def attach(conn: psycopg.Connection, doc_id: int, file_id: int, page_from: int = 1, page_to: int | None = None,
           eng: tuple[int | None, int | None] = (None, None), part_label: str | None = None,
           role: str = Role.MAIN) -> None:
    R.attach(conn, doc_id, file_id, page_from, page_to, eng, part_label, role)


def _eng_range(pages: list[PageText], a: int, b: int) -> tuple[int | None, int | None]:
    e = [p.page for p in pages if a <= p.page <= b and p.is_english]
    return (e[0], e[-1]) if e else (None, None)


def synthetic_id(prefix: str, sha: str) -> str:
    return f"{prefix}-{sha[:16]}"


def base_values(fa: FileAnalysis, dc: DocClass, ident: Identity | None) -> dict:
    v = {"doc_class": dc.value, "status": fa.cls.status, "issuer": fa.cls.issuer, "nature": fa.cls.nature,
         "relevance": fa.cls.relevance}
    if ident:
        v.update({"series": ident.series, "number": ident.number, "year": ident.year, "part": ident.part,
                  "revision": ident.revision, "family_key": ident.family_key, "doc_date": ident.doc_date,
                  "doc_date_precision": ident.doc_date_precision})
    return {k: val for k, val in v.items() if val is not None}


def write_documents(conn: psycopg.Connection, f: dict, ctx: FileCtx, fa: FileAnalysis) -> list[int]:
    dc = fa.cls.doc_class
    pages = ctx.pages
    n = ctx.page_count or (pages[-1].page if pages else 1)
    ident = fa.identity
    doc_ids: list[int] = []
    flags: list[tuple[str, dict]] = []

    if dc in (DocClass.AIS_STANDARD, DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM, DocClass.SAFETY_STANDARD_LEGACY):
        doc_ids += write_ais(conn, f, ctx, fa)
    elif dc == DocClass.AIS_FORM_TABLE:
        codes = [x.get("title") or "" for x in ctx.listings if x.get("source") == "ARAI_AIS"]
        ref = ais_table_ref(ctx.names, codes, ctx.english)
        arai = parse_arai_code(codes[0]) if codes else {}
        base = P.ais_canonical(arai.get("code") or 7, arai.get("part"), arai.get("rev") or 5)
        cid = f"{base}/Table-{ref}" if ref else synthetic_id("AIS-TABLE", ctx.sha)
        data = {"table_ref": ref, "annex_of": base, "title": (ctx.english.strip().splitlines() or [None])[0]}
        did, _ = upsert_document(conn, cid, {**base_values(fa, dc, None), "family_key": f"{base}/Tables",
                                             "data": _valid(dc, data)})
        attach(conn, did, f["id"], 1, n, role=Role.ANNEX_TABLE)
        doc_ids.append(did)
    elif dc in (DocClass.AIS_DRAFT, DocClass.AIS_INTERPRETATION):
        base = ident.canonical_id if ident else None
        suffix = "Draft" if dc == DocClass.AIS_DRAFT else "Interpretation"
        cid = f"{base}/{suffix}-{ctx.sha[:8]}" if base else synthetic_id(f"AIS-{suffix.upper()}", ctx.sha)
        data = draft_data(ctx, ident) if dc == DocClass.AIS_DRAFT else {"interprets": base}
        vals = {**base_values(fa, dc, ident), "data": _valid(dc, data)}
        vals.pop("family_key", None)  # drafts never take part in the version order
        did, _ = upsert_document(conn, cid, vals)
        attach(conn, did, f["id"], 1, n, eng=_eng_range(pages, 1, n))
        doc_ids.append(did)
    elif dc in (DocClass.TAP_DOCUMENT, DocClass.TAP_AMENDMENT):
        cid = ident.canonical_id if ident else "TAP-115/116(Issue.4)"
        did, _ = upsert_document(conn, cid, {**base_values(fa, DocClass.TAP_DOCUMENT, ident),
                                             "doc_class": DocClass.TAP_DOCUMENT.value, "issuer": "MoRTH",
                                             "family_key": "TAP-115/116"})
        attach(conn, did, f["id"], 1, n, eng=_eng_range(pages, 1, n), part_label=tap_part_label(ctx.name, ctx.english))
        doc_ids.append(did)
    else:
        if dc.is_notification:
            cid = ident.canonical_id if ident and ident.year else synthetic_id("NOTIF", ctx.sha)
            if not (ident and ident.year):
                flags.append((FlagRule.IDENTITY_NOT_FOUND, {"reason": "no G.S.R./S.O. heading in English text",
                                                            "scan": not ctx.text_layer}))
        elif ident and ident.canonical_id and dc in (DocClass.FORM_TEMPLATE, DocClass.TIS_STANDARD, DocClass.MY_GUIDELINE, DocClass.MY_FORM, DocClass.MY_ACT,
                                                                         DocClass.MY_SUBSIDIARY_LEGISLATION) + (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE) or (ident and ident.kind == "notification"):
            cid = ident.canonical_id
        else:
            cid = synthetic_id("DOC", ctx.sha)
            if dc == DocClass.TIS_STANDARD:
                flags.append((FlagRule.IDENTITY_NOT_FOUND, {"reason": "no มอก. number on the TISI page"}))
            elif dc in (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE):
                flags.append((FlagRule.IDENTITY_NOT_FOUND, {"reason": "no Thai law number / title on the first page"}))
        data = notification_header_data(fa) if dc.is_notification or (ident and ident.kind == "notification") else {}
        if dc == DocClass.FORM_TEMPLATE:
            data = form_data(ctx, ident)
        vals = {**base_values(fa, dc, ident), "official_title": fa.official_title, "data": _valid(dc, data)}
        vals = {k: v for k, v in vals.items() if v is not None}
        existing = R.find_document(conn, cid)
        did, created = upsert_document(conn, cid, vals)
        if existing and existing["doc_class"] != dc.value:
            flags.append((FlagRule.DUPLICATE_IDENTITY_DIFF_HEADER,
                          {"canonical_id": cid, "classes": sorted({existing["doc_class"], dc.value}), "file": ctx.sha}))
        role = Role.HINDI_ONLY if (pages and not any(p.is_english for p in pages) and dc.is_notification) else Role.MAIN
        if ident and ident.kind == "tis-link":
            # a full text whose text layer is unreadable (old scan, broken font): kept with its standard, never
            # its readable copy
            role = Role.HISTORICAL_COPY
            flags.append((FlagRule.IDENTITY_NOT_FOUND, {"reason": "full-text PDF has no readable มอก. number; "
                                                                  "attached by the link on its TISI page", "file": ctx.sha}))
        e = _eng_range(pages, 1, n)
        attach(conn, did, f["id"], 1, n, eng=e, role=role)
        doc_ids.append(did)
        if dc == DocClass.OFF_TOPIC:
            flags.append((FlagRule.OFF_TOPIC, {"reason": fa.cls.reason}))

    for m in fa.title_mismatch:
        add_flag(conn, "document", f["id"], FlagRule.TITLE_FILE_MISMATCH, m)
    for m in fa.placeholder_dates:
        add_flag(conn, "document", f["id"], FlagRule.PLACEHOLDER_LISTING_DATE, m)
    if fa.year_note:
        flags.append((FlagRule.IDENTITY_YEAR_INFERRED, fa.year_note))
    for rule, details in flags:
        for did in doc_ids[:1]:
            add_flag(conn, "regulation", did, rule, details)
    unlink_other_documents(conn, f["id"], doc_ids)
    recompute_best_copies(conn, doc_ids)
    return doc_ids


def unlink_other_documents(conn: psycopg.Connection, file_id: int, doc_ids: list[int]) -> int:
    """A re-classified file keeps only the documents it produces now; a document left without any file is retired
    (relations to it fall back to their text reference, its flags are resolved as superseded)."""
    stale = conn.execute("SELECT DISTINCT regulation_id FROM document_parts WHERE document_id=%s "
                         "AND NOT (regulation_id = ANY(%s))", (file_id, doc_ids)).fetchall()
    n = 0
    for r in stale:
        did = r["regulation_id"]
        R.detach(conn, did, file_id)
        n += 1
        still = conn.execute("SELECT 1 FROM document_parts WHERE regulation_id=%s LIMIT 1", (did,)).fetchone()
        used = conn.execute("SELECT 1 FROM requirement_versions WHERE source_regulation_id=%s LIMIT 1", (did,)).fetchone()
        if not still and not used:
            R.retire_document(conn, did)
    return n


def _valid(dc: DocClass, data: dict) -> dict:
    """Drop None values; keep the shape of the doc_class model (schema checked again in extract)."""
    model = model_for(dc)
    keys = set(model.model_fields)
    return {k: v for k, v in data.items() if k in keys and v not in (None, [], {})}


def notification_header_data(fa: FileAnalysis) -> dict:
    ident = fa.identity
    d: dict = {}
    if ident and ident.kind == "notification":
        d.update(series=ident.series, number=ident.number,
                 date=ident.doc_date.isoformat() if ident.doc_date else None, other_ids=ident.others[:20])
    if fa.gazette:
        d["gazette"] = fa.gazette
    d["file_no"] = fa.file_no
    d["official_title"] = fa.official_title
    if fa.draft_ref:
        d["draft_ref"] = fa.draft_ref
    return d


def form_data(ctx: FileCtx, ident: Identity | None) -> dict:
    head = ctx.english[:1500]
    rule = re.search(r"\[?\s*See\s+(?:sub-)?rules?\s+([0-9A-Za-z()\s,\-and]{1,40}?)\s*\]", head, re.I)
    lines = [ln.strip() for ln in head.splitlines() if len(ln.strip()) > 12 and not ln.strip().upper().startswith("FORM")]
    return {"form_no": ident.number if ident else None, "rule_ref": f"Rule {rule.group(1).strip()}" if rule else None,
            "purpose": lines[0][:200] if lines else None}


def draft_data(ctx: FileCtx, ident: Identity | None) -> dict:
    head = ctx.english[:4000]
    c = re.search(r"Last\s+date\s+for\s+(?:receipt\s+of\s+)?comments?\s*[:\-]?\s*(.{0,40})", head, re.I)
    d = P.parse_date(c.group(1)) if c else None
    return {"draft_of": ident.canonical_id if ident else None, "comments_until": d.isoformat() if d else None,
            "finalized_draft": bool(re.search(r"finali[sz]ed\s+draft", head, re.I)) or None}


# ---------------------------------------------------------------------- AIS (split)
def write_ais(conn: psycopg.Connection, f: dict, ctx: FileCtx, fa: FileAnalysis) -> list[int]:
    pages = ctx.pages
    n = ctx.page_count or (pages[-1].page if pages else 1)
    ident = fa.identity
    arai_codes = [x.get("title") or "" for x in ctx.listings if x.get("source") == "ARAI_AIS"]
    from_morth = "ARAI_AIS" not in {x.get("source") for x in ctx.listings} and ctx.folder == "06"
    if ident is None:
        cid = synthetic_id("AIS-UNIDENTIFIED", ctx.sha)
        did, _ = upsert_document(conn, cid, {**base_values(fa, DocClass.AIS_STANDARD, None),
                                             "data": {"arai_code_raw": arai_codes[0]} if arai_codes else {}})
        attach(conn, did, f["id"], 1, n, eng=_eng_range(pages, 1, n))
        add_flag(conn, "regulation", did, FlagRule.IDENTITY_NOT_FOUND, {"reason": "no AIS code on cover", "file": ctx.sha})
        return [did]
    segs = split_ais(pages) if fa.cls.doc_class != DocClass.SAFETY_STANDARD_LEGACY else []
    ident = identity_from_headers(ident, segs)
    base_cid = ident.canonical_id
    ids: list[int] = []
    multi = len(segs) > 1
    has_base = any(s.kind == "base" for s in segs)
    standalone = fa.cls.doc_class in (DocClass.AIS_AMENDMENT, DocClass.AIS_CORRIGENDUM)
    if not segs:
        segs = []
    if (not segs or has_base) and not standalone:
        base_seg = next((s for s in segs if s.kind == "base"), None)
        a, b = (base_seg.page_from, base_seg.page_to) if base_seg else (1, n)
        data = {"arai_code_raw": arai_codes[0] if arai_codes else None}
        vals = {**base_values(fa, DocClass.AIS_STANDARD, ident), "doc_class": DocClass.AIS_STANDARD.value,
                "data": _valid(DocClass.AIS_STANDARD, data)}
        did, _ = upsert_document(conn, base_cid, vals)
        role = Role.HISTORICAL_COPY if from_morth else (Role.CONSOLIDATED_SEGMENT if multi else Role.MAIN)
        attach(conn, did, f["id"], a, b, eng=_eng_range(pages, a, b), part_label="Base standard" if multi else None,
               role=role)
        ids.append(did)
    for s in segs:
        if s.kind == "base":
            continue
        kind_cls = DocClass.AIS_AMENDMENT if s.kind == "amendment" else DocClass.AIS_CORRIGENDUM
        target = base_cid
        if s.target_raw:  # the header names the amended standard; prefer it when it is the same code
            t = P.ais_canonical_from_text(s.target_raw)
            tp = P.parse_canonical_ais(t) if t else None
            if tp and tp["code"] == int(ident.number) and (tp["rev"] or tp["part"]):
                target = t
        no = s.number or 1
        cid = f"{target}/{'Amd' if s.kind == 'amendment' else 'Corr'}.{no}"
        issued_date = None
        if s.issued and s.precision == "day":
            issued_date = date.fromisoformat(s.issued)
        elif s.issued and s.precision == "month":
            issued_date = date.fromisoformat(s.issued + "-01")
        data = {"amends": target, "amendment_no": no if s.kind == "amendment" else None,
                "corrigendum_no": no if s.kind == "corrigendum" else None, "issued": s.issued,
                "issued_precision": s.precision, "header_format": s.header_format}
        tp = P.parse_canonical_ais(target) or {}
        vals = {"doc_class": kind_cls.value, "status": "final", "issuer": "AISC/ARAI", "nature": "technical",
                "relevance": fa.cls.relevance, "series": "AIS", "number": ident.number,
                "part": str(tp["part"]) if tp.get("part") else ident.part, "revision": tp.get("rev"),
                "amendment_no": no if s.kind == "amendment" else None,
                "corrigendum_no": no if s.kind == "corrigendum" else None,
                "family_key": ident.family_key, "doc_date": issued_date,
                "doc_date_precision": s.precision, "year": issued_date.year if issued_date else None,
                "data": _valid(kind_cls, data)}
        did, _ = upsert_document(conn, cid, {k: v for k, v in vals.items() if v is not None})
        role = Role.HISTORICAL_COPY if from_morth else (Role.CONSOLIDATED_SEGMENT if multi or not standalone else Role.MAIN)
        attach(conn, did, f["id"], s.page_from, s.page_to, eng=_eng_range(pages, s.page_from, s.page_to),
               part_label=s.label, role=role)
        ids.append(did)
    if not ids:  # stand-alone amendment without a parsable header: keep the file under its cover id
        did, _ = upsert_document(conn, base_cid, {**base_values(fa, fa.cls.doc_class, ident)})
        attach(conn, did, f["id"], 1, n, eng=_eng_range(pages, 1, n))
        ids.append(did)
    drop_stale_segments(conn, f["id"], {s.page_from for s in segs} or {1})
    check_amendment_gaps(conn, ident.family_key)
    return ids


def drop_stale_segments(conn: psycopg.Connection, file_id: int, starts: set[int]) -> int:
    """After a re-split, remove this file's segment rows whose start page is no longer a segment start
    (their chunks go with them; the pages now belong to a new segment document)."""
    rows = conn.execute("SELECT regulation_id, page_from FROM document_parts WHERE document_id=%s", (file_id,)).fetchall()
    n = 0
    for r in rows:
        if r["page_from"] not in starts:
            R.detach(conn, r["regulation_id"], file_id, r["page_from"])
            n += 1
    return n


def identity_from_headers(ident: Identity, segs: list) -> Identity:
    """Every amendment/corrigendum header in the file names the same other standard ('TO AIS-071(Part 2):2009')
    while the cover read gave a different code: the headers are the better evidence of what the file is."""
    named = set()
    for s in segs:
        if s.kind != "base" and s.target_raw:
            p = P.parse_ais_code(s.target_raw)
            if p:
                named.add((p["code"], p["part"]))
    if len(named) != 1:
        return ident
    code, part = named.pop()
    if code == int(ident.number) and (part is None or str(part) == (ident.part or str(part))):
        return ident
    rev = None
    for s in segs:  # a revision printed in a header ('TO AIS-038 (Rev.2)') is kept
        p = P.parse_ais_code(s.target_raw or "")
        if p and p["rev"]:
            rev = p["rev"]
    return Identity(kind="ais", canonical_id=P.ais_canonical(code, part, rev), number=f"{code:03d}",
                    part=str(part) if part else None, revision=rev, year=ident.year,
                    family_key=P.ais_family(code, part), doc_date=ident.doc_date,
                    doc_date_precision=ident.doc_date_precision,
                    evidence=f"amendment headers name AIS-{code:03d}; cover read gave {ident.canonical_id}")


def check_amendment_gaps(conn: psycopg.Connection, family_key: str | None) -> None:
    if not family_key:
        return
    rows = conn.execute(
        f"""SELECT g.data->>'amends' AS target, array_agg(g.amendment_no ORDER BY g.amendment_no) AS nos
            FROM regulations g WHERE g.family_key=%s AND g.local_class='AIS_AMENDMENT' AND g.amendment_no IS NOT NULL
              AND {country.region_sql('g')}
            GROUP BY 1""", (family_key,)).fetchall()
    for r in rows:
        gaps = amendment_gaps([x for x in r["nos"] if x is not None])
        base = R.find_document(conn, r["target"])
        if not base:
            continue
        # a gap flag is identified by (target, missing); notes added later (explained / evidence) do not change it
        same = "details->'target' = %s::jsonb AND details->'missing' = %s::jsonb"
        args = (json.dumps(r["target"]), json.dumps(gaps))
        # close open flags that describe an older state of the family, with the reason
        conn.execute(f"UPDATE quality_flags SET resolved_at=now(), details = details || "
                     f"'{{\"resolution\": \"superseded: the amendment list of this standard changed\"}}'::jsonb "
                     f"WHERE entity='regulation' AND entity_id=%s AND rule=%s AND resolved_at IS NULL AND NOT ({same})",
                     (base["id"], FlagRule.AMENDMENT_GAP.value, *args))
        if not gaps:
            continue
        # raise once: not while an equal flag is open, nor after an equal flag was resolved with evidence
        known = conn.execute(f"SELECT 1 FROM quality_flags WHERE entity='regulation' AND entity_id=%s AND rule=%s AND {same} "
                             f"AND (resolved_at IS NULL OR details ? 'evidence') LIMIT 1",
                             (base["id"], FlagRule.AMENDMENT_GAP.value, *args)).fetchone()
        if not known:
            add_flag(conn, "regulation", base["id"], FlagRule.AMENDMENT_GAP, {"target": r["target"], "missing": gaps})


# ---------------------------------------------------------------------- best copy
ROLE_RANK = {"main": 0, "consolidated_segment": 0, "annex_table": 0, "historical_copy": 2, "hindi_only": 3}


def recompute_best_copies(conn: psycopg.Connection, doc_ids: list[int]) -> None:
    """One is_best_copy per document: text layer > ARAI source > not a historical copy > newest > more English."""
    for did in doc_ids:
        rows = conn.execute(
            """SELECT p.document_id AS file_id, p.page_from,
                      CASE p.role WHEN 'other_language_only' THEN 'hindi_only' ELSE p.role END AS role, p.is_best_copy,
                      d.text_layer, d.ocr_engine, d.downloaded_at AS first_seen_at, d.file_ext,
                      coalesce((d.language_mix->>'en_pages')::int,0) AS en_pages,
                      EXISTS (SELECT 1 FROM raw_ingestion_records s JOIN sources so ON so.id=s.source_id
                              WHERE s.document_id=d.id AND so.code IN ('ARAI_AIS','ARAI_TAP')) AS arai,
                      (SELECT max(s.listing_date) FROM raw_ingestion_records s WHERE s.document_id=d.id) AS listed
               FROM document_parts p JOIN documents d ON d.id=p.document_id WHERE p.regulation_id=%s""",
            (did,)).fetchall()
        if not rows:
            continue
        doc = conn.execute("SELECT local_class FROM regulations WHERE id=%s", (did,)).fetchone()
        if doc["local_class"] == "TAP_DOCUMENT":
            continue  # every TAP part file is needed; best copy is per part, all true
        # a Thai standard's full-text PDF is read over its one-page TISI summary (fields stay from the summary)
        full_text_first = doc["local_class"] == "TIS_STANDARD"
        best = sorted(rows, key=lambda r: (full_text_first and (r["file_ext"] != "pdf" or r["role"] == "historical_copy"),
                                           not r["text_layer"], not r["arai"],
                                           ROLE_RANK.get(r["role"], 1),
                                           -(r["listed"].toordinal() if r["listed"] else 0), -r["en_pages"],
                                           r["file_id"]))[0]
        for r in rows:
            want = r["file_id"] == best["file_id"] and r["page_from"] == best["page_from"]
            if r["is_best_copy"] != want:
                conn.execute("UPDATE document_parts SET is_best_copy=%s WHERE regulation_id=%s AND document_id=%s "
                             "AND page_from=%s", (want, did, r["file_id"], r["page_from"]))


def tap_best_copies(conn: psycopg.Connection) -> None:
    conn.execute("""UPDATE document_parts p SET is_best_copy=true FROM regulations g
                    WHERE g.id=p.regulation_id AND g.local_class='TAP_DOCUMENT' AND NOT p.is_best_copy
                      AND """ + country.region_sql("g"))
