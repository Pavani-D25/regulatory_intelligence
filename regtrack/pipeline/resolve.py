"""Deterministic resolution of quality flags (no LLM). A flag is resolved only when the evidence settles it;
the evidence is written into quality_flag.details (resolution, evidence) so every resolution can be audited.
Unsettled flags stay open. Runs at the end of every pipeline run and via `python -m regtrack.cli resolve-flags`.
"""

from __future__ import annotations

import json
import re

import psycopg

from regtrack import country
from regtrack.pipeline.identity import parse_arai_code
from regtrack.pipeline.text import load_pages

SERIES_RX = {"GSR": r"G\s?[.,]?\s?S\s?[.,]?\s?R", "SO": r"S\s?\.?\s?O"}


def _resolve(conn: psycopg.Connection, flag_id: int, resolution: str, evidence: dict) -> None:
    conn.execute("UPDATE quality_flag SET resolved_at=now(), details=coalesce(details,'{}'::jsonb) || %s::jsonb "
                 "WHERE id=%s AND resolved_at IS NULL",
                 (json.dumps({"resolution": resolution, "evidence": evidence}, default=str), flag_id))


def _file_text(sha: str) -> str:
    return "".join(p.text for p in load_pages(sha))


# ---------------------------------------------------------------- title_file_mismatch
def verify_title_mismatches(conn: psycopg.Connection) -> int:
    """The listing names an ID that never occurs in the file, and the Gazette sub-section (if read) agrees with the
    content's series (G.S.R. → Part II-3(i), S.O. → Part II-3(ii)): the listing is wrong, the content identity stands."""
    n = 0
    for q in conn.execute("""SELECT q.id, q.entity_id, q.details, f.sha256 FROM quality_flag q JOIN file_object f ON f.id=q.entity_id
                             WHERE q.rule='title_file_mismatch' AND q.resolved_at IS NULL AND """ + country.sql("f")).fetchall():
        d = q["details"]
        doc = conn.execute("""SELECT d.canonical_id, d.data->'gazette'->>'sub_section' AS sub FROM document d
                              JOIN document_file df ON df.document_id=d.id WHERE df.file_id=%s AND d.canonical_id=%s""",
                           (q["entity_id"], d.get("content"))).fetchone()
        if not doc:
            continue
        text = _file_text(q["sha256"])
        absent = []
        for claim in d.get("claimed", []):
            s, num = claim.split("-", 1)
            rx = SERIES_RX.get(s, s) + r"\s*\.?\s*(?:No\.?\s*)?0*" + re.escape(num) + r"\b"
            absent.append(re.search(rx, text, re.I) is None)
        series = doc["canonical_id"].split("-")[0]
        expected_sub = {"GSR": "(i)", "SO": "(ii)"}.get(series)
        sub_ok = doc["sub"] in (None, expected_sub)
        if absent and all(absent) and sub_ok:
            _resolve(conn, q["id"], "listing title wrong; identity from content confirmed",
                     {"claimed_absent_from_file": d.get("claimed"), "content_id": doc["canonical_id"],
                      "gazette_sub_section": doc["sub"] or "not read (scan)"})
            n += 1
    return n


# ---------------------------------------------------------------- amendment_gap
INCORPORATING = re.compile(r"Incorporating\s+(Amendments?\s+No\.?\s*[\d\s,.&/and\-–A-Za-z]{1,120}?)\)", re.I | re.S)


