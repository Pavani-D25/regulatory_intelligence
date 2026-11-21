"""The detailed summary of one regulation (Reports › Regulation summary): JSON for the portal, PDF to download.

One builder (`build`) gathers what the portal knows about a regulation: identity, summary, impact and its KPI breakdown,
the obligations it sets and those that cite it as a standard (only versions still in force), related documents,
versions, the latest detected change and the original file. `pdf` renders that same dict.
"""

from __future__ import annotations

from datetime import date, datetime

from regtrack.api import sql as S
from regtrack.db import connect

DISCLAIMER = (
    "RegTrack supports teams in the regulatory process with summaries and action items; decisions should be "
    "verified against the official source documents. The platform assumes no legal liability for errors or "
    "omissions, or for meeting regulatory requirements."
)
OPS = {"lte": "≤", "lt": "<", "gte": "≥", "gt": ">"}
UNITS = {
    "engine_cc": ("engine", "cc"),
    "power_kw": ("power", "kW"),
    "gvw_kg": ("GVW", "kg"),
    "seats": ("seats", ""),
    "speed_kmh": ("speed", "km/h"),
}
SCOPES = {
    "new_models": "new models",
    "existing_models": "existing models",
    "registered_vehicles": "registered vehicles",
}


def conditions_text(cond: dict | None) -> str:
    if isinstance(cond, str):  # some client registers (MY) keep the condition as text
        return cond
    if not isinstance(cond, dict):
        return ""
    parts = []
    for key, ops in cond.items():
        if not isinstance(ops, dict):
            continue
        label, unit = UNITS.get(key, (key, ""))
        for op, v in ops.items():
            parts.append(f"{label} {OPS.get(op, op)} {v:g} {unit}".strip())
    return "; ".join(parts)


def _d(v) -> str | None:
    if isinstance(v, (date, datetime)):
        return v.strftime("%d %b %Y")
    return v


def digest_for(conn, regulation_id: int, cc: str, vocab: dict) -> dict:
    """The detailed summary of one regulation from its own text (regtrack/pipeline/digest.py), with its in-force
    obligations and its relations."""
    from regtrack.pipeline import digest

    r = conn.execute(f"SELECT * FROM {S.docs(cc)} d WHERE d.id = %s", (regulation_id,)).fetchone()
    ms = conn.execute(
        f"""SELECT m.subject, m.implementation_date, m.vehicle_categories, m.model_scope, m.conditions
            FROM {S.mandates(cc)} m WHERE m.source_doc_id = %s AND (m.valid_to IS NULL OR m.valid_to > current_date)
            ORDER BY m.implementation_date NULLS LAST, m.mandate_key""",
        (regulation_id,),
    ).fetchall()
    rel = conn.execute(
        """SELECT r.type, coalesce(t.external_code, r.to_ref) AS target FROM regulation_relations r
           LEFT JOIN regulations t ON t.id = r.to_regulation_id WHERE r.from_regulation_id = %s ORDER BY r.type, r.id""",
        (regulation_id,),
    ).fetchall()
    mandates = [{**m, "applies_to": conditions_text(m["conditions"])} for m in ms]
    labels = {"cat": vocab["cat_label"], "domain": vocab["domain_label"]}
    return digest.digest(dict(r), digest.load_text(conn, regulation_id), mandates, [dict(x) for x in rel], labels)


