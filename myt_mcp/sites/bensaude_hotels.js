// Bensaude Hotels (the hotel group's own booking engine, bensaude.e-gds.com) availability reader. Run it in the operator's Chrome on the availability tab the recipe opened.
// Read only: it waits for the rooms, reads every room and rate plan (name, meal text, price of the whole stay) and fetches each rate plan's detail page from the SAME site
// (the page behind the "i" icon: cancellation policy, nightly rates, local tax). It never presses ADD and books nothing.
// The tool replaces __EXPECT__ (hotel id, dates and adults the address asked for).
await (async () => {
  const EXPECT = __EXPECT__;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  if (!/availability\.aspx/i.test(location.pathname) || !/e-gds\.com$/i.test(location.hostname)) return JSON.stringify({ ok: false, error: 'not the Bensaude booking page: open the url first' });
  for (let i = 0; i < (typeof ROOM_TRIES !== 'undefined' ? ROOM_TRIES : 60) && !document.querySelectorAll('div.Room').length; i++) await wait(500);      // up to 30 s (ROOM_TRIES: tests only)
  const rooms = [...document.querySelectorAll('div.Room')];
  if (!rooms.length) return JSON.stringify({ ok: false, error: 'no rooms are shown for these dates (sold out, a search that did not run, or a changed page): never say sold out, say it could not be read' });
  await wait(800);
  const text = document.body.innerText;
  const after = (label) => { const i = text.indexOf(label); return i < 0 ? null : (text.slice(i + label.length).split('\n').map((x) => x.trim()).filter(Boolean)[0] || null); };
  const hotel = after('Hotel / Destination'), checkIn = after('Check-In'), checkOut = after('Check-Out'), adults = parseInt(after('Adults') || '', 10) || null;
  const hotelId = parseInt(new URLSearchParams(location.search).get('hotelid') || '', 10) || null;
  const problems = [];
  if (EXPECT.hotel_id && hotelId !== EXPECT.hotel_id) problems.push('hotel id ' + hotelId + ' instead of ' + EXPECT.hotel_id);
  if (EXPECT.check_in && checkIn !== EXPECT.check_in) problems.push('check-in ' + checkIn + ' instead of ' + EXPECT.check_in);
  if (EXPECT.check_out && checkOut !== EXPECT.check_out) problems.push('check-out ' + checkOut + ' instead of ' + EXPECT.check_out);
  if (EXPECT.adults && adults !== EXPECT.adults) problems.push(adults + ' adults instead of ' + EXPECT.adults);
  if (problems.length) return JSON.stringify({ ok: false, error: 'the page searched something else (' + problems.join('; ') + '): open the url again', hotel, check_in: checkIn, check_out: checkOut, adults });
  // The page keeps the last search's guests in its session: after a search with a child, the SAME address (children 0) still prices 2 adults + the child (27 Oct 2026: 3 rooms and higher prices instead of 11 rate plans). The rate links say what it really priced.
  const q = new URLSearchParams(((document.querySelector('a[href*="RatePlanDetail"]') || { getAttribute: () => '' }).getAttribute('href') || '').split('?')[1] || '');
  const kids = (parseInt(q.get('children') || '0', 10) || 0) + (parseInt(q.get('totalExtraChildren') || '0', 10) || 0);
  if (kids) return JSON.stringify({ ok: false, children_on_page: kids, error: 'the page still prices a child from an earlier search in this Chrome (its rate links carry children), so the rooms and prices are not for the adults asked: close every Bensaude tab, open the url again in a NEW Chrome window, and run the script once more' });
  const money = (s) => { const m = (s || '').match(/€\s?([\d.,]+)/); return m ? parseFloat(m[1].replace(/,/g, '')) : null; };
  const lines = (el) => el.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
  const detail = async (href) => {
    try {
      const res = await fetch(href, { credentials: 'same-origin' });
      if (!res.ok) return null;
      const d = new DOMParser().parseFromString(await res.text(), 'text/html');
      d.querySelectorAll('script,style').forEach((n) => n.remove());
      const t = d.body.textContent.replace(/\s+/g, ' ').trim();
      const pick = (re, n) => { const m = t.match(re); return m ? m[0].slice(0, n) : null; };
      return { cancel: pick(/Cancellation Policy.{0,360}/i, 360), tax: pick(/(Local )?tourist tax.{0,200}/i, 200), pay: pick(/credit card.{0,200}/i, 200), nightly: pick(/Rate detail for the period.{0,400}/i, 400) };
    } catch (e) { return null; }
  };
  const rows = []; let fetched = 0; let failed = 0;
  for (const r of rooms) {
    const rl = lines(r);
    const room = ((r.querySelector('h2,h3,h4') || {}).innerText || rl[0] || '').replace(/\s*Recommended\s*$/i, '').trim();      // the heading can carry a "Recommended" badge
    const roomDesc = rl.find((x, i) => i > 0 && x.length > 40) || null;
    for (const p of r.querySelectorAll('div.RatePlan')) {
      const pl = lines(p).filter((x) => !/^Special Offer$/i.test(x));
      const stop = pl.findIndex((x) => /^Nr\. Rooms/i.test(x));
      const link = p.querySelector('a[href*="RatePlanDetail"]');
      let det = null;
      if (link && fetched < 30) { det = await detail(link.getAttribute('href')); fetched++; if (!det) failed++; await wait(200); }
      rows.push({ room, room_desc: roomDesc ? roomDesc.slice(0, 200) : null, plan: pl[0] || null, description: pl.slice(1, stop > 0 ? stop : 6).join(' ').slice(0, 260), special: /Special Offer/i.test(p.innerText),
        price: money((p.querySelector('.QuantityRow') || p).innerText), cancel: det && det.cancel, tax: det && det.tax, pay: det && det.pay, nightly: det && det.nightly });
    }
  }
  const login = /\b(log ?out|sign out)\b/i.test(text) || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    hotel, hotel_id: hotelId, check_in: checkIn, check_out: checkOut, adults, children_on_page: kids, agent_login: login, details_read: fetched - failed, details_failed: failed }, rows);
})()
