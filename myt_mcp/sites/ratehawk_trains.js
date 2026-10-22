// RateHawk train tickets results reader. Run it in the operator's logged-in RateHawk train RESULTS tab (read only: it ticks the filters you ask for and presses "Load more").
// The filters are not in the address (the page applies them itself), so the script ticks them and reports which boxes are ticked. The tool replaces __CHANGES__, __CLASS__ (a
// service class name or ""), __SKIP__ and __LIMIT__ before it runs. "from" prices are for the WHOLE group of adults.
await (async () => {
  const CHANGES = "__CHANGES__"; const CLASS = "__CLASS__"; const SKIP = __SKIP__; const LIMIT = __LIMIT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const selectBtns = () => [...document.querySelectorAll('button')].filter((b) => (b.innerText || '').trim() === 'Select fare');
  const cardOf = (b) => { let e = b; for (let i = 0; i < 14 && e; i++) { e = e.parentElement; if (e && (e.innerText.match(/Select fare/g) || []).length === 1 && /\d\d:\d\d/.test(e.innerText) && e.innerText.length > 80) return e; } return null; };
  const cards = () => selectBtns().map(cardOf).filter(Boolean);
  if (!location.pathname.startsWith('/railway')) return JSON.stringify({ ok: false, error: 'not a RateHawk train results page: open the url first' });
  for (let i = 0; i < 80 && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no train cards: logged out, no trains for this search, or still searching (wait and run once more)' });
  let last = -1; let stable = 0;
  for (let i = 0; i < 20 && stable < 3; i++) { await wait(1000); const n = cards().length; if (n === last) stable++; else { stable = 0; last = n; } }
  // "Load more" resets the page's filters to the defaults, so the whole list is loaded FIRST and the filters are ticked on it afterwards
  for (let i = 0; i < 12; i++) {
    const btn = [...document.querySelectorAll('button')].find((b) => (b.innerText || '').trim() === 'Load more');
    if (!btn) break;
    const before = cards().length; btn.click();
    for (let k = 0; k < 20 && cards().length === before; k++) await wait(500);
    if (cards().length === before) break;
  }
  await wait(1000);
  const tick = async (label) => {
    const l = [...document.querySelectorAll('label')].find((x) => (x.innerText || '').trim() === label);
    const input = l && (l.querySelector('input') || document.getElementById(l.getAttribute('for') || ''));
    if (!input) return false;
    if (!input.checked) { input.click(); await wait(4000); }
    return true;
  };
  const notFound = [];
  if (CHANGES && !(await tick(CHANGES))) notFound.push(CHANGES);
  if (CLASS && !(await tick(CLASS))) notFound.push(CLASS);
  if (notFound.length) return JSON.stringify({ ok: false, error: `filter(s) not found on the page: ${notFound.join(', ')}` });
  const allLoaded = ![...document.querySelectorAll('button')].some((b) => (b.innerText || '').trim() === 'Load more');
  const money = (s) => { const m = (s || '').match(/([€$£])\s?([\d,]+(?:\.\d+)?)/); return m ? { v: parseFloat(m[2].replace(/,/g, '')), c: ({ '€': 'EUR', '$': 'USD', '£': 'GBP' })[m[1]] } : null; };
  const row = (c) => {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const after = (label) => { const i = lines.indexOf(label); return i >= 0 ? lines[i + 1] || null : null; };
    const classes = lines.filter((x) => /^(Standard|Comfort|Premier)\b.*from/.test(x)).map((x) => { const m = money(x); return { name: x.split(/\s+from/)[0].trim(), price: m ? m.v : null, currency: m ? m.c : null }; });
    return { train: lines[0], route: lines[1], tag: lines.find((x) => /^The (fastest|cheapest|earliest) option$/i.test(x)) || null, dep: after('Departure'), travel: after('Travel time'), arr: after('Arrival'),
      date: lines.find((x) => /^\d{1,2} [A-Z][a-z]+, [A-Z][a-z]{2}$/.test(x)) || null, changes: lines.find((x) => /^(Direct|\d+ change)/i.test(x)) || null, classes };
  };
  const rows = cards().slice(0, SKIP + LIMIT).map(row).slice(SKIP);
  const pageTicked = [...document.querySelectorAll('input:checked')].map((b) => ((b.closest('label') || b.parentElement || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)).filter(Boolean);
  const heading = (document.body.innerText.match(/\n([^\n]+) → ([^\n]+)\n/) || [])[0];
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    page_ticked: pageTicked, settled: stable >= 3, all_loaded: allLoaded, cards_total: cards().length, offset: SKIP }, rows);
})()
