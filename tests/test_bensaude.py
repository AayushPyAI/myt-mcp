"""Bensaude Hotels (the group's own booking engine): the address, the hotel names, the converter on what the real page gave (27 Oct 2026) and the tool."""

import json
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.bensaude_hotels import availability_url, bensaude_hotels_recipe, convert, find_hotel, hotels

CANCEL = "Cancellation Policy Cancellations must be submitted 7 days before check-in date. Any cancellation submitted after this period shall be charged by 100.00% of the total value of the reservation."
TAX = "Local tourist tax: €2 per night (maximum 3 nights), per guest, to be charged at the reception desk upon check-in. Children up to the age of 13 are exempt from payment."


def _row(room="Cosy Art Deco", plan="FLEX", price=322.0, description="Book Now, Pay Later At The Hotel! Breakfast included All prices with VAT", cancel=CANCEL, tax=TAX, special=False):
    return {"room": room, "room_desc": f"{room} style Double or Twin Room, 15 square meters", "plan": plan, "description": description, "special": special, "price": price,
            "cancel": cancel, "tax": tax, "pay": "credit card", "nightly": "Rate detail for the period of 06/03/2027 to 08/03/2027 Day 2 Customers 06/03/2027 €167.00 07/03/2027 €155.00"}


def _data(rows=None, **kw):
    base = {"ok": True, "hotel": "Terra Nostra Garden Hotel", "hotel_id": 29, "check_in": "06/03/2027", "check_out": "08/03/2027", "adults": 2, "agent_login": None, "rows": rows if rows is not None else [
        _row(), _row(plan="TN Special", price=466.0, description="EXCLUSIVE OFFER at bensaudehotels.com Accommodation with half board (breakfast and one meal per day, per person excluding drinks) All prices with VAT", special=True),
        _row("Garden View", price=394.0), _row("Garden View", "TN Special", 531.0, "Accommodation with half board", special=True)]}
    base.update(kw)
    return json.dumps(base)


class _Day(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 27)


@pytest.fixture
def frozen(monkeypatch):
    """The free-cancellation date (7 days before check-in) is compared with today: a test that reads it must not depend on the day it runs."""
    monkeypatch.setattr("myt_mcp.sites.bensaude_hotels.date", _Day)


WISHES = {"expect": {"hotel_id": 29, "check_in": "06/03/2027", "check_out": "08/03/2027", "adults": 2}}


def test_the_address_carries_everything_and_the_hotel_name_is_found_with_or_without_accents():
    url = availability_url(29, date(2027, 3, 6), date(2027, 3, 8), 2, 1)
    assert url.startswith("https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?") and all(
        x in url for x in ("hotelid=29", "adults=2", "children=0", "nrooms=1", "arrivaldate=20270306", "departuredate=20270308"))
    assert len(hotels()) == 11 and find_hotel("Hotel Açores Lisboa") == (30, "Hotel Açores Lisboa") and find_hotel("hotel acores lisboa") == (30, "Hotel Açores Lisboa")
    assert find_hotel("caloura") == (9880610, "Caloura Hotel Resort") and find_hotel("29") == (29, "Terra Nostra Garden Hotel")
    assert sorted(find_hotel("terra nostra")) == ["Botania Hall by Terra Nostra", "Terra Nostra Garden Hotel"]       # two hotels fit: the operator chooses
    assert find_hotel("Hilton Lisbon") is None


def test_the_recipe_has_the_expected_search_inside_the_script():
    out = bensaude_hotels_recipe(29, date(2027, 3, 6), date(2027, 3, 8))
    assert out["expect"] == WISHES["expect"] and '"hotel_id": 29' in out["script"] and "__EXPECT__" not in out["script"] and "emit(" in out["script"]
    with pytest.raises(ValueError):
        bensaude_hotels_recipe(29, date(2027, 3, 8), date(2027, 3, 6))


