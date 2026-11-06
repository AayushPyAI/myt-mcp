// CP (Comboios de Portugal) journey reader. Run it on ANY page of www.cp.pt (read only; no results page and no cards are needed).
// CP's own pages get their trains with ONE request, POST <travelApiUrl>/journeys (body: stations, date, classes, passengers, train types): the script sends that same request from the page, with the keys the page itself
// loads from its public /fe-config.json (same site, nothing sent elsewhere), and reads every train with its times, services, changes and prices (per person and for the whole group, normal and promo, with the
// promo's restriction such as NON_REFUNDABLE) as CP's own data, not as text off cards. When the operator gave a departure time wish it also asks CP's own time filter (limitType 2 = departures between start and end)
// and joins the two lists; a return day is searched in the SAME call (`returnDate`: the answer's `returnTrip` is the way back, with its own time window); the train types the operator wants go to CP's own `services`
// filter. It books nothing. The tool replaces __REQUEST__ (what to search).
await (async () => {
  const REQ = __REQUEST__;
  const text = () => (document.body && document.body.innerText) || '';
  if (!/(^|\.)cp\.pt$/.test(location.hostname)) return JSON.stringify({ ok: false, error: 'not a cp.pt page: open https://www.cp.pt/en first' });
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'CP shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  let cfg;
  try { const r = await fetch('/fe-config.json', { credentials: 'same-origin' }); if (!r.ok) throw new Error('answered ' + r.status); cfg = await r.json(); }
  catch (err) { return JSON.stringify({ ok: false, error: 'CP\'s page configuration could not be read (' + String(err).slice(0, 60) + '): say it could not be read' }); }
  if (!cfg || !cfg.travelApiUrl || !cfg.travelApiKey || !cfg.xcck || !cfg.xccs) return JSON.stringify({ ok: false, error: 'CP\'s page configuration has no travel service entries (the site changed): say it could not be read' });
  const headers = { Accept: 'application/json', 'X-Api-Key': cfg.travelApiKey, 'x-cp-connect-id': cfg.xcck, 'x-cp-connect-secret': cfg.xccs };
  const t0 = performance.now();
  let stations; let rules = [];
  try {
    const [rs, rr] = await Promise.all([fetch(cfg.travelApiUrl + '/stations', { headers }), fetch(cfg.travelApiUrl + '/rules', { headers }).catch(() => null)]);
    if (!rs.ok) throw new Error('answered ' + rs.status);
    stations = await rs.json();
    if (rr && rr.ok) rules = await rr.json().catch(() => []);
  } catch (err) { return JSON.stringify({ ok: false, error: 'CP\'s station list could not be read (' + String(err).slice(0, 60) + '): say it could not be read' }); }
  const rule = (k) => { const x = (Array.isArray(rules) ? rules : []).find((r) => r.ruleKey === k); const n = x ? parseInt(x.value, 10) : NaN; return Number.isFinite(n) ? n : null; };
  const nameOf = (code) => ((Array.isArray(stations) ? stations : []).find((s) => s.code === code) || {}).designation || null;
  const from = nameOf(REQ.origin_code); const to = nameOf(REQ.destination_code);
  if (!from || !to) return JSON.stringify({ ok: false, error: 'CP has no station with the code ' + (!from ? REQ.origin_code : REQ.destination_code) + ': ask the operator for the station name again' });
  const PLAIN = { startTime: '00:00', endTime: '23:59', limitType: 0 };
  const win = (w) => (w && (w.earliest || w.latest) ? { startTime: w.earliest || '00:00', endTime: w.latest || '23:59', limitType: 2 } : null);      // limitType 0 = no limit, 1 = arrivals in the window, 2 = departures in the window, 3 = departures from the start (read live 5 Nov 2026)
  const WIN = win(REQ.window); const WINB = REQ.return_day ? win(REQ.back_window) : null;
  const makeBody = (out, back) => ({ departureStationCode: REQ.origin_code, arrivalStationCode: REQ.destination_code, travelDate: REQ.day, returnDate: REQ.return_day || null, classes: [REQ.first_class ? 1 : 2], configID: 200, lang: 'EN',
    quantities: [{ quantity: REQ.passengers, type: 1 }], searchType: 3, services: Array.isArray(REQ.services) ? REQ.services : [], timeLimit: out, returnTimeLimit: back, saleableOnly: false, username: 'sivNetticket' });
  const search = async (out, back) => {
    const res = await fetch(cfg.travelApiUrl + '/journeys', { method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(makeBody(out, back)) });
    if (!res.ok) { let m = ''; try { const e = await res.json(); m = e.message || e.label || ''; } catch (err) { /* the status says it */ } throw new Error('CP\'s journeys service answered ' + res.status + (m ? ': ' + String(m).slice(0, 120) : '')); }
    return res.json();
  };
  let j; let jw = null;
  try {
    j = await search(PLAIN, PLAIN);
    if (WIN || WINB) jw = await search(WIN || PLAIN, WINB || PLAIN);
  } catch (err) { return JSON.stringify({ ok: false, error: String(err.message || err).slice(0, 200) + ': say it could not be read' }); }
  const ms = Math.round(performance.now() - t0);
  const tripKey = (t) => (t.departureTime || '') + '>' + (t.arrivalTime || '') + '|' + (t.travelSections || []).map((x) => x.trainNumber).join('+');
  const join = (plain, windowed) => { const base = Array.isArray(plain) ? plain : []; const known = new Set(base.map(tripKey)); const extra = (Array.isArray(windowed) ? windowed : []).filter((t) => !known.has(tripKey(t))); return { base, extra }; };
  const O = join(j.outwardTrip, jw && jw.outwardTrip); const B = join(j.returnTrip, jw && jw.returnTrip);
  const cls = REQ.first_class ? 1 : 2;
  const eur = (cents) => (Number.isFinite(cents) ? cents / 100 : null);
  const toRow = (t, leg, isExtra) => {
    const prices = (t.basePrices || []).filter((p) => p.travelClass === cls);
    const by = (type) => prices.find((p) => p.priceType === type) || null;
    const normalGroup = by(100); const promoGroup = by(104); const normalPp = by(1); const promoPp = by(4);
    const secs = t.travelSections || [];
    return { leg, dep: t.departureTime || null, arr: t.arrivalTime || null, dur: t.duration || null, changes_n: Number.isInteger(t.transferCount) ? t.transferCount : null,
      services: secs.map((s) => ((s.serviceCode || {}).designation || (s.serviceCode || {}).code || '')).filter(Boolean), codes: secs.map((s) => (s.serviceCode || {}).code).filter(Boolean), trains: secs.map((s) => s.trainNumber).filter((x) => x != null),
      cls: cls, price_normal: eur(normalGroup && normalGroup.centsValue), price_promo: eur(promoGroup && promoGroup.centsValue), pp_normal: eur(normalPp && normalPp.centsValue), pp_promo: eur(promoPp && promoPp.centsValue),
      promo_limits: ((promoGroup || promoPp || {}).constraints || []).map((c) => c.code || JSON.stringify(c).slice(0, 40)), normal_limits: ((normalGroup || normalPp || {}).constraints || []).map((c) => c.code || JSON.stringify(c).slice(0, 40)),
      price_types: prices.map((p) => p.priceType), saleable: t.saleableOnline === true, bike: t.bike != null ? t.bike : null, mobility: t.mobility != null ? t.mobility : null, from_window: isExtra };
  };
  const outRows = [...O.base.map((t) => toRow(t, 'out', false)), ...O.extra.map((t) => toRow(t, 'out', true))];
  const backRows = REQ.return_day ? [...B.base.map((t) => toRow(t, 'back', false)), ...B.extra.map((t) => toRow(t, 'back', true))] : [];
  const rows = [...outRows, ...backRows];
  const notices = (Array.isArray(j.messages) ? j.messages : []).map((m) => String((m && m.text) || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 240)).filter(Boolean);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    origin: { code: REQ.origin_code, name: from }, destination: { code: REQ.destination_code, name: to }, day: j.travelDate || REQ.day, passengers: REQ.passengers, cls: cls, no_results: !rows.length, trips_total: rows.length, out_total: outRows.length, back_total: backRows.length, return_day: REQ.return_day || null, services_sent: Array.isArray(REQ.services) && REQ.services.length ? REQ.services : null, trips_unfiltered: O.base.length + (REQ.return_day ? B.base.length : 0), window_sent: WIN, window_back_sent: WINB, window_extra: O.extra.length + (REQ.return_day ? B.extra.length : 0), stations_total: Array.isArray(stations) ? stations.length : null, calendar_limit_days: rule('calendar_limit'), max_tickets: rule('max_tickets_qty'), min_wait_minutes: rule('dep_after_arr_limit'), ms, notices, viewport: window.innerWidth }, rows);
})()
