await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  const LIMIT = __LIMIT__; const SKIP = __SKIP__;
  if (/(?<!re)captcha|verify you are human|unusual (traffic|activity)|access denied|blocked by our security/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'SATA shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (location.hostname !== 'book.azoresairlines.pt' || !/\/booking\/flights/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the Azores Airlines flight results page (book.azoresairlines.pt/booking/flights): open the url first' });
  // the page keeps the flights and fares it drew the list from in its own state store (no network call, no cookie): find that store from any element of the page
  const findStore = () => {
    let tried = 0;
    for (const el of document.querySelectorAll('body *')) {
      const key = Object.keys(el).find((k) => k.startsWith('__reactFiber')); if (!key) continue;
      let f = el[key];
      for (let i = 0; i < 900 && f; i++, f = f.return) { const p = f.memoizedProps; if (p && p.store && typeof p.store.getState === 'function') return p.store; }
      if (++tried > 25) break;
    }
    return null;
  };
  const avail = () => { try { const s = findStore(); const A = s && s.getState().Availability; return A && A.status === 'OK' && A.availability && A.availability.bounds ? A : null; } catch (e) { return null; } };
  for (let i = 0; i < 36 && !(avail() && /Prices are per passenger|Not Available|from\s*€/i.test(text())); i++) await wait(1000);
  await wait(1500);
  const A = avail();
  if (!A) return JSON.stringify({ ok: false, error: 'the Azores Airlines flight list is not on the page: still searching, no flights for this search, or a human check: wait and run once more' });
  const av = A.availability; const rb = A.requestBody || {}; const trav = rb.travelers || {}; const b0 = (rb.bounds || [])[0] || {};
  const fam = {}; for (const c of av.cabins || []) for (const f of c.fareFamilies || []) { const ben = {}; for (const x of f.fareBenefits || []) ben[x.code] = x; fam[f.id] = { code: f.code, cabin: c.code, ben }; }
  const short = (b, n) => (b ? `${String(b.value || '').slice(0, n)}${b.inclusionStatus ? ' (' + String(b.inclusionStatus).replace('NOT_INCLUDED', 'not included').toLowerCase() + ')' : ''}` : null);
  const sols = []; const bound = (av.bounds || [])[0] || {};
  for (const sec of bound.sectors || []) for (const s of sec.sectorSolutions || []) {
    const segs = s.segments || []; const opts = [];
    for (const [key, it] of Object.entries(av.itineraryInfoDictionary || {})) {
      const m = key.match(/^(\d+)_(\d+)$/); if (!m || Number(m[1]) !== s.id || !it.totalTripPrice || !(it.totalTripPrice.cash > 0)) continue;
      opts.push({ it, f: fam[Number(m[2])] || { code: 'fare ' + m[2], cabin: null, ben: {} }, total: it.totalTripPrice.cash });
    }
    if (!opts.length) continue;
    opts.sort((a, b) => a.total - b.total);
    // every landing between the first take-off and the last landing counts as a stop, as the page's "N Stops" does: a change of flight AND a technical stop of the same flight number (a segment with 2 legs)
    const legs = segs.flatMap((g) => (g.legs && g.legs.length ? g.legs : [g])); const landings = legs.slice(0, -1).map((l) => l.destinationAirport);
    const tech = segs.reduce((n, g) => n + Math.max((g.legs || []).length - 1, 0), 0);
    sols.push({ s, segs, opts, cheapest: opts[0].total, landings, tech });
  }
  sols.sort((a, b) => a.cheapest - b.cheapest || (a.s.duration || 0) - (b.s.duration || 0));
  const shown = sols.slice(SKIP, SKIP + LIMIT); const rows = [];
  for (const x of shown) for (const [fi, o] of x.opts.entries()) {
    const pt = o.it.totalPricePerPaxType || {}; const n = o.it.numberOfPassengersPerPaxType || {}; const ben = o.f.ben;
    rows.push({ fi, flights: x.segs.map((g) => `${g.marketingAirlineCode}${g.flightNumber}`).join('+'), from: x.s.originAirport, to: x.s.destinationAirport, dep: (x.s.startDate || '').slice(0, 16).replace('T', ' '), arr: (x.s.endDate || '').slice(0, 16).replace('T', ' '),
      mins: x.s.duration ?? null, stops: Math.max(x.landings.length, 0), tech: x.tech, via: x.landings.join(','), fare: o.f.code, cabin: o.f.cabin, total: o.total,
      adt: (pt.ADT || {}).cash ?? null, chd: (pt.CHD || {}).cash ?? null, inf: (pt.INF || {}).cash ?? null, nadt: n.ADT || 0, nchd: n.CHD || 0, ninf: n.INF || 0,
      carry: short(ben.CARRYON_BAGS, 22), bag: short(ben.CHECKED_BAGS, 12), change: short(ben.TICKET_CHANGE_BEFORE_DEPARTURE, 22), refund: short(ben.TICKET_REFUND_BEFORE_DEPARTURE, 22) });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    currency: av.currency || null, searched: { from: b0.origin || null, to: b0.destination || null, day: b0.startDate || null, adults: trav.numberOfAdults ?? null, children: trav.numberOfChildren ?? null, infants: trav.numberOfInfants ?? null, directions: (rb.bounds || []).length },
    no_flight_found: !!A.noFlightFound, flights_total: sols.length, offset: SKIP, flights_in_part: shown.length }, rows);
})()
