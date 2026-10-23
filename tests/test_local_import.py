"""Hand-saved documents (TH_LOCAL / MY_LOCAL): Thai law rules, OCR language choice, the folder listing.
Synthetic text only: no test document enters the real database."""

from datetime import date

from regtrack.pipeline import ocr, thai

MR = """กฎกระทรวง
ฉบับที่ ๕ (พ.ศ. ๒๕๕๑)
ออกตามความในพระราชบัญญัติรถยนต์ พ.ศ. ๒๕๒๒
อาศัยอำนาจตามความในมาตรา ๕ ... รัฐมนตรีว่าการกระทรวงคมนาคมออกกฎกระทรวงไว้ ดังต่อไปนี้
ข้อ ๑ รถยนต์ต้องมีโคมไฟหน้า ไฟท้าย และไฟเลี้ยว ... ห้ามล้อต้องใช้การได้ดี ... ความกว้างของรถไม่เกิน ๒.๕๐ เมตร
ให้ไว้ ณ วันที่ ๑๒ มีนาคม พ.ศ. ๒๕๕๑"""

DLT = """ประกาศกรมการขนส่งทางบก
เรื่อง กำหนดมาตรฐานความปลอดภัยของรถยนต์ไฟฟ้า และความเข้ากันได้ทางแม่เหล็กไฟฟ้า
อาศัยอำนาจตามความใน ... แบตเตอรี่ขับเคลื่อน ... ตามข้อกำหนด UN R100 และ R10
ประกาศ ณ วันที่ ๒๐ ตุลาคม พ.ศ. ๒๕๖๕"""

ACT = """พระราชบัญญัติรถยนต์ พ.ศ. ๒๕๒๒
... การจดทะเบียนรถ ..."""


def test_thai_law_class_and_identity():
    assert thai.law_class(MR) == "MINISTERIAL_REGULATION"
    n = thai.law_identity(MR, "MINISTERIAL_REGULATION")
    assert n["canonical_id"] == "TH-MR-MOT-5-2551"  # Thai numerals, ministry from the text
    assert n["date"] == date(2008, 3, 12) and n["year"] == 2008
    assert set(thai.law_domains(MR)) >= {"LIGHTING", "BRAKING", "DIMENSIONS_WEIGHTS"}

    assert thai.law_class(DLT) == "DLT_NOTIFICATION"
    d = thai.law_identity(DLT, "DLT_NOTIFICATION")
    assert d["canonical_id"].startswith("TH-DLT-2565-") and d["date"] == date(2022, 10, 20)
    assert "รถยนต์ไฟฟ้า" in d["title"]
    assert {"EV_ALT_FUEL", "BATTERY"} <= set(thai.law_domains(DLT))

    assert thai.law_class(ACT) == "TH_ACT"
    a = thai.law_identity(ACT, "TH_ACT")
    assert a["canonical_id"].startswith("TH-ACT-2522-") and "REGISTRATION" in thai.law_domains(ACT)
    # the same content always gives the same id (identity from content, re-runs write nothing)
    assert thai.law_identity(ACT, "TH_ACT")["canonical_id"] == a["canonical_id"]


def test_thai_law_rules_back_the_register_rows():
    from regtrack.pipeline.country_mandates import RULES

    def rows_for(doc_class, domains, subject=""):
        r = {"doc_class": doc_class, "domains": domains, "subject": subject, "refs": "", "canonical_id": "x",
             "sources": {"TH_LOCAL"}}
        return {code for code, _, pred in RULES["TH"] if pred(r)}

    assert {"TH-07", "TH-08", "TH-10"} <= rows_for("MINISTERIAL_REGULATION", ["LIGHTING", "BRAKING", "DIMENSIONS_WEIGHTS"])
    assert {"TH-13", "TH-14"} <= rows_for("DLT_NOTIFICATION", ["EV_ALT_FUEL"], "ความเข้ากันได้ทางแม่เหล็กไฟฟ้า")
    assert "TH-02" in rows_for("TH_ACT", [])
    assert "TH-15" in rows_for("GAZETTE_NOTICE", ["FUEL_EFFICIENCY"])
    assert "TH-13" not in rows_for("TIS_STANDARD", ["EV_ALT_FUEL"])  # NGV/LPG car standard is not EV safety


def test_ocr_language_per_country():
    assert ocr.ocr_lang("TH") == ("th", "tha+eng")  # Thai documents print English too (cover titles)
    assert ocr.ocr_lang("MY")[0] == "en-US" and ocr.ocr_lang("IN") == ("en-US", "eng")
    assert ocr.can_ocr("tesseract", "TH") and not ocr.can_ocr(None, "IN")
    # Windows OCR reads Thai only once the Thai OCR language is installed in Windows settings
    assert ocr.can_ocr("windows_ocr", "TH") == ocr.windows_language_installed("th")


