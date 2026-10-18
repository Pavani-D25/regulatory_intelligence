"""The one place that decides which country's rows a process sees.

Every query that picks work or shows data filters on the current country (setting COUNTRY, env REGTRACK_COUNTRY,
default 'IN'). In the v4B schema a country is a region (table regions); tables carry region_id, and tables without
one are filtered through their owner (chunks and parts through their regulation, runs and listings through their
source).

    from regtrack import country
    cc = country.code()                                              # 'IN'
    sql = f"... FROM regulations g WHERE {country.region_sql('g', cc)}"
"""

from __future__ import annotations

import re

from regtrack.config import get_settings

_CODE = re.compile(r"[A-Z]{2}")


def code(value: str | None = None) -> str:
    """The country to use: `value` (an explicit ?country=) or the COUNTRY setting. Raises ValueError unless it is a
    two-letter code, which is what makes it safe to inline in SQL."""
    c = (value or get_settings().country).strip().upper()
    if not _CODE.fullmatch(c):
        raise ValueError(f"bad country code {value!r}")
    return c


def region_sql(alias: str | None = None, country: str | None = None) -> str:
    """`<alias>.region_id = <id of the country's region>` for the v4B tables (documents, regulations, sources…)."""
    col = f"{alias}.region_id" if alias else "region_id"
    return f"{col} = (SELECT id FROM regions WHERE code = '{code(country)}')"
