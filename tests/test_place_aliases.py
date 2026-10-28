"""One place, many names: place_matches reads 'Lisbon Airport' and 'Humberto Delgado Airport (LIS)' as the same place (27 Oct 2026: RateHawk Transfers' page named it that way and compose_answer refused it twice, so the chat
searched RateHawk a third time, 53 Chrome actions). And every recipe that has a script says where to open it: a NEW tab."""

import json

import pytest
from mcp import Client

import myt_mcp.sites as sites
from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import alias_groups, place_matches, place_words

SAME = [("Lisbon Airport", "Humberto Delgado Airport (LIS)"), ("Lisbon Airport", "Airport Lisbon Portela"), ("Lisbon Airport", "LIS"), ("Faro Airport", "Portugal, Faro Airport"), ("Porto Airport", "Francisco Sá Carneiro Airport (OPO)"),
        ("Praça do Comércio", "Praca do Comercio"), ("Rome Fiumicino", "Leonardo da Vinci Fiumicino (FCO)"), ("Tel Aviv Airport", "Ben Gurion (TLV)"), ("Funchal Airport", "Madeira Cristiano Ronaldo (FNC)"),
        ("Florence Airport", "Firenze-Peretola Airport"), ("Roma Termini", "Roma Termini railway station"), ("Airport", "anything")]
OTHER = [("Lisbon Airport", "Faro Airport (FAO)"), ("Faro Airport", "Spain, Malaga Airport"), ("Lisbon Airport", "Praça do Comércio"), ("Ponta Delgada Airport", "Lisbon Humberto Delgado"),
         ("Porto Airport", "Lisbon Airport (LIS)"), ("Rome Fiumicino", "Milan Malpensa (MXP)"), ("Fiumicino Airport", "Ciampino Airport"), ("Malpensa Airport", "Linate Airport (LIN)"), ("Fiumicino (FCO)", "Ciampino (CIA)")]      # two airports of one city stay two places when the city word is not what was asked


@pytest.mark.parametrize("expected,got", SAME)
def test_the_other_names_of_one_place_are_the_same_place(expected, got):
    assert place_matches(expected, got)


@pytest.mark.parametrize("expected,got", OTHER)
def test_another_place_is_still_refused(expected, got):
    assert not place_matches(expected, got)


def test_the_alias_table_has_no_word_in_two_groups_so_two_cities_never_merge_and_every_word_is_lower_case_ascii():
    seen: dict[str, int] = {}
    for i, g in enumerate(alias_groups()):
        for w in g:
            assert w == w.lower() and w.isascii() and w not in sites.GENERIC_PLACE_WORDS, w
            assert seen.setdefault(w, i) == i, f"'{w}' is in two groups"
    assert "lisbon" in place_words("Lisbon Airport") and {"humberto", "delgado", "lis"} <= place_words("Lisbon Airport")


@pytest.mark.anyio
async def test_every_recipe_with_a_script_says_to_open_the_url_in_a_new_tab(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: False)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        flights = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "cabin": "economy"})).structured_content
        iway = (await c.call_tool("iway_transfers_recipe", {"origin": "Lisbon Airport", "destination": "Praça do Comércio", "day": "2027-03-06", "time": "10:00"})).structured_content
        asked = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06"})).structured_content
    assert "NEW tab" in flights["tab"] and "never in the operator's current tab" in flights["tab"]
    assert "OWN iWay tab" in iway["tab"] and "NEW tab" not in iway["tab"]      # iWay is the one exception: its page does not draw in a background tab (28 Oct 2026)
    assert "tab" not in asked      # a question has no page to open
