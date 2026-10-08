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


# ---- titles (rules_v2) --------------------------------------------------------------------------------------------
def test_junk_titles():
    from regtrack.pipeline.extract import is_junk_title

    for t in ["Date of hosting on website: 8th September 2026", "AIS-137 (Part 5)", "Draft AIS-221/D0/Dec. 2025",
              "REGISTERED NO. DL-33004/2001", "Amends CMVR", "FINALISED DRAFT", "Page 38/52, ANNEXURE F, Clause No. 1.0",
              "Central Motor Vehicles (……Amendment) Rules, 2026", None, ""]:
        assert is_junk_title(t), t
    for t in ["AIS-197: Bharat New Car Assessment Programme", "Amends CMVR Rule 102(1), CMVR Rule 104",
              "Finalised Draft of 67 Proposed Amendments to the Motor Vehicles Act, 1988", "Electronic Stability Control Systems",
              "Central Motor Vehicles (Tenth Amendment) Rules, 2024"]:
        assert not is_junk_title(t), t


def test_ais_title_from_draft_cover():
    from regtrack.pipeline.extract import ais_title

    cover = ("Date of hosting on website: 8th September 2026\nLast date for comments: 22nd September 2026\n"
             "Draft Corrigendum No. 1  (…../2026)\nTo\nAIS-185 Approval of vehicles with regard to the Advanced\n"
             "Emergency Braking System (AEBS) for M1 and N1 vehicles\n1. Page 18/39, Clause 7.5.1, third paragraph\n")
    assert ais_title(cover).startswith("Draft Corrigendum No. 1 to AIS-185: Approval of vehicles with regard to the Advanced")
    std = "AUTOMOTIVE INDUSTRY STANDARD – 164\n(AIS – 164)\nConstructional and Functional Requirements\nfor Insulated Vehicles\nDate of Hosting on website"
    assert ais_title(std) == "Constructional and Functional Requirements for Insulated Vehicles"
    back = "PRINTED BY THE ARAI ON BEHALF OF AUTOMOTIVE INDUSTRY STANDARDS COMMITTEE UNDER CENTRAL MOTOR VEHICLE RULES"
    assert ais_title(back) is None  # "STANDARDS COMMITTEE" is not a title


def test_called_title():
    from regtrack.pipeline.extract import called_title

    assert called_title("(1) These rules may be called as the Motor Vehicles (Third Party Insurance Base Premium and "
                        "Liability) Rules, 2022.") == "Motor Vehicles (Third Party Insurance Base Premium and Liability) Rules, 2022"
    assert called_title("These rules may be called the Central Motor Vehicles (………Amendment) Rules, 2021.") == \
        "Central Motor Vehicles (Amendment) Rules, 2021"


def test_ais_listing_match():
    from regtrack.pipeline.extract import ais_listing_matches

    std = {"doc_class": "AIS_STANDARD", "status": "final", "number": "137", "part": "5"}
    assert ais_listing_matches(std, {"code": "AIS-137 (Part 5) and Amd 1", "tab": "Published"})
    assert not ais_listing_matches(std, {"code": "AIS-137 (Part 6)", "tab": "Published"})
    assert not ais_listing_matches(std, {"code": "Draft AIS-137 (Part 5)/D1", "tab": "Draft"})
    draft = {"doc_class": "AIS_DRAFT", "status": "draft", "number": "221", "part": None}
    assert ais_listing_matches(draft, {"code": "Draft AIS-221/D0/Dec. 2025", "tab": "Draft"})


def test_draft_ais_running_header():
    import re

    head = "Draft AIS-221/D0/Dec. 2025\nII\nINTRODUCTION\nThe Government of India felt the need"
    assert re.search(r"\bDraft\s*/?\s*AIS[\s\-]*\d{3}[^\n]{0,40}?/\s*D(?:F\d?|\d)\b", head, re.I)
