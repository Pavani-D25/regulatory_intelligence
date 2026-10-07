# Phase 3 — Text, language and OCR

## Built
`regtrack/pipeline/text.py` + `stages.stage_text` (stage `downloaded` → `text`):
- PyMuPDF per page; DOCX via `word/document.xml` (tables as `cell | cell` rows); legacy DOC via UTF-16 run scan;
  HTM/CSV as text. Pages saved to `data/text/<sha[:2]>/<sha>.jsonl` (+ `.meta.json` cache, so extraction can run
  before the DB — `scripts/prepare_corpus.py`).
- `file_object`: page_count, text_layer (≥ 100 chars/page on average), scanned_pages (pages < 100 chars),
  language_mix (Latin/Devanagari share, `hi_legacy_font` = any Kruti Dev fingerprint as in discovery/analyze.py,
  page counts, `english_range` = first/last English page), pdf_meta (NUL bytes stripped).
- OCR (`regtrack/pipeline/ocr.py`): engine order Qwen vision (if the LM Studio model accepts an image — probed once
  per process) → Windows.Media.Ocr (built into Windows 11, en-US) → Tesseract (only if on PATH; not installed).
  Qwen is offline, Tesseract absent, so Windows OCR was used. One page image per call, text kept when longer than
  the text layer. `ocr_engine` and a heuristic `ocr_confidence` (share of well-formed English tokens — none of the
  engines reports a calibrated score) are stored; < 0.6 → `quality_flag low_ocr_confidence`.
- Notifications whose header page has a garbled embedded OCR layer get their first pages re-OCR'd during classify.

## Numbers
| Measure | Expected | Measured |
|---|---|---|
| Scanned files / pages | 251 / 1,742 | **248 / 1,724** (unique files; 2 more are 0-page PDFs, TAP Part-15 Ch.1 and Ch.3) |
| OCR'd files | — | 246 (windows_ocr), mean confidence 0.777, 22 below 0.6 (flagged) |
| Files with Kruti Dev fingerprints | — | 283 (notifications among them are counted in Phase 4) |
| Files with an English page range | — | 1,988 of 2,018 |
| Text stage errors | — | 0 (3 NUL-in-metadata failures fixed and re-run) |

## Open issues
- When the LLM is reachable, re-OCR the 22 low-confidence scans with Qwen vision (set `ocr_engine=NULL` on them and
  re-run `run --stage text`) — Windows OCR is weak on old 1989–2005 typewritten gazettes.
- Hindi OCR is not attempted (English only; Hindi is never embedded).
