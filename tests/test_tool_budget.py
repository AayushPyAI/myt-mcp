"""The tool list claude.ai loads: short, one place to start, and every recipe with its kind words (27 Oct 2026: 65 tools, about 29,500 tokens in every chat, nine of them 'NOT USED' pointers, five of them saying 'call me first')."""

import json

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.tool_tags import KIND_OF, KINDS

pytestmark = pytest.mark.anyio

LEGACY = {"tap_flight_prices", "sata_flight_prices", "viator_search_activities", "viator_activity_details", "getyourguide_find_activities", "getyourguide_activity_details", "ofran_find_location",
          "ofran_car_prices", "ratehawk_hotels"}
SWITCHES = ("TAP_SERVER_BROWSER", "SATA_SERVER_BROWSER", "VIATOR_SERVER_BROWSER", "GYG_SERVER_BROWSER", "OFRAN_SERVER_SEARCH", "RATEHAWK_SERVER_BROWSER", "LEGACY_TOOL_POINTERS")
BUDGET_TOKENS = 29_000      # descriptions + parameter schemas, characters / 4 (raised from 28,000 for iWay, 27 Oct 2026, one more recipe): lower it when descriptions get shorter, never raise it without a reason
MAX_TOOLS = 58


async def production_tools(monkeypatch, **env):
    for k in SWITCHES:      # the tests turn the server-browser tools on; production does not
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        return (await c.list_tools()).tools


async def test_the_pointers_to_the_old_tool_names_are_not_listed_unless_asked_for(monkeypatch):
    names = {t.name for t in await production_tools(monkeypatch)}
    assert not (LEGACY & names), LEGACY & names
    assert {"tap_recipe", "sata_recipe", "viator_find_recipe", "getyourguide_find_recipe", "ofran_recipe", "ratehawk_hotels_recipe", "tap_fare_calendar"} <= names      # the real ways stay
    old = {t.name for t in await production_tools(monkeypatch, LEGACY_TOOL_POINTERS="1")}
    assert LEGACY <= old and len(old) == len(names) + len(LEGACY)


async def test_every_recipe_has_its_kind_words_in_front_and_every_kind_entry_is_a_real_tool(monkeypatch):
    tools = {t.name: t for t in await production_tools(monkeypatch)}
    recipes = {n for n in tools if n.endswith("_recipe")}
    assert recipes == set(KIND_OF), f"recipes without a kind or a kind for no recipe: {recipes ^ set(KIND_OF)} (add the new recipe to myt_mcp/tool_tags.py)"
    for name in recipes:
        assert tools[name].description.startswith("[" + KINDS[KIND_OF[name]] + "] FOR "), name
    assert len(recipes) == 24


async def test_task_plan_is_the_one_tool_that_says_call_me_first_and_no_description_points_to_a_tool_that_is_not_listed(monkeypatch):
    tools = {t.name: t for t in await production_tools(monkeypatch)}
    first = [n for n, t in tools.items() if "CALL THIS FIRST" in t.description or "USE THIS FIRST" in t.description or "TOOL TO CALL FIRST" in t.description]
    assert first == ["task_plan"] and "THE ONE TOOL TO CALL FIRST" in tools["task_plan"].description
    assert "ratehawk_hotels (" not in tools["hotel_prices"].description and "ratehawk_hotels_recipe" in tools["hotel_prices"].description
    assert "Europcar, Rentalcars" not in tools["other_source_prices"].description.split("Sites that have a tool")[0]      # sites that have a tool are not listed as having none
    for name, t in tools.items():       # a tool name written in a description must be a listed tool (or the word is a site, a field, a state)
        for token in ("task_plan", "quote_guide", "compose_answer", "check_answer", "find_trip"):
            if f"call {token}" in t.description:
                assert token in tools, (name, token)


async def test_the_whole_list_stays_inside_its_budget(monkeypatch):
    tools = await production_tools(monkeypatch)
    tokens = sum(len(t.description or "") + len(json.dumps(t.input_schema)) for t in tools) // 4
    assert len(tools) <= MAX_TOOLS, f"{len(tools)} tools"
    assert tokens <= BUDGET_TOKENS, f"{tokens} tokens: a tool description or schema grew; shorten something or say why the budget must rise"
