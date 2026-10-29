"""Mandates and client-requirement links for Thailand and Malaysia (deterministic, no Qwen).

- Thailand: a mandatory TIS standard is itself a rule: key = its family (TIS-721), effective date from the TISI page.
  A newer edition supersedes the old version (mandates.supersede: never updated in place).
- Malaysia: one rule per row of JPJ's CTA component table, and per DOE type-approval / in-use emission stage.
- match_requirements: links the client's regulatory register (client_requirements, TH-01… / MY-01…) to the stored
  regulations that cover each row (client_requirement_regulations, matched_by='rules').
"""

from __future__ import annotations

import re
from datetime import date

import psycopg

from regtrack import country
from regtrack.pipeline import malaysia
from regtrack.pipeline import mandates as M

MATCHED_BY = "rules:v1"


def _record(conn: psycopg.Connection, key: str, doc: dict, values: dict, valid_from: date | None) -> int:
    if M.already_recorded(conn, key, doc["id"]):
        return 0
    v = {
        "source_doc_id": doc["id"],
        "usage": doc.get("usage") or [],
        "powertrains": doc.get("powertrains") or [],
        "conditions": {},
        "model_scope": "all",
        "standard_refs": [],
        "standard_doc_ids": [],
        **values,
    }
    M.supersede(conn, key, v, valid_from or date.today(), False)
    return 1


def tis_mandate(conn: psycopg.Connection, doc: dict) -> int:
    """TIS_STANDARD -> one rule version (key = family, e.g. TIS-721)."""
    if not doc.get("family_key"):
        return 0
    newer = conn.execute(
        """SELECT 1 FROM requirement_versions v JOIN compliance_requirements r ON r.id = v.requirement_id
                            JOIN regulations g ON g.id = v.source_regulation_id
                            WHERE r.region_id = (SELECT region_id FROM regulations WHERE id = %s)
                              AND r.requirement_code = %s AND v.valid_to IS NULL AND g.year > %s""",
        (doc["id"], doc["family_key"], doc.get("year") or 0),
    ).fetchone()
    if newer:
        return 0  # an older edition processed late never replaces the newer edition's rule
    data = doc.get("data") or {}
    eff = date.fromisoformat(data["effective_date"]) if data.get("effective_date") else None
    return _record(
        conn,
        doc["family_key"],
        doc,
        {
            "legal_basis": f"{doc['canonical_id']} (TISI mandatory standard)",
            "subject": doc.get("subject"),
            "standard_refs": [doc["canonical_id"]],
            "standard_doc_ids": [doc["id"]],
            "vehicle_categories": doc.get("vehicle_categories") or [],
            "date_of_notification": None,
            "effective_date": eff,
            "implementation_date": eff,
            "implementation_rule": "mandatory from the TISI effective date (วันที่มีผลบังคับใช้)" if eff else None,
        },
        eff,
    )


def my_mandates(conn: psycopg.Connection, doc: dict, text: str) -> int:
    """MY_GUIDELINE pages: the CTA component table and the DOE emission stages."""
    n = 0
    for c in malaysia.cta_components(text):
        key = f"MY-CTA-{malaysia.slug(c['component'])}"
        n += _record(
            conn,
            key,
            doc,
            {
                "legal_basis": "Customs (Prohibition of Imports) Order: JPJ Component Type Approval",
                "subject": f"CTA: {c['component']}",
                "standard_refs": c["refs"],
                "vehicle_categories": c["vehicle_categories"],
                "conditions": {"regulations": c["regulations"]},
                "implementation_rule": "component must hold JPJ CTA before domestic supply and sale",
            },
            None,
        )
    for s in malaysia.doe_stages(text):
        n += _record(
            conn,
            s["key"],
            doc,
            {
                "legal_basis": s["legal_basis"],
                "subject": s["subject"],
                "vehicle_categories": ["ALL"],
                "powertrains": [s["fuel"]],
                "effective_date": s["effective_date"],
                "implementation_date": s["effective_date"],
                "conditions": {"text": s["text"]},
                "implementation_rule": "new models on or after this date" if s["effective_date"] else None,
            },
            s["effective_date"],
        )
    return n


