"""The detailed summary of one regulation (Reports › Regulation summary): JSON for the portal, PDF to download.

One builder (`build`) gathers what the portal knows about a regulation: identity, summary, impact and its KPI breakdown,
the obligations it sets and those that cite it as a standard (only versions still in force), related documents,
versions, the latest detected change and the original file. `pdf` renders that same dict.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

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
    parts = []
    for key, ops in (cond or {}).items():
        label, unit = UNITS.get(key, (key, ""))
        for op, v in ops.items():
            parts.append(f"{label} {OPS.get(op, op)} {v:g} {unit}".strip())
    return "; ".join(parts)


def _d(v) -> str | None:
    if isinstance(v, (date, datetime)):
        return v.strftime("%d %b %Y")
    return v


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
def _fonts() -> tuple[str, str]:
    """A Unicode face for ≤ and the like (Segoe UI / DejaVu when present), else Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold in (
        (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ):
        if Path(regular).exists() and Path(bold).exists():
            if "RT" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("RT", regular))
                pdfmetrics.registerFont(TTFont("RTB", bold))
            return "RT", "RTB"
    return "Helvetica", "Helvetica-Bold"


def pdf(s: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    reg, bold = _fonts()
    if reg == "Helvetica":  # no Unicode face: plain ASCII comparisons
        tr = str.maketrans({"≤": "<=", "≥": ">=", "–": "-", "·": "-", "’": "'"})
    else:
        tr = None
    navy, accent, body, muted, rule, band = (
        colors.HexColor(c) for c in ("#13233F", "#A84E14", "#2D3748", "#5A6578", "#D9D4C7", "#F3F1EB")
    )
    st = {
        "title": ParagraphStyle("t", fontName=bold, fontSize=17, leading=22, textColor=navy),
        "sub": ParagraphStyle("s", fontName=reg, fontSize=10, leading=14, textColor=muted),
        "h": ParagraphStyle(
            "h", fontName=bold, fontSize=12, leading=16, textColor=accent, spaceBefore=12, spaceAfter=5
        ),
        "p": ParagraphStyle("p", fontName=reg, fontSize=9.5, leading=14, textColor=body, spaceAfter=4),
        "cell": ParagraphStyle("c", fontName=reg, fontSize=8.5, leading=11.5, textColor=body),
        "cellb": ParagraphStyle("cb", fontName=bold, fontSize=8.5, leading=11.5, textColor=navy),
        "head": ParagraphStyle("hd", fontName=bold, fontSize=8.5, leading=11.5, textColor=colors.white),
        "note": ParagraphStyle("n", fontName=reg, fontSize=8, leading=11, textColor=muted),
    }

    def t(v) -> str:
        text = "—" if v in (None, "", []) else str(v)
        return escape(text.translate(tr) if tr else text)

    def P(v, style="p"):
        return Paragraph(t(v), st[style])

    width = A4[0] - 36 * mm

    def table(head, rows, widths, bold_first=True):
        data = [[Paragraph(t(h), st["head"]) for h in head]]
        data += [
            [Paragraph(t(c), st["cellb" if i == 0 and bold_first else "cell"]) for i, c in enumerate(r)] for r in rows
        ]
        tb = Table(data, colWidths=widths, repeatRows=1)
        tb.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), navy),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, band]),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.4, rule),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return tb

    story = [P(s["canonical_id"], "title"), P(s["title"], "sub")]
    if s.get("subtitle"):
        story.append(P(s["subtitle"], "sub"))
    story += [
        Spacer(1, 4),
        P(f"Regulation summary · {s['country']} · generated {s['generated']}", "note"),
        Spacer(1, 6),
        P("Key facts", "h"),
        table(["Field", "Value"], s["facts"], [45 * mm, width - 45 * mm]),
        P("Summary", "h"),
        P(s["summary"]),
    ]
    if s["ai_pending"]:
        story.append(
            P(
                "The AI-written summary for this regulation is pending; the text above comes from rule-based "
                "extraction.",
                "note",
            )
        )
    story += [P("Detected change", "h"), P(s["change"]), P("Recommended follow-up", "h"), P(s["action"])]
    im = s["impact"]
    story += [
        P("Impact assessment", "h"),
        P(
            f"Rule-based impact: {im['level']} ({im['basis']}) · workflow status: {im['workflow']} · "
            f"impact KPI score: {im['kpi_score']} / 100 ({im['kpi_band']})"
        ),
    ]
    if im["kpi"]:
        story.append(
            table(
                ["Criterion", "Weight", "Score", "Points", "Basis and reason"],
                [
                    [k["label"], f"{k['weight']}%", f"{k['score']} / 5", k["points"], f"{k['basis']}: {k['reason']}"]
                    for k in im["kpi"]
                ],
                [48 * mm, 15 * mm, 15 * mm, 14 * mm, width - 92 * mm],
            )
        )
    for title, key in (
        ("Obligations set by this regulation", "obligations"),
        ("Obligations citing this regulation as a standard", "cited_by"),
    ):
        rows = s[key]
        story.append(P(title, "h"))
        if rows:
            story.append(
                table(
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
                    [22 * mm, width - 112 * mm, 32 * mm, 22 * mm, 36 * mm],
                    bold_first=False,
                )
            )
        else:
            story.append(P("None recorded.", "note"))
    story.append(P("Related documents", "h"))
    story.append(
        table(
            ["Relation", "Document"], [[r["relation"], r["document"]] for r in s["related"]], [50 * mm, width - 50 * mm]
        )
        if s["related"]
        else P("None recorded.", "note")
    )
    if s["versions"]:
        story += [
            P("Version history", "h"),
            table(
                ["Version", "Type", "Date", "Current"],
                [[v["id"], v["type"], v["date"] or "—", "current" if v["current"] else ""] for v in s["versions"]],
                [60 * mm, 55 * mm, 30 * mm, width - 145 * mm],
            ),
        ]
    story += [
        P("Source document", "h"),
        P(
            "Original official document stored unchanged (SHA-256 " + s["file"]["sha256"][:16] + "…); open it "
            "from the regulation panel in the portal."
            if s["file"]
            else "No original file stored."
        ),
        Spacer(1, 10),
        P("Disclaimer: " + s["disclaimer"], "note"),
    ]

    def footer(c, d):
        c.saveState()
        c.setFont(reg, 7.5)
        c.setFillColor(muted)
        label = f"RegTrack · {s['canonical_id']} · regulation summary"
        c.drawString(18 * mm, 10 * mm, label.translate(tr) if tr else label)
        c.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {d.page}")
        c.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"{s['canonical_id']} – regulation summary",
        author="RegTrack",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def safe_name(canonical_id: str) -> str:
    keep = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in canonical_id)
    return f"RegTrack_{keep}_summary.pdf"
