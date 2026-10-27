// Europcar car list reader (www.europcar.com/en-us/reservation/vehicles). Run it in the operator's Chrome on the results tab the recipe opened (read only).
// The list loads 10 cars at a time while the page is scrolled: the script scrolls until no new car appears, then reads every card and opens each card's "Vehicle details"
// (it only expands the card) for the protection's excess. It never presses Select and books nothing. The tool replaces __EXPECT__ (what the address asked for).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/\/reservation\/vehicles/i.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the Europcar vehicle list: open the url first' });
  const cards = () => [...document.querySelectorAll('div.ecw-vehicle-card')];
  for (let i = 0; i < (typeof CARD_TRIES !== 'undefined' ? CARD_TRIES : 60) && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no cars are shown (still loading, a block or check page, or nothing matches): never say sold out, say it could not be read' });
  const text = document.body.innerText;
  const lines = text.split('\n').map((x) => x.trim()).filter(Boolean);
  const after = (label, n = 1) => { const i = lines.indexOf(label); return i < 0 ? null : (lines[i + n] || null); };
  const form = { pickup_place: after('Pick up'), pickup_when: after('Pick up', 2), dropoff_place: after('Return'), dropoff_when: after('Return', 2) };
  const q = new URLSearchParams(location.search);
  const age = parseInt(q.get('driverAge') || '', 10) || null, residency = q.get('countryOfResidence') || null;
  const problems = [];
  if (EXPECT.age && age !== EXPECT.age) problems.push('driver age ' + age + ' instead of ' + EXPECT.age);
  if (EXPECT.residency && residency !== EXPECT.residency) problems.push('residency ' + residency + ' instead of ' + EXPECT.residency);
  if (EXPECT.pickup_when && form.pickup_when !== EXPECT.pickup_when) problems.push('pick-up ' + form.pickup_when + ' instead of ' + EXPECT.pickup_when);
  if (EXPECT.dropoff_when && form.dropoff_when !== EXPECT.dropoff_when) problems.push('return ' + form.dropoff_when + ' instead of ' + EXPECT.dropoff_when);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form, age, residency });
  let last = -1; let stalled = 0;      // the list is infinite: 10 cars come, 10 more after each scroll
  for (let i = 0; i < 30 && stalled < 3; i++) { window.scrollTo(0, document.body.scrollHeight); await wait(1200); const n = cards().length; stalled = n === last ? stalled + 1 : 0; last = n; }
  window.scrollTo(0, 0);
  const T = (el, sel) => ((el.querySelector(sel) || {}).innerText || '').replace(/\s+/g, ' ').trim() || null;
  const money = (s) => { const m = (s || '').match(/(\$|€|₪|£|₹)\s?([\d,]+(?:\.\d+)?)/); return m ? { symbol: m[1], amount: parseFloat(m[2].replace(/,/g, '')) } : null; };
  const KEYS = { pax: 'seats', doors: 'doors', luggage: 'bags', transmission: 'gearbox', air_conditionning: 'ac', minimum_age: 'min_age' };
  const rows = [];
  for (const c of cards()) {
    const btn = c.querySelector('.ecw-vehicle-card__basic-information__more-details button');
    if (btn && !c.querySelector('.ecw-vehicle-more-details')) { btn.click(); await wait(250); }
    const icons = {};
    [...c.querySelectorAll('.ecw-vehicle-card__basic-information__features-icons > div')].forEach((d, i) => {
      const use = d.querySelector('use'); const id = use ? (use.getAttribute('href') || use.getAttribute('xlink:href') || '') : '';
      const key = KEYS[id.replace('#', '').replace(/_svg__a$/, '')] || ['seats', 'doors', 'bags', 'gearbox', 'ac', 'min_age'][i];
      icons[key] = ((d.querySelector('p') || {}).innerText || '').trim();
    });
    const feats = [...c.querySelectorAll('.ecw-vehicle-card__basic-information__features-list p')].map((p) => p.innerText.trim());
    const price = c.querySelector('.ecw-vehicle-card__basic-information__price-section');
    const total = money(T(c, '.ecw-vehicle-card__basic-information__price-section--total')), day = money(T(c, '.ecw-vehicle-card__basic-information__price-section--day'));
    const excessLine = [...c.querySelectorAll('.ecw-vehicle-more-details p')].map((p) => p.innerText.trim()).find((x) => /^Excess:/i.test(x)) || null;
    rows.push({ car: T(c, 'h2'), klass: T(c, '.ecw-vehicle-card__basic-information__tags p'), seats: icons.seats, doors: icons.doors, bags: icons.bags, gearbox: icons.gearbox, ac: icons.ac, min_age: icons.min_age,
      mileage: feats.find((x) => /mileage/i.test(x)) || null, protection: feats.find((x) => /protection/i.test(x)) || null, pay: price ? (T(price, 'p') || null) : null,
      symbol: total && total.symbol, total: total && total.amount, per_day: day && day.amount, excess_text: excessLine, excess: money(excessLine) && money(excessLine).amount });
  }
  const sort = (lines.find((x) => /^(recommended|price|lowest price)/i.test(x)) || null);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, age, residency, sort, cards_read: rows.length }, rows);
})()
