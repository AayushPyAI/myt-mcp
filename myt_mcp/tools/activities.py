"""Activity tools (Viator; Tripadvisor Experiences are largely the same Viator inventory)."""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import IntegrationError, tool_errors
from myt_mcp.labels import activity_glance, free_cancellation
from myt_mcp.gyg.client import URL_PATTERN
from myt_mcp.gyg.parse import (AgeGroupError, PAGE_SIZE as GYG_PAGE, SORTS as GYG_SORTS, check_availability as check_gyg, check_search as check_gyg_search,
                               MIN_REVIEWS_FOR_RATING_SORT as MIN_REVIEWS, duration_minutes as gyg_minutes, group_note, long_date, parse_availability, participants_for,
                               price_range as gyg_price_range, search_page, shortlist as gyg_shortlist, sort_rows as gyg_sort_rows)
from myt_mcp.services import Services
from myt_mcp.viator.parse import (MIN_REVIEWS_FOR_RATING_SORT as VIATOR_MIN_REVIEWS, PAGE_SIZE as VIATOR_PAGE, SORTS as VIATOR_SORTS, AgeBandError, age_bands_for, bookable_on, check_availability,
                                  check_product, check_search, duration_minutes, price_range, related, shortlist as viator_shortlist, sort_rows, summarize_availability,
                                  summarize_product, summarize_search)

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _today() -> date:
    return date.today()


