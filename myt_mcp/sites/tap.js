// TAP flight reader. Run it on a TAP booking page (booking.flytap.com; read only; it books nothing).
// The booking page gets its flights and fares from ONE request, POST /bfm/rest/booking/availability/search (the search in a JSON body, the page's own login token as `Authorization: Bearer ...`; it answers plain
// HTTP clients with ACCESS DENIED). The script sends that same request from the page, with the token the page keeps in its own session storage, for the leg and the group the operator asked for (checked live 5 Nov 2026:
// the answer equals the one the page drew its list from: the same 10 flights, 23 fares and prices). When that request fails, it reads the answer the page itself stored (`airportTranslationData`), the way it always did.
await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  const LIMIT = __LIMIT__; const SKIP = __SKIP__; const REQ = __REQUEST__;
  if (/(?<!re)captcha|verify you are human|unusual (traffic|activity)|access denied|blocked by our security/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'TAP shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (location.hostname !== 'booking.flytap.com' || !/\/booking\//.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a TAP booking page (booking.flytap.com/booking/flights): open the url first' });
  const t0 = performance.now();
  const token = () => { try { const t = JSON.parse(sessionStorage.getItem('token') || 'null'); return typeof t === 'string' && t.length > 20 ? t : null; } catch (e) { return null; } };
  const read = () => { try { const a = JSON.parse(sessionStorage.getItem('airportTranslationData') || 'null'); return a && a.data && Array.isArray(a.data.listOutbound) ? a : null; } catch (e) { return null; } };
  const NONE = /No flights available on[^\n]*/i;   // the page says it itself; the tool that runs this script gives up after 45 s, so the waits stop at about 38 s
  let ans = null; let source = null; let apiNote = null;
  for (let i = 0; i < 25 && !token() && !read(); i++) await wait(1000);          // the page logs itself in when it loads
  if (token() && REQ && REQ.day) {
    const dd = REQ.day.slice(8, 10) + REQ.day.slice(5, 7) + REQ.day.slice(0, 4); const seated = REQ.adults + REQ.children;
    const pax = { ADT: REQ.adults, YTH: 0, CHD: REQ.children, INF: REQ.infants };
    const body = { adt: REQ.adults, airlineId: 'TP', bfmModule: 'BFM_BOOKING', c14: 0, cabinClass: 'E', changeReturn: false, channelDetectionName: '', chd: REQ.children, cmsId: 'string', communities: [], departureDate: [dd], destination: [REQ.destination], groups: [], inf: REQ.infants,
      language: 'en', market: 'PT', multiCityTripType: false, numSeat: seated, numSeats: seated, oneWay: true, origin: [REQ.origin], passengers: pax, paxSearch: { ...pax }, permittedCabins: [], preferredCarrier: [], promocode: '', promotionId: '', returnDate: dd,
      roundTripType: false, searchPoint: true, session: 'string', tripType: 'O', validTripType: true, student: false, resident: false, yth: 0 };
    try {
      const res = await fetch('/bfm/rest/booking/availability/search?payWithMiles=false&starAlliance=false', { method: 'POST', credentials: 'same-origin', headers: { Authorization: 'Bearer ' + token(), Accept: 'application/json, text/plain, */*', 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error('answered ' + res.status);
      const j = await res.json();
      if (j && j.data && Array.isArray(j.data.listOutbound)) { ans = j; source = 'api'; } else apiNote = 'no flight list in the answer';
    } catch (err) { apiNote = String(err.message || err).slice(0, 80); }
    if (ans && source === 'api' && (!ans.data.listOutbound.length || ans.data.notAvailable)) return JSON.stringify({ ok: false, error: 'TAP itself says: "No flights available on ' + REQ.day + '" for ' + REQ.origin + ' to ' + REQ.destination + '. TAP has no flight on this leg that day: report that, do not retry; look at other days (tap_fare_calendar) or the other sources.' });
  }
  if (!ans) {      // the answer the page drew its own list from (the way it was read before the request above was used)
    for (let i = 0; i < 30 && !(read() && /flights? found|direct flights|connecting flights/i.test(text())) && !(NONE.test(text()) && !read()); i++) await wait(1000);
    await wait(1500);
    ans = read(); source = ans ? 'page' : null;
    if (!ans && NONE.test(text())) return JSON.stringify({ ok: false, error: 'TAP itself says: "' + text().match(NONE)[0].trim() + '". TAP has no flight on this leg that day: report that, do not retry; look at other days (tap_fare_calendar) or the other sources.' });
    if (!ans) return JSON.stringify({ ok: false, error: 'the TAP flight list could not be read (' + (apiNote ? 'its availability service said: ' + apiNote + '; ' : '') + 'the page has not drawn it: still searching, no flights for this search, or a human check): wait and run once more' });
  }
  const d = ans.data; const airlines = (ans.translate && ans.translate.airlines) || {};
  const offers = {}; for (const o of ((d.offers || {}).listOffers) || []) offers[o.idOffer] = o;
  const all = (v) => { const f = (v || []).filter((x) => typeof x === 'boolean'); return f.length ? (f.every(Boolean) ? 1 : 0) : null; };
  const local = (s) => (typeof s === 'string' && s.length >= 16 ? s.slice(0, 16).replace('T', ' ') : null);
  const flights = [];
  for (const fl of d.listOutbound || []) {
    const segs = (fl.listSegment || []).filter(Boolean); if (!segs.length) continue;
    const fares = (fl.relateOffer || []).map((i) => offers[i]).filter(Boolean).sort((a, b) => ((a.totalPrice || {}).price ?? 1e12) - ((b.totalPrice || {}).price ?? 1e12));
    if (!fares.length) continue;
    const first = segs[0]; const last = segs[segs.length - 1];
    const ops = [...new Set(segs.map((s) => s.operationCarrier && s.operationCarrier !== s.carrier ? (airlines[s.operationCarrier] || {}).name || s.operationCarrier : null).filter(Boolean))];
    flights.push({ fl, segs, first, last, ops, fares, cheapest: (fares[0].totalPrice || {}).price ?? 1e12 });
  }
  flights.sort((a, b) => a.cheapest - b.cheapest || (a.fl.duration || 0) - (b.fl.duration || 0));
  const shown = flights.slice(SKIP, SKIP + LIMIT); const rows = [];
  for (const f of shown) for (const [fi, o] of f.fares.entries()) {
    const per = {}; for (const p of o.listPaxPrice || []) if (p && p.typePax) per[p.typePax] = p.price;
    const out = o.outbound || {}; const seats = (o.groupFlights || []).map((g) => g.seatOutBound).filter((x) => x !== undefined && x !== null);
    rows.push({ fi, flights: f.segs.map((s) => `${s.carrier || ''}${s.flightNumber || ''}`).join('+'), op: f.ops.join(', ') || null, from: f.first.departureAirport, to: f.last.arrivalAirport, dep: local(f.first.departureDate), arr: local(f.last.arrivalDate),
      stops: f.fl.numberOfStops, mins: f.fl.duration, via: f.segs.slice(0, -1).map((s) => s.arrivalAirport).join(','), fare: o.outFareFamily, cabin: (out.cabin || [])[0] || null, total: (o.totalPrice || {}).price ?? null,
      adt: per.ADT ?? null, chd: per.CHD ?? null, inf: per.INF ?? null, bag: all(out.bagIncluded), ref: all(out.refundable), seats: seats.length ? Math.min(...seats) : null });
  }
  const pax = {}; for (const p of d.listPaxNum || []) if (p && p.paxType) pax[p.paxType] = p.paxNum;
  const t = text(); const num = (re) => { const m = t.match(re); return m ? Number(m[1]) : null; };
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    currency: (d.offers || {}).currency || null, pax, not_available: !!d.notAvailable, flights_total: flights.length, offset: SKIP, flights_in_part: shown.length,
    page_direct: num(/(\d+)\s+direct flights/i), page_connecting: num(/(\d+)\s+connecting flights/i), source, api_note: apiNote, ms: Math.round(performance.now() - t0) }, rows);
})()
