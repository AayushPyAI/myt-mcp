// Booking.com attractions list reader (comparison only). Run it in the operator's Booking.com attractions RESULTS tab the recipe opened (read only: it only scrolls down to load more cards).
// Every activity is a card (data-testid="card") with named parts: card-title, review-score ("User reviews, Exceptional, 9.6 out of 10 from 56 reviews"), price ("From | EUR 35 | EUR 29.05 | Original price from ...
// Current price from EUR 29.05"). The card also says "Duration: 9 hours", "Free cancellation available" and "#1 Best seller". The price is the LOWEST starting price per person of the activity (not for a date and
// group: that is on the activity's own page), in the currency of the address (selected_currency=EUR). 15 cards load first and more come while the page is scrolled (15, then 30, then 45; 27 Oct 2026); the page does not
// say how many exist. A human check (captcha) stops the script: it is never worked around. The tool replaces __EXPECT__ (what the address asked for) and __LIMIT__ (how many cards to read at most).
await (async () => {
  const EXPECT = __EXPECT__; const LIMIT = __LIMIT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(document.body.innerText.slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)booking\.com$/i.test(location.hostname) || !/^\/attractions\/searchresults\/[a-z]{2}\/[a-z0-9-]+(\.[a-z-]+)?\.html$/i.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Booking.com attractions results page: open the url first' });
  const cards = () => [...document.querySelectorAll('[data-testid="card"]')];
  for (let i = 0; i < (typeof CARD_TRIES !== 'undefined' ? CARD_TRIES : 60) && !cards().length; i++) await wait(500);      // up to 30 s (CARD_TRIES: tests only)
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no activities are shown (still loading, a check page, or none for this search): never say there are none, say it could not be read' });
  const q = new URLSearchParams(location.search);
  const m = location.pathname.match(/\/searchresults\/([a-z]{2})\/([a-z0-9-]+)/i);
  const form = { place: m ? m[1].toLowerCase() + '/' + m[2].toLowerCase() : null, day: q.get('date_from'), day_to: q.get('date_to'), adults: parseInt(q.get('adults') || '', 10) || null, currency: q.get('selected_currency') };
  const problems = [];
  for (const k of ['place', 'day', 'day_to', 'adults', 'currency']) if (EXPECT[k] !== undefined && form[k] !== EXPECT[k]) problems.push(k + ' ' + form[k] + ' instead of ' + EXPECT[k]);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form });
  let last = -1; let stalled = 0;
  for (let i = 0; i < 25 && cards().length < LIMIT && stalled < 3; i++) { window.scrollTo(0, document.body.scrollHeight); await wait(1500); const n = cards().length; stalled = n === last ? stalled + 1 : 0; last = n; }
  window.scrollTo(0, 0);
  const T = (el, id) => { const e = el.querySelector('[data-testid="' + id + '"]'); return e ? e.innerText.replace(/\s+/g, ' ').trim() : null; };
  const rows = []; const unparsed = [];
  for (const c of cards().slice(0, LIMIT)) {
    const title = T(c, 'card-title'); const priceText = T(c, 'price'); const text = c.innerText.replace(/\s+/g, ' ');
    const cur = priceText && priceText.match(/Current price from\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
    const orig = priceText && priceText.match(/Original price from\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
    const plain = priceText && priceText.match(/From\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
    const pick = cur || plain;
    if (!title || !pick) { if (unparsed.length < 3) unparsed.push(text.slice(0, 160)); continue; }
    const rv = (T(c, 'review-score') || '').match(/([\d.]+) out of 10 from ([\d,]+) reviews?/i);
    const a = c.querySelector('a[href*="/attractions/"]') || c.closest('a');
    rows.push({ title, cur: pick[1], from: parseFloat(pick[2].replace(/,/g, '')), was: orig ? parseFloat(orig[2].replace(/,/g, '')) : null, rating: rv ? parseFloat(rv[1]) : null, reviews: rv ? parseInt(rv[2].replace(/,/g, ''), 10) : null,
      duration: ((c.innerText.split('\n').map((x) => x.trim()).find((x) => /^Duration:/i.test(x)) || '').replace(/^Duration:\s*/i, '')) || null,
      free_cancel: /Free cancellation available/i.test(text), best_seller: (text.match(/#(\d+) Best seller/i) || [null, null])[1], available_from: (text.match(/Available from [a-z0-9 ]+?(?= See availability|$)/i) || [null])[0],
      path: a ? a.getAttribute('href').split('?')[0].split('#')[0] : null });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, heading: ((document.querySelector('h1') || {}).innerText || '').slice(0, 80), cards_on_page: cards().length, unparsed }, rows);
})()
