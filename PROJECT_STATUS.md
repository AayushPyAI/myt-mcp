# Project status (updated 2026-10-12)

| Module | Status | Notes |
|---|---|---|
| A. MYT read: trip, itinerary, travellers, quote and totals | ✅ Done | Live on test trip #906; other trips blocked by `ALLOWED_TRIP_IDS` |
| A. MYT write: quote lines, markups, version, mini-site link | 🔴 Blocked | Public API has no write endpoints. Asked MYT CEO (meeting 2026-10-12). Fallback: Claude in Chrome on the COST tab (untested) |
| Quote math (`calculate_quote`) | ✅ Done | Matches MYT to the cent |
| B. Hotels: RateHawk | ✅ Works via Claude in Chrome | Operator's logged-in browser. Tested 17–18 Oct: Lisboa Plaza €189 |
| B. Hotels: Arbitrip | ✅ Works via Claude in Chrome | Tested: Lisboa Plaza €189 room only / €200 breakfast / €244 free cancellation. **Needs client's written OK** (terms ban automation) |
| C. Cars: Ofran | ✅ Server tool | Own JSON feed; blocked from India, so it needs non-India hosting or the VPN browser |
| C. Trains: Trenitalia | ✅ Server tool | Live fares by class; Firenze→Roma tested |
| D. GetYourGuide | ✅ Connector (search, from price) + our `getyourguide_activity_details` | Adds start times, exact group price, meeting point, cancellation, traveller groups per activity. Tested live (Florence pasta class, 2 adults, with children) |
| D. Viator / Tripadvisor Experiences | ✅ Server tool | Search + exact group price on a date, start times, meeting point, cancellation. Runs in the automation Chrome (DataDome blocks plain HTTP). Tested: Florence cooking class, Sintra day trip |
| Edge cases | ✅ 105+ live cases, 0 open | Found and fixed: Rome→Rometta, romma→Bromma (Sweden), emoji searches, misleading errors, Viator calendar vs group-price contradiction. Claude-side plan in docs |
| Data correctness | ✅ | Every answer checked against the search; mismatches refused; `checked_at` on every price; `scripts/live_check.py` live PASS/FAIL per source (2026-10-12: MYT, Trenitalia, SATA, Aspire, Viator PASS; Ofran blocked from India) |
| E. Claude instructions | ✅ ~90% | Workflow, mapping, scraping rules, hotel/car/train steps, GYG + Viator comparison table. Pending client answers on quote rules |
| F. Mini-site link | ⏳ | Depends on MYT write API / "Update Mini-Site" |
| G. Hosting | ⏳ | Temporary Cloudflare tunnel from a laptop. Move to Railway/Render (outside India) |
| G. Testing with operator + Loom | ⏳ | After MYT write works |
| Flights: SATA (S4 + SP inter-island) | ✅ Server tool | Scraped from SATA's own booking site in the automation Chrome. One way + round trip, every fare's group total and conditions. Tested LIS↔PDL (€502.99, 2+1), PDL→PIX, PDL→HOR. Other airlines: no tool yet |
| Aspire Lounge | ✅ Server tool | Lounges per airport + group price for a flight time. Tested TLV (€80 adult) and Venice (€49 adult) |

## Waiting on the client
- MYT write API (CEO meeting)
- Arbitrip written OK
- Correct car site instead of Meckano
- Direct-supplier rates location
- Quote rules: 13%, 5%, €230 Other, new version or existing
- Hosting cost (hosted server also needs a browser for Viator)
- Rotate the SerpAPI and Tavily keys that were shared in chat
- Which other airlines they price besides SATA (each would be its own site)
- Other lounge providers they use (besides Aspire)
