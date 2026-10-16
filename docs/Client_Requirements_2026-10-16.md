# Client requirements, pasted by the user on 16 Oct 2026 (client's words, not edited)

The goal is to identify the most suitable option based on availability, price, and the client's requirements, rather than relying on a single platform.
For hotels, we generally compare RateHawk, Arbitrip, and direct hotel websites, depending on the destination, availability, rates, and booking conditions.
For direct suppliers, flight tickets, lounge access, train tickets, and other services may be sourced from different websites or suppliers depending on the destination and itinerary.

Also in MYT need integrate with supplier reservation, voucher, payment from customer and payment to supplier, balance accounting.

## Where we stand against each line (16 Oct 2026)
1. **Most suitable option, not one platform.** Done for hotels (RateHawk and Arbitrip, detail pages, filters, bed-fit rule, labels Cheapest / Best fit / Most flexible / Recommended), transfers (Kiwitaxi and Mozio), flights (SATA, TAP, Israir), activities (Viator and GetYourGuide), trains (Trenitalia), cars (Ofran), lounges (Aspire).
2. **Hotels: RateHawk, Arbitrip AND direct hotel websites.** RateHawk and Arbitrip are done (browser). **Direct hotel websites: not done yet.** The client's own list (Client_Reply_2026-10-14): bensaudehotels.com, hotihoteis.com, pestana.com, marriott.com, hilton.com, plus booking.com, airbnb.com, agoda.com. Needs the operator's OK per site, read-only in Claude in Chrome; the hotel's official link must come from the operator or MYT, not from web search.
3. **Direct suppliers per destination (flights, lounges, trains, other).** Built: Trenitalia (Italy trains), SATA and TAP (Portugal and Azores flights), Israir (Tel Aviv), Aspire (lounges). Not built: El Al (Radware bot check and Queue-it), ITA Airways, Italo and other train operators, Skyscanner (captcha and terms), Portuguese trains (CP). Source choice by destination is now written in the playbook.
4. **MYT integration: supplier reservation, voucher, payment from customer, payment to supplier, balance accounting.** Built (read only): supplier reservations with status and voucher flags, reconciliation of reservations against quote lines, paperwork check from the trip's own screens. **Not built:** customer payments, supplier payments and balance accounting as a report (they are read from the MYT Trip Balance screens; the API does not have them), and writing changes. Needs the client's written confirmation of this larger scope and its hours (open since the 15 Oct call), and answers in docs/Client_Questions_2026-10-15.md.
