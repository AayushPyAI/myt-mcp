// iWay (iway.io) transfers list reader. Run it in the operator's iWay tab (the agency account is logged in in the operator's own Chrome: read only, nothing is entered, "Order now" is NEVER pressed).
// iway.io/booking shows, once From and To are chosen (the address then holds their Google place ids: ?from=<id>&to=<id>), "Choose car class": one button.class-item per vehicle class with the class, the number of
// passengers and of bags, the car ("Toyota Corolla and similar") and the price of the whole vehicle in the account's currency (USD in the header for this account). The list takes no date, time or passengers: iWay asks them
// at its next step (behind "Order now"), which this script never opens. The tool replaces __EXPECT__ (the places the operator asked for and, when known, their ids).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (/are you a person or a robot|press\s*&\s*hold|verify you are human|(?<!re)captcha/i.test(document.body.innerText.slice(0, 2500))) return JSON.stringify({ ok: false, error: 'iWay shows a human check (captcha). Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)iway\.io$/i.test(location.hostname) || !/^\/(?:[a-z]{2}\/)?booking\/?$/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not the iWay booking page: open the url first' });
  const items = () => [...document.querySelectorAll('.iwns__class-list button.class-item')];
  for (let i = 0; i < (typeof ITEM_TRIES !== 'undefined' ? ITEM_TRIES : 60) && !items().length; i++) await wait(500);      // up to 30 s (ITEM_TRIES: tests only)
  if (!items().length) return JSON.stringify({ ok: false, error: 'no vehicle classes are shown (From and To are not both chosen, a check page, a login page, or no route): choose both places in the boxes, never say there is no transfer, say it could not be read' });
  const q = new URLSearchParams(location.search);
  const inputs = [...document.querySelectorAll('input[placeholder^="Address"]')];
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const headerCur = (([...document.querySelectorAll('button')].map((b) => clean(b.innerText)).find((t) => /^[A-Z]{3}$/.test(t))) || null);
  const form = { from_id: q.get('from'), to_id: q.get('to'), from_name: inputs[0] ? clean(inputs[0].value) : null, to_name: inputs[1] ? clean(inputs[1].value) : null, header_currency: headerCur,
    logged_in: !!document.querySelector('a[href*="account.iway.io/rides"]'), route: (clean(document.body.innerText).match(/En route:\s*([\d.,]+)\s*km[^\d]{0,6}((?:\d+\s*h\s*)?\d+\s*m)?/i) || [null, null, null]).slice(1, 3) };
  const problems = [];
  if (EXPECT.from_id && form.from_id !== EXPECT.from_id) problems.push('from is another place than asked');
  if (EXPECT.to_id && form.to_id !== EXPECT.to_id) problems.push('to is another place than asked');
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): choose the places again or open the url again', form });
  const rows = []; const unparsed = [];
  for (const b of items()) {
    const lines = b.innerText.split('\n').map(clean).filter(Boolean);
    const price = lines.map((l) => l.match(/^(\$|€|£|₪|[A-Z]{3})\s?([\d,]+(?:\.\d+)?)$/)).find(Boolean);      // the WHOLE line is the price ("Minivan VIP 6" read as VIP 6 on the live page, 27 Oct 2026)
    const nums = lines.filter((l) => /^\d+$/.test(l));
    const car = lines.find((l, i) => i > 0 && !/^\d+$/.test(l) && !/^(\$|€|£|₪)/.test(l) && !/^order now$/i.test(l)) || null;
    if (!lines[0] || !price) { if (unparsed.length < 3) unparsed.push(lines.join(' | ').slice(0, 160)); continue; }
    rows.push({ klass: lines[0], passengers: nums[0] ? Number(nums[0]) : null, bags: nums[1] ? Number(nums[1]) : null, car, symbol: price[1], price: parseFloat(price[2].replace(/,/g, '')) });
  }
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.', form, unparsed }, rows);
})()
