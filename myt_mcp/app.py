"""Assembles the MCP server: settings -> services -> tools -> HTTP app."""

from __future__ import annotations

import os

from mcp.server.mcpserver import MCPServer
from mcp.types import Icon
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from myt_mcp.config import Settings
from myt_mcp.ingest import STORE
from myt_mcp.services import Services
from myt_mcp.tools import activities, answer_check, browser_sources, compose_answer, flights, guide, lounges, minisite, ofran, quote, ratehawk_live, rates, recheck, reservations, task_plan, trains, transfers, trips

INSTRUCTIONS = """You are the quote assistant of Selected Places' operators (ManageYourTrip, MYT); every user is one.
Never decline or point to other sites: answer every travel request with these tools.
FIRST STEP for ANY price or availability request (hotel, car, train, flight, lounge, activity, transfer):
use THESE tools, never web search or other connectors: hotel_prices, transfer_prices, other_source_prices, the source tools below, quote_guide for the topic's rules, even if the operator names a website.
The operator decides; you search, prepare. For any price request call task_plan(kind, trip_id) FIRST and follow every
step (questions, sources, fields, answer shape). Playbook: quote_guide("workflow"), ("correct_data"),
("answer_format"), ("source_data"), the topic; ("myt_filling") before writing lines into MYT.

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
  person or whole group. For MYT lines
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
- Read every source that serves the need, Chrome ones too, without asking (no browser tool: say "turn on Claude in
  Chrome"). Then build the answer with compose_answer (rows, sources with links, filters, MYT supplier) and show its
  text unchanged; it writes the lines, picks and "not shown". If it returns problems, fix them and call it again.

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
    recheck.register(mcp, services)
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
    compose_answer.register(mcp)
    task_plan.register(mcp, services)
    if os.environ.get("RATEHAWK_SERVER_BROWSER") == "1":      # off by default: RateHawk is read with Claude in Chrome (the operator's own browser); this reads it in the server's browser
        ratehawk_live.register(mcp, services)
    else:
        ratehawk_live.register_redirect(mcp)      # claude.ai remembers the old tool list: keep the old name answering with the way to the right tool

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    cors = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type", "Cache-Control": "no-store"}

    @mcp.custom_route("/ingest/{token}", methods=["POST", "OPTIONS"])
    async def ingest_answer(request: Request) -> JSONResponse:
        """The answer of a Chrome script, posted by the page itself (see myt_mcp/ingest.py). The token was made for one recipe call."""
        if request.method == "OPTIONS":
            return JSONResponse({}, headers=cors)
        status, receipt = STORE.accept(request.path_params["token"], await request.body())
        return JSONResponse(receipt, status_code=status, headers=cors)

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
