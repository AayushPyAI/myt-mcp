# Validation on three finished trips with a real quote (16 Oct 2026, read only)

Trips (MYT trip numbers; quotation numbers in brackets): **456** (quotation 289 V1, Italy, 19-27 May 2026, 2 pax), **518** (quotation 308 V2, Italian Riviera and Tuscany, 11-23 Jun 2026, 2 pax), **435** (quotation 273 V4, Portugal and the Azores, 19 Sep-3 Oct 2026, 2 pax). Read through our MCP (get_quotation) after adding only these trip ids to ALLOWED_TRIP_IDS; the allowlist was restored afterwards (276310,189423) and the three trips are blocked again. No traveller names, emails or phones were used. Quotes are in EUR; "net" = line price divided by (1 + profit): profit is 13% on transport and attractions, 3% on food and lodging (Arbitrip and RateHawk contract rate), 0% on commission and benefit lines.

Method: the same lines were searched with our tools for 2 adults on the same day and month one year later (the trips are in the past; hotels and trains are not published a year ahead). A line "matches" when our net is within 5% of the quote's net.

## Result per line
| Line (supplier in the quote) | Quote net | Our result | Verdict |
|---|---|---|---|
| Train Termini to Firenze 21 May (Trenitalia, PP) | EUR 50 pp = 100 | Frecciarossa 9520, Standard BASE (flexible) EUR 100.00 for 2 adults | MATCH (exact) |
| Golf Cart Tour: Highlights of Florence and Hills (GetYourGuide, PP) | EUR 80 pp | EUR 79.99 pp | MATCH |
| Madeira Skywalk, Porto Moniz, Seixal and Fanal 4WD Tour (GetYourGuide) | EUR 70 pp | EUR 69 pp | MATCH |
| Azores Whale Watching and Islet Boat Tour (GetYourGuide) | EUR 75 pp | EUR 78 pp | MATCH (+4%) |
| Transfer Madeira airport to hotel (RateHawk Transfers) | EUR 30 | Mozio EUR 25.81 | MATCH (ours cheaper) |
| Transfer FCO to hotel Rome (RateHawk Transfers) | EUR 70 (2 pax) | Mozio EUR 102.31, Kiwitaxi EUR 106 | NO: +46% to +51% |
| Transfer PDL airport to Terra Nostra (RateHawk) | EUR 80 | Mozio EUR 124.80 | NO: +56% |
| Transfer hotel Marina to PDL airport (RateHawk) | EUR 35 | Mozio EUR 60.78 | NO: +74% |
| Transfer Porto airport to hotel (RateHawk) | EUR 30 | Mozio EUR 39.79 | NO: +33% |
| Transfer Terra Nostra to Hotel Marina Atlantico (RateHawk) | EUR 80 | Mozio: no transfer | NO |
| Uffizi and Accademia timed tickets (GetYourGuide, PP) | EUR 78 pp | EUR 41.50 pp (the product is now called "Timed Combo Tickets and Audio App") | NO: ours 47% lower, product or option differs |
| Rapallo Sunset Boat Tour (GetYourGuide, PP) | EUR 75 pp | not listed (14 Rapallo results, none with that name) | NOT FOUND |
| Train Rapallo-Levanto (Trenitalia, regional, PP) | EUR 15 pp | Trenitalia answers 400 (regional trains are published only to the December timetable) | CANNOT TEST |
| Hotels (Arbitrip and RateHawk), 15 lines, 3% profit | EUR 158-487 a night | Terra Nostra Garden, 23-26 Sep 2027 (Arbitrip): no rooms for that date | CANNOT TEST (dates a year ahead are not sold) |
| Ofran cars (VW T-Cross EUR 650, Toyota Yaris Cross EUR 125 a day...) | see quote | not run: pick-up place and exact times are not in the quote | NOT TESTED |
| Cooking class, wine tasting, dinner, e-bike tour, Artur Azores Tours day tours, Portugo culinary tour, museum tickets | various | no tool (direct suppliers) | NOT COVERED |
| Azores Airlines multi-city flights and reschedule fees | EUR 471 pp + fees | not run (open-jaw route) | NOT TESTED |
| Commission and Benefit lines (staff) | 0% profit | not a price | n/a |

Score on the lines we could test: 5 match of 13 (train, golf cart, Madeira tour, whale tour, Madeira transfer); 6 do not match (5 transfers, Uffizi); 1 not found; 1 cannot test.

## What the check found
1. **Transfers are the main gap.** The agency books transfers on **RateHawk Transfers** (the Transfers tab in RateHawk). Same search as trip 168 (FCO to Room Mate Collection Mia, 1 Mar 2027 16:30, 2 adults and a child): RateHawk Economy EUR 81, Comfort 82, Business 88, Business MPV 98 (3 seats and 3 bags, 60 min waiting, free cancellation 24 h); our Mozio EUR 91.30 and Kiwitaxi EUR 106. RateHawk Transfers is the cheapest and is what the quotes use: it must become a transfer source (read in Claude in Chrome, like hotels).
2. **Trains:** the agency sells the flexible BASE fare (EUR 50 pp). Our tool shows it per train when asked (fares for one train); it matched exactly. The default "cheapest" is a cheaper fare class: say which fare class a quote line uses.
3. **Activities:** GetYourGuide matched on the tours that still exist in the same form; a product can be renamed or removed (Rapallo sunset tour), so the line must be searched again before it is reused.
4. **Hotels** could not be compared: past dates cannot be priced and dates a year ahead are not sold. A fair test needs a trip that is 2-4 months ahead (hotel, train and car prices are then live).
5. **Profit rules seen in the quotes:** transport and attractions 13%, food 3%, lodging 3% (Arbitrip and RateHawk), commission and benefit 0%.
6. **Structure of a real quote** (what a complete quote contains): Transport (transfers on RateHawk, trains, cars from Ofran or a local company, flights from Azores Airlines with reschedule fees), Food (cooking class, wine tasting, dinner), Staff (Commission, Commission Get Client, Benefit), Lodging (one line per hotel, PS, per night, BB), Attraction (GetYourGuide and local operators), 12 to 29 lines.
