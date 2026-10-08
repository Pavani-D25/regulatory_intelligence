"""One-time upload of the local object store to S3/MinIO: python -m regtrack.cli storage-upload [--switch].

Every file_object whose storage_path is a local file is uploaded under the same key <sha[:2]>/<sha>.<ext>
(write-once: existing keys are skipped; the local copy's sha256 is checked first). With --switch the
file_object.storage_path is rewritten to s3://<bucket>/<key> - set STORAGE_BACKEND=s3 in .env at the same time.
Local files are never deleted. Re-running uploads nothing new.
"""

from __future__ import annotations

import logging
from pathlib import Path

from regtrack.config import get_settings
from regtrack.db import connect
from regtrack.storage import ensure_bucket, is_s3_uri, object_key, s3_client, s3_exists, s3_put, sha256_file

log = logging.getLogger(__name__)


def upload_all(limit: int | None = None, switch: bool = False, verify: bool = True) -> dict:
    s = get_settings()
    client = s3_client()
    locked = ensure_bucket(client, s.s3_bucket)
    stats = {"bucket": s.s3_bucket, "object_lock": locked, "checked": 0, "uploaded": 0, "already_there": 0,
             "missing_local": 0, "bad_hash": 0, "switched": 0}
    with connect() as conn:
        rows = conn.execute("SELECT id, sha256, ext, storage_path FROM file_object ORDER BY id"
                            + (f" LIMIT {int(limit)}" if limit else "")).fetchall()
        for r in rows:
            stats["checked"] += 1
            if is_s3_uri(r["storage_path"]):
                stats["already_there"] += 1
                continue
            p = Path(r["storage_path"])
            if not p.exists():
                stats["missing_local"] += 1
                continue
            if s3_exists(client, s.s3_bucket, object_key(r["sha256"], r["ext"])):
                stats["already_there"] += 1
                uri = f"s3://{s.s3_bucket}/{object_key(r['sha256'], r['ext'])}"
            else:
                if verify and sha256_file(p) != r["sha256"]:
                    stats["bad_hash"] += 1
                    log.error("local object %s does not match its sha256; skipped", p)
                    continue
                uri, created = s3_put(p, r["sha256"], r["ext"])
                stats["uploaded"] += created
            if switch:
                conn.execute("UPDATE file_object SET storage_path=%s WHERE id=%s", (uri, r["id"]))
                stats["switched"] += 1
            if stats["checked"] % 200 == 0:
                conn.commit()
                log.info("%s", stats)
        conn.commit()
    return stats
