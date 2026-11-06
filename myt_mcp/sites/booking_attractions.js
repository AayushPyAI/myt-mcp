// Booking.com attractions list reader (comparison only). Run it on a Booking.com attractions results page (www.booking.com/attractions/searchresults/<country>/<city>.html; read only; it books nothing).
// The page's data is Booking.com's own: the first 15 activities (and the filter counts) are embedded in the page as an Apollo store (<script data-capla-store-data="apollo">: attractionsProduct.searchProducts with
// the products, `filterStats` = how many activities match and how many exist, `pagination.hasNextPage`), and the page loads the next 15 with each scroll from ONE GraphQL request, operation SearchResultsProducts at
// accommodations.booking.com/dml/graphql (input: ufi, limit 15, page N, source, and the filters as filterByLabel / filterByMinRating / filterBySupportedLanguage / sortBy). The script reads page 1 of the page's own sort from the
// embedded data and sends that same request, with a compact query for just the fields it needs (checked live 5 Nov 2026: page 1 equals the embedded one on all 15 activities), for the next pages and for the second sort
// (the agency reads Our top picks and Best reviewed together), one request at a time with a pause. The tool replaces __REQUEST__ (what to read).
await (async () => {
  const REQ = __REQUEST__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  const where = location.pathname.match(/^\/attractions\/searchresults\/([a-z]{2}\/[a-z0-9-]+?)(?:\.[a-z-]+)?\.html$/);
  if (!/(^|\.)booking\.com$/i.test(location.hostname) || !where) return JSON.stringify({ ok: false, error: 'not a Booking.com attractions results page (www.booking.com/attractions/searchresults/pt/lisbon.html): open the url first' });
  const t0 = performance.now();
  const el = document.querySelector('script[data-capla-store-data="apollo"]');
  let store = null; try { store = el ? JSON.parse(el.textContent) : null; } catch (err) { store = null; }
  const root = store && store.ROOT_QUERY && store.ROOT_QUERY.attractionsProduct;
  if (!root) return JSON.stringify({ ok: false, error: 'the page has no activity data (Booking.com changed its page or it is not loaded yet): say it could not be read' });
  const searches = Object.keys(root).filter((k) => k.startsWith('searchProducts:')).map((k) => ({ input: (JSON.parse(k.slice('searchProducts:'.length)) || {}).input || {}, value: root[k] }));
  const listEntry = searches.find((s) => s.input.limit > 0); const statsEntry = searches.find((s) => s.input.extractFilterStats);
  if (!listEntry) return JSON.stringify({ ok: false, error: 'the page holds no activity list (Booking.com changed its page): say it could not be read' });
  const ufi = listEntry.input.ufi;
  const pageFilters = { filterByLabel: listEntry.input.filterByLabel || [], filterByMinRating: listEntry.input.filterByMinRating || [], filterBySupportedLanguage: listEntry.input.filterBySupportedLanguage || [] };
  const same = (a, b) => JSON.stringify([...(a || [])].sort()) === JSON.stringify([...(b || [])].sort());
  const filtersMatch = ['filterByLabel', 'filterByMinRating', 'filterBySupportedLanguage'].every((k) => same(pageFilters[k], (REQ.filters || {})[k]));
  const pageSort = listEntry.input.sortBy || 'trending';
  const deref = (x) => { if (Array.isArray(x)) return x.map(deref); if (x && typeof x === 'object') { if (x.__ref) return deref(store[x.__ref]); const o = {}; for (const [k, v] of Object.entries(x)) if (k !== '__typename') o[k] = deref(v); return o; } return x; };
  const stats = statsEntry && filtersMatch ? deref(statsEntry.value).filterStats || null : null;
  const params = new URLSearchParams(location.search);
  const QUERY = 'query SearchResultsProducts($input: AttractionsProductSearchInput!, $contextParams: AttractionsContextParamsInput) { attractionsProduct { searchProducts(input: $input, contextParams: $contextParams) { ... on AttractionsProductSearchResponse { pagination { hasNextPage } products { id slug name availableFrom bookingWindowDays guideSupportedLanguagesLabels { code label } audioSupportedLanguagesLabels { code label } duration { label min max type value } cancellationPolicy { comparedTo hasFreeCancellation isStillRefundable label message percentage period until } reviewsStats { combinedNumericStats { average total scale } } representativePrice { chargeAmount currency publicAmount discounts { __typename } } labels { text type } flags { flag value rank label } primaryLabel { text type } } } } } }';
  const html = document.documentElement.innerHTML; const grab = (re) => (html.match(re) || [])[1] || null;
  const headers = { accept: '*/*', 'content-type': 'application/json', 'x-booking-site-type-id': '1', 'x-booking-context-action': 'attractions', 'x-booking-context-action-name': 'attractions', 'x-booking-topic': 'capla_browser_b-attractions-product-frontend-capla' };
  if (grab(/"csrfToken":"([^"]+)"/)) headers['x-booking-csrf-token'] = grab(/"csrfToken":"([^"]+)"/);
  if (grab(/"pageviewId":"([^"]+)"/)) headers['x-booking-pageview-id'] = grab(/"pageviewId":"([^"]+)"/);
  if (params.get('aid')) headers['x-booking-context-aid'] = params.get('aid');
  const endpoint = new URL('https://accommodations.booking.com/dml/graphql'); ['aid', 'label', 'date_from', 'date_to', 'adults', 'selected_currency'].forEach((k) => { if (params.get(k)) endpoint.searchParams.set(k, params.get(k)); }); endpoint.searchParams.set('lang', 'en-gb');
  const contextParams = { requestUrl: location.origin + location.pathname, urlCode: '', test: false, showInactive: false, source: '', adPlat: '', label: params.get('label') || '' };
  const fetchPage = async (sortKey, page) => {
    const input = { ufi, limit: 15, page, source: 'search_results', ...(sortKey && sortKey !== 'trending' ? { sortBy: sortKey } : {}) };
    for (const k of ['filterByLabel', 'filterByMinRating', 'filterBySupportedLanguage']) if (((REQ.filters || {})[k] || []).length) input[k] = REQ.filters[k];
    const res = await fetch(endpoint.toString(), { method: 'POST', credentials: 'include', headers, body: JSON.stringify({ operationName: 'SearchResultsProducts', variables: { input, contextParams }, extensions: {}, query: QUERY }) });
    if (!res.ok) throw new Error('answered ' + res.status);
    const j = await res.json();
    if (j.errors && j.errors.length) throw new Error(String(j.errors[0].message || 'query refused').slice(0, 80));
    const sp = j && j.data && j.data.attractionsProduct && j.data.attractionsProduct.searchProducts;
    if (!sp || !Array.isArray(sp.products)) throw new Error('no activity list in the answer');
    return { products: sp.products, next: !!(sp.pagination && sp.pagination.hasNextPage) };
  };
  const toRow = (p, sort, rank) => {
    const price = p.representativePrice || {}; const cs = ((p.reviewsStats || {}).combinedNumericStats) || {}; const cp = p.cancellationPolicy || {}; const d = p.duration || {};
    const best = (p.flags || []).find((f) => f.flag === 'bestseller' && f.value);
    return { sort, rank, id: p.id || null, title: p.name || null, slug: p.slug || null, cur: price.currency || null, from: Number.isFinite(price.chargeAmount) ? price.chargeAmount : null, public_from: Number.isFinite(price.publicAmount) ? price.publicAmount : null, discounted: (price.discounts || []).length > 0,
      rating5: Number.isFinite(cs.average) ? cs.average : null, reviews: Number.isFinite(cs.total) ? cs.total : null, scale: cs.scale || null, duration: d.label ? d.label.replace(/^Duration:\s*/i, '') : null, duration_iso: d.value || null, duration_type: d.type || null,
      available_from: p.availableFrom || null, booking_window_days: Number.isFinite(p.bookingWindowDays) ? p.bookingWindowDays : null, guide_langs: (p.guideSupportedLanguagesLabels || []).map((l) => l.label || l.code).filter(Boolean), audio_langs: (p.audioSupportedLanguagesLabels || []).map((l) => l.label || l.code).filter(Boolean),
      free_cancel: cp.hasFreeCancellation === true, refundable_now: cp.isStillRefundable === true, cancel_until: cp.until || null, cancel_period: cp.period || null, labels: (p.labels || []).map((l) => l.type).filter(Boolean),
      flags: (p.flags || []).filter((f) => f.value).map((f) => f.flag), best_seller: best ? best.rank : null, best_seller_text: best ? best.label : null, primary_label: p.primaryLabel ? p.primaryLabel.text : null };
  };
  const rows = []; const sorts = []; const failed = [];
  for (const sort of REQ.sorts) {
    let list = []; let page = 1; let next = true; let source = 'api';
    if (sort.key === pageSort && filtersMatch) { list = deref(listEntry.value.products || []); next = !!(listEntry.value.pagination && listEntry.value.pagination.hasNextPage); source = 'page'; page = 2; }
    while (list.length < REQ.limit && next) {
      try { const r = await fetchPage(sort.key, page); list = list.concat(r.products); next = r.next; page++; }
      catch (err) { failed.push(sort.label + ' page ' + page + ': ' + String(err.message || err).slice(0, 80)); next = false; break; }
      if (list.length < REQ.limit && next) await wait(600);
    }
    const take = list.slice(0, REQ.limit); take.forEach((p, i) => rows.push(toRow(p, sort.label, i + 1)));
    sorts.push({ sort: sort.label, key: sort.key, read: take.length, has_next: next, first_page_from: source });
    await wait(600);
  }
  if (!rows.length) return JSON.stringify({ ok: false, error: 'Booking.com gave no activity (' + (failed[0] || 'an empty list') + '): say it could not be read, never that there are none' });
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    place: where[1], country: where[1].split('/')[0], searched: { place: where[1], day: params.get('date_from'), day_to: params.get('date_to'), adults: parseInt(params.get('adults') || '', 10) || null, currency: params.get('selected_currency') || null, filters: REQ.filters },
    page_filters: pageFilters, filters_match: filtersMatch, ufi, results_matching: stats && Number.isFinite(stats.filteredProductCount) ? stats.filteredProductCount : null, results_in_city: stats && Number.isFinite(stats.unfilteredProductCount) ? stats.unfilteredProductCount : null,
    sorts, failed: failed.length ? failed : null, ms: Math.round(performance.now() - t0) }, rows);
})()
