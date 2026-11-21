"""The summary of one vehicle category (Reports › Category summary): JSON for the portal, PDF to download.

It follows the portal's view filters (?year=, ?variant=) like every list view: the regulations come from
portal.regulations(), the obligations are those whose source regulation passes the same filters.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

from fastapi import HTTPException

from regtrack.api import sql as S
from regtrack.api.params import view_label, view_sql
from regtrack.api.regsummary import DISCLAIMER, SCOPES, conditions_text
from regtrack.db import connect

DRAFTS = ("NOTIFICATION_DRAFT", "AIS_DRAFT")


def _d(v) -> str | None:
    return v.strftime("%d %b %Y") if isinstance(v, (date, datetime)) else v


def _obligation(m) -> dict:
    text = " ".join((m["subject"] or "").split())
    if len(text) >= 295 and not text.endswith((".", ";", ":")):
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


def build(category: str, cc: str) -> dict:
    from regtrack.api.portal import change_monitor, load_vocab, regulations

    with connect() as conn:
        vocab = load_vocab(conn, cc)
        if category not in vocab["categories"]:
            raise HTTPException(404, f"unknown vehicle category {category!r} for {cc}")
        rows = regulations(conn, category, cc=cc)  # in-scope regulations naming it or ALL, with the view filters
        cats = [category, "ALL"]
        cols = """m.mandate_key, m.legal_basis, m.subject, m.standard_refs, m.vehicle_categories, m.conditions,
                  m.model_scope, m.implementation_date, m.is_draft, d.external_code AS source"""
        base = (
            f"FROM {S.mandates(cc)} m JOIN regulations d ON d.id = m.source_doc_id "
            f"WHERE m.vehicle_categories && %s AND (m.valid_to IS NULL OR m.valid_to > current_date)"
            f"{view_sql('d')}"
        )
        upcoming = conn.execute(
            f"SELECT {cols} {base} AND m.implementation_date >= current_date "
            "ORDER BY m.implementation_date, m.is_draft, m.mandate_key LIMIT 30",
            (cats,),
        ).fetchall()
        in_force = conn.execute(
            f"SELECT count(*) AS n {base} AND NOT m.is_draft "
            "AND (m.implementation_date IS NULL OR m.implementation_date < current_date)",
            (cats,),
        ).fetchone()["n"]
        n_upcoming = conn.execute(
            f"SELECT count(*) AS n {base} AND m.implementation_date >= current_date", (cats,)
        ).fetchone()["n"]
    ids = {r["id"] for r in rows}
    changes = [e for e in change_monitor(90, cc)["events"] if e["doc_id"] in ids]

    impact = Counter(r["impact"] for r in rows)
    bands = Counter(r["kpi_band"] for r in rows)
    topics: dict[str, dict] = {}
    for r in rows:
        for dm in r["domains"] or []:
            t = topics.setdefault(
                dm, {"topic": vocab["domain_label"].get(dm, dm.replace("_", " ")), "regulations": 0, "high": 0}
            )
            t["regulations"] += 1
            t["high"] += r["impact"] == "High"
    top = sorted(rows, key=lambda r: (-(r["kpi_score"] or 0), r["canonical_id"]))[:10]
    register = sorted(rows, key=lambda r: r["doc_date"] or date.min, reverse=True)
    return {
        "category": category,
        "label": vocab["cat_label"].get(category, category),
        "country": cc,
        "country_name": vocab["name"],
        "filters": view_label() or "none",
        "generated": datetime.now().strftime("%d %b %Y %H:%M"),
        "figures": [
            ("Regulations tracked", len(rows)),
            (
                "High / Medium / Low impact (rule-based)",
                f"{impact.get('High', 0)} / {impact.get('Medium', 0)} / {impact.get('Low', 0)}",
            ),
            (
                "High / Medium / Low impact KPI band",
                f"{bands.get('High', 0)} / {bands.get('Medium', 0)} / {bands.get('Low', 0)}",
            ),
            ("Open drafts", sum(1 for r in rows if r["doc_class"] in DRAFTS or r["doc_status"] == "draft")),
            ("Changes detected in the last 90 days", len(changes)),
            ("Obligations in force", in_force),
            ("Obligations still to come", n_upcoming),
        ],
        "topics": sorted(topics.values(), key=lambda t: (-t["regulations"], t["topic"])),
        "upcoming": [_obligation(m) for m in upcoming],
        "top_impact": [
            {
                "id": r["canonical_id"],
                "title": r["name"],
                "kpi_score": r["kpi_score"],
                "kpi_band": r["kpi_band"],
                "impact": r["impact"],
            }
            for r in top
        ],
        "changes": [
            {
                "date": e["detected_at"].strftime("%d %b %Y") if e.get("detected_at") else "—",
                "type": (e["event_type"] or "").replace("_", " "),
                "id": e["canonical_id"],
                "summary": " ".join((e["summary"] or "").split())[:240],
            }
            for e in changes[:25]
        ],
        "register": [
            {
                "id": r["canonical_id"],
                "title": r["name"],
                "date": _d(r["doc_date"]),
                "impact": r["impact"],
                "kpi_score": r["kpi_score"],
                "status": r["status"],
            }
            for r in register
        ],
        "changes_total": len(changes),
        "note": "Includes regulations that apply to all vehicles as well as those naming this category.",
        "disclaimer": DISCLAIMER,
    }


def pdf(s: dict) -> bytes:
    from reportlab.platypus import PageBreak, Spacer

    from regtrack.api.pdfkit import Kit
    from regtrack.api.regsummary import obligations_table

    k = Kit()
    mm, w = k.mm, k.width
    story = [
        k.P(f"{s['label']}", "title"),
        k.P(f"Vehicle category summary · {s['country_name']}", "sub"),
        Spacer(1, 4),
        k.P(f"Generated {s['generated']} · filters: {s['filters']}. {s['note']}", "note"),
        k.P("Key figures", "h"),
        k.table(["Measure", "Value"], s["figures"], [90 * mm, w - 90 * mm]),
        k.P("Regulations by topic", "h"),
        k.table(
            ["Topic", "Regulations", "High impact"],
            [[t["topic"], t["regulations"], t["high"]] for t in s["topics"]],
            [w - 60 * mm, 30 * mm, 30 * mm],
        )
        if s["topics"]
        else k.P("No topics recorded.", "note"),
        k.P("Upcoming implementation dates", "h"),
        obligations_table(k, s["upcoming"]) if s["upcoming"] else k.P("None scheduled.", "note"),
        k.P("Highest impact regulations (KPI score)", "h"),
        k.table(
            ["Regulation", "Title", "KPI score", "Rule-based impact"],
            [[r["id"], r["title"], f"{r['kpi_score']} ({r['kpi_band']})", r["impact"]] for r in s["top_impact"]],
            [40 * mm, w - 100 * mm, 28 * mm, 32 * mm],
        )
        if s["top_impact"]
        else k.P("None.", "note"),
        k.P(
            "Changes detected in the last 90 days"
            + (
                f" (latest {len(s['changes'])} of {s['changes_total']})"
                if s["changes_total"] > len(s["changes"])
                else ""
            ),
            "h",
        ),
        k.table(
            ["Detected", "Type", "Regulation", "Summary"],
            [[c["date"], c["type"], c["id"], c["summary"]] for c in s["changes"]],
            [22 * mm, 26 * mm, 36 * mm, w - 84 * mm],
            bold_first=False,
        )
        if s["changes"]
        else k.P("No changes detected.", "note"),
        k.P("Disclaimer: " + s["disclaimer"], "note"),
        PageBreak(),
        k.P(f"Appendix: regulation register ({len(s['register'])})", "h"),
        k.table(
            ["Regulation", "Title", "Published", "Impact", "KPI", "Status"],
            [[r["id"], r["title"], r["date"] or "—", r["impact"], r["kpi_score"], r["status"]] for r in s["register"]],
            [36 * mm, w - 120 * mm, 22 * mm, 18 * mm, 12 * mm, 32 * mm],
        ),
    ]
    return k.build(
        story, f"{s['label']} – category summary", f"RegTrack · {s['country']} · {s['category']} · category summary"
    )
