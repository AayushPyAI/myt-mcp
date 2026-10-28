// Booking.com attractions, ONE activity for a date and a group (comparison only). Run it in the operator's tab on the activity's own page (read only: it chooses nothing, it only sets the number of tickets
// of each kind and reads the site's own Total; it never presses "Next", which is the first step of the booking).
// The activity page (booking.com/attractions/<country>/<slug>.html) has a ticket box (data-testid="inline-ticket-config"): the dates row (the chosen one has aria-pressed="true"), "Select time" radios
// (data-testid="timeslot-option"; "Show more" doubles them), "Ticket" with the ticket's own wording ("Non-refundable" or a free-cancellation line), and one stepper per kind of ticket
// (data-testid="ticket-selector-stepper": a label "Adult (age 13-64)", the price per ticket, an <input type=range> that holds the count). The page prices the whole group in "Total ... Includes taxes and charges".
// With ?date=YYYY-MM-DD in the address a date that cannot be booked shows "Your selected date is unavailable, please choose another one" and no tickets: that is returned as it is (never "sold out").
// The tool replaces __EXPECT__ (what the address asked for: the activity, the date and its label, the adults and the children's ages).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(document.body.innerText.slice(0, 2500))) return JSON.stringify({ ok: false, error: 'Booking.com shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  const slug = (location.pathname.match(/^\/attractions\/[a-z]{2}\/([a-z0-9-]+?)(?:\.[a-z-]+)?\.html$/i) || [])[1];
  if (!/(^|\.)booking\.com$/i.test(location.hostname) || !slug) return JSON.stringify({ ok: false, error: 'not a Booking.com activity page: open the url first' });
  if (slug !== EXPECT.slug) return JSON.stringify({ ok: false, error: 'this is the page of "' + slug + '", not "' + EXPECT.slug + '": open the url again', slug });
  const box = () => document.querySelector('[data-testid="inline-ticket-config"]');
  for (let i = 0; i < (typeof BOX_TRIES !== 'undefined' ? BOX_TRIES : 60) && !box(); i++) await wait(500);      // up to 30 s (BOX_TRIES: tests only)
  if (!box()) return JSON.stringify({ ok: false, error: 'the ticket box is not on the page (still loading, a check page, or a changed page): say it could not be read' });
  await wait(1500);
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const boxText = () => clean(box().innerText);
  const title = clean((document.querySelector('h1') || {}).innerText);
  const form = { slug, path: location.pathname, date: new URLSearchParams(location.search).get('date'), currency: new URLSearchParams(location.search).get('selected_currency') };
  const chosen = [...document.querySelectorAll('[data-testid="datepicker-item"]')].filter((e) => e.getAttribute('aria-pressed') === 'true').map((e) => clean(e.innerText));
  const unavailable = (boxText().match(/Your selected date is unavailable[^.]*/i) || [null])[0];
  const head = { form, title, chosen_day: chosen[0] || null, operated_by: ((document.body.innerText.match(/Operated by ([^\n]+)/) || [])[1] || null) };
  if (unavailable) return emit({ ok: true, ...head, unavailable, steppers: 0 }, []);
  if (head.chosen_day && head.chosen_day.toLowerCase() !== EXPECT.day_label.toLowerCase()) return JSON.stringify({ ok: false, error: 'the page shows ' + head.chosen_day + ', not ' + EXPECT.day_label + ': open the url again', chosen: head.chosen_day });
  const more = document.querySelector('[data-testid="timeslots-show-more-cta"]');
  if (more) { more.click(); await wait(1200); }
  const labelOf = (inp) => { const l = document.querySelector('label[for="' + inp.id + '"]') || inp.closest('label') || inp.parentElement; return clean(l ? l.innerText : ''); };
  const slots = [...document.querySelectorAll('[data-testid="timeslot-option"]')].map((i) => ({ t: labelOf(i), on: !!i.checked }));
  const text = boxText(); const a = text.indexOf('Ticket '); const b = text.indexOf('How many tickets');
  const ticket = a >= 0 && b > a ? text.slice(a + 7, b).trim() : null;
  const steppers = [...document.querySelectorAll('[data-testid="ticket-selector-stepper"]')].map((s) => {
    const inp = s.querySelector('input'); const lab = inp ? labelOf(inp) : clean((s.querySelector('label') || {}).innerText);
    const price = clean(s.innerText).match(/(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/);
    const age = lab.match(/\(age (\d+)(?:\s*-\s*(\d+)|\s*\+)?\)/i);
    return { inp, label: lab, symbol: price ? price[1] : null, price: price ? parseFloat(price[2].replace(/,/g, '')) : null, min_age: age ? Number(age[1]) : null, max_age: age ? (age[2] ? Number(age[2]) : (/\+\)/.test(lab) ? 99 : Number(age[1]))) : null };
  });
  if (!steppers.length) return JSON.stringify({ ok: false, error: 'the ticket kinds are not on the page: say it could not be read' });
  // who goes in which ticket kind: a child in the kind whose age range holds the age; the adults in the kind called Adult
  const need = steppers.map(() => 0); const lost = [];
  const adultIx = steppers.findIndex((s) => /^adult/i.test(s.label));
  if (adultIx < 0) return JSON.stringify({ ok: false, error: 'there is no Adult ticket kind on the page: say it could not be read', kinds: steppers.map((s) => s.label) });
  need[adultIx] += EXPECT.adults;
  for (const age of EXPECT.ages) { const ix = steppers.findIndex((s) => s.min_age !== null && age >= s.min_age && age <= s.max_age); if (ix < 0) lost.push(age); else need[ix]++; }
  if (lost.length) return JSON.stringify({ ok: false, error: 'no ticket kind on the page holds a traveller of age ' + lost.join(', ') + ': say it could not be quoted', kinds: steppers.map((s) => s.label) });
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  // the page keeps the first change on a fresh page at one ticket (seen live 27 Oct 2026: 2 adults set, 1 kept): each count is set again until the page holds it (three tries), then the converter checks them all
  for (let i = 0; i < steppers.length; i++) {
    const inp = steppers[i].inp; if (!inp) continue;
    for (let t = 0; t < 3 && Number(inp.value) !== need[i]; t++) { setter.call(inp, String(need[i])); inp.dispatchEvent(new Event('input', { bubbles: true })); inp.dispatchEvent(new Event('change', { bubbles: true })); await wait(1000); }
  }
  await wait(1500);
  const totalText = clean((document.querySelector('[data-testid="ticket-selector-total"]') || {}).innerText);
  const tm = totalText.match(/(€|\$|£|₪|₹|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)/);
  const counts = steppers.map((s) => (s.inp ? Number(s.inp.value) : null));
  const kinds = steppers.map((s, i) => ({ label: s.label, price: s.price, count: counts[i], wanted: need[i] }));
  const computed = steppers.reduce((sum, s, i) => sum + (s.price || 0) * (counts[i] || 0), 0);
  const includes = clean(((([...document.querySelectorAll('h2')].find((h) => /What's included/i.test(h.innerText)) || {}).parentElement) || {}).innerText).replace(/^What's included\s*/i, '').slice(0, 300);
  const additional = clean(((([...document.querySelectorAll('h2')].find((h) => /Additional information/i.test(h.innerText)) || {}).parentElement) || {}).innerText).replace(/^Additional information\s*/i, '').slice(0, 500);
  window.scrollTo(0, document.body.scrollHeight); await wait(1500); window.scrollTo(0, 0);      // the supplier's name loads further down the page
  head.operated_by = head.operated_by || ((document.body.innerText.match(/Operated by ([^\n]+)/) || [])[1] || null);
  const row = { ticket, times: slots.map((x) => x.t).filter(Boolean), time_chosen: (slots.find((x) => x.on) || {}).t || null, kinds, symbol: tm ? tm[1] : null, total: tm ? parseFloat(tm[2].replace(/,/g, '')) : null,
    taxes: /Includes taxes and charges/i.test(totalText), computed, symbol_kinds: steppers[adultIx].symbol };
  return emit({ ok: true, ...head, includes, additional, unavailable: null, steppers: steppers.length }, [row]);
})()
