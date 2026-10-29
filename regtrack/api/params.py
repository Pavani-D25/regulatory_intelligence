"""Query parameters shared by the read API and the portal."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Annotated

from fastapi import HTTPException, Query

from regtrack import country

# ?country=TH; without it, the COUNTRY setting (regtrack/country.py). Annotated keeps the default a real None, so
# endpoints can also be called as plain functions (the report builder does).
CountryParam = Annotated[
    str | None, Query(alias="country", description="Country code (IN, TH); default: the COUNTRY setting")
]


def resolve_country(value: str | None) -> str:
    try:
        return country.code(value)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ?year=2024 on any request (the portal's year selector): the publication year the list views show. Set per request by
# the middleware in app.py; read where a view lists regulations (sql.docs(yearly=True), year_sql). Lookups of one
# regulation (detail, versions, files) ignore it.
YEAR: ContextVar[int | None] = ContextVar("regtrack_year", default=None)


def parse_year(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        y = int(raw)
    except ValueError:
        y = 0
    if not 1900 <= y <= 2100:
        raise ValueError("year must be a year such as 2024")
    return y


def year_sql(alias: str, column: str = "published_date", keep_null: bool = False) -> str:
    """' AND <alias>.<column> in the selected year' (empty without one); keep_null keeps rows without that table."""
    y = YEAR.get()
    if not y:
        return ""
    cond = f"extract(year FROM {alias}.{column}) = {int(y)}"
    return f" AND ({alias}.id IS NULL OR {cond})" if keep_null else f" AND {cond}"


# ?variant=ev|hybrid|ice (the portal's powertrain selector): regulations specific to that powertrain. Regulations with
# no powertrain (general rules for every vehicle) are not specific to any, so they are left out; hydrogen (fuel cell or
# combustion) is in none of the three.
VARIANT: ContextVar[str | None] = ContextVar("regtrack_variant", default=None)
VARIANTS = {
    "ev": (
        "EV",
        "g.powertrains && '{bev}' OR EXISTS (SELECT 1 FROM regulation_domains rd JOIN domains dm ON dm.id = rd.domain_id "
        "WHERE rd.regulation_id = g.id AND lower(dm.code) IN ('battery', 'charging'))",
    ),
    "hybrid": ("Hybrid", "g.powertrains && '{hybrid}'"),
    "ice": ("ICE", "g.powertrains && '{petrol,diesel,cng,lpg,ethanol_flex,biodiesel,lng,methanol}'"),
}


def parse_variant(raw: str | None) -> str | None:
    if not raw:
        return None
    v = raw.lower()
    if v not in VARIANTS:
        raise ValueError("variant is ev, hybrid or ice")
    return v


def variant_sql(alias: str, keep_null: bool = False) -> str:
    """' AND <alias> is specific to the selected powertrain variant' (empty without one); alias = a regulations row."""
    v = VARIANT.get()
    if not v:
        return ""
    cond = "(" + VARIANTS[v][1].replace("g.", f"{alias}.") + ")"
    return f" AND ({alias}.id IS NULL OR {cond})" if keep_null else f" AND {cond}"


def view_sql(alias: str, keep_null: bool = False) -> str:
    """The portal's view filters (year, powertrain variant) on a regulations row."""
    return year_sql(alias, keep_null=keep_null) + variant_sql(alias, keep_null=keep_null)


def view_label() -> str:
    """'published in 2024, EV' for report headings; empty without filters."""
    parts = ([f"published in {YEAR.get()}"] if YEAR.get() else []) + (
        [VARIANTS[VARIANT.get()][0]] if VARIANT.get() else []
    )
    return ", ".join(parts)
