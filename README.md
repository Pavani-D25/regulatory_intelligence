# RegTrack India

Automatic collection of Indian vehicle regulations: ARAI AIS standards, MoRTH Gazette notifications/orders/
guidelines, e-Gazette and India Code CMVR amendments. Originals are kept write-once, structured data lives in
PostgreSQL 16 (typed columns + JSONB), clause-level text in pgvector. Refreshes every 6 hours.

Design: `docs/DB_DESIGN.md` (authoritative) and `docs/ETL_SPEC.md`. Start with `reports/BUILD_SUMMARY.md` (what happened, decisions, what is pending), then `reports/VALIDATION_REPORT.md` and the phase reports in `reports/`.

## Setup (Windows, PowerShell)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env          # then set LLM_BASE_URL (ngrok URL of LM Studio) and EMBED_MODEL
docker compose up -d db         # pgvector/pgvector:pg16 on localhost:5432
.venv\Scripts\python -m regtrack.cli check      # DB, pgvector, LLM, structured output, embedding dim
.venv\Scripts\python -m regtrack.cli migrate    # db/migrations + db/seeds (idempotent)
```

Low disk space on C: stops Docker Desktop (its WSL disk lives on C:) and pip (temp files). If `pip` fails with
"No space left on device", set `TMP`/`TEMP`/`PIP_CACHE_DIR` to a folder on D: for the install.

## Running

```powershell
python -m regtrack.cli import-seed           # Phase 2: D:\Regulatory_Documents -> storage + DB (read-only, idempotent)
python -m regtrack.cli run                   # all stages for pending files (resumable from file_object.stage)
python -m regtrack.cli run --stage text      # one stage: text | classify | extract | link | chunk | embed
python -m regtrack.cli crawl MORTH_API       # one live crawl + pipeline (MORTH_API ARAI_AIS EGAZETTE INDIACODE)
python -m regtrack.cli schedule              # APScheduler: every 6 h per source + hourly pipeline catch-up
python -m regtrack.cli api                   # read-only API on http://127.0.0.1:8000/docs
python -m regtrack.cli report                # reports/VALIDATION_REPORT.md
python scripts/prepare_corpus.py             # offline: hash + store + extract text (no DB needed)
python scripts/profile_offline.py            # offline: classification/identity profile vs regression numbers
```

`pytest` runs the unit tests; DB tests (`tests/test_db.py`) run against a throw-away `regtrack_test` database and
are skipped when PostgreSQL is not reachable.

### Windows Task Scheduler instead of `schedule`

Create one task per source (or one task calling all), every 6 hours:

```powershell
$py  = "D:\regulatory_intelligence\.venv\Scripts\python.exe"
$act = New-ScheduledTaskAction -Execute $py -Argument "-m regtrack.cli crawl" -WorkingDirectory "D:\regulatory_intelligence"
$trg = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 6)
Register-ScheduledTask -TaskName "RegTrackIndia crawl" -Action $act -Trigger $trg -Description "RegTrack India 6-hourly crawl"
```

(`crawl` with no arguments runs MORTH_API, ARAI_AIS, EGAZETTE and INDIACODE in turn, each followed by the pipeline.)

## How it works

```
sources (MoRTH JSON API, ARAI page via Playwright, e-Gazette via Playwright, India Code DSpace REST, seed corpus)
  -> file_object (sha256, write-once STORAGE_DIR/<sha[:2]>/<sha>.<ext>) + file_sighting (listing claims)
  -> text (PyMuPDF / docx XML; OCR for scans: Qwen vision if it accepts images, else Windows OCR, else Tesseract)
  -> classify + identity from content (G.S.R./S.O. number + year, AIS code/Part/Rev, TAP, form) + split AIS files
  -> extract (deterministic first; Qwen fills the doc_class Pydantic model when reachable)
  -> link (finalises, amends, extends_date, table rows, revises, annex_of, references) + versions + mandates
  -> chunk (clause level, English only, boilerplate flagged) -> embed (LM Studio embedding model)