def test_local_listing_ids_follow_content(tmp_path, monkeypatch):
    from regtrack import config
    from regtrack.sources import local_import

    (tmp_path / "TH" / "dlt").mkdir(parents=True)
    f = tmp_path / "TH" / "dlt" / "notice.pdf"
    f.write_bytes(b"%PDF-1.4 first")
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    try:
        a = local_import.listings("TH_LOCAL")
        f.write_bytes(b"%PDF-1.4 replaced")
        b = local_import.listings("TH_LOCAL")
        assert len(a) == len(b) == 1 and a[0].item_id.startswith("dlt/notice.pdf#")
        assert a[0].item_id != b[0].item_id  # a replaced file is a new version
        assert local_import.listings("MY_LOCAL") == []  # no MY folder: nothing, no error
    finally:
        config.get_settings.cache_clear()


def test_tesseract_thai_spacing_and_confidence():
    from regtrack.pipeline.ocr import heuristic_confidence, join_thai

    raw = "ท ่ อ ไอ เส ี ย ร ถ จ ั ก ร ย า น ย น ต ์ เล ข ท ี ่ ม อ ก . 341-2528"
    text = join_thai(raw)
    assert text.startswith("ท่อไอเสียรถจักรยานยนต์") and "มอก . 341-2528" in text
    assert thai.tis_number(text)["canonical_id"] == "TIS-341-2528"  # "มอก ." as Tesseract writes it
    assert heuristic_confidence("มาตรฐานผลิตภัณฑ์อุตสาหกรรม ท่อไอเสียรถจักรยานยนต์ ที่ต้องเป็นไปตามมาตรฐาน") > 0.8
    assert heuristic_confidence("ราคพอ «8 ว๒ 08 หห 071080 ช 0105 5 พฐแบราร «= ฆ <") < 0.8  # OCR junk scores lower


def test_thai_pages_are_chunked_with_their_language():
    from regtrack.pipeline.chunk import chunk_language, chunk_pages
    from regtrack.pipeline.text import PageText

    thai_page = PageText(1, "1. ขอบข่าย\n" + "มาตรฐานผลิตภัณฑ์อุตสาหกรรมนี้ครอบคลุมท่อไอเสียรถจักรยานยนต์ " * 8).analyse()
    assert chunk_pages([thai_page]) == []  # India's rule: English pages only
    chunks = chunk_pages([thai_page], all_scripts=True)  # Thailand / Malaysia: every page with text
    assert chunks and chunk_language(chunks[0].content) == "th"
    assert chunk_language("This marking shall only be mandatory for tyre types") == "en"


def test_english_cover_titles():
    assert thai.nice_case("LIQUEFIED  PETROLEUM  GAS  CYLINDERS ON WET SURFACES") == "Liquefied Petroleum Gas Cylinders on Wet Surfaces"
    assert thai.nice_case("UN R100 ELECTRIC VEHICLES, LEVEL 10") == "UN R100 Electric Vehicles, Level 10"
    cover = "มอก. 341\nUDC 621.43.06:629.118.6\nSTANDARD FOR MOTORCYCLE EXHAUST\nMUFFLER\n<<<PAGE 2>>>\nTHAI INDUSTRIAL STANDARD"
    assert thai.english_cover_title(cover) == "Standard for Motorcycle Exhaust Muffler"
    assert thai.english_cover_title("ข้อความภาษาไทยเท่านั้น") is None


def test_malaysian_english_names():
    from regtrack.pipeline import malaysia

    assert malaysia.english_legal_title("act", "334", None) == "Commercial Vehicles Licensing Board Act 1987"
    assert (malaysia.english_legal_title("pua", None, "Peraturan-Peraturan Kualiti Alam Sekeliling (Kawalan Pelepasan Daripada "
                                                      "Enjin Diesel) (Pindaan) 2000")
            == "Environmental Quality (Control of Emissions from Diesel Engines) (Amendment) Regulations 2000")
    assert malaysia.document_title("BAHAGIAN KEJURUTERAAN AUTOMOTIF\nBORANG PERMOHONAN KELULUSAN JENIS KOMPONEN (COMPONENT "
                                   "TYPE APPROVAL)\nBUTIRAN PEMOHON :")[0] == "Component Type Approval (CTA) Application Form"
    assert malaysia.document_title("JAS/VTA (L)\nGUIDELINES\nAPPLICATION FOR MOTORCYCLES\nTYPE APPROVAL\nJULY 2016")[0] == \
        "Guidelines: Application for Motorcycles Type Approval"
