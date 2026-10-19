# myt-mcp

MCP server that lets Claude read ManageYourTrip (MYT) trips and quotes, preview quote prices, and fetch live prices for cars (Ofran), Italian trains (Trenitalia), activities (Viator), SATA flights (azoresairlines.pt) and airport lounges (Aspire), for the Selected Places operations team.

## Tools
| Tool | What it does |
|---|---|
| `find_trip`, `get_trip`, `get_trip_participants` | Read trips, itinerary and travellers (MYT public API) |
| `get_quotation` | Read the selected quote: lines, markups, MYT's per-person and group totals |
| `update_minisite` | After a quote exists: POST the mini-site webhook (preview, then confirm) and return the customer `trip_url` |
| `quote_guide` | The operators' playbook, one topic at a time (workflow, correct data, flights, activities, hotels…) |
| `calculate_quote` | Preview a quote with MYT's pricing rule (13% line profit × 5% conversion + fixed markups) |
| `ofran_find_location`, `ofran_car_prices` | Ofran pick-up points and live car offers, cheapest first |
| `train_find_station`, `train_prices` | Trenitalia stations, and trains with fares by class for a date and group |
| `viator_search_activities` | Viator activities for a search: "from" price, rating, duration, free cancellation, link |
| `sata_flight_prices` | SATA fares (S4 + SP inter-island), one way or round trip, from SATA's booking site: total for the group, every fare's price and conditions |
| `lounge_prices` | Aspire lounges at an airport: entry/exit time, ticket prices, group total |
| `getyourguide_activity_details` | What the GetYourGuide connector lacks, for one activity link: options with start times, exact group price, meeting point, cancellation, highlights, includes |
| `viator_activity_details` | One activity: options, start times, exact group price on a date, meeting point/pickup, inclusions, cancellation |

Writing to MYT quotes is not built yet (the public API has no endpoint for it; see `myt_mcp/myt/quote_api.py`).

## Layout
```
server.py                 entry point: settings -> server -> uvicorn
myt_mcp/
  config.py               all settings from .env, validated at start-up
  errors.py               tool_errors: every failure becomes a clear message, never a crash
  cache.py                async TTL cache (concurrent callers share one load)
  ratelimit.py            per-site pacing + hourly cap for scraped sources
  browser.py              one shared Playwright connection to the automation Chrome
  services.py             builds every outside client once (MYT, Ofran, Trenitalia, Viator, SATA, Aspire) and shares them; trip allow-list
  checks.py               data checks (answer must match the search) + checked_at on every price
  app.py                  creates the MCPServer and the HTTP app
  tools/                  thin MCP tools (input checks + calling services): trips, quote, ofran, trains, activities, flights, lounges
  myt/                    MYT: client.py (HTTP + errors + 60 s trip cache), summaries.py, quote_api.py
  ofran/                  Ofran: transport.py (HTTP or browser), locations.py, offers.py, client.py
  trenitalia/             Trenitalia (lefrecce.it JSON): client.py, parse.py
  viator/                 Viator (pages in the automation Chrome): client.py, parse.py
  gyg/                    GetYourGuide details (page + availability service, in the automation Chrome): client.py, parse.py
  sata/                   SATA booking site (read in the automation Chrome): client.py, parse.py
  lounges/                Aspire Lounges: aspire.py (HTTP or browser transport), parse.py
  quote/calc.py           MYT pricing rule
tests/                    127 tests, no network (fixtures/ = trimmed real Viator, GetYourGuide, SATA and Aspire answers)
```

## Correct, real data
- **Match checks** (`myt_mcp/checks.py` and a `check_*` function next to each parser):
  - every answer is compared with the search: route, dates and times, travellers, product or trip id, currency EUR, and totals that add up;
  - a mismatch raises `DataCheckError`, and the price is never shown.
- **checked_at / data_age_minutes** on every price answer: the time the data was really fetched, even when it comes from the 10-minute cache.
- **Edge-case sweep:** `.venv/bin/python scripts/edge_check.py [group]` sends 100+ odd, wrong and extreme inputs to every tool, live, and reports crashes, wrong answers and unclear messages. Claude-side prompts: `../docs/Edge_Case_Test_Plan.md`.
- **Live self-check:** `.venv/bin/python scripts/live_check.py` runs one real search per source and prints PASS/FAIL with a sample price. Run it before demos or daily.

## Run locally
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill MYT_API_KEY, MCP_SECRET, ALLOWED_TRIP_IDS
.venv/bin/python server.py       # http://127.0.0.1:8000/mcp/<MCP_SECRET>
.venv/bin/python -m pytest -q
```

## Ofran, Viator, hotels and the browser
- **Ofran (cars), server tool.** Ofran answers 403 to Indian IPs.
  - Hosted outside India: nothing to set; requests go straight over HTTPS (`OFRAN_PROXY` optional).
  - Local testing from India: start the automation Chrome (`--remote-debugging-port=9333`, profile `~/myt-ofran-chrome`) with a VPN extension on, then set `BROWSER_CDP_URL=http://127.0.0.1:9333` and `OFRAN_USE_BROWSER=true`.
- **Viator (activities), server tool.** viator.com blocks plain HTTP (DataDome), so pages are read in the automation Chrome (`BROWSER_CDP_URL`).
  - Set Viator's currency to EUR once in that browser (header → Currency); the tools warn if it isn't EUR.
  - The group price comes from the same "Check Availability" request the page makes. Nothing is booked or held.
  - `VIATOR_ENABLED=false` switches it off.
- **SATA flights, server tool.** SATA's search service only answers its own booking page (each call carries the page's invisible reCAPTCHA token), so we never call it directly. The tool opens SATA's booking page with the search in the link, in the automation Chrome, and reads the flight list the page receives. A refusal or a human check stops it. No third-party search APIs (SerpAPI, Serper, Tavily) are used.
- **Aspire lounges, server tool.** The website's own price service. Goes through the automation Chrome when `BROWSER_CDP_URL` is set (the site is behind Cloudflare), else plain HTTPS. Only the price check is called, never booking or payment.
- **RateHawk and Arbitrip (hotels), not server tools.** Claude reads them through **Claude in Chrome**, in the operator's own logged-in browser, following the rules in `instructions/claude_project.md`.
- **Scraping safety** (Ofran, Trenitalia, Viator, SATA, Aspire):
  - the same search is answered from memory for `SCRAPE_CACHE_MINUTES` (10)
  - `SCRAPE_MIN_INTERVAL_SECONDS` (5) between requests, at most `SCRAPE_MAX_PER_HOUR` (60)
  - a captcha stops the search
  - `OFRAN_ENABLED`, `TRENITALIA_ENABLED`, `VIATOR_ENABLED`, `ASPIRE_ENABLED`, `SATA_ENABLED` = `false` switch a source off
  - Full rules: `../docs/Scraping_Rules.md`.

## Connect to Claude
Deploy, set the env vars, and add the domain to `ALLOWED_HOSTS`. In Claude, add a custom connector with `https://<domain>/mcp/<MCP_SECRET>`, No Project instructions to paste: the server sends Claude its core rules when the connector connects, and Claude reads the detailed playbook (`instructions/claude_project.md`) through the `quote_guide` tool. Edit that file and restart the server to change the rules. The secret in the URL is the only protection, so keep it private.
