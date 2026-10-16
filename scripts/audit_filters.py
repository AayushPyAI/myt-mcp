"""Live audit of the sort and filter options of train_prices, viator_search_activities and getyourguide_find_activities against the running
local server: every row must obey the filter and every sort must be in order. Run: .venv/bin/python scripts/audit_filters.py (about 4 minutes;
it reads Roma-Firenze trains, 2 Viator pages and 2 GetYourGuide pages, then answers the filters from the same reads)."""
import asyncio, json, re, subprocess, sys
sys.path.insert(0, ".")
from myt_mcp.viator.parse import duration_minutes as vmin
from myt_mcp.gyg.parse import duration_minutes as gmin
def call(name, args):
    out=subprocess.run([".venv/bin/python","scripts/call_tool.py",name,json.dumps(args)],capture_output=True,text=True,timeout=300).stdout
    try: return json.loads(out)
    except Exception: return {"_error": out[:200]}
R=[]
def check(label, ok, detail=""):
    R.append((label, ok)); print(("✅" if ok else "❌"), label, detail)
def sorted_by(vals, reverse=False): return vals==sorted(vals, reverse=reverse)
def hm(t): h,m=t.split(":"); return int(h)*60+int(m)

print("=== TRENITALIA (Roma Termini -> Firenze S.M.N., 4 Mar 2027, 2 adults + child 8)")
base={"from_station":"Roma Termini","to_station":"Firenze S.M. Novella","travel_date":"2027-03-04","depart_after":"00:00","adults":2,"children":1}
d=call("train_prices",{**base,"max_results":150})
rows=d.get("trains",[]); check("whole day read", d.get("trains_read")==37 and len(rows)==37, f"read={d.get('trains_read')} rows={len(rows)}")
for sort in ("price","departure","duration"):
    d=call("train_prices",{**base,"sort_by":sort,"max_results":150}); r=d["trains"]
    if sort=="price": ok=sorted_by([x["cheapest_price"] for x in r])
    elif sort=="departure": ok=sorted_by([x["departure"] for x in r])
    else: ok=sorted_by([int(re.search(r"(\d+)h",x["duration"]).group(1))*60+int(re.search(r"(\d+)min",x["duration"]).group(1)) for x in r])
    check(f"sort_by {sort}", ok)
d=call("train_prices",{**base,"sort_by":"arrival","max_results":150}); r=d["trains"]
arr=[hm(x["departure"])+int(re.search(r"(\d+)h",x["duration"]).group(1))*60+int(re.search(r"(\d+)min",x["duration"]).group(1)) for x in r]
check("sort_by arrival", sorted_by(arr))
d=call("train_prices",{**base,"max_price":50,"max_results":150}); r=d["trains"]
check("max_price 50 (whole group)", len(r)>0 and all(x["cheapest_price"]<=50 for x in r), f"{len(r)} trains, max {max(x['cheapest_price'] for x in r) if r else None}")
d=call("train_prices",{**base,"direct_only":True,"max_results":150}); r=d["trains"]
check("direct_only", len(r)>0 and all(x["changes"]==0 for x in r), f"{len(r)} trains")
d=call("train_prices",{**base,"depart_after":"15:00","max_results":150}); r=d["trains"]
check("depart_after 15:00", len(r)>0 and all(x["departure"]>="15:00" for x in r), f"{len(r)} trains")
d=call("train_prices",{**base,"train_type":"frecce","max_results":150}); r=d["trains"]
check("train_type frecce", len(r)>0 and all(all("Frecciarossa" in t or "Frecciargento" in t or "Frecciabianca" in t for t in x["trains"]) for x in r), f"{len(r)} trains")
d=call("train_prices",{**base,"train_type":"regional","max_results":150})
check("train_type regional (date beyond timetable) says so, no invented trains", len(d.get("trains",[]))==0 and bool(d.get("note") or d.get("types_note") or d.get("warning")), (d.get("note") or d.get("types_note") or d.get("warning") or "")[:90])
d=call("train_prices",{**base,"max_results":5}); check("max_results 5 reads only 5 trains and says later trains were not read", len(d["trains"])==5 and d["trains_read"]==5 and "later trains" in (d.get("note") or ""))

