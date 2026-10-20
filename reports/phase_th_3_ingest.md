# Phase TH-3 (ingestion only): Thailand's first real crawler

**Date:** 20 October 2026 · continues from `phase_th_2_rebuild.md`.

**Status:** done, scoped to ingestion only (deliberately, see "Open issue" below) — real documents discovered, downloaded and stored from a live Thai government site, verified idempotent.

## What was checked against the live sites before writing any code

- **Royal Gazette (`ratchakitcha.soc.go.th`, TH_GAZETTE):** `phase_th_0.md` reported no captcha. Re-checked live: it now shows a real Cloudflare "Verify you are human" checkbox (Turnstile), not an auto-passing JS challenge. Per `CLAUDE.md`'s hard rule, this was not touched or worked around. Not built this phase.
- **TISI mandatory-standards list (`www.tisi.go.th/website/standardlist/comp_thai/th`, TH_TISI_MANDATORY):** confirmed live, no captcha, plain static HTML (all 152+ rows render server-side, no pagination). `phase_th_0.md` reported the detail links (`www3.tisi.go.th/hscode/hscode_view.asp?id=<n>`) were broken (404). Re-checked live: they work and return full content — standard number, product name, effective date, scope description, HS2022 code. Built against this source instead of the DB/Portal pair `phase_th_0.md` recommended, since the simpler direct path turned out to work.

## What was built

| File | What |
|---|---|
| `regtrack/sources/thailand_tisi.py` | New crawler module, `crawl()` entry point matching the existing `arai.py`/`morth.py` convention exactly. Uses Playwright (already a project dependency, same pattern as `arai.py`) to render the static listing, reads each category heading and its rows, parses the Thai Buddhist-era effective date (`14 ก.ค. 2551` → `2008-07-14`) into a real date, and records each row through the existing `regtrack/sources/common.py` helpers (`record_listing`, `mark_gone`, write-once storage) — no new ingestion machinery needed. |
| `regtrack/scheduler.py` | `CRAWLERS_BY_COUNTRY["TH"]` now maps `TH_TISI_MANDATORY` → `thailand_tisi` (was `{}`). |

## Verification against the live site and the validated database

- First run: 159 items seen (152 "in force" + 7 newly-published entries without an effective date yet), **159 new files downloaded and stored**, 0 errors.
- Re-run (idempotency check, CLAUDE.md rule 7): 159 seen, **0 new listings, 0 new files** — every row correctly recognized as already known. Confirms the crawler is safely re-runnable (e.g. by the 6-hour scheduler) without duplicating work.
- Spot-checked a stored file directly on disk: content decodes cleanly as `cp874` (the Thai legacy codepage the page itself declares via `<meta charset="windows-874">`), byte count matches exactly — the write-once original is faithful to what the server actually sent, not silently re-encoded or corrupted.
- `sources.last_sync_status` = `success` for `TH_TISI_MANDATORY`.
- `pytest`: 111 passed, 1 pre-existing unrelated failure (same as prior phases), 2 skipped. `ruff`: clean.

## Open issue: this is ingestion only, not full pipeline integration

Discussed with the user before building: a document being stored (`stage='downloaded'`) is not the same as it being usable data. Tracing the pipeline further:

- `regtrack/pipeline/text.py`'s `PageText.analyse()` only recognizes English, Hindi, and legacy-Hindi-font text (`lang: en | hi | hi_legacy | mixed | empty | unknown`). Thai script isn't in that list, so every one of these 159 documents will come out as `lang="unknown"`, `is_english=False`.
- Both the deterministic extractor (`regtrack/pipeline/extract.py`) and the Qwen prompt build their input from `english_text()` — pages flagged `is_english`. For an all-Thai document, that's an empty string. The pipeline wouldn't error; it would silently produce a document with no vehicle categories, no scope, nothing — `doc_class` would fall through `classify()`'s generic "no rule matched" path to `OTHER`.
- This is a shared-pipeline gap (every document in the system goes through `text.py`), not something specific to this crawler, so it wasn't fixed as a side effect of building this one source — it needs its own scoped, tested piece of work, deliberately touching code the India corpus already depends on.

So right now: 159 real Thai regulatory documents are correctly discovered, downloaded, and recorded — verified end-to-end against the live site. They will sit at `stage='downloaded'` → `'text'` → classified as `OTHER` if the ordinary pipeline run reaches them, until the Thai-language text-detection work happens separately.

## Not done

- `TH_GAZETTE`: blocked by a live captcha.
- `TH_TISI_DB`, `TH_TISI_PORTAL`, `TH_TISI_NEWS`, `TH_DLT`, `TH_INDUSTRY`, `TH_PCD`: not attempted this phase (`TH_TISI_MANDATORY`'s direct detail pages already cover the richest, most reliable path TH-0 identified; the DB/Portal pair's extra depth wasn't needed).
- Thai-language support in `regtrack/pipeline/text.py` (and consequently real classification/extraction/in-scope flagging for Thai documents) — flagged above as separate future work.
