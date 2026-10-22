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


def test_split_header_followed_by_contents_instruction():
    """'Contents' inside an amendment's own instructions must not hide its header (AIS-186 Amd 1, AIS-025 Amd 4)."""
    pages = [PageText(1, "AMENDMENT NO. 2 (06/2026)\nTo\nAIS-186 Approval of Motor Vehicles\n1. Clause 5 substitute").analyse(),
             PageText(2, "1/ 9\n\nAMENDMENT NO. 1 (05/2026)\nTo\nAIS-186 Approval of Motor Vehicles\n"
                         "1. Page II, Contents, Annexes\nRenumber existing Annexes").analyse(),
             PageText(3, "Amendment No 10 (11/2021)\nTo\nAIS-37: Standard Procedure for Type Approval").analyse(),
             PageText(4, "STATUS CHART OF THE STANDARD\nAmendment No. 1 to AIS-186 dated May 2026").analyse()]
    segs = split_ais(pages)
    assert [(s.kind, s.number, s.page_from) for s in segs] == [("amendment", 2, 1), ("amendment", 1, 2), ("amendment", 10, 3)]


def test_year_from_short_title_then_file_no():
    from regtrack.pipeline.analysis import FileAnalysis, fix_year_from_file_no
    from regtrack.pipeline.classify import ClassResult
    from regtrack.pipeline.identity import Identity

    def fa(title, file_no, year):
        ident = Identity(kind="notification", canonical_id=f"GSR-212(E)-{year}", series="G.S.R.", number="212(E)",
                         year=year, doc_date=None)
        f = FileAnalysis(ctx=None, cls=ClassResult(DocClass.NOTIFICATION_FINAL), identity=ident)
        f.official_title, f.file_no = title, file_no
        fix_year_from_file_no(f)
        return f

    # OCR'd heading date '20 IS' gave a wrong nearby year; the notification's own short title wins
    f = fa("Central Motor Vehicles (Fourth Amendment) Rules, 2015", "RT-11042/13/2008-MVL", 2005)
    assert f.identity.canonical_id == "GSR-212(E)-2015" and f.year_note["from"] == "GSR-212(E)-2005"
    # no short title: a notification cannot predate its file
    assert fa(None, "RT-11042/20/2005-MVL", 1989).identity.canonical_id == "GSR-212(E)-2005"
    # nothing better: unchanged, no note
    g = fa(None, "RT-11042/20/1988-MVL", 1989)
    assert g.identity.canonical_id == "GSR-212(E)-1989" and g.year_note is None


def test_identity_from_amendment_headers():
    from regtrack.pipeline.identity import Identity
    from regtrack.pipeline.split import Segment
    from regtrack.pipeline.stages import identity_from_headers

    cover = Identity(kind="ais", canonical_id="AIS-007", number="007", family_key="AIS-007")
    segs = [Segment("amendment", 1, 2, 2, target_raw="AIS-071(Part 2):2009"), Segment("base", 3, 3),
            Segment("amendment", 4, 21, 1, target_raw="AIS-071(Part 2):2009")]
    i = identity_from_headers(cover, segs)
    assert i.canonical_id == "AIS-071(Part2)" and i.family_key == "AIS-071(Part2)"
    same = [Segment("amendment", 1, 1, 1, target_raw="AIS-007 (Rev.5)")]
    assert identity_from_headers(cover, same) is cover


def test_notification_heading_tolerates_ocr():
    """The operative heading is found when OCR lowercases the opening words or turns the dash into '_'."""
    for text, want in (
            ("MINISTRY OF ROAD TRANSPORT AND HIGHWAYS NOTIFICATION New Delhi, the 31 st May, 2002 G.s.R400(E).- whereas "
             "the draft of certain rules", "GSR-400(E)-2002"),
            ("NOTIFICATION New Delhi, the 3l st Augus! 2015 G.s.R.673(E)._Thefollowingdraftofcertainrules", "GSR-673(E)-2015"),
            ("NOTIFICATION New Delhi, the 2nd September, 2022 G.S.R. 680(E).—the draft rules the Inter-Country",
             "GSR-680(E)-2022"),
            ("NOTIFICATION New Delhi, the 12th August, 2022 S.O. 3896(E).—In exercise of the powers", "SO-3896(E)-2022")):
        idt = notification_identity(text)
        assert idt and idt.canonical_id == want, (text[:60], idt)
    # a citation is still not a heading
    assert notification_identity("as published vide notification number G.S.R. 31(E) dated the 15th January, 2002, "
                                 "and the draft rules") is None


