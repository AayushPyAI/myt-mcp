"""MYT write-API test on the test trip 168 only. Nothing is sent unless you pass --yes; without it the script prints exactly what it would send.

    .venv/bin/python scripts/api_write_test.py create            # show the Create call (reservations/Create)
    .venv/bin/python scripts/api_write_test.py create --yes      # send it: one test product, EUR 1.00, clearly labelled
    .venv/bin/python scripts/api_write_test.py update --yes      # change that test reservation (price 1.00 -> 2.00, a note); needs `create` first
    .venv/bin/python scripts/api_write_test.py status --yes      # trip/ChangeTripStatus with the trip's CURRENT status (a no-op), to learn the parameter name

The API key comes from .env and is never printed. Trip 168 (MYT id 189423) is hard-coded: any other trip is refused.
There is no delete endpoint: remove the test reservation on the MYT screen afterwards (Supplier Reservations > row menu > Delete).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

TRIP_ID = 189423                   # trip 168, the test trip
BASE = "https://www.manageyourtrip.com/api"
EXTERNAL_ID = "claude-api-test-2026-10-17"
SUPPLIER_ID = 101768               # "Lisbon Airport Transfers", the placeholder supplier already used in trip 168's quote
EUR = 3                            # CurrencyCodeId of EUR (GET /api/Currency/Get: ILS 1, USD 2, EUR 3)


def client() -> tuple[httpx.Client, str]:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    key = os.environ["MYT_API_KEY"]
    return httpx.Client(base_url=BASE, headers={"x-api-key": key, "Accept": "application/json"}, timeout=60), key


def read_trip(http: httpx.Client, key: str) -> dict:
    return http.get("/trip/GetTrip/v3", params={"key": key, "tripId": TRIP_ID}).json()


def show(label: str, response: httpx.Response) -> None:
    print(f"{label}: HTTP {response.status_code} {response.headers.get('content-type', '')}")
    print(response.text[:1200] or "(empty body)")


def create_body() -> dict:
    return {"tripId": TRIP_ID, "externalId": EXTERNAL_ID, "comments": "API TEST by Claude 17 Oct 2026 - safe to delete",
            "products": [{"SupplierId": SUPPLIER_ID, "StartDate": "2027-03-01", "Name": "API TEST - delete me (Claude, 17 Oct 2026)", "PricingTypeId": 1, "TypeId": 1,
                          "Price": 1.0, "CurrencyCodeId": EUR, "Quantity": 1, "Nights": 1, "ArrivalTime": "10:00", "Comments": "API test, delete me"}]}


def find_test_reservation(trip: dict) -> tuple[int, int, float] | None:
    for r in trip.get("reservations") or []:
        if "API TEST" in (r.get("product_name") or ""):
            return r["order_id"], r["reservation_id"], float((r.get("price") or {}).get("amount") or 0)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=["create", "update", "status"])
    parser.add_argument("--yes", action="store_true", help="really send the call (otherwise only show it)")
    args = parser.parse_args()
    http, key = client()
    trip = read_trip(http, key)
    if (trip.get("trip") or {}).get("trip_id") != TRIP_ID:
        print("Refusing: the trip returned is not trip 168.")
        return 1
    status = (trip["trip"].get("status") or {})
    print(f"Trip 168 now: status {status.get('name')!r} (id {status.get('id')}), {len(trip.get('reservations') or [])} reservations.")

    if args.what == "create":
        if find_test_reservation(trip):
            print("A test reservation already exists on trip 168: not creating a second one.")
            return 1
        body = create_body()
        print("POST /api/reservations/Create\n" + json.dumps(body, indent=2))
        if args.yes:
            show("Create", http.post("/reservations/Create", json=body))
            after = read_trip(http, key)
            print("Read back:", find_test_reservation(after) or "the test reservation is NOT visible in GetTrip/v3")
    elif args.what == "update":
        found = find_test_reservation(trip)
        if not found:
            print("No test reservation on trip 168: run `create --yes` first.")
            return 1
        order_id, reservation_id, price = found
        body = {"OrderDocId": order_id, "OrderReservations": [{"OrderReservationId": reservation_id, "ReservationDate": "2027-03-01", "Quantity": 1, "Duration": 1,
                                                          "Price": 2.0, "ArrivalTime": "10:00", "Comments": "API test updated by Claude", "IsActive": True}]}
        print(f"Test reservation: order {order_id}, reservation {reservation_id}, price now {price}")
        print("POST /api/reservations/Update\n" + json.dumps({"orderDoc": body}, indent=2))
        if args.yes:
            show("Update", http.post("/reservations/Update", json={"orderDoc": body}))
            print("Read back price:", (find_test_reservation(read_trip(http, key)) or (0, 0, None))[2])
    else:
        body = {"tripId": TRIP_ID, "statusId": status.get("id")}
        print("POST /api/trip/ChangeTripStatus (the CURRENT status, so nothing should change)\n" + json.dumps(body, indent=2))
        if args.yes:
            show("ChangeTripStatus", http.post("/trip/ChangeTripStatus", params={"key": key}, json=body))
            after = read_trip(http, key)["trip"].get("status") or {}
            print("Status after:", after.get("name"), after.get("id"))
    if not args.yes:
        print("\nNothing was sent. Add --yes to send it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
