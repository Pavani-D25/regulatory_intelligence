# RegTrack India — Validation report

Generated 2026-10-08 14:51.

| files | docs | rels | mandates | chunks | emb | events |
|---|---|---|---|---|---|---|
| 2142 | 2064 | 5398 | 178 | 148323 | 0 | 123 |


## Files by stage

| stage | files |
|---|---|
| chunked | 2142 |


## Regression table (CLAUDE.md) — measured vs expected

| Measure | Expected | Measured |
|---|---|---|
| Files / unique by SHA-256 | 2,274 / 2,016 | 2,274 / 2,018 |
| Scans (< 100 chars per page) | 251 files, 1,742 pages | 248 files, 1,724 pages |
| AIS files with embedded amendments | ≈ 210 | 181 |
| AIS files with corrigenda | ≈ 15 | 14 |
| Notifications with Kruti Dev Hindi | ≈ 300 | 232 unique files (276 incl. byte-copies) |
| Finals citing their draft (in corpus / missing) | 225 (121 / 104) | 207 (94 / 113) |
| MoRTH title ≠ content ID | 6 | 14 (all sources: 16) |
| Non-automotive files in folder 02 | ≈ 92 (→ OFF_TOPIC) | 138 OFF_TOPIC (47 non-automotive + 91 state-level) |


## Fill rate per column (documents excl. OFF_TOPIC)

| column | filled | total | rate |
|---|---|---|---|
| canonical_id | 1864 | 1864 | 100.0% |
| doc_class | 1864 | 1864 | 100.0% |
| series | 878 | 1864 | 47.1% |
| number | 1404 | 1864 | 75.3% |
| year | 1190 | 1864 | 63.8% |
| part | 186 | 1864 | 10.0% |
| revision | 176 | 1864 | 9.4% |
| amendment_no | 337 | 1864 | 18.1% |
| family_key | 836 | 1864 | 44.8% |
| version_seq | 830 | 1864 | 44.5% |
| official_title | 511 | 1864 | 27.4% |
| subject | 1682 | 1864 | 90.2% |
| issuer | 1827 | 1864 | 98.0% |
| status | 1864 | 1864 | 100.0% |
| doc_date | 1334 | 1864 | 71.6% |
| doc_date_precision | 1357 | 1864 | 72.8% |
| nature | 1673 | 1864 | 89.8% |
| vehicle_categories | 1043 | 1864 | 56.0% |
| usage | 251 | 1864 | 13.5% |
| powertrains | 333 | 1864 | 17.9% |
| domains | 1369 | 1864 | 73.4% |
| in_scope | 1864 | 1864 | 100.0% |
| relevance | 1864 | 1864 | 100.0% |
| data | 1822 | 1864 | 97.7% |
| extraction | 1864 | 1864 | 100.0% |


## Required columns (threshold ≥ 95 %)

| population | column | filled | total | rate | ≥95% |
|---|---|---|---|---|---|
| all | canonical_id | 1864 | 1864 | 100.0% | PASS |
| all | doc_class | 1864 | 1864 | 100.0% | PASS |
| all | status | 1864 | 1864 | 100.0% | PASS |
| all | issuer | 1827 | 1864 | 98.0% | PASS |
| all | relevance | 1864 | 1864 | 100.0% | PASS |
| all | data | 1822 | 1864 | 97.7% | PASS |
| notification | doc_date | 504 | 527 | 95.6% | PASS |
| notification | year | 527 | 527 | 100.0% | PASS |
| notification | series | 527 | 527 | 100.0% | PASS |
| notification | number | 527 | 527 | 100.0% | PASS |
| notification | nature | 413 | 527 | 78.4% | FAIL |
| notification | subject | 419 | 527 | 79.5% | FAIL |
| ais | doc_date | 537 | 643 | 83.5% | FAIL |
| ais | family_key | 643 | 643 | 100.0% | PASS |
| ais | version_seq | 643 | 643 | 100.0% | PASS |
| ais | subject | 643 | 643 | 100.0% | PASS |
| ais_standard | official_title | 295 | 295 | 100.0% | PASS |
| ais_standard | doc_date | 266 | 295 | 90.2% | FAIL |


