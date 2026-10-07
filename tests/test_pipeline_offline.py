"""Unit tests that need neither PostgreSQL nor the LLM (fixtures are small PDFs copied from the seed corpus)."""

from datetime import date
from pathlib import Path

import pytest

from regtrack.models import DATA_MODEL, export_schemas, model_for
from regtrack.models.enums import DocClass, RelationType
from regtrack.pipeline import mandates as M
from regtrack.pipeline.analysis import draft_reference, identify
from regtrack.pipeline.chunk import chunk_pages
from regtrack.pipeline.classify import FileCtx, classify, relevance
from regtrack.pipeline.extract import categories_of, operative_text
from regtrack.pipeline.identity import ais_identity, notification_identity
from regtrack.pipeline.split import amendment_gaps, split_ais
from regtrack.pipeline.text import PageText, build_result, english_text, extract, garbled_pages
from regtrack.storage import store_bytes
from regtrack.validators import in_scope, validate_data

FX = Path(__file__).parent / "fixtures"


def pages_of(name: str) -> list[PageText]:
    return extract(FX / name, "pdf").pages


def ctx_for(name: str, folder: str = "05_MoRTH_Gazette_Notifications", listings=None) -> FileCtx:
    r = extract(FX / name, "pdf")
    return FileCtx(None, "0" * 64, "pdf", [folder], [name], r.pages, r.page_count, r.text_layer, r.scanned_pages,
                   listings or [])


# ---------------------------------------------------------------- models / vocab
def test_every_doc_class_has_a_schema(tmp_path):
    files = export_schemas(tmp_path)
    assert len(files) == len(DocClass)
    assert model_for("NOTIFICATION_FINAL") is DATA_MODEL[DocClass.NOTIFICATION_FINAL]
    assert {r.value for r in RelationType} >= {"finalises", "extends_date", "inserts_row", "annex_of", "same_as"}


def test_validator_catches_bad_dates_and_unknown_keys():
    assert validate_data("NOTIFICATION_FINAL", {"series": "G.S.R.", "number": "888(E)", "date": "2022-12-19"}) == []
    assert validate_data("NOTIFICATION_FINAL", {"date": "19.12.2022"})
    assert validate_data("AIS_STANDARD", {"nonsense": 1})


def test_in_scope():
    assert in_scope(["L2", "M3"]) and in_scope(["ALL"]) and not in_scope(["M3", "T"])


# ---------------------------------------------------------------- storage
def test_storage_is_write_once(tmp_path):
    sha, p, created = store_bytes(b"%PDF-1.4 hello", "pdf", root=tmp_path)
    assert created and p.name == f"{sha}.pdf" and p.parent.name == sha[:2]
    sha2, p2, created2 = store_bytes(b"%PDF-1.4 hello", "pdf", root=tmp_path)
    assert (sha2, p2, created2) == (sha, p, False)
    assert not list(p.parent.glob(".tmp-*"))


# ---------------------------------------------------------------- text
def test_scan_detection_and_kruti():
    r = build_result(["", "short", "x" * 500], {}, is_paged=True)
    assert r.scanned_pages == [1, 2] and r.text_layer is True  # 505/3 >= 100 chars average
    r = build_result(["", "tiny"], {}, is_paged=True)
    assert r.text_layer is False
    r = build_result(["Hkkjr dk jkti=k % vlk/kkj.k " * 5, "The Central Government hereby makes the following rules " * 5],
                     {}, is_paged=True)
    assert r.language_mix["hi_legacy_font"] is True and r.english_pages == [2]


def test_english_pages_of_bilingual_gazette():
    pages = pages_of("so_359_2022_wheel_rim_extension.pdf")
    eng = english_text(pages)
    assert "S.O. 359(E)" in eng and garbled_pages(pages) == []


# ---------------------------------------------------------------- identity / classify
def test_identity_from_content_with_year():
    i = notification_identity(english_text(pages_of("so_3896_2022_wheel_rim_extension.pdf")))
    assert i.canonical_id == "SO-3896(E)-2022" and i.doc_date == date(2022, 8, 12)


def test_draft_notification_class_and_status():
    fa = identify(ctx_for("draft_notification.pdf", "02_CMVR_Amendments_Notifications"))
    assert fa.cls.doc_class == DocClass.NOTIFICATION_DRAFT and fa.cls.status == "draft"
    assert fa.canonical_id == "GSR-1118(E)-2017"


def test_extension_order_class():
    fa = identify(ctx_for("so_359_2022_wheel_rim_extension.pdf"))
    assert fa.canonical_id == "SO-359(E)-2022"
    assert fa.cls.doc_class in (DocClass.NOTIFICATION_EXTENSION, DocClass.NOTIFICATION_ORDER)


def test_title_mismatch_flagged():
    fa = identify(ctx_for("so_359_2022_wheel_rim_extension.pdf",
                          listings=[{"source": "MORTH_API", "title": "S.O. 395(E) regarding Wheel Rim", "date": None}]))
    assert fa.title_mismatch and fa.title_mismatch[0]["content"] == "SO-359(E)-2022"


