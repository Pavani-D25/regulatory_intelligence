# Phase 5 — Split consolidated files

## Built
`pipeline/split.py` + `stages.write_ais` (runs inside the classify stage, so every AIS file is split when it is
classified):
- Amendment headers in three formats — `AMENDMENT NO. 2  10 April 2015 TO AIS 021/2004` (full_date),
  `Amendment No. 4 (MM/YYYY) To AIS-xxx` (month_year), no date (no_date) — and corrigendum headers, found near the top
  of a page (status charts / amendment records / contents pages are ignored). The base standard is the cover segment.
- Each segment → its own document: `AIS-038(Rev.2)` (AIS_STANDARD), `AIS-038(Rev.2)/Amd.4` (AIS_AMENDMENT),
  `…/Corr.1` (AIS_CORRIGENDUM), with `document_file.page_from/page_to`, `part_label` and role
  `consolidated_segment`; issued date + precision + header format in `data`.
- TAP: every file of folder 11 → one `TAP-115/116(Issue.4)` document, `part_label` = `Part-03/Chapter-04` etc.
- AIS-007 Rev.5 DOCX tables → `AIS-007(Rev.5)/Table-<x>` (AIS_FORM_TABLE, role `annex_table`); `annex_of` is written in Phase 7.
- MoRTH copies (folder 06, no ARAI sighting): same identity → role `historical_copy`; drafts ("Finalized Draft",
  "Last date for comments") → separate `AIS_DRAFT` documents.
- `is_best_copy` per document: text layer > ARAI source > not a historical copy > newest listing > more English pages.
- Amendment numbers per base without gaps, else `quality_flag amendment_gap` (one open flag per base; earlier states
  of the family are resolved).

## Numbers
| Measure | Expected | Measured |
|---|---|---|
| AIS files split into amendment segments | ≈ 210 | 180 unique files (each byte-copy counted once) |
| AIS files with corrigenda | ≈ 15 | 14 |
| AIS document_file roles | — | consolidated_segment 475, main 243, historical_copy 188, annex_table 72 |
| Documents known only from MoRTH copies | — | 35 (older versions / drafts not on ARAI any more) |
| TAP | 1 document, 102 files | 1 document, 105 files (102 parts/chapters + amendment record + 2 overview PDFs), 104 part labels |
| AIS_FORM_TABLE | 72–73 | 66 documents from 72 DOCX files (6 files are byte-different copies of the same table) |
| Documents with exactly one best copy | all | 1,940 / 1,940 (TAP: every part file is a best copy) |
| amendment_gap | none expected | 21 open, e.g. AIS-156 (Amd 1–3 are not present as separate headers: ARAI's file holds Amd 5 and a consolidated Amd 4 reprint), AIS-052(Rev.1) 6–8, AIS-135 4–9 |

## Open issues
- Gaps are real "not separately present" cases, not split errors (checked AIS-156 by hand); they stay as flags.
- Amendment instructions (`add clause … after …`, `substitute`) are extracted by regex in Phase 6; Qwen improves them when online.
