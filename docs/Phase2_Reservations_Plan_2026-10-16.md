# Phase 2 plan: supplier reservations, vouchers, payments, status changes, reconciliation (16 Oct 2026)

Source of the asks: the 75-minute call with Nimrod on 15 Oct 2026 (`Meeting_2026-10-15_transcript_raw.txt`, times in brackets) and his written requirement of 16 Oct (`Client_Requirements_2026-10-16.md`). Written confirmation of this scope and of its hours is still pending.

## 1. What the client asked (recall, in his words and times)
1. **Connect first, then act (21:12-22:24).** "First of all, please connect it to the data in the supplier reservation... and also the itinerary... and the quote. After that, the next phase, we will give Claude to do some tasks inside those places... cost, price, quote lines."
2. **Voucher statuses (16:24-17:01).** "In the supplier reservation we see all the statuses of the vouchers from a trip. We need to know what are the prices and what are the statuses of vouchers... if there are some statuses that are not updated for a long time."
3. **Today's flow, and why it hurts (17:20-21:06).** The operator pays suppliers on several platforms, then goes to MYT: the reservation is created, its status changes (Ready To Send, Voucher Issued...), she uploads every voucher and every payment, and at the end sets it to paid after check-in. "It takes a lot of time and it's not on time... one by one... after, we don't know if we paid or not paid on time." Goal: "reduce this time for updating".
4. **Reconciliation, phase A (42:21-43:09).** "Make sure about all vouchers and payment invoices from suppliers for each reservation, like lodging, transfers, car, all reservations the operation made."
5. **Reconciliation, phase B, later (43:09-44:01).** "After we upload all vouchers and payments, a reconciliation of all reservations separately: check all details, which room they reserved, exactly like in the MYT booking reservation... verify all the data from voucher and payments to be sure that it's the same data that we put from operation."
6. **Commission (11:50-12:55).** "I want to change the commission": Ayush said the commission update part was still being built and might fail.
7. **Main goal (57:36-58:16).** Request arrives, Claude creates the trip, Meylinda adds details, Claude prices it, quote on the mini-site; "in addition to that he needs to check the accounting section and the supply reservation section".
8. **Daily exchange rate (1:06-1:15).** Every day take the ILS/EUR rate from the Israeli bank's foreign-currency table (it shows the previous day, e.g. 3.53 then 3.54) and put it in MYT Accounting settings; Meylinda cannot edit the field at the moment. "Every day."
9. **Receipts in the currency the customer paid (0:00-1:29).** If the customer transferred EUR, issue the receipt in EUR (MYT asks in ILS): to be clarified, not part of Claude's work yet.
10. Not wanted: a Lovable app (58:58-1:03), the mini-site is not connected yet (13:46).

## 2. What exists today (tools, tested)
- `get_supplier_reservations(trip_id)`: every reservation with order id, supplier, product, dates, quantity, unit and total cost, status, `voucher_flags` (status Ready To Send while the service is near or already started). Trip 906 on 16 Oct: 7 reservations (1 Voucher Issued, 1 Reservation Confirmed, 5 Ready To Send), 5 flags.
- `reconcile_trip(trip_id)`: each reservation against its quote line: 5 ok, 2 mismatch (Ofran 600 vs quote 83.38, Trenitalia 60 vs 113).
- `check_reservation_paperwork(trip_id, vouchers, supplier_invoices, supplier_payments)`: matches rows read from the screens; answers found / missing / amount difference / double payment.
- Playbook section "Supplier reservations, vouchers and reconciliation" (read only; status changes only with an approved exact change).

