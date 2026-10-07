# Phase 8 — Chunks and embeddings (stage `linked` → `chunked` → `embedded` → `done`)

## Built
`pipeline/chunk.py`: clause-level chunks from English pages of each document's page range (best copy, plus every
segment of consolidated AIS files): splits at clause numbers (`1`, `6.12`, `6.12.3`), `ANNEX …` headings and, for
notifications, numbered paragraphs; long clauses are cut at paragraph boundaries (≤ 1,800 chars). Boilerplate
(committee composition, status charts, Gazette mastheads, printer/digital-signature lines) is kept but flagged
`is_boilerplate`. Filter columns (doc_class, family_key, categories, domains, year, status, is_current, in_scope)
are copied from the document and kept in sync (`sync_chunk_filters`). OFF_TOPIC documents get no chunks; Hindi is
never chunked. `embed_pending()` embeds in batches of 64 with EMBED_MODEL; when the endpoint is down files stay at
`chunked` and are picked up by the next run.
`pipeline/search.py`: filtered vector search (category ∪ ALL, in_scope, is_current, doc_class, non-boilerplate);
falls back to text search over the same filters while embeddings are unavailable.

## Numbers
| | |
|---|---|
| Chunks | 136,220 from 1,726 documents (avg 438 chars), 2,411 boilerplate |
| Largest classes | AIS_STANDARD 47,604 · AIS_DRAFT 32,190 · AIS_AMENDMENT 20,346 · REPORT 7,861 · NOTIFICATION_FINAL 5,827 · TAP 5,107 |
| Embedded | **0** — LLM/embedding endpoint not configured |
| Files | 503 `done` (no chunks: OFF_TOPIC, forms, empty), 1,515 waiting at `chunked` for embeddings |

## 5 example searches (text-fallback mode; rerun after embeddings for vector ranking)
```
anti-lock braking system  [L2]   AIS-004(Part3)(Rev.1) §44 "BRAKES … Anti-lock …"; AIS-007(Rev.5)/Amd.4 §12.1 service brakes
traction battery safety   [L2]   AIS-048 "Battery Operated Vehicles - Safety Requirements of Traction Batteries";
                                 S.O. 1365 table row "Traction batteries used in battery operated vehicles AIS-048/2009"
seat belt reminder        [M1]   AIS-197 §3 "Seat Belt Reminder Meeting …"; AIS-197 drafts §3.4 "Seat Belt Reminders (SBR)"
speed limiting device     [N1]   AIS-194 §31 "Speed Governor - Speed Limiting Function as per AIS-018"
vehicle location tracking panic button   AIS-204 §3.10 "Requirements for panic button / Vehicle Tracking Devices (VTD)"
```

## Open issues
- Set `LLM_BASE_URL` + `EMBED_MODEL`, check the dimension (`regtrack.cli check`), add migration 0002 if ≠ 768,
  then `python -m regtrack.cli run --stage embed` (≈ 136 k chunks; boilerplate is embedded last).
- Two notification identities found during the search check have doubtful years (S.O. 701 inside a compilation of
  1989 orders; S.O. 1668(E) whose OCR'd masthead is garbled → "1989"). Both have no doc_date and are listed for checking.
