# Phase TH-4: TISI pages classified, off-topic standards marked

**Date:** 22 October 2026 · continues from `phase_th_3_ingest.md`.

**Status:** done. The 159 TISI pages stored in TH-3 now go through the pipeline (text → classify → extract → link). The automotive ones become `TIS_STANDARD` with content-derived identity, scope and vehicle categories. The rest (circuit breakers, steel, plastics, …) become `OFF_TOPIC`.

## Why

The TISI mandatory list (`www.tisi.go.th/website/standardlist/comp_thai/th`) covers every product type, not just vehicles. Only about 17 of its 159 entries concern vehicles. Before this phase, nothing distinguished e.g. `hscode_view.asp?id=184` (มอก.60947-2, low-voltage circuit breakers) from มอก.721 (seat belts): all 159 sat at `stage='downloaded'`.

## What was built

| File | What |
|---|---|
| `regtrack/pipeline/thai.py` (new) | Deterministic reading of a TISI page: มอก. number → `TIS-<n>[(Part<k>)]-<B.E. year>` (format from `docs/CLASSIFICATION_DESIGN.md` §6.3), Thai title, scope (ขอบข่าย), effective date (2- or 4-digit B.E. year), HS codes, vehicle categories. Includes the automotive test. |
| `regtrack/pipeline/text.py` | `read_html` decodes with the page's declared charset (TISI: `windows-874` → cp874). It used to read every page as UTF-8, which turned all Thai text into garbage. UTF-8 stays the default. The only India HTML file is pure ASCII, so its text is unchanged. |
| `regtrack/pipeline/classify.py` | A TISI listing is `TIS_STANDARD` (issuer TISI) if automotive, else `OFF_TOPIC`. This runs before the folder rules. |
| `regtrack/pipeline/analysis.py` | `TIS_STANDARD` identity comes from the page's own มอก. heading (rule 5). If the listing title names a different number, a `title_file_mismatch` flag is raised. |
| `regtrack/pipeline/stages.py` | `TIS_STANDARD` uses its `TIS-…` canonical id. With no number on the page, it falls back to `DOC-<sha>` and raises `identity_not_found`. |
| `regtrack/pipeline/extract.py` | `TIS_STANDARD` branch fills `TisStandardData` from Thai text. Thai titles are exempt from the ASCII-based junk-title check. No Qwen call (the page is a one-page summary the rules read completely). An empty category list raises `no_vehicle_category`. |
| `regtrack/models/data.py`, `schemas/TIS_STANDARD.json` | New `TisStandardData` model (title, tis_no, year_be, effective_date, scope_text, hs_codes); schema regenerated. |
| `regtrack/sources/thailand_tisi.py` | Uses the shared `thai.parse_thai_date`. |
| `db/migrations/0016_activate_tisi_mandatory.sql` | Sets `is_active = true` for `TH_TISI_MANDATORY`, so the scheduler crawls it. It was already applied to the dev DB in TH-3 but had not been committed. |

### Rules (all deterministic, read from page content)

- **Automotive:** TISI's own product group is ยานยนต์ (automotive), **or** the page *title* names a motorcycle or an internal-combustion engine (helmets มอก.369, engine LPG tanks มอก.370). The check uses the title only. Scopes also name vehicles in exclusions: มอก.27 (LPG cylinders) "does not cover tanks for internal-combustion engines". "รถยนต์" (car) on its own is not enough, because automotive sheet steel uses it.
- **Vehicle categories** (Thailand has L1, L3, M1, N1):
  - UN codes in the scope ("M1", "M 1", "L 3").
  - Bare class letters only right after ประเภท (category). This matters because "ภาคผนวก L" means Annex L, as on the circuit-breaker page.
  - Fallback to the vehicle words: รถจักรยานยนต์ (motorcycle) → L3, โมเปด (moped) → L1, รถยนต์ (car) → M1 + N1.

## Results (live dev DB)

| Measure | Result |
|---|---|
| TISI pages processed | 159 / 159, 0 errors at text, classify, extract, link |
| `TIS_STANDARD` | 17 (the 15 ยานยนต์ entries + มอก.369 + มอก.370) |
| — of which `in_scope = true` | 16 |
| — `in_scope = false`, `needs_check` | 1: มอก.370 engine LPG tank (names no vehicle) |
| `OFF_TOPIC` | 142, each with an `off_topic` flag (incl. id=184, the circuit breaker → `DOC-8cb4d97f7bceebe9`) |
| Re-run with no change | 0 files, 0 events, 0 rows (rule 7) |
| Effective dates vs. the Thailand requirements table | TIS-3017-2563 (light petrol Euro 6-equivalent) 2025-01-01; TIS-3044-2563 (large petrol) 2026-01-01; both match TH-03 and TH-04 |

`pytest`: 118 passed, 1 failed (`test_drafts_are_not_published_standards`, pre-existing, see `phase_th_1_rebuild.md`), 2 skipped. 7 new tests use 5 real TISI pages as fixtures. `ruff` is clean on `regtrack/` and `tests/`. The 56 findings in `discovery/` predate this work.

## Coverage against the Thailand requirement areas (TH-01 … TH-14)

| Covered by this source | Not covered (needs another source) |
|---|---|
| TH-03, TH-04, TH-05 emissions; TH-09 tyres; TH-11 seat belts / helmets; partly TH-06 (tyre noise only), TH-12 (glazing, no mirrors), TH-01 (list of mandatory standards) | TH-02, TH-07 (DLT); TH-08 lighting; TH-10 brakes; TH-13 EV; TH-14 EMC |

## Open issues

- A TISI page is a summary: number, title, scope, label text, HS codes. The limits and test methods are in the full standard and the Royal Gazette notice. `TH_GAZETTE` is captcha-blocked; `TH_TISI_DB` / `TH_TISI_PORTAL` are not built yet.
- `usage`, `powertrains` and `domains` stay empty for Thai documents, because those vocabularies are English keyword lists.
- Thai pages will be chunked and embedded by the next scheduler run like any other text. Search quality on Thai depends on the embedding model (the EMBED_DIM question from TH-1 is still open).
- "Large vehicle" emission standards (มอก.3044 / 3046) get M1 + N1 because their scope covers M1/N1 above 2,610 kg reference mass. This is correct, but those vehicles are heavier than typical cars.
