// RateHawk hotel results reader. Run it in the operator's logged-in RateHawk results tab (read only: it reads the page and clicks only the
// "Forward" page button). It returns compact JSON: checks (sort, start page, header count) and one row per hotel card.
// The tool replaces __MAX_PAGES__ and __EXPECT_SORT__ before it is run. A field the card does not show is null ("not shown").
await (async () => {
  const MAX_PAGES = __MAX_PAGES__;
  const EXPECT_SORT = "__EXPECT_SORT__";
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const cardsNow = () => [...document.querySelectorAll('.zen-hotelcard-wrapper')];
  const pageNo = () => parseInt((location.search.match(/[?&]page=(\d+)/) || [])[1] || '1', 10);
  const sortLabel = () => (document.querySelector('.zen-sorter')?.innerText || '').replace(/^\s*Sort by\s*/i, '').trim();
  async function waitForCards(prevFirst) {
    for (let i = 0; i < 40; i++) {                                   // up to ~20 s
      const c = cardsNow();
      if (c.length && c[0].innerText.split('\n')[0] !== prevFirst) { await wait(700); return true; }
      await wait(500);
    }
    return false;
  }
  function row(c, page) {
    const lines = c.innerText.split('\n').map((x) => x.trim()).filter(Boolean);
    const g = (re) => lines.find((x) => re.test(x)) || null;
    const iRoom = lines.findIndex((x) => /^\d+ \/ \d+$/.test(x));
    const href = c.querySelector('.zen-hotelcard-name-link')?.getAttribute('href') || null;
    return {
      p: page,
      name: c.querySelector('.zen-hotelcard-name')?.innerText?.trim() || lines[0] || null,
      stars: c.querySelectorAll('.zen-ui-stars-star').length || null,
      distance: g(/from the .* center/i),
      score: lines.find((x) => /^\d+(\.\d)?$/.test(x)) || null,
      reviews: g(/^\d[\d,]*\s+reviews?/i),
      room: iRoom >= 0 ? lines[iRoom + 1] || null : null,
      bed: iRoom >= 0 && lines[iRoom + 2] && !/(meals|breakfast|cancellation|^Pay |^EUR|^[A-Z]{3}\s)/i.test(lines[iRoom + 2]) ? lines[iRoom + 2] : null,
      meal: g(/(meals|breakfast|half board|full board|all inclusive)/i),
      cancellation: g(/cancellation/i),
      payment: g(/^Pay /i),
      price: lines.find((x) => /^[A-Z]{3}\s?[\d,]+(\.\d+)?$/.test(x)) || null,
      basis: g(/^for \d+ nights?/i),
      path: href ? href.split('?')[0] : null,
    };
  }
  if (!(await waitForCards(null))) return JSON.stringify({ ok: false, error: 'no hotel cards: not a RateHawk results page, logged out, or still searching' });
  const startPage = pageNo();
  const label = sortLabel();
  const header = (document.body.innerText.match(/[A-Za-zÀ-ÿ' .-]+:\s*([\d,]+)\s+accommodation options available/) || [])[0] || null;
  if (startPage !== 1) return JSON.stringify({ ok: false, error: `the results are on page ${startPage}, not page 1: open the URL again with &page=1`, header, sort: label });
  if (EXPECT_SORT && label !== EXPECT_SORT) return JSON.stringify({ ok: false, error: `the list is sorted by "${label}", not "${EXPECT_SORT}": open the URL with the right sort`, header, sort: label });
  const rows = [];
  let stopped = null;
  for (let page = 1; page <= MAX_PAGES; page++) {
    if (pageNo() !== page) { stopped = `page counter says ${pageNo()}, expected ${page}: stopped so that no page is skipped`; break; }
    cardsNow().forEach((c) => rows.push(row(c, page)));
    if (page === MAX_PAGES) break;
    const next = document.querySelector('.zenpagination-button-next');
    if (!next || next.disabled || /disabled/.test(next.className)) { stopped = 'last page reached'; break; }
    const first = cardsNow()[0].innerText.split('\n')[0];
    next.click();
    if (!(await waitForCards(first))) { stopped = 'the next page did not load'; break; }
  }
  const prices = rows.map((r) => parseFloat((r.price || '').replace(/[^\d.]/g, ''))).filter((x) => !isNaN(x));
  const asc = prices.every((p, i) => i === 0 || p >= prices[i - 1]);
  const desc = prices.every((p, i) => i === 0 || p <= prices[i - 1]);
  const residency = (location.search.match(/[?&]residency=([a-z-]+)/) || [])[1] || null;
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.', header, sort: label, residency, start_page: startPage, pages_read: rows.length ? Math.max(...rows.map((r) => r.p)) : 0, rows_read: rows.length,
    stopped, price_order: asc ? 'ascending' : desc ? 'descending' : 'mixed' }, rows);
})()
