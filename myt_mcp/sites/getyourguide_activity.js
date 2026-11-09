// GetYourGuide activity: the EXACT price of ONE activity for a date and a group (comparison only). Run it on the activity's page (www.getyourguide.com/<place>/<slug>-t<id>/; read only; it books nothing).
// The page's booking box gets its options from ONE call of its own: POST travelers-api.getyourguide.com/user-interface/activity-details-page/blocks with two events (bookingAssistantInputsChanged and participantsSelected:
// the date and the travellers per category id) and the payload of the booking box (contentIdentifier bookingAssistantConfiguratorContentIdentifier). Its answer holds the option cards (title, duration, guide language,
// "Cancel for free until Dec 16", meeting point, spots left) and a tracking event WebCheckTourAvailabilityAction with the structured data: the traveller categories with their age ranges, every available option with its languages,
// its start times each with the price of the WHOLE group, and the price per person by category (read live 6 Nov 2026: 2 adults 140.00 = the page's Total; 2 adults + 1 child 175 = 2 x 70 + 35). The categories (id, title, ages) are in the page's
// embedded state (window.__INITIAL_STATE__.sdui: participantSelector). The script puts every traveller in the category whose age range holds the age (the adults in the one that holds an adult), sends that call for the day the operator asked
// (no date picker and no stepper is touched, "Check availability" is not pressed) and never presses a booking button. The tool fills in the request where REQ is set.
await (async () => {
  const REQ = __REQUEST__;
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|performing security verification|just a moment\.\.\.|checking if the site connection is secure|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'GetYourGuide shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  const where = location.pathname.match(/-t(\d+)\/?$/);
  if (!/(^|\.)getyourguide\.com$/.test(location.hostname) || !where) return JSON.stringify({ ok: false, error: 'not a GetYourGuide activity page (…-t12345): open the url first' });
  const t0 = performance.now();
  const id = Number(where[1]);
  if (REQ.id && REQ.id !== id) return JSON.stringify({ ok: false, error: 'the page is the activity ' + id + ', not ' + REQ.id + ': open the url again' });
  const sdui = window.__INITIAL_STATE__ && window.__INITIAL_STATE__.sdui;
  let box = null; let fromPrice = null;
  const seek = (o, d) => { if (d > 60 || !o || typeof o !== 'object') return; if (Array.isArray(o)) { for (const x of o) seek(x, d + 1); return; } if (!box && o.participantSelector && Array.isArray(o.participantSelector.participants)) box = o.participantSelector.participants; if (!fromPrice && o.fromPriceAtPageLoad && typeof o.fromPriceAtPageLoad === 'object') fromPrice = o.fromPriceAtPageLoad; for (const k of Object.keys(o)) seek(o[k], d + 1); };
  seek(sdui, 0);
  if (!box || !box.length) return JSON.stringify({ ok: false, error: 'the page has no traveller categories (GetYourGuide changed its page, or the activity cannot be booked online): say it could not be read' });
  const cats = box.map((c) => ({ id: c.categoryId, title: c.title, min: c.minimumAge, max: c.maximumAge, kind: c.participantType, autonomous: c.isAutonomous, most: c.maximumParticipants }));
  const holds = (c, age) => (c.min == null || age >= c.min) && (c.max == null || age <= c.max);
  const PEOPLE = ['individual', 'group'];      // 'group' = ONE category that holds everybody (private tours: "Participants, age 99 and younger", count = the number of people; read live 6 Nov 2026 on -t63541)
  if (cats.some((c) => c.kind && !PEOPLE.includes(c.kind))) return JSON.stringify({ ok: false, error: 'this activity is priced by a category that is not a person (' + cats.filter((c) => c.kind && !PEOPLE.includes(c.kind)).map((c) => c.title).join(', ') + '): set the group on the page by hand and say the price could not be read by the script' });
  const count = new Map(); const unfit = [];
  const adultCat = cats.find((c) => holds(c, 30));
  if (REQ.adults) { if (adultCat) count.set(adultCat.id, (count.get(adultCat.id) || 0) + REQ.adults); else unfit.push('adult'); }
  for (const age of REQ.ages || []) { const c = cats.find((x) => holds(x, age)); if (c) count.set(c.id, (count.get(c.id) || 0) + 1); else unfit.push(String(age)); }
  const used = cats.map((c) => ({ ...c, count: count.get(c.id) || 0 }));
  if (unfit.length) return emit({ ok: true, path: location.pathname, id, activity: (document.querySelector('h1') || {}).innerText || document.title, day: REQ.day, travellers: { adults: REQ.adults, ages: REQ.ages || [] }, categories: cats, no_category_for: unfit, availability: null }, []);
  const params = new URLSearchParams(location.search);
  const vid = (document.cookie.match(/(?:^|;\s*)visitor_id=([^;]+)/) || [])[1];
  const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/plain, */*', 'accept-currency': 'EUR', 'accept-language': 'en-US', 'visitor-platform': 'desktop', 'x-gyg-app-type': 'Web' };
  if (vid) headers['visitor-id'] = vid;
  const participants = used.map((c) => ({ categoryId: c.id, count: c.count }));
  const from = 'bookingAssistantConfiguratorContentIdentifier';
  const body = { events: [{ event: { type: 'bookingAssistantInputsChanged', emitterId: from, payload: { participants, language: '', selectedDate: REQ.day, hasButtonBeenClickedWithValidForm: true } } }, { event: { type: 'participantsSelected', emitterId: from, payload: { participants } } }],
    payload: { activityId: id, templateName: 'ActivityDetails', contentIdentifier: from, datesSelected: { fromDate: REQ.day, toDate: REQ.day }, hasButtonBeenClickedWithValidForm: false, reviewsExperiments: [], ...(fromPrice ? { fromPriceAtPageLoad: fromPrice } : {}) } };
  let j;
  try {
    const res = await fetch('https://travelers-api.getyourguide.com/user-interface/activity-details-page/blocks?date_from=' + REQ.day + '&date_to=' + REQ.day, { method: 'POST', headers, body: JSON.stringify(body) });
    if (!res.ok) throw new Error('answered ' + res.status);
    j = await res.json();
  } catch (err) { return JSON.stringify({ ok: false, error: 'GetYourGuide\'s availability service could not be read (' + String(err.message || err).slice(0, 80) + '): say it could not be read' }); }
  const textOf = (o) => (typeof o.text === 'string' ? o.text : (o.text && typeof o.text.text === 'string' ? o.text.text : null));
  const linesOf = (root) => { const out = []; const walk = (o, d) => { if (d > 60 || !o || typeof o !== 'object') return; if (Array.isArray(o)) { for (const x of o) walk(x, d + 1); return; } const t = textOf(o); if (t && t.trim()) out.push(t.trim()); for (const k of Object.keys(o)) { if (k !== 'text') walk(o[k], d + 1); } }; walk(root, 0); return [...new Set(out)]; };
  const cardNodes = {}; const findCards = (o, d) => { if (d > 60 || !o || typeof o !== 'object') return; if (Array.isArray(o)) { for (const x of o) findCards(x, d + 1); return; } const m = typeof o.id === 'string' && o.id.match(/^carousel-option-card-(\d+)/); if (m) cardNodes[m[1]] = o; for (const k of Object.keys(o)) findCards(o[k], d + 1); }; findCards(j.content, 0);
  const all = linesOf(j.content);
  const ev = (j.trackingEvents || []).map((e) => e && (e.event || e)).find((e) => e && e.properties && e.properties.available_options);
  if (!ev) return JSON.stringify({ ok: false, error: 'the answer has no availability data (GetYourGuide changed its page): say it could not be read' });
  const p = ev.properties;
  const money = (x) => (x && Number.isFinite(x.amount) ? x.amount : null);
  const rows = (p.available_options || []).map((o, i) => {
    const slots = (o.time_slots || []).map((s) => ({ time: s.start_time || null, price: money(s.price), cur: s.price ? s.price.currency : null }));
    const seen = new Set(); const breakdown = [];
    for (const b of o.price_breakdown || []) { const key = [b.title, b.total_participants, money(b.total_price)].join('|'); if (seen.has(key)) continue; seen.add(key); breakdown.push({ title: b.title, n: b.total_participants, each: money(b.price_per_person), total: money(b.total_price) }); }
    const lines = linesOf(cardNodes[o.tour_option_id]);
    const prices = slots.map((s) => s.price).filter((v) => v !== null);
    return { n: i + 1, option_id: o.tour_option_id, title: lines[0] || null, lines, langs: o.languages || [], cur: (slots[0] || {}).cur || null, slots, total: prices.length ? Math.min(...prices) : null, totals_differ: new Set(prices).size > 1, breakdown };
  });
  // page sections (the same for every option): the flat text of the page between a heading and the next known heading
  const flat = []; const walkPage = (o, d) => { if (d > 60 || !o || typeof o !== 'object') return; if (Array.isArray(o)) { for (const x of o) walkPage(x, d + 1); return; } const t = typeof o.text === 'string' ? o.text : (o.text && typeof o.text.text === 'string' ? o.text.text : (typeof o.title === 'string' ? o.title : null)); if (t && t.trim()) flat.push(t.trim()); for (const k of Object.keys(o)) { if (k !== 'text') walkPage(o[k], d + 1); } };
  walkPage(sdui && (sdui.layout || sdui), 0);
  const ORDER = ['Highlights', 'Full description', 'Includes', 'Not suitable for', 'Meeting point', 'Important information', 'Group size', 'What to bring', 'Know before you go', 'Support', 'Customer reviews'];
  const FILLER = /^(See more|View details|Read more|Show more|View all)$/i;
  const section = (name, max) => { const k = flat.indexOf(name); if (k < 0) return null; const out = []; for (const l of flat.slice(k + 1)) { if (ORDER.includes(l) && l !== name) break; if (FILLER.test(l) || l === name) continue; out.push(l); } return out.join('; ').slice(0, max) || null; };
  const header = all.find((l) => /\d+ options? available|Not available for your selection|Sold out|No availability/i.test(l)) || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    path: location.pathname, id, activity: (document.querySelector('h1') || {}).innerText || document.title, day: REQ.day, day_read: p.date_selected || null, travellers: { adults: REQ.adults, ages: REQ.ages || [] }, categories: used.map((c) => ({ id: c.id, title: c.title, min: c.min, max: c.max, count: c.count, kind: c.kind })),
    categories_read: ((p.pricing_categories || {}).available || []).map((c) => ({ id: c.id, title: c.title, count: c.count, min: c.min_age, max: c.max_age })), availability: header, unavailable: JSON.stringify(p.unavailable_options || []).slice(0, 400), last_available_date: p.last_available_date || null,
    taxes_included: all.some((l) => /All taxes and fees included/i.test(l)), includes: section('Includes', 260), not_suitable: section('Not suitable for', 160), group_size: section('Group size', 120), know_before: section('Know before you go', 320), highlights: section('Highlights', 260),
    ms: Math.round(performance.now() - t0) }, rows);
})()
