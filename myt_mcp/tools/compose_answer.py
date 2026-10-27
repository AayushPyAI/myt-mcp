"""compose_answer: the final answer is built by the server from the rows Claude collected (see myt_mcp/compose.py)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.composed import COMPOSED
from myt_mcp.ingest import STORE
from myt_mcp.compose import MAX_ROWS_BY_KIND, NotChecked, Offer, SourceRead, apply_wishes, bag_unconfirmed, compose, refund_unconfirmed
from myt_mcp.sites import carried_wishes, convert_all, register_all, resolve_site_names
from myt_mcp.errors import tool_errors

log = logging.getLogger("myt_mcp")

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"]

# Sites read only through a recipe script in the operator's Chrome (their own tools are off): a row from them can come from a script answer (runs / site_results), never from typed `offers`.
# Found 24 Oct 2026: RateHawk hotel and tour prices were read off the pages by hand, passed as `offers`, and the answer went out with prices the server never received.
CHROME_ONLY = ("ratehawk", "arbitrip", "skyscanner", "el al", "comboios", "cp (", "getyourguide", "viator", "bensaude (", "europcar (", "rentalcars")


def typed_chrome_rows(offers: list[Offer]) -> list[str]:
    return sorted({o.source for o in offers if any(w in o.source.lower() for w in CHROME_ONLY)})


def _is_parts(item: dict[str, Any]) -> bool:
    try:
        data = json.loads(item.get("result", ""))
    except (TypeError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get("parts")) and bool(data.get("run")) and not item.get("wishes")


def merge_default_group(offers: list[Offer], items: list[dict[str, Any]]) -> None:
    """A site recipe that has no leg of its own labels its rows with the module's generic group ('Transfers'): when the answer has exactly ONE named group, those rows belong to it
    (23 Oct 2026: RateHawk transfers came as a second table with its own Picks next to Mozio's and Kiwitaxi's, and the two Picks tables disagreed)."""
    from myt_mcp.sites import modules
    generic = {getattr(m, "GROUP", None) for m in modules().values()} | {"Options"}
    named = {o.group for o in offers if o.group not in generic}
    if len(named) == 1:
        target = next(iter(named))
        for o in offers:
            if o.group in generic:
                o.group = target


WINDOW_SECONDS = 45 * 60          # a recipe call counts for this long (RateHawk hotels in parts mode take about 10 minutes)
DRILL_DOWNS = ("_rooms", "_activity")     # the page of one room or one tour: asking for it and not using it is not a missing source


def issued_sites(kind: str) -> set[str]:
    """The recipe keys of this kind of answer that a recipe call issued in the last 45 minutes (drill-downs too): they tell which site a display name means."""
    from myt_mcp.sites import modules
    mods = modules()
    return {run.site for run in STORE.issued(time.time() - WINDOW_SECONDS) if str(getattr(mods.get(run.site), "GROUP", "")).lower() == kind}


def unused_recipes(kind: str, used: set[str], not_checked: list[NotChecked]) -> list[str]:
    """Recipe calls of this kind, issued since the last successful compose_answer of the kind, whose site has no result in this answer and is not in not_checked.
    26 Oct 2026: the GetYourGuide list was run in Chrome, its rows were refused once for a wrong site name, and the answer went out without them and without a word."""
    from myt_mcp.sites import modules
    mods = modules()
    skipped = " ".join(n.name.lower() for n in not_checked)
    since = max(time.time() - WINDOW_SECONDS, COMPOSED.last_time(kind))
    found: dict[str, float] = {}
    for run in STORE.issued(since):
        mod = mods.get(run.site)
        if mod is None or run.site in used or run.site.endswith(DRILL_DOWNS) or str(getattr(mod, "GROUP", "")).lower() != kind:
            continue
        if str(getattr(mod, "SOURCE", run.site)).lower().split(" (")[0] in skipped:
            continue
        found.setdefault(run.site, run.created)
    return [f"{site} (the recipe was issued at {time.strftime('%H:%M', time.localtime(at))})" for site, at in found.items()]


def split_problems(carried: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    """Flight sources searched with different travellers (3 adults + 1 child on one, 2 adults + 2 children on another) give prices that cannot be compared, and a
    cheaper row of the odd one then becomes the 'Cheapest' pick (26 Oct 2026: Skyscanner counted the 12-year-old as a child, the airlines as an adult)."""
    by_day: dict[str, dict[tuple[int, int, int], list[str]]] = {}
    for (site, _run), c in carried.items():
        exp = ((c.get("wishes") or {}).get("expect")) or {}
        if exp.get("adults") is None or not exp.get("day"):
            continue
        split = (int(exp["adults"]) + int(exp.get("seniors") or 0), int(exp.get("children") or 0), int(exp.get("infants") or 0))
        by_day.setdefault(str(exp["day"]), {}).setdefault(split, []).append(site)
    out = []
    for day, splits in by_day.items():
        if len(splits) > 1:
            shown = "; ".join(f"{', '.join(sorted(set(sites)))}: {a} adult(s) + {c} child(ren)" + (f" + {i} infant(s)" if i else "") for (a, c, i), sites in splits.items())
            out.append(f"{day}: the sources were searched with different travellers ({shown}), so their prices cannot be compared. Run the odd one again with the same split as the others "
                       "(the operator's age rule decides who counts as a child; ask if it is not known).")
    return out


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def compose_answer(kind: Kind, site_results: list[dict[str, str]] | None = None, wishes: dict[str, Any] | None = None, filters_used: list[str] | None = None,
                             sources_read: list[SourceRead] | None = None, not_checked: list[NotChecked] | None = None, offers: list[Offer] | None = None,
                             myt_supplier: dict[str, str] | None = None, pickup_time: str | None = None, sorted_by_price: bool = True, notes: str = "",
                             ratehawk_results: list[str] | None = None, ratehawk_urls: list[str] | None = None, hotel_wishes: dict[str, Any] | None = None, runs: list[str] | None = None) -> dict[str, Any]:
        """BUILD THE FINAL ANSWER with this tool for every price or comparison request and show its `answer` text as it is; never write the table or the
        picks yourself. SHORTEST CALL for a Chrome site with a recipe: compose_answer(kind, runs=[the `ingest` id of every recipe you ran: each script posts its answer to the
        server by itself and its receipt holds the id; NEVER type, decode or pass the rows yourself], not_checked=[a source you could not read, with an allowed reason]);
        `site_results` (script answer parts passed unchanged) is the old way, only for a recipe whose answer has no `ingest`; the server fills the rest and tells you in `problems` what is missing.
        Longer form: pass the rows you
        read (from the tools) as `offers`, the sources with how many you read (`read` of `of`) and their exact links, the sources you did not read
        with an allowed reason, the filters with their source (operator / trip / default), and the MYT supplier check per pick (`myt_supplier`,
        e.g. {"TAP AIR PORTUGAL": "yes"}). For a Chrome site that has a recipe tool (ratehawk_hotels_recipe, ...) pass the script's answer UNCHANGED in
        `site_results`: [{"site": "<recipe site name>", "result": "<script answer text>", "url": "<page url>"}]; the server turns it into rows itself.
        `wishes` = the operator's wishes ({"breakfast": true, "free_cancellation": true, "stars_min": 4}). The server fills missing fields with "not
        shown", picks Cheapest, Best fit, Most flexible and Recommended by fixed rules (10% rule, one currency, quotable rows only), and writes the
        required lines and links. If something is missing it returns `problems`: fix them and call again. It reads no site and changes nothing."""
        offers = list(offers or [])
        typed = typed_chrome_rows(offers)
        if typed:
            log.info("CHECK compose_answer typed rows refused: %s", ", ".join(typed))
            return {"ok": False, "problems": [f"{', '.join(typed)}: rows from this site cannot be typed or passed as `offers`; only the recipe script's own answer is accepted (`runs` with its `ingest` id, or the parts of a long answer). "
                                              "Run the site's recipe again (RateHawk hotels: in parts mode, about 7 minutes), or, if the script really cannot read the page, put the site in not_checked with the reason 'could not be read: <the script's own error>'. Never read a price off a page by hand."],
                    "next": "Do not write these prices into the answer either: say the site was not read."}
        sources_read = list(sources_read or [])
        not_checked = list(not_checked or [])
        wishes = wishes or hotel_wishes
        if not filters_used and wishes:       # the operator's own wishes are the filters: no need to type them again
            filters_used = [f"{label} (operator)" for key, label in (("breakfast", "Breakfast included"), ("free_cancellation", "Free cancellation")) if wishes.get(key)]
            filters_used += [f"{wishes['stars_min']}+ stars (operator)"] if wishes.get("stars_min") else []
        filters_used = list(filters_used or [])
        items = list(site_results or [])
        ingested, ingest_problems = STORE.items(runs or [])
        if ingest_problems:
            log.info("CHECK compose_answer runs refused: %s", "; ".join(ingest_problems)[:600])
            return {"ok": False, "problems": ingest_problems, "next": "Fix this (run the script again in the same Chrome tab) and call compose_answer again. Do not type any row yourself."}
        items += ingested
        from myt_mcp.sites import modules
        items, renamed = resolve_site_names(items, modules(), issued_sites(kind))
        if renamed:
            log.info("CHECK compose_answer site names read as keys: %s", renamed)
        for raw, url in zip(ratehawk_results or [], list(ratehawk_urls or []) + [""] * len(ratehawk_results or [])):     # the first version's parameters
            items.append({"site": "ratehawk_hotels", "result": raw, "url": url})
        carried = carried_wishes(items)
        mixed = split_problems(carried) if kind == "flights" else []
        if mixed:
            log.info("CHECK compose_answer travellers differ: %s", "; ".join(mixed)[:400])
            return {"ok": False, "problems": mixed, "next": "Fix this (search the odd source again with the same adults and children) and call compose_answer again. Do not write the answer yourself."}
        if not filters_used:          # each recipe handed over the filters it was given, inside its own script answer
            filters_used = list(dict.fromkeys(f for c in carried.values() for f in c["filters_used"]))
        if items:
            extra, srcs, problems, by_price, site_notes = convert_all(items, wishes or hotel_wishes)
            if problems:
                log.info("CHECK compose_answer site_results refused: %s", "; ".join(dict.fromkeys(problems))[:800])
                stop = any(": STOP," in p for p in problems)
                return {"ok": False, "problems": list(dict.fromkeys(problems)),
                        "next": ("Do not run that source again: put it in not_checked with the reason the STOP line gives and call compose_answer again. Do not write the answer yourself." if stop
                                 else "Fix these (run the recipe again as the problem says) and call compose_answer again. Do not write the answer yourself.")}
            offers += extra
            via_model = sorted({str(i.get("site")) for i in items if _is_parts(i)})
            if via_model:       # the page refused to send these to the server: the rows went through the assistant (their checksums matched); the answer says so itself
                notes = (notes + f" Passed through the assistant in parts, not received by the server directly: {', '.join(via_model)} (every part matched its checksum).").strip()
            names = {x.name.lower() for x in srcs}
            sources_read = [x for x in sources_read if x.name.lower() not in names] + srcs
            sorted_by_price = by_price
            if site_notes:
                notes = (notes + " " + " ".join(site_notes)).strip()
        unused = unused_recipes(kind, {str(i.get("site")) for i in items}, not_checked)
        if unused:
            log.info("CHECK compose_answer recipes issued but missing: %s", "; ".join(unused))
            return {"ok": False, "problems": [f"recipe(s) were issued for this answer but have no result in it: {', '.join(unused)}. Pass the result (runs=[its ingest id], or its parts with the recipe's own site key) or put the source in not_checked with the real reason "
                                              "(block, could not be read: <the script's error>, route not served). A source is never dropped without a word."],
                    "next": "Fix this and call compose_answer again. Do not write the answer without these sources."}
        merge_default_group(offers, items)
        apply_wishes(offers, wishes or hotel_wishes)
        if any((c["wishes"].get("expect") or {}).get("checked_bag") for c in carried.values()):
            bag_note = bag_unconfirmed(offers)
            notes = (notes + " " + bag_note).strip() if bag_note else notes
        if kind == "flights" and any((c["wishes"].get("expect") or {}).get("refundable") for c in carried.values()):
            refund_note = refund_unconfirmed(offers)
            notes = (notes + " " + refund_note).strip() if refund_note else notes
        tracking_unknown = sorted({o.source for o in offers if (o.details or {}).get("flight_tracking") not in ("yes", "no")}) if kind == "transfers" and (wishes or any(c["wishes"].get("flight_tracking") for c in carried.values())) else []
        if tracking_unknown and any(c["wishes"].get("flight_tracking") for c in carried.values()):
            notes = (notes + f" Flight tracking was asked: only RateHawk shows it per row. {', '.join(tracking_unknown)} do not, so their rows are in the table with their flight tracking unknown.").strip()
        out = compose(kind, filters_used, sources_read, not_checked, offers, myt_supplier or {}, pickup_time, sorted_by_price, notes, max_rows=MAX_ROWS_BY_KIND.get(kind))
        log.info("CHECK compose_answer kind=%s ok=%s items=%s offers=%s carried=%s passed=%s problems=%s", kind, out.get("ok"), [(i.get("site"), len(i.get("result", ""))) for i in items], len(offers),
                 {k[0]: {w: (c["wishes"].get("expect") or {}).get(w) for w in ("direct_only", "checked_bag", "refundable")} for k, c in carried.items()},
                 sorted((wishes or {}).keys()), "; ".join(out.get("problems", []))[:800])          # sizes and rule messages only, never the rows
        if out.get("ok") and out.get("answer"):
            COMPOSED.remember(kind, out["answer"])
            if renamed:
                out["site_names_fixed"] = renamed
        return out

    register_all(mcp)