def _page_currency(currency: str | None) -> list[str]:
    if currency and currency.upper() not in ("EUR", "€"):
        return [f"Viator is showing prices in {currency}, not EUR (switch it in the automation browser: header -> Currency)"]
    return []


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def viator_search_activities(
        query: str,
        max_results: int = 12,
        pages: int = 2,
        sort_by: str = "featured",
        max_price: float | None = None,
        free_cancellation_only: bool = False,
        min_rating: float | None = None,
        max_hours: float | None = None,
        title_contains: list[str] | None = None,
    ) -> dict[str, Any]:
        """Things to do, tours, tickets, excursions and activity prices (use for any such question; Tripadvisor Experiences are mostly the same inventory). Search Viator for tours and activities, e.g. "Sintra day trip from Lisbon" or "Florence cooking class".
        Returns title, "from" price per person, rating and reviews, duration, free cancellation, languages,
        badges and the activity link. Then use viator_activity_details on the best few for the trip date.
        Viator shows 24 results per page, most relevant first, and cannot sort by price; this tool reads `pages` pages
        (24 each, one request about every 15 s: 2 pages ~30 s, 4 pages ~1 min, at most 9) and then sorts and filters them
        itself. The answer says how many results were read out of how many exist (`coverage`) and the price range of
        everything read: never call anything "the cheapest" unless coverage says all results were read; say "cheapest of
        the N read". Choose from the traveller's wishes: sort_by "price" (budget), "rating", "reviews" (most popular),
        "duration" (shortest first) or "featured" (Viator's order, default); max_price = most per person (the "from" price);
        free_cancellation_only; min_rating (e.g. 4.5); max_hours; title_contains = keep only titles with any of these words
        (e.g. ["cooking", "pasta"]: removes Viator's look-alike padding). Each row has `rank` (show in this order) and `few_reviews`;
        `shortlist_for_exact_price` names the cheapest, best rated and most reviewed to price with viator_activity_details.
        For a cheapest/budget question use pages 4-9."""
        if not query or not query.strip():
            raise ToolError("query is empty.")
        if sum(ch.isalnum() for ch in query) < 2:
            raise ToolError("query needs words, e.g. 'Florence cooking class'.")
        if len(query) > 200:
            raise ToolError("query is too long; use a few words (city + activity).")
        if not 1 <= max_results <= 60:
            raise ToolError("max_results must be between 1 and 60.")
        if not 1 <= pages <= 9:
            raise ToolError("pages must be between 1 and 9 (24 results each).")
        if sort_by not in VIATOR_SORTS:
            raise ToolError(f"sort_by must be one of: {', '.join(VIATOR_SORTS)}.")
        if max_price is not None and max_price <= 0:
            raise ToolError("max_price must be more than 0 (EUR per person).")
        if min_rating is not None and not 0 < min_rating <= 5:
            raise ToolError("min_rating must be between 0 and 5.")
        if max_hours is not None and max_hours <= 0:
            raise ToolError("max_hours must be more than 0.")
        words = [w.strip().lower() for w in title_contains or [] if w and w.strip()]

        viator = services.viator()
        read: list[dict[str, Any]] = []
        seen: set[str] = set()
        total = skipped = pages_read = 0
        stopped = None
        for number in range(1, pages + 1):
            try:
                page = await viator.search(query, number)
            except IntegrationError as e:
                if number == 1:
                    raise
                stopped = f"page {number} could not be read ({e}); the answer covers pages 1-{number - 1}."
                break
            batch, total, skip = summarize_search(page["state"], page.get("urls") or {}, VIATOR_PAGE)
            ensure("Viator", _page_currency(page.get("currency")) + check_search(batch))
            skipped += skip
            pages_read += 1
            read += [r for r in batch if r["code"] not in seen and not seen.add(r["code"])]
            if len(batch) < VIATOR_PAGE or len(read) >= total:
                break

        rows = read
        if max_price is not None:
            rows = [r for r in rows if r["from_price"] is not None and r["from_price"] <= max_price]
        if free_cancellation_only:
            rows = [r for r in rows if r["free_cancellation"]]
        if min_rating is not None:
            rows = [r for r in rows if (r["rating"] or 0) >= min_rating]
        if max_hours is not None:
            rows = [r for r in rows if (duration_minutes(r["duration"]) or 10 ** 9) <= max_hours * 60]
        if words:
            rows = [r for r in rows if any(w in (r["title"] or "").lower() for w in words)]
        rows = sort_rows(rows, sort_by)
        rows = [{"rank": n, **r, "few_reviews": (r["reviews"] or 0) < VIATOR_MIN_REVIEWS} for n, r in enumerate(rows, 1)]
        shown = rows[:max_results]

        everything = len(read) >= total
        answer: dict[str, Any] = {
            "query": query, "sorted_by": sort_by,
            "filters": {"max_price": max_price, "free_cancellation_only": free_cancellation_only, "min_rating": min_rating, "max_hours": max_hours,
                        "title_contains": words or None},
            "coverage": {"pages_read": pages_read, "results_read": len(read), "total_on_viator": total, "all_results_read": everything,
                         "passed_filters": len(rows), "shown": len(shown)},
            "price_range_of_results_read": price_range(read),
            "activities": shown,
            "shortlist_for_exact_price": viator_shortlist(rows),
            "show_rows": "In `rank` order (do not re-sort); mark rows with few_reviews true as \"few reviews\" (under 20 reviews).",
            "also_check": ("Search GetYourGuide (its Claude connector) with the same city, activity and date, and show both "
                           "sites side by side; the same class often has a different price there. If GetYourGuide is not "
                           "connected in this chat, say so at the top of the answer."),
        }
        notes = []
        if not read:
            notes.append("Viator found no activities for this search; try other words (city + activity).")
        elif not everything:
            notes.append(f"Read {len(read)} of {total}{'+' if total >= 200 else ''} results (Viator's own order, most relevant first). Say 'cheapest of the "
                         f"{len(read)} read', never just 'the cheapest'. To read more, search again with a higher `pages` (up to 9).")
        if read and not rows:
            notes.append("None of the results read passes the filters; say so and offer a higher price, a lower rating or more pages.")
        if notes:
            answer["note"] = " ".join(notes)
        warnings = []
        if stopped:
            warnings.append(stopped)
        if skipped:
            warnings.append(f"{skipped} results had an unexpected format and were left out.")
        no_link = [r["title"] for r in shown if not r.get("url")]
        if no_link:
            warnings.append(f"{len(no_link)} result(s) have no activity link ({'; '.join(t[:40] for t in no_link[:3])}); do not guess a link for them, "
                            "search again with their exact title.")
        if read and not related(query, read):
            warnings.append("None of these results contain the words you searched for; Viator showed general results. "
                            "Do not present them as matches; tell the operator nothing matched.")
        if warnings:
            answer["warning"] = " ".join(warnings)
        return answer

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def viator_activity_details(url: str, activity_date: date | None = None, adults: int = 2,
                                      child_ages: list[int] | None = None) -> dict[str, Any]:
        """Full details of one Viator activity (use the `url` from viator_search_activities): tour options, meeting
        point / pickup, what is and isn't included, cancellation policy, languages, duration, rating and age groups.
        With `activity_date` it also runs Viator's availability check for the group (`adults` + `child_ages`, the
        children's ages on the trip): which options and start times are free that day and the exact total price for
        the whole group. Nothing is booked. Without a date it lists the next bookable dates."""
        if not url.startswith("https://www.viator.com/tours/"):
            raise ToolError("url must be a Viator activity link (https://www.viator.com/tours/...).")
        if activity_date and activity_date < date.today():
            raise ToolError("activity_date is in the past.")
        child_ages = child_ages or []
        if not 0 <= adults <= 15 or adults + len(child_ages) == 0 or adults + len(child_ages) > 15:
            raise ToolError("Travellers must be 1-15 people in total (adults 0-15).")
        if any(not 0 <= age <= 17 for age in child_ages):
            raise ToolError("child_ages must be ages 0-17; put travellers aged 18+ in adults.")
        viator = services.viator()
        data = await viator.product(url)
        ensure("Viator", _page_currency(data.get("currency")) + check_product(data["product"], data["calendar"], url))
        answer = summarize_product(data["product"], data["calendar"], activity_date)
        answer["url"] = url
        if activity_date:
            try:
                bands = age_bands_for(data["product"], adults, child_ages)
            except AgeBandError as e:
                raise ToolError(str(e)) from None
            if bookable_on(data["calendar"], activity_date):
                check = await viator.check_availability(url, activity_date, bands)
                ensure("Viator", check_availability(check, data["product"]["productCode"], activity_date, bands))
                answer["for_your_group"] = {"date": activity_date.isoformat(), "travellers": bands,
                                            "prices_are_for": "the whole group together", **summarize_availability(check)}
            else:   # Viator's calendar lists the bookable days; a group price for another day would contradict it
                answer["for_your_group"] = {"date": activity_date.isoformat(), "travellers": bands, "any_available": False,
                                            "note": "Viator's calendar does not list this date as bookable, so no group price is shown. "
                                                    "See availability.nearest_available_dates."}
        if not data["calendar"]:
            answer["availability"]["note"] = "Viator did not return its price calendar; check availability on the page."
        group = answer.get("for_your_group") or {}
        if group.get("options"):
            refundable = group.get("refundable")
            answer["at_a_glance"] = activity_glance([
                {"option": o.get("option"), "time": s.get("time"), "price": s.get("total_price"),
                 "price_before_discount": s.get("price_before_discount"), "free_cancellation": refundable,
                 "cancellation": f"free cancellation until {group.get('free_cancellation_until')}" if refundable and group.get("free_cancellation_until") else None}
                for o in group["options"] if o.get("available") for s in o.get("start_times") or [] if s.get("available")])
        return answer


    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def getyourguide_activity_details(url: str, activity_date: date, adults: int = 2,
                                            child_ages: list[int] | None = None) -> dict[str, Any]:
        """The exact price for ONE GetYourGuide activity: use the activity link from getyourguide_find_activities (never guess a link).
        For the date and group it returns every option with its start times, the exact total price for the whole group
        (adults + children by age, in EUR), meeting point, cancellation, language and duration, plus the activity's
        highlights and what is included. Nothing is booked. The search "from" price is only the lowest starting price."""
        match = URL_PATTERN.match(url or "")
        if not match:
            raise ToolError("url must be a GetYourGuide activity link (https://www.getyourguide.com/.../...-t12345/).")
        if activity_date < _today():
            raise ToolError("activity_date is in the past.")
        child_ages = child_ages or []
        if not 0 <= adults <= 15 or not 1 <= adults + len(child_ages) <= 15:
            raise ToolError("Travellers must be 1-15 people in total (adults 0-15).")
        if any(not 0 <= age <= 17 for age in child_ages):
            raise ToolError("child_ages must be ages 0-17; put travellers aged 18+ in adults.")
        gyg = services.gyg()
        info = await gyg.page(url)
        try:
            participants, requested = participants_for(info["categories"], adults, child_ages)
        except AgeGroupError as e:
            raise ToolError(str(e)) from None
        parsed = parse_availability(await gyg.availability(url, info, activity_date, participants))
        ensure("GetYourGuide", check_gyg(parsed, activity_date, adults + len(child_ages)))
        options = []
        for option in parsed["options"]:
            note = group_note(option, requested)
            if not option.get("meeting_point") and info.get("meeting_point"):    # many options give it only in the page's "Meeting point" section
                option = {**option, "meeting_point": info["meeting_point"], "meeting_point_from": "the activity page (applies to every option unless the page says otherwise)"}
            options.append({**option, **({"price_note": note} if note else {})})
        answer: dict[str, Any] = {
            "title": info.get("title"), "activity_url": f"https://www.getyourguide.com/{url.split('getyourguide.com/')[1].split('?')[0]}",
            "date": activity_date.isoformat(), "travellers": requested, "prices_are_for": "the whole group together, in EUR, taxes included",
            "any_available": parsed["any_available"], "options": options,
            "meeting_point": info.get("meeting_point") or next((o["meeting_point"] for o in options if o.get("meeting_point")), None),
            "highlights": info["highlights"], "includes": info["includes"], "not_included": info["not_included"], "cancellation": info["cancellation"],
            "traveller_groups": [{"name": c["name"], "ages": f"{c['min_age']}-{c['max_age']}"} for c in info["categories"]],
        }
        if not parsed["any_available"]:
            answer["note"] = parsed["note"]
        if not answer["meeting_point"]:
            answer["meeting_point_note"] = "GetYourGuide's page gave no meeting point text for this activity: say 'meeting point not available' and check the page; never guess one."
        answer["at_a_glance"] = activity_glance([
            {"option": o.get("option"), "time": s.get("time"), "price": s.get("total_price"),
             "price_before_discount": s.get("price_before_discount"), "free_cancellation": free_cancellation(o.get("cancellation")),
             "cancellation": o.get("cancellation")}
            for o in options for s in o.get("start_times") or []])
        return answer

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def getyourguide_find_activities(
        query: str,
        activity_date: date | None = None,
        max_results: int = 12,
        pages: int = 2,
        sort_by: str = "popularity",
        min_price: float | None = None,
        max_price: float | None = None,
        free_cancellation_only: bool = False,
        min_rating: float | None = None,
        max_hours: float | None = None,
        title_contains: list[str] | None = None,
        read_all_relevant: bool = False,
    ) -> dict[str, Any]:
        """Search GetYourGuide for tours and activities, e.g. "Florence pasta cooking class". Use this, not the GetYourGuide connector
        (the connector only draws cards in the chat; Claude gets no prices, ratings or links from it).
        Returns for each result: title, REAL activity `url`, city, duration, "from" price in EUR (per person or per group:
        see price_basis), rating, reviews, free cancellation, private/small group, and whether it is available on
        `activity_date` (with the first start time). The "from" price is only the lowest starting price: for the exact EUR
        price of the whole group, start times, meeting point and cancellation call getyourguide_activity_details on the best 2-3.
        GetYourGuide shows 24 results per page in popularity order, most relevant first, and after a few pages it pads
        the list with other activities of the city; this tool reads `pages` pages (24 each, one request about every 5 s: 2 pages ~15 s,
        6 pages ~35 s, at most 12) and then sorts and filters them itself. The answer says how many results were read out of how many
        exist (`coverage`) and the price range of everything read: never call anything "the cheapest" unless coverage says all
        results were read; say "cheapest of the N read". Choose from the traveller's wishes: sort_by "price" (budget), "rating",
        "reviews" (most popular), "duration" (shortest first) or "popularity" (default); min_price / max_price = EUR "from" price shown;
        free_cancellation_only; min_rating (e.g. 4.5); max_hours; title_contains = keep only titles with any of these words (e.g. ["cooking", "pasta"]:
        removes the padding). Drop results that are not what was asked. For a "cheapest" question give `title_contains` and set `read_all_relevant` true:
        it reads up to 12 pages but stops at the first page (from page 2) where no title holds those words, and `coverage.all_relevant_read` says the
        relevant results were all read (then "cheapest of the N relevant" is fair). Never guess a link."""
        if not query or sum(ch.isalnum() for ch in query) < 2:
            raise ToolError("query needs words, e.g. 'Florence pasta cooking class'.")
        if len(query) > 200:
            raise ToolError("query is too long; use a few words (city + activity).")
        if not 1 <= max_results <= 60:
            raise ToolError("max_results must be between 1 and 60.")
        if not 1 <= pages <= 12:
            raise ToolError("pages must be between 1 and 12 (24 results each).")
        if sort_by not in GYG_SORTS:
            raise ToolError(f"sort_by must be one of: {', '.join(GYG_SORTS)}.")
        if (min_price is not None and min_price < 0) or (max_price is not None and max_price <= 0):
            raise ToolError("min_price must be 0 or more and max_price more than 0 (EUR).")
        if min_price is not None and max_price is not None and min_price > max_price:
            raise ToolError("min_price is higher than max_price.")
        if min_rating is not None and not 0 < min_rating <= 5:
            raise ToolError("min_rating must be between 0 and 5.")
        if max_hours is not None and max_hours <= 0:
            raise ToolError("max_hours must be more than 0.")
        if activity_date and activity_date < _today():
            raise ToolError("activity_date is in the past.")
        words = [w.strip().lower() for w in title_contains or [] if w and w.strip()]

        if read_all_relevant and not words:
            raise ToolError("read_all_relevant needs title_contains: the words that tell a relevant result from padding (e.g. [\"vatican\"]).")
        read_pages = await services.gyg().search(query, activity_date, 12 if read_all_relevant else pages, tuple(words) if read_all_relevant else ())
        read: list[dict[str, Any]] = []
        seen: set[Any] = set()
        total = None
        for answer in read_pages["answers"]:
            batch, page_total = search_page(answer)
            total = page_total or total
            read += [r for r in batch if r["activity_id"] not in seen and not seen.add(r["activity_id"])]
        ensure("GetYourGuide", check_gyg_search(read))
        currencies = {r["currency"] for r in read if r.get("currency")}
        ensure("GetYourGuide", [f"prices are in {', '.join(sorted(currencies))}, not EUR"] if currencies - {"EUR"} else [])

        rows = read
        if min_price is not None:
            rows = [r for r in rows if r["from_price"] is not None and r["from_price"] >= min_price]
        if max_price is not None:
            rows = [r for r in rows if r["from_price"] is not None and r["from_price"] <= max_price]
        if free_cancellation_only:
            rows = [r for r in rows if r["free_cancellation"]]
        if min_rating is not None:
            rows = [r for r in rows if (r["rating"] or 0) >= min_rating]
        if max_hours is not None:
            rows = [r for r in rows if (gyg_minutes(r["duration"]) or 10 ** 9) <= max_hours * 60]
        if words:
            rows = [r for r in rows if any(w in r["title"].lower() for w in words)]
        rows = gyg_sort_rows(rows, sort_by)
        rows = [{"rank": n, **r, "few_reviews": (r["reviews"] or 0) < MIN_REVIEWS} for n, r in enumerate(rows, 1)]
        shown = rows[:max_results]

        everything = total is not None and len(read) >= total
        relevant_read = [r for r in read if any(w in r["title"].lower() for w in words)] if words else []
        all_relevant = bool(read_all_relevant and read_pages.get("unrelated_from_page"))
        answer: dict[str, Any] = {
            "query": query, "date": activity_date.isoformat() if activity_date else None, "sorted_by": sort_by,
            "filters": {"min_price": min_price, "max_price": max_price, "free_cancellation_only": free_cancellation_only,
                        "min_rating": min_rating, "max_hours": max_hours, "title_contains": words or None},
            "coverage": {"pages_read": len(read_pages["answers"]), "results_read": len(read), "total_on_getyourguide": total,
                         "all_results_read": everything, "passed_filters": len(rows), "shown": len(shown)},
            "price_range_of_results_read": gyg_price_range(read),
            "activities": shown,
            "shortlist_for_exact_price": gyg_shortlist(rows),
            "show_rows": "In `rank` order (do not re-sort); mark rows with few_reviews true as \"few reviews\" (under 20 reviews).",
            "next_step": ("Call getyourguide_activity_details, one after another, for the shortlist_for_exact_price (cheapest, best rated, most reviewed of the results "
                          "that passed the filters) with the url, the date, adults and child_ages: the 'from' price here is only the lowest starting price. "
                          "Also search Viator with the same words and show both sites side by side."),
        }
        if read_all_relevant:
            answer["coverage"]["relevant_read"] = len(relevant_read)
            answer["coverage"]["all_relevant_read"] = all_relevant
        notes = []
        if not read:
            notes.append("GetYourGuide found no activities for this search; try other words (city + activity).")
        elif all_relevant:
            notes.append(f"Read all relevant results: {len(relevant_read)} titles with {', '.join(words)} in {len(read_pages['answers'])} pages; page "
                         f"{read_pages['unrelated_from_page']} had none, so the rest is other activities. Say 'cheapest of the {len(relevant_read)} relevant results' "
                         f"(of {total} GetYourGuide lists for the city search), not 'the cheapest on GetYourGuide'.")
        elif not everything:
            notes.append(f"Read {len(read)} of {total} results (GetYourGuide's popularity order, most relevant first; later pages drift to other activities of the city). "
                         f"Say 'cheapest of the {len(read)} read' and 'best of the {len(read)} read', never just 'the cheapest' or 'the best'. To read more, search again with a higher `pages` (up to 12).")
        if any(r["price_basis"] == "per group" for r in shown):
            notes.append("Rows with price_basis 'per group' show the price for the whole group (the size GetYourGuide shows on the card can be wrong); "
                         "do not compare them with per-person prices; get the exact price from the details tool.")
        if read and not rows:
            notes.append("None of the results read passes the filters; say so and offer a higher price, a lower rating or more pages.")
        if notes:
            answer["note"] = " ".join(notes)
        warnings = []
        if read_pages.get("stopped"):
            warnings.append(read_pages["stopped"])
        if read and not related(query, read):
            warnings.append("None of these results contain the words you searched for; GetYourGuide showed general results. "
                            "Do not present them as matches; tell the operator nothing matched.")
        if warnings:
            answer["warning"] = " ".join(warnings)
        return answer