def test_every_rate_plan_becomes_a_quotable_row_with_its_own_meal_cancellation_and_tax(frozen):
    rows = convert(_data(), {**WISHES}, "Hotels")
    by = {o.name: o for o in rows.offers}
    flex = by["Terra Nostra Garden Hotel - Cosy Art Deco - FLEX"]
    assert rows.problems == [] and len(rows.offers) == 4 and flex.price_total == 322.0 and flex.currency == "EUR" and flex.quotable is True and flex.supplier == "Bensaude Group"
    assert flex.details["meal"] == "Breakfast included" and flex.flexible is True and flex.details["cancellation"].startswith("free cancellation until 27 Feb 2027")
    assert "100% of the stay is charged" in flex.details["cancellation"] and flex.details["local_tax"].startswith("€2 per night (maximum 3 nights)")
    special = by["Terra Nostra Garden Hotel - Cosy Art Deco - TN Special"]
    assert special.details["meal"].startswith("Half board") and special.details["special_offer"] is True
    assert flex.details["stars"] is None and flex.details["distance_from_centre"] is None and "public website rate" in " ".join(rows.extra_notes)


def test_the_operators_wishes_are_judged_and_what_the_page_does_not_show_is_never_assumed(frozen):
    rows = convert(_data([_row(), _row(plan="No cancel", price=200.0, description="Room Only", cancel=None), _row(plan="Late", price=300.0, description="Breakfast included", cancel="Cancellations must be submitted 7 days before check-in date.")]),
                   {**WISHES, "breakfast": True, "free_cancellation": True, "max_total": 310}, "Hotels")
    fits = {o.name.split(" - ")[-1]: o.fits for o in rows.offers}
    assert fits == {"FLEX": False, "No cancel": False, "Late": True}      # FLEX 322 is over the 310 budget; "No cancel" is room only; "Late" has breakfast, free cancellation and 300
    unknown = {o.name.split(" - ")[-1]: o for o in rows.offers}["No cancel"]
    assert unknown.flexible is None and unknown.details["cancellation"].startswith("not shown") and any("never counted as free cancellation" in n for n in rows.extra_notes)
    stars = convert(_data(), {**WISHES, "stars_min": 4}, "Hotels")
    assert all(o.fits is None for o in stars.offers) and any("no star rating" in n for n in stars.extra_notes)         # not judged as met (compose then treats None as not met)


def test_a_passed_free_cancellation_date_is_said_and_not_counted_as_free():
    soon = date.today() + timedelta(days=3)
    data = _data(check_in=f"{soon:%d/%m/%Y}", check_out=f"{soon + timedelta(days=2):%d/%m/%Y}")
    rows = convert(data, {"expect": {**WISHES["expect"], "check_in": f"{soon:%d/%m/%Y}", "check_out": f"{soon + timedelta(days=2):%d/%m/%Y}"}, "free_cancellation": True}, "Hotels")
    flex = rows.offers[0]
    assert flex.flexible is False and flex.fits is False and flex.details["cancellation"].startswith("the free cancellation ended on") and not flex.details["cancellation"].startswith("free cancellation")


def test_a_wrong_page_a_failed_script_and_an_empty_page_are_refused():
    assert "searched hotel 30" in " ".join(convert(_data(hotel_id=30), WISHES, "Hotels").problems)
    assert "check-in '07/03/2027'" in " ".join(convert(_data(check_in="07/03/2027"), WISHES, "Hotels").problems)
    assert "adults 3" in " ".join(convert(_data(adults=3), WISHES, "Hotels").problems)
    assert "script reported: no rooms" in convert(json.dumps({"ok": False, "error": "no rooms are shown"}), WISHES, "Hotels").problems[0]
    assert "could not be read (never say sold out)" in " ".join(convert(_data(rows=[]), WISHES, "Hotels").problems)
    assert "not the script's JSON" in convert("not json", WISHES, "Hotels").problems[0]
    assert "bensaude_hotels" in modules() and convert_all([{"site": "bensaude_hotels", "result": _data(), "url": "u"}], WISHES)[0]