## Qwen double-extraction agreement (identity / status / date, threshold ≥ 90 %)

| field | agree | checked | rate |
|---|---|---|---|
| number | 0 | 0 | n/a |
| date | 0 | 0 | n/a |
| status | 0 | 0 | n/a |


## Open quality flags by rule

| rule | entity | open |
|---|---|---|
| no_vehicle_category | document | 380 |
| off_topic | document | 200 |
| identity_not_found | document | 116 |
| unresolved_reference | document | 113 |
| placeholder_listing_date | file_object | 25 |
| low_ocr_confidence | file_object | 22 |
| old_date_mismatch | mandate | 9 |
| duplicate_identity_diff_header | document | 6 |
| draft_final_date_mismatch | document | 1 |


## Resolved flags by rule and resolution (`regtrack/pipeline/resolve.py`)

Flags settled by evidence keep the evidence in `quality_flag.details`; 'superseded' = the flag described an older state (e.g. before a re-split) and was replaced; 'document retired' = the document was re-identified. Re-raised duplicates of resolved flags are excluded.

| rule | resolution | flags | example evidence |
|---|---|---|---|
| amendment_gap | every missing amendment is accounted for | 22 | {"1": "incorporated per cover: 'Incorporating  Amendment  No. 1/September 1999 & Amendment  No. 2/September 2000)'", "2": "incorporated per cover: 'In |
| amendment_gap | superseded: the amendment list of this standard changed | 11 |  |
| amendment_gap | document retired after re-classification | 1 |  |
| identity_year_inferred | file-number year confirmed by the listing date | 3 | {"listing_years": [2005]} |
| identity_year_inferred | document retired after re-classification | 1 |  |
| no_vehicle_category | document retired after re-classification | 1 |  |
| placeholder_listing_date | content date used; listing placeholder ignored | 22 | {"content_date": "2000-12-27", "listing_date": "2000-01-01"} |
| title_file_mismatch | listing title wrong; identity from content confirmed | 16 | {"content_id": "SO-2412(E)-2015", "gazette_sub_section": "not read (scan)", "claimed_absent_from_file": ["SO-728"]} |


## Top 20 documents that need checking

| canonical_id | class | flags | rules | title |
|---|---|---|---|---|
| GSR-291(E)-2014 | NOTIFICATION_FINAL | 3 | duplicate_identity_diff_header, unresolved_reference | Amends CMVR Rule 2, CMVR Rule 126, CMVR Rule 35(1), CMVR Rule 39, CMVR Rule 101, |
| NOTIF-4689ed122764b5d0 | NOTIFICATION_FINAL | 2 | identity_not_found, unresolved_reference | Central Motor Vehicles (First Amendment) Rules, 2004 |
| NOTIF-33bd3cc437e950bc | NOTIFICATION_FINAL | 2 | identity_not_found, unresolved_reference | Central Motor Vehicles (Third Amendment) Rules, 2002 |
| AIS-009(Rev.3) | AIS_STANDARD | 1 | no_vehicle_category | Uniform Provisions Concerning The Approval Of Light Signaling Devices And System |
| GSR-850(E)-2025 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Fifth Amendment) Rules, 2025 |
| GSR-514(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Tenth Amendment) Rules, 2024 |
| GSR-195(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Seventh Amendment) Rules, 2024 |
| GSR-27(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (First Amendment) Rules, 2024 |
| GSR-698(E)-2023 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Sixth Amendment) Rules, 2023 |
| GSR-226(E)-2023 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Second Amendment) Rules, 2023 |
| GSR-863(E)-2022 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Twenty-Second Amendment) Rules, 2022 |
| GSR-394(E)-2022 | NOTIFICATION_FINAL | 1 | unresolved_reference |  |
| GSR-596(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Eighteenth Amendment) Rules, 2021 |
| GSR-410(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Thirteenth Amendment) Rules, 2021 |
| GSR-394(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Eleventh Amendment) Rules, 2021 |
| GSR-240(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Sixth Amendment) Rules, 2021 |
| GSR-628(E)-2020 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Fourteenth Amendment) Rules, 2020 |
| AIS-038(Rev.2) | AIS_STANDARD | 1 | no_vehicle_category | AIS-038 (Rev. 2) |
| GSR-414(E)-2020 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Sixth Amendment) Rules, 2020 |
| GSR-337(E)-2020 | NOTIFICATION_FINAL | 1 | unresolved_reference | Amends CMVR Rule 2, CMVR Rule 126 |


