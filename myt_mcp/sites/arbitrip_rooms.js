// Arbitrip hotel-page room reader. Run it in the HOTEL tab (the one the Select button of a result opens): it only reads the room table of that hotel.
// Each room says its cancellation ("Non refundable" or "Free cancellation" with the date) and meal plan: this is where free cancellation is confirmed.
// The tool replaces __EXPECT__ (the dates and guests the address must carry) before it runs.
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const dealsNow = () => [...document.querySelectorAll('.deal-info')];
  if (!location.pathname.startsWith('/hotel/')) return JSON.stringify({ ok: false, error: 'not an Arbitrip hotel page: press Select on the hotel in the results first (it opens this page in a new tab)' });
  for (let i = 0; i < 60 && !dealsNow().length; i++) await wait(500);
  if (!dealsNow().length) return JSON.stringify({ ok: false, error: 'no rooms: logged out, still loading, or the hotel has no availability for these dates' });
  await wait(1500);
  const q = new URLSearchParams(location.search);
  const wrong = Object.keys(EXPECT).filter((k) => q.get(k) !== EXPECT[k]);
  if (wrong.length) return JSON.stringify({ ok: false, error: `the hotel page is for other ${wrong.join(', ')} than asked: search again with the right dates and guests`, found: wrong.map((k) => [k, q.get(k)]) });
  const money = (s) => { const m = (s || '').match(/€\s?([\d,]+(?:\.\d+)?)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  const rows = dealsNow().map((d) => {
    const lines = d.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const ci = lines.findIndex((x) => /^(Non refundable|Free cancellation)/i.test(x));
    const euro = lines.filter((x) => /^€/.test(x));
    return {
      room: lines[0], cancellation: ci >= 0 ? lines[ci] + (/^before /i.test(lines[ci + 1] || '') ? ' ' + lines[ci + 1] : '') : null,
      meal: lines.find((x) => /^(Breakfast|Room Only|Half Board|Full Board|All Inclusive)/i.test(x)) || null, price: money(euro[0]), per_night: money(euro.find((x) => /Avg/.test(x)) || lines[lines.findIndex((x) => /Avg\/Night/.test(x)) - 1]),
    };
  });
  const scoreEl = document.querySelector('[class*=review-score],[class*=score]');
  const prices = rows.map((r) => r.price).filter((x) => x != null);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    hotel: document.title.split('|')[0].trim(), hotel_path: location.pathname, stars: document.querySelectorAll('.star.full').length || null, score: scoreEl ? scoreEl.innerText.trim() : null,
    reviews: ((document.body.innerText.match(/([\d,]+)\s+Reviews/) || [])[1]) || null, distance: ((document.body.innerText.match(/\(([\d.]+ ?(?:km|m) from center)\)/) || [])[1]) || null,
    price_order: prices.every((p, i) => i === 0 || p >= prices[i - 1]) ? 'ascending' : 'not ascending' }, rows);
})()
