"""Measurements for phase reports and reports/VALIDATION_REPORT.md (Phase 11), on the v4B tables.
Regulations are read in the pipeline's shape (repo.REG_SQL: canonical_id, doc_class, status, ...)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import psycopg

from regtrack import country
from regtrack.config import ROOT
from regtrack.db import connect
from regtrack.pipeline import repo

EXPECTED = [
    ("Files / unique by SHA-256", "2,274 / 2,016"),
    ("Scans (< 100 chars per page)", "251 files, 1,742 pages"),
    ("AIS files with embedded amendments", "≈ 210"),
    ("AIS files with corrigenda", "≈ 15"),
    ("Notifications with Kruti Dev Hindi", "≈ 300"),
    ("Finals citing their draft (in corpus / missing)", "225 (121 / 104)"),
    ("MoRTH title ≠ content ID", "6"),
    ("Non-automotive files in folder 02", "≈ 92 (→ OFF_TOPIC)"),
]
REQUIRED = {  # columns that must be >= 95 % filled, per population
    "all": ["canonical_id", "doc_class", "status", "issuer", "relevance", "data"],
    "notification": ["doc_date", "year", "series", "number", "nature", "subject"],
    "ais": ["doc_date", "family_key", "version_seq", "subject"],
    "ais_standard": ["official_title", "doc_date"],
}
COLUMNS = ["canonical_id", "doc_class", "series", "number", "year", "part", "revision", "amendment_no", "family_key",
           "version_seq", "official_title", "subject", "issuer", "status", "doc_date", "doc_date_precision", "nature",
           "vehicle_categories", "usage", "powertrains", "domains", "in_scope", "relevance", "data", "extraction"]


def docs(cc: str | None = None) -> str:
    """Regulations of one country in the pipeline's shape (canonical_id, doc_class, status, vehicle_categories ...)."""
    return f"({repo.REG_SQL} WHERE {country.region_sql('g', cc)})"


def one(conn: psycopg.Connection, sql: str, args=()) -> int:
    r = conn.execute(sql, args or None).fetchone()
    return list(r.values())[0] if r else 0


