# Document classification for every country (India, Thailand, Malaysia)

**Status:** proposal, for decision. Nothing in this file is implemented yet.
**Date:** 14 October 2026
**Applies to:** `document` classification (pipeline Step 5) and everything that filters on it (portal, API, search).
**Related:** `docs/DB_DESIGN.md` §3 (current India vocabulary, authoritative until this is accepted), `docs/PIPELINE_WALKTHROUGH.md` (Step 5), migration `0005_country_thailand.sql`.

---

## 1. Why change

Today every document gets one `doc_class`, for example `NOTIFICATION_EXTENSION` or `AIS_AMENDMENT`. That one name mixes three different questions:

| Part of the name | Question | Problem when adding countries |
|---|---|---|
| `AIS_`, `TAP_`, `BIS_`, `NOTIFICATION_` | What kind of document is it? | Indian names. Thailand has TIS and ministerial regulations; Malaysia has MS and P.U.(A). |
| `_AMENDMENT`, `_EXTENSION`, `_EXEMPTION`, `_CORRIGENDUM` | What does it do to other documents? | Repeated for every kind, and again for every country. |
| `_DRAFT` | Is it final? | Duplicates the `status` column. |

Continuing this way means a new list per country (`TIS_STANDARD`, `TIS_AMENDMENT`, `MS_STANDARD`, `MY_PU_A`…). The portal could then not compare countries or filter "all regulations" across them.

**Goal:** one classification that means the same thing in every country, while keeping each country's own names as detail.

---

## 2. The design in one picture

Every document is described by **four country-neutral answers**, plus **local details**:

```
                    ┌─────────────────────────── country-neutral (same lists everywhere) ─────────────┐
 document  ───────► │ doc_type      what kind is it?          LAW · REGULATION · TECHNICAL_STANDARD … │
                    │ doc_role      what does it do?          BASE · AMENDMENT · EXTENSION · REPEAL … │
                    │ status        is it final?              draft · final · superseded · withdrawn  │
                    │ legal_force   must anyone comply?       MANDATORY · VOLUNTARY · INFORMATIVE …   │
                    └──────────────────────────────────────────────────────────────────────────────────┘
                    ┌─────────────────────────── local (per country, kept as detail) ─────────────────┐
                    │ country · issuer · local_type (official local name) · local_class (old doc_class)│
                    │ series · number · year · canonical_id                                            │
                    └──────────────────────────────────────────────────────────────────────────────────┘
```

**Example:** S.O. 3896(E) of 2022 (moves the wheel-rim deadline):

