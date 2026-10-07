# RegTrack India — Validation report

Generated 2026-10-08 04:18.

| files | docs | rels | mandates | chunks | emb | events |
|---|---|---|---|---|---|---|
| 2142 | 2048 | 5263 | 178 | 147272 | 0 | 123 |


## Files by stage

| stage | files |
|---|---|
| chunked | 1619 |
| done | 523 |


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
| canonical_id | 1848 | 1848 | 100.0% |
| doc_class | 1848 | 1848 | 100.0% |
| series | 870 | 1848 | 47.1% |
| number | 1391 | 1848 | 75.3% |
| year | 1181 | 1848 | 63.9% |
| part | 185 | 1848 | 10.0% |
| revision | 171 | 1848 | 9.3% |
| amendment_no | 328 | 1848 | 17.7% |
| family_key | 822 | 1848 | 44.5% |
| version_seq | 816 | 1848 | 44.2% |
| official_title | 509 | 1848 | 27.5% |
| subject | 1666 | 1848 | 90.2% |
| issuer | 1813 | 1848 | 98.1% |
| status | 1848 | 1848 | 100.0% |
| doc_date | 1323 | 1848 | 71.6% |
| doc_date_precision | 1348 | 1848 | 72.9% |
| nature | 1657 | 1848 | 89.7% |
| vehicle_categories | 1038 | 1848 | 56.2% |
| usage | 247 | 1848 | 13.4% |
| powertrains | 328 | 1848 | 17.7% |
| domains | 1353 | 1848 | 73.2% |
| in_scope | 1848 | 1848 | 100.0% |
| relevance | 1848 | 1848 | 100.0% |
| data | 1806 | 1848 | 97.7% |
| extraction | 1848 | 1848 | 100.0% |


## Required columns (threshold ≥ 95 %)

| population | column | filled | total | rate | ≥95% |
|---|---|---|---|---|---|
| all | canonical_id | 1848 | 1848 | 100.0% | PASS |
| all | doc_class | 1848 | 1848 | 100.0% | PASS |
| all | status | 1848 | 1848 | 100.0% | PASS |
| all | issuer | 1813 | 1848 | 98.1% | PASS |
| all | relevance | 1848 | 1848 | 100.0% | PASS |
| all | data | 1806 | 1848 | 97.7% | PASS |
| notification | doc_date | 504 | 529 | 95.3% | PASS |
| notification | year | 529 | 529 | 100.0% | PASS |
| notification | series | 529 | 529 | 100.0% | PASS |
| notification | number | 529 | 529 | 100.0% | PASS |
| notification | nature | 415 | 529 | 78.4% | FAIL |
| notification | subject | 421 | 529 | 79.6% | FAIL |
| ais | doc_date | 528 | 629 | 83.9% | FAIL |
| ais | family_key | 629 | 629 | 100.0% | PASS |
| ais | version_seq | 629 | 629 | 100.0% | PASS |
| ais | subject | 629 | 629 | 100.0% | PASS |
| ais_standard | official_title | 291 | 291 | 100.0% | PASS |
| ais_standard | doc_date | 261 | 291 | 89.7% | FAIL |


## Qwen double-extraction agreement (identity / status / date, threshold ≥ 90 %)

| field | agree | checked | rate |
|---|---|---|---|
| number | 0 | 0 | n/a |
| date | 0 | 0 | n/a |
| status | 0 | 0 | n/a |


## Open quality flags by rule

| rule | entity | open |
|---|---|---|
| no_vehicle_category | document | 377 |
| off_topic | document | 200 |
| identity_not_found | document | 116 |
| unresolved_reference | document | 113 |
| placeholder_listing_date | file_object | 45 |
| low_ocr_confidence | file_object | 22 |
| amendment_gap | document | 21 |
| title_file_mismatch | file_object | 16 |
| old_date_mismatch | mandate | 9 |
| duplicate_identity_diff_header | document | 5 |
| draft_final_date_mismatch | document | 1 |


## Top 20 documents that need checking