def regression(conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    seed = ("EXISTS (SELECT 1 FROM raw_ingestion_records s JOIN sources so ON so.id=s.source_id "
            "WHERE s.document_id=f.id AND so.code='LOCAL_SEED')")
    files = one(conn, "SELECT count(*) FROM raw_ingestion_records s JOIN sources so ON so.id=s.source_id WHERE so.code='LOCAL_SEED'")
    uniq = one(conn, f"SELECT count(*) FROM documents f WHERE {seed}")
    scans = conn.execute(f"SELECT count(*) AS n, coalesce(sum(cardinality(scanned_pages)),0) AS p FROM documents f "
                         f"WHERE {seed} AND file_ext='pdf' AND text_layer = false").fetchone()
    amd = one(conn, "SELECT count(DISTINCT p.document_id) FROM document_parts p JOIN regulations d ON d.id=p.regulation_id "
                    "WHERE d.local_class='AIS_AMENDMENT' AND p.role IN ('consolidated_segment','historical_copy','main')")
    corr = one(conn, "SELECT count(DISTINCT p.document_id) FROM document_parts p JOIN regulations d ON d.id=p.regulation_id "
                     "WHERE d.local_class='AIS_CORRIGENDUM'")
    kruti = one(conn, "SELECT count(DISTINCT f.id) FROM documents f JOIN document_parts p ON p.document_id=f.id "
                      "JOIN regulations d ON d.id=p.regulation_id WHERE d.local_class LIKE 'NOTIFICATION%' "
                      "AND (f.language_mix->>'hi_legacy_font')::boolean")
    kruti_copies = one(conn, "SELECT count(*) FROM raw_ingestion_records s JOIN sources so ON so.id=s.source_id "
                             "JOIN documents f ON f.id=s.document_id WHERE so.code='LOCAL_SEED' "
                             "AND (f.language_mix->>'hi_legacy_font')::boolean "
                             "AND EXISTS (SELECT 1 FROM document_parts p JOIN regulations d ON d.id=p.regulation_id "
                             "WHERE p.document_id=f.id AND d.local_class LIKE 'NOTIFICATION%')")
    fin = conn.execute("SELECT count(DISTINCT from_regulation_id) AS n, "
                       "count(DISTINCT from_regulation_id) FILTER (WHERE to_regulation_id IS NOT NULL) AS res "
                       "FROM regulation_relations WHERE type='finalises' AND method='regex'").fetchone()
    mism = conn.execute("SELECT count(*) FILTER (WHERE details->>'source'='MORTH_API') AS morth, count(*) AS total "
                        "FROM quality_flags WHERE rule='title_file_mismatch' "
                        "AND coalesce(details->>'resolution','') NOT LIKE 'duplicate of flag%'").fetchone()
    off02 = conn.execute(
        """SELECT count(DISTINCT f.id) AS n,
                  count(DISTINCT f.id) FILTER (WHERE d.relevance->>'state' IS NOT NULL) AS state
           FROM documents f JOIN document_parts p ON p.document_id=f.id JOIN regulations d ON d.id=p.regulation_id
           JOIN raw_ingestion_records s ON s.document_id=f.id
           WHERE d.local_class='OFF_TOPIC' AND s.payload->>'folder' LIKE '02%'""").fetchone()
    return [
        ("Files / unique by SHA-256", "2,274 / 2,016", f"{files:,} / {uniq:,}"),
        ("Scans (< 100 chars per page)", "251 files, 1,742 pages", f"{scans['n']} files, {scans['p']:,} pages"),
        ("AIS files with embedded amendments", "≈ 210", str(amd)),
        ("AIS files with corrigenda", "≈ 15", str(corr)),
        ("Notifications with Kruti Dev Hindi", "≈ 300", f"{kruti} unique files ({kruti_copies} incl. byte-copies)"),
        ("Finals citing their draft (in corpus / missing)", "225 (121 / 104)",
         f"{fin['n']} ({fin['res']} / {fin['n'] - fin['res']})"),
        ("MoRTH title ≠ content ID", "6", f"{mism['morth']} (all sources: {mism['total']})"),
        ("Non-automotive files in folder 02", "≈ 92 (→ OFF_TOPIC)",
         f"{off02['n']} OFF_TOPIC ({off02['n'] - off02['state']} non-automotive + {off02['state']} state-level)"),
    ]


def fill_rates(conn: psycopg.Connection, where: str = "doc_class <> 'OFF_TOPIC'") -> list[tuple[str, int, int]]:
    total = one(conn, f"SELECT count(*) FROM {docs()} d WHERE {where}")
    out = []
    for c in COLUMNS:
        if c in ("vehicle_categories", "usage", "powertrains", "domains"):
            cond = f"cardinality({c}) > 0"
        elif c in ("data", "relevance", "extraction"):
            cond = f"{c} IS NOT NULL AND {c}::text NOT IN ('{{}}', 'null')"
        else:
            cond = f"{c} IS NOT NULL"
        out.append((c, one(conn, f"SELECT count(*) FROM {docs()} d WHERE {where} AND {cond}"), total))
    return out


def agreement(conn: psycopg.Connection) -> dict:
    rows = conn.execute(f"SELECT extraction->'agreement' AS a FROM regulations g WHERE extraction ? 'agreement' "
                        f"AND {country.region_sql('g')}").fetchall()
    out = {}
    for f in ("number", "date", "status"):
        vals = [r["a"].get(f) for r in rows if r["a"] and r["a"].get(f) is not None]
        out[f] = (sum(1 for v in vals if v), len(vals))
    return out


def md_table(head: list[str], rows: list[list]) -> str:
    s = "| " + " | ".join(head) + " |\n|" + "|".join("---" for _ in head) + "|\n"
    for r in rows:
        s += "| " + " | ".join(str(x) for x in r) + " |\n"
    return s


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "n/a"


def write_validation_report(path: Path | None = None) -> str:
    path = path or ROOT / "reports" / "VALIDATION_REPORT.md"
    with connect() as conn:
        reg = regression(conn)
        out = [f"# RegTrack India — Validation report\n\nGenerated {datetime.now():%Y-%m-%d %H:%M}.\n"]
        cc = country.code()
        r = country.region_sql("x", cc)
        counts = conn.execute(
            f"SELECT (SELECT count(*) FROM documents x WHERE {r}) AS files, "
            f"(SELECT count(*) FROM regulations x WHERE {r}) AS docs, "
            f"(SELECT count(*) FROM regulation_relations rr JOIN regulations x ON x.id=rr.from_regulation_id WHERE {r}) AS rels, "
            f"(SELECT count(*) FROM requirement_versions v JOIN compliance_requirements x ON x.id=v.requirement_id "
            f"WHERE {r}) AS mandates, "
            f"(SELECT count(*) FROM document_chunks x WHERE {r}) AS chunks, "
            f"(SELECT count(*) FROM document_chunks x WHERE embedding IS NOT NULL AND {r}) AS emb, "
            f"(SELECT count(*) FROM regulation_changes x WHERE {r}) AS events").fetchone()
        out.append(md_table(list(counts.keys()), [list(counts.values())]))
        stages = conn.execute(f"SELECT stage, count(*) AS n FROM documents x WHERE {r} GROUP BY 1 ORDER BY 1").fetchall()
        out.append("\n## Files by stage\n\n" + md_table(["stage", "files"], [[r["stage"], r["n"]] for r in stages]))
        out.append("\n## Regression table (CLAUDE.md) — measured vs expected\n\n" + md_table(["Measure", "Expected", "Measured"],
                                                                                            [list(r) for r in reg]))
        fr = fill_rates(conn)
        out.append("\n## Fill rate per column (documents excl. OFF_TOPIC)\n\n" +
                   md_table(["column", "filled", "total", "rate"], [[c, a, b, pct(a, b)] for c, a, b in fr]))
        out.append("\n## Required columns (threshold ≥ 95 %)\n")
        rows = []
        pops = {"all": "doc_class <> 'OFF_TOPIC'", "notification": "doc_class LIKE 'NOTIFICATION%' AND canonical_id NOT LIKE 'NOTIF-%'",
                "ais": "doc_class IN ('AIS_STANDARD','AIS_AMENDMENT','AIS_CORRIGENDUM') AND canonical_id NOT LIKE 'AIS-UNIDENT%'",
                "ais_standard": "doc_class = 'AIS_STANDARD' AND canonical_id NOT LIKE 'AIS-UNIDENT%'"}
        for pop, cols in REQUIRED.items():
            rates = {c: (a, b) for c, a, b in fill_rates(conn, pops[pop])}
            for c in cols:
                a, b = rates[c]
                rows.append([pop, c, a, b, pct(a, b), "PASS" if b and a / b >= 0.95 else "FAIL"])
        out.append(md_table(["population", "column", "filled", "total", "rate", "≥95%"], rows))
        ag = agreement(conn)
        out.append("\n## Qwen double-extraction agreement (identity / status / date, threshold ≥ 90 %)\n\n" + md_table(
            ["field", "agree", "checked", "rate"], [[f, a, b, pct(a, b)] for f, (a, b) in ag.items()]))
        flags = conn.execute(f"""SELECT rule, entity, count(*) AS n FROM quality_flags q WHERE resolved_at IS NULL
                                 AND ((entity='regulation' AND entity_id IN (SELECT id FROM regulations x WHERE {r}))
                                   OR (entity='document' AND entity_id IN (SELECT id FROM documents x WHERE {r}))
                                   OR (entity='requirement_version' AND entity_id IN (
                                         SELECT v.id FROM requirement_versions v JOIN compliance_requirements x
                                         ON x.id=v.requirement_id WHERE {r}))
                                   OR entity NOT IN ('regulation','document','requirement_version'))
                                 GROUP BY 1,2 ORDER BY 3 DESC""").fetchall()
        out.append("\n## Open quality flags by rule\n\n" + md_table(["rule", "entity", "open"], [[r["rule"], r["entity"], r["n"]] for r in flags]))
        res = conn.execute(
            """SELECT rule, details->>'resolution' AS how, count(*) AS n,
                      (array_agg(left((details->'evidence')::text, 150) ORDER BY id))[1] AS example
               FROM quality_flags
               WHERE resolved_at IS NOT NULL AND coalesce(details->>'resolution','') NOT LIKE 'duplicate of flag%'
               GROUP BY 1, 2 ORDER BY 1, 3 DESC""").fetchall()
        out.append("\n## Resolved flags by rule and resolution (`regtrack/pipeline/resolve.py`)\n\n"
                   "Flags settled by evidence keep the evidence in `quality_flags.details`; 'superseded' = the flag "
                   "described an older state (e.g. before a re-split) and was replaced; 'document retired' = the "
                   "document was re-identified. Re-raised duplicates of resolved flags are excluded.\n\n" + md_table(
            ["rule", "resolution", "flags", "example evidence"],
            [[r["rule"], r["how"] or "(no reason recorded)", r["n"], (r["example"] or "").replace("|", "/")] for r in res]))
        top = conn.execute(
            """SELECT d.canonical_id, d.doc_class, count(q.id) AS flags, string_agg(DISTINCT q.rule, ', ') AS rules,
                      coalesce(d.official_title, d.subject, '') AS title
               FROM """ + docs(cc) + """ d JOIN quality_flags q ON q.entity='regulation' AND q.entity_id=d.id AND q.resolved_at IS NULL
               WHERE d.doc_class <> 'OFF_TOPIC' AND (d.in_scope OR d.doc_class LIKE 'AIS%' OR d.doc_class LIKE 'NOTIF%')
               GROUP BY d.id, d.canonical_id, d.doc_class, d.official_title, d.subject, d.in_scope, d.doc_date
               ORDER BY (d.in_scope IS TRUE) DESC, count(q.id) DESC, d.doc_date DESC NULLS LAST, d.canonical_id LIMIT 20""").fetchall()
        out.append("\n## Top 20 documents that need checking\n\n" + md_table(
            ["canonical_id", "class", "flags", "rules", "title"],
            [[r["canonical_id"], r["doc_class"], r["flags"], r["rules"], (r["title"] or "")[:80]] for r in top]))
        llm_pending = one(conn, f"SELECT count(*) FROM regulations x WHERE (extraction->>'llm_pending')::boolean AND {r}")
        out.append(f"\n## LLM status\n\nDocuments waiting for the Qwen pass (llm_pending): {llm_pending}.\n"
                   f"Chunks without embedding: {counts['chunks'] - counts['emb']}.\n")
    text = "\n".join(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)