## LLM status

Documents waiting for the Qwen pass (llm_pending): 1658.
Chunks without embedding: 148323.

## Assessment against the thresholds (updated 8 Oct 2026, after the non-LLM flag pass)

**Required columns ≥ 95 %: 14 of 18 pass.** The four below the line need Qwen or are genuinely absent:
notification `subject` (79.5 %) and `nature` (78.4 %) — Qwen pass; AIS `doc_date` (83.5 %) — 106 amendments
use the header format with no date at all; AIS_STANDARD `doc_date` (90.2 %) — covers without a month/year
(scans, consolidated reprints).

**Qwen agreement ≥ 90 %: not measurable yet** (LM Studio URL not set). `python -m regtrack.cli llm-smoke` checks the
connection on 10 documents; `python -m regtrack.cli run` then processes all pending documents and the 10 % sample.

**Non-LLM flags resolved in this pass** (`regtrack/pipeline/resolve.py`, evidence stored in each flag):

| Flag | Before | Now open | How |
|---|---|---|---|
| `title_file_mismatch` | 16 open | **0** | all 16 verified: the listing's claimed ID never occurs in the file and the Gazette sub-section agrees with the content's series (the 6 known MoRTH cases, 6 "S.O." listings of G.S.R. scans, S.O. 1407→1450, G.S.R. 07→26 (the ETL_SPEC example), 2 India Code). The measured count (14 MoRTH / 16 all) stays in the regression table — the discrepancies are real, the identities are confirmed. |
| `amendment_gap` | 21 open | **0** | 3 header misses fixed in the splitter ("Contents"/"Amendment Record" inside an amendment's own instructions hid its header; two-digit "AIS-37") → 5 new amendment documents; a file whose headers all name AIS-071(Part 2) was re-identified (cover misread as AIS-007); every remaining gap is accounted for: the ARAI listing says the file incorporates it ("AIS-156 and Amd. 1 to 5"), the cover says so ("Incorporating Amendment No. 1 …"), or the amendment is stored under a sibling ID. These amendments are not available as separate documents — only inside consolidated texts. |
| doubtful years | 2 | **0** | "SO-701(E)-1989" was `cmvr-1989.pdf`, the 332-page consolidated CMVR text → now `CONSOLIDATED_RULES` (Acts and consolidated texts no longer take an embedded notification's ID). "SO-1668(E)-1989" → **SO-1668(E)-2005**: unreadable heading date, file no. RT-11042/20/2005 (a notification cannot predate its file), confirmed by the listing date. Same rule fixed **GSR-212(E)-2015** (its own short title "Fourth Amendment Rules, 2015"). |
| dates in the future | 5 | **0** | AIS cover dates must not be later than today (later dates on a cover are implementation dates); generic document dates likewise; any remaining future date raises `doc_date_in_future`. |
| `placeholder_listing_date` | 47 | 25 | resolved where the document has its own content date (22); the 25 open ones are files without a readable content date (mostly yearbooks). |

Still open and expected: `no_vehicle_category` 380 (fees/licence/permit notifications and AIS scopes without a
category word — Qwen's implicit scope), `off_topic` 200, `identity_not_found` 116 (scans without a readable heading
→ Qwen vision OCR), `unresolved_reference` 113 (drafts not collected), `low_ocr_confidence` 22, `old_date_mismatch` 9
(an intermediate S.O. 1365(E) amendment is missing from the corpus), `duplicate_identity_diff_header` 6,
`draft_final_date_mismatch` 1.

**Idempotency re-checked:** after these changes a full re-run of all AIS and notification files writes zero rows
(PostgreSQL write counters: 0 inserts / 0 updates / 0 deletes on document, document_file, doc_relation, chunk,
mandate, quality_flag). Flags settled by evidence are not raised again (33 re-raised copies from an intermediate run
are marked "duplicate of flag N", nothing deleted).
