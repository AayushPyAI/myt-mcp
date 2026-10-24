await (async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 2500))) return JSON.stringify({ ok: false, error: 'GetYourGuide shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)getyourguide\.com$/.test(location.hostname) || !/-t\d+\/?$/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a GetYourGuide activity page (…-t12345): open the url first' });
  // wait for the availability answer of the selected date and group: "1 option available", "Choose from 5 available options" or "Not available for your selection"
  const HEAD = /\d+ options? available|\d+ available options?|Not available for your selection|Sold out|No availability/i;
  // some activities show a "Check availability" button first and the option cards only after it is pressed (it only shows the availability; nothing is booked or reserved): press it while waiting
  let pressed = 0; for (let i = 0; i < 40 && !HEAD.test(text()); i++) { if (i % 4 === 0 && pressed < 4) { const ca = [...document.querySelectorAll('button,a')].find((b) => /^Check availability$/i.test((b.innerText || '').trim()) && b.getBoundingClientRect().width > 0); if (ca) { ca.click(); pressed++; } } await wait(1000); }
  await wait(1500);
  // one option card ends with its button and holds exactly one. Most cards say "Duration:" (the innermost element with one such line is the card); some (the whale-watching page, 23 Oct 2026)
  // have no Duration line: there the card is the OUTERMOST element that still holds a single button and a price (the price box alone would lose the title)
  const endsWithButton = (x) => /(Continue|Select|Unavailable|Not available)\s*$/.test(x);
  const isOld = (e) => { const x = (e.innerText || '').trim(); return (x.match(/Duration:/g) || []).length === 1 && endsWithButton(x) && x.length < 1800; };
  const isNew = (e) => { const x = (e.innerText || '').trim(); if (x.length >= 1800 || !endsWithButton(x) || /Duration:/.test(x)) return false; const buttons = [...e.querySelectorAll('button,a')].filter((b) => /^(Continue|Select)$/i.test((b.innerText || '').trim())); return buttons.length === 1 && /[€₪$£]\s?[\d,.]+/.test(x); };
  const ALL = 'div,section,article,li';
  const cardList = () => { const all = [...document.querySelectorAll(ALL)]; const old = all.filter((e) => isOld(e) && [...e.querySelectorAll(ALL)].every((c) => !isOld(c))); return old.length ? old : all.filter((e) => isNew(e) && !(e.parentElement && isNew(e.parentElement))); };
  const countCards = () => cardList().length;
  const showAll = [...document.querySelectorAll('button,a')].find((b) => /^Show all options$/i.test((b.innerText || '').trim()));
  if (showAll) { const before = countCards(); showAll.click(); for (let i = 0; i < 16 && countCards() <= before; i++) await wait(500); await wait(800); }   // the page shows 3 options first
  const t = text(); const head = (t.match(HEAD) || [null])[0];
  if (!head) return JSON.stringify({ ok: false, error: 'the availability of the selected date and group is not on the page: set the date and the travellers, press "Check availability" (or Continue in the traveller box) and run the script once more' });
  const money = /^([€₪$£]|EUR|ILS|USD|GBP)\s?([\d.,]+)$/;
  const cards = cardList();
  const options = cards.map((c) => {
    const lines = c.innerText.split('\n').map((s) => s.trim()).filter(Boolean);
    const sel = c.querySelector('select'); const times = sel ? [...sel.options].map((o) => o.text.trim()).filter(Boolean) : [];
    const priceIdx = lines.findIndex((l) => money.test(l));
    const m = priceIdx >= 0 ? lines[priceIdx].match(money) : null;
    const day = (lines.find((l) => /^[A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}, \d{4}$/.test(l)) || null);
    return { title: lines.find((l) => !/^Only \d+ spots? left/i.test(l)) || lines[0], duration: (lines.find((l) => /^Duration:/.test(l)) || '').replace(/^Duration:\s*/, '') || null, guide: (lines.find((l) => /^(Audio guide|Live guide|Guide|Language|Languages|Audio|Live tour guide)\b.*:/.test(l)) || null),
      cancel: (lines.find((l) => /^(Cancel for free|Free cancellation|Non-refundable|Not refundable|Cancellation)/i.test(l)) || null), pay_later: lines.some((l) => /Reserve now & pay later/i.test(l)), meeting_point: lines.some((l) => /Meeting point|Pickup|Pick-up/i.test(l)),
      day, times, price_symbol: m ? m[1] : null, price: m ? Number(m[2].replace(/,/g, '')) : null,
      breakdown: priceIdx >= 0 ? lines.slice(priceIdx + 1).filter((l) => /×|x\s?\d/.test(l) && /\d/.test(l)).slice(0, 4) : [], taxes_included: lines.some((l) => /All taxes and fees included/i.test(l)),
      spots: lines.find((l) => /^Only \d+ spots? left/i.test(l)) || null, unavailable: lines.find((l) => /participants are required|not available|Unavailable|sold out/i.test(l) && !/^Unavailable$/.test(l)) || (lines[lines.length - 1] === 'Unavailable' ? 'Unavailable' : null) };
  });
  const trav = [...document.querySelectorAll('button,[role=button]')].map((b) => (b.innerText || '').trim()).find((x) => /(Adult|Child|Youth|Senior|Infant|Participant|Traveler|Traveller)/i.test(x) && /[x×]\s?\d/.test(x) && x.length < 60) || null;
  // page sections (the same for every option): the text between a heading and the next known heading
  const ORDER = ['Highlights', 'Full description', 'Includes', 'Not suitable for', 'Meeting point', 'Important information', 'Group size', 'Know before you go', 'Support'];
  const section = (name, max) => { const h = [...document.querySelectorAll('h2,h3')].find((x) => x.innerText.trim() === name); if (!h) return null; let box = h.parentElement; for (let i = 0; i < 8 && box && box.parentElement && box.innerText.trim() === h.innerText.trim(); i++) box = box.parentElement; const lines = (box ? box.innerText : '').split('\n').map((x) => x.trim()).filter(Boolean); const k = lines.indexOf(name); const out = []; for (const l of lines.slice(k + 1)) { if (ORDER.includes(l) && l !== name) break; out.push(l); } return out.join('; ').slice(0, max) || null; };
  const h1 = document.querySelector('h1');
  const header = [...document.querySelectorAll('header *')].map((e) => (e.innerText || '').trim()).find((x) => /^[A-Z]{2}\s*\/\s*[A-Z€₪$£]{1,3}$/.test(x)) || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    activity: h1 ? h1.innerText.trim() : document.title, url_path: location.pathname, availability: head, travellers: trav, locale_currency: header, options_found: options.length,
    includes: section('Includes', 260), not_suitable: section('Not suitable for', 160), meeting_page: section('Meeting point', 300), group_size: section('Group size', 120), know_before: section('Know before you go', 320), highlights: section('Highlights', 260) }, options.map((o, i) => ({ n: i + 1, ...o })));
})()
