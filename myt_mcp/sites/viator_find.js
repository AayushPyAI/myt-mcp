// Viator search list reader. Run it on a Viator search page (www.viator.com/searchResults/all[/N]?text=...&filters; read only).
// Viator's server renders each search page with the page's own data embedded as JSON (<script id="globalState">, pageModel.preloadedData.search): the script reads the products from THAT data (title, from price and currency,
// the crossed-out price, rating and review count, duration, free cancellation, badges, offered languages) and takes each product's link from the page's own card anchors; it does not read text off the cards. The search filters
// (duration, rating, price, language, one feature, the sort) are part of the page address, so the page already holds the filtered list. When more than one page is wanted it asks the same address for the next pages (one
// request each, a pause between them) and reads them the same way. It books nothing. The tool replaces __REQUEST__ (what to read).
await (async () => {
  const REQ = __REQUEST__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|performing security verification|just a moment\.\.\.|checking if the site connection is secure|verify you are human|access denied|unusual traffic|are you a robot|blocked/i.test(text().slice(0, 1500)) && !document.getElementById('globalState')) return JSON.stringify({ ok: false, error: 'Viator shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)viator\.com$/.test(location.hostname) || !/\/searchResults\//.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Viator search page (www.viator.com/searchResults/all?text=...): open the url first' });
  const t0 = performance.now();
  const parse = (doc) => {
    const el = doc.getElementById('globalState'); if (!el) return null;
    let g; try { g = JSON.parse(el.textContent); } catch (err) { return null; }
    const s = (((g.__PRELOADED_DATA__ || {}).pageModel || {}).preloadedData || {}).search;
    if (!s || !Array.isArray(s.results)) return null;
    const links = {};
    doc.querySelectorAll('a[href*="/tours/"]').forEach((a) => { const h = (a.getAttribute('href') || '').split('?')[0]; const m = h.match(/\/d\d+-([A-Za-z0-9_.]+)\/?$/); if (m && !links[m[1]]) links[m[1]] = h; });
    return { s, links };
  };
  const first = parse(document);
  if (!first) return JSON.stringify({ ok: false, error: 'the page has no search data (Viator changed its page or the page is not loaded yet): say it could not be read' });
  const PAGE_SIZE = 24;
  const pageOf = (path) => Number((path.match(/\/searchResults\/all\/(\d+)/) || [])[1] || 1);
  const startPage = pageOf(location.pathname);
  const minutes = (it) => {
    const d = it.itinerary && it.itinerary.duration; if (!d) return { lo: null, hi: null, unit: null };
    const k = { MINUTES: 1, HOURS: 60, DAYS: 1440 }[d.unit];
    if (!k) return { lo: null, hi: null, unit: d.unit || null };
    if (d.duration != null) return { lo: d.duration * k, hi: d.duration * k, unit: d.unit };
    if (d.from != null && d.to != null) return { lo: d.from * k, hi: d.to * k, unit: d.unit };
    return { lo: null, hi: null, unit: d.unit };
  };
  const toRows = (p, pageNo) => p.s.results.map((r, i) => {
    const it = r.item || {}; const pi = it.pricingInfo || {}; const from = pi.fromPrice || {}; const rs = it.reviewSummary || {}; const m = minutes(it);
    return { rank: (pageNo - 1) * PAGE_SIZE + i + 1, code: it.productCode || null, title: (it.title && it.title.text) || null, path: p.links[it.productCode] || null, dest: (it.primaryDestination && it.primaryDestination.name) || null,
      mins_from: m.lo, mins_to: m.hi, dur_unit: m.unit, free_cancel: it.cancellationPolicy ? it.cancellationPolicy.freeCancellation === true : null,
      rating: Number.isFinite(rs.exactRating) && rs.count > 0 ? rs.exactRating : null, reviews: Number.isFinite(rs.count) ? rs.count : null,
      price: Number.isFinite(from.amount) ? from.amount : null, cur: from.currency || null, was: pi.comparisonPrice && Number.isFinite(pi.comparisonPrice.amount) ? pi.comparisonPrice.amount : null,
      saved: pi.amountSaved && Number.isFinite(pi.amountSaved.amount) ? pi.amountSaved.amount : null, varies: pi.priceVariesByGroupSize === true, pricing_type: pi.pricingType || null,
      badges: (it.productBadges || []).map((b) => b.type).filter(Boolean), langs: (it.offeredLanguages || []).map((l) => l.code).filter(Boolean) };
  });
  let rows = toRows(first, startPage); let total = first.s.totalResults; let pagesRead = 1; let lastCount = first.s.results.length;
  const want = Math.max(1, Math.min(9 - startPage + 1, Number(REQ.pages) || 1));
  const failed = [];
  for (let k = 1; k < want && lastCount === PAGE_SIZE; k++) {
    await wait(1200);
    const pageNo = startPage + k;
    try {
      const res = await fetch(location.pathname.replace(/\/searchResults\/all(\/\d+)?/, '/searchResults/all/' + pageNo) + location.search, { credentials: 'same-origin', headers: { Accept: 'text/html' } });
      if (!res.ok) throw new Error('answered ' + res.status);
      const next = parse(new DOMParser().parseFromString(await res.text(), 'text/html'));
      if (!next) throw new Error('no search data in the page');
      rows = rows.concat(toRows(next, pageNo)); pagesRead++; lastCount = next.s.results.length; total = next.s.totalResults != null ? next.s.totalResults : total;
    } catch (err) { failed.push('page ' + pageNo + ': ' + String(err.message || err).slice(0, 60)); break; }
  }
  const qs = new URLSearchParams(location.search);
  const filters = {}; qs.forEach((v, k) => { if (k !== 'text') filters[k] = v; });
  const f = first.s.filters || {};
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    query_text: qs.get('text'), results_total: total, page: startPage, pages_read: pagesRead, shown_range: rows.length ? `${rows[0].rank}-${rows[rows.length - 1].rank}` : null, sort: qs.get('sortType') || 'featured', url_filters: filters,
    lang_keys: (f.languages || []).map((x) => x.key).filter(Boolean), features_available: (f.additionalFilters || []).filter((x) => x.available).map((x) => x.key), failed_pages: failed.length ? failed : null, ms: Math.round(performance.now() - t0) }, rows);
})()
