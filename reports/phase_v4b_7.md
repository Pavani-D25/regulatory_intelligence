# v4B phase 7: API and portal on the v4B tables, plus the v4 workspace screens

**Date:** 18 October 2026 · **Branch:** `v4-schema` · **Plan:** `docs/SCHEMA_V4B.md` §4 · **Tested on:** `regtrack_test`, `regtrack_dev`

## 7a: the API and the portal read and write v4B (commit `87230b9`)

The dashboard was built on the first schema's field names and values: `canonical_id`, `vehicle_categories[]`, `review_status = confirmed`, a source status of `ok` / `partial`, impact `High`. To keep it working unchanged, the translation sits in the queries, in one new module:

| `regtrack/api/sql.py` | v4B → the shape the dashboard uses |
|---|---|
| `docs(cc)` | regulations as documents: the same definition the pipeline uses (`repo.REG_SQL`), which now also returns the short issuer name ("MoRTH", "AISC/ARAI") in SQL |
| `mandates(cc)` | rule versions as mandates: the old columns, category codes, UNECE codes, country |
| `changes(cc)` + `REVIEW` | `regulation_changes`; `reviewed` → `confirmed`, otherwise `auto` (Qwen summary) / `needs_check` (template) |
| `sources(cc)`, `runs(cc)` | `sources` / `ingestion_runs`; `success` → `ok`, `warning` → `partial` |
| `settings`, `put_setting` | `app_settings` (JSON) as text values |

**Where the team's decisions are stored now:**

| Portal action | Before | v4B |
|---|---|---|
| review a regulation (status, impact, owner, note) | `document_review` | `regulations.workflow_status`, `impact_level` + `impact_basis = 'team'`, `owner_team_id`, `review_note`, `reviewed_at`. Clearing the impact returns to the rule at once |
| track a requirement (owner, status, due date, evidence, note) | `compliance_item` | `compliance_requirements` (owner team, status, due date, `evidence_links`, note) |
| owners typed as free text | text columns | teams (created on first use, as 0007 did) |
| mark changes reviewed | `change_event` details | `regulation_changes.review_status = 'reviewed'`, `reviewed_at`; their alerts close at once |
| alert rules | `alert_rule`, evaluated on every page view | `alert_rules`; the page lists the open stored `alert_events`; a new or re-enabled rule is evaluated at once |
| generated reports | `report_log` | `reports` (+ `report_templates`, owner team) |
| settings, scheduler heartbeat, auto-sync | `app_setting` | `app_settings` |

Impact is read from the stored value (phase 6). The Python rule in `classify_row` is kept only as a fallback for a regulation created since the last pipeline run.

**Same answers as before.** 37 read endpoints (the general API, all portal pages, two document details, search, share pack) were saved on `regtrack_dev` before the change (old code, old tables) and after it (new code, v4B), then compared field by field:

| Result | Endpoints |
|---|---|
| identical | search (2), compliance (2), regulation details (2), families, family versions, share pack (files and manifest), vehicle check (2), impact cell, documents by year / topic / text |
| differ only by the new data from phases 2–6 (G.S.R. 760(E)-2026, the job notice, change events 143–144, the MoRTH run of 18 Oct) | dashboard, library, change monitor, impact view, meta, admin, Ask-AI sources, reports |
| intended change | Alerts: the 18 **open** stored alerts instead of all 50 matches of the last 30 days (the page's cap) |
| cosmetic | list order of vehicle categories and topics (now sorted; the main topic stays first); `reviewed_at` in India time instead of UTC (same moment) |

The comparison also showed lists without a defined order where items tie: relations of one type, rule versions on the same date, latest regulations on the same date, issuers with equal counts. These now have tie-breakers, so they come back in the same order every time.

## 7b: the v4 workspace (commits `d16e0e0` and this one)

| Feature | Server (`regtrack/api/workspace.py`) | Screen |
|---|---|---|
| teams and users | `GET /portal/team`, `POST /portal/teams`, `POST /portal/users`, `PATCH /portal/users/{id}` (team, role, active). E-mail is checked and unique; roles viewer / editor / admin | new **Teams** page: KPIs, teams with their users / regulations / requirements / watches, add team, users table (change team or role inline, activate / deactivate), add user |
| watches | `GET /portal/watches`, `POST`, `DELETE` (one team or one user per watch, once) | regulation drawer: **Watched By** chips with remove, team picker + Watch. Teams page: watched regulations with their latest change |
| Ask-AI history | `GET /portal/ask/conversations` (+ the conversation endpoint from phase 5) | Ask AI: **History** card; clicking continues a conversation with its citations; follow-up questions stay in the conversation; New conversation button |
| report schedules | `GET/POST/PATCH/DELETE /portal/report-schedules`; the scheduler runs `run_due_schedules` every hour: due reports are written to `data/reports/`, logged in `reports` with `file_path` and the schedule id, and the next date moves on | Reports: **Scheduled Reports** card: new schedule (report, frequency, team), next / last run, pause / resume, remove |

`/portal/meta` also lists the teams (for the pickers); this is a new key, and nothing existing changed.

**Checked in a browser** (Chrome via Playwright, API on `regtrack_dev`, sample team / user / watch / schedule / question created through the API and removed afterwards):
- Teams page, Reports with a schedule, Ask AI with history, and the drawer all render; no console errors.
- Asking a question adds it to History. New conversation clears the chat, and clicking the history entry reopens it.
- In the drawer, choosing "Regulatory Affairs Team" and Watch adds a second watcher chip.

## Tests

| | Result |
|---|---|
| pytest (`DATABASE_URL` = `regtrack_dev`) | **109 passed, 2 skipped** (MinIO not running) |
| ruff | clean |
| dashboard build (`vite build`) | ok |

New or changed tests:
- **portal review:** team impact and back to the rule; the regulation's previous values are restored afterwards.
- **compliance:** owner and status; the requirement's previous values are restored afterwards.
- **alert rule:** with a category scope.
- **reports log:** shows owner and template.
- **workspace:** same team name gives the same team; duplicate or invalid e-mail; user update; watch rules (once, one owner, unknown regulation); a schedule run writes and logs a report and is not due again; bad frequency refused.

After the tests and the browser check, `regtrack_dev` has no test teams, users, watches, schedules, reports or conversations left.

## Open issues

1. **No sign-in yet.** Users are a directory. Watches and schedules name a team, and conversations have no user. Sign-in (and `assistant_conversations.user_id`, `reviewed_by_user_id`) comes with authentication, which is not in this plan.
2. **Watches and schedules don't send anything.** A watched regulation shows its latest change on the Teams page, and a scheduled report is written as a file. E-mail / Teams delivery to the recipients is not built (no mail settings exist).
3. **Thailand has no vehicle categories** in v4B, as in the old schema. Thai regulations cannot be tagged until the Thai vocabulary is seeded (multi-country rollout).
4. **Report runs find their log row by "latest of this template"**. That is fine with one scheduler process; `generate_report` returning the report id would be cleaner.
5. **Phase 8 remains:**
   - the regression numbers (`report.py` still reads the old tables);
   - the switch of the live database (backup, 0007–0010, verify);
   - dropping the old tables (0011+);
   - updating `CLAUDE.md` / `DB_DESIGN.md`.
