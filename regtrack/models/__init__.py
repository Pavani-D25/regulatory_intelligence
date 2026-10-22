"""Pydantic models (one per doc_class), enums, and JSON Schema export."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from regtrack.models.data import (
    AisAmendmentData,
    AisDraftData,
    AisFormTableData,
    AisInterpretationData,
    AisStandardData,
    BisCatalogueData,
    CircularData,
    FormTemplateData,
    GenericData,
    NotificationData,
    TapDocumentData,
    TisStandardData,
)
from regtrack.models.enums import DocClass

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

DATA_MODEL: dict[DocClass, type[BaseModel]] = {
    DocClass.AIS_STANDARD: AisStandardData,
    DocClass.AIS_AMENDMENT: AisAmendmentData,
    DocClass.AIS_CORRIGENDUM: AisAmendmentData,
    DocClass.AIS_DRAFT: AisDraftData,
    DocClass.AIS_FORM_TABLE: AisFormTableData,
    DocClass.AIS_INTERPRETATION: AisInterpretationData,
    DocClass.SAFETY_STANDARD_LEGACY: AisStandardData,
    DocClass.TAP_DOCUMENT: TapDocumentData,
    DocClass.TAP_AMENDMENT: TapDocumentData,
    DocClass.NOTIFICATION_DRAFT: NotificationData,
    DocClass.NOTIFICATION_FINAL: NotificationData,
    DocClass.NOTIFICATION_ORDER: NotificationData,
    DocClass.NOTIFICATION_CORRIGENDUM: NotificationData,
    DocClass.NOTIFICATION_EXEMPTION: NotificationData,
    DocClass.NOTIFICATION_EXTENSION: NotificationData,
    DocClass.CIRCULAR_OM: CircularData,
    DocClass.GUIDELINE_POLICY: CircularData,
    DocClass.FORM_TEMPLATE: FormTemplateData,
    DocClass.BIS_CATALOGUE: BisCatalogueData,
    DocClass.TIS_STANDARD: TisStandardData,
}


def model_for(doc_class: str | DocClass) -> type[BaseModel]:
    return DATA_MODEL.get(DocClass(doc_class), GenericData)


def schema_for(doc_class: str | DocClass) -> dict:
    return model_for(doc_class).model_json_schema()


def export_schemas(out: Path = SCHEMA_DIR) -> list[Path]:
    """Write one JSON Schema file per doc_class (generated, never hand-edited)."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for dc in DocClass:
        p = out / f"{dc.value}.json"
        schema = schema_for(dc)
        schema["$id"] = f"regtrack/{dc.value}"
        schema["title"] = f"{dc.value} ({model_for(dc).__name__})"
        p.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(p)
    return written


if __name__ == "__main__":
    for p in export_schemas():
        print(p)
