# Test run log and open issues, 28 Oct 2026

How we test: one kind per chat (flights, transfers, trains, activities, hotels, cars), in **manual mode** (the operator allows each script), read-only, nothing booked. The VPS log is watched while the chat runs. Code is `84bcc89` on the VPS unless a line says otherwise.

Where an issue comes from: **code** (ours), **env** (claude.ai / Chrome / the sites), **chat** (what the model does).

## Runs

| # | Kind | Mode | Result |
|---|---|---|---|
| 1 | Flights | auto | only Booking + SATA read (4 Chrome scripts refused by the auto-mode classifier "[Browser JS Exfil]") |
| 1 | Flights | manual | RateHawk Air + Skyscanner + Booking read; refund caution works; Best fit "not determined" (correct) |
| 2 | Transfers | auto | Kiwitaxi only (RateHawk and iWay refused by the classifier) |
| 2 | Transfers | manual | RateHawk Transfers read (23 rows, stand-in drop-off); iWay NOT read (page stayed grey, no iWay tab in the chat's tab group) |
| 3 | Trains | manual/auto | CP no trains on sale; server wrote the "nothing found" answer itself |
| 4-5 | Activities | manual | Viator list (24 of 200) + 3 exact prices read, each row has its own link, 24-hour times, cells cut at a word; Booking 30 of 35 rows shown; GYG Cloudflare check again (env); check ok; open: I-25, I-26, I-3 (rating) |
| 6 | Hotels | manual | all 3 sources read (RateHawk parts needed 1 checksum retry); Bensaude ROOM-ONLY gone from the table; one RateHawk note; check ok on the full text; open: I-20, I-21 |
| 7 | Cars | manual | Ofran 21, Europcar 30 (server), Rentalcars 500 of 530 read; RateHawk cars "Something went wrong" twice (env); low-price note and Europcar zero-excess note appeared; Best fit Ofran Qashqai 165.72; open: I-3 (large bags), I-2, I-23, I-24 |

## Open issues

| ID | Kind | Issue | Source | Next step |
|---|---|---|---|---|
| I-1 | flights | rows whose refund terms are "not shown" are dropped from the table (counted in "do not meet every wish") and only the cheapest is named in a note | code | show them in the table marked "not confirmed", never as a pick |
| I-2 | all | "Filters used" repeats the same filter in other words ("Checked bag included" / "Checked baggage", "tabs" / "sorts"); in cars the recipes' source notes ("... NOT checkable on Ofran") and 3 variants of zero excess and of the currency line were all listed | code | better dedupe key |
| I-3 | transfers, cars, hotels | a wish no row can confirm still lets the row be "Best fit, meets every wish": flight tracking (Kiwitaxi), 2 large bags (Ofran shows only 'x/y' bags), 2 km (Bensaude shows no distance), the rating on Viator's exact-price rows (not shown, still "meets every wish") | code | treat an unconfirmed wish like refund/bag: not a pick + note |
| I-4 | transfers | rows typed by the chat use other keys (`free cancellation`, `max bags`, `max passengers`): false "not shown" gaps next to RateHawk's `capacity` / `cancellation` | code | key aliases in Offer details |
| I-5 | transfers | "comfortable vehicle" asked but the recipe call had no `vehicle`; Micro 14 EUR became Best fit | chat + code | note when a filter line names a wish no recipe carried |
| I-6 | transfers | iWay page stays grey in a tab the chat opened; the operator's own iWay tab was not in the chat's tab group | env | operator adds the loaded iWay tab to the chat's tab group before the run |
| I-7 | all | auto mode refuses scripts that POST page data to the server ("[Browser JS Exfil]"); manual mode runs them | env | run in manual mode; move public sources server-side; parts mode for logged-in sources later |
| I-8 | flights | Skyscanner and TAP read fine from the VPS Chrome (probe 28 Oct) but are still Chrome-only | code | make them server-first (flags default on, Chrome fallback) |
| I-9 | all | the "reason must be one of ..." refusal does not echo the reason the chat wrote | code | add the rejected text to the message |
| I-10 | all | filter lines written by the chat without a source word are refused and cost a retry | chat | already accepted: operator / trip / default / server / agency / assistant |
| I-11 | activities | GetYourGuide shows a Cloudflare "Verify you are human" check; `GYG_FIND_READ_IN_SERVER=0` on the VPS (left as is on purpose) | env | none |
| I-12 | all | the chat checks a shortened draft and shows the full text | chat | warning added (84bcc89); keep watching |
| I-13 | activities | Viator's list can contain a non-activity (airport private transfer) | code | low |
| I-14 | trains | CP stations chosen by the chat but labelled "(operator)" | chat | low |
| I-15 | transfers | RateHawk has no "Praça do Comércio" place: the stand-in "Pousada de Lisboa, Praça do Comércio" is labelled "(default)" | chat | low |
| I-16 | all | a changed tool description needs the connector removed and added again in claude.ai | env | remember after each deploy that changes a description |
| I-17 | all | too many Chrome sources in one chat make the extension time out | env | one kind per chat |
| I-18 | hotels | RateHawk hotels parts fail their checksum about half of the time on the first try | env + code | retry works; server-first needs a RateHawk login in the VPS Chrome |
| I-20 | hotels | a 2 km limit was asked; Bensaude shows no distance and its rows still count as meeting every wish (the chat said Hotel Açores is 3.3 km away on RateHawk) | code | Bensaude rows: distance wish unconfirmed (like stars), never a pick |
| I-21 | hotels | RateHawk hotels address has no residency / citizenship (cars has `residency=il`); prices can depend on it | code | find the parameter RateHawk's hotel page writes and set it from the trip (default Israel); ask the chat what the page writes |
| I-23 | cars, all | "Most flexible: not determined: no refundable or free-cancellation option was read" is wrong when comparison-only rows do show free cancellation (Rentalcars) | code | say "only comparison rows (not quotable) show free cancellation" |
| I-24 | cars | Best fit is an Ofran car at a pick-up station OUTSIDE the airport terminal; only a table cell says so | code | caution line when a pick is not at the terminal |
| I-25 | activities | max price per person (50) and max duration (4 h) are applied to the lists they were given to but not to the exact-price rows or to Booking: tuk tuk tours at 80-130 EUR per person and day trips over 4 hours stay in the tables as meeting the wishes | code | compose-level `wishes` fill the gaps of every item; every row is judged on price per person and hours when it shows them |
| I-26 | activities | "Not shown by the sources: includes (in 13 rows), pay, ticket, option state" counts the Viator list rows for columns only the exact-price rows have | code | do not count a column against rows of a type that never has it |
| I-19 | all | own domain for the connector (option B) not decided | decision | needs DNS for selectedplaces.co.il |

## Fixed and deployed today

Bensaude ROOM-ONLY no longer meets a breakfast wish; "from tab" not in "Not shown"; Kiwitaxi duplicate columns; wishes written as filter lines and the recipes' lines joined; refundable / checked-bag wishes given to compose_answer are checked; Best fit with refund or bag terms "not shown" gets a caution; one leg written two ways is one table; source warnings only for the draft's own kind; activities lists cut at 30 rows; iWay own-tab rule and blank-page fallback; Viator "X tours" search (no destination-page redirect); nothing-found answer (also with a 0-row source); each Viator / GYG / Booking activity row has its own link; 24-hour times; long cells cut at a word; "place not found" is an allowed reason; RateHawk part notes merged; Rentalcars low-total note.

## Batch done locally after the manual-mode runs (not yet committed, pushed or deployed)

One mechanism instead of patches: a wish that no row can confirm is **not confirmed**: the row stays in the table marked "(not confirmed: ...)" and is never a pick; a clear miss still drops the row.

- I-1, I-3: `Offer.unconfirmed`; refund terms, checked bag, flight tracking (transfers), large bags (Ofran, Europcar), distance (Bensaude), rating / duration / price per person (activities, `myt_mcp/wishes.py`: the wishes of all runs are put together and judged on every row, the rating of an exact-price row comes from the list row of the same page).
- I-2: the filter dedupe key ignores source notes and small words (cars' repeated lines).
- I-4: typed rows' keys (`free cancellation`, `max bags`, `max passengers`) become the columns the other sources use.
- I-8: Skyscanner and TAP are server-first (`SKYSCANNER_READ_IN_SERVER`, `TAP_READ_IN_SERVER`, default on, Chrome fallback).
- I-21: RateHawk hotels address carries `residency=en-il` and the answer says "citizenship used: Israel (assumed)" (to be seen on the live page in the next hotels run).
- I-23: "Most flexible" says when only comparison rows show free cancellation.
- I-24: a pick that is not at the airport terminal gets a caution.
- I-26: a column a kind of row never has is not counted as "not shown".

Not touched on purpose: I-6 iWay tab group, I-7 auto mode, I-11 GetYourGuide Cloudflare and `GYG_FIND_READ_IN_SERVER=0`, I-17, RateHawk cars "Something went wrong".
