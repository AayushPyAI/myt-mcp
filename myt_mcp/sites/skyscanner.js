// Skyscanner flights (comparison only): the page's OWN search call, replayed in the page. Run it in the operator's Skyscanner RESULTS tab (read only; it clicks nothing and books nothing).
// The results page gets its tickets from ONE service of its own (read live 7 Nov 2026 in the page's code, chunk FlightsDayView): POST /g/radar/api/v2/web-unified-search/ with the search
// (cabin class, adults, children's ages, and per leg the origin and destination ENTITY ids and the date), then GET /g/radar/api/v2/web-unified-search/<session id> about once a second until its
// context.status is "complete". The headers are the page's own (X-Skyscanner-Locale / Market / Currency / ChannelId / ViewId / TrustedFunnelId / DeviceDetection; viewId and culture are in window.__internal on every
// skyscanner page). The search is the one the tool asks for (REQ: airports, date, adults, ages, cabin). The entity id of an airport is the GeoId of the page's own place lookup GET /g/autosuggest-search/api/v1/search-flight/
// <market>/<locale>/<IATA code> (read live 7 Nov 2026: FLR 95673830, LIS 95565055 = the ids the results page itself sends); when the page is the results page of the same airports its own ids are used. So the script
// does NOT need the results page: any skyscanner.net page works. The answer holds EVERY itinerary of the search (90 for FLR-LIS on 12 Dec 2026, the page said "90 results"):
// the price of the whole group (price.raw, exact: the page shows it rounded up), the legs with their segments (flight number, marketing and operating carrier), stop count, duration, the sellers with their prices
// (the airline's own among them), self-transfer flags, emissions and Skyscanner's "score" (the Best order: the page's Best list = score descending, its Cheapest list = price ascending, checked 18 of 18 tickets).
// Filters are the page's own client-side boxes and are NOT in the call: the call carries none, so no hidden filter can change the list; "direct only" is applied here on the stop count.
// The tool replaces __REQUEST__ (the search), __SORTS__ (e.g. ["Best","Cheapest"]), __LIMIT__ (tickets per sort), __SKIP__ (tickets already shown per sort: "more") and __DIRECT__ (true/false). A human check (captcha) stops the script: it is never worked around.
await (async () => {
  const SORTS = __SORTS__; const LIMIT = __LIMIT__; const SKIP = __SKIP__; const DIRECT = __DIRECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Skyscanner shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)skyscanner\.[a-z.]+$/.test(location.hostname)) return JSON.stringify({ ok: false, error: 'not a Skyscanner page: open the url first' });
  const REQ = __REQUEST__;
  const t0 = performance.now();
  for (let i = 0; i < 20 && !(window.__internal && window.__internal.viewId); i++) await wait(500);
  const w = window.__internal || {}; const cu = w.culture || {}; const sp = w.searchParams;
  if (!w.viewId) return JSON.stringify({ ok: false, error: 'the page has no Skyscanner session (Skyscanner changed its page, or it is still loading): wait and run once more' });
  const H = { 'X-Skyscanner-Locale': cu.locale || 'en-GB', 'X-Skyscanner-Market': cu.market || 'UK', 'X-Skyscanner-Currency': cu.currency || 'EUR', 'X-Skyscanner-ChannelId': 'website', 'X-Skyscanner-ViewId': w.viewId,
    'X-Skyscanner-TrustedFunnelId': w.viewId, 'X-Skyscanner-DeviceDetection-IsMobile': 'false', 'X-Skyscanner-DeviceDetection-IsTablet': 'false' };
  const blocked = (res, tx) => res.status === 403 || res.status === 429 || /captcha|are you a person or a robot/i.test(String(tx).slice(0, 600));
  const refused = (res) => JSON.stringify({ ok: false, error: 'Skyscanner refused the service (human check or block, HTTP ' + res.status + '). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  // the entity id of an airport: the results page's own ids when it is the same airports, else the GeoId of the page's place lookup (the place whose PlaceId is exactly the airport code)
  const pageLeg = sp && Array.isArray(sp.legs) && sp.legs.length === 1 ? sp.legs[0] : null;
  const entity = async (code, pageId, pageEntity) => {
    if (pageLeg && pageLeg[pageId] === code && pageLeg[pageEntity]) return { id: String(pageLeg[pageEntity]), from: 'page' };
    const res = await fetch('/g/autosuggest-search/api/v1/search-flight/' + (cu.market || 'UK') + '/' + (cu.locale || 'en-GB') + '/' + encodeURIComponent(code), { headers: H });
    const tx = await res.text();
    if (blocked(res, tx)) return { blocked: res };
    if (!res.ok) throw new Error('place lookup answered ' + res.status);
    const hit = (JSON.parse(tx) || []).find((p) => String(p.PlaceId).toUpperCase() === code && p.GeoId);
    if (!hit) return { missing: code };
    return { id: String(hit.GeoId), from: 'lookup' };
  };
  let eo; let ed;
  try { eo = await entity(REQ.origin, 'originId', 'originEntityId'); ed = await entity(REQ.destination, 'destinationId', 'destinationEntityId'); }
  catch (err) { return JSON.stringify({ ok: false, error: 'Skyscanner\'s place lookup could not be read (' + String(err.message || err).slice(0, 80) + '): say it could not be read' }); }
  if (eo.blocked || ed.blocked) return refused(eo.blocked || ed.blocked);
  if (eo.missing || ed.missing) return JSON.stringify({ ok: false, error: 'Skyscanner knows no airport with the code ' + (eo.missing || ed.missing) + ': check the code' });
  const [yy, mm, dd] = String(REQ.day).split('-');
  const ages = (REQ.ages || []).map((a) => Number(a));
  const body = { cabinClass: REQ.cabin, childAges: ages, adults: REQ.adults,
    legs: [{ legOrigin: { '@type': 'entity', entityId: eo.id }, legDestination: { '@type': 'entity', entityId: ed.id }, dates: { '@type': 'date', year: yy, month: mm, day: dd } }] };
  let j; let polls = 0;
  try {
    let res = await fetch('/g/radar/api/v2/web-unified-search/', { method: 'POST', headers: { ...H, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let tx = await res.text();
    if (blocked(res, tx)) return refused(res);
    if (!res.ok) throw new Error('answered ' + res.status);
    j = JSON.parse(tx);
    for (; polls < 30 && j.context && j.context.status !== 'complete'; polls++) {      // the page asks again about once a second until the search is complete (it gives up after 60 s; the browser tool after 45 s)
      await wait(1000);
      res = await fetch('/g/radar/api/v2/web-unified-search/' + encodeURIComponent(j.context.sessionId), { headers: H });
      tx = await res.text();
      if (blocked(res, tx)) return refused(res);
      if (!res.ok) throw new Error('answered ' + res.status + ' while the search ran');
      j = JSON.parse(tx);
    }
  } catch (err) { return JSON.stringify({ ok: false, error: 'Skyscanner\'s search service could not be read (' + String(err.message || err).slice(0, 80) + '): say it could not be read' }); }
  const it = j.itineraries || {};
  const status = j.context && j.context.status;
  if (status !== 'complete') return JSON.stringify({ ok: false, error: 'Skyscanner had not finished the search after ' + Math.round((performance.now() - t0) / 1000) + ' s (' + (it.results || []).length + ' tickets so far): run the script once more' });
  if (it.context && it.context.status === 'failure') return JSON.stringify({ ok: false, error: 'Skyscanner\'s search failed (its own status is "failure"): run the script once more, or say it could not be read' });
  const all = it.results || [];
  const agents = Object.fromEntries((it.agents || []).map((a) => [a.id, a]));
  const uniq = (xs) => [...new Set(xs.filter(Boolean))];
  const usable = (r) => { const l = (r.legs || [])[0]; return !!(l && r.price && Number.isFinite(r.price.raw) && (l.segments || []).length); };      // a ticket without a price or a flight is counted, never invented
  const rowOf = (r, sort, rank) => {
    const l = r.legs[0];
    const segs = l.segments;
    const sellers = (r.pricingOptions || []).map((po) => {
      const items = po.items || []; const names = uniq(items.map((x) => agents[x.agentId] && agents[x.agentId].name));
      const amount = po.price && Number.isFinite(po.price.amount) ? po.price.amount : items.reduce((s, x) => s + ((x.price && x.price.amount) || 0), 0);
      return { n: names.join(' + ') || null, a: items.length > 0 && items.every((x) => agents[x.agentId] && agents[x.agentId].isCarrier), p: amount || null };
    }).filter((s) => s.n && s.p).sort((a, b) => a.p - b.p);
    return { sort, rank, id: r.id, total: r.price.raw, stops: l.stopCount, mins: l.durationInMinutes, dep: l.departure, arr: l.arrival, plus: l.timeDeltaInDays || 0,
      mk: uniq(segs.map((s) => s.marketingCarrier && s.marketingCarrier.name)), op: uniq(segs.map((s) => s.operatingCarrier && s.operatingCarrier.name)),
      flights: segs.map((s) => ((s.marketingCarrier && s.marketingCarrier.displayCode) || '') + ' ' + (s.flightNumber || '')).map((x) => x.trim()),
      via: segs.slice(0, -1).map((s) => ({ code: s.destination && (s.destination.displayCode || s.destination.flightPlaceId), name: s.destination && s.destination.name })),
      layover: Math.max(0, l.durationInMinutes - segs.reduce((s, x) => s + (x.durationInMinutes || 0), 0)), self_transfer: !!r.isSelfTransfer, protected: !!r.isProtectedSelfTransfer, tags: r.tags || [],
      em_kg: r.emissions ? r.emissions.emissionsKg : null, em_level: r.emissions ? r.emissions.emissionsLevel : null, sellers: sellers.slice(0, 6), seller_count: sellers.length, airline_price: (sellers.find((s) => s.a) || {}).p || null };
  };
  const asked = DIRECT ? all.filter((r) => ((r.legs || [])[0] || {}).stopCount === 0) : all;
  const pool = asked.filter(usable); const unparsed = asked.length - pool.length;
  const order = { Best: (a, b) => (b.score || 0) - (a.score || 0), Cheapest: (a, b) => a.price.raw - b.price.raw };
  const rows = []; const sorts = [];
  for (const sort of SORTS) {
    if (!order[sort]) return JSON.stringify({ ok: false, error: 'unknown sort ' + sort });
    const win = [...pool].sort(order[sort]).slice(SKIP, SKIP + LIMIT);
    const before = rows.length;
    win.forEach((r, i) => rows.push(rowOf(r, sort, SKIP + i + 1)));
    sorts.push({ sort, read: rows.length - before });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    route: [REQ.origin, REQ.destination], date: REQ.day, adults: REQ.adults, children_ages: ages, cabin: REQ.cabin, entities: { origin: eo.from, destination: ed.from }, currency: cu.currency || 'EUR', direct_only: DIRECT, results_total: all.length, matching_total: asked.length,
    offset: SKIP, sorts, status, polls, unparsed, ms: Math.round(performance.now() - t0) }, rows);
})()