| Field | Value |
|---|---|
| `doc_type` | `REGULATION` |
| `doc_role` | `EXTENSION` |
| `status` | `final` |
| `legal_force` | `MANDATORY` |
| `country` · `issuer` · `local_type` | `IN` · `MoRTH` · `S.O.` |
| `local_class` | `NOTIFICATION_EXTENSION` (today's `doc_class`, unchanged) |

---

## 3. The four dimensions

### 3.1 `doc_type`: what kind of document is it?

| `doc_type` | Meaning | India | Thailand | Malaysia |
|---|---|---|---|---|
| `LAW` | Primary legislation passed by parliament | Motor Vehicles Act 1988 | Land Transport Act B.E. 2522, Motor Vehicle Act B.E. 2522 (พระราชบัญญัติ, พ.ร.บ.) | Road Transport Act 1987 (Act 333) |
| `REGULATION` | A binding instrument made under a law: rules, regulations, notifications, orders, decrees | CMVR 1989; G.S.R. and S.O. notifications | Royal Decree (พระราชกฤษฎีกา); Ministerial Regulation (กฎกระทรวง); ministry, DLT and TISI notifications (ประกาศ) | Motor Vehicles (Construction and Use) Rules 1959; P.U.(A) and P.U.(B) items; orders (Perintah) |
| `TECHNICAL_STANDARD` | A technical specification with test methods | AIS (ARAI), IS (BIS) | TIS (มอก.) | MS (Malaysian Standard) |
| `PROCEDURE` | How type approval, certification or testing is carried out | TAP 115/116 | DLT and TISI certification procedures | JPJ vehicle type approval (VTA) procedures |
| `GUIDANCE` | Circulars, guidelines, advisories, manuals, interpretations | Office Memoranda, circulars, advisories | Circulars (หนังสือเวียน), guidelines (แนวทาง), manuals (คู่มือ) | Circulars (Pekeliling), guidelines (Garis Panduan) |
| `REFERENCE` | Supporting material that is not itself a rule | Parivahan forms, ARAI approved lists, BIS catalogue, reports | TISI news, forms | JPJ forms, reports |
| `OFF_TOPIC` | Not about vehicle regulation (kept, but excluded) | | | |
| `UNKNOWN` | Could not be decided | | | |

**International standards.** UN Regulations (UN R xx) are `TECHNICAL_STANDARD` with issuer `UNECE`. Thailand and Malaysia adopt many of them, so they are worth storing once and linking from each country (see decision D5).

**`sub_type` (optional, free list).** A finer label inside a type, used mainly for `REFERENCE` and `GUIDANCE`: `FORM`, `LIST`, `CATALOGUE`, `REPORT`, `NEWS`, `CIRCULAR`, `GUIDELINE`, `MANUAL`.

### 3.2 `doc_role`: what does it do?

| `doc_role` | Meaning | Typical wording (IN · TH · MY) |
|---|---|---|
| `BASE` | Stands on its own (a new standard, a new set of rules) | |
| `AMENDMENT` | Changes another document | "further amendments" · แก้ไขเพิ่มเติม · (Pindaan) |
| `CORRIGENDUM` | Corrects an error in another document | "corrigendum" · แก้คำผิด · pembetulan |
| `EXTENSION` | Moves a date or period in another document | "shall be substituted" (dates), "extend" · ขยายระยะเวลา · lanjutan tempoh |
| `EXEMPTION` | Exempts someone from another document | "hereby exempts" · ยกเว้น · pengecualian |
| `REPEAL` | Cancels another document | "hereby rescinds", "omitted" · ยกเลิก · pembatalan |
| `CONSOLIDATION` | A combined text of a document with its amendments | consolidated CMVR | | |
| `ANNEX` | A table, form or annex that belongs to another document | AIS-007 tables | | |
| `INTERPRETATION` | Explains how to read another document | AIS interpretation manuals | | |

`doc_role` is decided from the text at classification (Step 5) and confirmed at linking (Step 7): a notification found to amend another document becomes `AMENDMENT` even if the wording was not caught earlier.

### 3.3 `status`: is it final?

Unchanged from today: `draft`, `final`, `superseded`, `withdrawn`.

Draft wording: "objections and suggestions … thirty days" (IN) · ร่าง (TH) · Draf, "cadangan" (MY).

### 3.4 `legal_force`: must anyone comply?

| `legal_force` | Meaning |
|---|---|
| `MANDATORY` | Binding on manufacturers, owners or authorities |
| `VOLUNTARY` | Exists, but only binding if another document makes it so |
| `INFORMATIVE` | Never binding (guidance, news, drafts, reports) |
| `UNKNOWN` | Not yet decided |

This matters most for standards, and it works the same way in all three countries:

| Country | A standard becomes mandatory when… |
|---|---|
| India | a CMVR rule or S.O. 1365(E) table row requires it (we already store this as a `mandate`) |
| Thailand | a Ministerial Regulation declares the TIS mandatory |
| Malaysia | a rule or JPJ requirement refers to the MS or UN R |

**Rule (same for every country):**
- `LAW` and final `REGULATION` → `MANDATORY`.
- Any `draft` → `INFORMATIVE`.
- `GUIDANCE`, `REFERENCE` → `INFORMATIVE`.
- `TECHNICAL_STANDARD` and `PROCEDURE` → `VOLUNTARY` by default, and `MANDATORY` while an open `mandate` refers to them.

It is set in Step 7 (Link), where mandates are built.

---

## 4. Local details

| Field | Meaning | IN | TH | MY |
|---|---|---|---|---|
| `country` | Already exists (migration 0005) | `IN` | `TH` | `MY` |
| `issuer` | Who issued it | MoRTH, AISC/ARAI, BIS | DLT, TISI, Ministry of Industry, Royal Gazette | JPJ, MITI, Department of Standards Malaysia |
| `local_type` | The official name of the instrument, as the country writes it | `G.S.R.`, `S.O.`, `AIS` | `กฎกระทรวง`, `ประกาศ`, `มอก.` | `P.U.(A)`, `P.U.(B)`, `Akta`, `MS` |
| `local_class` | The detailed per-country class: today's `doc_class` | `NOTIFICATION_EXTENSION` | `MINISTERIAL_REGULATION` | (to define) |
| `series`, `number`, `year` | As today. **`year` is always the Gregorian (CE) year** | | B.E. year − 543 (`country.year_offset`) | |

---

## 5. Mapping of the existing classes

### 5.1 India: all 28 current `doc_class` values

Every value maps without losing information. `*` = decided by the text and confirmed in Step 7: `AMENDMENT` if the document amends another one, otherwise `BASE`.

| Current `doc_class` | `doc_type` | `doc_role` | `status` | `sub_type` / note |
|---|---|---|---|---|
| `AIS_STANDARD` | `TECHNICAL_STANDARD` | `BASE` | final | |
| `AIS_AMENDMENT` | `TECHNICAL_STANDARD` | `AMENDMENT` | final | |
| `AIS_CORRIGENDUM` | `TECHNICAL_STANDARD` | `CORRIGENDUM` | final | |
| `AIS_DRAFT` | `TECHNICAL_STANDARD` | `BASE`* | draft | |
| `AIS_FORM_TABLE` | `TECHNICAL_STANDARD` | `ANNEX` | final | AIS-007 tables |
| `AIS_INTERPRETATION` | `GUIDANCE` | `INTERPRETATION` | final | `MANUAL` |
| `SAFETY_STANDARD_LEGACY` | `TECHNICAL_STANDARD` | `BASE` | final | old IS safety standards |
| `TAP_DOCUMENT` | `PROCEDURE` | `BASE` | final | |
| `TAP_AMENDMENT` | `PROCEDURE` | `AMENDMENT` | final | |
| `NOTIFICATION_DRAFT` | `REGULATION` | `AMENDMENT`* | draft | |
| `NOTIFICATION_FINAL` | `REGULATION` | `AMENDMENT`* | final | |
| `NOTIFICATION_ORDER` | `REGULATION` | `AMENDMENT`* | final | `local_type` = S.O. |
| `NOTIFICATION_CORRIGENDUM` | `REGULATION` | `CORRIGENDUM` | final | |
| `NOTIFICATION_EXEMPTION` | `REGULATION` | `EXEMPTION` | final | |
| `NOTIFICATION_EXTENSION` | `REGULATION` | `EXTENSION` | final | |
| `CIRCULAR_OM` | `GUIDANCE` | `BASE` | final | `CIRCULAR` |
| `GUIDELINE_POLICY` | `GUIDANCE` | `BASE` | final | `GUIDELINE` |
| `ACT` | `LAW` | `BASE`* | final | an "(Amendment) Act" → `AMENDMENT` |
| `CONSOLIDATED_RULES` | `REGULATION` | `CONSOLIDATION` | final | |
| `BIS_REGULATION` | `REGULATION` | `BASE` | final | issuer BIS |
| `BIS_CATALOGUE` | `REFERENCE` | `BASE` | final | `CATALOGUE` |
| `ENERGY_STANDARD` | `REGULATION` | `BASE`* | final | BEE standards are notified under the Energy Conservation Act |
| `FUEL_ORDER` | `REGULATION` | `BASE`* | final | issuer MoPNG |
| `APPROVED_LIST` | `REFERENCE` | `BASE` | final | `LIST` |
| `FORM_TEMPLATE` | `REFERENCE` | `BASE` | final | `FORM` |
| `REPORT` | `REFERENCE` | `BASE` | final | `REPORT` |
| `OFF_TOPIC` | `OFF_TOPIC` | — | — | |
| `OTHER` | `UNKNOWN` | — | — | |

### 5.2 Thailand: the 5 classes added on branch `multi-country`

| `local_class` | `doc_type` | `doc_role` | note |
|---|---|---|---|
| `TIS_STANDARD` | `TECHNICAL_STANDARD` | from text | `legal_force` from the Ministerial Regulation that makes it mandatory |
| `MINISTERIAL_REGULATION` | `REGULATION` | from text | กฎกระทรวง |
| `DLT_NOTIFICATION` | `REGULATION` | from text | ประกาศกรมการขนส่งทางบก |
| `GAZETTE_NOTICE` | `REGULATION` | from text | a Royal Gazette item. Its `doc_type` is decided from the content, since the Gazette publishes several kinds |
| `NEWS` | `REFERENCE` | `BASE` | `NEWS` |

### 5.3 Malaysia: proposed `local_class` values (new)

| Proposed `local_class` | `doc_type` | note |
|---|---|---|
| `MY_ACT` | `LAW` | e.g. Act 333 and its amendment Acts |
| `MY_SUBSIDIARY_LEGISLATION` | `REGULATION` | P.U.(A): rules, regulations, orders |
| `MY_GAZETTE_NOTICE` | `REGULATION` | P.U.(B) notices |
| `MS_STANDARD` | `TECHNICAL_STANDARD` | Malaysian Standards |
| `JPJ_CIRCULAR` | `GUIDANCE` | Pekeliling |
| `JPJ_GUIDELINE` | `GUIDANCE` / `PROCEDURE` | VTA guidelines are `PROCEDURE` |

---

## 6. How the classifier works

### 6.1 Two layers

```
 page text + sightings
        │
        ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Country profile (rules), one module per country            │
 │   identity: how numbers and years are written              │
 │   clues:    words that mean LAW / REGULATION / AMENDMENT…  │
 │   issuers:  ministries and agencies                         │
 │   language: which pages to read (IN: English, TH: Thai…)   │
 │ → doc_type, doc_role, status, issuer, local_type,          │
 │   local_class, canonical_id                                 │
 └──────────────────────────┬─────────────────────────────────┘
                            │ doc_type still UNKNOWN
                            ▼
 ┌────────────────────────────────────────────────────────────┐
 │ Qwen fallback: one country-neutral prompt                  │
 │   "Country: TH. Language: Thai. Allowed doc_type: …"       │
 │   answers with the universal lists only                     │
 └──────────────────────────┬─────────────────────────────────┘
                            ▼
 Step 7 (Link): doc_role confirmed from relations; legal_force from mandates
```

**What stays the same for every country:**
- the four answer lists (§3),
- the order "rules first, Qwen last",
- identity is taken from the content, never from a website title,
- the Qwen call shape (`with_structured_output`, temperature 0, CLAUDE.md rule 8).

**What each country provides:** a profile with its identity parsers, clue words, issuers and language.

**India:**
- **Classification is unchanged.** The existing `classify()` keeps producing `local_class`.
- A mapping table (§5.1) fills the new fields.
- India's results must not change; the regression numbers in `CLAUDE.md` still apply.

### 6.2 Clue words (Thailand and Malaysia)

These are the starting clues. **Every one must be checked against real documents** once the crawlers exist, and kept in the profile's tests.

**Thailand (Thai text):**

| Clue | Means |
|---|---|
| พระราชบัญญัติ / พ.ร.บ. | `LAW` |
| พระราชกฤษฎีกา | `REGULATION` (Royal Decree) |
| กฎกระทรวง | `REGULATION` (Ministerial Regulation) |
| ประกาศกระทรวง… / ประกาศกรมการขนส่งทางบก / ประกาศสำนักงานมาตรฐานผลิตภัณฑ์อุตสาหกรรม | `REGULATION` (notification) |
| มอก. / มาตรฐานผลิตภัณฑ์อุตสาหกรรม | `TECHNICAL_STANDARD` (TIS) |
| หนังสือเวียน · แนวทาง · คู่มือ | `GUIDANCE` |
| แบบฟอร์ม · ข่าว / ข่าวประชาสัมพันธ์ | `REFERENCE` (form, news) |
| แก้ไขเพิ่มเติม | `AMENDMENT` |
| ยกเลิก | `REPEAL` |
| ยกเว้น | `EXEMPTION` |
| ขยายระยะเวลา | `EXTENSION` |
| ร่าง | `draft` |
| พ.ศ. 2565 | year 2565 B.E. = 2022 CE (`country.year_offset` = 543) |
| ราชกิจจานุเบกษา เล่ม … ตอน … หน้า … | Royal Gazette citation: volume, section, page |

**Malaysia (Malay and English, often both in one document):**

| Clue | Means |
|---|---|
| Akta … (Act …) | `LAW` |
| Peraturan-Peraturan / Kaedah-Kaedah (Regulations / Rules) | `REGULATION` |
| Perintah (Order) | `REGULATION` |
| P.U.(A) n/yyyy | `REGULATION` (subsidiary legislation) |
| P.U.(B) n/yyyy | `REGULATION` (gazette notice) |
| Warta Kerajaan Persekutuan | Federal Government Gazette |
| Standard Malaysia / MS nnnn:yyyy | `TECHNICAL_STANDARD` |
| Pekeliling · Garis Panduan | `GUIDANCE` |
| (Pindaan) / Amendment | `AMENDMENT` |
| Pembatalan / Revocation | `REPEAL` |
| Pengecualian / Exemption | `EXEMPTION` |
| Draf / Draft | `draft` |

### 6.3 Identity (`canonical_id`) per country

`canonical_id` is unique across the whole database, so each country needs a format that cannot collide with another's.

| Country | Kind | Proposed format | Example |
|---|---|---|---|
| IN | all | unchanged (CLAUDE.md) | `GSR-659(E)-2022`, `AIS-038(Rev.2)/Amd.4` |
| TH | TIS standard | `TIS-<number>-<B.E. year>` (as cited in Thailand) | `TIS-2560-2565` |
| TH | Royal Gazette item | `TH-RG-<volume>-<section>-<page>` | `TH-RG-139-77ก-12` |
| TH | Ministerial Regulation without a Gazette citation | `TH-MR-<ministry>-<issue no>-<B.E. year>` | `TH-MR-MOI-3-2565` |
| MY | Act | `MY-ACT-<number>` | `MY-ACT-333` |
| MY | P.U.(A) / P.U.(B) | `PUA-<n>-<yyyy>` / `PUB-<n>-<yyyy>` | `PUA-123-2022` |
| MY | Malaysian Standard | `MS-<number>:<yyyy>` | `MS-1234:2020` |
| any | UN Regulation | `UNR-<nn>[(<series>)]` | `UNR-13H` |

Thai IDs keep the B.E. year because that is how Thai documents cite each other; the `year` column always holds the CE year for filters (decision D3).

---

## 7. What would change (when this is accepted)

**Database:** a new migration, `0006`. It needs your explicit OK, and it does not edit 0001–0005.
- `document`: add `doc_type`, `doc_role`, `legal_force`, `sub_type`, `local_type`, each with a `CHECK` on its list, plus an index on `(country, doc_type)`.
- `chunk`: add `doc_type` (a filter copy, like `doc_class` today).
- `country`: add `('MY', 'Malaysia', 0, 'ms')`, if Malaysia is added now (decision D4).
- Fill the new columns for existing India rows from table §5.1. This writes to existing rows; it is derived data only, and repeatable.

**Code:**
- `regtrack/models/enums.py`: new enums `DocType`, `DocRole`, `LegalForce`; `DocClass` stays, as the local class list.
- `regtrack/pipeline/classify.py`: India keeps its rules, plus the mapping to the new fields.
- `regtrack/pipeline/countries/` (new): one profile per country (`th.py`, `my.py`), and later India's rules moved into `in_.py`.
- `regtrack/pipeline/link.py`: confirm `doc_role`, set `legal_force`.
- `regtrack/api/`: filters on `doc_type` / `doc_role` / `legal_force` (keeping `doc_class` filters for India).

**Documents:** `docs/DB_DESIGN.md` §3 gets the new lists; this file becomes the reference for classification.

**Tests:**
- every India `doc_class` maps to valid new values;
- India's counts and regression numbers are unchanged;
- each country profile has fixtures of real documents, one per `doc_type` and per `doc_role`;
- the Qwen fallback only returns allowed values.

**Portal (later, screen by screen):** the register uses `doc_type IN (LAW, REGULATION, TECHNICAL_STANDARD, PROCEDURE)` instead of today's list of Indian reference classes; country filter and labels.

---

## 8. Rollout

| Step | What | Changes India's results? |
|---|---|---|
| 1 | Agree this design (decisions below) | no |
| 2 | Migration 0006 + enums + India mapping + tests | no (new columns only) |
| 3 | `legal_force` from mandates in Step 7 | no (new column only) |
| 4 | Thailand profile + crawlers, tested on real Thai documents | no (Thai rows only) |
| 5 | Malaysia: country row, sources, profile, crawlers | no |
| 6 | Portal and API move to the new fields | screens only |

---

## 9. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | Accept the four dimensions (`doc_type`, `doc_role`, `status`, `legal_force`) and the 8 `doc_type` values? | Yes |
| D2 | Keep today's `doc_class` as the per-country `local_class`, or replace it? | Keep it: India's pipeline, portal and tests keep working unchanged |
| D3 | Thai `canonical_id` with the B.E. year (`TIS-2560-2565`) or the CE year (`TIS-2560-2022`)? | B.E. year in the ID (as Thai documents cite it); CE year in the `year` column |
| D4 | Add Malaysia as a country now (migration 0006) or later? | Add the `country` row now (cheap); sources and crawlers later |
| D5 | Store UN Regulations once, as their own country `UN`, and link to them from IN/TH/MY? | Yes, but in a later step |
| D6 | Is `ENERGY_STANDARD` (BEE) a `REGULATION` or a `TECHNICAL_STANDARD`? | `REGULATION` (it is notified under the Energy Conservation Act) |

**Known open point:** the Thai and Malay clue words in §6.2 are a starting list from general knowledge of these legal systems. They have not yet been tested on real Thai or Malaysian files.
