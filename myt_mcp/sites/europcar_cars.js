// Europcar car list reader (www.europcar.com/en-us/reservation/vehicles). Run it in the operator's Chrome on the results tab the recipe opened (read only).
// The page loads its cars with ONE request to Europcar's own offers service (GET .../group-direct-channel-context/v1/offers?apikey=...&pickup-station-code=...&driver-age=...&limit=...&offset=...):
// the script finds that request in the page's own network log and sends it again from the same page (same site, the page's own key, nothing sent elsewhere), 50 cars at a time, with the filters the operator asked for
// (`filter=feature:contains:AUTOMATIC,seats:gte:5`: the site narrows the list). It reads every car with its prices in the station's currency and in the driver's, excess, fuel policy, mileage, cancellation and
// minimum age as the site's own data, not as text off cards, and needs no scrolling. It never presses Select and books nothing. The tool replaces __EXPECT__ (what the address asked for, and `filters`).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/\/reservation\/vehicles/i.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the Europcar vehicle list: open the url first' });
  const entry = async () => { for (let i = 0; i < (typeof API_TRIES !== 'undefined' ? API_TRIES : 60); i++) { const e = performance.getEntriesByType('resource').find((x) => /group-direct-channel-context\/v1\/offers\?/.test(x.name)); if (e) return e; await wait(500); } return null; };
  const e = await entry();
  if (!e) return JSON.stringify({ ok: false, error: 'the page has not made its offers request (still loading, a check page or a block): never say sold out, say it could not be read' });
  const base = new URL(e.name, location.href);
  const p = base.searchParams;
  const q = new URLSearchParams(location.search);
  const form = { pickup_station: p.get('pickup-station-code'), dropoff_station: p.get('drop-off-station-code'), pickup_when: (p.get('pickup-date') || '').replace('T', ' '), dropoff_when: (p.get('drop-off-date') || '').replace('T', ' ') };
  const age = parseInt(p.get('driver-age') || '', 10) || null; const residency = p.get('country-of-residence') || null;
  const problems = [];
  if (EXPECT.age && age !== EXPECT.age) problems.push('driver age ' + age + ' instead of ' + EXPECT.age);
  if (EXPECT.residency && residency !== EXPECT.residency) problems.push('residency ' + residency + ' instead of ' + EXPECT.residency);
  if (EXPECT.pickup_when && form.pickup_when !== EXPECT.pickup_when) problems.push('pick-up ' + form.pickup_when + ' instead of ' + EXPECT.pickup_when);
  if (EXPECT.dropoff_when && form.dropoff_when !== EXPECT.dropoff_when) problems.push('return ' + form.dropoff_when + ' instead of ' + EXPECT.dropoff_when);
  if (EXPECT.pickup_station && form.pickup_station !== EXPECT.pickup_station) problems.push('pick-up station ' + form.pickup_station + ' instead of ' + EXPECT.pickup_station);
  if (EXPECT.dropoff_station && form.dropoff_station !== EXPECT.dropoff_station) problems.push('return station ' + form.dropoff_station + ' instead of ' + EXPECT.dropoff_station);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form, age, residency });
  const wanted = typeof EXPECT.filter === 'string' ? EXPECT.filter : '';
  const get = async (offset) => {
    const u = new URL(base); u.searchParams.set('limit', '50'); u.searchParams.set('offset', String(offset)); u.searchParams.delete('filter');
    if (wanted) u.searchParams.set('filter', wanted);
    const res = await fetch(u.toString());
    let j = null; try { j = await res.json(); } catch (err) { /* a body that is not JSON is reported by the status */ }
    if (!res.ok) { const m = j && (j.message || j.label) ? String(j.message || j.label).slice(0, 160) : 'no message'; const c = j && j.code ? ' ' + j.code : ''; const err = new Error('Europcar\'s offers service answered ' + res.status + c + ': ' + m); err.status = res.status; err.code = j && j.code; throw err; }
    return j;
  };
  const all = []; let first = null; let total = null; let unfiltered = null;
  try {
    for (let offset = 0; offset < 1000; offset += 50) {
      const j = await get(offset);
      if (!first) { first = j; total = (j.pagination || {}).total; unfiltered = (j.pagination || {}).totalWithoutFilter; }
      const part = j.data || []; all.push(...part);
      if (!part.length || all.length >= (Number.isInteger(total) ? total : all.length)) break;
    }
  } catch (err) { return JSON.stringify({ ok: false, error: String(err.message || err).slice(0, 220), http_status: err.status || null, code: err.code || null, form, age, residency }); }
  const meta = (first && first.meta) || {};
  const rows = [];
  for (const o of all) {
    const car = o.car || {};
    for (const r of o.rates || []) {
      const pkgs = ((r.ancillaries || {}).packages || []).map((x) => ({ code: x.code, level: x.level, excess: (x.excessInDestinationCurrency || {}).amount, excess_cur: (x.excessInDestinationCurrency || {}).currency, excess_customer: (x.excessInCustomerCurrency || {}).amount, excess_customer_cur: (x.excessInCustomerCurrency || {}).currency }));
      const pol = r.policies || {}; const mil = pol.mileage || {}; const dest = r.priceInDestinationCurrency || {}; const cust = r.priceInCustomerCurrency || {};
      rows.push({ car: car.model || null, acriss: car.acriss || null, category: car.category || null, segments: (car.segments || []).map((s) => s.code), features: (car.features || []).map((f) => f.code),
        seats: (car.capacity || {}).seats, bags: (car.capacity || {}).luggages, bag_items: (car.capacity || {}).luggageItems, doors: car.doors, ac: car.airConditioning, automatic: (car.engine || {}).automatic, fuel_type: (car.engine || {}).fuel || null,
        model_guaranteed: car.modelGuaranteed, premium_brand: car.premiumBrandGuaranteed,
        total: dest.amount, per_day: dest.amountPerDay, cur: dest.currency, total_customer: cust.amount, per_day_customer: cust.amountPerDay, cur_customer: cust.currency,
        pay: r.type || null, brand: r.brand || null, discount: (r.discount || {}).type || null, min_age: r.minimumDriverAgeRequired, packages: pkgs, upgrades: ((r.ancillaries || {}).standalones || []).map((x) => x.code),
        surcharges: ((r.ancillaries || {}).surcharges || []).length, fuel_policy: pol.fuel || null, mileage_unlimited: mil.isUnlimited, mileage_included: mil.included, mileage_per_day: mil.includedPerDay, mileage_unit: mil.unit || null,
        cancellation_fees: (pol.cancellationFees || []).length, confirmation: pol.bookingConfirmation || null });
    }
  }
  if (!rows.length && !wanted) return JSON.stringify({ ok: false, error: 'the offers answer holds no cars: never say sold out, say it could not be read', form, age, residency });
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, age, residency, days: meta.durationInDays || null, young_driver_fee: meta.youngDriverSurchargeApplied === true, currencies: meta.currencies || null, filter_sent: wanted || null,
    total: Number.isInteger(total) ? total : rows.length, unfiltered_total: Number.isInteger(unfiltered) ? unfiltered : null, complete: Number.isInteger(total) ? all.length >= total : null, cars_read: rows.length }, rows);
})()