```

* Identity never comes from listing titles; mismatches become `quality_flag(title_file_mismatch)`.
* `canonical_id` formats: `GSR-659(E)-2022`, `SO-1365(E)-2004`, `AIS-038(Rev.2)`, `AIS-038(Rev.2)/Amd.4`,
  `AIS-007(Rev.5)/Table-1B`, `TAP-115/116(Issue.4)`, `FORM-20`. Files without a parsable identity get
  `NOTIF-<sha16>` / `AIS-UNIDENTIFIED-<sha16>` / `DOC-<sha16>` and an `identity_not_found` flag.
* Mandates are never updated in place: a change closes the old row (`valid_to`, `superseded_by`) and inserts a new
  one with the same `mandate_key` (e.g. `SO-1365(E)-2004 Table Sr.8(d)`).
* No manual review: failed checks write `quality_flag`; values are kept and marked `needs_check`.
* LLM offline (laptop off / ngrok URL changed): runs never fail. Deterministic extraction is written with
  `extraction.llm_pending=true` and the Qwen pass runs on a later run; chunks wait at stage `chunked` until the
  embedding endpoint is back.

## Object storage: local (default) or MinIO / S3

Originals are write-once under the key `<sha[:2]>/<sha>.<ext>` in both backends.

- `STORAGE_BACKEND=local` (default): files in `STORAGE_DIR`; `file_object.storage_path` is the local path.
- `STORAGE_BACKEND=s3`: files in the bucket `S3_BUCKET` (MinIO or any S3-compatible store);
  `storage_path` is `s3://<bucket>/<key>`. The bucket is created with object locking and every object gets a legal
  hold, so it cannot be deleted or overwritten. Parsing and the API read through a local cache (`CACHE_DIR`,
  default `data/cache`) that is checked against the sha256 in the key.

Switching an existing installation to MinIO:

```powershell
docker compose --profile s3 up -d minio                  # console http://localhost:9001 (S3_ACCESS_KEY / S3_SECRET_KEY)
.venv\Scripts\python -m regtrack.cli storage-upload      # upload every original (re-runs upload nothing new)
.venv\Scripts\python -m regtrack.cli storage-upload --switch   # point file_object.storage_path at s3://
# then set STORAGE_BACKEND=s3 in .env; local files are kept (never deleted)
```

## Dashboard (React + Vite + Tailwind, `dashboard/`)

Two terminals (PowerShell), from the project folder:

```powershell
# 1) the read API (port 8000) - the dashboard calls it from the browser (CORS allows localhost:5173/4173)
.venv\Scripts\python -m regtrack.cli api

# 2) the dashboard (first time: npm install)
cd dashboard
npm install
npm run dev            # open http://localhost:5173
```

Production-style: `npm run build` then `npm run preview` (http://localhost:4173). The API address comes from
`VITE_API_URL` (`dashboard/.env`, default `http://127.0.0.1:8000`; see `dashboard/.env.example`).

Pages: **Vehicle check** (category L1/L2/M1/N1, engine cc, powertrain, usage, date → regulations in force and coming
later, with standard, implementation date, legal basis, source document, and a *Download share pack* button for the
selection) · **Browse** (year, category, topic, type, in-scope) · **Versions** (family timeline: base → revisions →
amendments, current marked) · **Changes** (change_event feed) · **Search** · **Document** (metadata, relations,
mandates, quality flags, open/download the original). Values the Qwen pass has not filled yet are marked
"✦ AI fields pending".

## Read API

| Endpoint | Purpose |
|---|---|
| `/vehicles/applicable?category=L2&engine_cc=110&powertrain=petrol&on=2026-01-01` | mandates + standards (current versions, amendments) |
| `/documents?year=&category=&doc_class=&domain=&in_scope=&nature=` | year / category / class views |
| `/documents/{canonical_id}` | document + files + relations + mandates + flags |
| `/families/{family_key}/versions` | version view (e.g. `AIS-038`, `SO-1365-MASTER`) |
| `/changes?since=` | change events from live crawls |
| `/search?q=&category=` | filtered vector search (text fallback when embeddings are down) |
| `/share-pack?category=L2&engine_cc=110&powertrain=petrol` | zip of best-copy originals + `manifest.csv` for a vehicle selection |
| `/files/{sha256}[?download=true]` | the original file (inline or download) |
| `/families?q=` · `/meta` | family list; filter options and headline numbers (dashboard) |

## Rules this code keeps

`D:\Regulatory_Documents` is only read. No portal logins, no captchas, no tokens taken from web pages (ARAI's
embedded bearer token is not used). Crawling: 1–2 s between requests, exponential backoff on 429/5xx,
User-Agent `RegTrackIndia/0.1 (research)`.
