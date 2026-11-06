// GetYourGuide search: the LIST of activities for a query and a date (comparison only). Run it on www.getyourguide.com/s/?q=...&date_from=...&date_to=... (read only; it books nothing).
// The page draws its cards from ONE call of its own: POST travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks (no cookie needed; the page's own "Show more" button and every filter
// send the same call with a bigger `page` / a `filtersUpdated` list / a `sortingSelected`). The template of that call (location, content id, rule id) is embedded in the page's state
// (window.__INITIAL_STATE__.sdui: the "See more" block, route landing-pages/srp), so the script takes it from there and changes only page, filters, sort and the dates. Read live 6 Nov 2026: 24 cards a page, the same
// cards in the same order as the page; each card holds title, city, "3 hours - Private option available - Skip the line", rating, reviews, badges and the EXACT price object (starting_price, base_price,
// price_category_label "per person" / "per group"); the currency is the accept-currency header (EUR), so the visitor's header menu no longer matters. The tool fills in the request (filters, sort, how many cards) where REQ is set.
await (async () => {
  const REQ = __REQUEST__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|performing security verification|just a moment\.\.\.|checking if the site connection is secure|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'GetYourGuide shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)getyourguide\.com$/.test(location.hostname) || !/^\/s\/?$/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a GetYourGuide search page (www.getyourguide.com/s/?q=...): open the url first' });
  const t0 = performance.now();
  const sdui = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.sdui;
  let template = null;
  const seek = (o, d) => { if (template || d > 60 || !o || typeof o !== 'object') return; if (Array.isArray(o)) { for (const x of o) seek(x, d + 1); return; } if (o.route === 'landing-pages/srp' && o.payload && typeof o.payload === 'object' && 'contentIdentifier' in o.payload) { template = o.payload; return; } for (const k of Object.keys(o)) seek(o[k], d + 1); };
  seek(sdui, 0);
  if (!template) return JSON.stringify({ ok: false, error: 'the page holds no list template (GetYourGuide changed its page, or the search has no result list): say it could not be read' });
  const params = new URLSearchParams(location.search);
  const query = (template.additionalParams && template.additionalParams.q) || params.get('q') || null;
  const dates = template.datesSelected || null;
  const vid = (document.cookie.match(/(?:^|;\s*)visitor_id=([^;]+)/) || [])[1];
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/plain, */*', 'accept-currency': 'EUR', 'accept-language': 'en-US', 'visitor-platform': 'desktop', 'x-gyg-app-type': 'Web' };
  if (vid) headers['visitor-id'] = vid;
  const endpoint = 'https://travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks?' + ['q', 'date_from', 'date_to'].filter((k) => params.get(k)).map((k) => k + '=' + encodeURIComponent(params.get(k))).join('&');
  const PER_PAGE = 24;
  const fetchPage = async (page) => {
    const payload = { ...template, page, injectedCardsCount: 0, filtersUpdated: REQ.filters || [], sortingSelected: REQ.sort || 'popularity', selectedSortingOrderValue: REQ.sort || 'popularity' };
    const res = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify({ payload }) });
    if (!res.ok) throw new Error('answered ' + res.status);
    return res.json();
  };
  const textOf = (o) => (typeof o.text === 'string' ? o.text : (o.text && typeof o.text.text === 'string' ? o.text.text : null));
  const toRow = (card) => {
    const at = {}; let price = null; let link = null; const badges = [];
    const walk = (o, d) => {
      if (d > 40 || !o || typeof o !== 'object') return;
      if (Array.isArray(o)) { for (const x of o) walk(x, d + 1); return; }
      if (typeof o.id === 'string' && o.text !== undefined) { const t = textOf(o); const key = o.id.replace(/^\d+-/, ''); if (t !== null) { if (/-badge$/.test(key)) badges.push(key.replace(/-badge$/, '')); else at[key] = t.trim(); } }
      if (!price && o.formatted_base_price !== undefined) price = o;
      if (!link && o.type === 'openLinkInteractionConfiguration' && typeof o.link === 'string') link = o.link;
      for (const k of Object.keys(o)) walk(o[k], d + 1);
    };
    walk(card, 0);
    const id = ((link || '').match(/tours\/(\d+)/) || [])[1];
    if (!id || !at.title) return null;
    const rating = Number(at['polished-rating-text']); const rev = (at['polished-review-description'] || '').replace(/[(),\s]/g, '');
    const pct = price ? Number(price.unformatted_discount_percentage) || 0 : 0;
    return { id: Number(id), title: at.title, city: at['context-label'] || null, meta: at.attributes || null, rating: Number.isFinite(rating) && at['polished-rating-text'] ? rating : null, reviews: /^\d+$/.test(rev) ? Number(rev) : null,
      cur: price ? price.currency || null : null, from: price && Number.isFinite(price.starting_price) ? price.starting_price : null, was: price && pct > 0 && Number.isFinite(price.base_price) ? price.base_price : null, discount_pct: pct || null,
      per: price && price.price_category_label ? String(price.price_category_label).replace(/^per\s+/i, '').toLowerCase() : null, badges, path: '/-t' + id + '/' };
  };
  const rows = []; const seen = new Set(); const failed = []; let total = null; let visible = null; let pages = 0; let sortEcho = null; let location_id = null;
  const need = Math.ceil((REQ.skip + REQ.limit) / PER_PAGE);
  for (let page = 1; page <= need; page++) {
    let j;
    try { j = await fetchPage(page); } catch (err) { failed.push('page ' + page + ': ' + String(err.message || err).slice(0, 80)); break; }
    pages++;
    const grid = (j.content || []).find((c) => c && c.type === 'grid') || (j.content || [])[0] || {};
    const got = (grid.content || []).map(toRow).filter(Boolean);
    const ev = (j.trackingEvents || []).map((e) => e && (e.event || e)).find((e) => e && e.properties && e.properties.search_results);
    if (ev && page === 1) { total = Number.isFinite(ev.properties.result_count) ? ev.properties.result_count : null; sortEcho = ev.properties.sorting ? ev.properties.sorting.field : null; location_id = ev.properties.extracted_location_details ? ev.properties.extracted_location_details.id : null; }
    visible = got.length;
    let fresh = 0; for (const r of got) { if (!seen.has(r.id)) { seen.add(r.id); rows.push(r); fresh++; } }
    if (!fresh || got.length < PER_PAGE) break;
    if (page < need) await wait(600);
  }
  if (!rows.length) return JSON.stringify({ ok: false, error: failed.length ? 'GetYourGuide did not answer the list (' + failed[0] + '): say it could not be read' : 'GetYourGuide showed no activity cards (a security check page, or a page that did not load). Stop: look at the page, do not retry in a loop, never work around a human check; tell the operator.', cards_on_page: 0 });
  const take = rows.slice(REQ.skip, REQ.skip + REQ.limit).map((r, i) => ({ rank: REQ.skip + i + 1, ...r }));
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    results_total: total, query_text: query, date_from: dates ? dates.fromDate : null, date_to: dates ? dates.toDate : null, currency: 'EUR', sort: REQ.sort || 'popularity', sort_echo: sortEcho, filters_sent: REQ.filters || [], location_id,
    cards_on_page: visible, pages_read: pages, offset: REQ.skip, failed: failed.length ? failed : null, ms: Math.round(performance.now() - t0) }, take);
})()
