"""Ofran parsing, matching and offer summaries. Fixtures copy the shape of /api/locations and
/api/get_full_dynamic_result; the values are made up."""

from myt_mcp.ofran.locations import LocationIndex, parse_locations
from myt_mcp.ofran.offers import summarize_offers


def raw_location(code, name, iata_id, kind="1", preferred="1", country="69", aliases=()):
    return {"name": [code], "description": [name], "field_country_id": [country], "field_id": [iata_id],
            "field_iata_code_type_id": [kind], "field_preferred": [preferred], "field_type": ["iata"],
            "field_alternate_names": list(aliases)}


RAW_LOCATIONS = [
    raw_location("LISDT", "Lisbon City Center", "489", kind="2", aliases=["ליסבון"]),
    raw_location("LIS", "Lisbon Airport", "488", aliases=["ליסבון"]),
    raw_location("OPO", "Porto Airport", "490"),
    raw_location("PCDT", "Porto Cervo City Center", "1140", kind="2", country="60"),
    raw_location("FLR", "Firenze Airport", "60", preferred="0", country="60"),
    {"field_type": ["country"], "description": ["Portugal"]},   # country rows are skipped
    {"field_type": ["iata"], "description": []},               # malformed rows are dropped
    "garbage",
]
INDEX = LocationIndex(parse_locations(RAW_LOCATIONS))


def test_parse_skips_countries_and_malformed_rows():
    assert len(INDEX) == 5
    assert parse_locations({"not": "a list"}) == []


def test_matching_ranks_airports_and_codes_first():
    assert INDEX.match("Lisbon")[0].iata_id == "488"
    assert INDEX.match("lis")[0].name == "Lisbon Airport"
    assert INDEX.match("ליסבון")[0].kind == "airport"
    assert [l.name for l in INDEX.match("porto")] == ["Porto Airport", "Porto Cervo City Center"]
    assert INDEX.match("  Lisbon   Airport ")[0].code == "LIS"
    assert INDEX.match("nowhere") == [] and INDEX.match("   ") == []


def test_english_name_finds_local_name():
    assert INDEX.match("Florence Airport")[0].code == "FLR"


def offer(supplier, model, sipp, price, offline=None, extras=None):
    return {
        "cargroup": {"suppliername": supplier, "carmodel": model, "sippcode": sipp, "ofranCarGroupName": "Small",
                     "reccnumofadults": "4", "numdoors": "4", "reccnumofsuitcases": "1", "SupplierRating": "9.20",
                     "PictureFile": "Fiat 500.jpg"},
        "contracts": [{"nettotal": price, "OfflineRate": offline or price, "currency": "EUR", "contractname": "Inclusive",
                       "IsLiveRate": "true", "CDWExcess": "1000.00", "TPExcess": "1000.00", "Deposit": "1000.00",
                       "handlingfee": "0", "premiumfee": "0", "OneWayFee": [],
                       "AdditionalProducts": {"Products": {"AdditionalProduct": extras if extras is not None else [
                           {"Name": "Ofran Plus II", "RateInReservationPQCurrency": "394.43", "ReservationPQCurrencyCode": "EUR"}]}}}],
    }


RESULT = [
    offer("Hertz Portugal", "Ford Focus", "CDAR", "1875.91"),
    offer("Hertz Portugal", "Fiat 500", "MBMR", "793.31", offline="847.06"),
    offer("Tangerine Portugal", "Opel Corsa", "EDMR", "1214.27"),
]


def test_offers_sorted_cheapest_first_with_details():
    s = summarize_offers(RESULT)
    assert (s.total, s.skipped) == (3, 0)
    assert [c["price"] for c in s.cars] == [793.31, 1214.27, 1875.91]
    first = s.cars[0]
    assert first["car"] == "Fiat 500 or similar" and first["transmission"] == "manual"
    assert first["price_before_discount"] == 847.06 and first["supplier_rating"] == 9.2
    assert first["image"] == "https://img.ofran.co.il/photos/Desktop/Fiat%20500.jpg"
    assert first["fees"] == {} and first["one_way_fee"] is None
    assert first["optional_extras"][0] == {"name": "Ofran Plus II", "price": 394.43, "currency": "EUR"}


def test_transmission_filter_and_limit():
    s = summarize_offers(RESULT, transmission="automatic")
    assert s.total == 1 and s.cars[0]["sipp"] == "CDAR"
    assert len(summarize_offers(RESULT, limit=2).cars) == 2


def test_malformed_offers_are_skipped_not_fatal():
    broken = RESULT + [{"cargroup": None}, "garbage", offer("X", "Y", "MBMR", "not-a-price")]
    s = summarize_offers(broken)
    assert s.total == 3 and s.skipped == 3


def test_single_extra_as_object():
    s = summarize_offers([offer("A", "B", "MBMR", "10", extras={"Name": "One", "RateInReservationPQCurrency": "5"})])
    assert s.cars[0]["optional_extras"][0]["name"] == "One"
