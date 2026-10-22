# Phase MY-2: Malaysian legal texts

**Date:** 22 October 2026 · continues from `phase_th_5_fulltext.md`.

## Sources checked

| Source | Result |
|---|---|
| DOE regulation pages (`www.doe.gov.my/en/environmental-quality-control-of-...`) | Public. Each shows its regulation PDF in a DearFlip viewer whose options (in the page) give the PDF URL. **Used** (`MY_DOE_REGS`). |
| JPJ act pages (`www.jpj.gov.my/akta-333/`, `akta-334-2/`) | Public. A 3D FlipBook viewer whose page data (base64 JSON) gives the PDF URL (Akta 333 as at 15 Oct 2023, 230 pages, downloaded once in the probe). **Built** (`MY_JPJ_ACTS`), but `www.jpj.gov.my` stopped resolving (DNS timeout) during this phase while other hosts resolved: two crawl runs failed with `getaddrinfo failed`. The 6-hour auto-sync retries. |
| AGC Laws of Malaysia (`lom.agc.gov.my`) | Reachable, but every document link is a signed per-link token (`processFile.php?token=…`). Direct URLs answer "Invalid request". **Not used** (CLAUDE.md rule 2). |
| Federal Gazette (`federalgazette.agc.gov.my`) | No answer from this network. |

## What was built

- `0019`: sources `MY_JPJ_ACTS`, `MY_DOE_REGS`; classes `MY_ACT` (LAW) and `MY_SUBSIDIARY_LEGISLATION` (REGULATION).
- `sources/malaysia.py`: `viewer_pdfs()` reads the two viewer widgets. Several pages per source. For the legal-text sources only the PDF is stored (the page is only a viewer around it).
- `pipeline/malaysia.py`: `legal_identity()` reads the document's own first page. `P.U. (A) 543/96` → `PUA-543-1996`, and `Akta 333` → `MY-ACT-333` (formats from `docs/CLASSIFICATION_DESIGN.md` §6.3). It also gives the title, gazette date and in-force date (Malay month names). It reads the full text, because the Malay cover is not an "English" page.
- Client register: MY-03 ← PUA-543-1996, MY-04 ← PUA-429-1996 + PUA-488-2000, MY-05 / MY-06 / MY-07 supporting, MY-16 / MY-01 ← MY-ACT-333 (when JPJ answers).

## Results

| Regulation | Gazetted | In force | Categories |
|---|---|---|---|
| PUA-543-1996 Petrol Engines | 1996-11-01 | 1996-11-01 | ALL |
| PUA-429-1996 Diesel Engines | 1996-08-29 | 1996-09-01 | ALL |
| PUA-488-2000 Diesel Engines (amendment) | 2000-12-28 | 2000-12-28 | ALL |
| PUA-464-2003 Motorcycles | 2003-12-25 | 2004-01-01 | ALL, L3 |

The re-crawl is idempotent (4 seen, 0 new). A first run classified the 4 PDFs with India's rules (the new source codes were missing from `MY_SOURCES`); those 4 records were removed and reprocessed.

`pytest`: 125 passed, 1 failed (pre-existing `test_drafts_are_not_published_standards`), 2 skipped. `ruff` is clean.

## Open

- Akta 333 / 334: waiting for `www.jpj.gov.my` to resolve again (the auto-sync picks it up).
- The Motor Vehicles (Construction and Use) Rules and the JPJ list of adopted UN Regulations: only on the AGC portal (token links), not collected.
- The amendment P.U.(A) 488/2000 is not yet linked as `amends` PUA-429-1996.
