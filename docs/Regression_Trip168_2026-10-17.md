# Regression check, trip 168, quotation 82 V2 (17 Oct 2026, read only)

Method: every quote line our tools can read was re-priced with today's tools for the same date and group (2 adults + child 8), and the NET price (quote total divided by 1.13 for transport and attractions, 1.03 for lodging) was compared with the live price. Nothing was written to MYT.

| # | Line | Quote net | Live (17 Oct) | Result |
|---|---|---|---|---|
| 3 | Trenitalia Frecciarossa 9520, 4 Mar, Standard BASE | 125.00 | 125.00 | exact |
| 4 | TAP TP875 FLR-LIS, 6 Mar, fare CLANEW | 530.38 | 530.38 | exact |
| 6 | SATA S4 125 LIS-PDL, 8 Mar, fare BSC | 250.04 | 250.04 (BSC_DOMESTIC_BF) | exact |
| 13 | GetYourGuide Vatican tour, All 3 sites, 3 Mar 10:00 | 227.00 | 227.00 | exact |
| 14 | GetYourGuide Golf Cart Tour Highlights of Florence and Hills, 5 Mar 9:30 | 239.97 | 239.97 | exact |
| 1 | Ofran Peugeot 3008, Lisbon Airport, 6-8 Mar | 245.93 | 209.77 (read in the operator's Chrome, "3 days rental") | differs by -14.7%, unexplained: ask Meylinda which price, dates and profit she used |
| 2 | Transfer FCO - Room Mate Mia (RateHawk) | 81.00 | Mozio cheapest 92.08 | RateHawk not re-read (Chrome disconnected); Mozio is 14% higher |
| 5 | Transfer Berchielli - FLR (RateHawk) | 99.00 | Mozio cheapest 150.79 | same: Mozio 52% higher |
| 7 | Transfer PDL - Terra Nostra (RateHawk) | 100.00 | Mozio cheapest 130.79 | Mozio 31% higher |
| 8 | Transfer Terra Nostra - PDL (RateHawk) | 100.00 | Mozio cheapest 120.79 | Mozio 21% higher |
| 9-12 | Four hotels | - | not re-read today | Lisbon: H10 Duque de Loule sold out, Altis Grand compared, see the Lisbon sheet |
| 15 | Pure Azores tour | - | no source tool | not checkable |

Score: 5 of 5 lines that could be re-read on the same fare and option match exactly (0.00%); 1 differs (Ofran); 4 transfer lines were compared with a second source only; 5 lines were not re-read.

Things the re-read showed:
- Trenitalia for the same train has cheaper fares than BASE: Economy 99.80, Super Economy 59.80, FrecciaFAMILY 50.00, FrecciaFRIENDS 63.00, FrecciaDAYS 49.80 (all STANDARD class, whole group, EUR). The data does not give their conditions: check on trenitalia.com before offering any.
- TAP: DISCNEW 434.38 (no checked bag) against CLANEW 530.38 (23 kg bag, the quoted fare).
- SATA fares for the same flight: SPL 217.04, BSC 250.04 (quoted), FLX 283.04, TOP 408.04.
- GetYourGuide "read all relevant" stopped by itself: golf-cart search read 5 pages, 14 relevant of 120 read (599 on the site); the quoted tour was found by its exact title.
