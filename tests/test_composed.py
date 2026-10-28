"""check_answer compares the draft's price rows with what compose_answer built (a retyped or changed row is reported)."""

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.composed import COMPOSED, ComposedStore, amount_problems, row_problems, source_warnings
from myt_mcp.config import Settings
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

ANSWER = ("| Source | Option | Capacity | Price | Basis |\n|---|---|---|---|---|\n"
          "| RateHawk Transfers | Business Minivan: Mercedes-Benz V-Class or a similar one | up to 7 people / 7 bags | 40.00 EUR | per vehicle, one way |\n"
          "| Kiwitaxi | Comfort (Sedan comfort for 4 passengers) | 3 / 4 | 40.00 EUR | per vehicle |\n")


def store_with(text: str, kind: str = "transfers") -> ComposedStore:
    store = ComposedStore()
    store.remember(kind, text)
    return store


def test_the_servers_own_rows_pass_even_when_the_table_is_pasted_with_tabs_or_bold():
    assert row_problems(ANSWER, "transfers", store_with(ANSWER)) == []
    tabs = "RateHawk Transfers\tBusiness Minivan: Mercedes-Benz V-Class or a similar one\tup to 7 people / 7 bags\t40.00 EUR\tper vehicle, one way"
    assert row_problems(tabs, "transfers", store_with(ANSWER)) == []
    assert row_problems(ANSWER.replace("Kiwitaxi", "**Kiwitaxi**"), "transfers", store_with(ANSWER)) == []


def test_a_retyped_vehicle_name_is_named_and_the_answer_is_sent_back():
    changed = ANSWER.replace("Mercedes-Benz V-Class", "Toyota Alphard")
    problems = row_problems(changed, "transfers", store_with(ANSWER))
    assert len(problems) == 1 and "typed or changed by hand" in problems[0] and "toyota alphard" in problems[0] and "exactly as written" in problems[0]


def test_price_rows_with_no_composed_answer_on_the_server_are_refused_but_text_without_rows_is_not():
    assert "no compose_answer result" in row_problems(ANSWER, "transfers", ComposedStore())[0]
    assert row_problems("I found nothing: Aspire has no lounge here.", "lounges", ComposedStore()) == []
    assert row_problems(ANSWER, "cars", store_with(ANSWER, "transfers"))[0].startswith("the draft has price rows but no compose_answer")


def test_an_old_answer_is_forgotten_after_three_hours(monkeypatch):
    import myt_mcp.composed as composed
    store = store_with(ANSWER)
    now = composed.time.time()
    monkeypatch.setattr(composed.time, "time", lambda: now + 3 * 3600 + 1)
    assert store.recent("transfers") == []


async def test_compose_answer_remembers_its_answer_and_check_answer_catches_a_changed_row():
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        row = {"group": "LIS lounges", "source": "LoungePair", "name": "ANA Lounge, Terminal 1", "price_total": 19.0, "currency": "EUR", "price_basis": "'from' price PER PERSON", "quotable": False,
               "details": {"terminal": "Terminal 1"}, "link": "https://www.loungepair.com/at/LIS/x/"}
        composed = (await c.call_tool("compose_answer", {"kind": "lounges", "offers": [row], "filters_used": ["Airport LIS (operator)"],
                                                          "sources_read": [{"name": "LoungePair", "read": 1, "of": 1, "link": row["link"]}]})).structured_content
        assert composed["ok"] and COMPOSED.recent("lounges")
        ok = (await c.call_tool("check_answer", {"draft": composed["answer"], "kind": "lounges"})).structured_content
        assert not any("typed or changed" in m for m in ok["missing"])
        retyped = composed["answer"].replace("19.00 EUR", "38.00 EUR")
        bad = (await c.call_tool("check_answer", {"draft": retyped, "kind": "lounges"})).structured_content
    assert bad["ok"] is False and any("typed or changed by hand" in m and "38.00 eur" in m for m in bad["missing"])


