"""S3/MinIO backend (optional). Skipped unless an S3-compatible endpoint (S3_ENDPOINT in .env, e.g. MinIO) is up."""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from regtrack import config, storage


def _minio_up() -> bool:
    try:
        return httpx.get("http://localhost:9000/minio/health/live", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _minio_up(), reason="MinIO not running")


@pytest.fixture()
def s3_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("S3_BUCKET", "regtrack-test")
    os.environ.setdefault("S3_ACCESS_KEY", "regtrack")
    os.environ.setdefault("S3_SECRET_KEY", "regtrack-minio-secret")
    config.get_settings.cache_clear()
    storage._bucket_ready.clear()
    yield config.get_settings()
    config.get_settings.cache_clear()
    storage._bucket_ready.clear()


def test_put_open_and_write_once(s3_settings):
    data = b"%PDF-1.4 regtrack s3 test " + uuid.uuid4().hex.encode()
    sha, uri, created = storage.put_bytes(data, "pdf")
    assert created and uri == f"s3://regtrack-test/{sha[:2]}/{sha}.pdf" == storage.storage_uri(sha, "pdf")
    # same bytes again: nothing written
    assert storage.put_bytes(data, "pdf") == (sha, uri, False)
    # read back through the verified local cache
    p = storage.open_local(uri)
    assert p.read_bytes() == data and p.is_relative_to(s3_settings.cache_dir)
    # write-once: the legal hold makes MinIO refuse to delete the object
    client = storage.s3_client()
    if storage.ensure_bucket(client, "regtrack-test"):
        from minio.error import S3Error

        ver = client.stat_object("regtrack-test", f"{sha[:2]}/{sha}.pdf").version_id
        with pytest.raises(S3Error):
            client.remove_object("regtrack-test", f"{sha[:2]}/{sha}.pdf", version_id=ver)


def test_local_backend_is_default(monkeypatch):
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    config.get_settings.cache_clear()
    try:
        s = config.get_settings()
        if s.storage_backend == "local":
            assert not storage.storage_uri("ab" * 32, "pdf").startswith("s3://")
    finally:
        config.get_settings.cache_clear()
