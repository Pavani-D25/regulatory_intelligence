# Phase 4 — Relevance, classification and identity

## Built
`pipeline/classify.py` (rules from discovery/classify.py + analyze.py, extended to every DB_DESIGN §3 doc_class),
`pipeline/identity.py`, `pipeline/analysis.py`, `stages.stage_classify` (stage `text` → `classified`).
- Relevance: automotive keyword density + issuer (MoRTH, AISC/ARAI, MoEFCC, MoPNG, MoP/BEE, BIS, Law Ministry …) +
  CMVR/MV Act mention; State Government documents are detected separately. Non-automotive or state-level → `OFF_TOPIC`
  (+ `quality_flag off_topic`). Qwen is wired for files still `OTHER` (`classify_with_llm`) but was offline.
- Identity from the English operative heading, never the listing: `G.S.R. 659(E).—` + "New Delhi, the …" date
  (fallbacks: year near the heading, Gazette masthead/ID year). Tolerates poor text layers (`728E)`, `377. (E)`,
  `943{E)`, `G.S.R,`). References take their year from "dated the …" after them. AIS code/Part/Rev from the cover;
  TAP doc no + issue; form number.
- One `document` per identity; many files → one document via `document_file`. Files without an identity get
  `NOTIF-/AIS-UNIDENTIFIED-/DOC-<sha16>` ids and `identity_not_found`.
- Listing claims vs content → `title_file_mismatch`; MoRTH 1 January listing dates → `placeholder_listing_date`.
- doc_date + precision, status (draft: "objections and suggestions … expiry of thirty days"; final: cites its
  draft), issuer, gazette part/section/sub-section/Gazette ID/issue no., file_no, official short title into `data`.

## Numbers (from the DB)
| Measure | Expected | Measured |
|---|---|---|
| MoRTH title ≠ content ID | 6 flagged | **all 6 flagged** (904→903, 3504→3604, 1167→1067, 1432→1433, 454→453, 1162→S.O. 6052) + 7 more MoRTH listings that became readable after OCR: 6 where the listing says "S.O." but the scanned content is a G.S.R. with the same number (103, 367, 515, 583, 586, 84) and S.O. 1407 vs content S.O. 1450(E)-2003; India Code: 954→953, "S.O. 728" (an amendment *to* 728) |
| OFF_TOPIC in folder 02 | ≈ 92 | 138 files = 47 non-automotive (GST, pollution, chemicals, …) + 91 State Government (state MV rules/tax/schemes) |
| GSR/SO numbers reused across years → different canonical_ids | 20 cases | 50 series+number pairs with documents in more than one year, e.g. GSR-659(E)-2016 / GSR-659(E)-2022, GSR-683(E)-2016 / -2022 |
| Notifications with Kruti Dev | ≈ 300 | 232 unique files (≈ 300 with byte-copies) |
| Placeholder listing dates (1 Jan) | 14 | 44 = 31 yearbooks/reports (folder 27) + 18 notifications/circulars (05/06/01) |
| identity_not_found | — | 115 files (mostly OCR'd scans without a readable G.S.R./S.O. heading) |

Documents by class: NOTIFICATION_FINAL 327, AIS_AMENDMENT 327, AIS_STANDARD 276, OFF_TOPIC 198, NOTIFICATION_DRAFT 148,
NOTIFICATION_ORDER 105, AIS_DRAFT 102, FORM_TEMPLATE 90, CIRCULAR_OM 90, AIS_FORM_TABLE 66, REPORT 48, OTHER 30, ACT 30,
GUIDELINE_POLICY 25, NOTIFICATION_EXEMPTION 23, BIS_REGULATION 14, AIS_CORRIGENDUM 10, NOTIFICATION_CORRIGENDUM 8,
NOTIFICATION_EXTENSION 7, FUEL_ORDER 7, APPROVED_LIST 5, AIS_INTERPRETATION 2, BIS_CATALOGUE 1, TAP_DOCUMENT 1,
CONSOLIDATED_RULES 1.

## Open issues
- 30 `OTHER` + 115 unidentified files wait for Qwen (classification fallback / identity when regex fails).
- The 6 "S.O. vs G.S.R." mismatches may be OCR or MoRTH listing errors; the flag keeps both values for checking.
