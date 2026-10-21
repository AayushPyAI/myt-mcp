// RateHawk car-rental results reader. Run it in the operator's logged-in RateHawk cars results tab (read only: it scrolls the list,
// and ticks the filter boxes you ask for). The tool replaces __MAX_CARS__ and __FILTERS__ (a JSON list of filter labels) before it runs.
// A field the card does not show is null ("not shown"). The card is found from its "Choose" button, not from a class name (class names carry hashes).
await (async () => {
  const MAX_CARS = __MAX_CARS__;
  const FILTERS = __FILTERS__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const chooseButtons = () => [...document.querySelectorAll('button,a,div,span')].filter((e) => e.children.length === 0 && (e.innerText || '').trim() === 'Choose');
  const cardOf = (b) => { let e = b; for (let i = 0; i < 14 && e; i++) { e = e.parentElement; if (e && /Full conditions of rental/.test(e.innerText) && (e.innerText.match(/Choose/g) || []).length === 1) return e; } return null; };
  const cards = () => chooseButtons().map(cardOf).filter(Boolean);
  async function waitForCards() { for (let i = 0; i < 40; i++) { if (cards().length) { await wait(800); return true; } await wait(500); } return false; }

  if (!(await waitForCards())) return JSON.stringify({ ok: false, error: 'no car cards: not a RateHawk cars results page, logged out, or still searching' });

  // 1. tick the requested filters (by their visible label), one at a time
  const ticked = []; const notFound = [];
  for (const label of FILTERS) {
    const lab = [...document.querySelectorAll('label')].find((l) => (l.innerText || '').trim().replace(/\s+\d+$/, '') === label);
    const box = lab && (lab.querySelector('input[type=checkbox]') || document.getElementById(lab.getAttribute('for') || ''));
    if (!box) { notFound.push(label); continue; }
    if (!box.checked) { const before = cards().length + '|' + (cards()[0] ? cards()[0].innerText.slice(0, 60) : ''); lab.click(); for (let k = 0; k < 16; k++) { await wait(500); if (cards().length && cards().length + '|' + cards()[0].innerText.slice(0, 60) !== before) break; } await wait(700); }
    ticked.push(label);
  }
  if (notFound.length) return JSON.stringify({ ok: false, error: `filter label(s) not found on the page: ${notFound.join(', ')}`, ticked });

  // 2. scroll until no more cards load (or MAX_CARS)
  let last = -1;
  for (let i = 0; i < 40; i++) {
    const n = cards().length;
    if (n >= MAX_CARS || (n === last && i > 1)) break;
    last = n; window.scrollTo(0, document.body.scrollHeight); await wait(1700);
  }

  // 3. read the cards
  const money = (s) => { const m = (s || '').match(/[€$£]\s?([\d,]+(?:\.\d+)?)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  function row(c) {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const at = (re) => lines.findIndex((x) => re.test(x));
    const iGear = at(/^(Manual|Automatic)$/);
    const pre = iGear >= 3 ? lines.slice(0, iGear - 3) : [];                       // before the three counts: [score], [company]
    const isScore = (x) => /^\d(\.\d)?$/.test(x);
    const logo = [...c.querySelectorAll('img')].find((i) => /logo/i.test(i.alt || ''));
    const logoName = logo ? logo.src.split('/').pop().split('?')[0].replace(/\.\w+$/, '') : null;
    const score = pre.find(isScore) || null;
    const companyText = pre.find((x) => !isScore(x)) || null;
    const iModel = iGear >= 0 ? iGear + 1 : -1;
    const sim = lines[iModel + 1] || '';
    const dep = at(/^Deposit$/), exc = at(/^Excess$/), ins = at(/^Insurance$/), cond = at(/^Full conditions of rental$/);
    const placeLine = iModel >= 0 && dep > iModel + 1 ? lines.slice(iModel + 2, dep).join(' ') || null : null;
    const prices = (cond >= 0 ? lines.slice(cond + 1) : []).filter((x) => /^[€$£]\s?[\d,]+(\.\d+)?$/.test(x));
    const extras = [];
    for (let i = 0; i < lines.length; i++) if (/^(Snow chains|Additional driver|GPS|Child seat)/i.test(lines[i])) extras.push(lines[i] + (lines[i + 2] === 'free' ? ' (free)' : ''));
    return {
      score, company: companyText || logoName, company_from: companyText ? 'text' : logoName ? 'logo file name' : null,
      seats: iGear >= 3 ? lines[iGear - 3] : null, large_bags: iGear >= 2 ? lines[iGear - 2] : null, small_bags: iGear >= 1 ? lines[iGear - 1] : null,
      gearbox: iGear >= 0 ? lines[iGear] : null, car: lines[iModel] || null,
      code_class: (sim.match(/similar\s+(\S+)\s*•\s*(.+)/) || []).slice(1, 3).join(' • ') || sim || null,
      pickup_place: placeLine,
      deposit: dep >= 0 ? money(lines[dep + 1]) : null, excess: exc >= 0 ? money(lines[exc + 1]) : null, insurance: ins >= 0 ? lines[ins + 1] : null,
      mileage_fuel: lines.find((x) => /mileage|Fuel policy/i.test(x)) || null, extras,
      price: prices.length ? money(prices[0]) : null,
      currency: prices.length ? ({ '€': 'EUR', '$': 'USD', '£': 'GBP' })[prices[0].trim()[0]] || null : null,
      cancellation: lines.find((x) => /cancellation/i.test(x)) || null,
    };
  }
  const rows = cards().slice(0, MAX_CARS).map(row);
  const form = {
    pickup: document.querySelectorAll('input')[0]?.value || null, dropoff: document.querySelectorAll('input')[1]?.value || null,
    times: [...document.querySelectorAll('input')].filter((i) => /^\d\d:\d\d$/.test(i.value)).map((i) => i.value),
    age_residency: (document.body.innerText.match(/Driver's age\s*\n?\s*([^\n]+)\s*\n?\s*Driver's residency\s*\n?\s*([^\n]+)/i) || []).slice(1, 3),
    dates: (document.body.innerText.match(/\d{1,2} [A-Z][a-z]{2}, [A-Z][a-z]{2}/g) || []).slice(0, 2),
  };
  const prices = rows.map((r) => r.price).filter((x) => x != null);
  const asc = prices.every((p, i) => i === 0 || p >= prices[i - 1]); const desc = prices.every((p, i) => i === 0 || p <= prices[i - 1]);
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.', form, filters_ticked: ticked, rows_read: rows.length, reached_cap: rows.length >= MAX_CARS, price_order: asc ? 'ascending' : desc ? 'descending' : 'mixed' }, rows);
})()
