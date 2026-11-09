// RateHawk cars: the page's OWN "load more" call, replayed in the page (read only; it clicks and scrolls nothing and books nothing). Run it in the operator's logged-in RateHawk cars results tab once the cars show.
// The cars page is a Next.js page: its first 10 cars are in the page itself and every further batch (and every filter) comes from ONE server action of the page, getFilteredOffers (read live 7 Nov 2026): a POST to
// the page's own address with the header next-action = the action's id (written in the page's cars script: createServerReference("<id>", ..., "getFilteredOffers")) and the body
// [{"filters": {...}, "sessionId": "<the search's session>", "offset": N, "limit": 10}], answered as text/x-component whose line "1:" is {"offers": [...], "count": <all cars of the search: NOT reduced by the filters>}.
// The session id is in the page itself ("sessionId":"<uuid>"). The filters of the page's own boxes are body fields: vehicle_transmission_type ["automatic"] / ["manual"], rate_insurance_type ["zero_excess"],
// pick_up_office_subtype ["in_terminal"] (the call carries only the filters the tool asks for). Checked against the page: the first 30 cars in the same order, 28 of 30 with every field equal (model, gearbox, class, price,
// deposit, excess) and 2 with a trailing space in the model name; the search total is 1,481.
// An offer holds the vehicle (model, SIPP code, category, gearbox, seats, doors, bags), the rate (rental company with its rating, deposit, insurance with the excess, mileage, fuel policy, the cancellation periods with their fees,
// the fees and extras paid on site, the driver's age and licence limits), both offices and total.partner.amount_sell (the price the page shows, service fee included).
// The tool replaces __MAX_CARS__ and __SKIP__ (the window [SKIP, MAX_CARS) of the list) and __FILTERS__ (a JSON list of filter labels). A login page or a refusal stops the script: never worked around.
await (async () => {
  const MAX_CARS = __MAX_CARS__; const SKIP = __SKIP__; const FILTERS = __FILTERS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/(^|\.)ratehawk\.com$/.test(location.hostname) || !/^\/cars\/?$/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a RateHawk cars results page: open the url first' });
  if (/log in|sign in|forgot password/i.test((document.body && document.body.innerText || '').slice(0, 600)) && !(window.dataLayer || []).some((x) => x && x.user_email)) return JSON.stringify({ ok: false, error: 'RateHawk asks to log in: stop and tell the operator to log in (never type a password).' });
  const t0 = performance.now();
  const FILTER_BODY = { 'Automatic': ['vehicle_transmission_type', 'automatic'], 'Manual': ['vehicle_transmission_type', 'manual'], 'Zero excess': ['rate_insurance_type', 'zero_excess'], 'Airport (in the terminal)': ['pick_up_office_subtype', 'in_terminal'] };
  const filters = {};
  for (const label of FILTERS) {
    if (!FILTER_BODY[label]) return JSON.stringify({ ok: false, error: 'the filter "' + label + '" is not one the script can send: ask for it by hand on the page and say so' });
    const [key, value] = FILTER_BODY[label]; (filters[key] = filters[key] || []).push(value);
  }
  let sessionId = null;
  for (let i = 0; i < 60 && !sessionId; i++) {      // the page puts its first cars (and the search's session id) in itself; a search RateHawk has not cached takes its time
    const txt = [...document.scripts].filter((s) => !s.src).map((s) => s.textContent).join('\n');      // inside a self.__next_f.push("...") string the quotes are escaped: \"sessionId\":\"<uuid>\" (checked on the live page, 7 Nov 2026)
    const m = txt.match(/\\?"sessionId\\?":\\?"([0-9a-f]{8}-[0-9a-f-]{27})\\?",\\?"offers\\?":/) || txt.match(/\\?"sessionId\\?":\\?"([0-9a-f]{8}-[0-9a-f-]{27})\\?"/);
    sessionId = m ? m[1] : null;
    if (!sessionId) await wait(500);
  }
  if (!sessionId) return JSON.stringify({ ok: false, error: 'the page has not shown its cars (no search session after 30 s): open the url again, wait until the cars show and run the script once more' });
  const chunk = [...document.scripts].map((s) => s.src).find((u) => /\/_next\/static\/chunks\/app\/cars\/page-[0-9a-f]+\.js/.test(u));
  if (!chunk) return JSON.stringify({ ok: false, error: 'the page\'s cars script was not found (RateHawk changed its page): say it could not be read' });
  let actionId = null;
  try { const m = (await (await fetch(chunk)).text()).match(/createServerReference\)?\(\s*"([0-9a-f]{20,})"[^)]*"getFilteredOffers"/); actionId = m ? m[1] : null; } catch (e) { /* said below */ }
  if (!actionId) return JSON.stringify({ ok: false, error: 'the page\'s "load more" action was not found in its script (RateHawk changed its page): say it could not be read' });
  const call = async (offset) => {
    const ac = new AbortController(); const to = setTimeout(() => ac.abort(), 30000);
    try {
      const res = await fetch(location.pathname + location.search, { method: 'POST', headers: { accept: 'text/x-component', 'next-action': actionId, 'content-type': 'text/plain;charset=UTF-8' }, body: JSON.stringify([{ filters, sessionId, offset, limit: 10 }]), signal: ac.signal });
      const tx = await res.text();
      if (res.status === 401 || res.status === 403 || /captcha|are you a human|access denied/i.test(tx.slice(0, 400))) return { stop: 'RateHawk refused the cars service (HTTP ' + res.status + ': logged out, a human check or a block). Stop: do not retry and do not work around it; tell the operator to look at the page.' };
      if (!res.ok) return { stop: 'RateHawk\'s cars service answered ' + res.status + ': open the url again, wait until the cars show and run the script once more' };
      const line = tx.split('\n').find((l) => l.startsWith('1:'));
      if (!line) return { stop: 'RateHawk\'s cars service answered without a list (' + tx.slice(0, 80).replace(/\s+/g, ' ') + '): open the url again and run the script once more' };
      const j = JSON.parse(line.slice(2));
      if (!Array.isArray(j.offers)) return { stop: 'RateHawk\'s cars service answered without offers: open the url again and run the script once more' };
      return { j };
    } catch (err) { return { stop: 'RateHawk\'s cars service could not be read (' + String(err.name === 'AbortError' ? 'no answer in 30 s' : err.message).slice(0, 60) + '): run the script once more' }; } finally { clearTimeout(to); }
  };
  const base = Math.floor(SKIP / 10) * 10;
  const all = []; let count = null; let lastLen = 0;
  for (let off = base; off < MAX_CARS; off += 10) {
    const got = await call(off);
    if (got.stop) return JSON.stringify({ ok: false, error: got.stop });
    if (count === null) count = got.j.count;      // the whole search's count: it does NOT change with the filters (read live 7 Nov 2026: 1,481 with and without Automatic)
    all.push(...got.j.offers); lastLen = got.j.offers.length;
    if (lastLen < 10) break;
  }
  const num = (x) => (x === null || x === undefined || x === '' ? null : Number(x));
  const rowOf = (o) => {
    const v = o.vehicle || {}; const r = o.rate || {}; const p = (o.total || {}).partner || {}; const pu = (o.pick_up || {}).office || {}; const dof = (o.drop_off || {}).office || {};
    return { model: (v.model || '').trim() || null, sipp: v.sipp_code || null, category: v.category || null, gearbox: v.transmission_type || null, seats: v.seats_number, doors: v.doors_number, ac: v.has_air_conditioning, electric: v.is_electric,
      bags_small: v.small_bags_number, bags_medium: v.medium_bags_number, bags_large: v.large_bags_number,
      company: (r.rental_company || {}).label || null, rating: num((r.rental_company || {}).rating), supplier: (r.supplier || {}).slug || null,
      pickup: { name: pu.name || null, type: pu.type || null, sub: pu.subtype || null, address: pu.address || null, iata: pu.iata_code || null, at: (o.pick_up || {}).date_time || null },
      dropoff: { name: dof.name || null, sub: dof.subtype || null, at: (o.drop_off || {}).date_time || null },
      deposit: r.deposit ? num(r.deposit.amount) : null, ins_type: (r.insurance || {}).type || null, excess_cdw: num((r.insurance || {}).cdw_excess), excess_theft: num((r.insurance || {}).theft_excess),
      mileage: r.mileage, fuel: r.fuel_policy || null,
      cancel: (r.cancellation_policies || []).map((c) => ({ from: c.start_at, to: c.end_at, fee: num(c.amount_penalty), refundable: c.is_refundable })),
      fees: (r.fees || []).map((f) => ({ n: f.label, a: num(f.amount), in: !!f.is_included_in_rate, pay: f.payment, t: f.type })),
      extras: (r.additional_services || []).slice(0, 8).map((f) => ({ n: f.label, a: num(f.amount), in: !!f.is_included_in_rate, pay: f.payment })),
      driver: r.driver_requirements ? { min: r.driver_requirements.minimum_age, max: r.driver_requirements.maximum_age, years: r.driver_requirements.minimum_driving_experience, young: r.driver_requirements.young_driver_age } : null,
      price: num(p.amount_sell), currency: p.currency_code || null, fee_service: num(p.amount_service_fee) };
  };
  const rows = all.slice(SKIP - base, SKIP - base + (MAX_CARS - SKIP)).map(rowOf);
  const q = new URLSearchParams(location.search);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    search: { route: q.get('route'), date: q.get('date'), age: q.get('age'), residency: q.get('residency') }, filters, offset: SKIP, search_total: count, reached_cap: base + all.length >= MAX_CARS && lastLen === 10, ms: Math.round(performance.now() - t0) }, rows);
})()
