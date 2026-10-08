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


# ====================================================================== backends
# STORAGE_BACKEND=local (default): objects live in STORAGE_DIR, file_object.storage_path is the local path.
# STORAGE_BACKEND=s3: objects live in an S3-compatible bucket (MinIO) under the same key
# <sha[:2]>/<sha>.<ext>; file_object.storage_path is s3://<bucket>/<key>. Write-once in both: an existing key is
# never written again; in a bucket created with object locking every object also gets a legal hold (no delete).

def object_key(sha: str, ext: str) -> str:
    return f"{sha[:2]}/{sha}.{ext}"


def is_s3_uri(storage_path: str) -> bool:
    return str(storage_path).startswith("s3://")


def split_s3_uri(uri: str) -> tuple[str, str]:
    bucket, _, key = uri[len("s3://"):].partition("/")
    return bucket, key


def s3_client():
    from minio import Minio

    s = get_settings()
    return Minio(s.s3_endpoint, access_key=s.s3_access_key, secret_key=s.s3_secret_key, secure=s.s3_secure)


_bucket_ready: dict[str, bool] = {}


def ensure_bucket(client=None, bucket: str | None = None) -> bool:
    """Create the bucket (with object locking) if missing. Returns True when objects get a legal hold."""
    client = client or s3_client()
    bucket = bucket or get_settings().s3_bucket
    if bucket in _bucket_ready:
        return _bucket_ready[bucket]
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket, object_lock=True)
    try:
        locked = client.get_object_lock_config(bucket) is not None
    except Exception:  # noqa: BLE001  bucket without object lock
        locked = False
    _bucket_ready[bucket] = locked
    return locked


def s3_exists(client, bucket: str, key: str) -> bool:
    from minio.error import S3Error

    try:
        client.stat_object(bucket, key)
        return True
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchObject", "NotFound"):
            return False
        raise


def s3_put(path_or_bytes: Path | bytes, sha: str, ext: str) -> tuple[str, bool]:
    """Upload once. Returns (s3 uri, created)."""
    import io

    s = get_settings()
    client = s3_client()
    locked = ensure_bucket(client, s.s3_bucket)
    key = object_key(sha, ext)
    uri = f"s3://{s.s3_bucket}/{key}"
    if s3_exists(client, s.s3_bucket, key):
        return uri, False
    extra = {}
    if locked:
        extra["legal_hold"] = True
    if isinstance(path_or_bytes, (bytes, bytearray)):
        client.put_object(s.s3_bucket, key, io.BytesIO(path_or_bytes), len(path_or_bytes),
                          metadata={"x-amz-meta-sha256": sha}, **extra)
    else:
        client.fput_object(s.s3_bucket, key, str(path_or_bytes), metadata={"x-amz-meta-sha256": sha}, **extra)
    return uri, True


def storage_uri(sha: str, ext: str) -> str:
    """Where an object is (or will be) stored for the configured backend."""
    s = get_settings()
    if s.storage_backend == "s3":
        return f"s3://{s.s3_bucket}/{object_key(sha, ext)}"
    return str(object_path(sha, ext))


def put_file(src: Path, ext: str | None = None) -> tuple[str, str, bool]:
    """Store a file with the configured backend. Returns (sha, storage_path, created)."""
    ext = ext or normalise_ext(src.name)
    if get_settings().storage_backend == "s3":
        sha = sha256_file(src)
        uri, created = s3_put(src, sha, ext)
        return sha, uri, created
    sha, p, created = store_file(src, ext)
    return sha, str(p), created


def put_bytes(data: bytes, ext: str) -> tuple[str, str, bool]:
    """Store bytes with the configured backend. Returns (sha, storage_path, created)."""
    if get_settings().storage_backend == "s3":
        sha = sha256_bytes(data)
        uri, created = s3_put(data, sha, ext)
        return sha, uri, created
    sha, p, created = store_bytes(data, ext)
    return sha, str(p), created


def open_local(storage_path: str) -> Path:
    """A local filesystem path for a stored object. Local backend: the path itself. S3: a verified copy in
    CACHE_DIR (downloaded once; the sha256 in the key is checked, so a corrupted copy is never used)."""
    if not is_s3_uri(storage_path):
        return Path(storage_path)
    bucket, key = split_s3_uri(storage_path)
    dst = get_settings().cache_dir / key
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=".dl-")
    os.close(fd)
    try:
        s3_client().fget_object(bucket, key, tmp)
        want = Path(key).stem
        if sha256_file(Path(tmp)) != want:
            raise OSError(f"{storage_path}: content does not match its sha256 key")
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dst
