# Phase 6 — Extraction (stage `classified` → `parsed`)

## Built
`pipeline/extract.py`:
- Deterministic first, per doc_class: dates, file no., gazette part/section/Gazette ID, signatory, powers (MV Act
  sections), commencement, comment period (drafts), amended targets (CMVR rules, S.O. 1365(E) table), amended
  notifications, references (AIS / IS / UN R / ISO / IEC regexes); AIS: cover title, Scope clause, transitional
  provisions, "deemed to comply" standards, UN R basis, annexes; AIS amendments: add/substitute/delete instructions;
  circulars: ref no., date, subject, addressees; BIS catalogue rows from the CSV; forms: number, rule, purpose.
- Vehicle categories via the `vehicle_category` synonym table (explicit codes count once, plain words such as
  "truck" need two mentions in long texts; O1–O4 → O, T1–T5 → T; "all motor vehicles" → ALL), numeric conditions,
  usage, powertrains, domains (seed keywords), nature, `in_scope` = categories ∩ {L1, L2, M1, N1, ALL}.
- Qwen pass (when reachable): the doc_class Pydantic model wrapped with subject, implicit vehicle categories and
  per-field confidence, `with_structured_output(method="json_schema")`, English pages only (AIS: cover + scope +
  transitional). Fixed-format fields keep the regex value; disagreements go to `needs_check`.
  A second, independent identity/status/date prompt runs on a deterministic 10 % sample (`extraction.agreement`).
- `document.data` is validated against the generated JSON Schema → `schema_violation` flags (kept, `needs_check`).
- `document.extraction` = {model, rules version, prompt version, confidence per field, needs_check, source file, pages,
  llm_pending}.

## The 30-document trial
Run first on 30 files (notifications, Acts, OFF_TOPIC, …). Two problems found and fixed before the full run:
subjects were empty for notifications without a short title (now: the operative "hereby specifies/exempts …" clause,
else "Amends CMVR Rule …"), and single plain-word mentions added categories (now two mentions needed).

## Fill rates (documents excl. OFF_TOPIC: 1,743; identified notifications: 523; AIS standard/amendment/corrigendum: 613)
| Column | All | Notifications | AIS |
|---|---|---|---|
| subject | 90.4 % | 81.2 % | 100 % |
| issuer | 92.7 % | 96.6 % | 100 % |
| doc_date | 71.7 % | 95.0 % | 83.7 % |
| year | 64.1 % | 100 % | 85.3 % |
| official_title | 28.2 % | 38.9 % (short titles only) | 45 % (standards) |
| nature | 90.2 % | 78.4 % | 100 % |
| vehicle_categories | 45.0 % | 55.2 % | 30.0 % before Phase 7 inheritance; standards 184/276 |
| domains | 71.0 % | 65.7 % | 73.7 % |
| data / extraction | 98.1 % / 100 % | 100 % | 100 % |

- Schema violations: 0. `no_vehicle_category` flags: 362 (fees/licensing/permit notifications that name no category,
  and AIS files whose Scope clause was not found).
- **Qwen agreement rate: not measurable** — LM Studio was offline for the whole run (`LLM_BASE_URL` is still the
  placeholder). 1,537 documents are marked `llm_pending`; `enrich_pending()` runs them automatically on the next
  pipeline run once the endpoint answers, including the 10 % double extraction.

## Open issues
- Provisions (`data.provisions`) and implicit applicability are Qwen's job (DB_DESIGN §7); only the deterministic
  S.O. 1365(E)/rule obligations are covered until then (Phase 7).
