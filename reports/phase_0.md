# Phase 0 — Project setup (+ all DB-independent code)

## Built
- `git init`, `.gitignore` (.env, .venv, data/, discovery/out/, caches), `pyproject.toml` (all listed deps + jsonschema;
  dev: pytest, ruff), `docker-compose.yml` (`db` = pgvector/pgvector:pg16, port 5432, regtrack/regtrack/regtrack,
  named volume, `./db/migrations` and `./db/seeds` mounted read-only).
- `.env.example` exactly as in CLAUDE.md; `.env` created with the LLM URL given in the prompt.
- `regtrack/config.py`, `db.py`, `llm.py` (ChatOpenAI `with_structured_output(..., method="json_schema")`, embeddings,
  reachability check with cache; `LLMUnavailable` lets every stage leave work in place), `storage.py` (write-once).
- `python -m regtrack.cli check`.

Because Docker was not available, everything that does not need PostgreSQL was written and tested in this phase as
well (models, text/OCR, classify/identity, split, extract, mandates parser, link/chunk/runner, crawlers, API, report,
tests). See "Offline measurements" below — the DB phases will re-measure these from the database.

## `regtrack.cli check` output
```
[FAIL] DB reachable               connection timeout expired
[FAIL] pgvector installed         skipped (no DB)
[FAIL] LLM reachable              https://<your-ngrok-id>.ngrok-free.app/v1 -> LLM_BASE_URL not configured
[FAIL] structured output          skipped (LLM unreachable)
[FAIL] embedding                  skipped (LLM unreachable)
STORAGE_DIR=D:\regulatory_intelligence\data\raw  SEED_CORPUS_DIR=D:\Regulatory_Documents (exists=True)
```
- **DB:** Docker Desktop's processes run but its Linux engine never started (`//./pipe/dockerDesktopLinuxEngine` missing).
  Drive **C: has ~40 MB free** (D: 295 GB) — Docker's WSL disk and the Windows page file are on C:. pip also failed
  with "No space left on device" until TMP/PIP_CACHE_DIR were pointed at D:, and two `MemoryError`s came from the
  page file not being able to grow.
- **LLM:** the URL in the prompt is the literal placeholder `https://<your-ngrok-id>.ngrok-free.app/v1`; the older
  ngrok URL in `test_local_llm.py` returns ngrok's offline page. EMBED_DIM cannot be verified yet, so
  `vector(768)` in `0001_init.sql` is unchanged.

## Offline measurements (seed corpus, `scripts/prepare_corpus.py` + `scripts/profile_offline.py`)
| Measure | Expected | Measured offline |
|---|---|---|
| Files / unique by SHA-256 | 2,274 / 2,016 | 2,274 / **2,018** (root README, `_logs`, `_review*` excluded) |
| Scans (< 100 chars/page) | 251 / 1,742 | 248 files / 1,724 pages (unique files) |
| AIS files with embedded amendments | ≈ 210 | 187 unique files (the discovery regex finds 178 on the same files; the 210 counted byte-copies in 06+07) |
| AIS files with corrigenda | ≈ 15 | 14 |
| Notifications with Kruti Dev | ≈ 300 | 232 unique notification files (any Kruti fingerprint, as in discovery/analyze.py; ≈300 incl. copies) |
| Finals citing their draft | 225 (121 / 104) | 186 distinct finals (83 drafts in corpus / 103 missing) |
| MoRTH title ≠ content ID | 6 | **6** MoRTH (904→903, 1167→1067, 3504→3604, 1432→1433, 454→453, 1162→S.O. 6052) + 2 India Code |
| Non-automotive files in folder 02 | ≈ 92 | 134 OFF_TOPIC = 46 non-automotive (GST, pollution, chemicals …) + 88 state-government documents |

Live sources checked (read-only, polite): MoRTH JSON API returns 901 rows (615 kept: road transport only);
ARAI page renders with installed Chrome via Playwright (36 pages × 10 rows, public storage links, token not used);
India Code moved to `indiacode.gov.in` (DSpace 7) with a public REST search (no captcha); e-Gazette "Search by
Ministry" works without captcha (Ministry of Road Transport and Highways, month/year grid with gazette IDs).

## Open issues
1. Free several GB on C: and restart Docker Desktop, then `docker compose up -d db`.
2. Put the real ngrok URL in `.env` (`LLM_BASE_URL`) and the embedding model name (`EMBED_MODEL`).
3. OCR: Tesseract is not installed; Qwen vision untestable while offline. Windows' built-in OCR engine
   (Windows.Media.Ocr, en-US, via the `winrt-*` pip packages — no system software installed) works at ~1.1 s/page
   and is used as the fallback engine.
