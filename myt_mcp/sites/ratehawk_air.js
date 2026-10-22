// RateHawk air tickets results reader. Run it in the operator's logged-in RateHawk air RESULTS tab (read only: it only reads the page; the filters are already in the address).
// One card = one validating-carrier offer: its flight alternatives (itineraries, short keys d=departs a=arrives n=next-day t=travel s=stops l=layover f=flights) and its
// fare tiers (name, the price for the WHOLE group, bag weights in kg that come before the name). The search streams in, so it waits until the number of cards is steady.
await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const chooseButtons = () => [...document.querySelectorAll('button')].filter((e) => (e.innerText || '').trim() === 'Choose');
  const cardOf = (b) => { let e = b; for (let i = 0; i < 16 && e; i++) { e = e.parentElement; if (e && (e.innerText.match(/Choose/g) || []).length === 1 && /\d\d:\d\d/.test(e.innerText) && e.innerText.length > 100) return e; } return null; };
  const cards = () => chooseButtons().map(cardOf).filter(Boolean);
  for (let i = 0; i < 120 && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no flight cards: not a RateHawk air results page, logged out, no flights for this search, or still searching (wait and run once more)' });
  let last = -1; let stable = 0;
  for (let i = 0; i < 60 && stable < 5; i++) { await wait(1000); const n = cards().length; if (n === last) stable++; else { stable = 0; last = n; } }
  const isTime = (x) => /^\d\d:\d\d$/.test(x || '');
  const isMoney = (x) => /^[€$£]\s?[\d,]+(\.\d+)?$/.test(x || '');
  const val = (x) => parseFloat(x.replace(/[^\d.]/g, ''));
  const cur = (x) => ({ '€': 'EUR', '$': 'USD', '£': 'GBP' })[x.trim()[0]] || null;
  function row(c) {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const starts = [];
    for (let i = 0; i < lines.length - 3; i++) {
      if (!isTime(lines[i]) || !isTime(lines[i + 1])) continue;
      const nd = /^\+\d$/.test(lines[i + 2]) ? lines[i + 2] : null; const j = i + 2 + (nd ? 1 : 0);
      if (/travel time/.test(lines[j] || '')) starts.push({ i, nd, j });
    }
    const itineraries = starts.map((s, k) => {
      const end = k + 1 < starts.length ? starts[k + 1].i : lines.length;
      const blk = lines.slice(s.j, end);
      return { d: lines[s.i], a: lines[s.i + 1], n: s.nd, t: blk[0].replace(/ travel time$/, ''), s: blk[1] || null, l: blk.find((x, q) => q > 1 && /^\d+ (h|min)/.test(x) && /,/.test(x)) || null, f: blk.filter((x) => /^[A-Z0-9]{2}-\d+$/.test(x)) };
    });
    const fares = []; let nums = [];
    for (let j = starts.length ? starts[starts.length - 1].j : 0; j < lines.length; j++) {
      const x = lines[j];
      if (/^\d{1,3}$/.test(x)) { nums.push(parseInt(x, 10)); continue; }
      if (!isMoney(x) && isMoney(lines[j + 1]) && !/^(Choose|More rates|Fare conditions)$/i.test(x)) { fares.push({ name: x, price: val(lines[j + 1]), currency: cur(lines[j + 1]), bags: nums }); nums = []; j += 2; }
    }
    const route = lines.find((x) => /→/.test(x)) || null;
    return { carrier: (lines[0] || '').replace(/ validates$/i, ''), issuing: lines[1] || null, date: lines.find((x) => /^[A-Z][a-z]{2} \d{1,2}, [A-Z][a-z]{2}$/.test(x)) || null, route, itineraries, fares };
  }
  const rows = cards().map(row);
  const pageTicked = [...document.querySelectorAll('input[type=checkbox],input[type=radio]')].filter((b) => b.checked).map((b) => ((b.closest('label') || b.parentElement || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)).filter(Boolean);
  const lows = rows.map((r) => (r.fares.length ? Math.min(...r.fares.map((f) => f.price)) : null)).filter((x) => x != null);
  const asc = lows.every((p, i) => i === 0 || p >= lows[i - 1]);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    page_ticked: pageTicked, settled: stable >= 5, cards_read: rows.length, lowest_fare_order: asc ? 'ascending' : 'not ascending' }, rows);
})()
