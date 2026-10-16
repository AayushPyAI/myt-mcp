# Line sheet, trip 168 (MYT id 189423), quotation 82 V2 (Draft). Prices read on 16 Oct 2026. NOTHING IS WRITTEN YET.

Group: 2 adults + 1 child aged 8 (age from the operator, not MYT). Currency EUR. "Net" = supplier price; "Quote line" = net x (1 + profit). Profit assumed from the finished quotes (validation, quote 273): transport and attractions 13%, flights 3% (Azores Airlines line seen at 3%). All profit values are to be confirmed by Meylinda. MYT today: 8 lines, subtotal EUR 3,624.99 (read just now through the API, unchanged).

## A. Ready to write after the operator's yes (price found)
| # | Category | Supplier (MYT) | Product | Date | Qty | Net | Quote line (profit) | Source, checked | Open point |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Transportation | RateHawk Transfers (see note) | FCO airport to Room Mate Collection Mia, Economy, 3 seats | 1 Mar 2027 16:30 | 1 | 81.00 | 91.53 (13%) | RateHawk Transfers, 16 Oct | Real flight time; Comfort 82, Business 88 |
| 2 | Transportation | RateHawk Transfers | Hotel Berchielli to FLR airport, Economy | 6 Mar 2027 | 1 | 99.00 | 111.87 (13%) | RateHawk Transfers, 16 Oct (read for 08:45) | Pick-up time from TAP TP875 dep 12:20; Business 105 |
| 3 | Transportation | RateHawk Transfers | PDL airport to Terra Nostra Garden Hotel, Economy | 8 Mar 2027 | 1 | 100.00 | 113.00 (13%) | RateHawk Transfers, 16 Oct (read for 14:15) | Real arrival time (flight LIS-PDL 14:05 arr.?); Minibus 110 |
| 4 | Transportation | RateHawk Transfers | Terra Nostra Garden Hotel to PDL airport, Economy | 11 Mar 2027 | 1 | 100.00 | 113.00 (13%) | RateHawk Transfers, 16 Oct (read for 08:15) | Pick-up from flight 6H582 12:10 |
| 5 | Transportation | TAP Air Portugal | FLR to LIS TP875 12:20-14:30, direct, no checked bag (Discount) | 6 Mar 2027 | 1 (group) | 434.38 | 447.41 (3%) | tap.com tool, 16 Oct; RateHawk shows 438.38 | Fare: with 23 kg bag 530.38 (546.29 with 3%); refundable 654.38 |
| 6 | Attraction | Get Your Guide | Golf Cart Tour: Highlights of Florence and Hills, 3 h, free cancellation until 4 Mar | 5 Mar 2027, 9:30 / 13:00 / 16:30 | 1 (group) | 239.97 | 271.17 (13%) | getyourguide_activity_details, 16 Oct 09:26 UTC | Start time; cheaper other tour: Official Grand Panoramic EUR 128 |

Sum of lines 1-6 net 1,054.35; with the assumed profit 1,148.38. Quote subtotal would go from 3,624.99 to about 4,773.37 before items B and C.

## B. Price found but the operator must choose first
| Item | Options | Needed from the operator |
|---|---|---|
| Lisbon hotel 6-8 Mar (2 nights) | see docs/Lisbon_Hotel_Decision_2026-10-16.md | Hotel, bed set-up for 2 adults + child, breakfast, cancellation |
| Lisbon car 6-8 Mar (existing line: Ofran Peugeot 3008, 277.90) | Ofran net 229.54 (excess cancellation included) vs RateHawk Ford Kuga IDAR Zero excess 147.60 (166.79 with 13%) or Peugeot 3008 IFAR Refundable excess 157.20 (EUR 3,500 deposit) | Keep Ofran or switch; whether Zero excess equals Ofran's excess cancellation |

## C. No price source yet
| Item | Why | Needed |
|---|---|---|
| Flight TLV to FCO 6H581, 1 Mar 15:10 (Israir) | Agency block seats ("BATCH 02"), not in public search; Israir public: USD 237 for the 3 passengers on a different flight 349 | Batch/contract price from the operator or the client |
| Flight PDL to TLV 6H582, 11 Mar 12:10 | same | same |
| Optional: TLV lounge (Aspire, EUR 240 for the group), commission / benefit Staff lines | not decided | Operator |

## Notes for writing (when the operator says yes)
- Supplier names must be copied exactly from the MYT supplier list. Finished quote 273 carries the supplier "RateHawk" on its transfer lines, so ask Meylinda how that row is created (a DMC supplier did not stay in the row before). The existing line already uses supplier "Get Your Guide" (id 81856) and "Azore Airlines" (id 46627).
- A price older than 60 minutes must be re-read before the line is written. All transfer prices above were read earlier today and need a quick re-check.
- Lines are written in the browser with Claude in Chrome, one line at a time, only after the operator's yes. Never press Update Mini-Site or change the selected quotation version.
