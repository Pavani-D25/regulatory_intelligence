"""Validators. document.data is checked against the JSON Schema generated from its Pydantic model;
failures become quality_flags rows (no manual review step) and the value is kept, marked needs_check."""

from __future__ import annotations

from functools import lru_cache

from jsonschema import Draft202012Validator

from regtrack.models import schema_for
from regtrack.models.enums import IN_SCOPE_CATEGORIES


@lru_cache(maxsize=64)
def _validator(doc_class: str) -> Draft202012Validator:
    return Draft202012Validator(schema_for(doc_class))


def validate_data(doc_class: str, data: dict) -> list[str]:
    """Return schema errors as 'path: message' strings (empty list = valid)."""
    v = _validator(doc_class)
    return [f"{'/'.join(str(x) for x in e.absolute_path) or '$'}: {e.message[:200]}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(e.absolute_path))]


def in_scope(categories: list[str]) -> bool:
    return bool(set(categories) & IN_SCOPE_CATEGORIES)


def implementation_before_notification(impl, notified) -> bool:
    return bool(impl and notified and impl < notified)
