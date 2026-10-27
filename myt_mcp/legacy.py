"""Old tool names that only point to the Chrome recipes.

claude.ai keeps the tool list a chat saw when the connector was added, so a removed name answers 'Unknown tool'; the pointers (tap_flight_prices, sata_flight_prices, viator_search_activities, viator_activity_details,
getyourguide_find_activities, getyourguide_activity_details, ofran_find_location, ofran_car_prices, ratehawk_hotels) answered with the right tool instead. They cost about 2,150 tokens in every chat and a chat sometimes
called one (27 Oct 2026), so they are no longer listed unless LEGACY_TOOL_POINTERS=1: re-add the connector once and the list is the short one. Their real tools stay in the code behind their own switches
(TAP_SERVER_BROWSER, SATA_SERVER_BROWSER, VIATOR_SERVER_BROWSER, GYG_SERVER_BROWSER, OFRAN_SERVER_SEARCH, RATEHAWK_SERVER_BROWSER).
"""

import os


def legacy_pointers() -> bool:
    return os.environ.get("LEGACY_TOOL_POINTERS", "").strip().lower() in ("1", "true", "yes")