def test_a_sources_line_with_links_that_hold_dates_is_not_a_table_row():
    line = ("Sources: TAP (TLV-LIS): https://booking.flytap.com/booking/flights?depDate=10.12.2026&x=1 | TAP (LIS-TLV): https://booking.flytap.com/booking/flights?depDate=17.12.2026 | "
            "RateHawk Air (TLV-LIS): https://www.ratehawk.com/air/?route=LISa17122026TLVa | RateHawk Air (LIS-TLV): https://www.ratehawk.com/air/?route=x")
    assert row_problems(line, "flights", ComposedStore()) == []
    row = "| TAP | TP8920 13:40-17:50 | direct | 794.50 EUR | whole group |"
    assert "no compose_answer result" in row_problems(row, "flights", ComposedStore())[0]


def test_a_checked_bag_the_row_cannot_show_is_not_a_pick_and_the_note_names_the_cheapest_of_them():
    from myt_mcp.compose import Offer, bag_unconfirmed
    mk = lambda src, price, bag: Offer(group="g", source=src, name="x", price_total=price, currency="EUR", price_basis="b", fits=True, details={"checked_bag": bag})
    rows = [mk("TAP Air Portugal", 980.42, "yes"), mk("El Al", 846.0, "not shown on the list (fare rules on elal.com)"), mk("El Al", 900.0, "not shown on the list")]
    note = bag_unconfirmed(rows)
    assert [o.fits for o in rows] == [True, False, False] and "El Al 846.00 EUR" in note and "not picks" in note
    assert bag_unconfirmed([mk("TAP Air Portugal", 1.0, "yes"), mk("RateHawk", 2.0, "no")]) is None


def test_both_legs_of_a_source_keep_their_own_link_in_the_sources_line():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    from tests.test_compose import TAP_REAL, _tap
    out = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    back = dict(out, leg="LIS to FLR, 13 Mar 2027")
    item = lambda e, url: {"site": "tap", "result": _tap(TAP_REAL), "url": url, "wishes": {"expect": e}}
    one = convert_all([item(out, "https://t/out")], {})[1][0]
    two = convert_all([item(out, "https://t/out"), item(back, "https://t/back")], {})[1][0]
    assert one.link == "https://t/out" and two.link == f"{out['leg']}: https://t/out; LIS to FLR, 13 Mar 2027: https://t/back"


def test_a_source_with_one_link_per_leg_passes_compose_and_a_home_page_link_does_not():
    from myt_mcp.compose import Offer, SourceRead, compose
    offer = Offer(group="TLV to LIS", source="TAP", name="TP8920", price_total=794.5, currency="EUR", price_basis="whole group", fits=True, details={"checked_bag": "yes"})
    legs = "TLV to LIS, 10 Dec 2026: https://booking.flytap.com/booking/flights?depDate=10.12.2026; LIS to TLV, 17 Dec 2026: https://booking.flytap.com/booking/flights?depDate=17.12.2026"
    run = lambda link: compose("flights", ["Direct (operator)"], [SourceRead(name="TAP", read=1, of=1, link=link)], [], [offer], {}, None, True, "")
    assert run(legs)["ok"] is True and run("https://booking.flytap.com/booking/flights?depDate=10.12.2026")["ok"] is True
    for bad in ("https://www.flytap.com/", "TLV to LIS: https://www.flytap.com/; LIS to TLV: https://booking.flytap.com/x?a=1", "no link at all", None):
        assert any("not a home page" in p for p in run(bad)["problems"]), bad


async def test_compose_answer_refuses_typed_rows_from_a_chrome_only_site_but_takes_a_tools_rows():
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        hotel = {"group": "Rome 8-10 Feb", "source": "RateHawk", "name": "Hotel Ripa Roma - Standard Double room for 3 guests", "price_total": 205.0, "currency": "EUR", "link": "https://www.ratehawk.com/hotel/x"}
        refused = (await c.call_tool("compose_answer", {"kind": "hotels", "offers": [hotel], "sources_read": [{"name": "RateHawk", "read": 1, "of": 1, "link": hotel["link"]}]})).structured_content
        assert refused["ok"] is False and "RateHawk" in refused["problems"][0] and "cannot be typed" in refused["problems"][0] and "Never read a price off a page by hand" in refused["problems"][0]
        assert not COMPOSED.recent("hotels")
        tour = dict(hotel, group="Colosseum", source="GetYourGuide", name="Colosseum tour")
        assert (await c.call_tool("compose_answer", {"kind": "activities", "offers": [tour]})).structured_content["ok"] is False
        taxi = {"group": "Transfers", "source": "Kiwitaxi", "name": "Sedan", "price_total": 88.0, "currency": "EUR", "price_basis": "per vehicle", "link": "https://kiwitaxi.com/x"}
        assert "cannot be typed" not in " ".join((await c.call_tool("compose_answer", {"kind": "transfers", "offers": [taxi]})).structured_content.get("problems", []))


