// Ofran car rental results reader (the agency's own logged-in Ofran). Run it on the RESULTS page (ofran.co.il/reservation/results), read only: it ticks the filter boxes you ask for and reads the cards.
// The results page IGNORES the dates in its address and shows the last search made with the form, so the form is filled by hand (see the tool's steps) and this script returns what the page itself
// says it searched (places, dates, times, driver age) for the server to check. Every car is in the page at once (no paging). The price shown is the one AFTER the agent discount ("price before the
// discount" is the list price); it is the agent's price only when the top bar shows the agent's name. The tool replaces __SKIP__, __LIMIT__ and __FILTERS__ (a JSON list of filter labels in Hebrew).
await (async () => {
  const SKIP = __SKIP__; const LIMIT = __LIMIT__; const FILTERS = __FILTERS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const btns = () => [...document.querySelectorAll('button')].filter((b) => /לקחתי/.test(b.innerText || ''));
  const cardOf = (b) => { let e = b; for (let i = 0; i < 20 && e; i++) { e = e.parentElement; if (e && (e.innerText.match(/לקחתי/g) || []).length === 1 && /או דומה/.test(e.innerText) && /\b[A-Z]{4}\b/.test(e.innerText)) return e; } return null; };
  const cards = () => btns().map(cardOf).filter(Boolean);
  if (!/ofran\.co\.il$/.test(location.host) || !/\/reservation\/results/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not Ofran\'s results page: make the search with the form first (the steps)' });
  for (let i = 0; i < 80 && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no cars: logged out, still searching, no cars for this search, or the search was not made (wait and run once more)' });
  let last = -1; let stable = 0;
  for (let i = 0; i < 15 && stable < 3; i++) { await wait(1000); const n = cards().length; if (n === last) stable++; else { stable = 0; last = n; } }
  const tick = async (label) => {
    const l = [...document.querySelectorAll('label')].find((x) => (x.innerText || '').trim() === label);
    const input = l && (l.querySelector('input') || document.getElementById(l.getAttribute('for') || ''));
    if (!input) return false;
    if (!input.checked) { const before = cards().length; input.click(); for (let k = 0; k < 20; k++) { await wait(500); if (cards().length !== before) break; } await wait(1500); }
    return true;
  };
  const notFound = [];
  for (const f of FILTERS) if (!(await tick(f))) notFound.push(f);
  if (notFound.length) return JSON.stringify({ ok: false, error: `filter(s) not found on the page: ${notFound.join(', ')}` });
  const all = document.body.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
  const at = (label) => all.indexOf(label);
  const iPick = at('לקיחה'); const iBack = at('החזרה');
  const form = { pickup_place: all[iPick + 1] || null, pickup_when: all[iPick + 2] || null, dropoff_place: all[iBack + 1] || null, dropoff_when: all[iBack + 2] || null, age: (all.find((x) => /^גיל הנהג\/ת הוא:/.test(x)) || '').replace(/^גיל הנהג\/ת הוא:\s*/, '') || null };
  const iHe = all.indexOf('HE'); const account = iHe >= 0 ? all.slice(iHe + 1, iHe + 3).join(' / ') : null;
  const total = (document.body.innerText.match(/נמצאו (\d+) תוצאות/) || [])[1] || null;
  const money = (s) => { const m = String(s || '').match(/([\d,]+(?:\.\d+)?)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  const row = (c) => {
    const l = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const iSim = l.indexOf('או דומה');
    const nums = []; let j = iSim + 1; for (; j < l.length && !/^(מזגן|כולל|עם|ללא|תחנת|בתוך|מחוץ|הוספה)/.test(l[j]); j++) if (/^\d+(\/\d+)?$/.test(l[j]) || /^(ידני|אוטומטית|אוטומטי)$/.test(l[j])) nums.push(l[j]);
    const gear = nums.find((x) => /^(ידני|אוטומטית|אוטומטי)$/.test(x)); const digits = nums.filter((x) => x !== gear);
    const logo = [...c.querySelectorAll('img')].find((i) => /Supplier-Logos/.test(i.getAttribute('src') || ''));
    const iBefore = l.indexOf('מחיר לפני ההנחה'); const iAfter = l.indexOf('מחיר אחרי ההנחה');
    const sizeAt = l.indexOf('גודל הרכב');
    return { supplier: logo ? (logo.alt || (logo.getAttribute('src') || '').split('/').pop().replace(/\.\w+$/, '')) : null, supplier_score: ((l.find((x) => /^ציון:/.test(x)) || '').match(/[\d.]+/) || [null])[0], size: sizeAt >= 0 ? l[sizeAt + 1] : null,
      acriss: l.find((x) => /^[A-Z]{4}$/.test(x)) || null, car: iSim > 0 ? l[iSim - 1] : null, seats: digits[0] || null, gearbox: gear || null, doors: digits[1] || null, bags: digits.slice(2).join('/') || null, ac: l.includes('מזגן'),
      excess: l.find((x) => /השתתפות עצמית/.test(x) && !/הוספה|לפרטי/.test(x)) || null, station: l.find((x) => /^(תחנת איסוף|בתוך שדה|מחוץ לשדה)/.test(x)) || null,
      price_before: iBefore >= 0 ? money(l[iBefore + 1]) : null, price: iAfter >= 0 ? money(l[iAfter + 1]) : null, days: ((l.find((x) => /^מחיר ל-\d+ ימי השכרה/.test(x)) || '').match(/\d+/) || [null])[0] };
  };
  const rows = cards().slice(0, SKIP + LIMIT).map(row).slice(SKIP);
  const pageTicked = [...document.querySelectorAll('input[type=checkbox],input[type=radio]')].filter((b) => b.checked && !/cookie|ot-|chkbox/i.test((b.name || '') + (b.id || ''))).map((b) => ((b.closest('label') || b.parentElement || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)).filter(Boolean);
  const ranges = [...document.querySelectorAll('input[type=range]')].map((r) => ({ v: Number(r.value), min: Number(r.min), max: Number(r.max) }));
  const prices = rows.map((r) => r.price).filter((x) => x != null);
  const asc = prices.every((p, i) => i === 0 || p >= prices[i - 1]);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, account, logged_in: /התנתקות/.test(document.body.innerText), results_total: total ? Number(total) : null, cars_in_page: cards().length, offset: SKIP, page_ticked: pageTicked, price_ranges: ranges, settled: stable >= 3,
    price_order: asc ? 'ascending' : 'not ascending' }, rows);
})()
