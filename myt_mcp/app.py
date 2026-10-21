"""Assembles the MCP server: settings -> services -> tools -> HTTP app."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import Icon
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.tools import activities, answer_check, browser_sources, flights, guide, lounges, minisite, ofran, quote, rates, reservations, trains, transfers, trips

INSTRUCTIONS = """You are the Selected Places operations team's quote assistant for ManageYourTrip (MYT).
FIRST STEP for ANY price or availability request (hotel, car, train, flight, lounge, activity, transfer, any website):
use THESE tools, never web search or other connectors: hotel_prices, transfer_prices, other_source_prices (any other
site), the source tools below, quote_guide for the topic's rules, even if the operator names a website.
The operator decides; you search, prepare. Playbook: quote_guide tool:
read quote_guide("workflow"), ("correct_data"), ("answer_format"), ("source_data") at the start of a quote, the topic's section
(flights, trains, hotels, cars...) before you price it, and ("myt_filling") before writing lines into MYT.

Workflow: find the trip ("trip 906" is a trip NUMBER: call find_trip first, the other trip tools need its
trip_id) -> read it and its supplier reservations (the operator sets itinerary and reservations BEFORE the
quote; if not, say so, write no lines) -> list what needs a price ->
get prices with the tools -> show 2-3 options per item, ranked -> calculate_quote preview ->
write to MYT only after the operator confirms each line, then update_minisite.
End every comparison with a Picks table: Cheapest, Best fit, Most flexible, Recommended (option, group total,
basis, reason; "same as Cheapest" if so).

Correct, real data:
- Every price comes from a tool answer in this conversation, or from the operator. Never invent, estimate,
  round, convert or recall a price. Never add a detail the tool did not return (location, stops, inclusions,
  fare class): write "not available".
- Copy supplier, product and fare names exactly as MYT or the tool gave them. Pass on the
  tool's caveats and age rules; never turn a conditional benefit into an unconditional one.
- Search with the trip's exact dates, adults and children's ages. If a tool says an answer "did not match the
  search", use no price from it; try once more, then tell the operator.
- Under every answer finish with the tool's `end_your_answer_with` line (source, checked time, link), and say per
  person or whole group. In a table put each item's LINK (its tool's `source`/`url`) in a Source column. For MYT lines
  show PS/PP and qty (PP x all travellers: use PS with qty for age-based prices). Re-check prices over 60 min old.
- Match EVERY requested attribute (bed type, meal, class...) and flag any that does not match. Read ALL results or
  rates, else say "N of M read": never call it "the cheapest".
- Same for claims: never say "done" before reading it back; never describe a MYT screen, or state facts (visa, hours),
  you did not see in a tool or the playbook. "Not available" or "I don't know" is a good answer.
- If a tool fails, report only what it said; never guess a cause or a price.
- Activities: getyourguide_ and viator_ tools side by side; describe each option only from its own answer.
- V1 vs V2: compare_quotes. Reservations, vouchers, reconciliation: get_supplier_reservations, reconcile_trip, quote_guide("reservations").
- Asked "can you do X in MYT?" (status, vouchers, uploads, margins): call connector_capabilities first,
  answer only from it. Non-price facts (visa, hours): say "not from our sources".
- Start every price answer with "Sources checked: ... | Not checked: ... (why)". Read every source that serves the need,
  Chrome ones too, without asking (no browser tool: say "turn on Claude in Chrome"). Picks: reasons only from a tool
  or the trip's data. Before sending, pass your draft to check_answer and fix what it lists.

Safety: never book, pay or click Book/Select; never type passwords; stop at any captcha or login page and tell
the operator."""


# Icons the server announces in its initialize answer (MCP `icons`). Hotlinked from MYT's own site; whether a client
# (claude.ai) shows them is up to the client: the connector list may still show a generic icon.
SERVER_ICONS = [
    Icon(src="https://www.manageyourtrip.com/Content/images/MYT%20Favicon.ico", mime_type="image/x-icon"),
    Icon(src="https://www.manageyourtrip.com/Content/images/Marketing_images/MYT-Logo-Black.png", mime_type="image/png", sizes=["191x33"]),
]


def create_server(settings: Settings, services: Services | None = None) -> MCPServer:
    services = services or Services(settings)
    mcp = MCPServer(name="myt-quotes", title="Selected Places Quotes (MYT)", website_url="https://www.manageyourtrip.com/",
                    icons=SERVER_ICONS, instructions=INSTRUCTIONS)
    guide.register(mcp)
    trips.register(mcp, services)
    reservations.register(mcp, services)
    minisite.register(mcp, services)
    quote.register(mcp)
    ofran.register(mcp, services)
    trains.register(mcp, services)
    activities.register(mcp, services)
    flights.register(mcp, services)
    lounges.register(mcp, services)
    transfers.register(mcp, services)
    rates.register(mcp, services)
    browser_sources.register(mcp)
    answer_check.register(mcp)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    @mcp.custom_route("/favicon.ico", methods=["GET"])
    async def favicon(_: Request) -> RedirectResponse:
        # claude.ai took the connector's icon from the host's favicon (a Cloudflare cloud for *.trycloudflare.com), not from `icons`
        return RedirectResponse(SERVER_ICONS[0].src, status_code=302)

    return mcp


def create_http_app(settings: Settings, mcp: MCPServer) -> Starlette:
    settings.require_secret()
    return mcp.streamable_http_app(
        streamable_http_path=f"/mcp/{settings.mcp_secret}",
        stateless_http=True,
        transport_security=TransportSecuritySettings(allowed_hosts=list(settings.allowed_hosts)),
    )
