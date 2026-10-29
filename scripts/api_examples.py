"""Call every read-API endpoint in-process and print compact example responses (Phase 10 report)."""

import csv
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

from regtrack.api.app import app  # noqa: E402

c = TestClient(app)


def show(url, keep=None, n=1500):
    r = c.get(url)
    print(f"\n### GET {url} -> {r.status_code}")
    if r.headers.get("content-type", "").startswith("application/json"):
        body = r.json()
        print(json.dumps(keep(body) if keep and r.status_code == 200 else body, default=str, ensure_ascii=False)[:n])
    return r


show("/health")
show(
    "/vehicles/applicable?category=L2&engine_cc=110&powertrain=petrol&on=2026-01-01",
    lambda b: {
        "count": b["count"],
        "mandates": [
            {k: m[k] for k in ("legal_basis", "subject", "standard_refs", "implementation_date", "source_canonical_id")}
            for m in b["mandates"][:6]
        ],
    },
)
show(
    "/documents?year=2022&category=M1&doc_class=NOTIFICATION_FINAL&limit=3",
    lambda b: {
        "total": b["total"],
        "documents": [
            {k: d[k] for k in ("canonical_id", "subject", "doc_date", "vehicle_categories", "in_scope")}
            for d in b["documents"]
        ],
    },
)
show(
    "/documents/SO-3896(E)-2022",
    lambda b: (
        {k: b[k] for k in ("canonical_id", "doc_class", "doc_date", "subject", "family_key", "is_current")}
        | {
            "relations_out": b["relations_out"][:4],
            "mandates": [m["mandate_key"] for m in b["mandates"]][:5],
            "files": [f["sha256"][:12] for f in b["files"]],
        }
    ),
)
show(
    "/documents/AIS-156/Amd.5",
    lambda b: (
        {k: b[k] for k in ("canonical_id", "doc_class", "doc_date", "subject", "family_key")}
        | {"relations_out": b["relations_out"][:3]}
    ),
    800,
)
show(
    "/families/AIS-038/versions",
    lambda b: {
        "current": b["current"],
        "versions": [(v["canonical_id"], v["version_seq"], v["status"], v["is_current"]) for v in b["versions"]],
    },
)
show(
    "/families/SO-1365-MASTER/versions",
    lambda b: {
        "current": b["current"],
        "n": len(b["versions"]),
        "first": [(v["canonical_id"], str(v["doc_date"])) for v in b["versions"][:4]],
    },
    800,
)
show(
    "/changes?since=2026-10-01",
    lambda b: {
        "count": b["count"],
        "sample": [(e["event_type"], e["canonical_id"], (e["summary"] or "")[:70]) for e in b["changes"][:5]],
    },
)
show(
    "/search?q=anti-lock%20braking&category=L2&limit=3",
    lambda b: {"mode": b["mode"][:40], "hits": [(h["canonical_id"], h["clause_no"]) for h in b["results"]]},
    600,
)
r = show("/share-pack?category=L2")
print(r.headers.get("content-type"), r.headers.get("content-disposition"), len(r.content), "bytes")
z = zipfile.ZipFile(io.BytesIO(r.content))
rows = list(csv.reader(io.StringIO(z.read("manifest.csv").decode("utf-8"))))
print("zip entries:", len(z.namelist()), "manifest rows:", len(rows) - 1)
print("header:", rows[0])
print("row 1:", rows[1][:6])
