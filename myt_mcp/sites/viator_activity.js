await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 1500)) && !/Book Now|Check Availability|Update Search/.test(text())) return JSON.stringify({ ok: false, error: 'Viator shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)viator\.com$/.test(location.hostname) || !/\/tours\/.+\/d\d+-/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Viator activity page (www.viator.com/tours/<place>/<name>/d123-CODE): open the url first' });
  const lines = (el) => (el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean);
  const DATE = /^[A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}$/; const MONEY = /^[€₪$£]\s?[\d,.]+$/;
  const dateInput = () => [...document.querySelectorAll('input')].find((i) => DATE.test((i.value || '').trim()));
  for (let i = 0; i < 30 && !dateInput(); i++) await wait(1000);
  const di = dateInput();
  if (!di) return JSON.stringify({ ok: false, error: 'the booking box with a date is not on the page: pick the date in the calendar and the travellers (Apply), then run the script once more' });
  let box = di; for (let i = 0; i < 14 && box.parentElement; i++) { box = box.parentElement; if (/Travelers/.test(box.innerText) && /Date/.test(box.innerText) && /[€₪$£]/.test(box.innerText) && box.innerText.length < 1600) break; }   // the box that also holds the price
  const bl = lines(box);
  const inputs = [...box.querySelectorAll('input')].map((e) => (e.value || '').trim());
  const dateText = inputs.find((v) => DATE.test(v)) || null; const trav = inputs.find((v) => /^\d+$/.test(v)) || null;
  const boxPriced = MONEY.test(bl[0] || '');
  // layout B (a product with several options): a radio list, each option with its own price and breakdown; layout A: one price in the box and a "Price details" window
  const radios = [...document.querySelectorAll('input[type=radio]')];
  const optionOf = (r) => { let e = r; for (let i = 0; i < 10 && e.parentElement; i++) { e = e.parentElement; if (e.querySelectorAll('input[type=radio]').length === 1 && lines(e).some((l) => MONEY.test(l))) return e; } return null; };
  const cards = radios.map((r) => ({ r, e: optionOf(r) })).filter((x) => x.e);
  const TIME = /^\d{1,2}:\d\d [AP]M$/;
  const cancelOf = (ls) => ls.find((l) => /cancellation/i.test(l)) || null; const payOf = (ls) => ls.find((l) => /Reserve now, pay nothing/i.test(l)) || null;
  const rows = [];
  if (cards.length >= 2 || (cards.length === 1 && !boxPriced)) {
    for (const { r, e } of cards) {
      const ls = lines(e); const label = (r.closest('label') || r.parentElement || e); const title = lines(label)[0] || ls[0];
      const bd = ls.filter((l) => /^\d+ [A-Za-z]+ x [€₪$£]/.test(l));
      const times = [...e.querySelectorAll('button')].map((b) => (b.innerText || '').trim()).filter((x) => TIME.test(x));
      rows.push({ option: title, selected: !!r.checked, priced: true, price_text: ls.find((l) => MONEY.test(l)), breakdown: bd.map((l) => { const nxt = ls[ls.indexOf(l) + 1]; return `${l} ${nxt && /^[−-]\d+%$/.test(nxt) ? nxt : ''}`.trim(); }), times, cancellation: cancelOf(ls), pay_later: payOf(ls) });
    }
  } else {
    const priced = boxPriced && !/^From\b/i.test(bl[0] || '');
    const sel = box.querySelector('select'); const times = sel ? [...sel.options].map((o) => o.text.trim()).filter((x) => x && !/^Select time$/i.test(x)) : [];
    const chosen = sel && sel.selectedIndex > 0 ? sel.options[sel.selectedIndex].text.trim() : ((bl.find((l) => TIME.test(l) && !times.includes(l)) || null));
    let dlg = []; const pd = [...box.querySelectorAll('button')].find((b) => /^Price details$/i.test((b.innerText || '').trim()));
    if (priced && pd) {
      pd.click();
      for (let i = 0; i < 12 && !/Total Price/i.test(text()); i++) await wait(500);
      const d = [...document.querySelectorAll('[role=dialog], [aria-modal=true]')].find((e) => /Total Price/i.test(e.innerText)) || null;
      dlg = d ? lines(d) : [];
      const close = d && (d.querySelector('button[aria-label*="lose"]') || d.querySelector('button'));
      if (close) close.click(); else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      await wait(500);
    }
    const ti = dlg.findIndex((l) => /^Total Price/i.test(l));
    const bd = []; for (let i = 0; i < dlg.length; i++) { if (/^\d+ [A-Za-z]+.* x [€₪$£]/.test(dlg[i])) bd.push(`${dlg[i]} = ${dlg[i + 1] && /^[€₪$£]/.test(dlg[i + 1]) ? dlg[i + 1] : (dlg[i + 2] || '')}`.replace(/\s+/g, ' ')); }
    rows.push({ option: null, selected: true, priced, price_text: priced ? bl[0] : null, from_text: priced ? null : bl[0] || null, start_time: chosen, times, cancellation: cancelOf(bl), pay_later: payOf(bl), dialog_travellers: dlg.find((l) => /^\d+ (Adult|Child|Infant|Senior|Youth|Traveler)/i.test(l) && !/ x /.test(l)) || null,
      dialog_when: dlg.find((l) => /\d{4}\s*•/.test(l)) || null, breakdown: bd, dialog_total: ti >= 0 ? dlg[ti + 1] || null : null });
  }
  const t = text(); const h1 = document.querySelector('h1');
  // page sections: the text under the page's own headings up to the next known heading
  const ORDER = ['Overview', "What's Included", 'Meeting Point & Itinerary', 'Additional Info', 'Cancellation Policy', 'Questions?', 'Traveler Photos', 'Reviews'];
  const section = (name, max) => { const h = [...document.querySelectorAll('h2,h3')].find((x) => x.innerText.trim() === name); if (!h) return null; let bx = h.parentElement; for (let i = 0; i < 8 && bx && bx.parentElement && bx.innerText.trim() === h.innerText.trim(); i++) bx = bx.parentElement; const ls = (bx ? bx.innerText : '').split('\n').map((x) => x.trim()).filter(Boolean); const k = ls.indexOf(name); const out = []; for (const l of ls.slice(k + 1)) { if (ORDER.includes(l) && l !== name) break; out.push(l); } return out.join('; ').slice(0, max) || null; };
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.', url_path: location.pathname, activity: h1 ? h1.innerText.trim() : document.title,
    date_box: dateText, travellers_box: trav ? Number(trav) : null, options_found: rows.length, duration: (t.match(/(\d+ (?:hours?|minutes?|days?)[^\n]{0,40}\(approx\.\))/) || [])[1] || null, offered_in: (t.match(/Offered in:\s*([^\n]+)/) || [])[1] || null, mobile_ticket: /Mobile ticket/i.test(t),
    included: section("What's Included", 240), meeting_text: section('Meeting Point & Itinerary', 320), additional: section('Additional Info', 240), cancel_policy: section('Cancellation Policy', 240) }, rows);
})()
