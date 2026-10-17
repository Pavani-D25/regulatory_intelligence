"""Controlled vocabularies: exactly the lists in DB_DESIGN section 3 (and the seed file)."""

from __future__ import annotations

from enum import StrEnum


class DocClass(StrEnum):
    AIS_STANDARD = "AIS_STANDARD"
    AIS_AMENDMENT = "AIS_AMENDMENT"
    AIS_CORRIGENDUM = "AIS_CORRIGENDUM"
    AIS_DRAFT = "AIS_DRAFT"
    AIS_FORM_TABLE = "AIS_FORM_TABLE"
    AIS_INTERPRETATION = "AIS_INTERPRETATION"
    SAFETY_STANDARD_LEGACY = "SAFETY_STANDARD_LEGACY"
    TAP_DOCUMENT = "TAP_DOCUMENT"
    TAP_AMENDMENT = "TAP_AMENDMENT"
    NOTIFICATION_DRAFT = "NOTIFICATION_DRAFT"
    NOTIFICATION_FINAL = "NOTIFICATION_FINAL"
    NOTIFICATION_ORDER = "NOTIFICATION_ORDER"
    NOTIFICATION_CORRIGENDUM = "NOTIFICATION_CORRIGENDUM"
    NOTIFICATION_EXEMPTION = "NOTIFICATION_EXEMPTION"
    NOTIFICATION_EXTENSION = "NOTIFICATION_EXTENSION"
    CIRCULAR_OM = "CIRCULAR_OM"
    GUIDELINE_POLICY = "GUIDELINE_POLICY"
    ACT = "ACT"
    CONSOLIDATED_RULES = "CONSOLIDATED_RULES"
    BIS_REGULATION = "BIS_REGULATION"
    BIS_CATALOGUE = "BIS_CATALOGUE"
    ENERGY_STANDARD = "ENERGY_STANDARD"
    FUEL_ORDER = "FUEL_ORDER"
    APPROVED_LIST = "APPROVED_LIST"
    FORM_TEMPLATE = "FORM_TEMPLATE"
    REPORT = "REPORT"
    OFF_TOPIC = "OFF_TOPIC"
    OTHER = "OTHER"
    # Thailand (migration 0005)
    TIS_STANDARD = "TIS_STANDARD"
    GAZETTE_NOTICE = "GAZETTE_NOTICE"
    DLT_NOTIFICATION = "DLT_NOTIFICATION"
    MINISTERIAL_REGULATION = "MINISTERIAL_REGULATION"
    NEWS = "NEWS"

    @property
    def is_notification(self) -> bool:
        return self.value.startswith("NOTIFICATION_")

    @property
    def is_ais(self) -> bool:
        return self.value.startswith("AIS_")


AIS_CLASSES = {c for c in DocClass if c.is_ais}
NOTIFICATION_CLASSES = {c for c in DocClass if c.is_notification}
THAI_CLASSES = frozenset({DocClass.TIS_STANDARD, DocClass.GAZETTE_NOTICE, DocClass.DLT_NOTIFICATION,
                          DocClass.MINISTERIAL_REGULATION, DocClass.NEWS})
# what India's classifier may answer (the Qwen prompt and its schema list exactly these)
INDIA_CLASSES = [c for c in DocClass if c not in THAI_CLASSES]


# ---- country-neutral classification (migration 0006, docs/CLASSIFICATION_DESIGN.md); the per-country mapping
#      from DocClass lives in the database table local_class, the derived fields in refresh_universal_fields()
class DocType(StrEnum):
    LAW = "LAW"
    REGULATION = "REGULATION"
    TECHNICAL_STANDARD = "TECHNICAL_STANDARD"
    PROCEDURE = "PROCEDURE"
    GUIDANCE = "GUIDANCE"
    REFERENCE = "REFERENCE"
    OFF_TOPIC = "OFF_TOPIC"
    UNKNOWN = "UNKNOWN"


class DocRole(StrEnum):
    BASE = "BASE"
    AMENDMENT = "AMENDMENT"
    CORRIGENDUM = "CORRIGENDUM"
    EXTENSION = "EXTENSION"
    EXEMPTION = "EXEMPTION"
    REPEAL = "REPEAL"
    CONSOLIDATION = "CONSOLIDATION"
    ANNEX = "ANNEX"
    INTERPRETATION = "INTERPRETATION"


class LegalForce(StrEnum):
    MANDATORY = "MANDATORY"
    VOLUNTARY = "VOLUNTARY"
    INFORMATIVE = "INFORMATIVE"
    UNKNOWN = "UNKNOWN"


class RelationType(StrEnum):
    AMENDS = "amends"
    CORRECTS = "corrects"
    REVISES = "revises"
    SUPERSEDES = "supersedes"
    FINALISES = "finalises"
    EXTENDS_DATE = "extends_date"
    EXEMPTS = "exempts"
    MANDATES = "mandates"
    INSERTS_ROW = "inserts_row"
    SUBSTITUTES_ROW = "substitutes_row"
    OMITS_ROW = "omits_row"
    ANNEX_OF = "annex_of"
    PART_OF = "part_of"
    INTERPRETS = "interprets"
    REFERENCES = "references"
    SAME_AS = "same_as"
    ADOPTS = "adopts"                # a national standard takes over an international one (TIS -> UN R)
    EQUIVALENT_TO = "equivalent_to"
    REPEALS = "repeals"


