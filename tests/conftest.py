"""Shared fixtures. DB tests use a separate database regtrack_test (created on the same server) and are skipped
when PostgreSQL is not reachable."""

from __future__ import annotations

import pytest

from regtrack.config import get_settings


def _dsn(dbname: str) -> str:
    base = get_settings().psycopg_dsn.rsplit("/", 1)[0]
    return f"{base}/{dbname}"


@pytest.fixture(scope="session")
def test_dsn():
    import psycopg

    try:
        with psycopg.connect(get_settings().psycopg_dsn, autocommit=True, connect_timeout=3) as c:
            c.execute("DROP DATABASE IF EXISTS regtrack_test WITH (FORCE)")
            c.execute("CREATE DATABASE regtrack_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable: {str(e).splitlines()[0]}")
    return _dsn("regtrack_test")


@pytest.fixture(scope="session")
def migrated(test_dsn):
    from regtrack.migrate import migrate

    first = migrate(test_dsn)
    second = migrate(test_dsn)
    return test_dsn, first, second


@pytest.fixture()
def conn(migrated):
    from regtrack.db import connect

    c = connect(dsn=migrated[0])
    yield c
    c.rollback()
    c.close()
