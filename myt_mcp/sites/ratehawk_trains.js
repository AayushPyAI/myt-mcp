// RateHawk trains: the page's OWN data, read instead of its cards (read only; the only click is the page's own "Load more" button, as before). Run it in the operator's logged-in RateHawk train RESULTS tab.
// The railway page is a Next.js page (read live 7 Nov 2026): its first offers (15 for Roma Termini to Firenze S.M. Novella) are inside the page itself ("defaultValue":{"offers":{"one_way":[...]}, "search_id", "next_pagination_token"})
// and "Load more" asks the page's server action for the next batch with that token (13 offers, then a new token; one answer takes up to 12 s). The script reads the embedded list, presses the page's own "Load more" and
// takes the offers from the page's own answers (it never calls an action of its own: the page has four and only the page knows which is which). An offer: the train legs (station, time, train number, carrier), the duration,
// and the "from" price and the highest price of each class (standard / comfort / premier) for the whole group. Checked against the page: 28 offers (15 embedded + 13 loaded) in the same order, with the departure and arrival
// times, train numbers and the three class prices equal on every card. The filters of the page (direct, up to 1 change, a class) are applied by the page in the browser without any call, so they are applied here on the loaded
// offers (direct = one train leg; a class = the offer has a price in it). The tool replaces __CHANGES__ ("Direct route", "Up to 1 change of train" or ""), __CLASS__ ("Standard", "Comfort", "Premier" or ""), __SKIP__ and
// __LIMIT__ (the window of the filtered list). A login page stops the script: never worked around.
await (async () => {
  const CHANGES = "__CHANGES__"; const CLASS = "__CLASS__"; const SKIP = __SKIP__; const LIMIT = __LIMIT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/(^|\.)ratehawk\.com$/.test(location.hostname) || !location.pathname.startsWith('/railway')) return JSON.stringify({ ok: false, error: 'not a RateHawk train results page: open the url first' });
  if (/log in|sign in|forgot password/i.test((document.body && document.body.innerText || '').slice(0, 600)) && !(window.dataLayer || []).some((x) => x && x.user_email)) return JSON.stringify({ ok: false, error: 'RateHawk asks to log in: stop and tell the operator to log in (never type a password).' });
  const t0 = performance.now();
  const readEmbedded = () => {
    const txt = [...document.scripts].filter((s) => !s.src).map((s) => s.textContent).join('\n');
    const re = /self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)/g; let m; const parts = [];
    while ((m = re.exec(txt))) { try { parts.push(JSON.parse(m[1])); } catch (e) { /* a cut chunk */ } }
    const joined = parts.join(''); const i = joined.indexOf('"one_way"'); if (i < 0) return null;
    const line = joined.slice(joined.lastIndexOf('\n', i) + 1, joined.indexOf('\n', i)); let data = null;
    try { data = JSON.parse(line.slice(line.indexOf(':') + 1)); } catch (e) { return null; }
    let found = null; const walk = (o, d) => { if (found || d > 60 || !o || typeof o !== 'object') return; if (!Array.isArray(o) && o.offers && Array.isArray(o.offers.one_way)) { found = o; return; } for (const k of Object.keys(o)) walk(o[k], d + 1); };
    walk(data, 0); return found;
  };
  let dv = null;
  for (let i = 0; i < 40 && !dv; i++) { dv = readEmbedded(); if (!dv) await wait(500); }
  if (!dv) return JSON.stringify({ ok: false, error: 'the page has not shown its trains (nothing embedded after 20 s: logged out, no trains for this search, or RateHawk changed its page): open the url again and run the script once more' });
  const captured = []; const realFetch = window.fetch;
  window.fetch = async function (i, o) {      // only READS the page's own server-action answers (text/x-component line 1 with offers)
    const r = await realFetch.apply(this, arguments);
    try { if (o && o.method === 'POST' && new Headers(o.headers || {}).get('next-action')) r.clone().text().then((tx) => { const line = tx.split('\n').find((l) => l.startsWith('1:')); if (line) { try { const j = JSON.parse(line.slice(2)); if (j && j.offers) captured.push(j); } catch (e) { /* not a list */ } } }); } catch (e) { /* never break the page */ }
    return r;
  };
  const offers = [...dv.offers.one_way]; const seen = new Set(offers.map((o) => o.id)); let token = dv.next_pagination_token || null;
  const passes = (o) => (!CHANGES || (CHANGES === 'Direct route' ? (o.full_route || []).length === 1 : (o.full_route || []).length <= 2)) && (!CLASS || ((o.prices || {}).comfort_categories || []).some((c) => c.id === CLASS.toLowerCase()));
  try {
    while (offers.filter(passes).length < SKIP + LIMIT && token && performance.now() - t0 < 32000) {
      const btn = [...document.querySelectorAll('button')].find((b) => (b.innerText || '').trim() === 'Load more');
      if (!btn) break;
      const before = captured.length; btn.click();
      for (let k = 0; k < 40 && captured.length === before && performance.now() - t0 < 42000; k++) await wait(500);
      if (captured.length === before) break;
      const j = captured[captured.length - 1];
      for (const o of j.offers.one_way || []) if (!seen.has(o.id)) { seen.add(o.id); offers.push(o); }
      token = j.next_pagination_token || null;
    }
  } finally { window.fetch = realFetch; }
  const matching = offers.filter(passes);
  const rowOf = (o, rank) => {
    const legs = (o.full_route || []).map((s) => ({ from: s.departure && s.departure.station, to: s.arrival && s.arrival.station, dep: s.departure && s.departure.datetime, arr: s.arrival && s.arrival.datetime, train: s.train_number, brand: s.carrier && (s.carrier.marketing_information || s.carrier.brand || s.carrier.name), operator: s.carrier && s.carrier.operating_company }));
    const p = o.prices || {};
    return { rank, id: o.id, supplier: o.supplier, legs, dep: legs.length ? legs[0].dep : null, arr: legs.length ? legs[legs.length - 1].arr : null, minutes: o.duration, changes: Math.max(0, legs.length - 1),
      classes: (p.comfort_categories || []).map((c) => ({ id: c.id, from: c.min_price, to: c.max_price })), cur: p.currency_code || null, services: o.services || [], seat_reservation: !!o.seat_reservation };
  };
  const rows = matching.slice(SKIP, SKIP + LIMIT).map((o, i) => rowOf(o, SKIP + i + 1));
  const q = new URLSearchParams(location.search);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    search: { from: q.get('from'), to: q.get('to'), date: q.get('date'), time: q.get('time'), adt: q.get('adt') }, filters: { changes: CHANGES || null, class: CLASS || null }, offset: SKIP, loaded: offers.length, matching: matching.length,
    all_loaded: !token, ms: Math.round(performance.now() - t0) }, rows);
})()
