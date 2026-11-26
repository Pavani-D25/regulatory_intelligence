"""WTO ePing TBT notifications for Thailand (regtrack/pipeline/wto.py, regtrack/sources/thailand_eping.py)."""

from regtrack.pipeline import wto
from regtrack.sources import thailand_eping

REGULAR = """G/TBT/N/THA/797 21 October 2025 (25-6798) Page: 1 / 2 Committee on Technical Barriers to Trade Original: English
NOTIFICATION
The following notification is being circulated in accordance with Article 10.6
1.
 | Notifying Member: THAILAND
2.
 | Agency responsible:
Thai Industrial Standards Institute (TISI), Ministry of Industry
3.
 | Notified under Article 2.9.2 [X], 2.10.1 [ ], 5.6.2 [ ], 5.7.1 [ ], 3.2 [ ], 7.2 [ ], Other:
4.
 | Products covered (HS codes or national tariff lines. ICS numbers may be provided in addition, where applicable): Automotive wheels (ICS 43.040.50, 83.160.01)
5.
 | Details of notified document(s) (title, number of pages and languages, means of access): Draft Ministerial Regulation Prescribing Industrial Products for Automotive Wheels to Conform to the Standard B.E. ....; (17 page(s), in Thai)
Link to notified document(s) and/or contact details for agency or authority which can provide copies upon request:
https://members.wto.org/crnattachments/2025/TBT/THA/25_07028_00_x.pdf
WTO/TBT Enquiry Point and Notification Authority
Website: https://www.tisi.go.th
6.
 | Description of content: The draft Ministerial Regulation applies to automotive wheels designed for vehicles of categories M1, M1G, N1, N1G, O1 and O2.
7.
 | Objective and rationale, including the nature of urgent problems where applicable: Protection of human health or safety
8.
 | Relevant documents:
UN Regulation No. 124
9.
 | Proposed date of adoption: To be determined
Proposed date of entry into force: After 270 days following the date of its publication in the Government Gazette.
10.
 | Provision of comments
Final date for comments: 20 November 2025 (30 days from notification)
"""

ADDENDUM = """G/TBT/N/THA/702/Rev.1/Add.1 23 September 2025 (25-6024) Page: 1 / 1 Committee on Technical Barriers to Trade
NOTIFICATION
Addendum
The following communication, dated 23 September 2025, is being circulated at the request of the delegation of Thailand.
_______________
Title: Ministerial Regulation Prescribing Industrial Products for Heavy Motor Vehicles Equipped with Positive Ignition Engines

Reason for Addendum:
[ ]
 | Comment period changed - date:
[X]
 | Notified measure adopted - date: 14 August 2025
[X]
 | Notified measure published - date: 5 September 2025
[X]
 | Notified measure enters into force - date: 1 January 2026
[X]
 | Text of final measure available from:
https://members.wto.org/crnattachments/2025/TBT/THA/final_measure/25_06331_00_x.pdf
[ ]
 | Notified measure withdrawn or revoked - date:

Description: This addendum is to inform that the Ministerial Regulation will enter into force on 1 January 2026.
__________
"""

FREE_ADDENDUM = """G/TBT/N/THA/482/Add.1 3 December 2018 ( 18-7624 ) Page: 1 / 1 Committee on Technical Barriers to Trade
NOTIFICATION
Addendum
The following communication, dated 3 December 2018, is being circulated at the request of the delegation of Thailand.
_______________
Thai Industrial Standard for Pneumatic Tyres for Commercial Vehicles and Their Trailers
This addendum is to inform that the standard (TIS 2719-2558 (2016)), notified under G/TBT/N/THA/482, was adopted on 22 November 2018 and will enter into force after 60 days of publication in the Official Gazette (21 January 2019).
https://members.wto.org/crnattachments/2018/TBT/THA/18_6192_00_x.pdf
__________
"""