# ------------------------------------------------------------------ client register -> regulations
def _rx(p: str):
    rx = re.compile(p, re.I)
    return lambda r: bool(rx.search(r["subject"] or "") or rx.search(r["refs"]))


def _id(*prefixes: str):
    return lambda r: (r["canonical_id"] or "").startswith(prefixes)


def _src(*codes: str, rx: str | None = None):
    pat = re.compile(rx, re.I) if rx else None
    return lambda r: (
        bool(r["sources"] & set(codes)) and (pat is None or bool(pat.search(r["refs"] + " " + (r["subject"] or ""))))
    )


EMISSION = _rx(r"สารมลพิษ|ท่อไอเสีย")
EMC = re.compile(r"แม่เหล็กไฟฟ้า|electromagnetic|\bEMC\b|\bR\s?10\b", re.I)
LAW_CLASSES = {"TH_ACT", "MINISTERIAL_REGULATION", "DLT_NOTIFICATION", "GAZETTE_NOTICE"}


def _law(r: dict) -> bool:
    return r["doc_class"] in LAW_CLASSES


RULES: dict[str, list[tuple[str, str, object]]] = {
    "TH": [
        ("TH-01", "supporting", lambda r: r["doc_class"] == "TIS_STANDARD"),
        ("TH-03", "primary", _id("TIS-3017-")),
        ("TH-04", "primary", _id("TIS-3044-")),
        ("TH-05", "primary", lambda r: EMISSION(r) and not _id("TIS-3017-", "TIS-3044-")(r)),
        ("TH-06", "primary", _id("TIS-2721-")),
        ("TH-06", "supporting", _id("TIS-341-")),
        ("TH-09", "primary", _rx(r"ยางล้อ|ยางใน")),
        ("TH-11", "primary", _rx(r"เข็มขัดนิรภัย|หมวกนิรภัย")),
        ("TH-12", "primary", _rx(r"กระจกนิรภัย")),
        # Thai legal texts saved by hand (TH_LOCAL): by their topics (thai.law_domains) and subject line
        ("TH-02", "primary", lambda r: r["doc_class"] == "TH_ACT" or (_law(r) and "REGISTRATION" in r["domains"])),
        ("TH-07", "primary", lambda r: _law(r) and "DIMENSIONS_WEIGHTS" in r["domains"]),
        ("TH-08", "primary", lambda r: _law(r) and "LIGHTING" in r["domains"]),
        ("TH-10", "primary", lambda r: _law(r) and "BRAKING" in r["domains"]),
        ("TH-13", "primary", lambda r: _law(r) and bool({"EV_ALT_FUEL", "BATTERY"} & set(r["domains"]))),
        ("TH-14", "primary", lambda r: _law(r) and bool(EMC.search(f"{r['subject'] or ''} {r['refs']}"))),
        ("TH-15", "primary", lambda r: _law(r) and "FUEL_EFFICIENCY" in r["domains"]),
    ],
    "MY": [
        ("MY-01", "primary", _src("MY_JPJ_VTA")),
        ("MY-01", "supporting", _id("MY-ACT-333")),  # Road Transport Act 1987: registration needs approval
        ("MY-16", "primary", _id("MY-ACT-333")),
        ("MY-03", "primary", _id("PUA-543-1996")),  # EQ (Control of Emissions from Petrol Engines) 1996
        ("MY-04", "primary", _id("PUA-429-1996", "PUA-488-2000")),  # Diesel Engines 1996 + amendment 2000
        ("MY-05", "supporting", _id("PUA-429-1996", "PUA-488-2000")),
        ("MY-06", "supporting", _id("PUA-464-2003")),  # Motorcycles 2003 (the motorcycle route)
        ("MY-07", "supporting", _id("PUA-464-2003")),
        ("MY-16", "primary", _src("MY_JPJ_VTA")),
        ("MY-02", "primary", _src("MY_JPJ_CTA")),
        ("MY-03", "primary", _src("MY_DOE_EMISSION")),
        ("MY-04", "primary", _src("MY_DOE_EMISSION")),
        ("MY-05", "primary", _src("MY_DOE_EMISSION")),
        ("MY-06", "primary", _src("MY_DOE_VTA_GUIDE")),
        ("MY-07", "primary", _src("MY_DOE_VTA_GUIDE")),
        ("MY-08", "primary", _src("MY_JPJ_AED")),
        ("MY-09", "primary", _src("MY_JPJ_CTA", rx=r"brake")),
        ("MY-10", "primary", _src("MY_JPJ_CTA", rx=r"tyre")),
        ("MY-11", "primary", _src("MY_JPJ_CTA", rx=r"headlamp|lamp|light")),
        ("MY-12", "primary", _src("MY_JPJ_CTA", rx=r"glass|glazing|mirror")),
        ("MY-13", "primary", _src("MY_JPJ_CTA", rx=r"seat|belt|child")),
        ("MY-14", "candidate", _src("MY_JPJ_AED")),
        ("MY-15", "candidate", _src("MY_JPJ_AED")),
        # its functions: VTA testing "bagi tujuan pengiktirafan Energy Efficient Vehicle (EEV)"
        ("MY-17", "primary", _src("MY_JPJ_AED")),
        ("MY-14", "primary", _src("MY_LOCAL", rx=r"R\s?100\b|REESS|electric\s+vehicle|kenderaan\s+elektrik")),
        ("MY-15", "primary", _src("MY_LOCAL", rx=r"R\s?10\b|electromagnetic|\bEMC\b|keserasian\s+elektromagnet")),
        ("MY-08", "primary", _src("MY_LOCAL", rx=r"UN\s+Regulation|UNECE|WP\.?29")),
    ],
}