# ---------------------------------------------------------------- Thailand: TISI mandatory-standard pages
def tisi_ctx(name: str, category: str, title: str) -> FileCtx:
    r = extract(FX / name, "html")
    return FileCtx(None, "2" * 64, "html", ["05_MoRTH_Gazette_Notifications"], [], r.pages, r.page_count, r.text_layer,
                   [], [{"source": "TH_TISI_MANDATORY", "title": title, "date": None, "category": category, "raw": {}}])


def test_tisi_page_is_decoded_from_its_declared_charset():
    from regtrack.pipeline.text import html_encoding

    raw = (FX / "tisi_65_seat_belt.html").read_bytes()
    assert html_encoding(raw) == "cp874"
    assert "เข็มขัดนิรภัยสำหรับรถยนต์" in extract(FX / "tisi_65_seat_belt.html", "html").pages[0].text
    assert html_encoding(b"<html><body>plain</body></html>") == "utf-8"


def test_tisi_circuit_breaker_is_off_topic():
    # มอก.60947-2 low-voltage circuit breakers (MCB): on TISI's mandatory list, but not a vehicle standard
    fa = identify(tisi_ctx("tisi_184_circuit_breaker.html", "ไฟฟ้ากำลัง",
                           "มอก.60947 เล่ม 2-2569 สวิตช์เกียร์และเกียร์ควบคุมไฟฟ้าแรงดันต่ำ เล่ม 2 เครื่องตัดวงจร"))
    assert fa.cls.doc_class == DocClass.OFF_TOPIC
    assert fa.cls.issuer == "TISI"


def test_tisi_lpg_cylinder_excluding_engines_is_off_topic():
    # its scope names engine tanks only as an exclusion ("ไม่ครอบคลุมถังสำหรับเครื่องยนต์สันดาปภายใน")
    fa = identify(tisi_ctx("tisi_46_lpg_cylinder.html", "เครื่องกล", "มอก.27-2543 ถังก๊าซปิโตรเลียมเหลว"))
    assert fa.cls.doc_class == DocClass.OFF_TOPIC


def test_tisi_seat_belt_is_an_in_scope_tis_standard():
    from regtrack.pipeline import thai
    from regtrack.pipeline.text import full_text

    ctx = tisi_ctx("tisi_65_seat_belt.html", "ยานยนต์", "มอก.721-2551 เข็มขัดนิรภัยสำหรับรถยนต์")
    fa = identify(ctx)
    assert fa.cls.doc_class == DocClass.TIS_STANDARD
    assert (fa.canonical_id, fa.identity.year, fa.identity.family_key) == ("TIS-721-2551", 2008, "TIS-721")
    assert fa.title_mismatch == []
    text = full_text(ctx.pages)
    assert thai.categories_of(text) == ["M1", "N1"]
    assert in_scope(thai.categories_of(text), "TH")
    f = thai.fields_of(text)
    assert f["title"] == "เข็มขัดนิรภัยสำหรับรถยนต์"
    assert f["effective_date"] == "2011-02-26"  # "26 ก.พ. 54": two-digit Buddhist-Era year
    assert "8708.21.00.000" in f["hs_codes"]
    assert validate_data("TIS_STANDARD", {k: v for k, v in f.items() if v not in (None, [])}) == []


def test_tisi_identity_comes_from_the_page_not_the_listing():
    fa = identify(tisi_ctx("tisi_65_seat_belt.html", "ยานยนต์", "มอก.722-2551 something else"))
    assert fa.canonical_id == "TIS-721-2551"
    assert fa.title_mismatch[0]["claimed"] == ["TIS-722-2551"]