## 3. The MYT screens (read on trip 906 on 16 Oct, nothing changed)
- Supplier Reservations (`#/supplierReservations?tripId=<id>`): rows grouped by category (Transport, Food, Lodging, DMC). Per row: warning or tick icon, order id and voucher number ("R2342258 - T906 - N/V": N/V = no voucher), supplier, date, amount, supplier email, status; a counter bar with the number of reservations per status colour; checkboxes; a row menu; an arrow that opens the details.
- Row menu (three dots): Check Availability, **Send Request** and **Edit & Send Request** (these email the supplier), **Skip To COR** (to Reservation Confirmed), **Skip To COR & Download**, **Skip To Voucher & Download** (to Voucher Issued), Duplicate, **Reservation History**, Additional Information, Delete.
- **Reservation History** lists every action with date and time, the user and the action ("Reservation created, 13 Oct 2026 5:01 PM"). This is where "status not updated for a long time" can be measured: the API has no status date.
- Row details (arrow): tabs **PRODUCTS**, **PAYMENTS** (supplier payments of this reservation, count in the tab title), **FILES** (Google Drive attachments: vouchers and invoices), **OTHER DETAILS** (supplier email, comments added to the voucher, external id). All trip-scoped.
- Tab SUPPLIER INVOICES is **account-wide** (default: all customers, date window, invoice responsible) and shows only invoices "Waiting for Payment Request": do not use it without a filter that limits it to the trip (it was empty on 16 Oct).
- CLIENT RESERVATIONS holds customer invoicing (pro-forma, invoice, receipt, credit, charge): never pressed.

## 4. Gaps against the asks
| Ask | Status | Gap |
|---|---|---|
| Read reservations, itinerary, quote | done | none |
| Status and price of every voucher, flag old statuses | partly | the flag uses the service date; the real "days in status" needs Reservation History per row (screen read) and the client's number of days |
| Reconcile voucher + payment invoice per reservation | partly | the tool exists; the rows must be read from each reservation's PAYMENTS and FILES tabs (and Trip Balance); not yet run on a trip that has payments and files |
| Check each reservation's detail against the voucher (room, dates, names) | not built | needs the content of the uploaded voucher files (Drive) vs the reservation |
| Change statuses (Skip To COR, Skip To Voucher), mark paid | not built | needs one tested, approved change on trip 906 and the client's rules (which statuses Claude may set, who approves) |
| Commission change | not built here | Staff lines through the quote screen (playbook rules exist) |
| Daily ILS/EUR rate | not built | bank page, MYT field, time of day and a stop switch to be confirmed in writing |
| Customer payments, supplier payments, balance report | not built as a report | read from Trip Balance; client's written scope and hours |

## 5. Proposed order of work
1. **Read-only first (no risk):** a "reservations report" for one trip: table with status, days in status (from Reservation History), voucher number, payments (from the PAYMENTS tab), files present (FILES tab), flags. Test on trip 906 and 168; it needs no write.
2. **Reconciliation phase A:** the same report plus `check_reservation_paperwork`; list reservations missing voucher, invoice or payment, and payments older than X days (client's number).
3. **One status change, with approval, on trip 906 only:** the operator picks one reservation and the exact change (for example R2342227 Ready To Send to Reservation Confirmed with "Skip To COR"); Claude does it, reads Reservation History and the status back, and reports. Never Send Request, never Delete, never Duplicate.
4. **Rules to confirm in writing before more changes:** which status moves Claude may do on its own list, whether each needs a "yes", what "paid" means and who marks it.
5. **Phase B (voucher content vs reservation):** after the client confirms scope and hours.
6. **Exchange rate task:** after written approval, source, time and stop switch.

## 6. Questions for the client (add to `Client_Questions_2026-10-15.md`)
- How many days without a status change count as "not updated for a long time", per status?
- Which status moves may Claude do by itself on its list, which need a "yes", and which never (Send Request, Delete)?
- Does "Skip To COR" or "Skip To Voucher & Download" email the supplier or the customer? (We assume not; to be confirmed before the first test.)
- Where are supplier invoices and payment proofs kept: uploaded in the PAYMENTS and FILES tabs of the reservation, or elsewhere?
- What must match in phase B (room, dates, names, amount; EUR against ILS tolerance)?
- Which bank page and which MYT field for the daily rate, and what time of day?
