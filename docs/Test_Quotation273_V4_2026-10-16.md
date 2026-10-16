# Test of our system on a finished quote: MYT quotation 273 / V4 (trip 435), 16 Oct 2026, read only

Quote opened from the link the user gave (https://www.manageyourtrip.com/Applications#/quotation/249673), read on the screen only (cost tab, all pages). Nothing was changed in MYT; only the page-2 pager of the transport tab was clicked. No traveller data copied; the names of commission recipients are not recorded here. Trip 435 is not in ALLOWED_TRIP_IDS (276310,189423), so our MCP tools did not read it: only the screen was used (the quote was already used in Validation_2026-10-16.md).

Quote: Portugal and the Azores, 19 Sep to 3 Oct 2026, 29 lines: Transport 12, Staff 3, Lodging 6, Attraction 8, Food 0. Profit in the quote: 13% transport and attractions, 3% flights (Azores Airlines) and lodging, 0% commission and benefit.

Method: the same legs and activities searched for 2 adults on the same day and month one year later (Sep 2027), because the trip is in the past. Net = quote line price / (1 + profit). A line "matches" when our net is within 5% of the quote's net.

## Transfers (quote source: RateHawk Transfers), searched on RateHawk Transfers in the operator's Chrome
| Leg (2027 date, time) | Quote net | RateHawk Transfers now | Verdict |
|---|---|---|---|
| PDL airport to Terra Nostra Garden Hotel, 23 Sep 15:15 | 80 | Economy 76, Comfort 81 | MATCH (Economy -5%, Comfort +1%) |
| Terra Nostra Garden Hotel to Hotel Marina Atlantico, 26 Sep 11:00 | 80 | Economy 72, Comfort 76 | OURS CHEAPER (-10% / -5%) |
| Hotel Marina Atlantico to PDL airport, 27 Sep 13:00 | 35 | Economy 25, Comfort 26, MPV 30 | OURS CHEAPER (-29% / -14% MPV) |
Earlier on Mozio the same legs were 124.80, no transfer and 60.78: RateHawk Transfers is the right source and fits the quote.
Not run today: Madeira airport to hotel (30), Lisbon and Porto airport legs (35, 30), hotel to Lisbon airport (35).

## Activities (quote source: GetYourGuide), our getyourguide_find_activities ("from" price per person, not the exact option price)
| Activity | Quote net | Tool | Verdict |
|---|---|---|---|
| Funchal: Guided Tuk Tuk Tour to Toboggan Rides and Old Town | 38 | 37.50 (4.8, 1,126 reviews) | MATCH |
| Madeira Skywalk, Porto Moniz, Seixal and Fanal 4WD (validation) | 70 | 69 | MATCH |
| Azores Whale Watching and Islet Boat Tour (validation) | 75 | 78 | MATCH (+4%) |
| From Pinhao: Douro Valley Tour with Wine Tasting and Boat Trip | 60 | 55 (3 h, 4.5, 515 reviews) | CLOSE (-8%) |
| From Porto: 516 Arouca Bridge and Paiva Walkways, return transfer and lunch | 125 | 95 for the guided tour (115 for versions with Aveiro) | DIFFERENT OPTION: quote adds transfer and lunch; details tool needed |

## Not covered by any tool of ours
- Artur Azores Tours: Full Day Furnas and Nordeste (125), Full Day Sete Cidades (125): direct local supplier.
- 7M Rent a Car, Madeira (120 a day), and the second car (Toyota Yaris Cross, 125 a day): Ofran may carry the second, not the first.
- Azores Airlines FNC-PDL-PIX-TER-LIS (516.74 at 3%) and two reschedule fees (100, 61): open-jaw route, fees are not search prices.
- Lodging, 6 Arbitrip lines (3%): hotels cannot be priced for past dates and a year ahead is not sold.
- Staff: 2 commission lines and 1 benefit line (0%): amounts come from the operator.

## Result
Of the 25 lines that carry a market price (everything except the 3 staff lines and the 3 flight/fee items that are not searchable): about 10 can be priced by our system (7 transfers on RateHawk Transfers, 5 GetYourGuide activities counted once each); of the 8 we compared today or in the validation, 5 match within 5%, 2 are cheaper than the quote, 1 is a different option. Roughly 11 lines (hotels, local tours, local car, flights) still need the operator's own supplier or a human price.
What our system cannot do yet: write the lines into MYT (the API is read-only), set the markups and return the mini-site link.
