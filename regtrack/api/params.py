"""Query parameters shared by the read API and the portal."""

from __future__ import annotations

from typing import Annotated

from fastapi import HTTPException, Query

from regtrack import country

# ?country=TH; without it, the COUNTRY setting (regtrack/country.py). Annotated keeps the default a real None, so
# endpoints can also be called as plain functions (the report builder does).
CountryParam = Annotated[str | None, Query(alias="country", description="Country code (IN, TH); default: the COUNTRY setting")]


def resolve_country(value: str | None) -> str:
    try:
        return country.code(value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
