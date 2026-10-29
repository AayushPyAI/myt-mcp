  // Output: claude.ai cuts long tool answers, and a cut or re-typed answer is not the page's data. So the rows leave in short, self-contained
  // PARTS (about PART_CHARS each), in a compact form (columns named once, columns that never change moved to `common`). Part 1 is returned; the
  // others stay in window.__mytParts and are fetched with one short expression. The server decodes and joins the parts and checks none is missing.
  const PART_CHARS = 3500;
  const RUN = Date.now().toString(36);
  // With INGEST (the server made it for this recipe call) the whole answer goes to the server and the model only gets a short receipt: the browser tool shows the model about 1,000 characters.
  const post = async (head, rows) => {
    const body = JSON.stringify({ ...head, run: RUN, rows_read: rows.length, page_url: location.href.split('#')[0], viewport: window.innerWidth, rows });
    let received = false; let how = null;
    try { const r = await fetch(INGEST.url, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body }); const j = await r.json(); received = !!j.ok && j.rows === rows.length; how = received ? 'confirmed by the server' : 'the server answered ' + JSON.stringify(j).slice(0, 80); }
    catch (e1) {
      try { await fetch(INGEST.url, { method: 'POST', mode: 'no-cors', headers: { 'Content-Type': 'text/plain' }, body }); received = null; how = 'sent, the reply could not be read'; }
      catch (e2) { received = false; how = 'the page refused to send: ' + String(e2).slice(0, 60); }
    }
    return JSON.stringify({ ok: received !== false, received, how, ingest: INGEST.token, rows_sent: rows.length, chars_sent: body.length,
      next: received === false ? 'The answer did NOT reach the server. Run this script once more in the same tab; if it fails again, put this source in not_checked (reason: browser blocked) and do not type any row.'
        : 'STOP: do not read or type any row. Call compose_answer with runs=["' + INGEST.token + '"] (plus kind, wishes if any, not_checked) and show the text it returns, nothing else.' });
  };
  const emit = (head, rows) => {
    if (typeof LOCAL_RETURN !== 'undefined') return JSON.stringify({ ...head, run: RUN, rows_read: rows.length, page_url: location.href.split('#')[0], viewport: window.innerWidth, rows });      // the server runs this script in its own browser and takes the whole answer itself
    if (typeof INGEST !== 'undefined') return post(head, rows);
    const keys = rows.length ? Object.keys(rows[0]) : [];
    const same = (k) => rows.length > 1 && rows.every((r) => JSON.stringify(r[k]) === JSON.stringify(rows[0][k]));
    const common = {}; const cols = [];
    keys.forEach((k) => (same(k) ? (common[k] = rows[0][k]) : cols.push(k)));
    let base = '';
    if (cols.includes('path')) {
      base = rows.map((r) => r.path || '').reduce((a, b) => { let i = 0; while (i < a.length && a[i] === b[i]) i++; return a.slice(0, i); });
      base = base.slice(0, base.lastIndexOf('/') + 1);
    }
    const arr = rows.map((r) => cols.map((k) => (k === 'path' && r.path ? r.path.slice(base.length) : r[k])));
    const MORE = 'This answer is only part 1: run the expression in `more` with the javascript tool for each next part and pass EVERY part, unchanged, as its own item of compose_answer site_results.';
    // each part ends with the CRC32 of its own text: a part that was cut, re-typed or changed on its way through the model fails the server's check
    const crc32 = (str) => { let crc = 0xFFFFFFFF; for (const x of new TextEncoder().encode(str)) { crc ^= x; for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ (0xEDB88320 & -(crc & 1)); } return ((crc ^ 0xFFFFFFFF) >>> 0).toString(16).padStart(8, '0'); };
    // a part holds ASCII only: every other character is written as \uXXXX (28 Oct 2026: RateHawk's names carry U+00A0 and U+200A spaces that the model saw as plain spaces and typed back as plain spaces, so the checksum failed on about every
    // other run). The server reads the escapes back as the same characters, and the checksum is made on the text exactly as the model sees it.
    const asciiOnly = (str) => str.replace(/[\u007f-￿]/g, (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'));
    const mk0 = (part, parts, chunk) => asciiOnly(JSON.stringify({ ...head, run: RUN, rows_read: rows.length, part, parts, ...(part === 1 && typeof WISHES !== 'undefined' ? WISHES : {}), ...(part === 1 && parts > 1 ? { more: 'window.__mytParts[1] (then [2], [3] ... up to parts-1)', note: MORE } : {}), cols, common, path_base: base, rows: chunk }));
    const mk = (part, parts, chunk) => { const t = mk0(part, parts, chunk); return t.slice(0, -1) + ',"crc":"' + crc32(t) + '"}'; };
    if (typeof SLIM !== 'undefined' && SLIM) {
      // SLIM parts (RateHawk hotels, 29 Oct 2026): the browser tool shows the model only about 1,000 characters, and the page's security policy stops the post, so the answer has to pass through the model. Every part is
      // made to fit in ONE output (SLIM_CHARS): part 1 carries the head, the columns and a token for the wishes (the server keeps them), the others only their rows. The server joins the parts of a run before it reads them.
      const SLIM_CHARS = 850;
      const slimHead = { ...head, next: 'Pass every part, unchanged, to compose_answer.' };
      const slim0 = (part, parts, chunk) => asciiOnly(JSON.stringify(part === 1
        ? { fmt: 'slim', ...slimHead, run: RUN, rows_read: rows.length, part, parts, wk: typeof WK !== 'undefined' ? WK : null, viewport: window.innerWidth, ...(parts > 1 ? { more: 'window.__mytParts[1] .. [parts-1]' } : {}), cols, common, path_base: base, rows: chunk }
        : { fmt: 'slim', run: RUN, part, parts, rows: chunk }));
      const slim = (part, parts, chunk) => { const t = slim0(part, parts, chunk); return t.slice(0, -1) + ',"crc":"' + crc32(t) + '"}'; };
      const groups = []; let now = [];
      for (const a of arr) { now.push(a); if ((now.length > 1 || groups.length === 0) && slim(groups.length + 1, 9, now).length > SLIM_CHARS) { now.pop(); groups.push(now); now = [a]; } }      // part 1 may hold no row at all when its head is all that fits
      groups.push(now);
      window.__mytParts = groups.map((c, i) => slim(i + 1, groups.length, c));
      return window.__mytParts[0];
    }
    const chunks = []; let cur = [];
    for (const a of arr) { cur.push(a); if (cur.length > 1 && mk(1, 9, cur).length > PART_CHARS) { cur.pop(); chunks.push(cur); cur = [a]; } }
    chunks.push(cur);
    window.__mytParts = chunks.map((c, i) => mk(i + 1, chunks.length, c));
    return window.__mytParts[0];
  };