def test_regular_notification():
    f = wto.fields(REGULAR)
    assert f["symbol"] == "G/TBT/N/THA/797" and f["kind"] == "regular" and f["distribution_date"] == "2025-10-21"
    assert f["agency"] == "Thai Industrial Standards Institute (TISI), Ministry of Industry"
    assert f["ics_codes"] == ["43.040.50", "83.160.01"]
    assert f["title"].startswith("Draft Ministerial Regulation Prescribing Industrial Products for Automotive Wheels")
    assert f["document_links"] == ["https://members.wto.org/crnattachments/2025/TBT/THA/25_07028_00_x.pdf"]
    assert f["objective"] == "Protection of human health or safety" and f["relevant_documents"] == [
        "UN Regulation No. 124"
    ]
    assert f["proposed_adoption"] == "To be determined" and f["comment_deadline"] == "2025-11-20"
    assert wto.status_of(f) == "draft"
    assert wto.categories(f["description"]) == ["M1", "N1", "O"]


def test_structured_addendum_gives_the_final_dates():
    f = wto.fields(ADDENDUM)
    assert f["symbol"] == "G/TBT/N/THA/702/Rev.1/Add.1" and f["kind"] == "addendum"
    assert (f["adopted_date"], f["published_date"], f["entry_into_force_date"]) == (
        "2025-08-14",
        "2025-09-05",
        "2026-01-01",
    )
    assert "withdrawn_date" not in f  # an unticked box
    assert f["document_links"] == [
        "https://members.wto.org/crnattachments/2025/TBT/THA/final_measure/25_06331_00_x.pdf"
    ]
    assert wto.status_of(f) == "final"
    assert wto.symbol_of(ADDENDUM)["family_key"] == "G/TBT/N/THA/702"  # a version of the notification


def test_free_text_addendum_and_cited_symbols():
    f = wto.fields(FREE_ADDENDUM)
    # the header's symbol wins over the one the body cites ("notified under G/TBT/N/THA/482")
    assert f["symbol"] == "G/TBT/N/THA/482/Add.1"
    assert f["title"] == "Thai Industrial Standard for Pneumatic Tyres for Commercial Vehicles and Their Trailers"
    assert f["adopted_date"] == "2018-11-22" and f["entry_into_force_date"] == "2019-01-21"
    assert wto.status_of(f) == "final"


def test_old_symbols_and_header_at_the_end():
    old = wto.symbol_of(
        "World Trade Organization G/TBT/Notif.99.42/Corr.1( 4 March 1999 Committee on Technical Barriers"
    )
    assert old["canonical_id"] == "G/TBT/Notif.99/42/Corr.1" and old["kind"] == "corrigendum" and old["member"] is None
    # an old Word file: the body cites the notification, the header (with its date) comes last
    body = "This draft was notified under Notification G/TBT/N/THA/428.\n__________\nG/TBT/N/THA/428/Add.1\n\n21 April 2016\n"
    s = wto.symbol_of(body)
    assert s["canonical_id"] == "G/TBT/N/THA/428/Add.1" and s["date"].isoformat() == "2016-04-21"


def test_vehicle_filter_and_listing():
    car = {
        "id": "1",
        "documentSymbol": " G/TBT/N/THA/797",
        "dolLink": "G\\TBTN25\\THA797.DOCX",
        "distributionDate": "2025-10-21T00:00:00+00:00",
        "title": "<p>Automotive wheels</p>",
        "icsCodes": [{"code": "43.040.50"}],
        "hsCodes": [],
        "notificationType": "Regular notification",
    }
    food = {**car, "title": "<p>Flavoured milk</p>", "icsCodes": [{"code": "67.100.10"}], "productsFreeText": "Milk"}
    assert wto.is_vehicle(car) and not wto.is_vehicle(food)
    lst = thailand_eping.to_listing(car)
    assert lst.item_id == "G/TBT/N/THA/797" and lst.listing_date.isoformat() == "2025-10-21"
    assert lst.url == "https://docs.wto.org/dol2fe/Pages/SS/directdoc2.aspx?filename=t:/g/tbtn25/tha797.docx"
