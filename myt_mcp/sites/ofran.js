// Ofran car rental reader (the agency's own logged-in Ofran). Run it on ANY ofran.co.il page of the operator's logged-in Chrome (read only, no form to fill, no results page needed).
// Ofran's own pages get their cars with ONE request, POST /api/get_full_dynamic_result?order_uuid=<any new uuid> (body: CountryId, PickupIataId, PickupDate "08.03.2027", PickupHour "17:00", DropoffIataId,
// DropoffDate, DropoffHour, Age, GoTos): the script sends that same request from the page (same site, the agent's login cookie, nothing sent elsewhere) and reads every car with its supplier, ACRISS code,
// seats, doors, price after the agent discount, list price, excess, deposit and one-way fee as the site's own data, not as text off cards. The place is found in the site's own list (GET /api/locations).
// The page may be in Hebrew or English (the plan names and error texts follow it): nothing here depends on the language. The site's filter boxes (gearbox, excess, station) work in the page only: the server judges every wish on these rows. It books nothing and never presses "I took it".
// The tool replaces __REQUEST__ (what to search).
await (async () => {
  const REQ = __REQUEST__;
  if (!/(^|\.)ofran\.co\.il$/.test(location.host)) return JSON.stringify({ ok: false, error: 'not an Ofran page: open https://ofran.co.il/ in the operator\'s logged-in Chrome first' });
  const pageText = document.body ? document.body.innerText : '';
  if (/Access Denied/i.test(pageText) && pageText.length < 200) return JSON.stringify({ ok: false, error: 'Ofran answers "Access Denied" to this Chrome (it refuses some countries: the operator needs the VPN on in this Chrome): never work around it, tell the operator' });
  const first = (v) => (Array.isArray(v) ? v[0] : v);
  const KINDS = { 1: 'airport', 2: 'city', 3: 'railway', 4: 'other' };
  const EXONYMS = { florence: 'firenze', rome: 'roma', milan: 'milano', venice: 'venezia', naples: 'napoli', turin: 'torino', genoa: 'genova', munich: 'münchen', cologne: 'köln', vienna: 'wien', prague: 'praha', lisbon: 'lisboa', seville: 'sevilla', athens: 'athina', copenhagen: 'københavn' };
  let places;
  try {
    const r = await fetch('/api/locations', { credentials: 'same-origin' });
    if (!r.ok) return JSON.stringify({ ok: false, error: 'Ofran\'s place list answered ' + r.status + ': say it could not be read' });
    const raw = await r.json();
    places = (Array.isArray(raw) ? raw : []).filter((x) => x && first(x.field_type) === 'iata' && first(x.description) && first(x.field_id) && first(x.field_country_id)).map((x) => ({
      name: first(x.description), code: first(x.name) || '', kind: KINDS[first(x.field_iata_code_type_id)] || 'other', country_id: String(first(x.field_country_id)), iata_id: String(first(x.field_id)), preferred: first(x.field_preferred) === '1',
      aliases: (x.field_alternate_names || []).filter((a) => typeof a === 'string' && a) }));
  } catch (err) { return JSON.stringify({ ok: false, error: 'Ofran\'s place list could not be read (' + String(err).slice(0, 60) + ')' }); }
  if (!places.length) return JSON.stringify({ ok: false, error: 'Ofran\'s place list came back empty (logged out or the site changed): say it could not be read' });
  const find = (query) => {            // the same ranking as the server's LocationIndex: exact code, name starts with, name contains, alias contains; airports and preferred places first
    const q = String(query || '').toLowerCase().split(/\s+/).filter(Boolean).join(' ');
    if (!q) return [];
    const variants = [q, ...Object.entries(EXONYMS).filter(([en]) => q.includes(en)).map(([en, local]) => q.split(en).join(local))];
    const ranked = [];
    for (const p of places) {
      const code = p.code.toLowerCase(); const name = p.name.toLowerCase(); const aliases = p.aliases.map((a) => a.toLowerCase());
      let rank;
      if (variants.includes(code)) rank = 0; else if (variants.some((v) => name.startsWith(v))) rank = 1; else if (variants.some((v) => name.includes(v))) rank = 2; else if (variants.some((v) => aliases.some((a) => a.includes(v)))) rank = 3; else continue;
      ranked.push([rank, p.kind !== 'airport', !p.preferred, p.name, p]);
    }
    ranked.sort((a, b) => a[0] - b[0] || Number(a[1]) - Number(b[1]) || Number(a[2]) - Number(b[2]) || (a[3] < b[3] ? -1 : a[3] > b[3] ? 1 : 0));
    return ranked.map((x) => x[4]);
  };
  const pick = find(REQ.pickup); const drop = REQ.dropoff ? find(REQ.dropoff) : pick;
  const short = (p) => ({ name: p.name, code: p.code, kind: p.kind, country_id: p.country_id });
  if (!pick.length || !drop.length) return JSON.stringify({ ok: false, error: 'Ofran has no place matching "' + (!pick.length ? REQ.pickup : REQ.dropoff) + '": ask the operator for the airport or station name as Ofran writes it', needs_place: true });
  const a = pick[0]; const b = REQ.dropoff ? drop[0] : a;
  const dmy = (iso) => iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4);
  const body = { CountryId: a.country_id, PickupIataId: a.iata_id, PickupDate: dmy(REQ.pickup_date), PickupHour: REQ.pickup_time, DropoffIataId: b.iata_id, DropoffDate: dmy(REQ.dropoff_date), DropoffHour: REQ.dropoff_time,
    Age: REQ.age ? String(REQ.age) : '', GoTos: { Countries: [] } };
  const t0 = performance.now();
  let data;
  try {
    const res = await fetch('/api/get_full_dynamic_result?order_uuid=' + (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + '-' + Math.random().toString(16).slice(2)),
      { method: 'POST', headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-cache' }, body: JSON.stringify(body), credentials: 'same-origin' });
    if (!res.ok) return JSON.stringify({ ok: false, error: 'Ofran\'s search answered ' + res.status + ' (' + (res.status === 403 ? 'blocked: the VPN or the login' : 'say it could not be read') + ')' });
    data = await res.json();
  } catch (err) { return JSON.stringify({ ok: false, error: 'Ofran\'s search could not be read (' + String(err).slice(0, 60) + ')' }); }
  const ms = Math.round(performance.now() - t0);
  if (!data || typeof data !== 'object') return JSON.stringify({ ok: false, error: 'Ofran\'s search answer had an unexpected format: say it could not be read' });
  const errs = Array.isArray(data.errors) ? data.errors : (data.errors ? [data.errors] : []);
  if (errs.length) return JSON.stringify({ ok: false, error: 'Ofran could not run this search (its own message, the answer still said 200): ' + JSON.stringify(errs).slice(0, 200) });
  if (data.result !== null && data.result !== undefined && !Array.isArray(data.result)) return JSON.stringify({ ok: false, error: 'Ofran\'s search answer had an unexpected format: say it could not be read' });
  const items = data.result || [];
  const asList = (v) => (Array.isArray(v) ? v : v ? [v] : []);
  const rows = [];
  for (const it of items) {
    const g = it && it.cargroup; const cs = it && it.contracts;
    if (!g || !Array.isArray(cs)) continue;
    for (const c of cs) {
      if (!c || c.nettotal === undefined || c.nettotal === null || c.nettotal === '') continue;
      rows.push({ supplier: g.suppliername || null, supplier_score: g.SupplierRating || null, size: g.ofranCarGroupName || null, acriss: g.sippcode || null, car: g.carmodel || null, seats: g.reccnumofadults || null, kids: g.reccnumofkids || null,
        doors: g.numdoors || null, suitcases: g.reccnumofsuitcases || null, handbags: g.reccnumofhandbags || null, station_type: ((g.Filters || {}).StationType || {}).StationTypeName || null,
        price: c.nettotal, price_before: c.OfflineRate || null, currency: c.currency || null, package: c.contractname || null, live_rate: c.IsLiveRate === 'true' || c.IsLiveRate === true,
        cdw_excess: c.CDWExcess === undefined ? null : c.CDWExcess, theft_excess: c.TPExcess === undefined ? null : c.TPExcess, deposit: c.Deposit === undefined ? null : c.Deposit, excess_currency: c.PolicyCurrency || null,
        one_way_fee: (Array.isArray(c.OneWayFee) ? c.OneWayFee.length : c.OneWayFee) ? (typeof c.OneWayFee === 'object' ? JSON.stringify(c.OneWayFee).slice(0, 160) : String(c.OneWayFee)) : null,
        extras: asList(((c.AdditionalProducts || {}).Products || {}).AdditionalProduct).map((e) => ({ name: e.Name || null, price: e.RateInReservationPQCurrency || null, currency: e.ReservationPQCurrencyCode || null })) });
    }
  }
  rows.sort((x, y) => parseFloat(x.price) - parseFloat(y.price));
  const SKIP = REQ.skip || 0; const LIMIT = REQ.limit || 30;
  const OUT = /התנתקות|\blog\s?out\b/i; const seesOut = () => OUT.test(document.body.innerText || ''); for (let i = 0; i < 16 && !seesOut(); i++) await new Promise((r) => setTimeout(r, 500)); const account = seesOut();
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form: { pickup_place: a.name + ' (' + a.code + ')', dropoff_place: b.name + ' (' + b.code + ')', pickup_when: dmy(REQ.pickup_date).slice(0, 6) + REQ.pickup_date.slice(2, 4) + ' | ' + REQ.pickup_time,
      dropoff_when: dmy(REQ.dropoff_date).slice(0, 6) + REQ.dropoff_date.slice(2, 4) + ' | ' + REQ.dropoff_time, age: REQ.age ? String(REQ.age) : null },
    other_places: pick.slice(1, 4).map(short), logged_in: account, diag: account ? null : { page: location.origin + location.pathname, title: (document.title || '').slice(0, 80), text_start: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 200), login_link: /התחברות|\blog\s?in\b|\blogin\b/i.test(document.body.innerText || '') }, cars_total: rows.length, offset: SKIP, ms, settled: true }, rows.slice(SKIP, SKIP + LIMIT));
})()
