// CP (Comboios de Portugal) results reader. Run it on the RESULTS page https://www.cp.pt/en/resultado-pesquisa?... (the stations, the date, the passengers and the class are in the address).
// Read only: it reads the journey cards the page drew (departure, arrival, duration, the services, the number of changes, price, promo flag). The price on the card is for ALL the passengers ("3x"). Nothing is bought or reserved.
await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'CP shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)cp\.pt$/.test(location.hostname) || !/resultado-pesquisa/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the CP results page (www.cp.pt/en/resultado-pesquisa): open the url first' });
  const buttons = () => [...document.querySelectorAll('button')].filter((b) => /^Select departure$/i.test((b.innerText || '').trim()));
  const cardOf = (b) => { let e = b; for (let i = 0; i < 12 && e; i++) { e = e.parentElement; if (e && [...e.querySelectorAll('button')].filter((x) => /^Select departure$/i.test((x.innerText || '').trim())).length === 1 && /Departure at/.test(e.innerText) && e.innerText.length < 900) return e; } return null; };
  const NONE = /No results were found/i;
  for (let i = 0; i < 36 && !buttons().length && !NONE.test(text()); i++) await wait(1000);
  await wait(1200);
  const t = text();
  const hdr = (t.match(/([^\n]+›[^\n]+)\n([^\n]+)\n([^\n]*Class[^\n]*)/) || []);
  const cards = buttons().map(cardOf).filter(Boolean);
  const after = (lines, label) => { const i = lines.findIndex((l) => l === label); return i >= 0 ? lines[i + 1] : null; };
  const euro = (s) => { const m = (s || '').match(/([\d.,]+)\s*€/); return m ? Number(m[1].replace(/,/g, '')) : null; };
  const rows = cards.map((c) => {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const promo = after(lines, 'Promo price');
    // a card with a change shows a lone number (the changes) before the duration and one "Service" line per train: "1 | 03h03 | ... Service Regional | R | Service Alfa Pendular | AP" (read on cp.pt 26 Oct 2026); a direct train has neither
    const di = lines.findIndex((l) => /^\d{2}h\d{2}$/.test(l));
    const changesN = di > 0 && /^\d+$/.test(lines[di - 1]) ? Number(lines[di - 1]) : 0;
    const services = lines.filter((l) => /^Service\b/.test(l)).map((l) => l.replace(/^Service\s*/, '')).filter(Boolean);
    return { pax: (lines.find((l) => /^\d+x$/.test(l)) || '').replace('x', '') || null, dur: lines.find((l) => /^\d{2}h\d{2}$/.test(l)) || null, cls: lines.find((l) => /Class/.test(l)) || null,
      dep: after(lines, 'Departure at'), arr: after(lines, 'Arrival at'), service: services[0] || null, services, changes_n: changesN, code: lines[lines.findIndex((l) => /^Service\b/.test(l)) + 1] || null,
      price: euro(promo || after(lines, 'Price')), promo: promo != null, was: euro(after(lines, 'Price without promotion')), note: lines.find((l) => /^Promo ticket/i.test(l)) || null,
      changes: lines.find((l) => /change|transfer|connection/i.test(l) && !/^See detail/.test(l)) || null };
  });
  return emit({ ok: true, route: hdr[1] || null, date_text: hdr[2] || null, class_text: hdr[3] || null, no_results: NONE.test(t) && !rows.length, cards_total: rows.length, viewport: window.innerWidth }, rows);
})()
