// Booking.com attractions: ONE activity's price for a date and a group (comparison only). Run it on the activity's page (www.booking.com/attractions/<country>/<slug>.html; read only; it books nothing).
// The page's ticket box gets its tickets, prices and time slots from ONE GraphQL request, operation GetAvailability at accommodations.booking.com/dml/graphql (input: the date, the product id, includeSoldOut) and works out the
// Total of the group itself from the price of each kind of ticket (checked live 5 Nov 2026: 2 adults + 1 child on 18 Dec, the page's Total 77.50 = 2 x 29.90 + 17.70 from the service). The script sends that same request with a
// compact query for just the fields it needs, for the date the operator asked (no date picker and no stepper is touched), puts each traveller in the kind of ticket whose age range holds their age (the adults in "Adult"),
// and adds the group's price up for every ticket offer and every time slot. The product's own data (what is included, the operator, the meeting address) is in the page's embedded Apollo store
// (<script data-capla-store-data="apollo">: getProduct). It never presses Next. The tool replaces __REQUEST__ (the activity, the day, the travellers).
await (async () => {
  const REQ = __REQUEST__;
  const text = () => (document.body && document.body.innerText) || '';
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  const where = location.pathname.match(/^\/attractions\/([a-z]{2})\/([a-z0-9-]+?)(?:\.[a-z-]+)?\.html$/);
  if (!/(^|\.)booking\.com$/i.test(location.hostname) || !where) return JSON.stringify({ ok: false, error: 'not a Booking.com activity page (www.booking.com/attractions/pt/<slug>.html): open the url first' });
  const t0 = performance.now();
  const el = document.querySelector('script[data-capla-store-data="apollo"]');
  let store = null; try { store = el ? JSON.parse(el.textContent) : null; } catch (err) { store = null; }
  const root = store && store.ROOT_QUERY && store.ROOT_QUERY.attractionsProduct;
  const pk = root && Object.keys(root).find((k) => k.startsWith('getProduct:'));
  const deref = (x) => { if (Array.isArray(x)) return x.map(deref); if (x && typeof x === 'object') { if (x.__ref) return deref(store[x.__ref]); const o = {}; for (const [k, v] of Object.entries(x)) if (k !== '__typename') o[k] = deref(v); return o; } return x; };
  const product = pk ? deref(root[pk]) : null;
  if (!product || !product.id) return JSON.stringify({ ok: false, error: 'the page has no activity data (Booking.com changed its page or it is not loaded yet): say it could not be read' });
  if (REQ.slug && where[2] !== REQ.slug) return JSON.stringify({ ok: false, error: 'the page is the activity \'' + where[2] + '\', not \'' + REQ.slug + '\': open the url again' });
  const params = new URLSearchParams(location.search);
  const html = document.documentElement.innerHTML; const grab = (re) => (html.match(re) || [])[1] || null;
  const headers = { accept: '*/*', 'content-type': 'application/json', 'x-booking-site-type-id': '1', 'x-booking-context-action': 'attractions', 'x-booking-context-action-name': 'attractions', 'x-booking-topic': 'capla_browser_b-attractions-product-frontend-capla' };
  if (grab(/"csrfToken":"([^"]+)"/)) headers['x-booking-csrf-token'] = grab(/"csrfToken":"([^"]+)"/);
  if (grab(/"pageviewId":"([^"]+)"/)) headers['x-booking-pageview-id'] = grab(/"pageviewId":"([^"]+)"/);
  if (params.get('aid')) headers['x-booking-context-aid'] = params.get('aid');
  const endpoint = new URL('https://accommodations.booking.com/dml/graphql'); ['aid', 'label', 'selected_currency'].forEach((k) => { if (params.get(k)) endpoint.searchParams.set(k, params.get(k)); }); endpoint.searchParams.set('date', REQ.day); endpoint.searchParams.set('lang', 'en-gb');
  const contextParams = { requestUrl: location.origin + location.pathname, urlCode: '', test: false, showInactive: false, source: '', adPlat: '', label: params.get('label') || '' };
  const QUERY = 'query GetAvailability($input: AttractionAvailabilityInput!, $contextParams: AttractionsContextParamsInput) { attractionsProduct { getAvailability(input: $input, contextParams: $contextParams) { ... on AttractionAvailabilityResponse { timeslots { timeSlotId startTime startDate reservableUntil unitsAvailable availabilityState timeSlotOffers { id label availabilityType reservationRestrictions { adultRequiredForReservation maxOfferItemsPerReservation minOfferItemsPerReservation } items { id offerItemId type label isAdultLike unitsRequired minPerReservation maxPerReservation ticketsAvailable constraint { label minAge maxAge type } price { chargeAmount currency publicAmount discounts { __typename } } cancellationPolicy { comparedTo hasFreeCancellation isStillRefundable label message percentage period until } } } } } } } }';
  let slots;
  try {
    const res = await fetch(endpoint.toString(), { method: 'POST', credentials: 'include', headers, body: JSON.stringify({ operationName: 'GetAvailability', variables: { input: { date: REQ.day, id: product.id, urlCode: '', includeSoldOut: true }, contextParams }, extensions: {}, query: QUERY }) });
    if (!res.ok) throw new Error('answered ' + res.status);
    const j = await res.json();
    if (j.errors && j.errors.length) throw new Error(String(j.errors[0].message || 'query refused').slice(0, 80));
    const ga = j && j.data && j.data.attractionsProduct && j.data.attractionsProduct.getAvailability;
    if (!ga || !Array.isArray(ga.timeslots)) throw new Error('no time slots in the answer');
    slots = ga.timeslots;
  } catch (err) { return JSON.stringify({ ok: false, error: 'Booking.com\'s availability service could not be read (' + String(err.message || err).slice(0, 80) + '): say it could not be read' }); }
  const holds = (c, age) => !!c && (c.minAge == null || age >= c.minAge) && (c.maxAge == null || age <= c.maxAge);
  const round2 = (n) => Math.round(n * 100) / 100;
  const offerIds = []; const offers = {};
  for (const s of slots) for (const o of s.timeSlotOffers || []) { if (!offers[o.id]) { offers[o.id] = { o, slots: [] }; offerIds.push(o.id); } offers[o.id].slots.push({ s, o }); }
  const staticOffers = {}; for (const o of product.offers || []) staticOffers[o.id] = o;
  const rows = [];
  // an offer can hold the same kind of ticket many times (read live 5 Nov 2026: five identical Adult items for a group tour, forty for a private tour whose price per person depends on the group size: one Adult item
  // per size with min = max per booking, 450 for 1, 225 each for 2, 150 each for 3 ... 56.25 each for 8). The item of a kind is the first whose per-booking limits hold the number of travellers of that kind.
  const pick = (items, type, n) => (items || []).find((k) => k.type === type && (k.minPerReservation == null || n >= k.minPerReservation) && (k.maxPerReservation == null || n <= k.maxPerReservation)) || null;
  for (const id of offerIds) {
    const first = offers[id].o; const kinds = first.items || [];
    const want = new Map(); const unfit = [];
    const adultKind = kinds.find((k) => k.type === 'adult') || kinds.find((k) => k.isAdultLike);
    if (REQ.adults) { if (adultKind) want.set(adultKind.type, (want.get(adultKind.type) || 0) + REQ.adults); else unfit.push('adult'); }
    for (const age of REQ.ages || []) { const k = kinds.find((x) => holds(x.constraint, age)); if (k) want.set(k.type, (want.get(k.type) || 0) + 1); else unfit.push(String(age)); }
    const slotRows = offers[id].slots.map(({ s, o }) => {
      let total = 0; let ok = s.availabilityState === 'available'; const why = [];
      for (const [type, n] of want) {
        const k = pick(o.items, type, n);
        if (!k) { ok = false; const any = (o.items || []).find((x) => x.type === type); why.push((any ? any.label : type) + ': no ticket takes ' + n + ' in one booking'); continue; }
        total += n * (k.price && Number.isFinite(k.price.chargeAmount) ? k.price.chargeAmount : 0);
        if (n > (k.ticketsAvailable == null ? 1e9 : k.ticketsAvailable)) { ok = false; why.push('only ' + k.ticketsAvailable + ' ' + k.label + ' left'); }
      }
      return { time: s.startTime || null, total: round2(total), state: s.availabilityState || null, units: s.unitsAvailable != null ? s.unitsAvailable : null, until: s.reservableUntil || null, bookable: ok, why };
    });
    const used = [...want].map(([type, n]) => { const k = pick(kinds, type, n) || kinds.find((x) => x.type === type) || {}; return { type, label: k.label || type, count: n, price: k.price ? k.price.chargeAmount : null, public_price: k.price ? k.price.publicAmount : null, constraint: k.constraint ? k.constraint.label : null, discounted: !!(k.price && (k.price.discounts || []).length) }; });
    const adultPick = adultKind ? pick(kinds, adultKind.type, want.get(adultKind.type) || 1) || adultKind : null;
    const pol = (adultPick && adultPick.cancellationPolicy) || (kinds[0] && kinds[0].cancellationPolicy) || {};
    const st = staticOffers[id] || {}; const cur = (kinds.find((k) => k.price) || {}).price;
    const bookable = slotRows.filter((r) => r.bookable);
    const totals = [...new Set(slotRows.map((r) => r.total))];
    rows.push({ offer_id: id, ticket: first.label || null, availability_type: first.availabilityType || null, cur: cur ? cur.currency : null, kinds: used, unfit, total: (bookable[0] || slotRows[0] || {}).total, totals_differ: totals.length > 1, slots: slotRows,
      adult_required: !!(first.reservationRestrictions && first.reservationRestrictions.adultRequiredForReservation),
      cancel: { free: pol.hasFreeCancellation === true, refundable_now: pol.isStillRefundable === true, label: pol.label || null, until: pol.until || null, period: pol.period || null, percentage: pol.percentage != null ? pol.percentage : null },
      includes: Array.isArray(st.whatsIncluded) ? st.whatsIncluded.join('; ') : (st.whatsIncluded || null), not_included: Array.isArray(st.notIncluded) ? st.notIncluded.join('; ') : (st.notIncluded || null) });
  }
  const flat = (v) => (Array.isArray(v) ? v.join('; ') : (typeof v === 'string' ? v : null));
  const addr = ((product.addresses || {}).attraction || [])[0] || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    path: location.pathname, slug: where[2], country: where[1], activity: product.name || document.title, product_id: product.id, operated_by: typeof product.operatedBy === 'string' ? product.operatedBy : null, day: REQ.day, travellers: { adults: REQ.adults, ages: REQ.ages || [] },
    duration: product.duration && product.duration.label ? String(product.duration.label).replace(/^Duration:\s*/i, '') : null, duration_iso: product.duration ? product.duration.value || null : null,
    currency: params.get('selected_currency') || null, slots_total: slots.length, includes: flat(product.whatsIncluded), not_included: flat(product.notIncluded), additional: typeof product.additionalInfo === 'string' ? product.additionalInfo.replace(/\s+/g, ' ').trim().slice(0, 600) : null,
    meeting: addr ? [addr.address, addr.city].filter(Boolean).join(', ') : null, unavailable: slots.length ? null : 'Booking.com lists no time slot on ' + REQ.day, ms: Math.round(performance.now() - t0) }, rows);
})()
