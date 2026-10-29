"""document.data shapes, one Pydantic model per doc_class (DB_DESIGN section 5).

These models are the single definition: JSON Schema files are generated from them (schemas/*.json),
Qwen fills them via structured output, and validators.py checks document.data against the schema
before every write.

All fields are optional so deterministic code and Qwen can fill them incrementally; required-ness is
measured as fill rate in the validation report.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"
ISO_MONTH = r"^\d{4}-\d{2}$"
ISO_PARTIAL = r"^\d{4}(-\d{2}(-\d{2})?)?$"


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- AIS
class Applicability(_Data):
    categories: list[str] = Field(default_factory=list, description="Category codes as written, e.g. L, M1, N1")
    raw: str | None = Field(None, description="Verbatim applicability sentence from the scope clause")


class ContentsEntry(_Data):
    clause: str
    title: str
    page: str | None = None


class AnnexEntry(_Data):
    id: str
    title: str | None = None


class StatusChartEntry(_Data):
    amendment: int
    date: str | None = Field(None, pattern=ISO_PARTIAL)


class AisStandardData(_Data):
    title: str | None = None
    cover_month: str | None = Field(None, pattern=ISO_MONTH, description="Cover date as YYYY-MM")
    parts: list[str] = Field(default_factory=list)
    based_on: list[str] = Field(default_factory=list, description="e.g. UN R100, ECE R13")
    scope_text: str | None = None
    applicability: Applicability | None = None
    transitional_text: str | None = None
    deemed_compliance: list[str] = Field(default_factory=list, description="Older standards this one replaces")
    contents: list[ContentsEntry] = Field(default_factory=list)
    annexes: list[AnnexEntry] = Field(default_factory=list)
    status_chart: list[StatusChartEntry] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list, description="Cited AIS/IS/UN R/ISO codes")
    arai_code_raw: str | None = None


class AmendmentInstruction(_Data):
    action: Literal["add", "substitute", "delete", "renumber", "correct", "other"]
    clause: str | None = None
    clauses: list[str] = Field(default_factory=list)
    after: str | None = None
    text: str | None = None


class AisAmendmentData(_Data):
    amends: str | None = Field(None, description="canonical_id of the amended standard, e.g. AIS-038(Rev.2)")
    amendment_no: int | None = None
    corrigendum_no: int | None = None
    issued: str | None = Field(None, pattern=ISO_PARTIAL)
    issued_precision: Literal["day", "month", "year"] | None = None
    header_format: Literal["no_date", "month_year", "full_date"] | None = None
    instructions: list[AmendmentInstruction] = Field(default_factory=list)


class AisDraftData(_Data):
    draft_of: str | None = None
    title: str | None = None
    draft_stage: str | None = Field(None, description="D1..D10 | DF | F | revised")
    comments_until: str | None = Field(None, pattern=ISO_DATE)
    hosted_on: str | None = Field(None, pattern=ISO_DATE)
    finalized_draft: bool | None = None
    scope_text: str | None = None


class AisFormTableData(_Data):
    table_ref: str | None = None
    annex_of: str | None = None
    title: str | None = None
    rows: int | None = None


class AisInterpretationData(_Data):
    interprets: str | None = None
    title: str | None = None
    issued: str | None = Field(None, pattern=ISO_PARTIAL)


# ---------------------------------------------------------------- Notifications
class GazetteRef(_Data):
    part: str | None = None
    section: str | None = None
    sub_section: str | None = None
    gazette_id: str | None = Field(None, description="e.g. CG-DL-E-03092022-238578")
    issue_no: str | None = None


class DraftRef(_Data):
    canonical_id: str
    date: str | None = Field(None, pattern=ISO_DATE)


class Implementation(_Data):
    model_scope: Literal["new_models", "existing_models", "all", "registered_vehicles"] | None = None
    date: str | None = Field(None, pattern=ISO_DATE)
    rule: str | None = Field(None, description="Relative rule, e.g. 'twelve months from notification'")


class Bound(_Data):
    lt: float | None = None
    lte: float | None = None
    gt: float | None = None
    gte: float | None = None
    eq: float | None = None


class Conditions(_Data):
    engine_cc: Bound | None = None
    power_kw: Bound | None = None
    gvw_kg: Bound | None = None
    seats: Bound | None = None
    speed_kmh: Bound | None = None


class Provision(_Data):
    action: Literal[
        "insert",
        "substitute",
        "omit",
        "insert_row",
        "substitute_row",
        "omit_row",
        "amend_table_entry",
        "extend_date",
        "exempt",
        "commence",
        "other",
    ]
    target: str | None = Field(None, description="e.g. 'Rule 96(4A)' or 'SO-1365(E)-2004 Table Sr.26(b)'")
    subject: str | None = None
    standards: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    conditions: Conditions | None = None
    usage: list[str] = Field(default_factory=list)
    powertrains: list[str] = Field(default_factory=list)
    implementation: list[Implementation] = Field(default_factory=list)
    old_text: str | None = None
    new_text: str | None = None


class NotificationData(_Data):
    series: Literal["G.S.R.", "S.O."] | None = None
    number: str | None = Field(None, description="e.g. 888(E)")
    date: str | None = Field(None, pattern=ISO_DATE)
    gazette: GazetteRef | None = None
    file_no: str | None = None
    signatory: str | None = None
    powers: list[str] = Field(default_factory=list)
    official_title: str | None = None
    commencement: str | None = None
    draft_ref: DraftRef | None = None
    comment_period_days: int | None = None
    amends_targets: list[str] = Field(default_factory=list)
    amends_notification: list[str] = Field(default_factory=list, description="canonical_ids amended/corrected")
    provisions: list[Provision] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    other_ids: list[str] = Field(default_factory=list, description="Other G.S.R./S.O. ids in the same file")


# ---------------------------------------------------------------- TAP
class TapPart(_Data):
    part: str | None = None
    chapter: str | None = None
    title: str | None = None
    file: str | None = None


class TapAmendmentEntry(_Data):
    amd: int
    date: str | None = None
    pages: str | None = None


class TapDocumentData(_Data):
    doc_no: str | None = None
    issue: int | None = None
    parts: list[TapPart] = Field(default_factory=list)
    amendment_record: list[TapAmendmentEntry] = Field(default_factory=list)


# ---------------------------------------------------------------- other official documents
class CircularData(_Data):
    ref_no: str | None = None
    date: str | None = Field(None, pattern=ISO_DATE)
    addressees: list[str] = Field(default_factory=list)
    subject: str | None = None
    directions: list[str] = Field(default_factory=list)
    valid_until: str | None = Field(None, pattern=ISO_DATE)
    file_no: str | None = None


class FormTemplateData(_Data):
    form_no: str | None = None
    rule_ref: str | None = None
    purpose: str | None = None


class BisCatalogueRow(_Data):
    is_no: str
    title: str | None = None
    amendments: int | None = None
    reaffirmed: int | None = None


class BisCatalogueData(_Data):
    rows: list[BisCatalogueRow] = Field(default_factory=list)


class GenericData(_Data):
    """ACT, CONSOLIDATED_RULES, BIS_REGULATION, ENERGY_STANDARD, FUEL_ORDER, APPROVED_LIST, REPORT, OFF_TOPIC..."""

    title: str | None = None
    ref_no: str | None = None
    date: str | None = Field(None, pattern=ISO_PARTIAL)
    issuer_text: str | None = None
    summary: str | None = None
    references: list[str] = Field(default_factory=list)
    file_name: str | None = None


class TisStandardData(_Data):
    """TIS_STANDARD: a Thai mandatory standard (มอก.) as its TISI page gives it (regtrack/pipeline/thai.py)."""

    title: str | None = None  # Thai title
    tis_no: str | None = None  # as printed, e.g. "มอก. 721-2551"
    year_be: int | None = None  # Buddhist-Era year of the edition (the regulations.year column is CE)
    effective_date: str | None = Field(None, pattern=ISO_DATE)  # วันที่มีผลบังคับใช้
    scope_text: str | None = None  # ขอบข่าย
    hs_codes: list[str] = Field(default_factory=list)
    title_en: str | None = None  # English title: the PDF cover's, else a machine translation
    title_en_source: str | None = None  # "cover" (TISI's own wording) | "machine translation"
    scope_en: str | None = None  # machine translation of scope_text (labelled in the portal)
