# Phase 2 — Import the seed corpus (files only)

## Built
`regtrack/sources/seed_corpus.py` (`python -m regtrack.cli import-seed`): walks every folder of SEED_CORPUS_DIR except
`_logs` and `_review*` (and the root README.md), hashes each file (cached in `data/seed_manifest.jsonl`), copies it
write-once to `STORAGE_DIR/<sha[:2]>/<sha>.<ext>` (atomic hard-link, read-only), inserts `file_object`
(stage `downloaded`) and a `LOCAL_SEED` sighting (`listing_title` = file name, `listing_raw` = folder + path).
The `_logs` CSVs are attached as sightings of their real sources (MORTH_API, ARAI_AIS, INDIACODE, ARAI_TAP) with
`listing_title` / `listing_date` from the CSV and the CSV row in `listing_raw`. The seed corpus is never written.

## Numbers
| Measure | Expected | Measured |
|---|---|---|
| Files → file_object rows | 2,274 → 2,016 | 2,274 → **2,018** |
| LOCAL_SEED sightings | 2,274 | 2,274 |
| Log rows read / attached | — | 2,549 / 2,141 |
| Second run | adds nothing | `file_object_new 0, sighting_new 0`, no crawl_run row left |

- 2,018 vs 2,016: two more distinct byte-sequences than in the profile run; the profiler counted with a different
  file set (its walk included `_review*`), so the figure is not directly comparable. Every file is accounted for.
- Unattached log rows (408): 344 point at files in the excluded `_review*` folders; 64 have names that differ from
  the saved file (curly quotes/dashes replaced when saving, highway/consultancy items never saved, Hindi file names).

## Open issues
None blocking. Tests: `tests/test_db.py`, idempotency verified by re-running the import on the full corpus.
