from datetime import date

from regtrack.pipeline import patterns as P
from regtrack.pipeline.identity import ais_identity, notification_identity, parse_arai_code


def test_notification_canonical_includes_year():
    assert P.notification_canonical("G.S.R.", "659", 2022) == "GSR-659(E)-2022"
    assert P.notification_canonical("S.O.", "0411", 2016) == "SO-411(E)-2016"
    assert P.notification_canonical("GSR", 659, 2016) != P.notification_canonical("GSR", 659, 2022)


def test_parse_dates():
    assert P.parse_date("New Delhi, the 25th August, 2022") == date(2022, 8, 25)
    assert P.parse_date("dated 13.12.2004") == date(2004, 12, 13)
    assert P.parse_date("on and from the 1st day of October, 2022") == date(2022, 10, 1)
    assert P.parse_date("December 19, 2022") == date(2022, 12, 19)
    assert P.parse_month_year("September 2020") == (2020, 9)
    assert P.parse_month_year("(08/2024)") == (2024, 8)


def test_ais_codes():
    assert P.ais_canonical_from_text("AIS-038 (Rev. 2)") == "AIS-038(Rev.2)"
    assert P.ais_canonical_from_text("AIS 021/2004") == "AIS-021"
    assert P.ais_canonical_from_text("AIS-137 (Part 1)") == "AIS-137(Part1)"
    assert P.ais_canonical_from_text("AIS-001 (Part 1)(Rev. 2):2023") == "AIS-001(Part1)(Rev.2)"
    assert P.ais_canonical_from_text("AIS-004 (Part III)") == "AIS-004(Part3)"
    assert P.parse_canonical_ais("AIS-038(Rev.2)/Amd.4") == {"code": 38, "part": None, "rev": 2, "kind": "Amd",
                                                            "no": 4, "table": None}


def test_amendment_header_formats():
    t1 = "AMENDMENT NO. 2  10 April 2015\nTO\nAIS 021/2004"
    m = P.AMD_HEADER.search(t1)
    assert m and m.group(1) == "2"
    assert P.header_date(m.group("mid")) == ("2015-04-10", "day", "full_date")
    t2 = "Amendment No. 4 (08/2024)\nTo\nAIS-156"
    m = P.AMD_HEADER.search(t2)
    assert m and m.group(1) == "4"
    assert P.header_date(m.group("mid")) == ("2024-08", "month", "month_year")
    t3 = "AMENDMENT NO. 1\nTO\nAIS-037"
    m = P.AMD_HEADER.search(t3)
    assert m and P.header_date(m.group("mid"))[2] == "no_date"


def test_arai_code_strings():
    a = parse_arai_code("AIS-037/2004 & Amd. No. 1 to 11")
    assert a["code"] == 37 and a["amendments"] == list(range(1, 12))
    a = parse_arai_code("AIS-001 and Amd. No.1 & Amd. No.2")
    assert a["amendments"] == [1, 2]
    a = parse_arai_code("AIS-001 (Part 1)(Rev. 2):2023 & Corrigendum1")
    assert a["part"] == 1 and a["rev"] == 2 and a["corrigenda"] == [1]
    a = parse_arai_code("AIS-007(Rev. 5) - Table 24A")
    assert a["kind"] == "table" and a["table"] == "24A" and a["rev"] == 5
    a = parse_arai_code("Draft AIS-132/D10/May 2017 (Date of hosting on website: 26th May 2017)")
    assert a["draft"] and a["draft_stage"] == "D10" and a["hosted_on"] == "2017-05-26"
    a = parse_arai_code("Revised Draft Amd 10 to AIS-137 (Part 3) (Date of hosting on website: 7th January 2025)")
    assert a["kind"] == "draft_amendment" and a["draft_amendment_no"] == 10 and a["part"] == 3
    assert parse_arai_code("Interpretation manual for AIS-189")["kind"] == "interpretation"
    assert parse_arai_code("List")["kind"] == "list"


GAZETTE = """
MINISTRY OF ROAD TRANSPORT AND HIGHWAYS
NOTIFICATION
New Delhi, the 2nd September, 2022
S.O. 4143(E).—In exercise of the powers conferred by section 110 of the Motor Vehicles Act, 1988, the
Central Government hereby makes the following amendments in the notification of the Government of India
in the Ministry of Shipping, Road Transport and Highways, number S.O. 1365(E), dated the 13th December, 2004,
namely:-
In the said notification, in the Table, against serial number 26, ...
[F. No. RT-11036/60/2022-MVL]
"""


def test_notification_identity_from_content():
    ident = notification_identity(GAZETTE)
    assert ident.canonical_id == "SO-4143(E)-2022"
    assert ident.doc_date == date(2022, 9, 2)
    assert "SO-1365(E)-2004" in ident.others


def test_ais_identity_cover():
    cover = "AUTOMOTIVE INDUSTRY STANDARD\nSpecific Requirements for Electric Power Train\nAIS-038 (Rev.2)\nSeptember 2020\n"
    i = ais_identity(cover)
    assert i.canonical_id == "AIS-038(Rev.2)" and i.family_key == "AIS-038" and i.doc_date == date(2020, 9, 1)


def test_categories_and_conditions():
    c = P.find_categories("vehicles of category L2 and M1, and two-wheelers, trailers of category O2")
    assert c["L2"] >= 2 and c["M1"] == 1 and c["O"] >= 1
    assert "L1" in P.find_categories("vehicles of category L")
    cond = P.find_conditions("motor cycles with engine capacity not exceeding 125 cc and GVW exceeding 3.5 tonnes")
    assert cond["engine_cc"] == {"lte": 125.0} and cond["gvw_kg"] == {"gt": 3500.0}


def test_references():
    refs = P.find_references("conforming to IS 14664:2010, AIS-156 and UN R136; see rule 96 (4A)")
    assert "IS 14664:2010" in refs and "AIS-156" in refs and "UN R136" in refs and "CMVR Rule 96(4A)" in refs
