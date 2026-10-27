// Rentalcars.com (by Booking.com) car list reader. Run it in the operator's Chrome on the results tab the recipe opened (read only).
// The page loads its cars with ONE request to its own server (GET /api/search-results?searchCriteria=...): the script finds that request in the page's own network log and reads it again from the
// same page (same site, same cookies, nothing sent elsewhere), so it gets every car with its supplier, depot, fees and excess as the site's own data, not as text off cards. It never presses
// "View deal" and books nothing. The tool replaces __EXPECT__ (what the address asked for).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/\/search-results/i.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the Rentalcars search results page: open the url first' });
  const q = new URLSearchParams(location.search);
  const two = (n) => String(n).padStart(2, '0');
  const when = (p) => q.get(p + 'Year') + '-' + two(q.get(p + 'Month')) + '-' + two(q.get(p + 'Day')) + ' ' + two(q.get(p + 'Hour')) + ':' + two(q.get(p + 'Minute'));
  const form = { iata: q.get('locationIata'), drop_iata: q.get('dropLocationIata'), pickup_when: when('pu'), dropoff_when: when('do'), age: parseInt(q.get('driversAge') || '', 10) || null };
  const problems = [];
  for (const k of ['iata', 'drop_iata', 'pickup_when', 'dropoff_when', 'age']) if (EXPECT[k] && form[k] !== EXPECT[k]) problems.push(k + ' ' + form[k] + ' instead of ' + EXPECT[k]);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form });
  const entry = async () => { for (let i = 0; i < (typeof API_TRIES !== 'undefined' ? API_TRIES : 60); i++) { const e = performance.getEntriesByType('resource').find((x) => /\/api\/search-results\?/.test(x.name)); if (e) return e; await wait(500); } return null; };
  const e = await entry();
  if (!e) return JSON.stringify({ ok: false, error: 'the page has not made its search request (still loading, a check page or a block): never say sold out, say it could not be read' });
  let j;
  try { const res = await fetch(e.name, { credentials: 'same-origin' }); if (!res.ok) return JSON.stringify({ ok: false, error: 'the page\'s own search request answered ' + res.status + ': say it could not be read' }); j = await res.json(); }
  catch (err) { return JSON.stringify({ ok: false, error: 'the page\'s own search request could not be read again (' + String(err).slice(0, 60) + ')' }); }
  const matches = j.matches || [];
  if (!matches.length) return JSON.stringify({ ok: false, error: 'the search answer holds no cars: never say sold out, say it could not be read' });
  const shown = (document.body.innerText.match(/([\d,]+)\s+cars?\s+available/i) || [])[1] || null;
  const fee = (m, name) => { const f = (m.fees || []).find((x) => x.name === name); return f && f.price ? f.price.amount : null; };
  const OTHER = ['TRANSPONDER_FEE', 'VALET_FEE', 'ADMINISTRATION_FEE', 'CREDIT_CARD_CHARGE', 'ENVIRONMENTAL_FEE'];
  const rows = matches.map((m) => {
    const v = m.vehicle || {}; const depot = (j.depots || {})[(m.route || {}).pickUpDepotId] || {}; const sup = (j.suppliers || {})[depot.supplierId] || {};
    const drive = v.driveAwayPrice || {}; const base = v.price || {};
    return { id: v.id, car: v.makeAndModel, klass: v.carClass, category: (v.carCategories || [])[0] || null, seats: v.numberOfSeats, doors: v.numberOfDoors, big: v.bigSuitcase, small: v.smallSuitcase,
      gearbox: v.transmission, ac: v.airConditioning, fuel: v.fuel, mileage: v.mileageType, pay: v.payWhen, free_cancel: v.freeCancellation, card_needed: v.creditCardRequired,
      cur: drive.currency || base.currency, total: drive.amount, base: base.amount, damage_excess: fee(m, 'DAMAGE_EXCESS'), theft_excess: fee(m, 'THEFT_EXCESS'), deposit: fee(m, 'DEPOSIT'),
      other_fees: (m.fees || []).filter((f) => OTHER.includes(f.name) && f.price && f.price.amount != null).map((f) => f.name + ' ' + f.price.amount + (f.includedInDriveAwayPrice ? ' (in the total)' : ' (not in the total)')).join('; ') || null,
      supplier: sup.name || null, rating: depot.rating ? depot.rating.average : null, ratings: depot.rating ? depot.rating.numRatings : null, place: depot.name || null, place_type: depot.locationType || null, address: depot.address || null };
  });
  const policies = ((j.aggregates || {}).fuelPolicyTypes || []).map((x) => x.value);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, cars_shown_by_page: shown, matches_read: rows.length, fuel_policies: policies }, rows);
})()
