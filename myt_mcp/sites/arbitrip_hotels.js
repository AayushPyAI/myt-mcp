// Arbitrip hotel results reader. Run it in the operator's logged-in Arbitrip RESULTS tab (read only: it scrolls the list).
// The list is windowed (only about 3 cards exist in the page at a time), so it scrolls down in small steps and keeps each card the first time it is seen.
// The tool replaces __LIMIT__, __SKIP__, __EXPECT_SORT__ and __EXPECT_KEYS__ (the filters the address must carry). The list price is the cheapest room
// (with breakfast when that filter is on) and it can be a NON-REFUNDABLE room: cancellation is read on the hotel page, never here.
await (async () => {
  const LIMIT = __LIMIT__; const SKIP = __SKIP__;
  const EXPECT_SORT = "__EXPECT_SORT__"; const EXPECT_KEYS = __EXPECT_KEYS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const cardsNow = () => [...document.querySelectorAll('.hotel-content')];
  if (!location.pathname.startsWith('/results')) return JSON.stringify({ ok: false, error: 'not an Arbitrip results page: open the url first' });
  for (let i = 0; i < 70 && !cardsNow().length; i++) await wait(500);
  if (!cardsNow().length) return JSON.stringify({ ok: false, error: 'no hotel cards: logged out, still searching, or no hotel matches the filters' });
  await wait(1200);
  const text = document.body.innerText;
  const sort = ((text.match(/Sort by:\s*([^\n]*)/) || [])[1] || '').trim();
  const contract = ((text.match(/Showing results for\s*([^\n]*)/) || [])[1] || '').trim();
  const keys = [...new URLSearchParams(location.search).keys()];
  const missing = EXPECT_KEYS.filter((k) => !keys.includes(k));
  if (EXPECT_SORT && sort !== EXPECT_SORT) return JSON.stringify({ ok: false, error: `the list is sorted by "${sort}", not "${EXPECT_SORT}": open the url again`, sort });
  if (missing.length) return JSON.stringify({ ok: false, error: `the address lost filter(s) ${missing.join(', ')}: open the url again`, filters_in_url: keys });
  if (!contract) return JSON.stringify({ ok: false, error: 'the results are not shown for the agency contract (the "Showing results for ..." name is missing): open the url again, the tool adds the contract', filters_in_url: keys });
  const money = (s) => { const m = (s || '').match(/€\s?([\d,]+(?:\.\d+)?)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  const row = (c) => {
    const t = (sel) => ((c.querySelector(sel) || {}).innerText || '').trim() || null;
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const priceLines = lines.filter((x) => /^€/.test(x));
    const rev = (c.querySelector('.hotel-review') || {}).innerText || '';
    return {
      name: t('.hotel-name'), stars: c.querySelectorAll('.star.full').length || null, score: t('.review-score'), label: t('.review-description'),
      reviews: (rev.match(/\(([\d,]+)\s+Reviews?\)/) || [])[1] || null, area: t('.full-address'), distance: t('.distance-description'),
      price: money(priceLines[0]), per_night: money(priceLines.find((x) => /Avg/.test(x))), tax_included: /Tax Included/.test(c.innerText) || null,
    };
  };
  const seen = new Map();          // hotel -> row, in the order first seen (a card's position drifts while the page scrolls, so the position is not a key)
  const grab = () => cardsNow().sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top).forEach((c) => { const r = row(c); const key = r.name + '|' + r.distance; if (!seen.has(key)) seen.set(key, r); });
  window.scrollTo(0, 0); await wait(700); grab();
  const cardH = cardsNow()[0].closest('.result').getBoundingClientRect().height || 240;
  let holder = cardsNow()[0]; while (holder.parentElement && holder.getBoundingClientRect().height < cardH * 3) holder = holder.parentElement;
  const approxTotal = Math.round(holder.getBoundingClientRect().height / cardH);
  let stalled = 0;
  for (let i = 0; i < 160 && seen.size < SKIP + LIMIT; i++) {
    const before = seen.size;
    window.scrollBy(0, Math.round(cardH * 1.4)); await wait(450); grab();
    stalled = seen.size === before ? stalled + 1 : 0;
    if (stalled >= 6 && window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 5) break;
  }
  const rows = [...seen.values()].slice(SKIP, SKIP + LIMIT);
  const prices = rows.map((r) => r.price).filter((x) => x != null);
  const asc = prices.every((p, i) => i === 0 || p >= prices[i - 1]);
  const breakfast = (new URLSearchParams(location.search).get('amenities') || '').includes('BREAKFAST_INCLUDED');
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    sort, contract, filters_in_url: keys, breakfast_filter: breakfast, approx_total: approxTotal, offset: SKIP, price_order: asc ? 'ascending' : 'not ascending' }, rows);
})()