SUMMARY = ("| Part | Best choice | Net € (family) |\n|---|---|---|\n| Flight out | El Al LY-383 | 492.45 |\n| Lounge | Aspire TLV | 240.00 |\n| Transfer | Kiwitaxi sedan | 88.00 |\n"
           "| Hotel | Hotel Ripa Roma | 205.00 |\n")


def test_a_table_price_no_tool_answer_holds_is_refused_and_the_assistants_own_sum_is_not():
    store = ComposedStore()
    store.remember("flights", "| El Al | LY-383 | 492.45 EUR |")
    store.remember("lounges", "| Aspire | 80.00 EUR | per person |")
    store.remember("transfers", "| Kiwitaxi | Sedan | 88.00 EUR |")
    problems, warnings = amount_problems(SUMMARY, store)
    assert len(problems) == 1 and "205" in problems[0] and "492.45" not in problems[0] and "240" not in problems[0] and "88" not in problems[0]      # 240 = 80 x 3 persons
    store.remember("hotels", "| Hotel Ripa Roma | 205.00 EUR |")
    assert amount_problems(SUMMARY, store) == ([], [])
    store.remember("quote", "2,065.52 2,389.62")
    assert amount_problems(SUMMARY + "\nTotal 2,065.52 EUR, selling price 2,389.62 EUR.", store) == ([], [])
    _, warnings = amount_problems("RateHawk Transfers has a minivan for €101 with a child seat.", store)
    assert warnings and "101" in warnings[0]
    assert amount_problems(SUMMARY, ComposedStore()) == ([], [])          # no composed answer at all is row_problems' message, not this one


def test_a_source_the_composed_answers_read_but_the_draft_never_names_is_warned_about():
    store = ComposedStore()
    store.remember("flights", "Sources checked: TAP (7 of 7 read); El Al (2 of 2 read); SATA / Azores Airlines (3 of 3 read) | Not checked: Israir (not connected)\n| TAP | x |")
    store.remember("hotels", "Sources checked: RateHawk (30 of 80 read); Arbitrip (30 of 40 read) | Not checked: none")
    draft = "Sources: TAP flights, SATA, RateHawk hotels in Lisbon."
    warnings = source_warnings(draft, None, store)
    assert len(warnings) == 1 and "El Al" in warnings[0] and "Arbitrip" in warnings[0] and "TAP" not in warnings[0] and "SATA" not in warnings[0] and "Israir" not in warnings[0]
    assert source_warnings(draft + " El Al, Arbitrip.", None, store) == []
    assert source_warnings(draft, None, ComposedStore()) == []


def test_a_draft_is_only_warned_about_the_sources_of_answers_of_its_own_kind():
    """28 Oct 2026: a train answer and an activities answer were warned that Kiwitaxi and iWay (the transfer answer's sources) were missing."""
    store = ComposedStore()
    store.remember("transfers", "Sources checked: Kiwitaxi (9 of 9 read); iWay (4 of 4 read) | Not checked: none")
    store.remember("trains", "Sources checked: none returned an option | Not checked: CP (not available)")
    train = "Sources checked: none returned an option | Not checked: CP (not available)"
    assert source_warnings(train, "trains", store) == [] and source_warnings(train, "activities", store) == []
    assert "Kiwitaxi" in source_warnings(train, "transfers", store)[0]
    assert "Kiwitaxi" in source_warnings(train, "general", store)[0]          # an unknown kind still looks at every answer


