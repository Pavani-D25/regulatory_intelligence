"""Row counts of every table (used to prove that a re-run writes zero rows)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from regtrack.db import connect  # noqa: E402

TABLES = ["documents", "raw_ingestion_records", "regulations", "document_parts", "regulation_relations",
          "compliance_requirements", "requirement_versions", "document_chunks", "regulation_changes", "quality_flags",
          "ingestion_runs", "alert_events"]
with connect() as c:
    print(json.dumps({t: c.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in TABLES}))
