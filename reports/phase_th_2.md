# Phase TH-2: dashboard country dropdown + cascading filter

**Date:** 19 October 2026 · **Plan:** `Thailand parity + cascading dashboard country filter` (TH-0..TH-8)

**Status:** done.

## What was built

| Item | What |
|---|---|
| `dashboard/src/api.js` | Centralized country injection instead of threading `country` through ~30 function signatures. A module-level `currentCountry` (initialized from `localStorage["ri.country"]`, same key `PortalLayout` persists to) is merged into every `get()`'s query string and every `send()`'s query string *and* JSON body (some POST endpoints read `body.country`, not `?country=` - `add_alert`, `run_sync`, `/ask`). `setApiCountry(cc)` is the one write path, called only from `PortalLayout`. `reportUrl()` now goes through the same `qs()` helper. |
| `dashboard/src/portal/PortalLayout.jsx` | New `country`/`setCountry` state, exported `COUNTRIES = [["IN","India"],["TH","Thailand"]]`. The sidebar's hardcoded "India · Automotive" is now `{countryName} · Automotive`. A new country `<select>` sits next to the existing (still-static) language selector. `setCountry` persists to `localStorage`, calls `setApiCountry`, and bumps `version` - the same counter the dashboard already uses to force every `useLoad(..., [...​, version])` call to refetch after a sync finishes, so switching country re-fetches every widget through the mechanism that already existed, not a new one. |
| `Admin.jsx`, `Compliance.jsx`, `AskAI.jsx` (×2 calls) | Didn't have `version` in their fetch deps at all (confirmed by a full `useLoad` audit of all 10 portal pages + 6 legacy pages) - would have kept showing stale-country data silently. Added. |
| `Compliance.jsx`, `AskAI.jsx` | A category filter or an in-progress AI conversation from the previous country doesn't carry forward: `Compliance`'s category resets on `country` change (a filter value from one country may not exist in the other); `AskAI`'s conversation resets the same way (continuing a thread across countries would mix clause search results from both). |
| 6 legacy "Tools" pages (`Browse`, `DocumentDetail`, `FamilyTimeline`, `Search`, `Versions`, `VehicleCheck`) | None called `usePortal()` before; none had `version` in their fetch deps. All now do. `Browse.jsx`'s separate legacy `api.meta()` poll (not `portal.meta()`) also needed `version` added - it wasn't using the shared `meta` from context at all. |
| Hardcoded `L1/L2/M1/N1` category lists | `Search.jsx` and `VehicleCheck.jsx` had **literal India-only arrays** for their category `<select>` (`VehicleCheck.jsx` even had India-specific labels like "L2 – motorcycle / scooter"). Both now read from `meta.categories`, so they already show `L1/L3/M1/N1` with Thailand's own labels when Thailand is selected - verified live in the browser. `Browse.jsx`'s "In scope only (L1/L2/M1/N1)" checkbox label was the same kind of hardcode, fixed the same way. |
| "India"/"Indian" copy in 5 pages | `Dashboard.jsx`, `AskAI.jsx` (welcome message + chat subtitle), `Regulations.jsx` (page description + CSV filename `regulations_india_*.csv`), `Reports.jsx` ("India ·" in the page subtitle), `ChangeMonitor.jsx` (named India's specific sources: MoRTH/ARAI/e-Gazette/India Code - generalized to "every monitored source" rather than hardcoding Thailand's source names too). |

## Design choice: centralized injection vs. per-call-site params

The plan (written from an earlier research pass) assumed every `portal.X()`/`api.X()` call already took a plain params object, making "add `country` to each call" mechanical. Re-reading `api.js` directly before implementing found this was only true for about half the functions - `portal.summary()`, `portal.impact()`, `portal.changes(days)`, `portal.compliance(category)`, `portal.reports()`, `portal.alerts()`, `portal.admin()`, `portal.askContext()` and others take fixed positional args or none at all. Rewriting ~30 signatures and ~20 call sites to thread a new parameter through would have been far more invasive and error-prone (easy to miss one silently) than injecting the country at the two chokepoints every request already passes through (`get()`/`send()`). Switched to that approach; it also means any *future* API call automatically inherits the current country with zero extra code - a page author can't forget to pass it.

## Verification

- `npm run build`: clean, no errors.
- Live in the browser (Chrome extension), both as India (default) and after switching to Thailand, confirmed on every page - Dashboard, Regulations, Change Monitor, Compliance Matrix, Impact View, Ask Regulatory AI, Reports, Alerts, Teams, Admin, Vehicle Check, Versions:
  - Sidebar and dropdown both show the selected country; page copy ("Live view of Thai vehicle regulations... for L1, L3, M1, N1", "Search, filter and review Thai vehicle regulations...", "Generate regulatory reports from live data · Thailand · L1, L3, M1, N1") is fully dynamic, not hardcoded.
  - **Admin** correctly lists Thailand's 8 sources (`TH_TISI_NEWS`, `TH_TISI_PORTAL`, `TH_TISI_DB`, `TH_TISI_MANDATORY`, etc.) when Thailand is selected - this was the exact gap the user first reported ("Admin page Regulatory Sources... why it's not shown").
  - **Impact View**'s heatmap columns render Thailand's actual category labels ("L1 Two-wheeled moped", "L3 Motorcycle", ...), confirming the grid is fully data-driven, not assuming 4 fixed India codes.
  - **Vehicle Check**'s category dropdown shows `L1/L3/M1/N1` with Thailand's own labels once Thailand is selected (verified via element inspection, not just a screenshot).
  - Network requests inspected directly (Chrome extension's network reader): every `/portal/*` call carries `?country=IN` or `?country=TH` as expected, including calls (like the notification bell's `/portal/alerts`) that needed no code change at all because of the centralized injection.
  - Selection survives a full page reload (localStorage persistence confirmed).
- `pytest`: 102 passed / 8 failed, identical to TH-1's end state - confirms this phase touched nothing on the backend.

## Known, deliberately deferred

- `Regulations.jsx` and `Search.jsx`'s `category` filter comes from the URL (`useSearchParams`), not component state - a stale India-specific category code left in the URL when switching to Thailand isn't auto-cleared (unlike `Compliance.jsx`, where it was a trivial fix). The backend already degrades gracefully here (falls back to showing every category rather than erroring - `portal.py`'s `regulations()`/`search()` treat an invalid category as "no filter"), so this is a minor UX polish item, not a correctness bug. Not fixed in this phase to avoid touching URL-state logic shared with bookmarking/sharing.
- The language selector next to the new country selector is still the pre-existing non-functional stub (`<option value="en">English</option>` only) - unrelated to this phase, untouched.