def test_a_recipe_issued_but_missing_from_the_answer_is_named_unless_it_is_in_not_checked_or_was_composed_since():
    import time
    from myt_mcp.compose import NotChecked
    from myt_mcp.ingest import STORE
    from myt_mcp.tools.compose_answer import unused_recipes
    STORE.new_run("getyourguide_find", {}, [])
    STORE.new_run("viator_find", {}, [])
    STORE.new_run("viator_activity", {}, [])          # the page of one tour: not a missing source
    STORE.new_run("ratehawk_hotels", {}, [])          # another kind
    found = unused_recipes("activities", {"viator_find"}, [])
    assert len(found) == 1 and found[0].startswith("getyourguide_find (the recipe was issued at ")
    assert unused_recipes("activities", {"viator_find", "getyourguide_find"}, []) == []
    assert unused_recipes("activities", {"viator_find"}, [NotChecked(name="GetYourGuide", reason="could not be read: blocked")]) == []
    assert [f.split(" ")[0] for f in unused_recipes("activities", set(), [])] == ["getyourguide_find", "viator_find"]
    COMPOSED.remember("activities", "answer")          # an answer of the kind was built after the recipe: it was weighed then
    time.sleep(0.01)
    assert unused_recipes("activities", {"viator_find"}, []) == []


async def test_compose_answer_refuses_an_answer_that_leaves_an_issued_recipe_out():
    from myt_mcp.ingest import STORE
    STORE.new_run("getyourguide_find", {}, [])
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        r = (await c.call_tool("compose_answer", {"kind": "activities", "not_checked": []})).structured_content
        assert r["ok"] is False and any("getyourguide_find" in p and "never dropped without a word" in p for p in r["problems"])


def test_a_display_name_for_a_site_is_refused_with_the_keys_it_could_mean():
    from myt_mcp.sites import modules, unknown_site
    mods = modules()
    gyg = unknown_site("GetYourGuide", mods)
    assert "'getyourguide_activity'" in gyg and "'getyourguide_find'" in gyg and "Did you mean" in gyg
    assert "'ratehawk_hotels'" in unknown_site("Ratehawk", mods) and "Did you mean" not in unknown_site("Nowhere", mods)


def test_sources_searched_with_different_travellers_are_named_and_refused_but_equal_ones_and_other_days_are_not():
    from myt_mcp.tools.compose_answer import split_problems
    wish = lambda adults, children, day="2027-03-09", **kw: {"wishes": {"expect": {"adults": adults, "children": children, "day": day, **kw}}}
    same = {("tap", "r1"): wish(3, 1), ("sata", "r2"): wish(3, 1), ("ratehawk_air", "r3"): wish(3, 1, infants=0)}
    assert split_problems(same) == []
    mixed = {**same, ("skyscanner", "r4"): wish(2, 2)}
    out = split_problems(mixed)
    assert len(out) == 1 and "2027-03-09" in out[0] and "skyscanner: 2 adult(s) + 2 child(ren)" in out[0] and "ratehawk_air, sata, tap: 3 adult(s) + 1 child(ren)" in out[0] and "cannot be compared" in out[0]
    assert split_problems({("tap", "r1"): wish(3, 1, "2027-03-09"), ("tap", "r2"): wish(2, 2, "2027-03-16")}) == []          # two legs on two days are judged separately
    assert split_problems({("elal", "r1"): wish(2, 1, seniors=1), ("tap", "r2"): wish(3, 1)}) == []          # El Al's seniors count as adults
    assert split_problems({("cp_trains", "r1"): {"wishes": {"expect": {"passengers": 2, "day": "2027-03-09"}}}}) == []      # a source with no split is left out


def test_the_bag_note_says_how_many_rows_of_a_source_do_not_show_a_bag():
    from myt_mcp.compose import Offer, bag_unconfirmed
    mk = lambda src, price, bag: Offer(group="g", source=src, name="x", price_total=price, currency="EUR", price_basis="b", fits=True, details={"checked_bag": bag})
    rows = [mk("RateHawk Air", 343.72, "23 kg checked bag included"), mk("RateHawk Air", 516.76, "not shown on the list"), mk("RateHawk Air", 400.0, "not shown on the list"), mk("El Al", 846.0, "not shown")]
    note = bag_unconfirmed(rows)
    assert "RateHawk Air (2 of its 3 rows)" in note and "El Al (all its rows)" in note and "RateHawk Air 400.00 EUR" in note and "some rows" in note