| canonical_id | class | flags | rules | title |
|---|---|---|---|---|
| GSR-291(E)-2014 | NOTIFICATION_FINAL | 3 | duplicate_identity_diff_header, unresolved_reference | Amends CMVR Rule 2, CMVR Rule 126, CMVR Rule 35(1), CMVR Rule 39, CMVR Rule 101, |
| AIS-039(Rev.1) | AIS_STANDARD | 2 | amendment_gap, no_vehicle_category | AIS-039(Rev.1):2015 |
| NOTIF-33bd3cc437e950bc | NOTIFICATION_FINAL | 2 | identity_not_found, unresolved_reference | Central Motor Vehicles (Third Amendment) Rules, 2002 |
| NOTIF-4689ed122764b5d0 | NOTIFICATION_FINAL | 2 | identity_not_found, unresolved_reference | Central Motor Vehicles (First Amendment) Rules, 2004 |
| AIS-213 | AIS_STANDARD | 1 | amendment_gap | 115 km/h ≤ Vmax < 130 |
| AIS-052 | AIS_STANDARD | 1 | amendment_gap | Requirements for Approval of Vehicles of Categories M2, M3, N and T with Regard  |
| GSR-850(E)-2025 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Fifth Amendment) Rules, 2025 |
| GSR-514(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Tenth Amendment) Rules, 2024 |
| GSR-195(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Seventh Amendment) Rules, 2024 |
| GSR-27(E)-2024 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (First Amendment) Rules, 2024 |
| GSR-698(E)-2023 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Sixth Amendment) Rules, 2023 |
| GSR-226(E)-2023 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Second Amendment) Rules, 2023 |
| GSR-863(E)-2022 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Twenty-Second Amendment) Rules, 2022 |
| AIS-009 | AIS_STANDARD | 1 | amendment_gap | Automotive Vehicles - Installation Requirements of Lighting and Light-Signalling |
| GSR-394(E)-2022 | NOTIFICATION_FINAL | 1 | unresolved_reference |  |
| GSR-596(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Eighteenth Amendment) Rules, 2021 |
| GSR-410(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Thirteenth Amendment) Rules, 2021 |
| GSR-394(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Eleventh Amendment) Rules, 2021 |
| GSR-240(E)-2021 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Sixth Amendment) Rules, 2021 |
| GSR-628(E)-2020 | NOTIFICATION_FINAL | 1 | unresolved_reference | Central Motor Vehicles (Fourteenth Amendment) Rules, 2020 |


## LLM status

Documents waiting for the Qwen pass (llm_pending): 1642.
Chunks without embedding: 147272.

## Assessment against the thresholds

**Required columns ≥ 95 %: 15 of 19 pass.** The four below the line, and why:

| Column | Rate | Reason | What closes it |
|---|---|---|---|
| notification `subject` | 79.6 % | deterministic subjects exist only for short titles, "hereby specifies/exempts …" clauses or amended rules | Qwen `subject` (110 notifications are `llm_pending`) |
| notification `nature` | 78.4 % | keyword rules find no technical/administrative/procedural cue in older or OCR'd notices | Qwen pass |
| AIS `doc_date` | 83.9 % | 101 amendments use the header format with **no date** (`AMENDMENT NO. 1 TO AIS-037`) — the date is genuinely absent from the document | status-chart dates via Qwen; otherwise stays empty (correct) |
| AIS_STANDARD `doc_date` | 89.7 % | 30 covers have no month/year (scans, consolidated reprints) | Qwen on cover pages |

**Qwen agreement ≥ 90 %: not measurable.** LM Studio was never reachable during the build (`LLM_BASE_URL` is the
placeholder `https://<your-ngrok-id>.ngrok-free.app/v1`). The 10 % double-extraction sample is wired into
`extract.py` and runs automatically on the first pipeline run after the URL is set
(`python -m regtrack.cli run`), followed by `python -m regtrack.cli report`.

**Validator failures: none unexplained.** No `schema_violation` flags. Every open flag rule is explained:
- `no_vehicle_category` (377): fees/licence/permit notifications and AIS files whose Scope clause did not parse; DB_DESIGN expects ≈ 385 notifications with no category word.
- `off_topic` (200): 47 non-automotive + 91 state-level documents in folder 02, plus e-waste rules, highway and other non-vehicle files.
- `identity_not_found` (116): mostly scans whose Windows-OCR text has no readable G.S.R./S.O. heading → Qwen vision OCR.
- `unresolved_reference` (113): drafts cited by finals but not collected yet (DB_DESIGN: 104 missing).
- `placeholder_listing_date` (45): MoRTH listings dated 1 January (31 are yearbooks/reports).
- `low_ocr_confidence` (22), `amendment_gap` (21, checked: amendments not present as separate headers), `old_date_mismatch` (9: an intermediate S.O. 1365(E) amendment such as S.O. 2914(E)-2021 is missing from the corpus).
- `title_file_mismatch` (16): the 6 known MoRTH cases + 6 "listing says S.O., OCR'd content says G.S.R. (same number)" + S.O. 1407→1450 + 1 extra MoRTH + 2 India Code.
- `duplicate_identity_diff_header` (5), `draft_final_date_mismatch` (1).

**Regression table:** every measure is within the expected range or the difference is explained in the phase
reports — unique-file counting (2,018 vs 2,016; scans 248 vs 251; AIS amendments 181 unique files vs ≈ 210 incl.
copies; Kruti Dev 232 unique vs ≈ 300 incl. copies), the State Government split of folder 02 (47 + 91), and the
7 extra title mismatches that only became visible after OCR.

**Not done because no LLM / embedding endpoint was available:** embeddings (147,272 chunks waiting at `chunked`),
Qwen extraction of provisions, Qwen summaries for change events, Qwen vision OCR. All are queued and run without
manual work once `LLM_BASE_URL` and `EMBED_MODEL` are set.
