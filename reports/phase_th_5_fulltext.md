# Phase TH-5: full texts of the Thai standards

**Date:** 22 October 2026 · continues from `phase_my_1.md`.

## Source

The TISI database / portal (`appdb.tisi.go.th`, `a.tisi.go.th`) could not be reached from this network: TCP timeouts on ports 80 and 443, both on host 164.115.25.113. It was not worked around. Instead, the detail pages already stored from `www.tisi.go.th/website/standardlist/comp_thai/th` turned out to link each standard's full text at `service.tisi.go.th/fulltext/<n>_<year>.pdf`, which is public and downloads directly. Plain HTTP requests to `www.tisi.go.th` now get an Incapsula block page; the crawler's Playwright render of the list still loads normally (159 rows).

## What was built

- `thailand_tisi.crawl()`: second pass. For each still-listed **automotive** detail page, follow its full-text link and store the PDF write-once (listing category `fulltext`, listed by URL). The other ~140 mandatory standards (steel, plastics, appliances…) are not fetched.
- `text.py`: Thai PDF fonts put shifted tone marks / vowels on private-use glyphs (U+F700–F71A). These are mapped back to standard Thai on pages that contain Thai text.
- `thai.py`: the number pattern accepts the spaced cover form ("มอก. 721   2551") and U+2212 dashes. `full_text_identity` picks, of all the numbers a PDF prints, the one of the standard whose page links it. Several PDFs open with a ministerial amendment notice or an erratum that cites the previous edition first (e.g. "มอก. 2718−2558").
- A PDF with no readable number (มอก.341, an old scan with a broken font layer) is attached as `historical_copy` with an `identity_not_found` flag. It is never the readable copy.
- `stages.py`: for `TIS_STANDARD` the full-text PDF is the best copy, so chunks / search read the full standard. `extract.py`: the TISI summary page's fields (title, effective date, HS codes, scope) win, and the PDF only fills gaps, whichever file is processed first.

## Results

| Measure | Result |
|---|---|
| Full texts downloaded | 17 / 17 (0 errors), 10–141 pages each |
| Attached to the right `TIS-…` regulation | 17 / 17 (16 readable best copies, 1 flagged historical copy) |
| Full-text chunks (Thai, for search; embeddings pending the model) | 1,028 |
| Regulations / open mandates | 17 / 17 (unchanged) |
| Re-crawl with no change | 176 seen, 0 new |

A first run before the identity fix created 6 wrong regulations (previous-edition numbers). They and their 5 mandate versions were removed, and the versions they had closed were reopened.

`pytest`: 123 passed, 1 failed (`test_drafts_are_not_published_standards`, pre-existing), 2 skipped. `ruff` is clean.

## Open

- The inspection-criteria PDFs (`appdb.tisi.go.th/tis_devs/p12/file_pr/…`) are on the unreachable host. Retry when it answers.
- มอก.341 needs Thai OCR to become readable.