def build(canonical_id: str, cc: str) -> dict:
    from regtrack.api.app import document as document_record
    from regtrack.api.portal import regulation_detail

    detail = regulation_detail(canonical_id, cc)  # 404 when unknown
    doc = document_record(canonical_id, cc)
    with connect() as conn:
        rid = detail["id"]
        cols = """m.mandate_key, m.legal_basis, m.subject, m.standard_refs, m.vehicle_categories, m.conditions,
                  m.model_scope, m.implementation_date, m.implementation_rule, m.is_draft, d.external_code AS source"""
        live = "(m.valid_to IS NULL OR m.valid_to > current_date)"
        sets = conn.execute(
            f"""SELECT {cols} FROM {S.mandates(cc)} m JOIN regulations d ON d.id = m.source_doc_id
                WHERE m.source_doc_id = %s AND {live} ORDER BY m.implementation_date NULLS LAST, m.mandate_key""",
            (rid,),
        ).fetchall()
        cited = conn.execute(
            f"""SELECT {cols} FROM {S.mandates(cc)} m JOIN regulations d ON d.id = m.source_doc_id
                WHERE %s = ANY(m.standard_doc_ids) AND m.source_doc_id <> %s AND {live}
                ORDER BY m.implementation_date NULLS LAST, m.mandate_key LIMIT 25""",
            (rid, rid),
        ).fetchall()
        versions = []
        if detail.get("family_key"):
            versions = conn.execute(
                f"""SELECT d.canonical_id, d.doc_class, d.doc_date, d.is_current, d.status FROM {S.docs(cc)} d
                    WHERE d.family_key = %s ORDER BY d.version_seq NULLS LAST, d.doc_date NULLS LAST""",
                (detail["family_key"],),
            ).fetchall()

    def obligation(m) -> dict:
        text = " ".join((m["subject"] or "").split())
        if len(text) >= 295 and not text.endswith((".", ";", ":")):  # the stored text is cut at 300 characters
            text += "…"
        return {
            "requirement": text,
            "legal_basis": m["legal_basis"],
            "standards": m["standard_refs"] or [],
            "categories": m["vehicle_categories"] or [],
            "applies_to": "; ".join(
                x for x in (SCOPES.get(m["model_scope"] or "", ""), conditions_text(m["conditions"])) if x
            )
            or "all",
            "date": _d(m["implementation_date"]),
            "draft": m["is_draft"],
            "source": m["source"],
        }

    related = [
        {"relation": r["type"].replace("_", " "), "document": r["target"], "known": r["resolved"]}
        for r in doc.get("relations_out") or []
    ]
    related += [
        {"relation": f"{r['type'].replace('_', ' ')} (from)", "document": r["source"], "known": True}
        for r in doc.get("relations_in") or []
    ]
    f = detail.get("file")
    return {
        "canonical_id": detail["canonical_id"],
        "title": detail.get("name"),
        "subtitle": detail.get("subtitle"),
        "country": cc,
        "generated": datetime.now().strftime("%d %b %Y %H:%M"),
        "facts": [
            ("Regulation ID", detail["canonical_id"]),
            ("Type", (detail.get("doc_class") or "").replace("_", " ").title()),
            ("Issuing authority", detail.get("authority")),
            ("Published", _d(detail.get("doc_date"))),
            ("Effective / applies from", _d(detail.get("effective"))),
            ("Status", detail.get("doc_status")),
            ("Vehicle categories", ", ".join(detail.get("all_categories") or []) or "—"),
            ("Topics", ", ".join(d.replace("_", " ") for d in detail.get("domains") or []) or "—"),
            ("Powertrains", ", ".join(doc.get("powertrains") or []) or "all"),
            ("In scope", "yes" if detail.get("in_scope") else "no (stored for reference)"),
            ("Next obligation", _d(detail.get("next_obligation")) or "none"),
        ],
        "summary": detail.get("summary"),
        "digest": detail.get("digest"),
        "ai_pending": bool(detail.get("ai_pending")),
        "change": detail.get("change"),
        "action": detail.get("action"),
        "impact": {
            "level": detail.get("impact"),
            "basis": detail.get("impact_basis"),
            "workflow": detail.get("status"),
            "kpi_score": detail.get("kpi_score"),
            "kpi_band": detail.get("kpi_band"),
            "kpi": detail.get("kpi") or [],
            "bands": detail.get("kpi_bands") or {},
        },
        "obligations": [obligation(m) for m in sets],
        "cited_by": [obligation(m) for m in cited],
        "related": related,
        "versions": [
            {
                "id": v["canonical_id"],
                "type": (v["doc_class"] or "").replace("_", " ").title(),
                "date": _d(v["doc_date"]),
                "current": v["is_current"],
                "status": v["status"],
            }
            for v in versions
        ],
        "file": {"sha256": f["sha256"], "ext": f["ext"]} if f else None,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- PDF
def pdf(s: dict) -> bytes:
    from regtrack.api.pdfkit import Kit

    k = Kit()
    return k.build(
        story(k, s), f"{s['canonical_id']} – regulation summary", f"RegTrack · {s['canonical_id']} · regulation summary"
    )


def pdf_many(items: list[dict], filters: str) -> bytes:
    """Several regulations in one PDF: an index page, then each regulation's summary from a new page."""
    from reportlab.platypus import PageBreak, Spacer

    from regtrack.api.pdfkit import Kit

    k = Kit()
    mm, w = k.mm, k.width
    head = [
        k.P(f"Regulation summaries ({len(items)})", "title"),
        k.P(
            f"{items[0]['country']} · generated {items[0]['generated']}"
            + (f" · selected with filters: {filters}" if filters else ""),
            "sub",
        ),
        Spacer(1, 8),
        k.P("Index", "h"),
        k.table(
            ["#", "Regulation", "Title", "Published"],
            [
                [i + 1, s["canonical_id"], s["title"], dict(s["facts"]).get("Published") or "—"]
                for i, s in enumerate(items)
            ],
            [10 * mm, 42 * mm, w - 82 * mm, 30 * mm],
            bold_first=False,
        ),
    ]
    body = []
    for s in items:
        body += [PageBreak(), *story(k, s)]
    return k.build(
        head + body, f"Regulation summaries ({len(items)})", f"RegTrack · regulation summaries ({len(items)})"
    )


def story(k, s: dict) -> list:
    """One regulation's summary as PDF flowables."""
    from reportlab.platypus import Spacer

    mm, w = k.mm, k.width
    flow = [k.P(s["canonical_id"], "title"), k.P(s["title"], "sub")]
    if s.get("subtitle"):
        flow.append(k.P(s["subtitle"], "sub"))
    flow += [
        Spacer(1, 4),
        k.P(f"Regulation summary · {s['country']} · generated {s['generated']}", "note"),
        Spacer(1, 6),
        k.P("Key facts", "h"),
        k.table(["Field", "Value"], s["facts"], [45 * mm, w - 45 * mm]),
        k.P("Summary", "h"),
        k.P(s["summary"]),
    ]
    dg = s.get("digest")
    if dg and dg["sections"]:
        flow.append(k.P("Detailed summary", "h"))
        for sec in dg["sections"]:
            flow.append(k.P(sec["title"], "sub2"))
            if sec.get("text"):
                flow.append(k.P(sec["text"]))
            for it in sec.get("items", []):
                flow.append(k.P("•  " + it, "bullet"))
        flow.append(k.P(dg["source"] + ".", "note"))
    flow += [k.P("Detected change", "h"), k.P(s["change"]), k.P("Recommended follow-up", "h"), k.P(s["action"])]
    im = s["impact"]
    flow += [
        k.P("Impact assessment", "h"),
        k.P(
            f"Rule-based impact: {im['level']} ({im['basis']}) · workflow status: {im['workflow']} · "
            f"impact KPI score: {im['kpi_score']} / 100 ({im['kpi_band']})"
        ),
    ]
    if im["kpi"]:
        flow.append(
            k.table(
                ["Criterion", "Weight", "Score", "Points", "Basis and reason"],
                [
                    [c["label"], f"{c['weight']}%", f"{c['score']} / 5", c["points"], f"{c['basis']}: {c['reason']}"]
                    for c in im["kpi"]
                ],
                [48 * mm, 15 * mm, 15 * mm, 14 * mm, w - 92 * mm],
            )
        )
    for title, key in (
        ("Obligations set by this regulation", "obligations"),
        ("Obligations citing this regulation as a standard", "cited_by"),
    ):
        flow.append(k.P(title, "h"))
        flow.append(obligations_table(k, s[key]) if s[key] else k.P("None recorded.", "note"))
    flow.append(k.P("Related documents", "h"))
    flow.append(
        k.table(
            ["Relation", "Document"], [[r["relation"], r["document"]] for r in s["related"]], [50 * mm, w - 50 * mm]
        )
        if s["related"]
        else k.P("None recorded.", "note")
    )
    if s["versions"]:
        flow += [
            k.P("Version history", "h"),
            k.table(
                ["Version", "Type", "Date", "Current"],
                [[v["id"], v["type"], v["date"] or "—", "current" if v["current"] else ""] for v in s["versions"]],
                [60 * mm, 55 * mm, 30 * mm, w - 145 * mm],
            ),
        ]
    flow += [
        k.P("Source document", "h"),
        k.P(
            "Original official document stored unchanged (SHA-256 " + s["file"]["sha256"][:16] + "…); open "
            "it from the regulation panel in the portal."
            if s["file"]
            else "No original file stored."
        ),
        Spacer(1, 10),
        k.P("Disclaimer: " + s["disclaimer"], "note"),
    ]
    return flow


def obligations_table(k, rows: list[dict]):
    """Obligations as a table (also used by the category summary)."""
    mm, w = k.mm, k.width
    return k.table(
        ["Applies from", "Requirement", "Applies to", "Categories", "Standards / basis"],
        [
            [
                r["date"] or "—",
                r["requirement"],
                r["applies_to"],
                ", ".join(r["categories"]),
                ", ".join(r["standards"])
                + (f" ({r['legal_basis']})" if r["legal_basis"] else "")
                + (" [draft]" if r["draft"] else ""),
            ]
            for r in rows
        ],
        [22 * mm, w - 112 * mm, 32 * mm, 22 * mm, 36 * mm],
        bold_first=False,
    )


def safe_name(canonical_id: str) -> str:
    from regtrack.api.pdfkit import safe_name as name

    return name(canonical_id, "summary")
