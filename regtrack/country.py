"""The one place that decides which country's rows a process sees (migration 0005).

Every query that picks work or shows data filters on the current country (setting COUNTRY, env REGTRACK_COUNTRY,
default 'IN'). Tables without a country column are filtered through their owner: mandate and chunk through
document, crawl_run and file_sighting through source.

    from regtrack import country
    cc = country.code()                                   # 'IN'
    sql = f"... FROM document d WHERE {country.sql('d', cc)}"   # d.country = 'IN'
"""

from __future__ import annotations

import re

from regtrack.config import get_settings

_CODE = re.compile(r"[A-Z]{2}")
# rows written before 0005 belong here (the default of every country column); also used for change events whose
# document was later retired (document_id NULL) - all of those are India's
LEGACY = "IN"


def code(value: str | None = None) -> str:
    """The country to use: `value` (an explicit ?country=) or the COUNTRY setting. Raises ValueError unless it is a
    two-letter code, which is what makes it safe to inline in SQL."""
    c = (value or get_settings().country).strip().upper()
    if not _CODE.fullmatch(c):
        raise ValueError(f"bad country code {value!r}")
    return c


def sql(alias: str | None = None, country: str | None = None) -> str:
    """`<alias>.country = '<CC>'` for a table with a country column (document, file_object, source)."""
    col = f"{alias}.country" if alias else "country"
    return f"{col} = '{code(country)}'"


def doc_sql(column: str, country: str | None = None) -> str:
    """For rows that point at a document (mandate.source_doc_id, chunk.document_id, change_event.document_id)."""
    return f"{column} IN (SELECT id FROM document WHERE {sql(None, country)})"


def event_sql(column: str, country: str | None = None) -> str:
    """change_event.document_id: events follow their document; an event without one is LEGACY's."""
    cc = code(country)
    return f"({doc_sql(column, cc)} OR ({column} IS NULL AND {str(cc == LEGACY).upper()}))"


def source_sql(column: str, country: str | None = None) -> str:
    """For rows that point at a source (crawl_run.source_id, file_sighting.source_id)."""
    return f"{column} IN (SELECT id FROM source WHERE {sql(None, country)})"


def flag_sql(alias: str | None = None, country: str | None = None) -> str:
    """quality_flag rows whose entity (document, file / file_object, mandate) belongs to the country."""
    p = f"{alias}." if alias else ""
    cc = code(country)
    return (f"(({p}entity = 'document' AND {doc_sql(p + 'entity_id', cc)})"
            f" OR ({p}entity IN ('file', 'file_object') AND {p}entity_id IN (SELECT id FROM file_object WHERE {sql(None, cc)}))"
            f" OR ({p}entity = 'mandate' AND {p}entity_id IN (SELECT id FROM mandate WHERE {doc_sql('source_doc_id', cc)}))"
            f" OR {p}entity NOT IN ('document', 'file', 'file_object', 'mandate'))")
