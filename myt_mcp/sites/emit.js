  // Output: claude.ai cuts long tool answers, and a cut or re-typed answer is not the page's data. So the rows leave in short, self-contained
  // PARTS (about PART_CHARS each), in a compact form (columns named once, columns that never change moved to `common`). Part 1 is returned; the
  // others stay in window.__mytParts and are fetched with one short expression. The server decodes and joins the parts and checks none is missing.
  const PART_CHARS = 3500;
  const RUN = Date.now().toString(36);
  const emit = (head, rows) => {
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
    const mk = (part, parts, chunk) => JSON.stringify({ ...head, run: RUN, rows_read: rows.length, part, parts, ...(part === 1 && parts > 1 ? { more: 'window.__mytParts[1] (then [2], [3] ... up to parts-1)', note: MORE } : {}), cols, common, path_base: base, rows: chunk });
    const chunks = []; let cur = [];
    for (const a of arr) { cur.push(a); if (cur.length > 1 && mk(1, 9, cur).length > PART_CHARS) { cur.pop(); chunks.push(cur); cur = [a]; } }
    chunks.push(cur);
    window.__mytParts = chunks.map((c, i) => mk(i + 1, chunks.length, c));
    return window.__mytParts[0];
  };
