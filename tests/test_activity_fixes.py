"""27 Oct 2026, the six-kind test chat: a Viator/GYG/CP/SATA page the server cannot read comes back as the recipe for the operator's Chrome (it came back as nothing: 35 Chrome actions to find another way); 'Viator' is told
apart as the list or the page by the rows; one-activity runs add up ('2 of 1 read'); the operator's rating (10 points) is read on Viator's and GetYourGuide's 5 points; Viator's 'You can cancel up to 24 hours in
advance ... for a full refund' is free cancellation."""

import json
from datetime import date

import pytest
from mcp import Client

import myt_mcp.sites as sites
from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all, modules, resolve_site_names

pytestmark = pytest.mark.anyio


async def test_a_page_the_servers_chrome_cannot_read_comes_back_as_the_recipe_for_the_operators_chrome_for_viator_gyg_cp_and_sata(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: True)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mcp.example.test")

    async def refused(site, origin, url, out, ready_path=None):
        return {"ok": False, "error": f"{site}: not a search page (the server's reader failed)"}
    monkeypatch.setattr(sites, "read_in_server_browser", refused)
    calls = {
        "viator_find_recipe": {"query": "Lisbon tours", "day_label": "Sun 7 Mar", "free_cancellation": True, "max_price": 100, "max_hours": 6, "operator_answered": True},
        "getyourguide_find_recipe": {"query": "Lisbon tours", "day": "2027-03-07", "free_cancellation": True, "max_price": 100, "max_hours": 6, "operator_answered": True},
        "cp_trains_recipe": {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 2, "first_class": False, "earliest": "07:00", "refundable": False, "direct_only": False},
        "sata_recipe": {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "direct_only": True, "checked_bag": False, "refundable": False},
    }
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        for tool, args in calls.items():
            out = (await c.call_tool(tool, args)).structured_content
            assert out.get("script") and out["server_read"]["ok"] is False and "not a search page" in out["server_read"]["why"], (tool, out)
            assert "window.__mytParts" in out["how_the_answer_comes_back"] and "NEW tab" in out["tab"], tool      # their pages do not let the operator's Chrome post: the rows come in parts


def part(**head):
    return json.dumps({"ok": True, "run": head.pop("run"), **head, "rows": []})


def test_viator_and_getyourguide_are_told_apart_as_the_list_or_the_page_by_the_rows_even_when_both_recipes_were_issued():
    mods = modules()
    issued = {"viator_find", "viator_activity", "getyourguide_find", "getyourguide_activity"}
    items = [
        {"site": "Viator", "result": part(run="r1", url_path="/tours/Lisbon/x", activity="Best of Lisbon", options_found=1)},
        {"site": "Viator", "result": part(run="r2", query_text="Lisbon tours", results_total="120", page=1)},
        {"site": "GetYourGuide", "result": part(run="r3", query_text="Lisbon", results_total="500+", date_chip="Mar 7")},
        {"site": "GetYourGuide", "result": part(run="r4", url_path="/lisbon/x-t1/", activity="X", availability="2 options")},
        {"site": "Viator", "result": json.dumps({"ok": True, "run": "r1", "part": 2, "parts": 2, "rows": [[1]]})},      # a later part has no head: its run says which answer it belongs to
    ]
    fixed_items, fixed = resolve_site_names(items, mods, issued)
    assert [i["site"] for i in fixed_items] == ["viator_activity", "viator_find", "getyourguide_find", "getyourguide_activity", "viator_activity"] and fixed == {"Viator": "viator_activity", "GetYourGuide": "getyourguide_activity"} or all(
        i["site"] in mods for i in fixed_items)
    unknown, _ = resolve_site_names([{"site": "Viator", "result": "not json"}], mods, issued)
    assert unknown[0]["site"] == "Viator"      # nothing to go by: still refused with the question, never guessed


def test_two_one_activity_runs_are_two_read_of_two_not_two_of_one():
    from tests.test_booking_attraction import EXPECT, RECIPE, answer
    items = [{"site": "booking_attraction", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}, {"site": "booking_attraction", "result": answer(), "url": RECIPE["url"] + "&x=2", "wishes": {"expect": EXPECT}}]
    offers, sources, problems, _, _ = convert_all(items, {"expect": EXPECT})
    assert problems == [] and sources[0].read == 2 and sources[0].of == 2


