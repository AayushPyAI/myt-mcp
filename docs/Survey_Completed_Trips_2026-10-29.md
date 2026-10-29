# Survey of completed trips: supplier reservations and quotes, 29 Oct 2026 (read only)

Read through MYT's public API (`GetTrips` status Completed, `GetTrip/v3`) with our own read-only functions (`reservations_summary`, `reconcile`, `quotation_summary`), one trip at a time with a 1.2 s pause. Nothing was changed in MYT. No customer, traveller or supplier name is recorded here: only counts, categories, statuses and amounts. Two screens were looked at (Reports > Receipts and Supplier Reservations of trip 190148), nothing pressed.

## What was read
- The first page of the Completed list: 100 trips (the newest trip ids first), plus trip 190148 (named by the operator) and trip 435 (internal id 235475, the reference trip of 17 Oct).
- 57 of the 100 are test-like (only "Ready To Send" reservations, no quote): left out of the numbers below.
- 44 are real-looking (some reservation past "Ready To Send", or a quote): the numbers below.

## Findings (44 real-looking trips)

| What | Result |
|---|---|
| Both reservations and a quote | **43 of 44**; 1 has reservations only; none has a quote only |
| Supplier reservations per trip | 17 to 41 rows in 11 to 28 orders (an order = all the rows of one supplier) |
| Quote lines per trip | 8 to 46, mostly 16 to 31 |
| Quote lines by category (43 trips) | Attraction 233, Lodging 219, Transport 172, Staff 97, Food 54, DMC 1 |
| Reservation statuses | mostly **Voucher Paid**, then Voucher Issued; every trip has 0 to 10 **Rejected By Operator** rows (a booking that was replaced) |
| Quote status | 40 Draft, 3 Lost (a finished trip's quote stays Draft) |
| Reservation against quote line (`reconcile_trip`) | ok 176, **MISMATCH 277**, CURRENCY 139: only about 30 % match cleanly |
| Profit % implied by the quote line over the reservation cost | **13 %** most often (36 trips), then **3 %** (29), 0 % (21), 15 % (15), 14 % (14), 21 %, 16 %, 17 %, 34 %, 4 %: there is no single rule |
| A quote line's supplier also has a reservation on the same trip | about **41 %** |
| Quote lines subtotal over reservation cost (same currency, trip 435) | 1.11 |

## What it says about how the two are connected
1. A reservation is a **supplier order**: all the hotels of a trip can sit in ONE order under a booking platform (Arbitrip), transfers under RateHawk, tours under Get Your Guide. A quote line is **one item** with its own profit %. So they do not map one to one (trip 435: 41 reservation rows in 26 orders against 29 quote lines; 23 reservations without a quote line and 11 quote lines without a reservation).
2. A quote is **not** rebuilt when a reservation changes; each keeps its own amount. The totals are close, not equal (trip 435: reservations 7,878.94, quote net 7,852.34; trip 906: 2,321.00 = 2,321.00).
3. The profit % differs line by line (13 %, 3 %, 15 %...): a quote cannot be derived from a reservation with one fixed percentage.
4. The API gives no creation time of a reservation or of a quote, so **which came first cannot be proven from the data**. The operator says reservations first (22 Oct 2026).
5. Our own flow today: prices of the quote come from the search answers; reservations are created apart (`plan_supplier_reservations`); the two are only compared afterwards (`reconcile_trip`). No code builds quote lines from reservations.

## Trip 190148 (named by the operator; the screen and the API agree)
- 18 reservation rows in 12 orders, total 2,961.08 EUR (plus USD rows), **all "Ready To Send" and N/V (no voucher)**: Transport 3, Food 4, Lodging 3 shown on the screen. Some amounts are placeholders (0.00 and 5.00).
- Quote V1 (Draft): 8 lines (Transport 1, Food 3, Lodging 3, DMC 1), net group price 18,868 EUR, group price 30,225 EUR.
- `reconcile_trip`: only 2 lines pair up (both MISMATCH, the reservation far below the quote line), 16 reservations have no quote line, 6 quote lines have no reservation.
- Reading: reservations here were made from the itinerary drafts (one per supplier), still small and unsent, while the quote is coarser and larger. The screen has the tabs SUPPLIER RESERVATIONS, SUPPLIER INVOICES, CLIENT RESERVATIONS, PACKAGES, CALENDAR.

## Receipts (read the same day)
- Reports > RECEIPTS (`#/reports/receipts`) lists the receipts. The list comes from the web app's own call `/api/receipt/GetReceipts` (needs the logged-in session; the public API key gets 401 on it and on `invoice/GetCustomerInvoices`).
- A receipt record has `ReceiptId`, `ReceiptNumber`, `EntityId` (the customer), `TripsNumbers`, `InvoicesNumbers`, `TotalAmount`, `TotalShareAmount`, dates and flags; **no receipt URL and no trip id**. The trip id comes from `get_trip_by_number`. A receipt of a mini-site registration starts as "To Match" (no trip, no invoice) until it is matched.
- "Payment completed" = active, not cancelled, `TotalShareAmount` equal to `TotalAmount`, one trip and one invoice (297 of 500 read).
- The receipt PDF is a download action (`downloadAccountingDocument(ReceiptId, 4)`), not a link. Row actions Send, Regenerate and Cancel Receipt exist: never pressed.

## Limits of this survey
- One page of 100 trips (the newest ids); older completed trips were not read.
- Trip numbers did not come back from `GetTrip/v3` in this run (shown as None), so trips are identified by their internal id only.
- `reconcile_trip`'s verdict uses its accepted profit set (3, 13, 15 %): a MISMATCH is a line to check, not an error.