class Nature(StrEnum):
    TECHNICAL = "technical"
    ADMINISTRATIVE = "administrative"
    PROCEDURAL = "procedural"


class Status(StrEnum):
    DRAFT = "draft"
    FINAL = "final"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class Role(StrEnum):
    MAIN = "main"
    CONSOLIDATED_SEGMENT = "consolidated_segment"
    ANNEX_TABLE = "annex_table"
    HISTORICAL_COPY = "historical_copy"
    HINDI_ONLY = "hindi_only"


class Stage(StrEnum):
    DOWNLOADED = "downloaded"
    TEXT = "text"
    CLASSIFIED = "classified"
    PARSED = "parsed"
    LINKED = "linked"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    DONE = "done"
    FAILED = "failed"


STAGE_ORDER = [Stage.DOWNLOADED, Stage.TEXT, Stage.CLASSIFIED, Stage.PARSED, Stage.LINKED, Stage.CHUNKED,
               Stage.EMBEDDED, Stage.DONE]


class Domain(StrEnum):
    SAFETY_EQUIPMENT = "safety_equipment"
    BRAKING = "braking"
    LIGHTING = "lighting"
    EMISSION = "emission"
    FUEL_EFFICIENCY = "fuel_efficiency"
    EV_ALT_FUEL = "ev_alt_fuel"
    BATTERY = "battery"
    CHARGING = "charging"
    CYBERSECURITY = "cybersecurity"
    TRACKING_ITS = "tracking_its"
    TYPE_APPROVAL = "type_approval"
    DIMENSIONS_WEIGHTS = "dimensions_weights"
    REGISTRATION = "registration"
    NUMBER_PLATES = "number_plates"  # was "hsrp" (India only) until migration 0006
    LICENSING = "licensing"
    PERMIT = "permit"
    FEES = "fees"
    FITNESS_PUC = "fitness_puc"
    RECALL_SCRAPPAGE = "recall_scrappage"


class VehicleCategory(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"
    L7 = "L7"
    QUADRICYCLE = "QUADRICYCLE"
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    N1 = "N1"
    N2 = "N2"
    N3 = "N3"
    O = "O"  # noqa: E741  trailers O1-O4
    T = "T"  # tractors T1-T5
    CEV = "CEV"
    E_RICKSHAW = "E_RICKSHAW"
    E_CART = "E_CART"
    ALL = "ALL"


IN_SCOPE_CATEGORIES = frozenset({"L1", "L2", "M1", "N1", "ALL"})


class Usage(StrEnum):
    PRIVATE = "private"
    TRANSPORT = "transport"
    ALL = "all"


class Powertrain(StrEnum):
    PETROL = "petrol"
    DIESEL = "diesel"
    CNG = "cng"
    LPG = "lpg"
    ETHANOL_FLEX = "ethanol_flex"
    BIODIESEL = "biodiesel"
    HYDROGEN = "hydrogen"
    LNG = "lng"
    METHANOL = "methanol"
    HYBRID = "hybrid"
    BEV = "bev"
    ALL = "all"


class ModelScope(StrEnum):
    NEW_MODELS = "new_models"
    EXISTING_MODELS = "existing_models"
    ALL = "all"
    REGISTERED_VEHICLES = "registered_vehicles"


class ChangeEventType(StrEnum):
    NEW_DOCUMENT = "new_document"
    NEW_AMENDMENT = "new_amendment"
    NEW_REVISION = "new_revision"
    CORRIGENDUM = "corrigendum"
    DRAFT_PUBLISHED = "draft_published"
    DRAFT_FINALISED = "draft_finalised"
    IMPLEMENTATION_DATE_CHANGED = "implementation_date_changed"
    MANDATE_SUPERSEDED = "mandate_superseded"
    FILE_REISSUED = "file_reissued"
    LISTING_REMOVED = "listing_removed"


class FlagRule(StrEnum):
    TITLE_FILE_MISMATCH = "title_file_mismatch"
    PLACEHOLDER_LISTING_DATE = "placeholder_listing_date"
    LOW_OCR_CONFIDENCE = "low_ocr_confidence"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    AMENDMENT_GAP = "amendment_gap"
    DRAFT_FINAL_DATE_MISMATCH = "draft_final_date_mismatch"
    DUPLICATE_IDENTITY_DIFF_HEADER = "duplicate_identity_diff_header"
    OFF_TOPIC = "off_topic"
    SCHEMA_VIOLATION = "schema_violation"
    NO_VEHICLE_CATEGORY = "no_vehicle_category"
    IMPLEMENTATION_BEFORE_NOTIFICATION = "implementation_before_notification"
    IDENTITY_NOT_FOUND = "identity_not_found"
    LLM_DISAGREEMENT = "llm_disagreement"
    OCR_PENDING = "ocr_pending"
    DOC_DATE_IN_FUTURE = "doc_date_in_future"
    IDENTITY_YEAR_INFERRED = "identity_year_inferred"