def resolve_amendment_gaps(conn: psycopg.Connection) -> int:
    n = 0
    for q in conn.execute("""SELECT q.id, q.entity_id, q.details, d.family_key, d.canonical_id FROM quality_flag q
                             JOIN document d ON d.id=q.entity_id
                             WHERE q.rule='amendment_gap' AND q.resolved_at IS NULL AND """ + country.sql("d")).fetchall():
        target, missing = q["details"]["target"], set(q["details"]["missing"])
        why: dict[int, str] = {}
        # (a) the amendment exists under a sibling id of the same family (header named the standard without Rev/Part)
        for r in conn.execute("""SELECT canonical_id, amendment_no FROM document WHERE family_key=%s
                                 AND doc_class='AIS_AMENDMENT' AND data->>'amends' <> %s""", (q["family_key"], target)):
            if r["amendment_no"] in missing:
                why.setdefault(r["amendment_no"], f"present as {r['canonical_id']}")
        # (b) ARAI's listing for this standard's files says the file includes the amendment
        claims = [r["t"] for r in conn.execute(
            """SELECT DISTINCT s.listing_title t FROM document d JOIN document_file df ON df.document_id=d.id
               JOIN file_sighting s ON s.file_id=df.file_id JOIN source so ON so.id=s.source_id AND so.code='ARAI_AIS'
               WHERE d.canonical_id=%s OR d.data->>'amends'=%s""", (target, target))]
        for t in claims:
            parsed = parse_arai_code(t or "")
            if parsed.get("code") is not None and f"AIS-{parsed['code']:03d}" not in target:
                continue  # a listing row of another standard sharing the file
            for a in parsed.get("amendments", []):
                if a in missing:
                    why.setdefault(a, f"incorporated in the consolidated file (ARAI listing: '{t}')")
        # (c) the cover says which amendments are incorporated
        for r in conn.execute("""SELECT DISTINCT fo.sha256 FROM document d JOIN document_file df ON df.document_id=d.id
                                 JOIN file_object fo ON fo.id=df.file_id WHERE d.canonical_id=%s""", (target,)):
            head = "".join(p.text for p in load_pages(r["sha256"])[:3])
            for m in INCORPORATING.finditer(head):
                for a in (int(x) for x in re.findall(r"No\.?\s*(\d{1,2})", m.group(1))):
                    if a in missing:
                        why.setdefault(a, f"incorporated per cover: '{re.sub(chr(10), ' ', m.group(0))[:120]}'")
        if missing and set(why) >= missing:
            _resolve(conn, q["id"], "every missing amendment is accounted for", {str(k): v for k, v in sorted(why.items())})
            n += 1
        elif why and q["details"].get("explained") != {str(k): v for k, v in sorted(why.items())}:
            conn.execute("UPDATE quality_flag SET details = details || %s::jsonb WHERE id=%s",
                         (json.dumps({"explained": {str(k): v for k, v in sorted(why.items())}}), q["id"]))
    return n


# ---------------------------------------------------------------- placeholder_listing_date
def resolve_placeholder_dates(conn: psycopg.Connection) -> int:
    """The listing's 1 January date was a placeholder; resolved when the document has its own date from the content."""
    n = 0
    for q in conn.execute("""SELECT q.id, q.details, max(d.doc_date) AS doc_date FROM quality_flag q
                             JOIN document_file df ON df.file_id=q.entity_id JOIN document d ON d.id=df.document_id
                             WHERE q.rule='placeholder_listing_date' AND q.resolved_at IS NULL AND q.entity='file_object'
                               AND """ + country.sql("d") + """
                             GROUP BY q.id, q.details""").fetchall():
        if q["doc_date"]:
            _resolve(conn, q["id"], "content date used; listing placeholder ignored",
                     {"listing_date": q["details"].get("date"), "content_date": q["doc_date"]})
            n += 1
    return n


# ---------------------------------------------------------------- identity_year_inferred
def corroborate_inferred_years(conn: psycopg.Connection) -> int:
    """A year taken from the file number is confirmed when an independent listing date has the same year."""
    n = 0
    for q in conn.execute("""SELECT q.id, q.entity_id, d.year FROM quality_flag q JOIN document d ON d.id=q.entity_id
                             WHERE q.rule='identity_year_inferred' AND q.resolved_at IS NULL AND """ + country.sql("d")).fetchall():
        years = [r["y"] for r in conn.execute(
            """SELECT DISTINCT extract(year FROM s.listing_date)::int AS y FROM document_file df
               JOIN file_sighting s ON s.file_id=df.file_id WHERE df.document_id=%s AND s.listing_date IS NOT NULL
               AND NOT (extract(month FROM s.listing_date)=1 AND extract(day FROM s.listing_date)=1)""", (q["entity_id"],))]
        if q["year"] in years:
            _resolve(conn, q["id"], "file-number year confirmed by the listing date", {"listing_years": years})
            n += 1
    return n


def resolve_all(conn: psycopg.Connection) -> dict:
    return {"title_file_mismatch": verify_title_mismatches(conn), "amendment_gap": resolve_amendment_gaps(conn),
            "placeholder_listing_date": resolve_placeholder_dates(conn),
            "identity_year_inferred": corroborate_inferred_years(conn)}
