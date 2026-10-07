# PROMPTS.md — paste these into Claude Code, one phase at a time

Open `D:\regulatory_intelligence` in VS Code and start Claude Code in the terminal (`claude`). Paste one phase. Let it finish and show you its report, then paste the next phase.

Each prompt is self-contained. Claude Code reads `CLAUDE.md` automatically.

---

## Phase 0 — Project setup

```
Read CLAUDE.md, docs/DB_DESIGN.md and docs/ETL_SPEC.md fully before writing code.
Phase 0: set up the project.
- git init, .gitignore (.env, .venv, data/, discovery/out/, __pycache__).
- pyproject.toml with: psycopg[binary], sqlalchemy, pydantic>=2, python-dotenv, pymupdf, httpx, tenacity,
  langchain-openai, playwright, fastapi, uvicorn, apscheduler, pytest, ruff.
- docker-compose.yml: service "db" from pgvector/pgvector:pg16, port 5432, user/db/password regtrack,
  named volume, and mount ./db/migrations + ./db/seeds so they can be applied.
- .env.example exactly as in CLAUDE.md; copy to .env and ask me for LLM_BASE_URL.
- regtrack/config.py (loads .env), regtrack/db.py (connection), regtrack/llm.py
  (ChatOpenAI with_structured_output helper + embeddings helper + a reachability check).
- scripts: `python -m regtrack.cli check` that prints: DB reachable, pgvector installed, LLM reachable,
  one structured-output call works (tiny Pydantic model), embedding call works and its dimension.
Stop and show me the check output. If EMBED_DIM differs from the real embedding dimension, tell me before Phase 1.
```

## Phase 1 — Database

```
Phase 1: database.
- Set vector(N) in db/migrations/0001_init.sql to the embedding dimension found in Phase 0.
- A tiny migration runner (regtrack/migrate.py) that applies db/migrations/*.sql in order and records them
  in a schema_migrations table; then applies db/seeds/*.sql. Idempotent.
- regtrack/models/: Python enums for doc_class, relation_type, nature, status, role, stage, domain;
  Pydantic models for document.data per doc_class (shapes in DB_DESIGN §5 and the doc's section 6);
  export JSON Schema files to regtrack/models/schemas/*.json from those models.
- Tests: migrations apply twice without error; the partial unique index rejects a second is_current row
  in the same family; the example queries in DB_DESIGN §6 run on a small inserted sample.
Write reports/phase_1.md.
```

## Phase 2 — Import the seed corpus (files only)

```
Phase 2: import SEED_CORPUS_DIR (read-only) into storage and the DB, without parsing content yet.
- regtrack/sources/seed_corpus.py: walk all folders except _logs and any _review* folder.
  For each file: sha256, copy to STORAGE_DIR (write-once), insert file_object (stage='downloaded')
  and a file_sighting for source LOCAL_SEED with listing_title = file name, listing_raw = folder + path.
- Also read the CSVs in _logs (morth_download_log.csv, ais_download_log.csv, cmvr_indiacode_log.csv,
  indiacode_multi_log.csv, arai_static_log.csv) and attach each row to its file's sighting as listing_raw,
  with source = MORTH_API / ARAI_AIS / INDIACODE / ARAI_TAP and listing_title/listing_date from the CSV.
- Re-running must add nothing. Test that.
Check against CLAUDE.md: 2,274 files -> 2,016 file_object rows. Write reports/phase_2.md.
```

## Phase 3 — Text, language and OCR

```
Phase 3: text stage (pipeline/text.py), stage 'downloaded' -> 'text'.
- PyMuPDF per page; DOCX via document.xml; HTM/CSV as text. Save page texts to data/text/<sha>.jsonl.
- Fill file_object: page_count, text_layer, scanned_pages (pages < 100 chars), language_mix
  (Devanagari share + Kruti Dev legacy-font detection; see discovery/analyze.py hindi_legacy pattern),
  pdf_meta.
- Detect English page range for bilingual notifications (store per file for later use).
- OCR for scanned pages: first test whether the LM Studio Qwen model accepts images. If yes, use it
  (one page image per call, plain text out). If not, use Tesseract (tell me to install it; do not install
  system software yourself). Store ocr_engine and a confidence.
- If the LLM is offline, leave scan files at stage 'text' with scanned_pages set and continue.
Check: 251 scanned files / 1,742 pages; ~300 Kruti Dev notifications. Write reports/phase_3.md.
```

## Phase 4 — Relevance, classification and identity

```
Phase 4: classify + identify (pipeline/classify.py, pipeline/identity.py), stage 'text' -> 'classified'.
- Start from discovery/classify.py and discovery/analyze.py rules; extend them to the full doc_class list
  in DB_DESIGN §3. Use Qwen only for files still OTHER after the rules.
- Relevance: automotive keyword density + issuer + CMVR/MV Act mention; non-automotive -> OFF_TOPIC.
- Identity from the English header text, NOT the listing title:
  G.S.R./S.O. number + date + year; AIS code / Part / Rev from the cover; TAP doc no + issue; form no.
- Create document rows (one per identity; many files can map to one document via document_file).
  Where the listing title's ID differs from the content ID, write quality_flag title_file_mismatch.
- Fill doc_date + precision, status (draft/final), issuer, gazette part/section, file_no into data.
Check: the 6 title mismatches are flagged; ~92 OFF_TOPIC in folder 02; GSR numbers reused across years
produce different canonical_ids. Write reports/phase_4.md.
```

## Phase 5 — Split consolidated files

