"""Write-once object storage: STORAGE_DIR/<sha[:2]>/<sha>.<ext>. Never overwrite, never delete."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from regtrack.config import get_settings

CHUNK = 1 << 20


def sha256_file(path: Path, chunk: int = CHUNK) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                h.update(block)
        return h.hexdigest()
    except MemoryError:  # low commit memory on the laptop: retry with small reads
        if chunk <= 1 << 14:
            raise
        import gc

        gc.collect()
        return sha256_file(path, chunk // 16)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_ext(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return ext if ext and len(ext) <= 5 and ext.isalnum() else "bin"


def object_path(sha: str, ext: str, root: Path | None = None) -> Path:
    root = root or get_settings().storage_dir
    return root / sha[:2] / f"{sha}.{ext}"


def store_file(src: Path, ext: str | None = None, root: Path | None = None) -> tuple[str, Path, bool]:
    """Copy src into storage. Returns (sha, path, created). Existing objects are left untouched."""
    sha = sha256_file(src)
    dst = object_path(sha, ext or normalise_ext(src.name), root)
    if dst.exists():
        return sha, dst, False
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".tmp-")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        if sha256_file(Path(tmp)) != sha:
            raise OSError(f"copy of {src} changed while copying")
        _finalise(Path(tmp), dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return sha, dst, True


def store_bytes(data: bytes, ext: str, root: Path | None = None) -> tuple[str, Path, bool]:
    sha = sha256_bytes(data)
    dst = object_path(sha, ext, root)
    if dst.exists():
        return sha, dst, False
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".tmp-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    try:
        _finalise(Path(tmp), dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return sha, dst, True


def _finalise(tmp: Path, dst: Path) -> None:
    try:
        os.link(tmp, dst)  # atomic create; fails if dst exists (never overwrite)
    except FileExistsError:
        return
    except OSError:
        if not dst.exists():
            shutil.copyfile(tmp, dst)
    os.remove(tmp)  # drop the temp name before marking the object read-only (they share an inode)
    try:
        os.chmod(dst, 0o444)  # read-only marks write-once on Windows too
    except OSError:
        pass


def open_local(storage_path: str) -> Path:
    """A local filesystem path for a stored object (local backend: the path itself)."""
    return Path(storage_path)
