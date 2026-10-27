"""Regression check for test trip 168 (quotation 82 V2): re-price the lines our tools can read and compare with the net prices in the quote.
Read only. Run: .venv/bin/python scripts/regress_trip168.py   (needs the automation Chrome for TAP, SATA and GetYourGuide)
Result of the first run (17 Oct 2026): docs/Regression_Trip168_2026-10-17.md
"""
import asyncio, json, sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from mcp import Client
from dotenv import load_dotenv
from myt_mcp.app import create_server
from myt_mcp.config import Settings
load_dotenv(__import__("pathlib").Path(__file__).resolve().parent.parent / ".env")
def pl(r): return {"ERROR": r.content[0].text[:200]} if r.is_error else (r.structured_content or json.loads(r.content[0].text))
def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values(): yield from walk(v)
    elif isinstance(x, list):
        for v in x: yield from walk(v)
async def main():
    async with Client(create_server(Settings.from_env())) as c:
        out = {}
        async def call(name, tool, args):
            d = pl(await c.call_tool(tool, args)); out[name] = d; return d
        # 3 train (net 125.00): Roma Termini -> Firenze SMN 4 Mar 09:08, 2 adults + child 8
        d = await call("3 train", "train_prices", {"from_station": "Roma Termini", "to_station": "Firenze S. M. Novella", "travel_date": "2027-03-04", "depart_after": "09:08", "adults": 2, "children": 1, "max_results": 1})
        t = (d.get("trains") or [{}])[0]; print("3 TRAIN", t.get("departure"), t.get("trains"), "cheapest", t.get("cheapest_price"), [(f["class"], f["fare"], f["price"]) for f in t.get("fares", []) if f["class"] == "STANDARD"], d.get("ERROR"))
        # 4 TAP (net 530.38)
        d = await call("4 tap", "tap_flight_prices", {"from_airport": "FLR", "to_airport": "LIS", "departure_date": "2027-03-06", "adults": 2, "child_ages": [8], "max_results": 8})
        for f in d.get("flights", []):
            segs = json.dumps(f.get("segments"))
            if "875" in segs:
                print("4 TAP TP875:", [(x.get("fare_code"), x.get("price_total") or x.get("total")) for x in f.get("fares", [])][:6])
        if d.get("ERROR"): print("4 TAP", d["ERROR"])
        # 6 SATA (net 250.04)
        d = await call("6 sata", "sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": "2027-03-08", "adults": 2, "children": 1, "max_results": 10})
        for o in d.get("options", []):
            leg = (o.get("legs") or [{}])[0]
            if any("125" in fl for fl in leg.get("flights", [])): print("6 SATA", leg.get("flights"), leg.get("departs"), o.get("total_price"), leg.get("fare"))
        if d.get("ERROR"): print("6 SATA", d["ERROR"])
        # 13 / 14 activities
        d = await call("13 vatican", "getyourguide_activity_details", {"url": "https://www.getyourguide.com/rome-l33/rome-vatican-museums-sistine-chapel-basilica-tour-t429439/", "activity_date": "2027-03-03", "adults": 2, "child_ages": [8]})
        for o in d.get("options", []):
            for s in o.get("start_times", []):
                if s.get("time") == "10:00 AM": print("13 VATICAN", o["option"][:50], s["time"], s.get("total_price"), "(quote net 227.00)")
        if d.get("ERROR"): print("13", d["ERROR"])
        d = await call("14 find golf", "getyourguide_find_activities", {"query": "Golf Cart Tour Florence", "activity_date": "2027-03-05", "title_contains": ["golf"], "read_all_relevant": True, "max_results": 5})
        acts = d.get("activities", [])
        print("14 GOLF found:", [(a["title"][:50], a["from_price"], a["url"].split("/")[-2][-12:]) for a in acts[:4]], d.get("coverage"), d.get("ERROR"))
        json.dump({k: v for k, v in out.items()}, open("/tmp/myt-mcp/regress168.json", "w"), default=str)
asyncio.run(main())