def test_a_page_that_still_prices_a_child_from_an_earlier_search_is_refused():
    problems = " ".join(convert(_data(children_on_page=2), WISHES, "Hotels").problems)
    assert "priced a child kept from an earlier search" in problems and "new Chrome window" in problems


def test_a_logged_in_agency_page_drops_the_public_rate_note():
    rows = convert(_data(agent_login=True), WISHES, "Hotels")
    assert not any("public website rate" in n for n in rows.extra_notes)


@pytest.mark.anyio
async def test_the_tool_asks_for_an_unclear_hotel_refuses_children_and_returns_the_url_and_wishes():
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        unclear = (await c.call_tool("bensaude_hotels_recipe", {"hotel": "terra nostra", "check_in": "2027-03-06", "check_out": "2027-03-08"})).structured_content
        unknown = (await c.call_tool("bensaude_hotels_recipe", {"hotel": "Hilton", "check_in": "2027-03-06", "check_out": "2027-03-08"})).structured_content
        children = await c.call_tool("bensaude_hotels_recipe", {"hotel": "Terra Nostra Garden Hotel", "check_in": "2027-03-06", "check_out": "2027-03-08", "children_ages": [8]})
        ok = (await c.call_tool("bensaude_hotels_recipe", {"hotel": "Terra Nostra Garden Hotel", "check_in": "2027-03-06", "check_out": "2027-03-08", "breakfast": True, "free_cancellation": True,
                                                            "budget_per_night": 200})).structured_content
    assert unclear["ok"] is False and unclear["searched"] is False and len(unclear["known_hotels"]) == 2 and "Terra Nostra Garden Hotel" in unclear["known_hotels"]
    assert unknown["ok"] is False and len(unknown["known_hotels"]) == 11
    assert children.is_error and "children are not supported yet" in children.content[0].text
    assert "hotelid=29" in ok["url"] and ok["hotel"] == "Terra Nostra Garden Hotel" and ok["nights"] == 2
    assert ok["wishes"]["breakfast"] is True and ok["wishes"]["free_cancellation"] is True and ok["wishes"]["max_total"] == 400 and ok["wishes"]["expect"]["hotel_id"] == 29
    assert any("Breakfast included" in f for f in ok["filters_used"]) and any("2 adults" in f for f in ok["filters_used"]) and "script" in ok


def test_the_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = bensaude_hotels_recipe(29, date(2027, 3, 6), date(2027, 3, 8))["script"]
    path = Path(tmp_path) / "bensaude.mjs"           # top-level await: a module
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_a_room_only_plan_named_in_its_title_does_not_meet_a_breakfast_wish_even_with_free_cancellation(frozen):
    """27 Oct 2026, seen live: 'Executive - FLEX (ROOM-ONLY)' (no meal words in its description) became the Best fit of a breakfast search because the free-cancellation check turned the unknown meal into a yes."""
    rows = convert(_data([_row(plan="FLEX (ROOM-ONLY)", price=231.0, description="Book Now, Pay Later At The Hotel! All prices with VAT"),
                          _row(plan="FLEX", price=279.0, description="Book Now, Pay Later At The Hotel! Breakfast included All prices with VAT")]),
                   {**WISHES, "breakfast": True, "free_cancellation": True}, "Hotels")
    by = {o.name.split(" - ")[-1]: o for o in rows.offers}
    assert by["FLEX (ROOM-ONLY)"].details["meal"] == "Room only" and by["FLEX (ROOM-ONLY)"].fits is False
    assert by["FLEX"].fits is True


def test_an_unknown_meal_is_never_turned_into_a_yes_by_a_later_check(frozen):
    rows = convert(_data([_row(plan="FLEX", price=250.0, description="Book Now, Pay Later At The Hotel! All prices with VAT")]), {**WISHES, "breakfast": True, "free_cancellation": True}, "Hotels")
    assert rows.offers[0].details["meal"] == "not shown" and rows.offers[0].fits is None
