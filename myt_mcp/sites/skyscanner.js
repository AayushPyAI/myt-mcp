// Skyscanner results reader (comparison only). Run it in the operator's Skyscanner RESULTS tab (read only: it clicks the sort tabs and "Show more results").
// Every ticket has one hidden accessibility sentence ("Flight option N: 138 € per passenger. Total cost 414 €. Flight with ... Departing from ... at hh:mm, arriving in ... at hh:mm
// ... Direct flight taking ... / Indirect flight taking ... with one stop in ..."): that sentence is parsed, nothing else. Sponsored tickets ("Advertisement by ...") are left out and counted.
// The tool replaces __SORTS__ (e.g. ["Best","Cheapest"]), __LIMIT__ (tickets per sort) and __SKIP__ (tickets already shown per sort: "more"). A human check (captcha) stops the script: it is never worked around.
await (async () => {
  const SORTS = __SORTS__; const LIMIT = __LIMIT__; const SKIP = __SKIP__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => document.body.innerText;
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|captcha/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Skyscanner shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/\/transport\/flights\//.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Skyscanner flight results page: open the url first' });
  const desc = () => [...document.querySelectorAll('[class*=FlightsTicketA11yDescriptor]')].map((e) => e.innerText.replace(/\s+/g, ' ').trim());
  for (let i = 0; i < 100 && !desc().length; i++) await wait(500);
  if (!desc().length) return JSON.stringify({ ok: false, error: 'no flights found: still searching, no flights for this search, or a human check: wait and run once more' });
  let last = -1; let stable = 0;
  for (let i = 0; i < 30 && stable < 3; i++) { await wait(1000); const n = desc().length; if (n === last) stable++; else { stable = 0; last = n; } }
  const num = (s) => parseFloat(String(s).replace(/,/g, ''));
  const RE = /^Flight option (\d+): (Advertisement by [^.]*\. Opens in new window\. )?([\d,]+) € per passenger\. Total cost ([\d,]+) €\. Flight with (.+?)\. Departing from (.+?) at (\d\d:\d\d), arriving in (.+?) at (\d\d:\d\d)(?:, (.+?) later)?\. (?:Direct flight taking (.+?)\.|Indirect flight taking (.+?) with (.+?)\.)/;
  const parsed = []; const unparsed = []; let ads = 0;
  const readAll = (sort) => {
    for (const d of desc()) {
      const m = d.match(RE);
      if (!m) { if (unparsed.length < 3) unparsed.push(d.slice(0, 200)); continue; }
      if (m[2]) { ads++; continue; }
      parsed.push({ sort, per: num(m[3]), total: num(m[4]), airlines: m[5], from: m[6], dep: m[7], to: m[8], arr: m[9], later: m[10] || null, direct: !!m[11], duration: m[11] || m[12], via: m[13] || null });
    }
  };
  const label = (name) => [...document.querySelectorAll('label')].find((l) => new RegExp('^' + name).test((l.innerText || '').trim()));
  const sortedBy = () => ((text().match(/\d+ results? sorted by (\w+)/) || [])[1]) || null;
  const t = text();
  const rm = t.replace(/\s+/g, ' ').match(/\(([A-Z]{3})\) - [^()]{2,40}\(([A-Z]{3})\)/); const route = rm ? [rm[1], rm[2]] : [];      // the airport codes in the heading, e.g. ["FLR", "LIS"]
  const date = (t.match(/\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{1,2} [A-Z][a-z]{2}\b/) || [null])[0];
  const trav = t.match(/(\d+) travellers?\s*,\s*([A-Za-z ]+?)(?:\n|$)/);
  const tabs = {}; ['Best', 'Cheapest', 'Fastest'].forEach((n) => { const l = label(n); if (l) tabs[n] = (l.innerText || '').replace(/\n+/g, ' | ').slice(0, 40); });
  const total = (t.match(/(\d+) results? sorted by/) || [])[1] || null;
  // the filter boxes: stops (all ticked by default), baggage / emissions / nearby airports / the direct toggle (unticked by default), airlines and layover airports (all ticked by default: an unticked one is a filter)
  const boxes = [...document.querySelectorAll('input[type=checkbox]')].map((b) => ({ t: ((b.closest('label') || b.parentElement || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40), on: b.checked }));
  const isStop = (t) => /^(Direct|1 stop|2\+ stops)$/.test(t); const isOff = (t) => /^(Cabin bag|Checked bag|Direct flights|Add nearby airports)/.test(t) || /Only show flights with lower CO2e/.test(t);
  const filters = { stops: boxes.filter((b) => isStop(b.t) && b.on).map((b) => b.t), ticked_extras: [...new Set(boxes.filter((b) => isOff(b.t) && b.on).map((b) => b.t))], unticked_defaults: boxes.filter((b) => b.t && !isStop(b.t) && !isOff(b.t) && !b.on).length };
  const directOnly = filters.stops.length === 1 && filters.stops[0] === 'Direct';
  const sorts = [];
  for (const sort of SORTS) {
    const l = label(sort);
    if (!l) return JSON.stringify({ ok: false, error: `the sort tab "${sort}" is not on the page` });
    if (sortedBy() !== sort && total) { l.click(); for (let k = 0; k < 20 && sortedBy() !== sort; k++) await wait(500); await wait(1500); }
    for (let i = 0; i < 12; i++) {
      const fresh = desc().filter((d) => !/Advertisement by/.test(d)).length;
      if (fresh >= SKIP + LIMIT) break;
      const btn = [...document.querySelectorAll('button,a')].find((b) => /show more results/i.test((b.innerText || '').trim()));
      if (!btn) break;
      const before = desc().length; btn.click();
      for (let k = 0; k < 16 && desc().length === before; k++) await wait(500);
      if (desc().length === before) break;
    }
    const before = parsed.length; readAll(sort);
    parsed.splice(before + SKIP + LIMIT); parsed.splice(before, SKIP);                    // keep the window [SKIP, SKIP + LIMIT) of this sort
    sorts.push({ sort, shown_as: sortedBy(), read: parsed.length - before });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    route, date, travellers: trav ? Number(trav[1]) : null, cabin: trav ? trav[2].trim() : null, results_total: total ? Number(total) : null, direct_only: directOnly, filters, offset: SKIP, tabs, sorts, ads_skipped: ads, unparsed }, parsed);
})()
