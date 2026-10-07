"""Offline preparation (no DB needed): hash the seed corpus, copy originals write-once into STORAGE_DIR,
and extract page text into TEXT_DIR. The DB stages later reuse these caches.

    python scripts/prepare_corpus.py [--workers 4]
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from regtrack.config import get_settings  # noqa: E402
from regtrack.pipeline.text import extract_cached  # noqa: E402
from regtrack.sources.seed_corpus import copy_to_storage, scan  # noqa: E402
from regtrack.storage import object_path  # noqa: E402


def _one(args: tuple[str, str, str]) -> tuple[str, int, bool, str | None]:
    sha, path, ext = args
    m = extract_cached(sha, Path(path), ext)
    return sha, m["page_count"], m["text_layer"], m["error"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    t0 = time.time()
    files = scan()
    print(f"scanned {len(files)} files, {len({f.sha256 for f in files})} unique sha256 ({time.time()-t0:.0f}s)", flush=True)
    print(f"copied {copy_to_storage(files)} new objects to {get_settings().storage_dir}", flush=True)
    uniq = {}
    for f in files:
        uniq.setdefault(f.sha256, f)
    jobs = [(sha, str(object_path(sha, f.ext)), f.ext) for sha, f in uniq.items()]
    done = 0
    with ProcessPoolExecutor(a.workers) as ex:
        futs = [ex.submit(_one, j) for j in jobs]
        for fu in as_completed(futs):
            sha, n, tl, err = fu.result()
            done += 1
            if err:
                print("ERR", sha[:12], err, flush=True)
            if done % 200 == 0:
                print(f"{done}/{len(jobs)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"text done for {done} files in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
