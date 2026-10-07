"""Row counts of every table (used to prove that a re-run writes zero rows)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from regtrack.db import connect  # noqa: E402

TABLES = ["file_object", "file_sighting", "document", "document_file", "doc_relation", "mandate", "chunk",
          "change_event", "quality_flag", "crawl_run"]
with connect() as c:
    print(json.dumps({t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in TABLES}))