```
Phase 5: split (pipeline/split.py).
- AIS consolidated files: detect amendment headers (3 formats: "AMENDMENT NO. 2  10 April 2015 TO AIS 021/2004",
  "Amendment No. 4 (MM/YYYY) To AIS-xxx", no date), corrigendum headers, and the base standard start (cover).
  Each segment -> its own document (AIS_AMENDMENT / AIS_CORRIGENDUM / AIS_STANDARD) + document_file
  with page_from/page_to and role='consolidated_segment'.
- TAP: the 102 files of folder 11 -> one TAP_DOCUMENT with document_file.part_label per part/chapter.
- AIS-007 Rev.5 DOCX tables -> AIS_FORM_TABLE documents linked later with annex_of.
- MoRTH copies of AIS (folder 06) that differ from ARAI bytes: match to the right version by code,
  revision and amendment set; role='historical_copy' or a separate older version document.
- Pick is_best_copy per document (text layer, newest, ARAI over MoRTH).
Check: ~210 AIS files split; amendment numbers per family have no gaps (else quality_flag amendment_gap).
Write reports/phase_5.md.
```

## Phase 6 — Qwen extraction

```
Phase 6: extract (pipeline/extract.py), stage 'classified' -> 'parsed'.
- For each document, send only its English pages to Qwen with the doc_class Pydantic model
  (structured output). Fill document.data, subject, official_title, vehicle_categories (via the
  vehicle_category synonym table first, Qwen for implicit scope), usage, powertrains, domains, nature,
  in_scope, and document.extraction (model, prompt_version, confidence per field).
- Deterministic first: dates, file_no, gazette part, references (AIS/IS/UN R/GSR/SO/Rule regexes).
- Validate data against the JSON Schema; failures -> quality_flag schema_violation.
- Double-extract identity/status/date fields with a second prompt on 10% of documents and report agreement.
Start with 30 documents across classes, show me the results, then run the rest.
Write reports/phase_6.md with fill rates per column and the agreement rate.
```

## Phase 7 — Links, versions and mandates

```
Phase 7: link + version + mandates (pipeline/link.py, version.py, mandates.py), stage -> 'linked'.
- doc_relation: finalises (file_no match or "draft ... vide G.S.R. X dated Y"), amends/corrects/revises
  for AIS (revises sets requires_reapproval=true), extends_date, exempts, inserts_row/substitutes_row/omits_row
  for S.O. 1365(E) and CMVR Rule 124(4) tables, annex_of, part_of, references. Unknown targets -> to_ref.
- Versions: family_key, version_seq, exactly one is_current per family.
- Mandates: seed the S.O. 1365(E) master table (2004 base, OCR/vision), then replay every amending
  notification in date order; each provision -> mandate rows (categories, conditions JSON,
  model_scope, the three dates, legal_basis, mandate_key). Changes close old rows (valid_to, superseded_by).
  Draft mandates is_draft=true; replaced when the final arrives.
Check: 225 finals link to drafts (121 resolved, 104 to_ref); wheel-rim chain S.O. 1406 -> 359 -> 3896 -> 3800
gives 4 versions of one mandate_key. Write reports/phase_7.md.
```

## Phase 8 — Chunks and embeddings

```
Phase 8: chunk + embed (pipeline/chunk.py), stage -> 'chunked' -> 'embedded' -> 'done'.
- Clause-level chunks using clause numbering; English only; mark boilerplate (committee lists, status charts,
  Gazette mastheads); copy filter columns from document; embed with EMBED_MODEL in batches.
- Skip OFF_TOPIC documents.
- A search function: filtered vector search (category, in_scope, is_current) as in the doc's query 9.6.
Write reports/phase_8.md with chunk counts and 5 example searches.
```

## Phase 9 — Live sources and the 6-hour schedule

```
Phase 9: live crawlers + scheduler.
- sources/morth.py: the MoRTH JSON API (ETL_SPEC §1) for gazettes-notifications, orders-and-notices,
  guidelines; paginate; new/changed files only.
- sources/arai.py: the public AIS list via Playwright page render (never the embedded token).
- sources/egazette.py and sources/indiacode.py: public search/listing pages only; stop and tell me
  if a page needs login or captcha.
- scheduler.py (APScheduler): every 6 h per source; each run = crawl_run row; pipeline runs the new files
  through all stages; change_event rows for new_document, new_amendment, draft_finalised,
  implementation_date_changed, etc. with a Qwen one-line summary.
- Also a Windows Task Scheduler option documented in README.
Check: a second run right after the first writes zero new rows. Write reports/phase_9.md.
```

## Phase 10 — Read API

```
Phase 10: read-only FastAPI (regtrack/api).
Endpoints: /vehicles/applicable?category=L2&engine_cc=110&powertrain=petrol&on=2026-01-01,
/documents?year=&category=&doc_class=&domain=&in_scope=, /documents/{canonical_id},
/families/{family_key}/versions, /changes?since=, /search?q=&category=,
/share-pack?category=...  (zip of best-copy originals + manifest.csv).
No LLM calls at read time except embedding the search query.
Write reports/phase_10.md with example responses.
```

## Phase 11 — Validation report

```
Phase 11: final validation.
Produce reports/VALIDATION_REPORT.md: fill rate per column, Qwen agreement, open quality_flags by rule,
the CLAUDE.md regression table measured vs expected, and the top 20 documents that need checking.
Thresholds: required columns >= 95% filled, >= 90% agreement on identity/status/date fields,
no unexplained validator failures.
```
