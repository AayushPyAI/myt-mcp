// Booking.com attractions list reader (comparison only). Run it in the operator's Booking.com attractions RESULTS tab the recipe opened (read only: it picks the sort in the page's own sort box and scrolls down to load more cards).
// Every activity is a card (data-testid="card") with named parts: card-title, review-score ("User reviews, Exceptional, 9.6 out of 10 from 56 reviews"), price ("From | EUR 35 | EUR 29.05 | Original price from ...
// Current price from EUR 29.05"). The card also says "Duration: 9 hours", "Free cancellation available" and "#1 Best seller". The price is the LOWEST starting price per person of the activity (not for a date and
// group: that is on the activity's own page), in the currency of the address (selected_currency=EUR). The address already holds the site's own filters (filter_by_label[]=free_cancellation, filter_by_min_rating[]=4.5 ...).
// 15 cards load first and 15 more come each time the page is scrolled; the page does not say how many exist. The script reads the first LIMIT cards of "Our top picks" (the default order), then picks "Best reviewed"
// (the sort box's radio) and reads the first LIMIT of that (the agency reads both). A human check (captcha) stops the script: it is never worked around.
// The tool replaces __EXPECT__ (what the address asked for), __LIMIT__ (cards per sort) and __SORTS__ ([["Our top picks","trending"],["Best reviewed","highest_weighted_rating"]]).
await (async () => {
  const EXPECT = __EXPECT__; const LIMIT = __LIMIT__; const SORTS = __SORTS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(document.body.innerText.slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)booking\.com$/i.test(location.hostname) || !/^\/attractions\/searchresults\/[a-z]{2}\/[a-z0-9-]+(\.[a-z-]+)?\.html$/i.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Booking.com attractions results page: open the url first' });
  const cards = () => [...document.querySelectorAll('[data-testid="card"]')];
  for (let i = 0; i < (typeof CARD_TRIES !== 'undefined' ? CARD_TRIES : 60) && !cards().length; i++) await wait(500);      // up to 30 s (CARD_TRIES: tests only)
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no activities are shown (still loading, a check page, or none for this search): never say there are none, say it could not be read' });
  const q = new URLSearchParams(location.search);
  const m = location.pathname.match(/\/searchresults\/([a-z]{2})\/([a-z0-9-]+)/i);
  const all = (k) => q.getAll(k + '[]').sort();
  const form = { place: m ? m[1].toLowerCase() + '/' + m[2].toLowerCase() : null, day: q.get('date_from'), day_to: q.get('date_to'), adults: parseInt(q.get('adults') || '', 10) || null, currency: q.get('selected_currency'),
    sort: q.get('sort_by'), labels: all('filter_by_label'), min_rating: all('filter_by_min_rating'), language: all('filter_by_language'), time_of_day: all('filter_by_time_of_day') };
  const problems = [];
  for (const k of ['place', 'day', 'day_to', 'adults', 'currency', 'sort', 'labels', 'min_rating', 'language', 'time_of_day']) if (EXPECT[k] !== undefined && JSON.stringify(form[k]) !== JSON.stringify(EXPECT[k])) problems.push(k + ' ' + JSON.stringify(form[k]) + ' instead of ' + JSON.stringify(EXPECT[k]));
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', form });
  // what the page's own filter boxes say is on (the sort radios are not filters)
  const filtersOn = () => [...document.querySelectorAll('input:checked')].filter((x) => x.name && x.name !== 'sort').map((x) => x.name + '=' + x.value).sort();
  const sortOn = () => { const r = [...document.querySelectorAll('input[name="sort"]')].find((x) => x.checked); return r ? r.id.replace(/^.*-/, '') : null; };
  const sig = () => cards().slice(0, 3).map((c) => ((c.querySelector('[data-testid="card-title"]') || {}).innerText || '')).join('|');
  const T = (el, id) => { const e = el.querySelector('[data-testid="' + id + '"]'); return e ? e.innerText.replace(/\s+/g, ' ').trim() : null; };
  const rows = []; const unparsed = []; const sorts = [];
  const readCards = (sortName) => {
    for (const c of cards().slice(0, LIMIT)) {
      const title = T(c, 'card-title'); const priceText = T(c, 'price'); const text = c.innerText.replace(/\s+/g, ' ');
      const cur = priceText && priceText.match(/Current price from\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
      const orig = priceText && priceText.match(/Original price from\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
      const plain = priceText && priceText.match(/From\s*(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/i);
      const pick = cur || plain;
      if (!title || !pick) { if (unparsed.length < 3) unparsed.push(text.slice(0, 160)); continue; }
      const rv = (T(c, 'review-score') || '').match(/([\d.]+) out of 10 from ([\d,]+) reviews?/i);
      const a = c.querySelector('a[href*="/attractions/"]') || c.closest('a');
      rows.push({ sort: sortName, title, cur: pick[1], from: parseFloat(pick[2].replace(/,/g, '')), was: orig ? parseFloat(orig[2].replace(/,/g, '')) : null, rating: rv ? parseFloat(rv[1]) : null, reviews: rv ? parseInt(rv[2].replace(/,/g, ''), 10) : null,
        duration: ((c.innerText.split('\n').map((x) => x.trim()).find((x) => /^Duration:/i.test(x)) || '').replace(/^Duration:\s*/i, '')) || null,
        free_cancel: /Free cancellation available/i.test(text), best_seller: (text.match(/#(\d+) Best seller/i) || [null, null])[1], available_from: (text.match(/Available from [a-z0-9 ]+?(?= See availability|$)/i) || [null])[0],
        path: a ? a.getAttribute('href').split('?')[0].split('#')[0] : null });
    }
  };
  const filtersStart = filtersOn();
  for (const [name, key] of SORTS) {
    if (sortOn() !== key) {
      const radio = [...document.querySelectorAll('input[name="sort"]')].find((x) => x.id.endsWith('-' + key));
      if (!radio) return JSON.stringify({ ok: false, error: 'the sort box has no "' + name + '" choice: run the script once more' });
      const before = sig(); (radio.closest('label') || radio).click();
      for (let k = 0; k < 30 && (sortOn() !== key || sig() === before); k++) await wait(400);
      await wait(1500);
    }
    let last = -1; let stalled = 0;
    for (let i = 0; i < 25 && cards().length < LIMIT && stalled < 3; i++) { window.scrollTo(0, document.body.scrollHeight); await wait(1500); const n = cards().length; stalled = n === last ? stalled + 1 : 0; last = n; }
    window.scrollTo(0, 0);
    const before = rows.length; readCards(name);
    sorts.push({ sort: name, shown_as: sortOn(), read: rows.length - before, cards_on_page: cards().length });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    form, filters_on: filtersStart, filters_on_end: filtersOn(), heading: ((document.querySelector('h1') || {}).innerText || '').slice(0, 80), sorts, unparsed }, rows);
})()
