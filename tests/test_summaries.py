"""Summaries of MYT GetTrip/v3 payloads. The fixture is synthetic and shaped like the real
response (no client data); field names and nesting follow trip 269362 / quotation 350-2."""

from myt_mcp.myt.summaries import quotation_summary, trip_summary, trips_list


def _d(iso: str, time: str = "00:00") -> dict:
    return {"date": f"{iso}T{time}:00", "string": iso, "time": {"time": f"{time}:00", "string": time}}


V3 = {
    "trip": {
        "trip_id": 1001,
        "number": "898",
        "name": "Sample - Azores and Portugal",
        "status": {"registration_phase": True, "name": "Registration Phase", "id": 2},
        "dates": {"start": _d("2027-06-01"), "end": _d("2027-06-17")},
        "paying_participants": 2,
        "participants": 2,
        "number_of_staff": 0,
    },
    "schedule": [
        {
            "day_number": 1,
            "date": _d("2027-06-01"),
            "activites": [
                {
                    "name": "Private Transfers",
                    "supplier_name": "PRIVATE TRANSFERS",
                    "supplier_type": {"transportation": True},
                    "description": "From Lisbon airport<br/>to the   hotel",
                }
            ],
        }
    ],
    "accomodation": [
        {
            "product_name": "Terceira Mar Hotel",
            "supplier_name": "Bensaude Group",
            "dates": {"start": _d("2027-06-02"), "end": _d("2027-06-04")},
            "duration": 2,
            "quantity": 1.0,
            "price": {"amount": 160.0},
            "currency": {"name": "EUR"},
        }
    ],
    "flights": [
        {
            "number": "S48823",
            "from_airport": "Lisbon International Airport",
            "to_airport": "Aeroporto da Ilha Terceira",
            "departure_date": _d("2027-06-02", "11:10"),
            "arrival_date": _d("2027-06-02", "13:05"),
            "description": "Operated by TAP Air Portugal",
        }
    ],
    "suppliers": [{"supplier_id": 7, "supplier_name": "Ilha Verde", "supplier_type": {"transportation": True}}],
    "quotation": {
        "number": "350-2",
        "version": "2",
        "status": "Draft",
        "currency": {"name": "EUR"},
        "language": {"name": "Hebrew"},
        "markup": {"other": 230.0, "is_amount": True},
        "product_packages": [
            {
                "id": 55,
                "title": "Version 2",
                "pax_free": [
                    {
                        "pax": 2,
                        "free": 0,
                        "price": {
                            "person": {"amount": 5035.0},
                            "group": {"amount": 10070.0},
                            "single_supplement": {"amount": 0.0},
                            "tax": {"net": {"amount": 9131.59}},
                            "products": [
                                {
                                    "name": "Terceira - NISSAN QASHQAI",
                                    "type": {"name": "Transportation", "transportation": True},
                                    "first_category": {"name": "Day", "day": True},
                                    "second_category": {"name": "Car", "car": True},
                                    "third_category": {"name": "5", "5": True},
                                    "supplier_name": "Ilha Verde",
                                    "supplier_id": 7,
                                    "quantity": 1.0,
                                    "nights": 1,
                                    "start_date": _d("2027-06-02"),
                                    "PP": False,
                                    "PS": True,
                                    "currency": {"name": "EUR"},
                                    "unit_price": {"amount": 372.9},
                                    "total_price": {"amount": 372.9},
                                    "vat": 0.0,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    },
}


def test_trip_summary_keeps_what_a_quote_needs():
    t = trip_summary(V3)
    assert (t["number"], t["start"], t["end"], t["paying_participants"]) == ("898", "2027-06-01", "2027-06-17", 2)
    assert t["status"] == "Registration Phase"
    act = t["days"][0]["activities"][0]
    assert act["supplier_type"] == "transportation"
    assert act["description"] == "From Lisbon airport to the hotel"
    assert t["hotels"][0] == {
        "hotel": "Terceira Mar Hotel", "supplier": "Bensaude Group", "check_in": "2027-06-02",
        "check_out": "2027-06-04", "nights": 2, "rooms": 1.0, "price": 160.0, "currency": "EUR",
    }
    assert t["flights"][0]["departure"] == "2027-06-02 11:10"
    assert t["quotation"] == {"number": "350-2", "version": "2", "status": "Draft"}


def test_quotation_summary_lines_and_totals():
    q = quotation_summary(V3)
    pkg = q["packages"][0]
    assert (pkg["price_per_person"], pkg["price_group"], pkg["lines_subtotal_group"]) == (5035.0, 10070.0, 9131.59)
    line = pkg["lines"][0]
    assert line["category"] == "Transportation"
    assert (line["pricing"], line["line_type"], line["transport"], line["seats"]) == ("PS", "Day", "Car", "5")
    assert line["unit_price_with_profit"] == 372.9
    assert q["markup"] == {"other": 230.0, "is_amount": True}
    assert "note" not in q                       # a priced quotation needs no explanation


def test_unpriced_draft_explains_the_empty_total():
    import copy
    draft = copy.deepcopy(V3)
    for pkg in draft["quotation"]["product_packages"]:
        for pf in pkg["pax_free"]:
            pf["price"]["group"] = 0
            pf["price"]["person"] = None
    q = quotation_summary(draft)
    assert q["packages"][0]["price_group"] in (0, 0.0, None) and "lines_subtotal_group" in q["note"] and "not set" in q["note"]


def test_missing_parts_do_not_crash():
    assert quotation_summary({}) is None
    t = trip_summary({"trip": {"trip_id": 1}})
    assert t["days"] == [] and t["hotels"] == [] and t["quotation"] is None


def test_trips_list():
    rows = trips_list([{"TripId": 276310, "TripName": "test", "StartDateAndTime": "2026-10-15T00:00:00",
                        "EndDateAndTime": "2026-10-20T00:00:00", "TripStatusName": "Registration Phase"}])
    assert rows[0]["trip_id"] == 276310 and rows[0]["start"] == "2026-10-15"


def test_contact_details_are_removed_from_participants():
    from myt_mcp.tools.trips import strip_contact_details

    data = {"participant_list": [{"first_name": "A", "email": "a@x.com", "phone": "1", "Mobile": "2"}],
            "responsibles": {"planning": {"name": "B", "email": "b@x.com", "phone": None}}}
    out = strip_contact_details(data)
    assert out == {"participant_list": [{"first_name": "A"}], "responsibles": {"planning": {"name": "B"}}}
    assert "@" not in str(out)