print("=== VIATOR (Florence pasta cooking class, 2 pages)")
vb={"query":"Florence pasta cooking class","pages":2,"max_results":60}
d=call("viator_search_activities",vb); rows=d.get("activities",[]); cov=d.get("coverage",{})
check("Viator pages read & coverage", cov.get("pages_read")==2 and cov.get("results_read")>=40, str(cov))
d=call("viator_search_activities",{**vb,"max_price":60}); r=d["activities"]
check("max_price 60", len(r)>0 and all(x["from_price"]<=60 for x in r), f"{len(r)} rows")
d=call("viator_search_activities",{**vb,"min_rating":4.8}); r=d["activities"]
check("min_rating 4.8", len(r)>0 and all((x["rating"] or 0)>=4.8 for x in r), f"{len(r)} rows")
d=call("viator_search_activities",{**vb,"max_hours":2}); r=d["activities"]
check("max_hours 2", len(r)>0 and all((vmin(x["duration"]) or 10**9)<=120 for x in r), f"{len(r)} rows")
d=call("viator_search_activities",{**vb,"free_cancellation_only":True}); r=d["activities"]
check("free_cancellation_only", len(r)>0 and all(x["free_cancellation"] for x in r), f"{len(r)} rows")
d=call("viator_search_activities",{**vb,"title_contains":["pasta"]}); r=d["activities"]
check("title_contains pasta", len(r)>0 and all("pasta" in x["title"].lower() for x in r), f"{len(r)} rows")
for sort in ("price","rating","reviews","duration"):
    d=call("viator_search_activities",{**vb,"sort_by":sort}); r=d["activities"]
    if sort=="price": ok=sorted_by([x["from_price"] for x in r if x["from_price"] is not None])
    elif sort=="rating": ok=sorted_by([(x["few_reviews"], -(x["rating"] or 0)) for x in r])
    elif sort=="reviews": ok=sorted_by([-(x["reviews"] or 0) for x in r])
    else: ok=sorted_by([vmin(x["duration"]) or 10**9 for x in r])
    check(f"Viator sort_by {sort}", ok)
d=call("viator_search_activities",{**vb,"sort_by":"rating"}); r=d["activities"]
check("Viator few_reviews rows come last", sorted_by([x["few_reviews"] for x in r]) and all(x["rank"]==i+1 for i,x in enumerate(r)))
check("Viator shortlist present with 20+ reviews", 1<=len(d.get("shortlist_for_exact_price",[]))<=3 and all(p["reviews"]>=20 for p in d["shortlist_for_exact_price"]))

print("=== GETYOURGUIDE (Florence pasta cooking class, 3 Mar 2027, 2 pages)")
gb={"query":"Florence pasta cooking class","activity_date":"2027-03-03","pages":2,"max_results":60}
d=call("getyourguide_find_activities",gb); cov=d.get("coverage",{})
check("GYG pages read & coverage", cov.get("pages_read")==2 and cov.get("results_read")>=40 and cov.get("total_on_getyourguide",0)>100, str(cov))
d=call("getyourguide_find_activities",{**gb,"max_price":60}); r=d["activities"]
check("max_price 60", len(r)>0 and all(x["from_price"]<=60 for x in r), f"{len(r)} rows")
d=call("getyourguide_find_activities",{**gb,"min_price":100}); r=d["activities"]
check("min_price 100", len(r)>0 and all(x["from_price"]>=100 for x in r), f"{len(r)} rows")
d=call("getyourguide_find_activities",{**gb,"min_rating":4.8}); r=d["activities"]
check("min_rating 4.8", len(r)>0 and all((x["rating"] or 0)>=4.8 for x in r), f"{len(r)} rows")
d=call("getyourguide_find_activities",{**gb,"max_hours":2.5}); r=d["activities"]
check("max_hours 2.5", len(r)>0 and all((gmin(x["duration"]) or 10**9)<=150 for x in r), f"{len(r)} rows")
d=call("getyourguide_find_activities",{**gb,"free_cancellation_only":True}); r=d["activities"]
check("free_cancellation_only", len(r)>0 and all(x["free_cancellation"] for x in r), f"{len(r)} rows")
d=call("getyourguide_find_activities",{**gb,"title_contains":["tiramisu"]}); r=d["activities"]
check("title_contains tiramisu", len(r)>0 and all("tiramisu" in x["title"].lower() or "tiramisù" in x["title"].lower() for x in r), f"{len(r)} rows")
for sort in ("price","rating","reviews","duration"):
    d=call("getyourguide_find_activities",{**gb,"sort_by":sort}); r=d["activities"]
    if sort=="price": ok=sorted_by([(x["price_basis"]=="per group", x["from_price"]) for x in r])
    elif sort=="rating": ok=sorted_by([(x["few_reviews"], -(x["rating"] or 0)) for x in r])
    elif sort=="reviews": ok=sorted_by([-(x["reviews"] or 0) for x in r])
    else: ok=sorted_by([gmin(x["duration"]) or 10**9 for x in r])
    check(f"GYG sort_by {sort}", ok)
d=call("getyourguide_find_activities",gb); check("GYG all prices EUR", all(x["currency"]=="EUR" for x in d["activities"]))
print("\nSUMMARY:", sum(1 for _,ok in R if ok), "ok /", len(R), "checks;", "FAILED:", [l for l,ok in R if not ok])