REG_SQL = """
SELECT g.id, g.external_code AS canonical_id, g.local_class AS doc_class, coalesce(g.summary, g.title) AS subject,
       coalesce(g.data->>'references', '') || ' ' || coalesce(g.data->>'title', '') AS refs,
       coalesce((SELECT array_agg(DISTINCT s.code) FROM document_parts p
                 JOIN raw_ingestion_records x ON x.document_id = p.document_id
                 JOIN sources s ON s.id = x.source_id WHERE p.regulation_id = g.id), '{{}}') AS sources,
       coalesce((SELECT array_agg(d.code) FROM regulation_domains rd JOIN public.domains d ON d.id = rd.domain_id
                 WHERE rd.regulation_id = g.id), '{{}}') AS domains
FROM regulations g WHERE {region} AND g.local_class <> 'OFF_TOPIC'"""


def match_requirements(conn: psycopg.Connection, cc: str | None = None) -> int:
    """Insert the missing links (idempotent: a re-run with nothing new writes nothing)."""
    cc = country.code(cc)
    rules = RULES.get(cc)
    if not rules:
        return 0
    reqs = {
        r["code"]: r["id"]
        for r in conn.execute(
            "SELECT id, code FROM client_requirements WHERE region_id=(SELECT id FROM regions WHERE code=%s)", (cc,)
        )
    }
    regs = conn.execute(REG_SQL.format(region=country.region_sql("g", cc))).fetchall()
    n = 0
    for r in regs:
        r = {**r, "sources": set(r["sources"] or [])}
        for code, role, pred in rules:
            if code in reqs and pred(r):
                cur = conn.execute(
                    """INSERT INTO client_requirement_regulations (requirement_id, regulation_id, role, matched_by)
                                      VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (reqs[code], r["id"], role, MATCHED_BY),
                )
                n += cur.rowcount
    return n
