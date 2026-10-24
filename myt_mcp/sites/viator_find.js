await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot|blocked/i.test(text().slice(0, 1500)) && !/Showing \d+/.test(text().slice(0, 3000))) return JSON.stringify({ ok: false, error: 'Viator shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)viator\.com$/.test(location.hostname) || !/\/searchResults\//.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Viator search page (www.viator.com/searchResults/all?text=...): open the url first' });
  const anchors = () => { const seen = new Set(); return [...document.querySelectorAll('a[href*="/tours/"]')].filter((a) => { const h = (a.getAttribute('href') || '').split('?')[0]; if (!/\/d\d+-[A-Za-z0-9_.]+\/?$/.test(h) || seen.has(h)) return false; seen.add(h); return true; }); };
  let last = -1; let stable = 0;
  for (let i = 0; i < 40 && stable < 3; i++) { await wait(1000); const n = anchors().length; if (n > 0 && n === last) stable++; else { stable = 0; last = n; } }
  const page = Number((location.pathname.match(/\/searchResults\/all\/(\d+)/) || [])[1] || 1);
  const euro = /€\s?([\d.,]+)/g;
  const rows = anchors().map((a, i) => {
    const lines = a.innerText.split('\n').map((s) => s.trim()).filter((s) => s && !/^\d$/.test(s));
    const TAG = /^(Special Offer|Likely to Sell Out|Best Seller|Top Rated|New on Viator)$/i;
    const ti = lines.findIndex((l) => l.length > 8 && !TAG.test(l));
    const title = lines[ti]; const meta = lines[ti + 1] || '';
    const rating = lines.find((l) => /^\d\.\d$/.test(l)) || null; const rev = lines.find((l) => /^\(\d[\d,]*\)$/.test(l)) || null;
    const fromIdx = lines.findIndex((l) => /^from\b/i.test(l));
    const priceText = fromIdx >= 0 ? lines.slice(fromIdx, fromIdx + 3).join(' ') : '';
    const amounts = [...priceText.matchAll(euro)].map((m) => Number(m[1].replace(/,/g, '')));
    return { rank: (page - 1) * 24 + i + 1, title, path: (a.getAttribute('href') || '').split('?')[0], duration: meta.replace(/Free Cancellation.*$/i, '').trim() || null, free_cancel: /Free Cancellation/i.test(meta),
      rating: rating ? Number(rating) : null, reviews: rev ? Number(rev.replace(/[(),]/g, '')) : null, symbol: fromIdx >= 0 ? (priceText.match(/[€₪$£]/) || [null])[0] : null, from: amounts.length ? amounts[amounts.length - 1] : null,
      was: amounts.length > 1 ? amounts[0] : null, varies: /varies by group size/i.test(a.innerText), tags: lines.filter((l) => TAG.test(l)) };
  });
  const t = text();
  const showing = (t.match(/Showing (\d+) - (\d+) of ([\d,]+\+?) results for "([^"]+)"/) || []);
  const adults = [...document.querySelectorAll('button')].map((b) => (b.innerText || '').trim()).find((x) => /^\d+ Adults?/.test(x)) || null;
  const sort = (t.match(/Sort by:\s*([^\n]+)/) || [])[1] || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    query_text: showing[4] || null, results_total: showing[3] || null, page, shown_range: showing[1] ? `${showing[1]}-${showing[2]}` : null, travellers_filter: adults, sort }, rows);
})()
