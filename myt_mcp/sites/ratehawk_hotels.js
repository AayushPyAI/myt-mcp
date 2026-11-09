// RateHawk hotels: the page's OWN search call, replayed in the page (read only; it clicks nothing and books nothing). Run it in the operator's logged-in RateHawk results tab once the results show.
// The results page gets its hotels from ONE service of its own (read live 7 Nov 2026): POST /hotel/search/v2/b2bsite/serp?session=<session id> with the search (currency, language, search_uuid, partner slug,
// arrival and departure date, region_id, residency, paxes [{adults, child_ages}]), the page, the sort (price_asc / price_desc / rating) and the FILTERS (stars [40, 50], free_cancellation true, meals ["breakfast"]),
// answering 20 hotels a page with total_av_hotels (the header's "188 accommodation options available"), search_finished and, per hotel, static data (name, kind, star_rating in tens, distance from the centre,
// rating_total, ta_rating.num_reviews) and its cheapest rate (room, meal, cancellation_info with the exact free-cancellation deadline, payment_options with the price, the per-night price and the taxes NOT in the price).
// The search id (search_uuid) is in the page's dataLayer, the session id in the address of the page's own call (performance log), the region in the address (q=), the headers are the page's own (X-CSRFToken = its
// cookie, X-User-Mail = the logged-in user, X-Singlepage-Id = the build address). The body built here from those was IDENTICAL to the page's own body (checked with a child, stars, breakfast and free cancellation),
// and its hotels equal the cards of the page (80 cards of 4 pages: name, stars, price, score, reviews, distance, meal, cancellation, payment). The filters are sent in the call (RateHawk filters, not this script).
// The tool replaces __REQUEST__ (dates, guests, filters, sort), __START_PAGE__, __MAX_PAGES__, __SKIP__ and __LIMIT__ (the window of the list the operator asked for). A login page or a refusal stops the script: never worked around.
await (async () => {
  const REQ = __REQUEST__;
  const START_PAGE = __START_PAGE__; const MAX_PAGES = __MAX_PAGES__; const SKIP = __SKIP__; const LIMIT = __LIMIT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/(^|\.)ratehawk\.com$/.test(location.hostname)) return JSON.stringify({ ok: false, error: 'not a RateHawk page: open the url first' });
  if (/log in|sign in|forgot password/i.test((document.body && document.body.innerText || '').slice(0, 600)) && !(window.dataLayer || []).some((x) => x && x.user_email)) return JSON.stringify({ ok: false, error: 'RateHawk asks to log in: stop and tell the operator to log in (never type a password).' });
  const t0 = performance.now();
  const q = new URLSearchParams(location.search);
  const find = (o, key, d) => { if (d > 7 || !o || typeof o !== 'object') return null; if (typeof o[key] === 'string' && o[key]) return o[key]; for (const k of Object.keys(o)) { const r = find(o[k], key, d + 1); if (r) return r; } return null; };
  let uuid = null; let slug = null; let mail = null; let sessionId = null;
  for (let i = 0; i < 90 && !(uuid && slug && mail && sessionId && q.get('q')); i++) {      // the page sets these as it searches (up to ~45 s for a search RateHawk has not cached)
    const dl = window.dataLayer || [];
    uuid = find(dl, 'search_uuid', 0); slug = find(dl, 'partner_slug', 0); mail = find(dl, 'user_email', 0);
    const urls = performance.getEntriesByType('resource').map((e) => e.name).filter((n) => /\/hotel\/search\/v2\/b2bsite\/serp\?/.test(n));
    if (urls.length) sessionId = new URL(urls[urls.length - 1]).searchParams.get('session');
    if (uuid && slug && mail && sessionId && q.get('q')) break;
    await wait(500);
  }
  if (!mail) return JSON.stringify({ ok: false, error: 'the page shows no logged-in RateHawk user: stop and tell the operator to log in (never type a password)' });
  if (!uuid || !slug || !sessionId || !q.get('q')) return JSON.stringify({ ok: false, error: 'the page has not started its search (no search id or session after 45 s): open the url again, wait until the results show and run the script once more' });
  const cookie = document.cookie.split('; ').find((c) => /^csrftoken=/i.test(c));
  const build = ((performance.getEntriesByType('resource').map((e) => e.name).find((n) => /f\.worldota\.net\/partner\/sp\/branch\/[^\/]+\//.test(n)) || '').match(/(\/\/f\.worldota\.net\/partner\/sp\/branch\/[^\/]+)/) || [])[1];
  if (!cookie) return JSON.stringify({ ok: false, error: 'the page has no session cookie (logged out?): stop and tell the operator to log in' });
  const headers = { accept: 'application/json', 'content-type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': cookie.split('=')[1], 'X-User-Mail': mail, ...(build ? { 'X-Singlepage-Id': build } : {}) };
  const filters = {};
  if (REQ.stars_min) filters.stars = [1, 2, 3, 4, 5].filter((s) => s >= REQ.stars_min).map((s) => s * 10);
  if (REQ.free_cancellation) filters.free_cancellation = true;
  if (REQ.breakfast) filters.meals = ['breakfast'];
  const bodyFor = (page) => ({ session_params: { currency: 'EUR', language: 'en', search_uuid: uuid, partner_slug_force: slug, arrival_date: REQ.check_in, departure_date: REQ.check_out, region_id: parseInt(q.get('q'), 10), residency: REQ.residency,
    paxes: [{ adults: REQ.adults, ...(REQ.ages && REQ.ages.length ? { child_ages: REQ.ages } : {}) }] }, page, ...(Object.keys(filters).length ? { filters } : {}), sort: REQ.sort, session_id: sessionId });
  const call = async (page) => {
    const ac = new AbortController(); const to = setTimeout(() => ac.abort(), 40000);
    try {
      const res = await fetch('/hotel/search/v2/b2bsite/serp?session=' + encodeURIComponent(sessionId), { method: 'POST', headers, body: JSON.stringify(bodyFor(page)), signal: ac.signal });
      const tx = await res.text();
      if (res.status === 401 || res.status === 403 || /captcha|are you a human|access denied/i.test(tx.slice(0, 400))) return { stop: 'RateHawk refused the search service (HTTP ' + res.status + ': logged out, a human check or a block). Stop: do not retry and do not work around it; tell the operator to look at the page.' };
      if (!res.ok) return { stop: 'RateHawk\'s search service answered ' + res.status + (/session/.test(tx.slice(0, 300)) ? ' (' + tx.slice(0, 120) + ')' : '') + ': open the url again, wait until the results show and run the script once more' };
      return { j: JSON.parse(tx) };
    } catch (err) { return { stop: 'RateHawk\'s search service could not be read (' + String(err.name === 'AbortError' ? 'no answer in 40 s' : err.message).slice(0, 60) + '): run the script once more' }; } finally { clearTimeout(to); }
  };
  const rowOf = (h, page, rank) => {
    const v = h.static_vm || {}; const r = (h.rates || [])[0]; const pay = r && ((r.payment_options || {}).payment_types || [])[0];
    if (!r || !pay) return null;
    const ci = r.cancellation_info || {};
    return { p: page, rank, name: v.name || null, kind: v.kind || null, stars: v.star_rating ? v.star_rating / 10 : null, dist_km: v.search_region_center_distance != null ? Math.round(v.search_region_center_distance * 100) / 100 : null,
      score: v.rating_total != null ? v.rating_total : null, reviews: (v.ta_rating && v.ta_rating.num_reviews) || null, room: r.room_name || null, meal: r.meal || [], free_before: ci.free_cancellation_before || null,
      penalty: (ci.policies || []).slice(0, 4).map((x) => ({ from: x.start_at, to: x.end_at, pct: x.penalty && x.penalty.percent, amt: x.penalty && x.penalty.amount })),
      pay: pay.type, amount: Number(pay.show_amount), cur: pay.show_currency_code || pay.currency_code, per_night: Number(pay.average_show_price_per_day) || null,
      taxes_extra: ((pay.tax_data || {}).taxes || []).filter((t) => t.included_in_show === false).map((t) => ({ n: t.name, a: Number(t.amount), c: t.currency_code })), left: r.allotment != null ? r.allotment : null,
      path: v.region_catalog_slug && h.master_id && v.otahotel_id ? '/hotel/' + v.region_catalog_slug + '/mid' + h.master_id + '/' + v.otahotel_id + '/' : null };
  };
  const rows = []; let stopped = null; let head = null; let unparsed = 0;
  for (let page = START_PAGE; page < START_PAGE + MAX_PAGES; page++) {
    let got = null;
    for (let tries = 0; tries < 12; tries++) {      // a page asked before RateHawk has finished the search says search_finished false: ask again
      got = await call(page);
      if (got.stop) return JSON.stringify({ ok: false, error: got.stop });
      if (got.j.search_finished !== false || performance.now() - t0 > 38000) break;
      await wait(2000);
    }
    const j = got.j;
    if (!head) head = { total: j.total_av_hotels, total_no_filter: j.total_av_hotels_no_filter, total_region: j.total_hotels, finished: j.search_finished !== false };
    const hs = j.hotels || [];
    if (!hs.length) { stopped = 'last page reached'; break; }
    hs.forEach((h, i) => { const row = rowOf(h, page, (page - 1) * 20 + i + 1); if (row) rows.push(row); else unparsed++; });
    if (hs.length < 20) { stopped = 'last page reached'; break; }
  }
  if (!head) return JSON.stringify({ ok: false, error: 'RateHawk answered no page: run the script once more' });
  rows.splice(0, SKIP); rows.splice(LIMIT);                    // keep exactly the window the operator asked for
  const pageHeader = ((document.body.innerText.match(/([\d,]+)\s+accommodation options available/) || [])[1] || '').replace(/,/g, '');
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    check_in: REQ.check_in, check_out: REQ.check_out, adults: REQ.adults, child_ages: REQ.ages || [], residency: REQ.residency, sort: REQ.sort, filters, offset: (START_PAGE - 1) * 20 + SKIP,
    results_total: head.total, search_finished: head.finished, page_header_count: pageHeader ? Number(pageHeader) : null, ...(unparsed ? { unparsed } : {}) }, rows);      // `unparsed` only when a hotel had no rate: the head stays short (a slim part holds 850 characters)
})()