def test_a_refundable_wish_makes_a_flight_row_with_unknown_refund_terms_not_a_pick():
    from myt_mcp.compose import Offer, refund_unconfirmed
    mk = lambda src, price, refund, quotable=True, fits=True: Offer(group="g", source=src, name="x", price_total=price, currency="EUR", price_basis="b", fits=fits, quotable=quotable, details={"refund_change": refund})
    rows = [mk("RateHawk Air", 343.72, "not shown on the list (open More rates)"), mk("RateHawk Air", 388.72, "not shown on the list"), mk("RateHawk Air", 411.0, "refundable"),
            mk("SATA / Azores Airlines", 380.72, "refund: Penalty \u20ac65 (chargeable)"), mk("Skyscanner", 254.0, "not shown on the list", quotable=False), mk("TAP Air Portugal", 315.72, "not refundable", fits=False)]
    note = refund_unconfirmed(rows)
    assert [o.fits for o in rows] == [False, False, True, True, True, False]          # only the quotable, undecided rows with unknown terms change; a comparison row and a decided row are left alone
    assert "RateHawk Air (2 of its 3 rows)" in note and "RateHawk Air 343.72 EUR" in note and "not picks" in note and "Skyscanner" not in note
    assert refund_unconfirmed([mk("TAP Air Portugal", 1.0, "refundable"), mk("SATA / Azores Airlines", 2.0, "refund: Without penalties (included)")]) is None


# ---------- a display name for a site is read as its key when only one recipe can be meant (26 Oct 2026: 'GetYourGuide' and 'RateHawk' got whole answers refused) ----------

def test_a_site_name_that_means_one_recipe_is_read_as_its_key_and_an_unclear_one_is_still_refused():
    from myt_mcp.sites import modules, resolve_site_names
    mods = modules()
    item = lambda site: [{"site": site, "result": "{}"}]
    assert resolve_site_names(item("RateHawk Hotels"), mods, set())[0][0]["site"] == "ratehawk_hotels"        # fits exactly one key
    assert resolve_site_names(item("Ratehawk"), mods, set())[0][0]["site"] == "Ratehawk"                      # five keys and nothing issued: unclear
    assert resolve_site_names(item("Ratehawk"), mods, {"ratehawk_hotels"})[0][0]["site"] == "ratehawk_hotels"      # one of them was issued in this chat
    assert resolve_site_names(item("GetYourGuide"), mods, {"getyourguide_find", "getyourguide_activity"})[0][0]["site"] == "GetYourGuide"      # both issued: still unclear
    out, fixed = resolve_site_names(item("GetYourGuide"), mods, {"getyourguide_find"})
    assert out[0]["site"] == "getyourguide_find" and fixed == {"GetYourGuide": "getyourguide_find"}
    assert resolve_site_names(item("Nowhere"), mods, {"getyourguide_find"})[0][0]["site"] == "Nowhere"
    assert resolve_site_names(item("tap"), mods, set())[0][0]["site"] == "tap"                                # an exact key stays as it is


@pytest.mark.anyio
async def test_compose_answer_reads_the_display_name_of_the_one_recipe_that_was_issued():
    from myt_mcp.ingest import STORE
    STORE.new_run("getyourguide_find", {}, [])
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        r = (await c.call_tool("compose_answer", {"kind": "activities", "site_results": [{"site": "GetYourGuide", "result": "{}"}], "not_checked": []})).structured_content
    assert not any("unknown site" in p for p in r.get("problems", []))


# ---------- a source the server converted to euro is never shown in its own currency in the table (27 Oct 2026, Europcar) ----------

def test_a_table_cell_in_another_currency_is_refused_when_the_server_converted_that_source():
    from myt_mcp.composed import COMPOSED, currency_problems
    draft = "| Car | Price |\n|---|---|\n| CITROEN C4 | $86.50 |\n| FIAT 500 | 76.85 EUR |"
    assert currency_problems(draft) == []                                    # nothing was converted: not this check's business
    COMPOSED.remember("cars", "| CITROEN C4 | 76.85 EUR | whole rental, converted from USD 86.50 at 1 USD = 0.8885 EUR (Bank of Israel representative rates, 2026-10-26) |")
    problems = currency_problems(draft)
    assert len(problems) == 1 and "$86.50" in problems[0] and "never the original or your own conversion" in problems[0]
    assert currency_problems("| CITROEN C4 | 76.85 EUR |") == [] and currency_problems("The dollar price was $86.50 before the conversion.") == []       # euro cells and prose are fine
    assert currency_problems("| CITROEN C4 | 76.85 EUR | whole rental, converted from USD 86.50 at 1 USD = 0.8885 EUR |") == []   # the server's own basis text may name the original
