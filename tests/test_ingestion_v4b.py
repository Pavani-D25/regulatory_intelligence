"""Phase 2 of the v4B move: crawlers write sources / ingestion_runs / raw_ingestion_records / documents.
Runs on regtrack_test with files stored in a temporary folder; the rows it commits are removed again."""

from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.db

PDF = b"%PDF-1.4\n" + b"test regulation " * 40  # over 200 bytes, starts like a PDF
TABLES = ("raw_ingestion_records", "documents", "ingestion_runs")


class FakeResponse:
    def __init__(self, content: bytes):
        self.status_code, self.content, self.headers = 200, content, {"content-type": "application/pdf"}


@pytest.fixture()
def ingest(migrated, monkeypatch, tmp_path):
    """A committed-to connection on the test database; downloads are faked and counted."""
    from regtrack import config
    from regtrack.db import connect
    from regtrack.sources import http

    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    config.get_settings.cache_clear()
    downloads: list[str] = []

    def fake_get(_client, url, **_kw):
        downloads.append(url)
        return FakeResponse(PDF)

    monkeypatch.setattr(http, "get", fake_get)
    conn = connect(dsn=migrated[0])
    before = {t: conn.execute(f"SELECT coalesce(max(id), 0) AS m FROM {t}").fetchone()["m"] for t in TABLES}
    yield conn, downloads
    conn.rollback()
    for t in TABLES:  # remove exactly what this test added
        conn.execute(f"DELETE FROM {t} WHERE id > %s", (before[t],))
    conn.execute("UPDATE sources SET last_synced_at=NULL, last_sync_status=NULL WHERE code='MORTH_API'")
    conn.commit()
    conn.close()
    config.get_settings.cache_clear()


def _listing(item_id: str, title: str = "S.O. 3896(E) regarding Wheel RIM third extension"):
    from regtrack.sources.common import Listing

    return Listing(
        item_id=item_id,
        url=f"https://morth.gov.in/backend/{item_id}.pdf",
        title=title,
        listing_date=date(2022, 8, 12),
        category="gazettes-notifications|Motor Vehicle Legislation",
        raw={"title": title},
        file_name=f"{item_id}.pdf",
    )


def _count(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()["n"]


def test_new_listing_downloads_once_and_rerun_writes_nothing(ingest):
    from regtrack.sources.common import RunStats, record_listing, start_run

    conn, downloads = ingest
    run = start_run(conn, "MORTH_API")
    stats = RunStats()
    record_listing(conn, None, "MORTH_API", run, _listing("test/a"), stats)
    assert (stats.seen, stats.new_files, stats.new_listings, len(downloads)) == (1, 1, 1, 1)
    doc = conn.execute("""SELECT d.* FROM documents d JOIN raw_ingestion_records r ON r.document_id = d.id
                          WHERE r.external_ref = 'test/a'""").fetchone()
    assert doc["stage"] == "downloaded" and doc["file_ext"] == "pdf" and len(doc["checksum_sha256"]) == 64
    assert doc["region_id"] == conn.execute("SELECT id FROM regions WHERE code='IN'").fetchone()["id"]
    assert doc["storage_path"].endswith(f"{doc['checksum_sha256']}.pdf")
    rec = conn.execute("SELECT * FROM raw_ingestion_records WHERE external_ref = 'test/a'").fetchone()
    assert rec["ingestion_run_id"] == run and rec["processing_status"] == "downloaded"
    assert rec["listing_title"].startswith("S.O. 3896(E)")  # the claim is kept as listed

    # the same listing again: known, nothing downloaded, nothing written (CLAUDE.md rule 7)
    n_docs, n_recs = (
        _count(conn, "SELECT count(*) AS n FROM documents"),
        _count(conn, "SELECT count(*) AS n FROM raw_ingestion_records"),
    )
    stats2 = RunStats()
    record_listing(conn, None, "MORTH_API", run, _listing("test/a"), stats2)
    assert (stats2.known, stats2.new_files, len(downloads)) == (1, 0, 1)
    assert _count(conn, "SELECT count(*) AS n FROM documents") == n_docs
    assert _count(conn, "SELECT count(*) AS n FROM raw_ingestion_records") == n_recs


def test_same_file_listed_twice_is_stored_once(ingest):
    from regtrack.sources.common import RunStats, record_listing, start_run

    conn, _ = ingest
    run = start_run(conn, "MORTH_API")
    stats = RunStats()
    record_listing(conn, None, "MORTH_API", run, _listing("test/b"), stats)
    record_listing(conn, None, "MORTH_API", run, _listing("test/c"), stats)  # other URL, same bytes
    assert (stats.new_listings, stats.new_files) == (2, 1)
    ids = {
        r["document_id"]
        for r in conn.execute(
            "SELECT document_id FROM raw_ingestion_records WHERE external_ref IN ('test/b', 'test/c')"
        )
    }
    assert len(ids) == 1


def test_listing_from_the_seed_log_is_linked_not_downloaded(ingest):
    from regtrack.sources.common import RunStats, record_listing, source_id, start_run, store_document

    conn, downloads = ingest
    region = conn.execute("SELECT id FROM regions WHERE code='IN'").fetchone()["id"]
    did, _ = store_document(conn, region, "b" * 64, "x.pdf", "x.pdf", None, "pdf", "application/pdf", 1)
    conn.execute(
        """INSERT INTO raw_ingestion_records (document_id, source_id, external_ref, listing_title, listing_date)
                    VALUES (%s, %s, 'morth_download_log.csv:seed.pdf', 'Seeded notice', DATE '2022-08-12')""",
        (did, source_id(conn, "MORTH_API")),
    )
    conn.commit()
    stats = RunStats()
    record_listing(
        conn, None, "MORTH_API", start_run(conn, "MORTH_API"), _listing("test/seeded", "Seeded notice"), stats
    )
    assert stats.known == 1 and downloads == []
    rec = conn.execute(
        "SELECT document_id, payload FROM raw_ingestion_records WHERE external_ref='test/seeded'"
    ).fetchone()
    assert rec["document_id"] == did and rec["payload"]["matched_seed"] is True


def test_run_status_and_gone_listings(ingest):
    from regtrack.sources.common import RunStats, finish_run, mark_gone, record_listing, start_run

    conn, _ = ingest
    run = start_run(conn, "MORTH_API")
    stats = RunStats()
    record_listing(conn, None, "MORTH_API", run, _listing("test/d"), stats)
    finish_run(conn, "MORTH_API", run, "partial", stats, "HTTP 404 for one link\nsecond line")
    r = conn.execute("SELECT * FROM ingestion_runs WHERE id=%s", (run,)).fetchone()
    assert (r["status"], r["documents_found"], r["changes_found"]) == ("warning", 1, 1)
    assert r["error_message"] == "HTTP 404 for one link"
    assert (
        conn.execute("SELECT last_sync_status FROM sources WHERE code='MORTH_API'").fetchone()["last_sync_status"]
        == "warning"
    )
    # the listing is no longer on the site after a complete pass
    assert mark_gone(conn, "MORTH_API", seen_ids=set()) >= 1
    assert conn.execute("SELECT gone_at FROM raw_ingestion_records WHERE external_ref='test/d'").fetchone()["gone_at"]


def test_region_filter():
    from regtrack import country

    assert country.region_sql("d", "th") == "d.region_id = (SELECT id FROM regions WHERE code = 'TH')"
