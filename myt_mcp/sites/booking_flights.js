// Booking.com flights list reader (comparison only). Run it on any Booking.com flights page (flights.booking.com/flights/...; read only; it books nothing).
// The results page gets its flights from ONE request, GET /api/flights/?type=ONEWAY&adults=N[&children=ages]&cabinClass=..&from=LIS.AIRPORT&to=OPO.AIRPORT&depart=YYYY-MM-DD&sort=BEST|CHEAPEST&currency=EUR[&stops=0][&page=N]
// (15 offers a page; the filters the service takes are stops=0, airlines=TP,FR, depTimeInt=06-11 (departure hours), duration=<max hours> and includedBaggage=CHECKIN; the page's security cookies travel with a request made from the page itself): the script sends that same request from the page for the leg and the group the operator asked for (checked live
// 5 Nov 2026: stops=0 gave exactly the 10 direct flights, children and the business cabin work, pages 2 and 11 follow) and reads every offer as Booking.com's own data: the legs with their flight numbers and carriers, the
// price of the whole group with its list price, base fare and taxes, the price per traveller, what baggage is included (personal item, hand, checked) and which extras are offered. It reads the first PAGES pages of each
// sort (the agency reads Best and Cheapest together), one request at a time with a pause. The tool replaces __REQUEST__ (what to ask).
await (async () => {
  const REQ = __REQUEST__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/flights\.booking\.com$/i.test(location.hostname) || !/^\/flights/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Booking.com flights page (flights.booking.com/flights/...): open the url first' });
  const t0 = performance.now();
  const money = (m) => (m && Number.isFinite(m.units) ? Math.round((m.units + (m.nanos || 0) / 1e9) * 100) / 100 : null);
  const base = new URLSearchParams({ type: 'ONEWAY', adults: String(REQ.adults), cabinClass: REQ.cabin, from: REQ.origin + '.AIRPORT', to: REQ.destination + '.AIRPORT', depart: REQ.day, currency: REQ.currency || 'EUR', enableVI: '1', search_source: 'user' });
  if ((REQ.children_ages || []).length) base.set('children', REQ.children_ages.join(','));
  if (REQ.stops !== null && REQ.stops !== undefined) base.set('stops', String(REQ.stops));
  if ((REQ.airlines || []).length) base.set('airlines', REQ.airlines.join(','));
  if (REQ.dep_hours) base.set('depTimeInt', REQ.dep_hours);
  if (REQ.max_hours) base.set('duration', String(REQ.max_hours));
  if (REQ.checked_bag) base.set('includedBaggage', 'CHECKIN');
  const PER_PAGE = 15;
  const flightIds = (ls) => ls.map((l) => { const fi = l.flightInfo || {}; const ci = fi.carrierInfo || {}; return (ci.marketingCarrier || '') + (fi.flightNumber != null ? fi.flightNumber : ''); });
  const toRow = (o, sort, page) => {
    const pb = o.priceBreakdown || {}; const segs = o.segments || [];
    const legs = segs.map((s) => { const ls = s.legs || [];
      return { dep: (s.departureTime || '').replace('T', ' ').slice(0, 16), from: (s.departureAirport || {}).code || null, from_name: (s.departureAirport || {}).name || null, arr: (s.arrivalTime || '').replace('T', ' ').slice(0, 16), to: (s.arrivalAirport || {}).code || null, to_name: (s.arrivalAirport || {}).name || null,
        mins: Number.isFinite(s.totalTime) ? Math.round(s.totalTime / 60) : null, stops: Math.max(ls.length - 1, 0), tech_stops: ls.reduce((n, l) => n + ((l.flightStops || []).length), 0), flights: flightIds(ls), ops: [...new Set(ls.map((l) => ((l.flightInfo || {}).carrierInfo || {}).operatingCarrier).filter(Boolean))],
        cabins: [...new Set(ls.map((l) => l.cabinClass).filter(Boolean))], via: ls.slice(0, -1).map((l) => (l.arrivalAirport || {}).code).filter(Boolean) }; });
    const ip = ((o.includedProducts || {}).segments || [])[0] || (o.includedProductsBySegment || [])[0] || [];
    const bag = (t) => { const x = ip.find((b) => b.luggageType === t); return x ? { per_pax: x.piecePerPax != null ? x.piecePerPax : null, kg: x.maxWeightPerPiece != null ? x.maxWeightPerPiece : null } : null; };
    const names = [...new Set(segs.flatMap((s) => (s.legs || []).flatMap((l) => (l.carriersData || []).map((c) => c.name))).filter(Boolean))];
    return { sort, page, carriers: names.join(', ') || null, legs, cur: (pb.total || {}).currencyCode || null, total: money(pb.total), list_total: money(pb.totalWithoutDiscount), base: money(pb.baseFare), tax: money(pb.tax), fee: money(pb.fee),
      trav: (o.travellerPrices || []).map((t) => ({ type: t.travellerType || null, total: money((t.travellerPriceBreakdown || {}).total) })), personal_item: !!bag('PERSONAL_ITEM'), hand: bag('HAND'), checked: bag('CHECKED_IN'),
      extras: (o.extraProducts || []).map((e) => e.type).filter(Boolean), flexible_upgrade: (o.extraProducts || []).some((e) => e.type === 'flexibleTicket') };
  };
  const rows = []; const sorts = []; const failed = []; const tokenOf = new Map(); let agg = null; let searchId = null; let source = null; let cabinBack = null; let directIgnored = false;
  for (const sort of REQ.sorts) {
    let read = 0; let seen = 1;
    for (let p = 1; p <= REQ.pages; p++) {
      const q = new URLSearchParams(base); q.set('sort', sort.key); if (p > 1) q.set('page', String(p));
      let j;
      try {
        const res = await fetch('/api/flights/?' + q.toString(), { credentials: 'same-origin', headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error('answered ' + res.status);
        j = await res.json();
      } catch (err) { failed.push(sort.label + ' page ' + p + ': ' + String(err.message || err).slice(0, 60)); break; }
      if (!j || !Array.isArray(j.flightOffers)) { failed.push(sort.label + ' page ' + p + ': no flight list in the answer'); break; }
      if (!agg) { agg = j.aggregation || {}; searchId = j.searchId || null; source = j.source || null; cabinBack = (j.searchCriteria || {}).cabinClass || null; directIgnored = !!(j.displayOptions && j.displayOptions.directFlightsOnlyFilterIgnored); }
      read++; for (const o of j.flightOffers) { const row = toRow(o, sort.label, p); rows.push(row); tokenOf.set(row, o.token); }
      const filtered = Number((j.aggregation || {}).filteredTotalCount); seen = Number.isFinite(filtered) ? Math.max(Math.ceil(filtered / PER_PAGE), 1) : seen;
      if (j.flightOffers.length < PER_PAGE || p >= seen) break;
      await wait(600);
    }
    sorts.push({ sort: sort.label, pages_read: read, pages_seen: seen });
    await wait(600);
  }
  // the details of an offer (GET /api/flight/<offer token>, what "View details" opens): its fare name, the rules per segment (change / cancel before departure), the fare's features (bags, refundable, changeable, seat ...)
  // and EVERY fare option of the same flight with its price for the group (the airline's own fare ladder: Discount, Classic, Plus ...). Read for the cheapest flights only, one request at a time with a pause.
  const wantDetails = Math.max(0, Math.min(10, REQ.details == null ? 5 : REQ.details)); const detailFailed = []; let detailsRead = 0;
  const ofFeature = (info) => ((info || {}).features || []).map((f) => ({ n: f.featureName, a: f.availability }));
  const has = (feats, name) => feats.some((f) => f.n === name && f.a === 'INCLUDED');
  const policy = (rules, type) => { const segs = (rules && rules.perSegment) || []; if (!segs.length) return null; if (segs.every((x) => (x.availablePolicies || []).some((p) => p.type === type))) return true; if (segs.some((x) => (x.unavailablePolicies || []).some((p) => p.type === type))) return false; return null; };
  const cheapest = [...new Set([...rows].sort((a, b) => (a.total == null ? 1e12 : a.total) - (b.total == null ? 1e12 : b.total)).map((r) => tokenOf.get(r)).filter(Boolean))].slice(0, wantDetails);
  for (const tok of cheapest) {
    await wait(600);
    try {
      const res = await fetch('/api/flight/' + tok + '?' + base.toString(), { credentials: 'same-origin', headers: { Accept: 'application/json' } });      // without the search parameters the service answers SEARCH_GETFLIGHTDETAILS_INVALID in a fresh browser (read live 5 Nov 2026)
      if (!res.ok) throw new Error('answered ' + res.status);
      const d = await res.json();
      if (!d || d.error || !d.brandedFareInfo) throw new Error('details service: ' + String((d && d.error && d.error.code) || 'no fare details').slice(0, 40));
      const feats = ofFeature(d.brandedFareInfo);
      const detail = { fare: (d.brandedFareInfo || {}).fareName || null, features: feats, change: policy(d.fareRules, 'CHANGE_BEFORE'), cancel: policy(d.fareRules, 'CANCEL_BEFORE'), no_flex: d.noFlexOrCfarContent ? { title: d.noFlexOrCfarContent.title || null, excluded: d.noFlexOrCfarContent.excludedFeatures || [] } : null,
        options: (d.brandedFareOffers || []).map((b) => { const f = ofFeature(b.brandedFareInfo); return { name: (b.brandedFareInfo || {}).fareName || null, total: money((b.priceBreakdown || {}).total), checked_bag: has(f, 'CHECK_BAGGAGE'), refundable: has(f, 'REFUNDABLE_TICKET'), changeable: has(f, 'CHANGEABLE_TICKET'), seat: has(f, 'PREMIUM_SEAT'), fast_track: has(f, 'FAST_TRACK') }; }),
        baggage_url: ((d.baggagePolicies || [])[0] || {}).url || null };
      for (const r of rows) if (tokenOf.get(r) === tok) r.detail = detail;
      detailsRead++;
    } catch (err) { detailFailed.push(String(err.message || err).slice(0, 60)); }
  }
  if (!agg) return JSON.stringify({ ok: false, error: 'Booking.com\'s flights service gave no flight list (' + (failed[0] || 'no answer') + '): say it could not be read' });
  const noDirect = REQ.stops === 0 && directIgnored;      // Booking.com says itself that it ignored the direct-only filter because the route has no direct flight (read live 5 Nov 2026: Lisbon - Sydney)
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    searched: { type: 'ONEWAY', origin: REQ.origin, destination: REQ.destination, day: REQ.day, adults: REQ.adults, children: (REQ.children_ages || []).length, cabin: REQ.cabin, currency: REQ.currency || 'EUR', stops: REQ.stops === null || REQ.stops === undefined ? null : String(REQ.stops), airlines: REQ.airlines || [], dep_hours: REQ.dep_hours || null, max_hours: REQ.max_hours || null, checked_bag: !!REQ.checked_bag },
    cabin_back: cabinBack, results_total: Number.isFinite(Number(agg.filteredTotalCount)) ? Number(agg.filteredTotalCount) : null, unfiltered_total: Number.isFinite(Number(agg.totalCount)) ? Number(agg.totalCount) : null,
    stops_available: (agg.stops || []).map((s) => ({ n: s.numberOfStops, count: s.count, from: money(s.minPrice) })), airlines_available: (agg.airlines || []).map((a) => ({ code: a.code || a.iataCode || null, name: a.name || null, count: a.count != null ? a.count : null })).slice(0, 12),
    baggage_counts: (agg.baggage || []).map((b) => ({ type: b.baggageType, count: b.count })), sorts, no_direct_notice: noDirect, search_id: searchId, source, failed: failed.length ? failed : null, details_read: detailsRead, details_failed: detailFailed.length ? detailFailed : null, ms: Math.round(performance.now() - t0) }, rows);
})()
