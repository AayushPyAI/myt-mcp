// RateHawk air tickets results reader. Run it in the operator's logged-in RateHawk air RESULTS tab (read only: it ticks the filters you ask for
// and scrolls to load the cards). The tool replaces __DIRECT__ and __CHECKED_BAG__ (true / false) and __MAX_CARDS__ before it runs.
// One card = one validating carrier offer: its flight alternatives (itineraries) and its fare tiers with the price for the WHOLE group.
await (async () => {
  const DIRECT = __DIRECT__; const CHECKED_BAG = __CHECKED_BAG__; const MAX_CARDS = __MAX_CARDS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const chooseButtons = () => [...document.querySelectorAll('button')].filter((e) => (e.innerText || '').trim() === 'Choose');
  const cardOf = (b) => { let e = b; for (let i = 0; i < 16 && e; i++) { e = e.parentElement; if (e && (e.innerText.match(/Choose/g) || []).length === 1 && /\d\d:\d\d/.test(e.innerText) && e.innerText.length > 120) return e; } return null; };
  const cards = () => chooseButtons().map(cardOf).filter(Boolean);
  for (let i = 0; i < 50 && !cards().length; i++) await wait(500);
  if (!cards().length) return JSON.stringify({ ok: false, error: 'no flight cards: not a RateHawk air results page, logged out, or still searching (wait and run once more)' });
  await wait(1200);
  const tick = async (text) => {
    const el = [...document.querySelectorAll('label,button,div,span')].find((e) => e.children.length <= 1 && (e.innerText || '').trim() === text);
    if (!el) return false;
    const before = cards().length + '|' + (cards()[0] ? cards()[0].innerText.slice(0, 80) : '');
    el.click();
    for (let k = 0; k < 20; k++) { await wait(500); const now = cards().length + '|' + (cards()[0] ? cards()[0].innerText.slice(0, 80) : ''); if (now !== before) break; }
    await wait(900);
    return true;
  };
  const ticked = []; const notFound = [];
  if (DIRECT) (await tick('Direct flight')) ? ticked.push('Direct flight') : notFound.push('Direct flight');
  if (CHECKED_BAG) (await tick('Checked baggage')) ? ticked.push('Checked baggage') : notFound.push('Checked baggage');
  if (notFound.length) return JSON.stringify({ ok: false, error: `filter(s) not found on the page: ${notFound.join(', ')}`, ticked });
  let last = -1;
  for (let i = 0; i < 30; i++) { const n = cards().length; if (n >= MAX_CARDS || (n === last && i > 1)) break; last = n; window.scrollTo(0, document.body.scrollHeight); await wait(1500); }
  const isTime = (x) => /^\d\d:\d\d$/.test(x || '');
  const isMoney = (x) => /^[€$£]\s?[\d,]+(\.\d+)?$/.test(x || '');
  const val = (x) => parseFloat(x.replace(/[^\d.]/g, ''));
  const cur = (x) => ({ '€': 'EUR', '$': 'USD', '£': 'GBP' })[x.trim()[0]] || null;
  function row(c) {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const starts = lines.map((x, i) => (isTime(x) && isTime(lines[i + 1]) && /travel time/.test(lines[i + 2] || '') ? i : -1)).filter((i) => i >= 0);
    let fareStart = lines.length;
    for (let j = (starts[starts.length - 1] || 0) + 3; j < lines.length - 2; j++) if (!isMoney(lines[j]) && isMoney(lines[j + 1]) && isMoney(lines[j + 2])) { fareStart = j; break; }
    const itineraries = starts.map((s, k) => {
      const end = k + 1 < starts.length ? starts[k + 1] : fareStart;
      const blk = lines.slice(s, end);
      return { dep: blk[0], arr: blk[1], travel: blk[2], stops: blk[3] || null, layover: blk.find((x) => /^\d+ h .*min,|^\d+ min,/.test(x)) || null, flights: blk.filter((x) => /^[A-Z0-9]{2}-\d+$/.test(x)) };
    });
    const fares = [];
    for (let j = fareStart; j < lines.length - 1; j++) if (!isMoney(lines[j]) && isMoney(lines[j + 1])) { fares.push({ name: lines[j], price: val(lines[j + 1]), currency: cur(lines[j + 1]) }); j += 2; }
    return { carrier: (lines[0] || '').replace(/ validates$/i, ''), issuing: lines[1] || null, date: lines.find((x) => /^[A-Z][a-z]{2} \d{1,2}, [A-Z][a-z]{2}$/.test(x)) || null,
      route: lines.find((x) => /→/.test(x)) || null, itineraries, fares };
  }
  const rows = cards().slice(0, MAX_CARDS).map(row);
  const head = document.body.innerText;
  const form = { route: (head.match(/\n([A-Z][^\n]+ → [^\n]+)\n/) || [])[1] || (rows[0] ? rows[0].route : null), date_pax: (head.match(/[A-Z][a-z]+ \d{1,2}, [A-Z][a-z]+\s*\n?[^\n]*adult[^\n]*/) || [])[0] || null };
  const lows = rows.map((r) => (r.fares[0] ? r.fares[0].price : null)).filter((x) => x != null);
  const asc = lows.every((p, i) => i === 0 || p >= lows[i - 1]);
  return JSON.stringify({ ok: true, form, filters_ticked: ticked, rows_read: rows.length, reached_cap: rows.length >= MAX_CARDS, lowest_fare_order: asc ? 'ascending' : 'not sorted', rows });
})()
