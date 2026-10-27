// Booking.com flights list reader (comparison only). Run it in the operator's Booking.com flights RESULTS tab the recipe opened (read only: it presses the Sort menu and the page numbers below the list).
// Every flight is one card (data-testid="searchresults_card") with named parts (flight_card_segment_departure_time_0, ..._stops_0, ..._duration_0, flight_card_carriers, upt_price = per adult,
// flight_card_price_total_price = "EUR 313 total" for the whole group): the parts are read by name, nothing is guessed from the text. The address already holds the cabin, the euro, the Best sort and, for
// "direct only", stops=0 (the site writes stops=0 itself when its stops filter is set; checked live 27 Oct 2026). The page lists 15 flights per page with page numbers under the list: the script reads the first
// PAGES pages of the Best sort, then picks Cheapest in the Sort menu and reads the first PAGES pages of that (the agency reads Best and Cheapest together). The page says "We found N flight options" (N is the
// whole list) and, when a route has no direct flight and direct was asked, "There are no direct flights for your search. Here are other options": that is returned too.
// A human check (captcha) stops the script: it is never worked around. The tool replaces __EXPECT__ (what the address asked for), __PAGES__ (pages per sort) and __SORTS__ (["Best","Cheapest"]).
await (async () => {
  const EXPECT = __EXPECT__; const PAGES = __PAGES__; const SORTS = __SORTS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(document.body.innerText.slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/flights\.booking\.com$/i.test(location.hostname) || !/^\/flights\//.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the Booking.com flights results page: open the url first' });
  const cards = () => [...document.querySelectorAll('[data-testid="searchresults_card"]')];
  for (let i = 0; i < (typeof CARD_TRIES !== 'undefined' ? CARD_TRIES : 60) && !cards().length; i++) await wait(500);      // up to 30 s (CARD_TRIES: tests only)
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no flights are shown (still searching, a check page, or no flights for this search): never say there are none, say it could not be read' });
  const q = new URLSearchParams(location.search);
  const code = (v) => String(v || '').split('.')[0];
  const form = { type: q.get('type'), origin: code(q.get('from')), destination: code(q.get('to')), day: q.get('depart'), adults: parseInt(q.get('adults') || '', 10) || null, children: q.get('children') ? q.get('children').split(',').length : 0,
    cabin: q.get('cabinClass'), currency: q.get('currency'), sort: q.get('sort'), stops: q.get('stops') };
  const problems = [];
  for (const k of ['type', 'origin', 'destination', 'day', 'adults', 'children', 'cabin', 'currency', 'sort', 'stops']) if (EXPECT[k] !== undefined && form[k] !== EXPECT[k]) problems.push(k + ' ' + form[k] + ' instead of ' + EXPECT[k]);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form });
  const text = () => document.body.innerText;
  const sortLabel = () => ((([...document.querySelectorAll('button')].map((b) => (b.innerText || '').trim()).find((t) => /^Sort by:/i.test(t))) || '').replace(/^Sort by:\s*/i, '')) || null;
  const pager = () => [...document.querySelectorAll('ol button')].filter((b) => /^\d{1,3}$/.test((b.innerText || '').trim()));
  const currentPage = () => { const b = pager().find((x) => x.getAttribute('aria-current')); return b ? parseInt(b.innerText.trim(), 10) : null; };
  const found = ((text().match(/We found ([\d,]+) flight options?/i) || text().match(/Showing ([\d,]+) results?/i) || [])[1] || '').replace(/,/g, '') || null;      // what the site says exists
  const noDirect = /There are no direct flights for your search/i.test(text());
  // the filter boxes: the stops radio ("-1" any, "0" direct only, "1" one stop at most), the airlines (all ticked by default) and the flight times (none ticked by default)
  const stopsRadio = (([...document.querySelectorAll('input[name="filters-stops-option"]')].find((r) => r.checked)) || {}).value || null;
  const inGroup = (id) => [...document.querySelectorAll('[data-testid="' + id + '"] input[type=checkbox]')];
  const filters = { stops: stopsRadio, airlines_off: inGroup('airlines_filter').filter((c) => !c.checked).length, times_on: inGroup('flight_times_filter').filter((c) => c.checked).length };
  const T = (el, id) => { const e = el.querySelector('[data-testid="' + id + '"]'); return e ? e.innerText.replace(/\s+/g, ' ').trim() : null; };
  const money = (s) => { const m = String(s || '').match(/(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/); return m ? { symbol: m[1], amount: parseFloat(m[2].replace(/,/g, '')) } : null; };
  const rows = []; const unparsed = []; const sorts = [];
  const readPage = (sort, page) => {
    for (const c of cards()) {
      const legs = []; for (let i = 0; T(c, 'flight_card_segment_departure_time_' + i); i++) legs.push(i);
      const total_price = money(T(c, 'flight_card_price_total_price')); const per = money(T(c, 'upt_price'));
      if (!legs.length || !total_price) { if (unparsed.length < 3) unparsed.push(c.innerText.replace(/\s+/g, ' ').slice(0, 160)); continue; }
      const leg = (i) => ({ dep: T(c, 'flight_card_segment_departure_time_' + i), from: T(c, 'flight_card_segment_departure_airport_' + i), dep_date: T(c, 'flight_card_segment_departure_date_' + i), stops: T(c, 'flight_card_segment_stops_' + i),
        duration: T(c, 'flight_card_segment_duration_' + i), arr: T(c, 'flight_card_segment_destination_time_' + i), to: T(c, 'flight_card_segment_destination_airport_' + i), arr_date: T(c, 'flight_card_segment_destination_date_' + i) });
      rows.push({ sort, page, legs: legs.map(leg), carriers: T(c, 'flight_card_carriers'), cur: total_price.symbol, total: total_price.amount, per_adult: per ? per.amount : null, flexible_upgrade: /Flexible ticket upgrade available/i.test(c.innerText) });
    }
  };
  const goPage = async (n) => {      // the site's own page number below the list (it changes the list inside the page: no reload)
    const b = pager().find((x) => parseInt(x.innerText.trim(), 10) === n);
    if (!b) return false;
    b.click();
    for (let k = 0; k < 24 && currentPage() !== n; k++) await wait(400);
    await wait(1500);
    return currentPage() === n;
  };
  for (const sort of SORTS) {
    if ((sortLabel() || '').toLowerCase() !== sort.toLowerCase()) {
      const sb = [...document.querySelectorAll('button')].find((b) => /^Sort by:/i.test((b.innerText || '').trim()));
      if (!sb) return JSON.stringify({ ok: false, error: 'the Sort menu is not on the page: run the script once more' });
      sb.click(); await wait(900);
      const item = [...document.querySelectorAll('button[role=menuitem]')].find((b) => new RegExp('^' + sort, 'i').test((b.innerText || '').trim()));
      if (!item) return JSON.stringify({ ok: false, error: 'the Sort menu has no "' + sort + '" item: run the script once more' });
      item.click();
      for (let k = 0; k < 24 && (sortLabel() || '').toLowerCase() !== sort.toLowerCase(); k++) await wait(400);
      await wait(1800);
    }
    if (currentPage() && currentPage() !== 1) await goPage(1);
    const pagesInList = pager().length ? Math.max(...pager().map((b) => parseInt(b.innerText.trim(), 10))) : 1;
    let read = 0;
    for (let p = 1; p <= Math.min(PAGES, pagesInList); p++) {
      if (p > 1 && !(await goPage(p))) break;
      readPage(sort, p); read++;
    }
    sorts.push({ sort, shown_as: sortLabel(), pages_read: read, pages_seen: pagesInList });
  }
  const perPage = (text().match(/Flight option \d+ of (\d+)/i) || [])[1];
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, filters, no_direct_notice: noDirect, results_total: found ? Number(found) : null, per_page: perPage ? Number(perPage) : null, sorts, unparsed }, rows);
})()
