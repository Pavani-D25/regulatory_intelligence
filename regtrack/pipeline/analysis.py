"""Per-file analysis shared by the DB classify stage and the offline profiler.

identify(ctx) -> FileAnalysis: identity from content, class, status, issuer, gazette fields, listing checks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from regtrack.models.enums import DocClass
from regtrack.pipeline import malaysia, thai
from regtrack.pipeline import patterns as P
from regtrack.pipeline.classify import DRAFT_CITE, ClassResult, FileCtx, classify
from regtrack.pipeline.identity import (
    Identity,
    ais_identity,
    form_identity,
    notification_identity,
    tap_identity,
    title_notification_ids,
)
from regtrack.pipeline.text import full_text, load_pages


@dataclass
class FileAnalysis:
    ctx: FileCtx
    cls: ClassResult
    identity: Identity | None
    gazette: dict = field(default_factory=dict)
    file_no: str | None = None
    official_title: str | None = None
    draft_ref: dict | None = None
    title_mismatch: list[dict] = field(default_factory=list)
    placeholder_dates: list[dict] = field(default_factory=list)
    kruti: bool = False
    year_note: dict | None = None  # identity year corrected from the file number (flagged)

    @property
    def canonical_id(self) -> str | None:
        return self.identity.canonical_id if self.identity else None


def gazette_fields(text: str) -> dict:
    g: dict = {}
    m = P.PART_SEC.search(text[:15000])
    if m:
        g = {"part": "II", "section": m.group(1)}
        if m.group(2):
            g["sub_section"] = f"({m.group(2).lower()})"
    m = P.GAZETTE_ID.search(text[:15000])
    if m:
        g["gazette_id"] = re.sub(r"\s+", "", m.group(1))
    m = re.search(r"\bNo\.\s*(\d{2,5})\]?\s*(?:NEW\s+DELHI|नई\s+दिल्ली)", text[:15000], re.I)
    if m:
        g["issue_no"] = m.group(1)
    return g


def file_number(text: str) -> str | None:
    ms = list(P.FILE_NO.finditer(text))
    if not ms:
        return None
    # the footer file no. of the operative notification is usually the last one
    v = re.sub(r"\s+", "", ms[-1].group(1)).rstrip(".,;]")
    return v[:60]


def short_title(text: str) -> str | None:
    m = P.SHORT_TITLE.search(text)
    if not m:
        return None
    ordinal = re.sub(r"\s+", " ", m.group(1)).strip().title()
    prefix = "Central Motor Vehicles" if re.match(r"\s*Central", m.group(0), re.I) else "Motor Vehicles"
    return f"{prefix} ({ordinal} Amendment) Rules, {m.group(2)}"


def draft_reference(text: str) -> dict | None:
    """'draft rules ... published vide G.S.R. 659(E) dated the 25th August, 2022' -> {canonical_id, date}."""
    m = DRAFT_CITE.search(text[:20000])
    if not m:
        return None
    num = int(m.group(2))
    series = P.series_code(m.group(1))
    tail = text[m.end() : m.end() + 120]
    d = P.parse_date(tail)
    if d is None:
        y = re.search(r"\b(19[89]\d|20[0-4]\d)\b", tail)
        return {"canonical_id": P.notification_canonical(series, num, int(y.group(1)) if y else None), "date": None}
    return {"canonical_id": P.notification_canonical(series, num, d.year), "date": d.isoformat()}


def fix_year_from_file_no(fa: FileAnalysis) -> None:
    """When the heading had no readable date (the year came from nearby text, often OCR noise), use stronger
    evidence from the same notification and flag the document for checking:
      1. its own short title 'Central Motor Vehicles (Fourth Amendment) Rules, 2015' -> 2015;
      2. its file number: a notification cannot be issued before its file was opened ('RT-11042/20/2005-MVL')."""
    ident = fa.identity
    if not (ident and ident.kind == "notification" and ident.doc_date is None):
        return
    this_year = date.today().year
    new, reason = None, None
    ty = re.search(r"\b((?:19|20)\d{2})\s*$", fa.official_title or "")
    if ty and int(ty.group(1)) != ident.year and int(ty.group(1)) <= this_year:
        new, reason = int(ty.group(1)), "heading date unreadable; year taken from the notification's short title"
    elif fa.file_no:
        m = re.search(r"/((?:19|20)\d{2})(?:\s*-|\s*$|/)", fa.file_no)
        fy = int(m.group(1)) if m else None
        if fy and ident.year and ident.year < fy <= this_year:
            new, reason = fy, "heading date unreadable; year taken from the file number"
    if new:
        old = ident.canonical_id
        ident.year = new
        ident.canonical_id = P.notification_canonical(
            P.series_code(ident.series), re.sub(r"\D", "", ident.number), new, "(E)" in (ident.number or "")
        )
        ident.doc_date_precision = "year"
        fa.year_note = {
            "from": old,
            "to": ident.canonical_id,
            "file_no": fa.file_no,
            "short_title": fa.official_title,
            "reason": reason,
        }


def identify(ctx: FileCtx) -> FileAnalysis:
    eng = ctx.english
    allt = full_text(ctx.pages)
    hindi = allt if not eng.strip() else None
    n_ident = notification_identity(eng, hindi) if eng.strip() or hindi else None
    # a sparse AIS cover ("Draft D0 AIS - 232 / AUTOMOTIVE INDUSTRY STANDARD") has too few words to count as English,
    # but it is where the code is printed; running headers of later pages can carry a stale number (AIS-230)
    p1 = ctx.pages[0] if ctx.pages else None
    cover = (
        f"\n<<<PAGE 1>>>\n{p1.text}"
        if p1 and p1.page == 1 and p1.text.strip() and not p1.is_english and p1.lang not in ("hi", "hi_legacy")
        else ""
    )
    a_ident = ais_identity((cover + eng)[:6000]) if eng.strip() else None
    cls = classify(ctx, n_ident, a_ident)
    ident: Identity | None = None
    dc = cls.doc_class
    if dc.is_notification:
        ident = n_ident
    elif dc.is_ais or dc == DocClass.SAFETY_STANDARD_LEGACY:
        ident = a_ident
    elif dc in (DocClass.TAP_DOCUMENT, DocClass.TAP_AMENDMENT):
        ident = tap_identity(eng) or Identity(
            kind="tap", canonical_id="TAP-115/116(Issue.4)", number="115/116", family_key="TAP-115/116"
        )
    elif dc == DocClass.FORM_TEMPLATE:
        ident = form_identity(eng, ctx.name)
    elif dc in (DocClass.MINISTERIAL_REGULATION, DocClass.DLT_NOTIFICATION, DocClass.TH_ACT, DocClass.GAZETTE_NOTICE):
        n = thai.law_identity(allt, dc.value)
        if n:
            ident = Identity(
                kind="th-law",
                canonical_id=n["canonical_id"],
                series=dc.value,
                year=n["year"],
                evidence=n["title"],
                doc_date=n["date"] or (date(n["year"], 1, 1) if n["year"] else None),
                doc_date_precision="day" if n["date"] else ("year" if n["year"] else None),
            )
    elif dc == DocClass.TIS_STANDARD:
        full = [x for x in ctx.listings if x.get("category") == thai.FULL_TEXT]
        if full:  # a full-text PDF: the number it prints that matches the standard whose page links it
            n, how = thai.full_text_identity(allt, thai.tis_number(full[0].get("title") or ""))
        else:
            n, how = thai.tis_number(allt), "content"  # the page's own มอก. heading, not the listing title
        if n:
            ident = Identity(
                kind="tis" if how != "link" else "tis-link",
                canonical_id=n["canonical_id"],
                series="TIS",
                number=n["number"],
                part=n["part"],
                year=n["year"],
                family_key=n["family_key"],
                evidence=n["tis_no"],
                doc_date=date(n["year"], 1, 1),
                doc_date_precision="year",
            )  # the edition year
    elif dc in (DocClass.MY_ACT, DocClass.MY_SUBSIDIARY_LEGISLATION):
        leg = malaysia.legal_identity(allt)
        if leg:
            ident = Identity(
                kind="my",
                canonical_id=leg["canonical_id"],
                series="PUA" if leg["kind"] == "pua" else "ACT",
                number=leg["number"],
                year=leg["year"],
                evidence=leg["ref_no"],
                doc_date=leg["published"] or date(leg["year"], 1, 1),
                doc_date_precision="day" if leg["published"] else "year",
            )
    elif dc in (DocClass.MY_GUIDELINE, DocClass.MY_FORM):
        src = malaysia.source_of(ctx.listings)
        if src:
            n = malaysia.identity(src, ctx.ext, ctx.names, allt)
            ident = Identity(kind="my", canonical_id=n["canonical_id"], series="MY", evidence=n["title"])
    elif (
        dc
        in (
            DocClass.ENERGY_STANDARD,
            DocClass.FUEL_ORDER,
            DocClass.CIRCULAR_OM,
            DocClass.GUIDELINE_POLICY,
            DocClass.BIS_REGULATION,
        )
        and n_ident
    ):
        ident = n_ident  # (Acts and consolidated rule texts reproduce other notifications: no notification identity)
    fa = FileAnalysis(ctx=ctx, cls=cls, identity=ident)
    fa.kruti = any(p.kruti >= 1 for p in ctx.pages)
    if dc.is_notification or ident and ident.kind == "notification":
        fa.gazette = gazette_fields(allt)
        fa.file_no = file_number(eng)
        fa.official_title = short_title(eng)
        fix_year_from_file_no(fa)
        fa.draft_ref = draft_reference(eng) if cls.status == "final" else None
    # listing checks (claims vs content)
    if ident and ident.kind == "notification":
        content = (P.series_code(ident.series), str(int(re.sub(r"\D", "", ident.number))))
        for lst in ctx.listings:
            claimed = title_notification_ids(lst.get("title") or "")
            others = {tuple(o.split("-")) for o in ident.ref_numbers}
            if claimed and content not in claimed and not any(c in others for c in claimed):
                fa.title_mismatch.append(
                    {
                        "source": lst.get("source"),
                        "title": lst.get("title"),
                        "claimed": [f"{s}-{n}" for s, n in claimed],
                        "content": ident.canonical_id,
                    }
                )
    if ident and ident.kind == "tis":
        for lst in ctx.listings:
            claimed = thai.tis_number(lst.get("title") or "")
            if claimed and claimed["canonical_id"] != ident.canonical_id:
                fa.title_mismatch.append(
                    {
                        "source": lst.get("source"),
                        "title": lst.get("title"),
                        "claimed": [claimed["canonical_id"]],
                        "content": ident.canonical_id,
                    }
                )
    for lst in ctx.listings:
        d = lst.get("date")
        if isinstance(d, str):
            try:
                d = date.fromisoformat(d)
            except ValueError:
                d = None
        if d and d.month == 1 and d.day == 1 and lst.get("source") == "MORTH_API":
            if not (fa.identity and fa.identity.doc_date and fa.identity.doc_date == d):
                fa.placeholder_dates.append(
                    {"source": lst.get("source"), "title": lst.get("title"), "date": d.isoformat()}
                )
    return fa


def analyse_file(ctx: FileCtx) -> dict:
    fa = identify(ctx)
    eng = ctx.english
    amd = list(P.AMD_HEADER.finditer(eng)) if fa.cls.doc_class.is_ais else []
    corr = list(P.CORR_HEADER.finditer(eng)) if fa.cls.doc_class.is_ais else []
    return {
        "sha": ctx.sha,
        "folder": ctx.folder,
        "name": ctx.name,
        "ext": ctx.ext,
        "pages": ctx.page_count,
        "scan": not ctx.text_layer and ctx.ext == "pdf",
        "scan_pages": len(ctx.scanned_pages),
        "doc_class": fa.cls.doc_class.value,
        "status": fa.cls.status,
        "why": fa.cls.reason,
        "issuer": fa.cls.issuer,
        "canonical_id": fa.canonical_id,
        "kruti": fa.kruti,
        "amd_headers": sorted({int(m.group(1)) for m in amd}),
        "corr_headers": len(corr),
        "cites_draft": fa.draft_ref,
        "title_mismatch": fa.title_mismatch,
        "placeholder": fa.placeholder_dates,
        "file_no": fa.file_no,
        "gazette": fa.gazette,
        "official_title": fa.official_title,
        "relevance": fa.cls.relevance,
        "others": fa.identity.others if fa.identity else [],
    }


# ------------------------------------------------------------------ contexts without the DB
def contexts_from_manifest() -> list[FileCtx]:
    from regtrack.pipeline.text import meta_path
    from regtrack.sources.seed_corpus import SeedFile, load_manifest, match_logs, read_logs

    man = load_manifest()
    files = [SeedFile(**d) for d in man.values()]
    rows = read_logs()
    matched = match_logs(files, rows)
    by_sha: dict[str, dict] = {}
    for i, sf in enumerate(files):
        e = by_sha.setdefault(sf.sha256, {"folders": [], "names": [], "ext": sf.ext, "listings": []})
        e["folders"].append(sf.folder)
        e["names"].append(sf.name)
        for lr in matched.get(i, []):
            e["listings"].append(
                {"source": lr.source, "title": lr.title, "date": lr.listing_date, "category": lr.category}
            )
    out = []
    for sha, e in by_sha.items():
        mp = meta_path(sha)
        if not mp.exists():
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))
        pages = load_pages(sha)
        out.append(
            FileCtx(
                None,
                sha,
                e["ext"],
                e["folders"],
                e["names"],
                pages,
                m["page_count"],
                m["text_layer"],
                m["scanned_pages"],
                e["listings"],
            )
        )
    return out
