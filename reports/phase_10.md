# Phase 10 — Read-only API (`regtrack/api/app.py`)

Start: `python -m regtrack.cli api` → http://127.0.0.1:8000/docs. No LLM call at read time except embedding the
`/search` query (with a text fallback while embeddings are unavailable). Examples below come from
`scripts/api_examples.py` (FastAPI TestClient against the live database).

| Endpoint | Purpose |
|---|---|
| `GET /vehicles/applicable?category=&engine_cc=&power_kw=&gvw_kg=&seats=&powertrain=&usage=&on=` | mandates valid on a date for a vehicle (category ∪ ALL, numeric conditions, powertrain/usage), with each standard's current version and amendments |
| `GET /documents?year=&category=&doc_class=&domain=&in_scope=&nature=&status=&is_current=&q=` | year / category / class views, paged |
| `GET /documents/{canonical_id}` | document + files (best copy first, sightings) + relations in/out + mandates + open flags |
| `GET /families/{family_key}/versions` | version view in `version_seq` order |
| `GET /changes?since=` | change events detected by live crawls |
| `GET /search?q=&category=&in_scope=&is_current=&doc_class=` | filtered chunk search |
| `GET /share-pack?category=&on=&technical_only=` | zip of best-copy originals + `manifest.csv` |

## Example responses (abridged)
```
GET /vehicles/applicable?category=L2&engine_cc=110&powertrain=petrol&on=2026-01-01   -> 200, 20 mandates, e.g.
  SO-1365(E)-2004 Table Sr.8(a)  "Wheel rims fitted in all motor vehicles"  [IS 9438:1980, IS 9436:1980]  2004-12-13  (S.O. 1406(E)-2021)
  SO-1365(E)-2004 Table Sr.43(a) "light alloy / sheet metal / spoke wheel rims, L category"  [AIS-073]   2008-04-01
  CMVR Rule 138 (spare wheel ...)                                       [AIS-072]          2014-10-01  (G.S.R. 291(E)-2014)

GET /documents?year=2022&category=M1&doc_class=NOTIFICATION_FINAL&limit=3   -> total 5
  GSR-863(E)-2022 "Central Motor Vehicles (Twenty-Second Amendment) Rules, 2022"  2022-12-01  [M1..N3]  in_scope
  GSR-797(E)-2022 "Central Motor Vehicles (Seventeenth Amendment) Rules, 2022"    2022-10-31

GET /documents/SO-3896(E)-2022   -> NOTIFICATION_EXTENSION, family SO-1365-MASTER,
  relations_out: extends_date SO-1365(E)-2004 {table: "Table", rows: ["8"], old_date: 2022-09-21, new_date: 2023-06-22} ...
  mandates: SO-1365(E)-2004 Table Sr.43(b), Table A Sr.6(b), Table B Sr.2(e..g) ...

GET /documents/AIS-156/Amd.5   -> AIS_AMENDMENT, issued 2026-08, amends AIS-156 (resolved)

GET /families/AIS-038/versions   -> current AIS-038(Rev.2)
  AIS-038 (1, superseded) · AIS-038(Rev.1) (2, superseded) · AIS-038(Rev.2) (3, final, current) · Rev.2/Amd.1..3 (4..6)

GET /families/SO-1365-MASTER/versions   -> 18 notifications, current SO-3800(E)-2023

GET /changes?since=2026-10-01   -> new_document / draft_published / draft_finalised / implementation_date_changed events
  from the live crawls (summaries are templates marked needs_check until Qwen is reachable)

GET /search?q=anti-lock braking&category=L2   -> mode "text (embeddings unavailable)", AIS-004(Part3)(Rev.1) §44 ...

GET /share-pack?category=L2   -> application/zip "regtrack_share_pack_L2_2026-10-08.zip", 67 MB,
  63 originals + manifest.csv (canonical_id, doc_class, title, doc_date, status, family_key, version_seq, is_current,
  vehicle_categories, file_in_zip, sha256, pages, role, source_urls)
```

## Fixes made in this phase
- Untyped NULL parameters in the condition filters (`%s IS NULL`) → cast to `numeric`.

## Open issues
- `/search` ranks by trigram similarity until embeddings exist.
- Mandate subjects from rule obligations are the full sentence; Qwen's `subject` will shorten them.
