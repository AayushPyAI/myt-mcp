await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  const LIMIT = __LIMIT__; const SKIP = __SKIP__;
  if (/(?<!re)captcha|verify you are human|unusual (traffic|activity)|access denied|blocked by our security/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'TAP shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (location.hostname !== 'booking.flytap.com' || !/\/booking\/flights/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the TAP flight results page (booking.flytap.com/booking/flights): open the url first' });
  // the page keeps the availability answer it drew the list from in its own session storage (no network call, no cookie)
  const read = () => { try { const a = JSON.parse(sessionStorage.getItem('airportTranslationData') || 'null'); return a && a.data && Array.isArray(a.data.listOutbound) ? a : null; } catch (e) { return null; } };
  const NONE = /No flights available on[^\n]*/i;   // the page says it itself; the tool that runs this script gives up after 45 s, so the wait stops at about 38 s
  for (let i = 0; i < 36 && !(read() && /flights? found|direct flights|connecting flights/i.test(text())) && !(NONE.test(text()) && !read()); i++) await wait(1000);
  await wait(1500);
  const ans = read();
  if (!ans && NONE.test(text())) return JSON.stringify({ ok: false, error: 'TAP itself says: "' + text().match(NONE)[0].trim() + '". TAP has no flight on this leg that day: report that, do not retry; look at other days (tap_fare_calendar) or the other sources.' });
  if (!ans) return JSON.stringify({ ok: false, error: 'the TAP flight list is not on the page: still searching, no flights for this search, or a human check: wait and run once more' });
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
    page_direct: num(/(\d+)\s+direct flights/i), page_connecting: num(/(\d+)\s+connecting flights/i) }, rows);
})()
