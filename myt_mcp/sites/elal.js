// El Al flight results reader. Run it on the RESULTS page of El Al's own booking engine (booking.elal.com/booking/flights, English): read only, it reads the flights of the selected day.
// The search is kept in the page's session, not in the address, so the form is filled once by hand (see the tool's steps); this script then reads the page and returns what the page itself
// says it searched (route, trip type, day, passengers) so the server can check it. Each flight row has ECONOMY / PREMIUM / BUSINESS columns with a price PER PASSENGER or "-".
await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const rowsNow = () => [...document.querySelectorAll('[class*=ui-bound__infos]')];
  if (!/booking\.elal\.com$/.test(location.host) || !/\/booking\/flights/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not El Al\'s results page: fill the search first (the steps), the results page is booking.elal.com/booking/flights' });
  for (let i = 0; i < 120 && !rowsNow().length; i++) await wait(500);
  const body = document.body.innerText;
  if (!rowsNow().length) return JSON.stringify({ ok: false, error: /[\u0590-\u05ff]/.test(body.slice(0, 400)) && !/Departure/.test(body) ? 'the page is in Hebrew: open booking.elal.com/booking/flights?market=IL&lang=en and run the script again' : 'no flights: still searching, no flights on this day, or the search was not made' });
  if (/[\u0590-\u05ff]/.test(body.slice(0, 300)) && !/Departure|Non-stop/.test(body)) return JSON.stringify({ ok: false, error: 'the page is in Hebrew: open booking.elal.com/booking/flights?market=IL&lang=en and run the script again' });
  let last = -1; let stable = 0;
  for (let i = 0; i < 15 && stable < 3; i++) { await wait(1000); const n = rowsNow().length; if (n === last) stable++; else { stable = 0; last = n; } }
  const lines = document.body.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
  const iTrip = lines.findIndex((x) => /^(One way|Round trip|Multi-city)$/.test(x));
  const route = iTrip >= 2 ? [lines[iTrip - 2], lines[iTrip - 1]] : [];
  const pax = iTrip >= 0 ? parseInt(lines[iTrip + 2], 10) : null;
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const dm = document.body.innerText.match(/(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), (\d{1,2}) ([A-Z][a-z]+), (\d{4})/);
  const day = dm ? `${dm[3]}-${String(MONTHS.indexOf(dm[2]) + 1).padStart(2, '0')}-${String(dm[1]).padStart(2, '0')}` : null;
  const cur = (x) => ({ '$': 'USD', '€': 'EUR', '₪': 'ILS' })[(x || '')[0]] || null;
  const price = (x) => parseFloat(String(x).replace(/[^\d.]/g, ''));
  const row = (e) => {
    const l = e.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const times = l.filter((x) => /^\d\d:\d\d$/.test(x));
    const stopsAt = l.findIndex((x) => /^(Non-stop|\d+ stops?)/i.test(x));
    const fares = {}; const labels = ['ECONOMY', 'PREMIUM', 'BUSINESS'];
    labels.forEach((name, k) => {
      const i = l.indexOf(name); if (i < 0) return;
      const j = labels.slice(k + 1).map((n) => l.indexOf(n)).filter((x) => x > i).sort((a, b) => a - b)[0] ?? l.length;
      const seg = l.slice(i + 1, j);
      const p = seg.find((x) => /^[$€₪]\s?[\d,]+(\.\d+)?$/.test(x));
      const left = seg.findIndex((x) => /left at this price/i.test(x));
      fares[name] = p ? { price: price(p), currency: cur(p), lowest: seg.includes('Lowest Price'), left: left > 0 && /^\d+$/.test(seg[left - 1]) ? parseInt(seg[left - 1], 10) : null } : null;
    });
    return { dep: times[0] || null, arr: times[times.length - 1] || null, from: l[1] || null, to: l[l.lastIndexOf(times[times.length - 1]) + 1] || null, stops: stopsAt >= 0 ? l[stopsAt] : null, duration: stopsAt >= 0 ? (l[stopsAt + 1] || null) : null,
      flights: l.filter((x) => /^[A-Z0-9]{2}\d{2,4}$/.test(x)), operated: l.includes('Operated by'), selling_fast: l.includes('Selling fast'), eco: fares.ECONOMY, prem: fares.PREMIUM, biz: fares.BUSINESS };
  };
  const rows = rowsNow().map(row);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    route, trip: iTrip >= 0 ? lines[iTrip] : null, day, pax, settled: stable >= 3, english: !/[\u0590-\u05ff]/.test(lines.slice(0, 12).join(' ')) }, rows);
})()
