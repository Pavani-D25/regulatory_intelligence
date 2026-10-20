# Phase TH-2 (rebuilt): dashboard country selector

**Date:** 20 October 2026 · continues from `phase_th_1_rebuild.md`.

**Status:** done — rebuilt from `phase_th_2.md`'s description (the original handoff had no dashboard code at all), verified live in the browser against both India and Thailand.

## What was built

| File | Change |
|---|---|
| `dashboard/src/api.js` | Centralized country injection: a module-level `currentCountry` (from `localStorage["ri.country"]`) merged into every `get()`'s query string and every `send()`'s query string *and* JSON body. `setApiCountry(cc)` is the one write path. `reportUrl()` goes through the same `qs()` helper. |
| `dashboard/src/portal/PortalLayout.jsx` | New `country`/`countryName` state and `COUNTRIES` export (`IN`/`TH`). Sidebar brand subtitle and a new country `<select>` next to the language selector. `setCountry` persists to `localStorage`, calls `setApiCountry`, and bumps the existing `version` counter. `country`/`countryName` exposed via context (`usePortal()`). |
| `Admin.jsx`, `Compliance.jsx`, `AskAI.jsx` | Didn't have `version` in their fetch deps — added. `Compliance.jsx`'s category and `AskAI.jsx`'s conversation now reset when `country` changes (a filter/conversation from the other country wouldn't be valid). |
| 6 legacy "Tools" pages (`Browse`, `DocumentDetail`, `FamilyTimeline`, `Search`, `Versions`, `VehicleCheck`) | None called `usePortal()` before; none had `version` in their fetch deps. All now do. |
| Hardcoded `L1/L2/M1/N1` arrays | `Search.jsx` and `VehicleCheck.jsx` had literal India-only category arrays (`VehicleCheck.jsx` even had India-specific labels). Both now read from `meta.categories`. `Browse.jsx`'s "In scope only" checkbox label was the same kind of hardcode, fixed the same way. |
| "India"/"Indian" copy | `Dashboard.jsx`, `AskAI.jsx` (welcome message + chat subtitle), `Regulations.jsx` (description + CSV filename), `Reports.jsx` ("India ·" in subtitle), `ChangeMonitor.jsx` (named India's specific sources, generalized to "every monitored source") |

## A bug caught during verification, not in the original report

`PortalLayout`'s `portal.meta()` polling effect (`useEffect(..., [toast])`) didn't depend on `country`: switching the dropdown updated the label and the per-country backend calls, but the shared `meta.categories` (used for "Vehicle Categories" / dropdown options everywhere) stayed stale until the next 60-second poll. Caught by actually reading the rendered category list after switching to Thailand (it said "L1, L2, M1, N1" instead of "L1, L3, M1, N1"), not just checking it compiled. Fixed by adding `country` to that effect's dependency array.

## Verification

- `npm run build`: clean, no errors.
- Live in the browser (built-in browser pane), pointed at the `regtrack-api-th-validate` API (the `regtrack_th_validate` DB from the previous phase):
  - Switching India → Thailand updates the sidebar brand, the category list everywhere (`L1, L3, M1, N1`), and persists across a full page reload (`localStorage`).
  - **Admin** correctly lists Thailand's 8 sources, each honestly marked "no crawler yet" (TH-3 isn't done) — this was the original gap your team lead's report said this phase fixed.
  - **Vehicle Check**'s category dropdown shows `L1/L3/M1/N1` with Thailand's own labels (confirmed via the accessibility tree, not just a screenshot).
  - **Compliance**, **Impact**, **Reports**, **Ask Regulatory AI**, **Change Monitor**, **Alerts**, **Teams**, **Browse**, **Search**, **Versions** all load cleanly for Thailand with zero console errors.
  - Switching back to India: category list correctly reverts to `L1, L2, M1, N1`, no stale state left over from Thailand.

## Known, deliberately deferred (same as the original report)

- `Regulations.jsx`/`Search.jsx`'s `category` filter comes from the URL, not component state — a stale category code left in the URL when switching country isn't auto-cleared. The backend already degrades gracefully (falls back to no filter on an unrecognized category), so this is minor UX polish, not fixed here.
- The language selector remains a non-functional stub.
