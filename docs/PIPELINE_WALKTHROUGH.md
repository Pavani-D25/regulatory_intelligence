# RegTrack pipeline walk-through: see every step yourself

This guide follows **one real document** through the whole system, from the government website to the portal. For every step it explains:

- **In simple words**: what the step does
- **What happens**: the details, in order
- **Where it happens**: file and line, so you can open the code in VS Code
- **Try it yourself**: commands to run
- **What to look for**: what the results mean
- **How it goes to the next step**

**The example document:** **S.O. 3896(E) of 12 August 2022**, a 2-page MoRTH notice that moved the deadline for vehicle wheel rims. In the database it is `document` id **754**, stored in `file_object` id **1012**.

Most "Try it yourself" commands only **read**. The ones that change something (running a crawl) are marked.

Line numbers refer to branch `multi-country` (October 2026).

---

## Contents

- [Before you start: tools](#before-you-start-tools)
- [The 10 steps at a glance](#the-10-steps-at-a-glance)
- [Step 1: Sources](#step-1-sources-how-does-regtrack-know-which-websites-to-read)
- [Step 2: Crawl](#step-2-crawl-reading-a-websites-list)
- [What is the "seed"?](#what-is-the-seed)
- [Step 3: Store](#step-3-store-saving-the-downloaded-file)
- [Step 4: Text](#step-4-text-reading-the-words-on-each-page)
- [Step 5: Classify](#step-5-classify-what-is-this-document)
- [Step 6: Extract](#step-6-extract-filling-in-the-details)
- [Step 7: Link](#step-7-link-connecting-documents-and-keeping-the-history-of-rules)
- [Step 8: Chunk & embed](#step-8-chunk--embed-preparing-the-text-for-search)
- [Step 9: After the run](#step-9-after-the-run-the-clean-up-round)
- [Step 10: Portal & API](#step-10-portal--api-reading-the-results)
- [Cheat sheet](#cheat-sheet)

---

## Before you start: tools

### The database console (psql)

The database runs on this machine (`D:\pgsql`, README "Database"). Its console program, **psql**, is in `D:\pgsql\Library\bin`.

1. In VS Code: **Terminal → New Terminal** (`` Ctrl+Shift+` ``).
2. Run:

   ```powershell
   D:\pgsql\Library\bin\psql.exe -h localhost -U regtrack -d regtrack
   ```

3. The prompt becomes `regtrack=#`. Type `\x auto` once, so wide rows are easier to read.

Tips:

- Every SQL query ends with `;`. If you forget it, the prompt becomes `regtrack-#`; type `;` and press Enter.
- Long results: **Space** scrolls, **q** returns to the prompt.
- `\q` leaves the console.

If you prefer a window with clickable tables, use **DBeaver**, **pgAdmin** or the VS Code **PostgreSQL** extension. Connect with host `localhost`, port `5432`, database `regtrack`, user `regtrack`, password `regtrack`.

### The Python console

Some steps let you run the pipeline's own functions. They **only read**:

```powershell
cd D:\regulatory_intelligence
.venv\Scripts\python
```

The prompt becomes `>>>`. Type the lines one at a time. `exit()` leaves.

### Keep two terminals open

- **Terminal 1:** psql (for SQL).
- **Terminal 2:** PowerShell in `D:\regulatory_intelligence` (for commands and Python).

---

## The 10 steps at a glance

```
1 Sources → 2 Crawl → 3 Store → 4 Text → 5 Classify → 6 Extract → 7 Link → 8 Chunk/embed → 9 After the run → 10 Portal
```

| Step | What it does | Main table it writes |
|---|---|---|
| 1 Sources | Knows which websites exist and when to read them | `source` (read) |
| 2 Crawl | Reads each website's list, decides what is new | `crawl_run`, `file_sighting` |
| 3 Store | Saves new files once, named by fingerprint | `file_object` (stage `downloaded`) |
| 4 Text | Reads the words on every page | `file_object` (stage `text`) + `data\text\` |
| 5 Classify | Finds the document's number and type | `document`, `document_file` (stage `classified`) |
| 6 Extract | Fills in the details | `document.data`, `document.extraction` (stage `parsed`) |
| 7 Link | Connects documents, builds rule history | `doc_relation`, `mandate` (stage `linked`) |
| 8 Chunk & embed | Cuts text into pieces for search | `chunk` (stage `chunked` → `done`) |
| 9 After the run | Clean-up, Qwen catch-up, "what's new" events | `change_event`, `quality_flag` |
| 10 Portal & API | Shows the results | (reads only) |

### The queue between steps 4 and 8

There is no separate queue system. The column **`file_object.stage`** *is* the queue:

```
downloaded → text → classified → parsed → linked → chunked → embedded → done     (or failed)
```

Each step picks the files sitting at its input stage, works on each one in its own transaction, and writes the next stage. If a file fails, its stage stays the same and `stage_error` gets the reason, so the next run tries again.

- Code: `regtrack/pipeline/runner.py:25-26` (the stage order), `:29` (`_files`, the query that picks work), `:55` (`run_stage`), `:112` (`run_pipeline`).
- See the queue right now:

  ```sql
  SELECT stage, count(*), count(*) FILTER (WHERE stage_error IS NOT NULL) AS with_error
  FROM file_object WHERE country = 'IN' GROUP BY 1 ORDER BY 1;
  ```

---

## Step 1: Sources. How does RegTrack know which websites to read?

### In simple words

RegTrack has no hard-coded list of URLs. It has a table, **`source`**, with **one row per website**. A website is crawled only if it also has a **Python crawler** for it.

### What happens

Each `source` row has:

| Column | Meaning |
|---|---|
| `code` | The short name, for example `MORTH_API`. Everything else uses this key. |
| `name`, `base_url` | A human-readable name and the website address |
| `schedule_hours` | How often to crawl. `0` means never automatically. |
| `country` | `IN` or `TH`. Only the current country's sources are used. |
| `last_run_at`, `last_status` | Last crawl time and result (`ok`, `partial`, `failed`) |

The code → crawler mapping:

```
MORTH_API → regtrack/sources/morth.py
ARAI_AIS  → regtrack/sources/arai.py
EGAZETTE  → regtrack/sources/egazette.py
INDIACODE → regtrack/sources/indiacode.py
```

A website is crawled only when it is (1) a row in `source`, (2) in the current country, (3) has `schedule_hours > 0`, and (4) has a crawler module.

**Three ways a crawl starts:**

1. **The scheduler**: `python -m regtrack.cli schedule`. It keeps running and starts each crawl every `min(schedule_hours, 6)` hours, then runs the pipeline. It also runs a catch-up pipeline every hour and writes a "heartbeat" every 5 minutes.
2. **By hand**: `python -m regtrack.cli crawl MORTH_API`.
3. **The portal**: Admin page → Sync.

### Where it happens

| What | File : line |
|---|---|
| The 6 India source rows are created | `db/seeds/0001_vocab.sql:49` |
| The 8 Thailand rows are created | `db/migrations/0005_country_thailand.sql:25` |
| Code → crawler mapping | `regtrack/scheduler.py:25` (`CRAWLERS_BY_COUNTRY`) |
| Calls the crawler's `crawl()` | `regtrack/scheduler.py:38` (`crawl_source`) |
| Crawl, then pipeline | `regtrack/scheduler.py:61` (`run_source`) |
| Scheduler loop and timers | `regtrack/scheduler.py:85` (`main`) |
| Manual crawl command | `regtrack/cli.py:105` (`cmd_crawl`) |
| Portal Sync button | `regtrack/api/portal.py:831` (`run_sync`) |
| Each crawler | `regtrack/sources/morth.py:85`, `arai.py:103`, `egazette.py:159`, `indiacode.py:63` |

### Try it yourself

```sql
-- A. all sources
SELECT id, code, country, schedule_hours, last_run_at, last_status, base_url
FROM source ORDER BY id;

-- B. the last crawls
SELECT r.id, so.code, r.started_at, r.status,
       r.stats->>'seen' AS seen, r.stats->>'known' AS known, r.stats->>'new_files' AS new
FROM crawl_run r JOIN source so ON so.id = r.source_id
ORDER BY r.id DESC LIMIT 10;

-- C. is the scheduler running?
SELECT key, value FROM app_setting;
```

Then open `regtrack/scheduler.py` and read lines 25–45 and 85–100.

### What to look for

- **14 sources:** 6 India, 8 Thailand. The Thai ones have `schedule_hours = 0` and no crawler, so they never run.
- **`ARAI_TAP` and `LOCAL_SEED`** are India sources without a crawler. `LOCAL_SEED` is the one-time import of your old folder (see [the seed](#what-is-the-seed)).
- **`INDIACODE`** says 24 hours, but the timer is `min(24, 6)`, so it runs every 6 hours too.
- **`scheduler_heartbeat`** is the last time the scheduler said "I'm alive". If it is old, the scheduler is not running, and nothing is crawled automatically.
- **`auto_sync = true`** allows scheduled crawls. `false` makes the scheduler skip them; manual crawls still work.

---

## Step 2: Crawl. Reading a website's list

### In simple words

A crawler does **not** search the web. It reads **one list** the website publishes, and asks one question per row: *"Have I seen this row before?"*

### What happens (MoRTH as the example)

**2a. Ask for the list.** MoRTH has a public JSON API. The crawler calls it for 3 lists (`gazettes-notifications`, `orders-and-notices`, `guidelines`), 100 rows per page, until a page brings nothing new.

**2b. Filter.** `keep()` drops highway material (NH declarations, tolls, land acquisition). It keeps a row when its group is "Motor Vehicle Legislation", its wing is Road Transport / Road Safety, or its title mentions G.S.R., S.O., vehicle, licence, emission and similar words.

**2c. Turn each row into a `Listing`:**

- `item_id`: the row's stable key. For MoRTH: `list name : file path`.
- `url`: the download link, `https://morth.gov.in/backend/` + the file path.
- `title` and `listing_date`: what the website **claims**. They are kept, but never trusted for identity.
- `raw`: the whole original row.

**2d. Decide per row**, each in its own transaction, so one bad row never stops the crawl:

| Case | Test | What it does | Counted as |
|---|---|---|---|
| **A. Known** | a `file_sighting` with the same source + `item_id` exists | updates `last_seen_at` (at most once per 20 h). **No download.** | `known` |
| **B. In the seed import** | same title and date in the seed's download log | adds a sighting pointing to the existing file. **No download.** | `known` |
| **C. New** | neither | downloads the file → Step 3 | `new_listings`, `new_files` |

If a download fails (HTTP 404, or under 200 bytes), it counts under `errors` and **no sighting is written**, so the next crawl tries again.

**2e. Politeness.** Every request goes through `http.get()`, which:

- waits 1–2 seconds between requests to the same website,
- retries up to 6 times, waiting longer each time, on HTTP 429 or 5xx,
- sends the User-Agent `RegTrackIndia/0.1 (research)`.

ARAI's list is read by opening the public page in a real browser (Playwright). The bearer token on that page is never used.

**2f. Bookkeeping.** A `crawl_run` row is created at the start (`running`). At the end it gets the counts, status and error notes, and `source.last_run_at` / `last_status` are updated. After a complete pass, `mark_gone()` marks rows the website no longer shows (`gone_at`).

### Where it happens

| What | File : line |
|---|---|
| API address and the 3 lists | `regtrack/sources/morth.py:22-23` |
| The filter | `regtrack/sources/morth.py:24-43` (`keep`) |
| Paging through the API | `regtrack/sources/morth.py:52` (`iter_listings`) |
| Row → `Listing` | `regtrack/sources/morth.py:72` (`to_listing`) |
| Crawl loop | `regtrack/sources/morth.py:85` (`crawl`) |
| The `Listing` structure | `regtrack/sources/common.py:23` |
| Opens / closes the `crawl_run` | `regtrack/sources/common.py:53` (`start_run`), `:60` (`finish_run`) |
| Decides A / B / C | `regtrack/sources/common.py:93` (A at 97, B at 109, C's download at 128) |
| Marks rows that disappeared | `regtrack/sources/common.py:159` (`mark_gone`) |
| Polite requests | `regtrack/sources/http.py:24` (`_pace`), `:52` (`get`) |

### Try it yourself

**A. See the raw list in your browser** (5 rows):

```
https://morth.gov.in/backend/api/gazettes-notifications?page=1&per_page=5&wings=&order_by=desc&search=
```

Look at `page` → `files` (groups) → `files_data` (rows): `title`, `file`, `published_date`, `wings_division`, and the group's `name`. Put `https://morth.gov.in/backend/` before a `file` value and open it; that's the PDF.

**B. Count before the crawl:**

```sql
SELECT (SELECT count(*) FROM file_sighting) AS sightings,
       (SELECT count(*) FROM file_object)   AS files;
```

**C. Run a crawl.** ⚠ This writes to the database, which is normal operation. In Terminal 2:

```powershell
.venv\Scripts\python -m regtrack.cli crawl MORTH_API --no-process
```

`--no-process` crawls only, without running the pipeline, so a new file stops at stage `downloaded`, where you can follow it. It takes about 15–30 seconds.

**D. The run it recorded:**

```sql
SELECT id, status, started_at, finished_at, stats, log
FROM crawl_run ORDER BY id DESC LIMIT 1;
```

**E. Count again** (query B) and compare.

**F. Case A happening** (known rows refreshed):

```sql
SELECT count(*) AS refreshed_just_now
FROM file_sighting s JOIN source so ON so.id = s.source_id
WHERE so.code = 'MORTH_API' AND s.last_seen_at > now() - interval '10 minutes';
```

**G. One row as the database stores it:**

```sql
SELECT source_item_id, source_url, listing_title, listing_date, listing_category,
       jsonb_pretty(listing_raw) AS raw, seen_at, last_seen_at
FROM file_sighting WHERE id = 8912;
```

### What to look for

- **D:** `seen` ≈ 1,160, `known` ≈ 1,155, `errors` = 5. The `log` lists 5 links MoRTH shows but answers with HTTP 404, which is why the status is `partial`.
- **E:** most likely no new sightings or files. Everything is already in the database. That's the normal case.
- **F:** a large number if the last crawl was more than 20 hours ago. Run the crawl again right away and it won't grow (the 20-hour rule), so a crawl with no changes writes almost nothing.
- **G:** `source_item_id` starts with `gazettes-notifications:`. `raw` is the same row you saw in the browser, plus `matched_seed: true`: this row was case B on its first crawl.

### How it goes to the next step

For a new row (case C), the downloaded bytes go straight to Step 3, inside the same function.

---

## What is the "seed"?

### In simple words

**The seed is the starting collection.** Before RegTrack existed, about 2,274 regulation files had already been downloaded into `D:\Regulatory_Documents`. RegTrack copied that folder into its database **once**, so it didn't start empty. In the database it appears as the source **`LOCAL_SEED`**.

- **Seed** = the files you already had, loaded once at the start.
- **Crawl** = checking the websites for anything new since then.

### What the import did

It was run once (7 Oct 2026, `crawl_run` id 1) with `python -m regtrack.cli import-seed`. Code: `regtrack/sources/seed_corpus.py:206` (`import_seed`).

1. Read every file in the folder (except `_logs` and `_review*`) and computed its fingerprint. **The folder is only read, never changed.**
2. Copied each file into storage, exactly as Step 3 does. 2,274 files gave **2,018 unique files** (256 were duplicates).
3. Created one `file_object` per unique file at stage `downloaded`.
4. Created a `LOCAL_SEED` sighting per file path (the folder name helps classification later).
5. Read the old download logs in `D:\Regulatory_Documents\_logs` (for example `morth_download_log.csv` → `MORTH_API`, mapping at `seed_corpus.py:109`). Each matched log row became an extra sighting under the real source, with the website's title and date.

### Why it matters

- **Step 2, case B:** without it, the first live crawl would have downloaded about 1,000 PDFs RegTrack already had.
- **Step 9:** "new document" events are written only for files first found by a **live** crawl, not the seed. Old material isn't news.
- **The regression numbers in `CLAUDE.md`** (2,274 / 2,016 files, 251 scans…) were measured on the seed.

### Try it yourself

```sql
-- the one seed run
SELECT id, started_at, status, jsonb_pretty(stats) FROM crawl_run WHERE id = 1;

-- what each source contributed
SELECT so.code,
       count(*) AS sightings,
       count(*) FILTER (WHERE s.source_item_id LIKE '%log.csv:%')      AS from_seed_logs,
       count(*) FILTER (WHERE s.listing_raw->>'matched_seed' = 'true') AS live_matched_to_seed,
       count(*) FILTER (WHERE s.crawl_run_id > 1)                      AS from_live_crawls
FROM file_sighting s JOIN source so ON so.id = s.source_id
GROUP BY 1 ORDER BY 2 DESC;

-- files found only by live crawls (never in the seed folder)
SELECT count(*) FROM file_object f
WHERE NOT EXISTS (SELECT 1 FROM file_sighting s JOIN source so ON so.id = s.source_id
                  WHERE s.file_id = f.id AND so.code = 'LOCAL_SEED');
```

You can open `D:\Regulatory_Documents\_logs\morth_download_log.csv` to look at the log rows. **Look only; don't save changes in that folder.**

---

## Step 3: Store. Saving the downloaded file

### In simple words

**When a new file is downloaded, RegTrack saves it in a folder under a special name, and writes one line in the database saying "I have this file".**

### The special name: the fingerprint

RegTrack computes a fingerprint of every file with **SHA-256**. It reads all the bytes and produces a 64-character code:

```
0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c
```

- **Same file → same code**, always.
- **Change one letter → a completely different code.**

This code is **the file's name**. The name on the website doesn't matter; the content decides the name.

### Where the file is saved

On your laptop, in **`D:\regulatory_intelligence\data\raw\`**. This comes from `.env`:

```
STORAGE_DIR=D:\regulatory_intelligence\data\raw
STORAGE_BACKEND=local
```

`local` means "save to this folder". MinIO / S3 is not used unless you set `STORAGE_BACKEND=s3`.

```
D:\regulatory_intelligence\data\raw\0d\0d470bd149c5…578c.pdf
                                    ↑↑  ↑
                     first 2 characters  full code as the file name
```

There are 256 sub-folders (`00` … `ff`), holding 2,144 files and about 3.2 GB. The files have no readable names; look them up in the database. `data\raw` is in `.gitignore`.

### What happens, in order

| # | What | Why |
|---|---|---|
| 1 | Check the first bytes: `%PDF-` is a PDF, `PK` is a .docx or zip, the OLE header is an old .doc | Websites often give wrong names |
| 2 | Compute the SHA-256 | It becomes the identity |
| 3 | Build the path `data\raw\<first 2>\<sha256>.<ext>` | 256 sub-folders keep folders small |
| 4 | **If that file exists, write nothing.** Otherwise write a temporary file, then move it into place. | **Write-once**: originals are never changed or deleted, and a crash never leaves half a file |
| 5 | Add a `file_object` row with stage `downloaded`, unless that fingerprint already has a row | **Same file = one row** |
| 6 | Add a `file_sighting` row: "source X listed it, with this title and date" | Every place it was seen is remembered |

**Two tables, two meanings:**

- `file_object` = **the file itself**. One row per fingerprint.
- `file_sighting` = **who listed it**. One row per website or folder.

Our example is **1 file** (`file_object` 1012) with **3 sightings**: the seed folder, the seed's MoRTH log, and the live MoRTH website.

### Where it happens

| What | File : line |
|---|---|
| Find the file type | `regtrack/sources/common.py:68` (`ext_from`) |
| Save the file | `regtrack/sources/common.py:139` (`put_bytes`) |
| Add the `file_object` row | `regtrack/sources/common.py:141` |
| Add the `file_sighting` row | `regtrack/sources/common.py:150` |
| Compute the fingerprint | `regtrack/storage.py:32` (`sha256_bytes`) |
| Build the path | `regtrack/storage.py:41` (`object_path`) |
| Write once, skip if it exists | `regtrack/storage.py:66` (`store_bytes`), `:83` (`_finalise`) |

### Try it yourself

**A. The file's row:**

```sql
SELECT id, sha256, ext, size_bytes, storage_path, stage, first_seen_at
FROM file_object WHERE id = 1012;
```

**B. Open it:**

```powershell
dir data\raw\0d\0d470bd1*
ii  data\raw\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.pdf
```

Or in File Explorer: `D:\regulatory_intelligence\data\raw\0d`.

**C. Let Windows compute the fingerprint**, and compare it with the name:

```powershell
Get-FileHash data\raw\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.pdf -Algorithm SHA256
```

**D. 1 file, 3 sightings:**

```sql
SELECT so.code, s.listing_title
FROM file_sighting s JOIN source so ON so.id = s.source_id
WHERE s.file_id = 1012;
```

**E. Files listed most often:**

```sql
SELECT f.id, count(*) AS times_listed, string_agg(DISTINCT so.code, ', ') AS listed_by
FROM file_object f
JOIN file_sighting s ON s.file_id = f.id
JOIN source so ON so.id = s.source_id
GROUP BY f.id ORDER BY times_listed DESC LIMIT 10;
```

**F. The rule that prevents duplicates:**

```sql
SELECT count(*) AS file_rows, count(DISTINCT sha256) AS unique_fingerprints FROM file_object;
\d file_object
```

In the `\d` output, find `"file_object_sha256_key" UNIQUE`.

### What to look for

- **A:** `storage_path` ends with the same code as `sha256`, inside folder `0d`.
- **C:** the hash Windows computes **is** the file name (shown in capitals).
- **D:** `LOCAL_SEED`, `MORTH_API`, `MORTH_API`.
- **E:** some files are listed 5+ times, yet each is one row and one file on disk.
- **F:** both counts are equal. There is never a duplicate file row.

### How it goes to the next step

The new row sits at **`stage = 'downloaded'`**, the label for "waiting for Step 4". Step 4 asks:

```sql
SELECT * FROM file_object WHERE stage = 'downloaded' AND country = 'IN' ORDER BY id;
```

If it returns 0 rows, the queue is empty: every file has already been processed.

---

## Step 4: Text. Reading the words on each page

### In simple words

A PDF is not plain text; the words must be **pulled out**. RegTrack:

1. Opens the stored file.
2. Takes out the text of every page.
3. Checks each page: **English, Hindi, or a scanned image?**
4. Saves the page text in a separate file, so later steps don't need the PDF again.

### What happens, in order

| # | What | Where |
|---|---|---|
| 1 | Picks files with `stage = 'downloaded'` | `runner.py:29` |
| 2 | Opens the stored PDF | `stages.py:44` (`stage_text`) |
| 3 | **Reads each page's text** with **PyMuPDF** (`page.get_text()`) and keeps the PDF's metadata | `text.py:86` (`read_pdf`) |
| 3b | Word, Excel, HTML and plain text have their own readers | `text.py:164` (`extract`) |
| 4 | **Checks each page** (rules below) | `text.py:40` (`analyse`) |
| 5 | **Saves the page text** to `data\text\` (each file is read only once) | `text.py:244` (`save_pages`), `:295` (`extract_cached`) |
| 6 | Scanned pages → **OCR** | `ocr.py:140` (`pick_engine`), `:150` (`ocr_page`), `stages.py:74` |
| 7 | Writes the results into `file_object`, sets **`stage = 'text'`** | `stages.py:44-70`, `dbutil.py:70` (`set_stage`) |

**How a page is checked:**

| The page has… | It is marked |
|---|---|
| fewer than **100 characters** | **empty** = scanned image → needs OCR |
| more Hindi letters (देवनागरी) than English letters | **hi** |
| patterns like `Hkkjr`, `vf/klwpuk` | **hi_legacy**: Hindi in the old Kruti Dev font, which looks like English rubbish |
| at least 5 English words | **en** |

Gazette notifications usually have Hindi first and English after; later steps read **only the English pages**.

**OCR** = reading text from a picture. RegTrack turns a scanned page into an image and uses Windows OCR, Tesseract or Qwen vision, whichever is available.

### Where the text is saved

Not in the database, but next to the originals:

```
data\text\0d\0d470bd1…578c.jsonl       ← text of every page (one line per page)
data\text\0d\0d470bd1…578c.meta.json   ← summary: pages, languages, scans
```

### Try it yourself

**A. Read the PDF the way the pipeline does** (Python console, read-only):

```python
from pathlib import Path
from regtrack.pipeline.text import extract
r = extract(Path(r"data\raw\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.pdf"), "pdf")
print(r.page_count, r.text_layer, r.scanned_pages)
for p in r.pages: print(p.page, p.lang, p.chars)
print(r.pages[1].text[:800])
exit()
```

**B. The saved text next to the PDF:**

```powershell
code data\text\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.jsonl
code data\text\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.meta.json
ii   data\raw\0d\0d470bd149c5359e6793e884463e266baed86e0bf44d22d24664d2bf09ab578c.pdf
```

**C. What Step 4 wrote in the database:**

```sql
SELECT id, page_count, text_layer, scanned_pages, ocr_engine, jsonb_pretty(language_mix), stage
FROM file_object WHERE id = 1012;
```

**D. A scanned file, for comparison:**

```sql
SELECT id, page_count, cardinality(scanned_pages) AS scanned, ocr_engine, ocr_confidence, sha256
FROM file_object WHERE text_layer = false ORDER BY page_count LIMIT 5;
```

Open one of them from `data\raw\<first 2>\<sha256>.pdf` and its `.jsonl` from `data\text\…`.

### What to look for

- **A:** `2 True []`, then `1 hi …` and `2 en …`: page 1 Hindi, page 2 English. The text starts with "THE GAZETTE OF INDIA" and later "S.O. 3896(E). —In exercise of the powers…".
- **B:** 2 lines in the `.jsonl`, each with `page`, `text`, `lang`. Some Hindi words look odd (रािमागग instead of राजमार्ग). That's how the PDF stores its font, and it doesn't matter, because later steps use English.
- **C:** `english_range: [2, 2]` tells later steps where the English is.
- **D:** `ocr_engine` is filled and `ocr_confidence` shows how sure the OCR was. Below 0.6 a `low_ocr_confidence` warning is raised.

### How it goes to the next step

The file gets **`stage = 'text'`**. Exception: a **scanned file not OCR'd yet waits at `text`** (`ready_for_classify`, `stages.py:127`).

---

## Step 5: Classify. What is this document?

### In simple words

RegTrack reads the words and decides:

1. **Who is it?** Its official number, for example `SO-3896(E)-2022`.
2. **What kind is it?** A final notification, a draft, an AIS standard, an extension…
3. **Which pages hold it?** One file can hold several documents.

Then it creates a **`document`** row. Up to now everything was about *files*; from here on it's about *documents*.

### The most important rule: trust the content, not the website

The website's title is only a **claim**. A real example from the database:

| | |
|---|---|
| India Code's title said | "17th amendment **GSR 954(E)** 04.10.2016" |
| The PDF actually says | **G.S.R. 953(E)** |
| RegTrack stored | `GSR-953(E)-2016`, and raised a `title_file_mismatch` warning |

**The year is part of the number**, because numbers repeat every year: `GSR-659(E)-2022` ≠ `GSR-659(E)-2019`.

### What happens, in order

| # | What | Where |
|---|---|---|
| 1 | Picks files with `stage = 'text'` (scans wait for OCR) | `runner.py`; `stages.py:127` |
| 2 | Collects page text **plus all sightings** (titles, folder names) | `stages.py:98` (`file_ctx`) |
| 3 | **Finds the number** in the English heading (`S.O. 3896(E). —In exercise of the powers…`) and the date (`New Delhi, the 12th August, 2022`) | `identity.py:126` (`notification_identity`) |
| 3b | AIS standards: code, part, revision from the cover | `identity.py:180` (`ais_identity`) |
| 4 | **Decides the type** with fixed rules, in order (folder rules, AIS, off-topic, notifications…) | `classify.py:201` (`classify`); notifications at 268 |
| 4b | Only if no rule matches (`OTHER`): asks **Qwen** | `classify.py:321` |
| 5 | Reads Gazette details: Part, Section, issue number, file number | `analysis.py:123` (`identify`) |
| 6 | **Compares website titles with the real number**; warning if they differ, and the content wins | `analysis.py:153-160` |
| 7 | Creates `document` + `document_file` ("this document = pages 1–2 of file 1012") | `stages.py:223` (`write_documents`), `:155` (`upsert_document`) |
| 7b | **AIS files are split**: standard + each amendment + corrigendum, each with its own pages | `stages.py:365` (`write_ais`), `split.py` |
| 8 | Same document in several files → picks the best copy | `stages.py:515` |
| 9 | Sets **`stage = 'classified'`** | |

### Try it yourself

**A. Run the identification** (Python console, read-only):

```python
from regtrack.db import connect
from regtrack.pipeline.stages import file_ctx
from regtrack.pipeline.text import load_pages
from regtrack.pipeline.analysis import identify
conn = connect()
f = conn.execute("SELECT * FROM file_object WHERE id=1012").fetchone()
ctx = file_ctx(conn, f, load_pages(f["sha256"]))
fa = identify(ctx)
print(fa.identity.canonical_id, fa.identity.doc_date)
print(fa.cls.doc_class, fa.cls.status, fa.cls.issuer, fa.cls.reason)
print(fa.gazette, fa.file_no)
print(fa.identity.evidence)
print(ctx.listings[0]["title"])
conn.close()
exit()
```

**B. What was saved:**

```sql
SELECT id, canonical_id, doc_class, status, series, number, year, doc_date, issuer, nature
FROM document WHERE canonical_id = 'SO-3896(E)-2022';

SELECT document_id, file_id, page_from, page_to, english_page_from, english_page_to, role, is_best_copy
FROM document_file WHERE document_id = 754;
```

**C. The website being wrong:**

```sql
SELECT q.details->>'source' AS website, q.details->>'title' AS website_title,
       q.details->>'content' AS real_number, q.details->>'resolution' AS result
FROM quality_flag q WHERE q.rule = 'title_file_mismatch' LIMIT 10;
```

**D. One file split into many documents:**

```sql
SELECT df.file_id, d.canonical_id, d.doc_class, df.page_from, df.page_to, df.role
FROM document_file df JOIN document d ON d.id = df.document_id
WHERE df.file_id = (SELECT file_id FROM document_file WHERE role = 'consolidated_segment'
                    GROUP BY file_id ORDER BY count(*) DESC LIMIT 1)
ORDER BY df.page_from;
```

### What to look for

- **A:** `SO-3896(E)-2022 2022-08-12`, then `NOTIFICATION_EXTENSION final MoRTH G.S.R./S.O. heading`: decided by rules, not Qwen. `evidence` is the English heading on page 2. The website title agrees, so no warning.
- **B:** 1 document on pages 1–2 of file 1012, English on page 2, best copy.
- **C:** real cases where a website named the wrong notification.
- **D:** one PDF → `AIS-xxx` on some pages, then `AIS-xxx/Amd.1`, `/Amd.2`…, each on its own pages.

### How it goes to the next step

The file gets **`stage = 'classified'`**. Step 6 works on **each document** in the file, using the page ranges in `document_file`.

---

## Step 6: Extract. Filling in the details

### In simple words

Step 5 found **who** the document is. Step 6 fills in **the details**: what it changes, which vehicles, which law gives the power, file number, signatory…

It does this in **two passes**:

1. **Fixed rules first**: pattern matching on the English text. Fast, free, always available.
2. **Qwen (the AI) second**, *if* reachable. If not, the rules result is saved and the document is marked **waiting for Qwen** (`llm_pending = true`), to be filled on a later run.

The pipeline **never stops** because the AI is off.

### Where the details go

| Where (on the `document` row) | What | Example |
|---|---|---|
| **Normal columns** | things every document has, used for filtering | `subject`, `vehicle_categories`, `in_scope`, `domains` |
| **`data`** (JSON) | details for this *kind* of document | Gazette part, file number, signatory, what it amends |
| **`extraction`** (JSON) | **who** filled it and **how sure** | `"model": "rules"`, `"llm_pending": true`, `"confidence": {...}` |

**One shape per kind of document.** The shape of `data` is one Python class, for example `NotificationData` (`regtrack/models/data.py:156`). The same class is:

- used to **check** the result,
- given to **Qwen** as the form to fill in,
- exported as a JSON Schema file (`regtrack/models/schemas/NOTIFICATION_EXTENSION.json`).

If data doesn't fit the shape, the value is kept and a `schema_violation` warning is raised.

**`in_scope`** = the vehicle categories include **L1, L2, M1, N1** or **ALL**. Only in-scope documents appear in the portal's register.

### What happens, in order

| # | What | Where |
|---|---|---|
| 1 | Picks files with `stage = 'classified'`; each document, best copy only | `extract.py:486` (`stage_extract`) |
| 2 | Keeps the **operative part** of the English text (from "In exercise of the powers…") | `extract.py:40` (`operative_text`) |
| 3 | **Rules**: amends what, powers (`MV Act s.109`), dates, other IDs, vehicle categories (synonyms: "two-wheeler" → L1/L2, "e-rickshaw" → E_RICKSHAW…), topics | `extract.py:277` (`deterministic`); `patterns.py:250`; `vocab.py:55` |
| 4 | **Qwen**, if reachable: English pages + the form, temperature 0 → form filled in | `extract.py:418` (form), `:443` (`llm_extract`), `regtrack/llm.py` |
| 5 | Qwen not reachable → `llm_pending = true` | `extract.py:603-608` |
| 6 | Checks `data` → `schema_violation`; no categories → `no_vehicle_category` | `extract.py:609-616`, `validators.py:19` |
| 7 | Saves, sets **`stage = 'parsed'`** | `extract.py:617+` |

### Try it yourself

**A. Run the rules** (Python console, read-only):

```python
import json
from regtrack.db import connect
from regtrack.pipeline.text import load_pages
from regtrack.pipeline.extract import deterministic
from regtrack.validators import validate_data
from regtrack import llm
conn = connect()
doc = conn.execute("SELECT * FROM document WHERE canonical_id='SO-3896(E)-2022'").fetchone()
df = conn.execute("SELECT * FROM document_file WHERE document_id=%s AND is_best_copy", (doc["id"],)).fetchone()
f = conn.execute("SELECT * FROM file_object WHERE id=%s", (df["file_id"],)).fetchone()
cols, data, conf = deterministic(doc, load_pages(f["sha256"]), df, f, [])
print(cols)
print(json.dumps(data, indent=1))
print(conf)
print(validate_data(doc["doc_class"], data))
print(llm.reachable())
conn.close()
exit()
```

**B. The shape Qwen fills in:**

```powershell
code regtrack\models\data.py
code regtrack\models\schemas\NOTIFICATION_EXTENSION.json
```

**C. What was saved:**

```sql
SELECT canonical_id, subject, vehicle_categories, in_scope,
       jsonb_pretty(data) AS data, jsonb_pretty(extraction) AS extraction
FROM document WHERE canonical_id = 'SO-3896(E)-2022';
```

**D. How many are waiting for Qwen:**

```sql
SELECT extraction->>'model' AS filled_by,
       count(*) FILTER (WHERE (extraction->>'llm_pending')::boolean) AS waiting_for_qwen,
       count(*) AS documents
FROM document GROUP BY 1;
```

**E. Warnings from this step:**

```sql
SELECT rule, count(*) FROM quality_flag
WHERE rule IN ('schema_violation', 'no_vehicle_category') AND resolved_at IS NULL GROUP BY 1;
```

### What to look for

- **A, `data`:** S.O. 3896(E), 12 Aug 2022, `MV Act s.109`, file no `RT-11036/17/2021-MVL`, signatory Mahmood Ahmed, and **amends `SO-1365(E)-2004 Table`**, which Step 7 uses.
- **A, `cols`:** `vehicle_categories: ['E_RICKSHAW', 'E_CART']`, `in_scope: False`. The rules saw "E-rickshaws and E-carts" (Table B) and stopped there, although the notice also changes rows for cars, trucks and two-wheelers. A weakness of the rules that Qwen would likely fix.
- **A, `reachable`:** if it says `LLM_BASE_URL not configured`, `.env` still has the placeholder ngrok address. This is why most documents are waiting.
- **C:** `"model": "rules"` and `"llm_pending": true`: no AI has touched it yet.

**To switch Qwen on:** start LM Studio and ngrok, put the real address in `.env` (`LLM_BASE_URL=https://xxxx.ngrok-free.app/v1`), then check with `.venv\Scripts\python -m regtrack.cli check`. Waiting documents are filled automatically at the end of the next pipeline run (Step 9).

### How it goes to the next step

The file gets **`stage = 'parsed'`**. Step 7 picks those files **in date order** (oldest notification first).

---

## Step 7: Link. Connecting documents, and keeping the history of rules

### In simple words

Our notice says, in short:

> *"In the 2004 notice S.O. 1365(E), change the deadline in rows 8 and 43 of the Table, row 6 of Table A, and row 2 of Table B, from **21 Sep 2022** to **22 Jun 2023**."*

Step 7 does three things with that:

1. **Relations:** records "S.O. 3896(E) extends dates in S.O. 1365(E)", and other links like this.
2. **Families and versions:** groups all notices that change the same master notice, in order.
3. **Mandates:** keeps a **history of each rule**, "who must comply with which standard, from when", with every old version kept.

### Part 1: Relations (`doc_relation`)

One row per link: **from** → **type** → **to**, plus the exact sentence it was found in (**evidence**).

| Type | Meaning |
|---|---|
| `amends` | changes another document |
| `extends_date` | moves a deadline |
| `substitutes_row` / `inserts_row` / `omits_row` | changes a table row |
| `finalises` | final notice confirming an earlier draft |
| `revises` | new revision of an AIS standard |
| `references` | only mentions another document |

If the target isn't in the database yet, the link is still saved. `to_doc` stays empty and `to_ref` keeps the number; it is filled in automatically when the target arrives (Step 9).

### Part 2: Families and versions

All notices changing the 2004 master share **`family_key = SO-1365-MASTER`**. They are numbered by date (`version_seq`), and exactly **one** is `is_current = true`; the database refuses two. AIS works the same way: `AIS-038`, `AIS-038(Rev.1)`, `AIS-038(Rev.2)` are one family.

### Part 3: Mandates

A **mandate** is one rule: *"wheel rims for cars and trucks (M and N) must meet IS 9436 and IS 9438, from date X"*. Its name (`mandate_key`) is the table row, for example `SO-1365(E)-2004 Table Sr.8(b)`.

When a new notice changes the date, RegTrack **never overwrites the old row**:

1. It **closes** the old version: `valid_to` = the new notice's date, `superseded_by` = the new row.
2. It **adds** a new version with the new date and the same `mandate_key`.

So you can always answer *"what was the rule on 1 January 2023?"*. The real history of row 8(b):

| Version | Written by | Comply from | Valid from | Valid until |
|---|---|---|---|---|
| 1 | S.O. 1406(E)-2021 | 21 Sep 2021 | 22 Mar 2021 | 27 Jan 2022 |
| 2 | S.O. 359(E)-2022 | 21 Sep 2022 | 27 Jan 2022 | 12 Aug 2022 |
| **3** | **S.O. 3896(E)-2022** | **22 Jun 2023** | 12 Aug 2022 | 5 Sep 2023 |
| 4 | S.O. 3947(E)-2023 | 22 Dec 2023 | 5 Sep 2023 | still valid |

That's why **files are linked in date order**: in another order, the history would come out wrong.

### Where it happens

| What | File : line |
|---|---|
| The stage | `regtrack/pipeline/link.py:195` (`stage_link`) |
| Finds relations in a notification | `link.py:62` (`link_notification`) |
| Saves one relation | `link.py:35` (`add_relation`) |
| AIS amendments and revisions | `link.py:111` (`link_ais`) |
| Families | `link.py:144`, `:153` (`recompute_family`) |
| Sentence patterns for table changes | `regtrack/pipeline/mandates.py:173-177`, `:180` (`parse_table_amendments`) |
| Builds mandate versions | `mandates.py:323` (`mandates_for_document`) |
| **Close old + add new** | `mandates.py:303` (`supersede`), `:298` (`close`) |
| Date order | `regtrack/pipeline/runner.py:55` (`run_stage`, the `link` query) |

### Try it yourself

**A. Run the sentence reader** (Python console, read-only):

```python
from regtrack.db import connect
from regtrack.pipeline.text import load_pages, english_text
from regtrack.pipeline.extract import operative_text
from regtrack.pipeline.mandates import parse_table_amendments
conn = connect()
f = conn.execute("SELECT * FROM file_object WHERE id=1012").fetchone()
op = operative_text(english_text(load_pages(f["sha256"]), 1, 2))
print(op[:600])
items, dates, omits = parse_table_amendments(op)
print(len(items), len(dates), len(omits))
for d in dates: print(d.table, d.serials, d.old, "->", d.new)
conn.close()
exit()
```

**B. The relations it saved:**

```sql
SELECT r.type, coalesce(t.canonical_id, r.to_ref) AS target, r.to_doc IS NOT NULL AS found,
       r.details, r.method, r.evidence
FROM doc_relation r LEFT JOIN document t ON t.id = r.to_doc
WHERE r.from_doc = 754 ORDER BY r.id;
```

**C. The family:**

```sql
SELECT version_seq, canonical_id, doc_class, doc_date, is_current
FROM document WHERE family_key = 'SO-1365-MASTER' ORDER BY version_seq;
```

**D. The history of one rule:**

```sql
SELECT m.id, d.canonical_id AS written_by, m.implementation_date AS comply_from,
       m.valid_from, m.valid_to, m.superseded_by
FROM mandate m JOIN document d ON d.id = m.source_doc_id
WHERE m.mandate_key = 'SO-1365(E)-2004 Table Sr.8(b)' ORDER BY m.id;
```

**E. The rule on a given date** (change the date and run again):

```sql
SELECT mandate_key, subject, implementation_date AS comply_from
FROM mandate
WHERE mandate_key = 'SO-1365(E)-2004 Table Sr.8(b)'
  AND valid_from <= DATE '2023-01-01' AND (valid_to IS NULL OR valid_to > DATE '2023-01-01');
```

### What to look for

- **A:** `0 4 0`: no row changes, **4 date changes**, no removals; each is `21 Sep 2022 -> 22 Jun 2023`.
- **B:** 7 rows. Four `extends_date` rows carry the row details (Sr. 8, 43, Table A 6, Table B 2) and the exact sentence as `evidence`; a fifth `extends_date` is a summary row for the whole notice. All five have `found = false`, because the 2004 master isn't in the database. Then 2 `references`: S.O. 359(E)-2022 (`found = true`) and S.O. 1365(E)-2004 (`found = false`).
- **C:** our notice is version **14**; one row is current.
- **D:** 4 versions; only the last has an empty `valid_to`.
- **E:** `2023-01-01` → version 3; try `2022-03-01` (version 2) and today (version 4).

### How it goes to the next step

The file gets **`stage = 'linked'`**.

---

## Step 8: Chunk & embed. Preparing the text for search

### In simple words

For the portal's search box, RegTrack needs:

1. **Chunk**: cut each document into **small pieces**, usually one clause each, so search points to "clause 2 on page 2" and not "somewhere in this 40-page PDF".
2. **Embed**: turn each piece into a **list of 768 numbers** (a "vector") that captures its *meaning*, so search can find "deadline postponed" even when the text says "22nd June, 2023 shall be substituted".

**A vector, simply:** picture every piece of text as a dot on a huge map, where texts with **similar meaning sit close together**. The 768 numbers are the dot's position. The question becomes a dot too, and the closest dots are the answers.

### Part 1: Chunk

| What | How |
|---|---|
| Which pages | **English only.** Hindi is never chunked for search. |
| Where to cut | AIS: clause numbers (`1`, `6.2`, `6.12.3`) or `ANNEX A`. Notifications: paragraphs (`2.`, `(1)`). |
| Size | A piece is closed after at least 120 characters; over 1,800 are cut at paragraph breaks; under 20 are dropped. |
| Boilerplate | Gazette headers, committee lists, printer lines: kept but marked `is_boilerplate = true`, ranked last. |
| Filters | Each piece copies its document's class, categories, `in_scope`, `is_current`. |
| Off-topic | `OFF_TOPIC` documents get no pieces. |

Pieces go into **`chunk`**; the file gets **`stage = 'chunked'`**.

### Part 2: Embed

RegTrack takes pieces without a vector, **64 at a time**, sends them to the **embedding model in LM Studio**, and saves the 768 numbers in `chunk.embedding`. When **all** pieces of a file have numbers, the file gets **`stage = 'done'`**.

**If `EMBED_MODEL` in `.env` is still the placeholder**, this part is off:

- no piece has numbers,
- most files wait at `chunked` (files with no pieces, such as off-topic files, reach `done`),
- search **falls back to keyword search** (matching words, not meaning).

### Where it happens

| What | File : line |
|---|---|
| The stage | `regtrack/pipeline/chunk.py:106` (`stage_chunk`) |
| Cutting rules | `chunk.py:25-30` |
| The cutting | `chunk.py:55` (`chunk_pages`) |
| Saves pieces | `chunk.py:135` (`write_chunks`) |
| Vectors, 64 at a time | `chunk.py:165` (`embed_pending`) |
| Files → `done` | `chunk.py:187` (`advance_embedded`) |
| Search (meaning first, keywords as fallback) | `regtrack/pipeline/search.py:15` (`search`), `:73` (`fulltext`) |

### Try it yourself

**A. Cut and search** (Python console, read-only):

```python
from regtrack.db import connect
from regtrack.pipeline.text import load_pages
from regtrack.pipeline.chunk import chunk_pages
from regtrack.pipeline.search import search
conn = connect()
f = conn.execute("SELECT * FROM file_object WHERE id=1012").fetchone()
for c in chunk_pages(load_pages(f["sha256"]), notification=True): print(c.index, c.clause_no, c.is_boilerplate, len(c.content), c.content[:60])
r = search(conn, "wheel rim deadline extended", category="M1", in_scope=None, limit=5)
print(r["mode"])
for h in r["results"]: print(round(float(h["score"]), 2), h["canonical_id"], h["clause_no"], h["content"][:70])
conn.close()
exit()
```

**B. The saved pieces:**

```sql
SELECT id, chunk_index, clause_no, page_from, is_boilerplate, embedding IS NOT NULL AS has_vector,
       vehicle_categories, left(content, 120) AS text
FROM chunk WHERE document_id = 754 ORDER BY chunk_index;
```

**C. The big picture:**

```sql
SELECT count(*) AS pieces,
       count(*) FILTER (WHERE embedding IS NOT NULL) AS with_vector,
       count(*) FILTER (WHERE is_boilerplate) AS boilerplate
FROM chunk;

SELECT stage, count(*) FROM file_object GROUP BY 1;
```

**D. An AIS standard, cut by clauses:**

```sql
SELECT chunk_index, clause_no, heading, page_from, left(content, 80) AS text
FROM chunk
WHERE document_id = (SELECT id FROM document WHERE doc_class = 'AIS_STANDARD' AND is_current LIMIT 1)
ORDER BY chunk_index LIMIT 15;
```

### What to look for

- **A, pieces:** **2 pieces**. Piece 0 is the Gazette header (`True` = boilerplate); piece 1 is clause `2`, the real content.
- **A, search:** `mode` = `text (embeddings unavailable…)` while embeddings are off. The top hit is S.O. 1406(E)-2021, the *first* wheel-rim notice, not ours. Ours never uses the words "deadline" or "extended"; it says "shall be substituted". Keyword search can't know they mean the same thing; meaning search can.
- **B:** `has_vector = false`; categories copied from the document.
- **C:** pieces vs pieces with a vector; files at `chunked` vs `done`.
- **D:** one clause per piece, with clause numbers and headings.

**To switch embeddings on:** load an embedding model with 768 dimensions in LM Studio, set `EMBED_MODEL=…` and a real `LLM_BASE_URL` in `.env`, then:

```powershell
.venv\Scripts\python -m regtrack.cli run --stage embed
```

### How it goes to the next step

After all stages, the pipeline does one last round over the whole database: Step 9.

---

## Step 9: After the run. The clean-up round

### In simple words

Steps 4–8 work **file by file**. Some jobs need to look at **everything at once**, so at the end of every pipeline run RegTrack does a clean-up round:

1. **Fill in missing links**: a relation saved earlier with an empty target (Step 7) gets connected if the target has arrived since.
2. **Tidy up**: keeps best copies and the search pieces' filter columns in line with their documents.
3. **Close warnings** whose evidence now settles them, and writes the evidence into the warning.
4. **Qwen catch-up**: if Qwen is reachable, fills up to 200 documents still marked `llm_pending` (the Step 6 Qwen pass).
5. **"What's new" events**: writes a `change_event` for documents that a **live** crawl found (never for the seed). This is the feed the portal shows as changes and alerts.

### What happens

| # | What | Where |
|---|---|---|
| 0 | The round itself | `regtrack/pipeline/runner.py:90` (`post_run`) |
| 1 | Fill in links whose target arrived | `link.py:237` (`resolve_refs`) |
| 2 | Best copies, search filters | `stages.py:541` (`tap_best_copies`), `chunk.py:152` (`sync_chunk_filters`) |
| 3 | Close settled warnings | `resolve.py:137` (`resolve_all`) → `:31` website title wrong, `:64` missing amendments, `:106` placeholder dates, `:122` guessed years |
| 4 | Qwen catch-up | `extract.py:661` (`enrich_pending`) |
| 5 | "What's new" events | `events.py:65` (`emit_events`), `:55` (`live_documents`), type by class at `:15` |

**About events:**

- Each one has a **type** (`new_document`, `draft_published`, `draft_finalised`, `new_revision`, `implementation_date_changed`…) and a **summary**.
- The summary is written by Qwen when reachable, otherwise from a template. Template summaries get `review_status = 'needs_check'` so a person can look at them.
- An event is written **once**; running again adds nothing.

**Warnings are never "fixed" by hand.** A warning (`quality_flag`) stays open until the evidence settles it. Then `resolved_at` is set and the reason is written into `details`, so every closed warning can be checked.

### Try it yourself

**A. The latest "what's new" events:**

```sql
SELECT e.detected_at, e.event_type, d.canonical_id, e.summary, e.review_status,
       e.details->>'summary_by' AS written_by
FROM change_event e LEFT JOIN document d ON d.id = e.document_id
ORDER BY e.detected_at DESC LIMIT 15;
```

**B. Why our notice has no event** (it came from the seed):

```sql
SELECT count(*) AS events_for_754 FROM change_event WHERE document_id = 754;

SELECT so.code, s.crawl_run_id, s.listing_raw->>'matched_seed' AS matched_seed
FROM file_sighting s JOIN source so ON so.id = s.source_id WHERE s.file_id = 1012;
```

**C. Warnings closed by evidence, and how:**

```sql
SELECT rule, details->>'resolution' AS how, count(*)
FROM quality_flag WHERE resolved_at IS NOT NULL
GROUP BY 1, 2 ORDER BY 3 DESC;
```

**D. Warnings still open:**

```sql
SELECT rule, count(*) FROM quality_flag WHERE resolved_at IS NULL GROUP BY 1 ORDER BY 2 DESC;
```

**E. Links still waiting for their target:**

```sql
SELECT type, count(*) FILTER (WHERE to_doc IS NULL) AS waiting, count(*) AS total
FROM doc_relation GROUP BY 1 ORDER BY 3 DESC;
```

### What to look for

- **A:** recent events such as `new_document` for `SO-5556(E)-2026` or `draft_published` for `GSR-868(E)-2026`. While Qwen is off, `written_by` = `template` and `review_status` = `needs_check`.
- **B:** 0 events for our notice. Its file came from the seed (`LOCAL_SEED`, run 1), and the live MoRTH row only matched it (`matched_seed = true`), so it isn't news.
- **C:** for example "listing title wrong; identity from content confirmed" (the Step 5 problem, settled) or "content date used; listing placeholder ignored".
- **E:** many `references` are waiting, because they point to documents that were never published online or aren't crawled. They connect on their own if the target ever arrives.

### How it goes to the next step

Nothing more is written. The data is ready to be read by the API and the portal.

---

## Step 10: Portal & API. Reading the results

### In simple words

Everything so far **writes** data. The last part only **reads** it and shows it:

- The **API** (FastAPI, Python) answers questions in JSON, for example "the document SO-3896(E)-2022" or "which rules apply to a scooter on 1 Jan 2026".
- The **portal** (the dashboard website, React) calls the API and draws the screens.

Everything shown is filtered to the **current country** (`REGTRACK_COUNTRY`, default `IN`). Add `?country=TH` to a request to see Thailand.

### What happens

The four views the project promises:

| View | API address | Reads from |
|---|---|---|
| **By vehicle** | `/vehicles/applicable?category=L2&engine_cc=110&on=2026-01-01` | **mandates** in force on that date for that category, plus the current version of each standard |
| **By year / category** | `/documents?year=2022&category=M1` | **documents** |
| **By version** | `/families/{family_key}/versions` | the **family** of a document |
| **Search** | `/search?q=wheel rim` | **chunks** |

Others:

| Address | What |
|---|---|
| `/documents/{canonical_id}` | everything about one document: files, sightings, relations, mandates, warnings |
| `/files/{sha256}` | the original file, from `data\raw` |
| `/share-pack?category=L2` | a zip of the original files for a vehicle, plus a list (manifest) |
| `/changes` | the "what's new" events |
| `/meta` | headline numbers |
| `/portal/...` | the portal's screens: summary, register, change monitor, compliance, alerts, admin |

The portal adds a few rules of its own on top: impact (High / Medium / Low), status, and the compliance matrix built from open mandates.

### Where it happens

| What | File : line |
|---|---|
| API endpoints | `regtrack/api/app.py`: `/vehicles/applicable` 57, `/documents` 104, `/documents/{id}` 144, `/families/…/versions` 176, `/changes` 192, `/search` 201, `/share-pack` 227, `/files` 269, `/meta` 300 |
| Portal endpoints | `regtrack/api/portal.py`: `/summary` 190, `/regulations` 245, `/changes` 318, `/compliance` 382, `/admin` 765 |
| Country filter (one helper for all queries) | `regtrack/country.py` |
| Dashboard (website) | `dashboard/src/`; it calls the API at `http://127.0.0.1:8000` (`dashboard/src/api.js:2`) |

### Try it yourself

**A. Start the API** (Terminal 2; it keeps running, stop it with `Ctrl+C`):

```powershell
.venv\Scripts\python -m regtrack.cli api
```

**B. Open the interactive API page:**

```
http://127.0.0.1:8000/docs
```

Every endpoint is listed. Click one → **Try it out** → **Execute** to see the real answer.

**C. Try these in the browser:**

```
http://127.0.0.1:8000/documents/SO-3896(E)-2022
http://127.0.0.1:8000/families/SO-1365-MASTER/versions
http://127.0.0.1:8000/vehicles/applicable?category=M1&on=2023-01-01
http://127.0.0.1:8000/vehicles/applicable?category=M1&on=2023-07-01
http://127.0.0.1:8000/vehicles/applicable?category=M1&on=2026-10-14
http://127.0.0.1:8000/search?q=wheel%20rim
http://127.0.0.1:8000/meta
```

**D. Start the portal** (a third terminal; needs Node.js):

```powershell
cd D:\regulatory_intelligence\dashboard
npm run dev
```

Then open `http://localhost:5173`. Or run `start.bat` in the project folder, which starts the database, API and portal together.

### What to look for

- **C, `/documents/SO-3896(E)-2022`:** everything from Steps 2–9 in one answer: `files` with their `sightings`, `relations_out` (7 relations), `mandates` (9 versions, all closed today), `quality_flags`, and `ai_pending: true`.
- **C, `/vehicles/applicable`:** this view shows only rules whose compliance date has already arrived on the date you ask for. Look for `mandate_key` = `SO-1365(E)-2004 Table Sr.8(b)`:
  - on `2023-01-01` it is **missing**: our version was in force, but its compliance date (22 Jun 2023) was still to come (add `&include_future=true` to see it);
  - on `2023-07-01` it shows the version **from our notice** (comply from 2023-06-22);
  - today it shows the later version from **S.O. 3947(E)-2023** (comply from 2023-12-22).

  This is the Step 7 history at work.
- **C, `/search`:** `mode` tells you whether it used meaning (`vector`) or keywords (`text`).
- **D, portal register:** our notice is **not** in the register, because its own categories are E_RICKSHAW / E_CART (Step 6), which are out of scope. Its family and history are still visible through the API.

---

## Cheat sheet

### Commands

```powershell
# database console (password: regtrack)
D:\pgsql\Library\bin\psql.exe -h localhost -U regtrack -d regtrack

# health check: database, pgvector, LLM, embeddings
.venv\Scripts\python -m regtrack.cli check

# crawl one source, without processing (writes to the database)
.venv\Scripts\python -m regtrack.cli crawl MORTH_API --no-process

# run one pipeline stage (text | classify | extract | link | chunk | embed); add --limit 1 for a single file
.venv\Scripts\python -m regtrack.cli run --stage text

# run the whole pipeline on whatever is waiting
.venv\Scripts\python -m regtrack.cli run

# start the scheduler (every 6 hours, keeps running)
.venv\Scripts\python -m regtrack.cli schedule

# start the API (http://127.0.0.1:8000/docs)
.venv\Scripts\python -m regtrack.cli api
```

### Follow any file through every table

In psql, set the file id first, then run the queries:

```sql
\set f 1012

SELECT id, sha256, ext, page_count, text_layer, stage, stage_error, storage_path FROM file_object WHERE id = :f;

SELECT so.code, s.listing_title, s.listing_date, s.source_url
FROM file_sighting s JOIN source so ON so.id = s.source_id WHERE s.file_id = :f;

SELECT d.id, d.canonical_id, d.doc_class, d.status, d.doc_date, d.vehicle_categories, d.in_scope,
       df.page_from, df.page_to, df.role, df.is_best_copy, d.extraction->>'llm_pending' AS waiting_for_qwen
FROM document_file df JOIN document d ON d.id = df.document_id WHERE df.file_id = :f;

SELECT r.type, coalesce(t.canonical_id, r.to_ref) AS target, r.to_doc IS NOT NULL AS found
FROM doc_relation r LEFT JOIN document t ON t.id = r.to_doc
WHERE r.from_doc IN (SELECT document_id FROM document_file WHERE file_id = :f);

SELECT mandate_key, implementation_date, valid_from, valid_to
FROM mandate WHERE source_doc_id IN (SELECT document_id FROM document_file WHERE file_id = :f);

SELECT chunk_index, clause_no, is_boilerplate, embedding IS NOT NULL AS has_vector, left(content, 80)
FROM chunk WHERE file_id = :f ORDER BY chunk_index;

SELECT entity, rule, resolved_at IS NOT NULL AS closed, details FROM quality_flag
WHERE (entity = 'file_object' AND entity_id = :f)
   OR (entity = 'document' AND entity_id IN (SELECT document_id FROM document_file WHERE file_id = :f));
```

### Folders

| Folder | What |
|---|---|
| `D:\Regulatory_Documents` | the seed collection: **read only, never change** |
| `data\raw\<2>\<sha256>.<ext>` | stored originals, write-once |
| `data\text\<2>\<sha256>.jsonl` | page text per file |
| `data\text\<2>\<sha256>.meta.json` | page count, languages, scans per file |

### Tables, in the order the data flows

| Table | One row per | Written in step |
|---|---|---|
| `source` | website | (setup) |
| `crawl_run` | crawl | 2 |
| `file_sighting` | time a website listed a file | 2, 3 |
| `file_object` | unique file (fingerprint) | 3, updated in 4–8 |
| `document` | document (number + type) | 5, 6, 7 |
| `document_file` | document's pages in a file | 5 |
| `doc_relation` | link between documents | 7, 9 |
| `mandate` | version of a rule | 7 |
| `chunk` | searchable piece of text | 8 |
| `quality_flag` | warning | 4–9 |
| `change_event` | "what's new" item | 9 |
