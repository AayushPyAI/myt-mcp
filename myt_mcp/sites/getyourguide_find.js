await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  const LIMIT = __LIMIT__; const SKIP = __SKIP__;
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'GetYourGuide shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)getyourguide\.com$/.test(location.hostname) || !/^\/s\/?$/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a GetYourGuide search page (www.getyourguide.com/s/?q=...): open the url first' });
  const anchors = () => { const seen = new Set(); return [...document.querySelectorAll('a[href*="-t"]')].filter((a) => { const h = (a.getAttribute('href') || '').split('?')[0]; if (!/-t\d+\/?$/.test(h) || seen.has(h)) return false; seen.add(h); return true; }); };
  let last = -1; let stable = 0;
  for (let i = 0; i < 40 && stable < 3; i++) { await wait(1000); const n = anchors().length; if (n > 0 && n === last) stable++; else { stable = 0; last = n; } }
  const showMore = () => [...document.querySelectorAll('button')].find((b) => /^show more$/i.test((b.innerText || '').trim()));
  for (let i = 0; i < 12 && anchors().length < SKIP + LIMIT; i++) {
    const b = showMore(); if (!b) break; const before = anchors().length; b.click();
    for (let k = 0; k < 20 && anchors().length === before; k++) await wait(500);
    if (anchors().length === before) break; await wait(800);
  }
  const t = text(); const all = anchors();
  const BADGE = /^(Top pick|Top rated|Certified by GetYourGuide|Likely to sell out|Special offer|New|Best seller|Staff pick|Free cancellation|Skip the line|Limited time)$/i;
  const rows = all.slice(SKIP, SKIP + LIMIT).map((a, i) => {
    const lines = a.innerText.split('\n').map((s) => s.trim()).filter(Boolean);
    const cityIdx = lines.findIndex((l) => /^[A-Z][A-Z .'’-]{2,}$/.test(l));
    const fromIdx = lines.findIndex((l) => /^From$/i.test(l));
    const priceLine = fromIdx >= 0 ? lines[fromIdx + 1] || '' : '';
    const pm = priceLine.match(/^([€₪$£]|EUR|ILS|USD|GBP)\s?([\d.,]+)$/);
    const title = cityIdx >= 0 ? lines[cityIdx + 1] : lines[0]; const metaIdx = cityIdx >= 0 ? cityIdx + 2 : 1;
    const meta = /hour|minute|min|day|•/i.test(lines[metaIdx] || '') ? lines[metaIdx] : null;
    const rating = lines.find((l) => /^\d(\.\d)?$/.test(l)) || null; const rev = lines.find((l) => /^\(\d[\d,]*\)$/.test(l)) || null;
    const tags = lines.filter((l) => BADGE.test(l));
    return { rank: SKIP + i + 1, title, path: (a.getAttribute('href') || '').split('?')[0], city: cityIdx >= 0 ? lines[cityIdx] : null, meta, rating: rating ? Number(rating) : null, reviews: rev ? Number(rev.replace(/[(),]/g, '')) : null,
      symbol: pm ? pm[1] : null, from: pm ? Number(pm[2].replace(/,/g, '')) : null, per: /per (person|group)/i.test(a.innerText) ? (a.innerText.match(/per (person|group)/i) || [])[1].toLowerCase() : null, tags };
  });
  const total = (t.match(/([\d,]+\+?)\s+results/) || [])[1] || null;
  const chip = (t.slice(0, 900).match(/\b([A-Z][a-z]{2} \d{1,2})\b(?=\s*\n)/) || [])[1] || null;
  const q = (t.match(/[\d,]+\+?\s+results:?\s*\n?\s*([^\n]+)/) || [])[1] || null;
  const cur = (t.slice(0, 300).match(/EN\/([A-Z]{3})/) || [])[1] || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    results_total: total, query_text: q, date_chip: chip, header_currency: cur, cards_on_page: all.length, offset: SKIP }, rows);
})()