def test_tisi_bare_class_letters_and_title_only_vehicle_words():
    from regtrack.pipeline import thai
    from regtrack.pipeline.text import full_text

    glass = full_text(extract(FX / "tisi_116_safety_glass.html", "html").pages)  # "ประเภท L ... M N O และ T"
    assert thai.categories_of(glass) == ["L1", "L3", "M1", "N1"]
    breaker = full_text(extract(FX / "tisi_184_circuit_breaker.html", "html").pages)  # "ภาคผนวก L" = Annex L
    assert thai.categories_of(breaker) == []
    tank = tisi_ctx("tisi_63_engine_lpg_tank.html", "เครื่องกล", "มอก.370-2552 ถังก๊าซปิโตรเลียมเหลวสำหรับเครื่องยนต์สันดาปภายใน")
    assert identify(tank).cls.doc_class == DocClass.TIS_STANDARD
    assert thai.categories_of(full_text(tank.pages)) == []  # no vehicle named: empty, flagged by extract


def test_thai_dates():
    from regtrack.pipeline.thai import parse_thai_date, tis_number

    assert parse_thai_date("14 ก.ค. 2551") == date(2008, 7, 14)
    assert parse_thai_date("1 ม.ค. 68") == date(2025, 1, 1)
    assert parse_thai_date("ไม่ระบุ") is None
    assert tis_number("มอก.60947 เล่ม 2-2569")["canonical_id"] == "TIS-60947(Part2)-2569"


# ---------------------------------------------------------------- Malaysia: JPJ / DOE pages
def my_text(name: str) -> str:
    return english_text(extract(FX / name, "html").pages)


def test_my_cta_component_table():
    from regtrack.pipeline import malaysia

    comps = {c["component"]: c for c in malaysia.cta_components(my_text("my_jpj_cta.html"))}
    assert len(comps) == 11
    assert comps["Protective Helmet"]["refs"][0] == "UNR-22" and comps["Protective Helmet"]["vehicle_categories"] == ["L1", "L3"]
    assert comps["Safety Seatbelts"]["refs"] == ["UNR-16"]
    assert {"UNR-54", "UNR-108", "UNR-109"} <= set(comps["New Pneumatic Tyres & New Retreaded Pneumatic Tyres"]["refs"])


def test_my_doe_type_approval_stages():
    from regtrack.pipeline import malaysia

    st = {s["key"]: s for s in malaysia.doe_stages(my_text("my_doe_emission.html"))}
    assert st["MY-DOE-TA-PETROL"]["effective_date"] == date(2000, 1, 1)
    assert st["MY-DOE-TA-DIESEL"]["effective_date"] == date(1997, 1, 1)  # "diesel vehicles" inside the text is no heading
    assert "Second Schedule" in st["MY-DOE-TA-DIESEL"]["legal_basis"]
    assert "50% opacity" in st["MY-DOE-INUSE-DIESEL-SMOKE"]["subject"]


def test_my_classify_and_identity():
    r = extract(FX / "my_jpj_cta.html", "html")
    ctx = FileCtx(None, "3" * 64, "html", ["05_x"], ["component-type-approval-cta.html"], r.pages, r.page_count,
                  r.text_layer, [], [{"source": "MY_JPJ_CTA", "title": "x", "date": None, "category": "page", "raw": {}}])
    fa = identify(ctx)
    assert fa.cls.doc_class == DocClass.MY_GUIDELINE
    assert fa.canonical_id == "MY-JPJ-COMPONENT-TYPE-APPROVAL-CTA"


def test_my_page_hash_ignores_counters():
    from regtrack.sources.malaysia import page_listing

    url = "https://www.doe.gov.my/en/emission-control-from-motor-vehicles/"
    raw = (FX / "my_doe_emission.html").read_bytes()
    assert b"<code>22 October 2026 @ 4:39 pm</code>" in raw  # the stamp changes on every request
    a, _ = page_listing("MY_DOE_EMISSION", url, raw)
    b, _ = page_listing("MY_DOE_EMISSION", url, raw.replace(b"22 October 2026 @ 4:39 pm", b"23 October 2026 @ 9:30 am"))
    c, _ = page_listing("MY_DOE_EMISSION", url, raw.replace(b"1 January 1997", b"1 January 1998"))
    assert a.item_id == b.item_id != c.item_id  # only a change of the page's own content is a new version
    _, files = page_listing("MY_JPJ_CTA", "https://www.jpj.gov.my/en/component-type-approval-cta/",
                            (FX / "my_jpj_cta.html").read_bytes())
    assert {f.file_name for f in files} == {"BORANG-PERMOHONAN-CTA-2021.rev0_.pdf", "Garis-Panduan-CTA-2020.pdf"}
