# Phase MY-1 + TH-5: Malaysia end to end, Thai mandates, client register in the dashboard

**Date:** 22 October 2026 · continues from `phase_th_4_scope.md`. Goal: all three countries demo-ready (ingestion → structured data → dashboard), with the LLM connected later.

## What was built

| Area | What |
|---|---|
| Malaysia DB (`0017_malaysia.sql`) | Authorities (JPJ, DOE, MITI, DSM); 5 sources (JPJ VTA / CTA / Automotive Engineering Division, DOE emission control / gas-and-noise VTA guidelines), active, every 6 h; categories L1, L3, M1, N1, ALL (UNECE meanings) + scope; classes `MY_GUIDELINE` (PROCEDURE), `MY_FORM` (REFERENCE), `OFF_TOPIC`, `OTHER`; the client register's 17 Malaysia rows (MY-01 … MY-17). |
| Malaysia crawler (`regtrack/sources/malaysia.py`) | Stores each page as a write-once `.html` original plus its linked PDF/DOCX files. A page's listing id is URL + a hash of its **main content**. Visitor counters and the "Updated Date" stamp are outside it, so an unchanged page writes nothing and an edited page becomes a new version. One module serves all five source codes (`CRAWLS_BY_CODE`). |
| Malaysia pipeline (`regtrack/pipeline/malaysia.py`) | Rules only. Class by source (forms by file name / BORANG). Identity `MY-<JPJ\|DOE>-<page title \| file name>`. UNECE category words (motorcycle → L3, moped → L1, passenger car → M1, goods/commercial vehicle → N1, motor vehicles / kenderaan motor → ALL). CTA component table parser. DOE type-approval stage parser. |
| Mandates (`regtrack/pipeline/country_mandates.py`) | Thailand: each mandatory TIS is a rule (key = family, e.g. `TIS-721`, effective date from the page). Malaysia: one rule per CTA component (UN R / MS references) and per DOE stage (petrol from 2000-01-01, Third Schedule; diesel from 1997-01-01, Second Schedule; in-use diesel smoke 50 % opacity). Written through `mandates.supersede`, never updated in place. |
| Client register links | `match_requirements` (runs in `post_run`) links each TH/MY register row to the regulations that cover it (`client_requirement_regulations`, roles primary / supporting / candidate, `matched_by='rules:v1'`). |
| API + dashboard | `GET /portal/requirements`; new page **Requirements Register** (coverage KPIs, each row with its documents, open in the drawer). Malaysia added to the country selector. Tab title "Regulatory Intelligence"; Compliance subtitle no longer says "CMVR". |
| Thailand extras | Thai domains / powertrains from the title + scope (spark ignition → petrol, compression → diesel, NGV/LPG); edition year as published date; `effective_date` column from the TISI page. |
| Fixes | `ext_from` sniffs HTML (pages fetched by a crawler were stored as `.bin`; the 5 affected rows got `file_ext='html'`, originals untouched). `0018`: TH_TISI_MANDATORY `sync_frequency_minutes` 0 → 360 (the scheduler skipped it). `start.ps1` starts one auto-sync per country (IN, TH, MY; they share the pipeline advisory lock). |

## Results (live dev DB)

| Measure | India | Thailand | Malaysia |
|---|---|---|---|
| Stored files | 2,154 (unchanged) | 159 | 8 (5 pages, 2 PDF, 1 DOCX) |
| Regulations shown (excl. OFF_TOPIC) | 437 | 17 (16 in scope) | 8 |
| Mandates in force | unchanged | 17 | 14 (11 CTA + 3 DOE) |
| Client register rows covered / partial / gap | — | 7 / 1 / 7 | 15 / 2 / 0 |
| Pipeline errors | — | 0 | 0 |

All portal endpoints return 200 for IN, TH and MY, and every dashboard view was checked in the browser for each country. A re-run with no upstream change writes nothing.

`pytest`: 122 passed, 1 failed (`test_drafts_are_not_published_standards`, pre-existing), 2 skipped. 11 new Thai/Malaysian tests use real pages as fixtures. Three reference-count tests were updated for the Malaysian rows. `ruff` is clean on `regtrack/` and `tests/`.

## Waiting for the LLM (no code change needed)

- `EMBED_MODEL` is not configured: chunks exist for TH/MY, embeddings are pending. Ask AI / vector search fill in on the next pipeline run after the model is set (`EMBED_DIM` must match).
- Malaysian documents carry `llm_pending`, and the hourly catch-up enriches them once `LLM_BASE_URL` answers. Thai TIS pages are fully read by rules and need no LLM.

## Open issues

- Thailand gaps TH-02, 07, 08, 10, 13, 14, 15 need DLT / Ministry of Industry sources (DLT did not load when checked; the Royal Gazette has a captcha).
- MY-14 (EV/R100) and MY-15 (EMC/R10) are only "candidate": no Malaysian source collected so far names the adoption of these UN Regulations.
- The CTA mandates have no dates (the JPJ table gives none).
