# Supplier reservations report, trip 906 ("Test"), 16 Oct 2026 (read only, 11:50 UTC)

Sources: API (`get_supplier_reservations`, `reconcile_trip`), MYT screen Supplier Reservations of trip 906 (row details, Reservation History, PAYMENTS and FILES tabs), `check_reservation_paperwork`. Nothing was changed. Travellers' and users' names are not copied. Today = 16 Oct 2026; every reservation was created on 13 Oct 2026 (3 days ago).

| Order | Supplier | Product | Service date | Cost EUR | Status | Days in status (History) | Voucher | Payments | Files | Itinerary light | Quote check | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R2342258 | Ofran | VW T-Cross | 15 Oct (started 1 day ago; quote says 18 Oct) | 600.00 | Ready To Send | 3 (created 13 Oct 17:01) | N/V | 0 | 0 | no activity found for part of it | MISMATCH: quote line 83.38 | service started, no voucher; amount mismatch; date mismatch |
| R2342207 | Trenitalia | Fiumicino - Firenze | 16 Oct (today) | 60.00 | Ready To Send | 3 (created 13 Oct 16:45) | N/V | 0 | 0 | activity exists | MISMATCH: quote line 113.00 | service today, no voucher; amount mismatch |
| R2342227 | ITCooking | Cooking workshop | 18 Oct (in 2 days) | 300.00 | Ready To Send | 3 (created 13 Oct 16:51) | N/V | 0 | 0 | activity exists | ok (3%) | voucher not sent, service in 2 days |
| R2342231 | Dario Cecchini | Dinner | 19 Oct (in 3 days) | 100.00 | Ready To Send | 3 (created 13 Oct 16:52) | N/V | 0 | 0 | activity exists | ok (3%) | voucher not sent, service in 3 days |
| R2342236 | Relais Vignale | Classic Double Room | 18 Oct (in 2 days) | 474.00 | Ready To Send | 3 (created 13 Oct 16:54) | N/V | 0 | 0 | no activity found for part of it | ok (13%) | voucher not sent, service in 2 days |
| R2342199 | RateHawk | Room Mate Collection Mia | 15 Oct (started) | 225.00 | Voucher Issued | 3 (13 Oct 16:40: created, skipped to COR, voucher printed VCH 2324) | V2324 | 0 | 0 | no activity found for part of it | ok (13%) | no payment, no invoice |
| R2342210 | RateHawk | Berchielli | 16 Oct (today) | 562.00 | Reservation Confirmed | 3 (13 Oct 16:47: created, skipped to COR) | N/V | 0 | 0 | no activity found for part of it | ok (13%) | confirmed but no voucher, service today; no payment |

Totals: 7 reservations, EUR 2,321.00; statuses 5 Ready To Send, 1 Voucher Issued, 1 Reservation Confirmed. **Paperwork complete: 0 of 7.** One voucher (V2324), no supplier invoice, no payment, no file on any reservation.
Drafts (itinerary items without a reservation, "CONVERT" not pressed): PRIVATE TRANSFERS 15 Oct 12:00, Berchielli 16 Oct, VW T-CROSS 18 Oct (3).
Trip 168: 0 reservations (only a quotation).

## What the screen showed that the API does not
- Days in status: every row shows only "Reservation created" (and for the two RateHawk rows "Order skipped to COR"; the voucher row also "Voucher printed VCH # 2324"), all on 13 Oct 2026 between 16:40 and 17:01.
- The traffic-light icon of a row (warning triangle or tick) with the text "No activity found for part of the reservations for this supplier on the trip" or "Activity exists on the trip": four rows have no matching itinerary activity.
- Voucher number (only V2324), PAYMENTS (all 0) and FILES (none).
- Row menus depend on the status: Ready To Send has Check Availability, Send Request, Edit & Send Request, Skip To COR, Skip To COR & Download, Skip To Voucher & Download; Voucher Issued has Create/Edit Invoice, Approve Voucher, Edit/Print Voucher, Edit & Send Voucher, Back To COR, Cancel Voucher, Cancel Vch W/ Email; Reservation Confirmed has Print Voucher, Request Cancellation, Cancel Reservation, Send COR, Download COR, Generate New COR.

## Reading of the three mismatches
Ofran 600 against 83.38 and Trenitalia 60 against 113 were already seen on 15 Oct: the reservations carry the old amounts, the quotation was edited afterwards. The Ofran reservation is dated 15 Oct and the quote line 18 Oct.
