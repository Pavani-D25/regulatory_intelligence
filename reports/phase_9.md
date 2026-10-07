# Phase 9 — Live sources and the 6-hour schedule

## Built
- `sources/http.py` — polite client: 1–2 s random gap per host, exponential backoff (2 s → 120 s, 6 tries) on
  429/5xx and transport errors, User-Agent `RegTrackIndia/0.1 (research)`, Windows certificate store (truststore).
- `sources/common.py` — crawl_run bookkeeping; one transaction per listing row (a bad row is logged, never aborts the
  run); write-once download → `file_object` (sha256 dedup) → `file_sighting` (listing claims); listings already
  imported from the seed `_logs` are linked to their file without re-downloading; `last_seen_at` refreshed at most
  every 20 h and `gone_at` set for rows that disappear after a complete pass — so a re-run writes nothing.
- `sources/morth.py` — MoRTH JSON API (`gazettes-notifications`, `orders-and-notices`, `guidelines`), paged until a
  page adds nothing; highway groups (NH Declaration/Entrustment, …) skipped; broken `/tmp/` links skipped.
- `sources/arai.py` — public AIS page rendered with Playwright using the installed Chrome (no browser download, the
  embedded bearer token is never used), Published + Draft tabs, 10 rows/page, public `/storage/ais-details/` files.
- `sources/indiacode.py` — India Code moved to `indiacode.gov.in` (DSpace 7); public REST search (no login, no
  captcha) for the seed corpus' queries; State Government items skipped; stops at the first fully known page.
- `sources/egazette.py` — public "Search by Ministry" (MoRTH, month/year) via Playwright; highway subjects (NH Act
  §3A/3D, user-fee, …) skipped, other gazettes downloaded and judged by content. The grid's PDF viewer embeds
  `WriteReadData/<year>/<number>.pdf`, so PDFs are plain polite GETs. Captcha or login on any page → the run stops
  with status `partial` and says so (none was met).
- `scheduler.py` — APScheduler: each source every 6 h (staggered start) + hourly pipeline catch-up (picks up work
  left while the LLM was offline); every crawl is followed by a full pipeline run. `change_event` rows
  (new_document, new_amendment, new_revision, corrigendum, draft_published, draft_finalised,
  implementation_date_changed, mandate_superseded) with a Qwen one-liner when reachable, else a template marked
  `needs_check`. Windows Task Scheduler alternative documented in README.

## First live runs (8 Oct 2026)
| Source | Seen | Already known | New listings | New files | Notes |
|---|---|---|---|---|---|
| MORTH_API | 1,160 | 937 | 218 | 34 | 5 dead links at MoRTH (HTTP 404), 8 XLSX templates (reader added) |
| ARAI_AIS | 426 (358 published + 68 drafts) | 357 | 69 | 64 | the Draft tab was empty when the seed was collected |
| INDIACODE | 60 central items | 60 | 0 | 0 | 75 state items skipped |
| EGAZETTE | 7 (Sep–Oct 2026, after skipping ≈ 360 highway gazettes) | 0 | 7 | 7 | incl. new draft **GSR-793(E)-2026** (CMVR amendment) |

Change events from these runs: new_document 61, draft_published 44, new_revision 12, draft_finalised 3,
corrigendum 1, implementation_date_changed 1, new_amendment 1.

## Check: a second run right after the first writes zero new rows
```
before: file_object 2142, file_sighting 5968, document 2048, document_file 2545, doc_relation 5263, mandate 178,
        chunk 147272, change_event 123, quality_flag 930, crawl_run 10
after : identical, except crawl_run 13 (each run logs its own crawl_run row by design)
MORTH_API 2nd run: seen 1160, known 1155, new 0 (5 = MoRTH's dead links, retried each run)
ARAI_AIS 426/426 known · INDIACODE 60/60 known · EGAZETTE 7/7 known
```

## Problems found and fixed
- Untyped NULL query parameter aborted the first MoRTH run → typed casts + per-listing transactions.
- e-Gazette: ASP.NET only sends its paging scripts to browsers it recognises, so the bare project UA got a page
  without `__doPostBack`; the crawler now sends Chrome's UA with `RegTrackIndia/0.1 (research)` appended. Its TLS
  chain lacks an intermediate certificate → Windows trust store (verification stays on).

## Open issues
- e-Gazette paging beyond page 10 uses the `...` link; months with > 150 MoRTH gazettes are long but complete.
- Event summaries wait for Qwen.
