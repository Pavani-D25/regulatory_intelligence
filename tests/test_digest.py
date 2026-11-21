"""The detailed summary from a regulation's own text (regtrack/pipeline/digest.py), without the LLM."""

from regtrack.pipeline import digest

NOTIFICATION = """
<<<PAGE 3>>>
THE GAZETTE OF INDIA : EXTRAORDINARY
मोटर यान नियम, 1989 में संशोधन किया जाएगा
MINISTRY OF ROAD TRANSPORT AND HIGHWAYS
NOTIFICATION
G.S.R. 310(E).—Whereas, the draft rules further to amend the Central Motor Vehicles Rules, 1989 were published,
inviting objections and suggestions from all persons likely to be affected thereby;
Now, therefore, in exercise of the powers conferred by section 110, the Central Government hereby makes the following
rules further to amend the Central Motor Vehicles Rules, 1989, namely:-
1. (1) These rules may be called the Central Motor Vehicles (Third Amendment) Rules, 2016.
(2) They shall come into force on the date of their final publication in the Official Gazette.
2. In the Central Motor Vehicles Rules, 1989, in rule 96, after sub-rule (4), the following sub-rule shall be inserted,
namely:- "(4A) New vehicle models of category L2 with engine capacity up to 125 cc manufactured on and after the
1st April, 2018 shall be fitted with anti-lock braking system or combined braking system conforming to IS 14664:2010."
"""

AIS_AMENDMENT = """
Amendment No. 3 (09/2026)
To AIS 039 (Rev 1): Electric Power Train Vehicles - Measurement of Electrical Energy Consumption
Clause No 5.2
Substitute following text for existing text:
5.2 Power setting of the chassis dynamometer. The procedure prescribed in AIS 137 shall be adopted for the test.
"""

LABELS = {"cat": {"L2": "L2 Two-wheeler"}, "domain": {"braking": "Braking"}}


def row(**kw):
    base = {
        "canonical_id": "GSR-310(E)-2016",
        "doc_class": "NOTIFICATION_FINAL",
        "issuer": "MoRTH",
        "doc_date": "2016-03-16",
        "vehicle_categories": ["L2"],
        "domains": ["braking"],
        "powertrains": [],
        "data": {
            "official_title": "Central Motor Vehicles (Third Amendment) Rules, 2016",
            "amends_targets": ["CMVR Rule 96"],
            "draft_ref": {"canonical_id": "GSR-673(E)-2015"},
            "references": ["IS 14664:2010"],
            "commencement": "date of publication",
        },
    }
    return {**base, **kw}


def test_notification_digest_from_text():
    text = digest.clean(NOTIFICATION)
    assert "मोटर" not in text and "GAZETTE OF INDIA" not in text  # Hindi lines and headers out
    d = digest.digest(row(), text, [], [], LABELS)
    assert "final notification issued by MoRTH on 16 Mar 2016" in d["overview"]
    assert "amends CMVR Rule 96" in d["overview"] and "finalises draft GSR-673(E)-2015" in d["overview"]
    sec = {s["title"]: s for s in d["sections"]}
    assert any("rule 96" in it and "inserted" in it for it in sec["What it changes"]["items"])
    assert "IS 14664:2010" in sec["Standards and documents referred to"]["items"]
    assert sec["Purpose and scope"]["text"].startswith("The Government makes")
    # boilerplate is no requirement: the short title, commencement and consultation sentences
    for s in d["sections"]:
        for it in s.get("items", []):
            assert "may be called" not in it and "objections and suggestions" not in it


def test_ais_amendment_lists_clause_changes():
    d = digest.digest(
        row(canonical_id="AIS-039(Rev.1)/Amd.3", doc_class="AIS_AMENDMENT", data={}),
        digest.clean(AIS_AMENDMENT),
        [],
        [],
        LABELS,
    )
    changes = next(s for s in d["sections"] if s["title"] == "What it changes")["items"]
    assert changes[0].startswith("Clause No 5.2: Substitute")


def test_obligations_and_no_text():
    m = [
        {
            "subject": "(1) (2) (3) ABS for new L2 models",
            "implementation_date": "2018-04-01",
            "vehicle_categories": ["L2"],
            "model_scope": "new_models",
            "applies_to": "engine ≤ 125 cc",
        }
    ]
    d = digest.digest(row(), "", m, [{"type": "finalises", "target": "GSR-673(E)-2015"}], LABELS)
    assert d["has_text"] is False and "no readable English text" in d["source"]
    req = next(s for s in d["sections"] if s["title"] == "Key requirements")["items"]
    assert req == ["From 01 Apr 2018: ABS for new L2 models (categories L2; new models; engine ≤ 125 cc)"]
    assert next(s for s in d["sections"] if s["title"] == "Related regulations")["items"] == [
        "finalises: GSR-673(E)-2015"
    ]


def test_odd_data_shapes_do_not_break():
    d = digest.digest(
        row(data={"draft_ref": "GSR-1", "powers": "MV Act s.110", "references": [{"ref": "AIS-004"}]}),
        "",
        [],
        [],
        LABELS,
    )
    assert "Legal basis: MV Act s.110" in d["overview"]