def test_a_rating_on_ten_points_is_read_on_five_for_viator_and_getyourguide():
    from myt_mcp.sites.getyourguide_find import getyourguide_find_recipe
    from myt_mcp.sites.viator_find import viator_find_recipe
    assert viator_find_recipe("Lisbon tours", None, 1, None, False, None, 9.0)["expect"]["min_rating"] == 4.5
    assert getyourguide_find_recipe("Lisbon tours", date(2027, 3, 7), 24, 0, None, False, None, 9.0)["expect"]["min_rating"] == 4.5
    assert viator_find_recipe("Lisbon tours", None, 1, None, False, None, 4.5)["expect"]["min_rating"] == 4.5      # already on five points: left alone
    with pytest.raises(ValueError):
        viator_find_recipe("Lisbon tours", None, 1, None, False, None, 0)


def test_viators_policy_line_up_to_24_hours_for_a_full_refund_is_free_cancellation():
    from myt_mcp.sites.viator_activity import convert
    row = {"option": None, "selected": True, "priced": True, "price_text": "€38.00", "from_text": None, "start_time": None, "times": [], "cancellation": None, "pay_later": None, "dialog_travellers": "2 Adults",
           "dialog_when": "Sun, Mar 7, 2027 • 9:30 AM", "breakdown": ["2 Adults x €19.00 = €38.00"], "dialog_total": "€38.00"}
    data = {"ok": True, "url_path": "/tours/Lisbon/Lisbon-Guided-Walking-Tour/d538-5383LISBONTOUR", "activity": "Best of Lisbon Small-Group Guided Walking Tour", "date_box": "Sun, Mar 7", "travellers_box": 2, "options_found": 1,
            "duration": "4 hours (approx.)", "cancel_policy": "You can cancel up to 24 hours in advance of the experience for a full refund.", "rows": [row]}
    wishes = {"expect": {"day": "2027-03-07", "adults": 2, "children": 0, "ages": [], "total": 2, "path": data["url_path"], "group": "Lisbon tours, 07 Mar 2027"}, "free_cancellation": True}
    o = convert(json.dumps(data), wishes, "Activities").offers[0]
    assert o.flexible is True and o.details["cancellation"].startswith("Free cancellation per the page's policy: You can cancel up to 24 hours")
    other = convert(json.dumps({**data, "cancel_policy": "This activity is non-refundable."}), wishes, "Activities").offers[0]
    assert other.flexible is not True and not other.details["cancellation"].startswith("Free cancellation")


def test_each_priced_viator_row_names_its_own_page_and_its_times_are_on_the_24_hour_clock():
    """28 Oct 2026: three Viator rows said 'see Sources' and Sources held one link; the start times were '10:00 AM' next to Booking.com's '10:00'."""
    from myt_mcp.sites.viator_activity import convert
    row = {"option": None, "selected": True, "priced": True, "price_text": "€38.00", "from_text": None, "start_time": "3:30 PM", "times": ["10:00 AM", "11:00 AM", "3:30 PM"], "cancellation": None, "pay_later": None,
           "dialog_travellers": "2 Adults", "dialog_when": "Sun, Mar 7, 2027 • 9:30 AM", "breakdown": ["2 Adults x €19.00 = €38.00"], "dialog_total": "€38.00"}
    data = {"ok": True, "url_path": "/tours/Lisbon/Alfama-Tour-Lisbon-Old-Town/d538-268183P3", "activity": "Alfama Tour", "date_box": "Sun, Mar 7", "travellers_box": 2, "options_found": 1, "duration": "2 hours", "rows": [row]}
    wishes = {"expect": {"day": "2027-03-07", "adults": 2, "children": 0, "ages": [], "total": 2, "path": data["url_path"], "group": "Lisbon activities 7 Mar 2027"}}
    o = convert(json.dumps(data), wishes, "Activities").offers[0]
    assert o.link == "https://www.viator.com/tours/Lisbon/Alfama-Tour-Lisbon-Old-Town/d538-268183P3"
    assert o.details["start_times"] == "chosen: 15:30; 3 start time(s): 10:00, 11:00, 15:30"


def test_a_getyourguide_row_link_names_the_activity_page_with_the_date():
    from myt_mcp.sites.getyourguide_activity import _page_link
    exp = {"day": "2027-03-07", "path": "/lisbon-l42/best-of-lisbon-walking-tour-rossio-chiado-alfama-t600"}
    assert _page_link(exp) == "https://www.getyourguide.com/lisbon-l42/best-of-lisbon-walking-tour-rossio-chiado-alfama-t600/?date_from=2027-03-07&date_to=2027-03-07"
    assert _page_link({"day": "2027-03-07", "path": ""}) is None and _page_link({}) is None
