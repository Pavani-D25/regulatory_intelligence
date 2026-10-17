# RegTrack India

Automatic collection of Indian vehicle regulations: ARAI AIS standards, MoRTH Gazette notifications/orders/
guidelines, e-Gazette and India Code CMVR amendments. Originals are kept write-once, structured data lives in
PostgreSQL 16 (typed columns + JSONB), clause-level text in pgvector. Refreshes every 6 hours.

Design: `docs/DB_DESIGN.md` (authoritative) and `docs/ETL_SPEC.md`. Start with `reports/BUILD_SUMMARY.md` (what happened, decisions, what is pending), then `reports/VALIDATION_REPORT.md` and the phase reports in `reports/`.

## Quick start (new collaborators start here)

You need **Python 3.11+**, **Node.js 18+**, and the database: **PostgreSQL 16 + pgvector**, either installed on the
machine (see [Database without Docker](#database-without-docker)) or through **Docker Desktop**. Then one command
sets everything up and starts it:

| Windows | macOS / Linux / Git Bash |
|---|---|
| double-click **`start.bat`** (or `.\start.ps1` in PowerShell) | `./start.sh` |

The first run takes a few minutes. The script:

1. checks the tools; starts the local database (`PG_BIN` set in `.env`) or Docker;
2. creates `.env` from `.env.example`;
3. creates `.venv` and installs the Python packages;
4. starts the database and applies the migrations;
5. asks where the data should come from, if the database is empty: a **snapshot from a teammate** (about a minute), the **seed corpus** folder (about 45 minutes), or a **live download** from the four sources (about an hour);
6. installs the portal packages;
7. starts the **API**, the **6-hour auto-sync** and the **portal**, then opens http://localhost:5173.

| Command | What it does |
|---|---|
| `start.bat` · `./start.sh` | set up (first time) and start everything |
| `.\start.ps1 -Snapshot regtrack_2026-10-08.dump` · `./start.sh --snapshot …` | load a teammate's database snapshot, then start |
| `.\start.ps1 -Files regtrack_files_….zip` · `./start.sh --files …` | also add the original PDFs ("Open original PDF") |
| `.\start.ps1 -Stop` · `./start.sh --stop` | stop the API, auto-sync and portal (the database keeps running) |
| `.\start.ps1 -NoSchedule` · `./start.sh --no-schedule` | start without the auto-sync |

On Windows each service runs in its own minimized window titled "RegTrack - …". On macOS/Linux they run in the
background and log to `data/logs/`. Running the script again is safe: it skips what is already done.

AI features (written answers, summaries, AI impact review, semantic search) stay off until `LLM_BASE_URL` and
`EMBED_MODEL` in `.env` point at LM Studio (see "When the LM Studio URL arrives").

### Sharing data with a teammate

Rebuilding the database takes up to an hour, and the seed corpus is not in git. Share a snapshot instead:

```powershell
.venv\Scripts\python -m regtrack.cli snapshot-export               # data\snapshots\regtrack_<date>.dump (~22 MB)
.venv\Scripts\python -m regtrack.cli snapshot-export --with-files  # + regtrack_files_<date>.zip (originals + page text, ~3 GB)
```

Send the `.dump` (and, if they need to open the original PDFs, the `.zip`) through a shared drive. They run
`start.bat` and choose option 1, or `.\start.ps1 -Snapshot <file>`. Loading a snapshot replaces their local
database. Files from the zip are only added, never overwritten. Stored file paths from another machine are found
again by their sha256 name, so the snapshot works in any folder.

## Manual setup (Windows, PowerShell)

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env          # then set LLM_BASE_URL (ngrok URL of LM Studio) and EMBED_MODEL
docker compose up -d db         # pgvector/pgvector:pg16 on localhost:5432 (or: regtrack.cli db start, see below)
.venv\Scripts\python -m regtrack.cli check      # DB, pgvector, LLM, structured output, embedding dim
.venv\Scripts\python -m regtrack.cli migrate    # db/migrations + db/seeds (idempotent)
```

Low disk space on C: stops Docker Desktop (its WSL disk lives on C:) and pip (temp files). If `pip` fails with
"No space left on device", set `TMP`/`TEMP`/`PIP_CACHE_DIR` to a folder on D: for the install. With C: nearly full,
use the database without Docker (below), which keeps everything on D:.

## Database without Docker

PostgreSQL 16 and pgvector from conda-forge run directly on Windows; nothing is compiled and nothing goes on C:.
This is how the main development laptop runs (PostgreSQL 16.15, pgvector 0.8.6, same versions as the Docker image).

```powershell
# 1. Miniforge (conda-forge installer) to D:, no PATH changes
#    https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Windows-x86_64.exe
D:\installers\Miniforge3-Windows-x86_64.exe /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /NoRegistry=1 /NoShortcuts=1 /S /D=D:\miniforge3

# 2. PostgreSQL 16 + pgvector in their own folder
$env:CONDA_PKGS_DIRS = "D:\miniforge3\pkgs"
D:\miniforge3\Scripts\conda.exe create -y -p D:\pgsql -c conda-forge --override-channels "postgresql=16.15" "pgvector=0.8.6"

# 3. the data folder (user regtrack, password regtrack, as in DATABASE_URL); this build has no ICU, so en-US + UTF-8
Set-Content D:\installers\pgpw.txt "regtrack" -NoNewline
D:\pgsql\Library\bin\initdb.exe -D D:\regulatory_intelligence\data\pg -U regtrack --pwfile=D:\installers\pgpw.txt -E UTF8 --auth=scram-sha-256 --locale=en-US
Remove-Item D:\installers\pgpw.txt
```

Then add to `.env`:

```
PG_BIN=D:\pgsql\Library\bin
PG_DATA=D:\regulatory_intelligence\data\pg
```

and start it:

```powershell
.venv\Scripts\python -m regtrack.cli db start       # also: db stop, db status; start.bat does this for you
D:\pgsql\Library\bin\createdb.exe -h localhost -U regtrack regtrack     # first time only (password: regtrack)
.venv\Scripts\python -m regtrack.cli migrate        # or load a snapshot: start.ps1 -Snapshot <file.dump>
```

The server log is `data\pglog\postgres.log`. With `PG_BIN` set, `start.bat` / `start.sh` start this server instead of
Docker, and `snapshot-export` / `snapshot-import` use the local `pg_dump` / `pg_restore`. The server does not start with
Windows on its own: run `start.bat` (or `regtrack.cli db start`), or register it once as a Windows service from an
administrator PowerShell:

```powershell
D:\pgsql\Library\bin\pg_ctl.exe register -N RegTrackPostgres -D D:\regulatory_intelligence\data\pg -S auto
Start-Service RegTrackPostgres
```

Do not run the Docker database at the same time: both use port 5432.

## Running

```powershell
python -m regtrack.cli import-seed           # Phase 2: D:\Regulatory_Documents -> storage + DB (read-only, idempotent)
python -m regtrack.cli run                   # all stages for pending files (resumable from file_object.stage)
python -m regtrack.cli run --stage text      # one stage: text | classify | extract | link | chunk | embed
python -m regtrack.cli crawl MORTH_API       # one live crawl + pipeline (MORTH_API ARAI_AIS EGAZETTE INDIACODE)
python -m regtrack.cli schedule              # APScheduler: every 6 h per source + hourly pipeline catch-up
python -m regtrack.cli api                   # read-only API on http://127.0.0.1:8000/docs
python -m regtrack.cli report                # reports/VALIDATION_REPORT.md
python -m regtrack.cli llm-smoke             # test LM Studio on 10 documents (Qwen extraction + embeddings); --dry-run writes nothing
python -m regtrack.cli resolve-flags         # resolve quality flags whose evidence settles them (also runs after every pipeline run)
python -m regtrack.cli storage-upload        # one-time copy of the originals to MinIO/S3 (see below)
python -m regtrack.cli snapshot-export       # database dump to share (--with-files adds the originals zip)
python -m regtrack.cli snapshot-import FILE --yes   # load a teammate's .dump (replaces the database) or files .zip
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

## When the LM Studio URL arrives

```powershell
# .env: LLM_BASE_URL=https://<ngrok-id>.ngrok-free.app/v1   EMBED_MODEL=<embedding model name in LM Studio>
.venv\Scripts\python -m regtrack.cli llm-smoke --dry-run   # reachability, structured output, 10 documents, embedding size
.venv\Scripts\python -m regtrack.cli llm-smoke             # same, and writes the 10 results
.venv\Scripts\python -m regtrack.cli run                   # everything pending: Qwen pass, embeddings, event summaries
.venv\Scripts\python -m regtrack.cli report                # agreement rate and fill rates
```

`llm-smoke` stops before writing anything if the embedding size differs from `EMBED_DIM` / `vector(N)` and prints
the migration to add. Exit code 2 means LM Studio was not reachable.

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

The dashboard follows the approved design (*Regulatory Intelligence Portal v2*): dark sidebar, KPI cards, cards and
drawer. Scope is India only, vehicle categories L1 / L2 / M1 / N1 (plus rules for all vehicles). In the design,
"Region" is the vehicle category, "Authority" is the issuer and "Domain" is the topic.

| View | What it shows (live data) |
|---|---|
| **Dashboard** (`/`) | KPIs, 12-month publication trend, severity donut, regulations per category, top topics, latest changes, upcoming / recent implementation dates |
| **Regulations** | register with search + category / impact / status filters, CSV export, composition by authority; click a row → detail drawer |
| **Change Monitor** | change events from the crawls (timeline), changes by type, review SLA; *Mark Visible as Reviewed* is saved |
| **Compliance Matrix** | obligations in force (CMVR rule + standard + categories), editable owner / evidence / status / due date, readiness |
| **Impact View** | category × topic heatmap (score 1–5), click a cell for its regulations, most-referenced standards |
| **Ask Regulatory AI** | answers with clause citations; until LM Studio is connected it returns the best-matching clauses (full-text search) |
| **Reports** | Executive summary, Compliance gap, Change impact — downloadable HTML or CSV, logged under Recent Reports |
| **Alerts** | alert rules (on/off, new, delete) evaluated against changes and dates; notifications are shown in the portal (no email yet) |
| **Admin** | sources and their last runs, ingestion jobs, monitoring settings, *Run Source Sync* (one crawl + pipeline in the background) |
| Tools: **Vehicle Check**, **Versions**, **Document** | the earlier pages: regulations in force for a vehicle + share pack, family timelines, full document record |

**Detail drawer:** ID, authority, category, effective date, impact, status, summary, detected change, recommended
follow-up; review status and owner can be changed there and are saved.

**Impact and status are rule-based** until the Qwen pass runs (marked "rule-based"):
- **High** = technical, and either has an obligation still to come, a revision needing re-approval, or was published in the last 12 months.
- **Medium** = other technical documents. **Low** = administrative (registration, licences, fees).
- **Status:**
  - Under Review = an unreviewed change in the last 30 days, or a draft.
  - Action Required = High with an obligation still to come.
  - Impact Analysis = other High.
  - Tracked = the rest.
  - A status set by the team always wins.

**No static data.** Every number, list and label comes from the database:
- category and topic names come from `vehicle_category` and `domain`;
- suggested AI questions come from the most-regulated topics and the latest high-impact items;
- knowledge sources, sync sources and the workflow counts are live.

**Keep the scheduler running.** The portal shows real sync health: the sidebar and Admin say *Auto-sync running / not running /
paused*. The scheduler writes a heartbeat every 5 minutes. A source is marked *overdue* when its 6-hour run is late.
For data that refreshes itself, keep the scheduler running next to the API:

```powershell
.venv\Scripts\python -m regtrack.cli schedule     # crawls every 6 h + pipeline; heartbeat every 5 min
```

The Admin switch *Automatic source sync* pauses and resumes the scheduled crawls. Manual *Run Source Sync* always
works. A PostgreSQL advisory lock stops a manual sync and the scheduler from running the pipeline at the same time.

The team's inputs (reviews, compliance matrix, alert rules, settings, report log) live in the tables of
`db/migrations/0002_portal_workflow.sql`. Pipeline data is never edited from the portal; the one exception is marking
change events as reviewed. Values the Qwen pass has not filled yet are marked "✦ AI fields pending".

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
| `/portal/*` | portal views: `summary`, `regulations` (+ `/{id}/detail`, `/{id}/review`), `changes` (+ `review`), `compliance`, `impact` (+ `cell`), `ask`, `reports/{kind}?fmt=html\|csv`, `alerts`, `admin`, `settings`, `admin/sync` |

## Rules this code keeps

`D:\Regulatory_Documents` is only read. No portal logins, no captchas, no tokens taken from web pages (ARAI's
embedded bearer token is not used). Crawling: 1–2 s between requests, exponential backoff on 429/5xx,
User-Agent `RegTrackIndia/0.1 (research)`.