def test_state_level_is_off_topic():
    text = ("GOVERNMENT OF RAJASTHAN\nTRANSPORT DEPARTMENT\nNOTIFICATION\nIn exercise of the powers conferred by the "
            "Rajasthan Motor Vehicles Taxation Act, 1951 the State Government hereby specifies the rate of tax payable on "
            "motor vehicles " * 8)
    ctx = FileCtx(None, "1" * 64, "pdf", ["02_CMVR_Amendments_Notifications"], ["2.pdf"],
                  [PageText(1, text).analyse()], 1, True)
    assert relevance(ctx)["state"] == "Rajasthan"
    assert classify(ctx).doc_class == DocClass.OFF_TOPIC


def test_draft_reference_regex():
    t = ("Whereas the draft rules further to amend the Central Motor Vehicles Rules, 1989 were published, as required "
         "under sub-section (1) of section 212 of the Motor Vehicles Act, 1988, vide notification number G.S.R. 117 (E), "
         "dated the 14th February, 2019 in the Gazette of India")
    assert draft_reference(t) == {"canonical_id": "GSR-117(E)-2019", "date": "2019-02-14"}
    draft_self = ("The following draft of certain rules ... is hereby published ... Note: The principal rules were "
                  "published vide notification number G.S.R. 590(E), dated the 2nd June, 1989")
    assert draft_reference(draft_self) is None


# ---------------------------------------------------------------- AIS split
def test_split_consolidated_ais():
    pages = [PageText(1, "AUTOMOTIVE INDUSTRY STANDARD\nAIS-038 (Rev.2)\nSeptember 2020\n").analyse()]
    pages += [PageText(i, f"clause text page {i} " * 20).analyse() for i in range(2, 6)]
    pages += [PageText(6, "AMENDMENT NO. 1 (05/2021)\nTO\nAIS-038 (Rev.2)\nClause 6.1 substitute").analyse(),
              PageText(7, "more amendment 1 text " * 10).analyse(),
              PageText(8, "Amendment No. 2 (08/2022) To AIS-038 (Rev.2)\nAdd new clause 6.12 after clause 6.11").analyse()]
    segs = split_ais(pages)
    assert [(s.kind, s.page_from, s.page_to, s.number) for s in segs] == [
        ("base", 1, 5, None), ("amendment", 6, 7, 1), ("amendment", 8, 8, 2)]
    assert segs[1].issued == "2021-05" and segs[1].header_format == "month_year"
    assert amendment_gaps([1, 2, 4]) == [3]
    assert ais_identity(pages[0].text).canonical_id == "AIS-038(Rev.2)"


# ---------------------------------------------------------------- mandates (wheel-rim chain)
def _op(name: str) -> str:
    return operative_text(english_text(pages_of(name)))


def test_so1365_row_substitution_items():
    items, dsubs, _ = M.parse_table_amendments(_op("so_1406_2021_wheel_rim.pdf"))
    keys = {i.key: i for i in items}
    it = keys["SO-1365(E)-2004 Table Sr.8(d)"]
    assert it.standards == ["IS 9438:2018"] and it.implementation_date == date(2021, 9, 21) and it.categories == ["O"]
    assert keys["SO-1365(E)-2004 Table Sr.8(b)"].categories[:1] == ["M1"]
    assert not dsubs


def test_so1365_date_substitutions():
    _, dsubs, _ = M.parse_table_amendments(_op("so_359_2022_wheel_rim_extension.pdf"))
    main = [d for d in dsubs if d.table == "SO-1365(E)-2004 Table"][0]
    assert main.serials == ["8", "43"] and main.old == date(2022, 3, 21) and main.new == date(2022, 9, 21)
    _, dsubs, _ = M.parse_table_amendments(_op("so_3896_2022_wheel_rim_extension.pdf"))
    assert {(tuple(d.serials), d.new) for d in dsubs if d.table.endswith("Table")} == {(("8",), date(2023, 6, 22)),
                                                                                    (("43",), date(2023, 6, 22))}


def test_rule_obligation_parser():
    op = ("In rule 96, after sub-rule (4), the following sub-rule shall be inserted, namely:- (4A) All motor cycles of "
          "category L2 manufactured on or after the 1st January, 2026 shall be fitted with anti-lock braking system "
          "conforming to IS 14664:2010, as amended from time to time.")
    obs = M.parse_rule_obligations(op)
    assert obs and obs[0].implementation_date == date(2026, 1, 1) and "IS 14664:2010" in obs[0].standards
    assert "L2" in obs[0].categories and obs[0].rule.startswith("CMVR Rule 96")


# ---------------------------------------------------------------- chunks / categories
def test_clause_chunks_and_boilerplate():
    text = ("1. SCOPE\n" + "This standard applies to vehicles of category L. " * 6 + "\n2. DEFINITIONS\n"
            + "2.1 Vehicle means a motor vehicle. " * 6 + "\nCOMPOSITION OF AISC PANEL\nConvener Representing ARAI\n" * 3)
    ch = chunk_pages([PageText(1, text).analyse()])
    assert [c.clause_no for c in ch][:2] == ["1", "2"]
    assert ch[0].heading.startswith("SCOPE")


def test_categories_from_text():
    assert categories_of("applicable to vehicles of category M1 and N1 and to all motor vehicles") == ["M1", "N1", "ALL"]


@pytest.mark.parametrize("name", sorted(p.name for p in FX.glob("*.pdf")))
def test_fixtures_extract(name):
    r = extract(FX / name, "pdf")
    assert r.page_count >= 1 and r.error is None
