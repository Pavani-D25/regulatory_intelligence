"""Deterministic resolution of quality flags (no LLM). A flag is resolved only when the evidence settles it;
the evidence is written into quality_flags.details (resolution, evidence) so every resolution can be audited.
Entities (v4B): 'document' = a stored file (documents), 'regulation' = regulations.
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
    conn.execute("UPDATE quality_flags SET resolved_at=now(), details=coalesce(details,'{}'::jsonb) || %s::jsonb "
                 "WHERE id=%s AND resolved_at IS NULL",
                 (json.dumps({"resolution": resolution, "evidence": evidence}, default=str), flag_id))


def _file_text(sha: str) -> str:
    return "".join(p.text for p in load_pages(sha))


# ---------------------------------------------------------------- title_file_mismatch
def verify_title_mismatches(conn: psycopg.Connection) -> int:
    """The listing names an ID that never occurs in the file, and the Gazette sub-section (if read) agrees with the
    content's series (G.S.R. → Part II-3(i), S.O. → Part II-3(ii)): the listing is wrong, the content identity stands."""
    n = 0
    for q in conn.execute("""SELECT q.id, q.entity_id, q.details, f.checksum_sha256 AS sha256 FROM quality_flags q
                             JOIN documents f ON f.id=q.entity_id
                             WHERE q.rule='title_file_mismatch' AND q.entity='document' AND q.resolved_at IS NULL
                               AND """ + country.region_sql("f")).fetchall():
        d = q["details"]
        doc = conn.execute("""SELECT g.external_code AS canonical_id, g.data->'gazette'->>'sub_section' AS sub
                              FROM regulations g JOIN document_parts p ON p.regulation_id=g.id
                              WHERE p.document_id=%s AND g.external_code=%s""",
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
    for q in conn.execute("""SELECT q.id, q.entity_id, q.details, d.family_key, d.external_code AS canonical_id
                             FROM quality_flags q JOIN regulations d ON d.id=q.entity_id
                             WHERE q.rule='amendment_gap' AND q.entity='regulation' AND q.resolved_at IS NULL
                               AND """ + country.region_sql("d")).fetchall():
        target, missing = q["details"]["target"], set(q["details"]["missing"])
        why: dict[int, str] = {}
        # (a) the amendment exists under a sibling id of the same family (header named the standard without Rev/Part)
        for r in conn.execute("""SELECT external_code AS canonical_id, amendment_no FROM regulations WHERE family_key=%s
                                 AND local_class='AIS_AMENDMENT' AND data->>'amends' <> %s AND """ + country.region_sql(),
                              (q["family_key"], target)).fetchall():
            if r["amendment_no"] in missing:
                why.setdefault(r["amendment_no"], f"present as {r['canonical_id']}")
        # (b) ARAI's listing for this standard's files says the file includes the amendment
        claims = [r["t"] for r in conn.execute(
            """SELECT DISTINCT s.listing_title t FROM regulations d JOIN document_parts p ON p.regulation_id=d.id
               JOIN raw_ingestion_records s ON s.document_id=p.document_id
               JOIN sources so ON so.id=s.source_id AND so.code='ARAI_AIS'
               WHERE (d.external_code=%s OR d.data->>'amends'=%s) AND """ + country.region_sql("d"), (target, target))]
        for t in claims:
            parsed = parse_arai_code(t or "")
            if parsed.get("code") is not None and f"AIS-{parsed['code']:03d}" not in target:
                continue  # a listing row of another standard sharing the file
            for a in parsed.get("amendments", []):
                if a in missing:
                    why.setdefault(a, f"incorporated in the consolidated file (ARAI listing: '{t}')")
        # (c) the cover says which amendments are incorporated
        for r in conn.execute("""SELECT DISTINCT fo.checksum_sha256 AS sha256 FROM regulations d
                                 JOIN document_parts p ON p.regulation_id=d.id JOIN documents fo ON fo.id=p.document_id
                                 WHERE d.external_code=%s AND """ + country.region_sql("d"), (target,)).fetchall():
            head = "".join(p.text for p in load_pages(r["sha256"])[:3])
            for m in INCORPORATING.finditer(head):
                for a in (int(x) for x in re.findall(r"No\.?\s*(\d{1,2})", m.group(1))):
                    if a in missing:
                        why.setdefault(a, f"incorporated per cover: '{re.sub(chr(10), ' ', m.group(0))[:120]}'")
        if missing and set(why) >= missing:
            _resolve(conn, q["id"], "every missing amendment is accounted for", {str(k): v for k, v in sorted(why.items())})
            n += 1
        elif why and q["details"].get("explained") != {str(k): v for k, v in sorted(why.items())}:
            conn.execute("UPDATE quality_flags SET details = details || %s::jsonb WHERE id=%s",
                         (json.dumps({"explained": {str(k): v for k, v in sorted(why.items())}}), q["id"]))
    return n


# ---------------------------------------------------------------- placeholder_listing_date
def resolve_placeholder_dates(conn: psycopg.Connection) -> int:
    """The listing's 1 January date was a placeholder; resolved when the document has its own date from the content."""
    n = 0
    for q in conn.execute("""SELECT q.id, q.details, max(d.published_date) AS doc_date FROM quality_flags q
                             JOIN document_parts p ON p.document_id=q.entity_id JOIN regulations d ON d.id=p.regulation_id
                             WHERE q.rule='placeholder_listing_date' AND q.resolved_at IS NULL AND q.entity='document'
                               AND """ + country.region_sql("d") + """
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
    for q in conn.execute("""SELECT q.id, q.entity_id, d.year FROM quality_flags q JOIN regulations d ON d.id=q.entity_id
                             WHERE q.rule='identity_year_inferred' AND q.entity='regulation' AND q.resolved_at IS NULL
                               AND """ + country.region_sql("d")).fetchall():
        years = [r["y"] for r in conn.execute(
            """SELECT DISTINCT extract(year FROM s.listing_date)::int AS y FROM document_parts p
               JOIN raw_ingestion_records s ON s.document_id=p.document_id WHERE p.regulation_id=%s
               AND s.listing_date IS NOT NULL
               AND NOT (extract(month FROM s.listing_date)=1 AND extract(day FROM s.listing_date)=1)""", (q["entity_id"],))]
        if q["year"] in years:
            _resolve(conn, q["id"], "file-number year confirmed by the listing date", {"listing_years": years})
            n += 1
    return n


def resolve_all(conn: psycopg.Connection) -> dict:
    return {"title_file_mismatch": verify_title_mismatches(conn), "amendment_gap": resolve_amendment_gaps(conn),
            "placeholder_listing_date": resolve_placeholder_dates(conn),
            "identity_year_inferred": corroborate_inferred_years(conn)}
