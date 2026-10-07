# Phase 7 — Links, versions and mandates (stage `parsed` → `linked`)

## Built
- `pipeline/link.py` — `doc_relation`: finalises (draft citation regex, or equal file_no), amends / corrects /
  extends_date / exempts between notifications, substitutes_row / inserts_row / omits_row (rows in `details.rows`) and
  extends_date (old/new date) for S.O. 1365(E) and CMVR Rule 124(4) tables, AIS amends / corrects / revises
  (`requires_reapproval = true`), annex_of (AIS-007 tables), interprets, supersedes ("deemed to comply"), references.
  Unknown targets keep `to_ref`; `resolve_refs()` fills `to_doc` when the target arrives later.
- Versions: `family_key` (AIS code[+Part], `SO-1365-MASTER`, `CMVR-Rule-124`, `TAP-115/116`, AIS-007 tables),
  `version_seq` (revision, amendment, corrigendum / date order), exactly one `is_current` per family; older revisions
  get status `superseded`. AIS amendments inherit categories/domains of the standard they amend.
- `pipeline/mandates.py` — deterministic replay in notification date order:
  row/item substitutions and insertions with quoted entries (also rows without item letters and "For new models / For
  existing models" dates → separate `[new_models]` / `[existing_models]` slots), date substitutions (the open
  version with the stated old date — or, when an intermediate notification is missing, the row's latest-dated open
  version, flagged `old_date_mismatch`), omissions, CMVR rule obligations ("manufactured on or after <date> …
  conforming to IS/AIS …"), and Qwen provisions when present. A change closes the old row (`valid_to`,
  `superseded_by`) and inserts a new one with the same `mandate_key`. Draft mandates are `is_draft`; a final closes
  its draft's mandates.

## Checks
| Check | Expected | Measured |
|---|---|---|
| Finals linked to drafts | 225 (121 resolved / 104 to_ref) | 204 finals by citation (92 resolved / 112 to_ref, each with `unresolved_reference`) + 9 by file_no |
| Wheel-rim chain S.O. 1406 → 359 → 3896 → 3800 | 4 versions of one mandate_key | `SO-1365(E)-2004 Table Sr.8(d)`: 21-09-2021 → 21-09-2022 → 22-06-2023 → 22-12-2023, each closed by the next; a 5th row from S.O. 3947(E)-2023, a corrigendum to S.O. 3800 restating 22-12-2023 (legal basis change only) |
| One is_current per family | all | 0 families violate it (enforced by the partial unique index) |

Relations: references 4,251 (1,896 resolved), amends 351, finalises 213, annex_of 66, revises 62, corrects 10,
extends_date 9, substitutes_row 6, supersedes 2, interprets 2, omits_row 1.
Mandates: 177 rows, 120 mandate_keys, 110 open, 47 draft, from 67 notifications.

## Open issues
- The S.O. 1365(E) 2004 master table itself is **not in the corpus** (searched all folders), so it could not be seeded
  by OCR/vision. Rows appear when a later notification substitutes or inserts them; date changes to rows never seen
  (e.g. S.O. 4143(E) Sl. 26(b),(c) → 1 Oct 2022) create a mandate with the notification's subject and no standards.
- Of the 18 S.O. 1365(E) amenders, 7 still yield no rows (older scans / free-form tables: S.O. 1558/2014, 2590/2014,
  1013/2015, 1139/2015, 2211/2018, 4567/2022, 451/2005) — these are exactly the "main extraction of provisions" DB_DESIGN
  §7 gives to Qwen; they are `llm_pending`.
- 112 drafts are cited but not collected (`unresolved_reference`); the new crawlers resolve them when they arrive.
