// RateHawk transfers results reader. Run it in the operator's logged-in RateHawk transfers RESULTS tab (read only: it only reads the page).
// The results address holds opaque place tokens, so the search form is filled once by hand (see the tool's steps); this script then reads the
// page the same way every time and returns what the page itself says it searched, so the server can check it against the request.
await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const chooseButtons = () => [...document.querySelectorAll('button')].filter((e) => (e.innerText || '').trim() === 'Choose');
  const cardOf = (b) => { let e = b; for (let i = 0; i < 16 && e; i++) { e = e.parentElement; if (e && (e.innerText.match(/Choose/g) || []).length === 1 && /waiting time/i.test(e.innerText)) return e; } return null; };
  const cards = () => chooseButtons().map(cardOf).filter(Boolean);
  for (let i = 0; i < 40 && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no transfer cards: not a RateHawk transfers results page, logged out, or still searching (wait and run again once)' });
  await wait(1200);
  const money = (s) => { const m = (s || '').match(/([€$£])\s?([\d,]+(?:\.\d+)?)/); return m ? { v: parseFloat(m[2].replace(/,/g, '')), c: ({ '€': 'EUR', '$': 'USD', '£': 'GBP' })[m[1]] } : null; };
  const rows = cards().map((c) => {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const iClass = 1;
    const prices = lines.filter((x) => /^[€$£]\s?[\d,]+(\.\d+)?$/.test(x));
    const p = money(prices[0]);
    const seat = lines.find((x) => /^Including seats for children/i.test(x)) || null;
    return {
      vehicle: lines[0] || null, vehicle_class: lines[iClass] || null,
      passengers: (lines[2] || '').replace(/^up to\s*/i, '') || null, bags: (lines[3] || '').replace(/^up to\s*/i, '') || null,
      waiting: lines.find((x) => /waiting time/i.test(x)) || null,
      meeting: lines.find((x) => /^Meeting|Meet /i.test(x)) || null,
      flight_tracking: lines.some((x) => /^Flight tracking/i.test(x)),
      cancellation: lines.find((x) => /cancellation/i.test(x)) || null,
      price: p ? p.v : null, currency: p ? p.c : null, child_seat: seat,
    };
  });
  const head = document.body.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
  const iDate = head.findIndex((x) => /^\d{1,2} [A-Z][a-z]{2}, [A-Z][a-z]{2}, \d\d:\d\d$/.test(x));
  const form = { from: iDate >= 2 ? head[iDate - 2] : null, to: iDate >= 1 ? head[iDate - 1] : null, when: iDate >= 0 ? head[iDate] : null, passengers: iDate >= 0 ? head[iDate + 1] : null };
  const pageTicked = [...document.querySelectorAll('input[type=checkbox],input[type=radio]')].filter((b) => b.checked).map((b) => ((b.closest('label') || b.parentElement || {}).innerText || '').trim().replace(/\s+/g, ' ').slice(0, 40)).filter(Boolean);
  const rng = (name) => { const i = head.indexOf(name); if (i < 0) return null; const n = (x) => parseInt(String(x || '').replace(/\D/g, ''), 10); return { from: n(head[i + 1]), to: n(head[i + 2]) }; };
  const prices = rows.map((r) => r.price).filter((x) => x != null);
  const asc = prices.every((p, i) => i === 0 || p >= prices[i - 1]); const desc = prices.every((p, i) => i === 0 || p <= prices[i - 1]);
  const sortActive = [...document.querySelectorAll('button')].map((b) => ({ t: (b.innerText || '').trim(), a: /active|selected|checked/i.test(b.className) })).filter((x) => /^(Cheapest|Spacious|Comfortable)$/.test(x.t)).filter((x) => x.a).map((x) => x.t)[0] || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.', form, page_ticked: pageTicked, bags_range: rng('Baggage count'), seats_range: rng('Number of seats'), rows_read: rows.length, sort_tab: sortActive, price_order: asc ? 'ascending' : desc ? 'descending' : 'mixed' }, rows);
})()
