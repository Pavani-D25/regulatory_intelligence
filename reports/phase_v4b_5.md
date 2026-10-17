# v4B phase 5: search and Ask-AI history on the v4B tables

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4 · **Tested on:** `regtrack_test`, `regtrack_dev`

## What was built

| File | Change |
|---|---|
| `db/migrations/0009_chunk_tsv.sql` | **new.** `document_chunks.tsv` becomes a column the database computes from `content` in the chunk's language (`chunk_ts_config`: English → `english`, others → `simple`), with its GIN index. 0007 left `tsv` empty in all 148,342 rows, and `document_chunks` has no expression index like the old `chunk_fts_idx`, so keyword search would have recomputed every chunk on every query |
| `regtrack/pipeline/chunk.py` | chunks are written to `document_chunks` with the regulation's filter copies (region, doc_type, legal_status, is_current, in_scope, year, vehicle-category ids, topic ids), using the same definition as the 0007 copy. Re-chunking, page-range rebuilds and TAP index offsets work as before. `sync_chunk_filters` now also keeps `year` and `doc_type` up to date. Embedding and `advance_embedded` use `document_chunks` / `documents` (English chunks only; Hindi is never embedded) |
| `regtrack/pipeline/search.py` | vector and keyword search on `document_chunks` + `regulations`. The category filter uses the region's category ids (category or ALL). Keyword search uses the `tsv` index. Results also carry `regulation_id` (for citations) |
| `regtrack/assistant.py` | **new.** `record_exchange` stores question, answer and the cited chunks (`assistant_conversations`, `assistant_messages`, `assistant_message_citations` with score); `conversation` reads one back |
| `regtrack/api/portal.py` | `POST /portal/ask` keeps every exchange (also the plain clause list when Qwen is off) and returns `conversation_id`; sending it back continues the conversation. New `GET /portal/ask/conversations/{id}`. The answer logic is unchanged |
| `regtrack/pipeline/runner.py` | `post_run` refreshes the regulation fields before the chunk sync, so the chunks get the new `doc_type` in the same run |
| tests | 3 new tests in `test_pipeline_v4b.py`; `test_country.py` (search stays in its country) and `test_portal.py` (ask: history kept, follow-up, 404, own rows removed) moved to v4B |

**Note on running the tests on this branch.** `test_portal.py` and parts of `test_country.py` run against `DATABASE_URL`. On `v4-schema` this must be `regtrack_dev`, because the live database has no v4B tables until phase 8:

```powershell
$env:DATABASE_URL = "postgresql+psycopg://regtrack:regtrack@localhost:5432/regtrack_dev"; .venv\Scripts\python -m pytest
```

## Tests

| Test | Shows |
|---|---|
| chunks carry the regulation's filters | S.O. 1406(E)-2021 chunks in order, each with region, type `REGULATION`, status, year 2021, category ids, language, `tsv`; re-chunking writes only the 2 stage updates; a status change reaches all its chunks in one sync, and the next sync does nothing |
| keyword and vector search | keyword search finds it (mode `text`); "ALL" makes it match any category; without ALL and L1 an L1 search leaves it out while N3 still finds it; with embeddings every chunk gets a vector, the file moves to `done`, vector search answers with a score |
| assistant history | two exchanges in one conversation, an unknown id starts a new one, citations come back with regulation and score |
| portal ask (on `regtrack_dev`) | answer with sources, `conversation_id`, follow-up in the same conversation, history in order with one citation per source, 404 for an unknown conversation |

| | Result |
|---|---|
| pytest (`DATABASE_URL` = `regtrack_dev`) | **103 passed, 2 skipped** (MinIO not running) |
| ruff | clean |

## Real runs on `regtrack_dev`

**Migration 0009:** 19 seconds; all 148,342 chunks have `tsv` (8 are empty: chunks of only numbers or stop words).

**Re-chunk everything, rolled back:** all 2,144 chunked files re-chunked with the new code in one transaction. Writes: only `documents` 512 updates (files at `done` going back to `chunked`); **0** chunk rows inserted, changed or deleted, 0 errors.

**Same answers from search, faster.** Keyword search with the old code (old tables) and the new code (v4B), same filters, top 10:

| Question | Category | Same results, same order | Old | New |
|---|---|---|---|---|
| traction battery safety | – | yes | 29 ms | 3 ms |
| wheel rims | L2 | yes | 19 ms | 5 ms |
| seat belt anchorages | M1 | yes | 38 ms | 7 ms |
| ABS motorcycles (7 hits) | L2 | yes | 13 ms | 6 ms |
| high security registration plate | – | yes | 11 ms | 3 ms |
| tyre pressure | N1 | yes | 29 ms | 7 ms |
| emission norms BS VI | M1 | yes | 10 ms | 4 ms |
| speed limiting device | – | yes | 21 ms | 5 ms |

**Chunk years corrected (299 rows).** The first filter sync on the copied data changes 299 chunks, all in the `year` column. The old sync never refreshed a chunk's year once the document's date was corrected after chunking. Examples:
- the 283 chunks of AIS-123(Part1) have no year, but the standard is dated 2025, so a year filter misses them;
- chunks of undated documents carry years such as 2027 and 2040.

After this sync the copies match the regulations; a second sync changes 0.

**New files chunked for real:**
- draft G.S.R. 760(E)-2026: 4 chunks;
- job notice: 9 chunks.

Both carry year 2026, their type, and `tsv`. Embedding wrote nothing (`EMBED_MODEL` is a placeholder), so both files correctly wait at `chunked`.

**Ask AI on `regtrack_dev`:** a question was answered from 8 clauses (mode `search`, Qwen off). The question, the answer and the 8 citations were stored. The test conversation was deleted afterwards (0 assistant rows left).

## Open issues

1. **Keyword-only answers are weak on specific questions.** "Comment period for the draft amending CMVR rule 125" does not rank G.S.R. 760(E)-2026 near the top: keyword search scores frequent words, not meaning. This is the same as before the move; vector search starts once `EMBED_MODEL` is configured, and all 148k chunks are then embedded by the normal `embed` stage.
2. **No user on conversations.** `user_id` stays empty until the portal has logins (phase 7, decision D4).
3. **One inconsistent date:** AIS-145 is published 2018-12-01 but its `year` column says 2027. The chunks now follow the published date (2018). The `year` value itself comes from identity parsing and is worth a look separately.
4. **Still on the old tables:** change events, flag resolution, report, and the rest of the API and portal (`/ask/context`, dashboards), in phases 6–7.
