"""Offline profile (no DB): run text stats, identity and classification over the prepared seed corpus and
print the CLAUDE.md regression measures. Used to tune rules before/without PostgreSQL.

    python scripts/profile_offline.py [--dump out.jsonl]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regtrack.pipeline.analysis import analyse_file, contexts_from_manifest  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump")
    ap.add_argument("--folder")
    a = ap.parse_args()
    ctxs = contexts_from_manifest()
    if a.folder:
        ctxs = [c for c in ctxs if c.folder == a.folder]
    rows = []
    for c in ctxs:
        rows.append(analyse_file(c))
    cls = collections.Counter(r["doc_class"] for r in rows)
    byf = collections.Counter((r["folder"], r["doc_class"]) for r in rows)
    print("unique files", len(rows))
    print("scans", sum(1 for r in rows if r["scan"]), "scan pages", sum(r["scan_pages"] for r in rows if r["scan"]))
    print("kruti notifications", sum(1 for r in rows if r["kruti"] and r["doc_class"].startswith("NOTIFICATION")))
    print("kruti any", sum(1 for r in rows if r["kruti"]))
    print(
        "AIS files with amendments",
        sum(1 for r in rows if r["amd_headers"]),
        "with corrigenda",
        sum(1 for r in rows if r["corr_headers"]),
    )
    print("finals citing draft", sum(1 for r in rows if r["cites_draft"]))
    print("title mismatch", sum(1 for r in rows if r["title_mismatch"]))
    print("off topic in 02", byf[("02", "OFF_TOPIC")])
    print(
        "no identity notifications",
        sum(1 for r in rows if r["doc_class"].startswith("NOTIFICATION") and not r["canonical_id"]),
    )
    ids = collections.Counter(r["canonical_id"] for r in rows if r["canonical_id"])
    print("distinct canonical ids", len(ids))
    for k, v in cls.most_common():
        print(f"  {k:28s} {v}")
    for k, v in sorted(byf.items()):
        print("   ", k, v)
    if a.dump:
        with open(a.dump, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    main()
