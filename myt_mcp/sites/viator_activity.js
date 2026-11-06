// Viator activity price reader. Run it on ONE Viator activity page (www.viator.com/tours/<place>/<name>/d<id>-<CODE>; read only).
// The activity page's booking box gets its options and prices from ONE request, POST /orion/ajax/product-availability (the product code, the date, the travellers per age band): the script sends that same request from the
// page, with the page's own security token (the page's data names its header and token), for the date and the group the operator asked for (no calendar and no traveller box are touched), and reads every option with the
// price of the WHOLE group (the discounted and the list price, the price per age band), its start times, the spots left, the pay-later deadline and the cancellation; the price calendar the page loads (GET .../product-price-calendar/<code>)
// tells which dates are bookable. The activity's own description (duration, languages, what is included, the meeting point, additional information, the cancellation policy) is read from the page's embedded data
// (<script id="globalState">). It books nothing and holds nothing. The tool replaces __REQUEST__ (the activity, the day, the travellers).
await (async () => {
  const REQ = __REQUEST__;
  const text = () => (document.body && document.body.innerText) || '';
  if (/(?<!re)captcha|performing security verification|just a moment\.\.\.|checking if the site connection is secure|verify you are human|access denied|unusual traffic|are you a robot/i.test(text().slice(0, 1500)) && !document.getElementById('globalState')) return JSON.stringify({ ok: false, error: 'Viator shows a human check or refuses the page. Stop: do not retry and do not work around it; tell the operator to look at the page.' });
  if (!/(^|\.)viator\.com$/.test(location.hostname) || !/\/tours\/.+\/d\d+-/.test(location.pathname)) return JSON.stringify({ ok: false, error: 'not a Viator activity page (www.viator.com/tours/<place>/<name>/d123-CODE): open the url first' });
  const el = document.getElementById('globalState');
  let pre = null; try { pre = el ? JSON.parse(el.textContent).__PRELOADED_DATA__ : null; } catch (err) { pre = null; }
  const product = pre && pre.pageModel && pre.pageModel.product;
  if (!product || !product.productCode) return JSON.stringify({ ok: false, error: 'the page has no activity data (Viator changed its page or the page is not loaded yet): say it could not be read' });
  if (REQ.code && product.productCode !== REQ.code) return JSON.stringify({ ok: false, error: 'the page is the activity ' + product.productCode + ', not ' + REQ.code + ': open the url again' });
  const csrf = pre.csrf || {};
  if (!csrf.headerName || !csrf.token) return JSON.stringify({ ok: false, error: 'the page gives no security token for its availability request (the site changed): say it could not be read' });
  const t0 = performance.now();
  const ranges = ((product.availabilityConfig || {}).ageBandRanges || []).filter((r) => r && r.ageBand);
  const bands = {}; const unfit = [];
  if (REQ.adults) { const a = ranges.find((r) => r.ageBand === 'ADULT') || ranges[0]; if (a) bands[a.ageBand] = (bands[a.ageBand] || 0) + REQ.adults; else unfit.push('adult'); }
  (REQ.ages || []).forEach((age) => { const r = ranges.find((x) => (x.ageMin == null || x.ageMin <= age) && (x.ageMax == null || age <= x.ageMax)); if (r) bands[r.ageBand] = (bands[r.ageBand] || 0) + 1; else unfit.push(String(age)); });
  const accepted = ranges.map((r) => r.ageBand + ' ' + r.ageMin + '-' + r.ageMax).join(', ') || 'not listed';
  if (unfit.length) return JSON.stringify({ ok: false, error: 'this activity does not take a traveller aged ' + unfit.join(', ') + ' (its age groups: ' + accepted + '): tell the operator' });
  const headers = { Accept: 'application/json' }; headers[csrf.headerName] = csrf.token;
  const asBands = {}; Object.keys(bands).forEach((k) => { asBands[k] = String(bands[k]); });
  let av; let cal = null;
  try {
    const [ra, rc] = await Promise.all([
      fetch('/orion/ajax/product-availability', { method: 'POST', credentials: 'same-origin', headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify({ productCode: product.productCode, searchDate: REQ.day, ageBands: asBands, source: 'commerce_module' }) }),
      fetch('/orion/ajax/react/product-price-calendar/' + product.productCode, { credentials: 'same-origin', headers }).catch(() => null)]);
    if (!ra.ok) throw new Error('answered ' + ra.status);
    av = await ra.json();
    if (rc && rc.ok) cal = await rc.json().catch(() => null);
  } catch (err) { return JSON.stringify({ ok: false, error: 'Viator\'s availability service could not be read (' + String(err.message || err).slice(0, 80) + '): say it could not be read' }); }
  const ms = Math.round(performance.now() - t0);
  const amt = (m) => (m && Number.isFinite(m.amount) ? m.amount : null);
  const strip = (s) => String(s || '').replace(/<[^>]*>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
  const grades = ((av.productAvailability || {}).tourGrades || []);
  const rows = grades.map((g) => {
    const p = g.price || {};
    return { option: g.title || null, code: g.tourGradeCode || null, available: g.isAvailable !== false && g.availability === 'AVAILABLE', availability: g.availability || null, date: g.date || null, spots: Number.isFinite(g.spotsLeft) ? g.spotsLeft : null,
      total: amt(p.discountedPrice) != null ? amt(p.discountedPrice) : amt(p.retailPrice), list_total: amt(p.retailPrice), discounted: p.isDiscounted === true, saved: amt(p.discountAmount), cur: g.currency || (p.retailPrice || {}).currencyCode || null,
      extra_charges: amt(g.totalRetailPricePlusExtraCharges), breakdown: (g.priceBreakdown || []).map((b) => ({ band: b.ageBand, n: b.numberOfTravelers, unit: amt((b.price || {}).discountedPrice), list: amt((b.price || {}).retailPrice) })),
      times: (g.startTimes || []).map((t) => ({ t: t.startTime24H || null, label: t.startTime || null, price: amt((t.price || {}).discountedPrice), spots: Number.isFinite(t.spotsLeft) ? t.spotsLeft : null, ok: t.availabilityResult ? t.availabilityResult === 'AVAILABLE' : null })),
      pay_by: g.earliestPaymentDate || null, reserve: g.isReserveEligible === true, langs: ((g.languages || []).length ? g.languages : (g.languageCodes || [])).filter(Boolean), guide: [...new Set((g.languageServices || []).flatMap((l) => [l.hasHumanGuide ? 'live guide' : null, l.hasAudioGuide ? 'audio guide' : null, l.hasWrittenGuide ? 'written guide' : null]).filter(Boolean))], about: strip(g.description).slice(0, 300) };
  });
  const policy = av.cancellationPolicyDetails || {};
  const d = product.description || {};
  const feats = (x) => ((x && x.features) || []).map((f) => (typeof f === 'string' ? f : f && f.text) || '').filter(Boolean);
  const dep = product.departureAndReturnLocations || {};
  const loc = (l) => strip((l.description || '') + (l.instructions ? ' (' + l.instructions + ')' : ''));
  const meeting = [].concat((dep.departureLocations || []).map((l) => 'Start: ' + loc(l)), (dep.returnLocations || []).map((l) => 'End: ' + loc(l))).filter(Boolean).join('; ');
  const dur = product.duration || {};
  const durText = [dur.days ? dur.days + (dur.days === 1 ? ' day' : ' days') : '', dur.hours ? dur.hours + (dur.hours === 1 ? ' hour' : ' hours') : '', dur.minutes ? dur.minutes + ' minutes' : ''].filter(Boolean).join(' ') || null;
  const langs = (product.productLanguages || {}).offeredLanguages || [];
  const attrs = product.productAttributes || [];
  const dates = (cal && cal.dates) || null;
  const askedDay = REQ.day; const later = dates ? Object.keys(dates).filter((k) => k >= askedDay).sort().slice(0, 5).map((k) => k + ' ' + (dates[k].formattedPrice || '')) : null;
  const pol = d.cancellationPolicy || {};
  return emit({ ok: true, next: 'STOP: do not write the answer yourself. Call compose_answer with this text unchanged (site_results) and show the text it returns, nothing else.',
    url_path: location.pathname, activity: product.title || document.title, code: product.productCode, supplier: product.supplierName ? String(product.supplierName).trim() : null, day: REQ.day, bands_sent: bands, travellers_sent: Object.values(bands).reduce((a, b) => a + b, 0),
    unit_pricing: (((product.pricing || {}).price || {}).hasUnitPricing) === true, max_per_unit: (product.pricing || {}).maxTravelersPerUnit || null, extra_per_traveller: (((product.pricing || {}).price || {}).extraChargeAmount || {}).amount || null, private_tour: product.isPrivateTour === true,
    options_found: rows.length, errors: av.validationErrors && Object.keys(av.validationErrors).length ? Object.keys(av.validationErrors) : null, max_travellers: (product.availabilityConfig || {}).maxTravellersPerBooking || null, age_groups: accepted,
    duration: durText, offered_in: langs.map((l) => l.displayName || l.code).filter(Boolean).join(', ') || null, mobile_ticket: attrs.some((a) => a.type === 'MOBILE_PHONE_TICKET'), time_zone: product.timeZone || null, free_cancel_flag: product.hasFreeCancellation === true,
    policy_type: policy.policyType || null, refund_until: policy.refundEligibleUntilDate || null, refund_deadline_past: policy.isRefundDeadlineInPast === true,
    included: feats(d.inclusions).join('; ') || null, excluded: feats(d.exclusions).join('; ') || null, additional: feats(d.additionalInfo).join('; ') || null, meeting_text: meeting || null,
    cancel_policy: ((pol.policies || []).map(strip).join(' ') || strip(pol.cancellationPolicyLabel + ' ' + (pol.cancellationPolicyDescription || ''))) || null,
    day_bookable: dates ? Object.prototype.hasOwnProperty.call(dates, askedDay) : null, next_dates: later, calendar_cur: cal ? cal.currencyCode || null : null, ms }, rows);
})()
