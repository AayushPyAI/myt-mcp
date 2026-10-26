"""One module per Chrome-only site: a tested read-only script for the operator's own logged-in Chrome, a URL builder and a converter.

A site module (myt_mcp/sites/<name>.py) must define:
    NAME: str                                  the site key, e.g. "ratehawk_hotels"
    def register(mcp) -> None                  registers the recipe tool (returns the url + script, see ratehawk_hotels.py)
    def convert(result_json: str, wishes: dict, group: str) -> SiteRows
and sits next to its script (myt_mcp/sites/<name>.js). Modules are discovered automatically: no shared file needs editing.
"""

from __future__ import annotations

import functools
import importlib
import json
import os
import pkgutil
import re
import zlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from myt_mcp.compose import Offer, SourceRead
from myt_mcp.ingest import STORE


@dataclass
class SiteRows:
    offers: list[Offer] = field(default_factory=list)
    read: int | None = None            # how many results the script read
    total: int | None = None           # how many exist after the filters (M)
    problems: list[str] = field(default_factory=list)
    sorted_by_price: bool = False
    extra_notes: list[str] = field(default_factory=list)
    read_rows: bool = False           # True when `read` / `total` count rows (rooms of a hotel), not the offers that are kept
    total_absolute: bool = False      # True when `total` is the whole count every part repeats (flights of the day), not a share to add up


def modules() -> dict[str, Any]:
    found: dict[str, Any] = {}
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "NAME") and hasattr(mod, "convert"):
            found[mod.NAME] = mod
    return found


def public_base() -> str:
    """The address the page posts to: PUBLIC_BASE_URL, else the tunnel host in ALLOWED_HOSTS (start_all.sh writes it on every start, so the two cannot differ), else ''."""
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    for host in (h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",")):
        host = host.removesuffix(":*")
        if host and not host.startswith(("127.", "localhost", "[::1]", "0.0.0.0")) and "*" not in host:
            return f"https://{host}"
    return ""


_SERVER_BROWSER: Any = None
_LAST_READ: dict[str, float] = {}
MIN_SECONDS_BETWEEN_READS = 5.0
MAX_READS_PER_HOUR = 40                 # per site: a person searching by hand does about this much
CACHE_SECONDS = 600                     # the same page asked again within 10 minutes is not fetched again
PAUSE_SECONDS = 3600                    # a site that showed a human check or refused the page is left alone for an hour
_READS: dict[str, list[float]] = {}
_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_PAUSED_UNTIL: dict[str, float] = {}
PAUSE_FILE = Path(os.environ.get("MYT_PAUSE_FILE", "/tmp/myt-mcp/paused_sites.json"))     # wall-clock times: a pause survives a restart of the server and is seen by every process
SITE_MIN_SECONDS = {"viator_find": 15.0, "viator_activity": 15.0}      # Viator flagged the server's IP once (15 Oct 2026): slower and fewer reads there
SITE_MAX_PER_HOUR = {"viator_find": 20, "viator_activity": 20}
BLOCK_WORDS = re.compile(r"human check|refuses|block page|captcha|access denied|unusual traffic|blocked by", re.I)


def _load_pauses() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(PAUSE_FILE.read_text()).items()}
    except (OSError, ValueError, TypeError):
        return {}


def paused_minutes(site: str) -> int:
    """Minutes left of a pause (0 = none): from memory (tests) and from the file (a restart, another process)."""
    import time
    until = max(_load_pauses().get(site, 0.0), 0.0)
    left = max(until - time.time(), _PAUSED_UNTIL.get(site, 0.0) - time.monotonic())
    return int(left // 60) + 1 if left > 0 else 0


def pause_site(site: str) -> None:
    import time
    _PAUSED_UNTIL[site] = time.monotonic() + PAUSE_SECONDS
    try:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _load_pauses(); data[site] = time.time() + PAUSE_SECONDS
        PAUSE_FILE.write_text(json.dumps(data))
    except OSError:
        pass


def server_reads(flag: str, default: bool = True) -> bool:
    """Is `flag` (an env switch such as CP_READ_IN_SERVER) on, and does the server have an automation Chrome? For pages whose security policy stops the operator's Chrome from sending the answer to the server."""
    if not server_browser_url():
        return False
    return os.environ.get(flag, "1" if default else "0").strip().lower() not in ("0", "false", "no", "")


def server_browser_url() -> str:
    return os.environ.get("BROWSER_CDP_URL", "").strip()


async def read_in_server_browser(site: str, origin: str, url: str, out: dict[str, Any], ready_path: str | None = None) -> dict[str, Any]:
    """For a page that does not let the operator's Chrome send its answer to this server (the page's security policy): the server opens the page in its own automation Chrome (BROWSER_CDP_URL),
    runs the SAME script there with the whole answer returned to it, and stores it as a run: the model gets the same short receipt and calls compose_answer(runs=[...]) as for any other site.
    Safeguards for the sites' sake: one page at a time per site, a gap between reads, at most MAX_READS_PER_HOUR a site, the same page is served from a 10-minute cache, and a site that showed a
    human check or refused the page is paused for an hour (the operator's own Chrome can still be used then); nothing is ever worked around."""
    import asyncio
    import time
    from myt_mcp.browser import BrowserSession
    from myt_mcp.errors import IntegrationError
    global _SERVER_BROWSER
    now = time.monotonic()

    def finish(raw: str, cached: bool = False) -> dict[str, Any]:
        data = json.loads(raw)
        if not data.get("ok"):
            return {"ok": False, "source": site, "error": data.get("error", "the page could not be read"),
                    "next": "Put this source in not_checked with the reason the error gives (block / no flights / not served); never type a row yourself."}
        token = STORE.new_run(site, out.get("wishes") or {}, out.get("filters_used"))
        status, receipt = STORE.accept(token, raw.encode("utf-8"))
        return {"ok": status == 200, "received": status == 200, "how": "read by the server itself in its own automation Chrome" + (" (the same page, read a few minutes ago)" if cached else ""), "ingest": token,
                "rows_read": receipt.get("rows"), "filters_used": out.get("filters_used"), "wishes": out.get("wishes"),
                "next": f'STOP: do not read or type any row. Call compose_answer with runs=["{token}"] (plus kind, not_checked) and show the text it returns, nothing else.'}

    left = paused_minutes(site)
    if left:
        return {"ok": False, "source": site, "error": f"{site} is paused for {left} more minutes after it showed a human check or refused a page: the server leaves it alone.",
                "next": "Put this source in not_checked with the reason 'block: the site refused the server's browser' and go on; never type a row yourself."}
    hit = _CACHE.get((site, url))
    if hit and now - hit[0] < CACHE_SECONDS:
        return finish(hit[1], cached=True)
    recent = [t for t in _READS.get(site, []) if now - t < 3600]
    cap = SITE_MAX_PER_HOUR.get(site, MAX_READS_PER_HOUR)
    if len(recent) >= cap:
        return {"ok": False, "source": site, "error": f"the server already read {site} {len(recent)} times in the last hour (its limit is {cap}).",
                "next": "Put this source in not_checked with the reason 'did not answer: hourly limit of the server' and go on; never type a row yourself."}
    if _SERVER_BROWSER is None:
        _SERVER_BROWSER = BrowserSession(server_browser_url())
    wait = max(MIN_SECONDS_BETWEEN_READS, SITE_MIN_SECONDS.get(site, 0.0)) - (time.monotonic() - _LAST_READ.get(site, 0.0))
    if wait > 0:
        await asyncio.sleep(wait)                              # the site is read slowly, one page at a time
    head = "await (async () => {\n"
    script = out["script"].replace(head, head + "  const LOCAL_RETURN = true;\n", 1)

    async def action(page: Any) -> str:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if ready_path:             # the booking page redirects itself after loading
            try:
                await page.wait_for_url(f"**{ready_path}*", timeout=25000)
            except Exception:
                pass               # the script says what is on the page
        blocked = await page.evaluate("() => /Ray ID|Access denied|Pardon Our Interruption|unusual traffic|An error occurred\\.\\s+We.ll be right back|Request blocked|403 Forbidden/i.test((document.title + ' ' + document.body.innerText).slice(0, 900))")
        if blocked is True:
            return json.dumps({"ok": False, "error": f"{site} shows a block page (it refuses the server's browser). Stop: do not retry and do not work around it."})
        return await page.evaluate("async () => (" + script + ")")

    try:
        _READS.setdefault(site, []).append(time.monotonic())
        try:
            raw = await _SERVER_BROWSER.run(origin, url, action)
        except IntegrationError as e:
            return {"ok": False, "source": site, "error": str(e), "next": "Put this source in not_checked with the reason 'did not answer: the server's browser could not read it' and go on; never type a row yourself."}
    finally:
        _LAST_READ[site] = time.monotonic()
    data = json.loads(raw)
    if not data.get("ok") and BLOCK_WORDS.search(str(data.get("error", ""))):
        pause_site(site)
    elif data.get("ok"):
        _CACHE[(site, url)] = (time.monotonic(), raw)
    return finish(raw)


def embed_wishes(out: Any, site: str | None = None) -> Any:
    """The operator's wishes for THIS script (and the filters it was given) travel inside the script's own answer: the model passes ONE `wishes` to compose_answer for every source,
    so a source whose recipe had other wishes (checked bag, refundable) was judged by the wrong ones (seen 23 Oct 2026: a fare with no bag and no refund became 'Best fit')."""
    if isinstance(out, dict) and out.get("script"):
        head = "await (async () => {\n"
        base = public_base()
        if base and site:       # the answer goes from the page straight to this server (myt_mcp/ingest.py); the wishes stay here
            token = STORE.new_run(site, out.get("wishes") or {}, out.get("filters_used"))
            out["script"] = out["script"].replace(head, head + f"  const INGEST = {json.dumps({'url': f'{base}/ingest/{token}', 'token': token})};\n", 1)
            out["ingest"] = token
            out["before_you_run"] = "The page must be at least 1200 px wide (the script reports window.innerWidth): in a narrow page (side panel open) RateHawk and Skyscanner show a mobile layout in which the scripts find nothing. You cannot resize the window or a tab: ask the operator to close or shrink the side panel or to zoom the page out (Ctrl and minus, about 67%), then run the script."
            out["finish"] = f"After the script's receipt call compose_answer with runs=[\"{token}\"] (no site_results, no typed rows)."
        elif out.get("wishes"):
            out["warning"] = "This server has no public address (PUBLIC_BASE_URL or a tunnel host in ALLOWED_HOSTS): the script returns its answer in parts the browser tool cuts at about 1,000 characters. Tell the operator before using it."
            carried = {"wishes": out.get("wishes") or {}, **({"filters_used": out["filters_used"]} if out.get("filters_used") else {})}
            out["script"] = out["script"].replace(head, head + f"  const WISHES = {json.dumps(carried, ensure_ascii=False)};\n", 1)
    return out


class _EmbeddingTools:
    """Hands a site module the real mcp, with `tool` wrapped so that every recipe answer carries its wishes inside its script."""

    def __init__(self, mcp: Any, site: str | None = None):
        self._mcp = mcp
        self._site = site

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mcp, name)

    def tool(self, *args: Any, **kwargs: Any) -> Any:
        register = self._mcp.tool(*args, **kwargs)

        def decorate(fn: Any) -> Any:
            @functools.wraps(fn)
            async def wrapped(*a: Any, **k: Any) -> Any:
                return embed_wishes(await fn(*a, **k), self._site)
            return register(wrapped)
        return decorate


def register_all(mcp: Any) -> None:
    for mod in modules().values():
        if hasattr(mod, "register"):
            mod.register(_EmbeddingTools(mcp, getattr(mod, "NAME", None)))


MIN_WIDTH = 1000


def narrow_window(mod: Any, item: dict[str, Any]) -> str | None:
    """Sites whose pages change to a mobile layout in a narrow window (RateHawk, Skyscanner) set NEEDS_WIDE_WINDOW: a script that ran in such a window read the wrong layout (23 Oct 2026)."""
    if not getattr(mod, "NEEDS_WIDE_WINDOW", False):
        return None
    try:
        width = json.loads(item.get("result", "")).get("viewport")
    except (TypeError, ValueError, AttributeError):
        return None
    if isinstance(width, (int, float)) and width < MIN_WIDTH:
        return f"{getattr(mod, 'SOURCE', item.get('site'))}: the browser window was only {int(width)} px wide, so the page showed its narrow (mobile) layout and the script read it wrongly: make the page at least 1200 px wide: close or shrink the side panel, or ask the operator to zoom the page out (Ctrl and minus, about 67%) because the script reads the page's own width; then run the script once more"
    return None


def _run_key(item: dict[str, Any]) -> tuple[str, str]:
    try:
        data = json.loads(item.get("result", ""))
    except (TypeError, ValueError):
        return (str(item.get("site", "")), "")
    return (str(item.get("site", "")), str(data.get("run", "")) if isinstance(data, dict) else "")


def carried_wishes(site_results: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """{(site, run): {"wishes": ..., "filters_used": [...]}} read from the part of each script run that carries them (part 1): the other parts of the run use the same."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for item in site_results:
        if isinstance(item.get("wishes"), dict) and "filters_used" in item:        # an answer the server itself received (ingest): its wishes were issued by the server
            found[_run_key(item)] = {"wishes": item["wishes"], "filters_used": item.get("filters_used") or []}
            continue
        try:
            data = json.loads(item.get("result", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("wishes"), dict) and data.get("run"):
            found[_run_key(item)] = {"wishes": data["wishes"], "filters_used": data.get("filters_used") or []}
    return found


def convert_all(site_results: list[dict[str, Any]], wishes: dict[str, Any] | None, group_for: dict[str, str] | None = None) -> tuple[list[Offer], list[SourceRead], list[str], bool, list[str]]:
    """site_results: [{"site": "ratehawk_hotels", "result": "<the script's answer text>", "url": "<the page address>"}]."""
    mods = modules()
    offers: list[Offer] = []
    sources: dict[str, SourceRead] = {}
    problems: list[str] = []
    notes: list[str] = []
    by_price = False
    reads: dict[str, set[str]] = {}
    counted: dict[str, dict[str | None, tuple[int, int]]] = {}
    links: dict[str, dict[str | None, str]] = {}      # one link per leg: a trip's outbound and return pages are both sources
    problems += check_parts(site_results)
    carried = carried_wishes(site_results)
    for item in site_results:
        site = item.get("site", "")
        mod = mods.get(site)
        if mod is None:
            problems.append(unknown_site(site, mods))
            continue
        narrow = narrow_window(mod, item)
        if narrow:
            problems.append(narrow)
            continue
        item_wishes = item.get("wishes") or carried.get(_run_key(item), {}).get("wishes") or wishes or {}
        rows = mod.convert(expand(item.get("result", "")), item_wishes, (group_for or {}).get(site, getattr(mod, "GROUP", "Options")))
        problems += rows.problems
        notes += rows.extra_notes
        by_price = by_price or rows.sorted_by_price
        seen = reads.setdefault(site, {o.link or f"{o.name}|{o.price_total}" for o in offers if o.source == getattr(mod, "SOURCE", site)})
        for o in rows.offers:
            key = o.link or f"{o.name}|{o.price_total}"
            if key not in seen:
                seen.add(key)
                offers.append(o)
        src_name = getattr(mod, "SOURCE", site)
        cur = sources.get(site)
        if rows.read_rows:       # e.g. the rooms read on hotel pages: every room read counts, one offer is kept per hotel
            legs = counted.setdefault(site, {})      # a whole count repeats within one leg (its batches), but the legs of a trip add up
            leg = (item_wishes.get("expect") or {}).get("leg")
            prev = legs.get(leg, (0, 0))
            legs[leg] = (prev[0] + (rows.read or 0), max(prev[1], rows.total or 0) if rows.total_absolute else prev[1] + (rows.total or 0))
            read, of = sum(v[0] for v in legs.values()), sum(v[1] for v in legs.values())
        else:
            read, of = len(seen) or None, rows.total or (cur.of if cur else None)
        if item.get("url"):
            links.setdefault(site, {})[(item_wishes.get("expect") or {}).get("leg")] = item["url"]
        mine = links.get(site) or {}
        link = (next(iter(mine.values())) if len(mine) == 1 else "; ".join(f"{leg}: {url}" if leg else url for leg, url in mine.items())) if mine else (cur.link if cur else None)
        sources[site] = SourceRead(name=src_name, read=read, of=of, link=link)
    return offers, list(sources.values()), problems, by_price, notes



def with_emit(script: str) -> str:
    """Adds the short-parts output step (emit.js) to a site script: it must start its body with 'await (async () => {' and end with emit(head, rows)."""
    head = "await (async () => {\n"
    if head not in script:
        raise ValueError("site script must start its body with 'await (async () => {'")
    return script.replace(head, head + Path(__file__).with_name("emit.js").read_text(encoding="utf-8"), 1)


def expand(raw: str) -> str:
    """The compact form the scripts emit (columns, common values, path base) back to the plain `rows` of dicts the converters read. Other text passes unchanged."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if not isinstance(data, dict) or "cols" not in data:
        return raw
    cols, common, base = data.pop("cols"), data.pop("common", None) or {}, data.pop("path_base", "") or ""
    rows = []
    for values in data.get("rows", []):
        row = dict(common)
        row.update(zip(cols, values))
        if row.get("path") and "path" in cols:
            row["path"] = base + row["path"]
        rows.append(row)
    data["rows"] = rows
    return json.dumps(data)


def checksum_problem(raw: str) -> str | None:
    """Each part ends with `,"crc":"<crc32 of the text before it>"}` (emit.js). None when it matches; else what is wrong."""
    text = raw.strip()
    cut = text.rfind(',"crc":"')
    if cut < 0 or not text.endswith('"}'):
        return "has no checksum (it was cut or rewritten)"
    expected = format(zlib.crc32((text[:cut] + "}").encode("utf-8")), "08x")
    return None if text[cut + 8:-2] == expected else "does not match its checksum (a character was changed while it was passed on)"


def unknown_site(site: str, mods: dict[str, Any]) -> str:
    """The site name is the recipe's own key ('getyourguide_find'): a display name ('GetYourGuide', 'Ratehawk') is refused with the keys it could mean (24-26 Oct 2026: both were sent and the rows were dropped)."""
    flat = re.sub(r"[^a-z0-9]", "", str(site).lower())
    near = sorted(k for k in mods if flat and (flat in k.replace("_", "") or k.replace("_", "") in flat))
    hint = f" Did you mean {' or '.join(repr(k) for k in near)}? Use the exact key, the same as the recipe tool you ran (the list of tours or hotels and the page of one tour or room are different keys)." if near else ""
    return f"unknown site '{site}': known sites are {sorted(mods)}.{hint}"


def check_parts(site_results: list[dict[str, Any]]) -> list[str]:
    """Every run of a script is sent in parts: all of them must be here, and together they must hold every row the script says it read."""
    runs: dict[tuple[str, str], dict[int, int]] = {}
    meta: dict[tuple[str, str], tuple[int, int]] = {}
    bad: list[str] = []
    for item in site_results:
        try:
            data = json.loads(item.get("result", ""))
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("parts") and data.get("run"):
            why = checksum_problem(str(item.get("result", "")))
            if why:
                bad.append(f"{item.get('site')}: part {data.get('part')} of {data.get('parts')} {why}: run window.__mytParts[{int(data.get('part', 1)) - 1}] again in the same Chrome tab and pass it exactly as it is")
            key = (str(item.get("site", "")), str(data["run"]))
            runs.setdefault(key, {})[int(data.get("part", 0))] = len(data.get("rows") or [])
            meta[key] = (int(data["parts"]), int(data.get("rows_read") or 0))
    problems = list(dict.fromkeys(bad))
    for key, got in runs.items():
        parts, rows_read = meta[key]
        missing = [i for i in range(1, parts + 1) if i not in got]
        if missing:
            problems.append(f"{key[0]}: part(s) {', '.join(map(str, missing))} of {parts} are missing: run window.__mytParts[<number minus 1>] in the same Chrome tab (the answer's `more` line) and pass each part unchanged as its own item of site_results")
        elif sum(got.values()) != rows_read:
            problems.append(f"{key[0]}: the parts hold {sum(got.values())} rows but the script read {rows_read}: run the script again and pass every part unchanged")
    return problems


GENERIC_PLACE_WORDS = {"airport", "station", "railway", "terminal", "international", "intl", "city", "center", "centre", "downtown", "the", "of", "de", "da", "di", "and"}


def place_matches(expected: str | None, got: str | None) -> bool:
    """Is the place the page searched the place that was asked? Compared by the DISTINCTIVE words (not 'airport', 'station'...): 'Faro Airport' is 'Portugal, Faro Airport', never 'Spain, Malaga Airport'."""
    def words(x: str | None) -> set[str]:
        return {w for w in re.sub(r"[^a-z0-9]+", " ", (x or "").lower()).split() if w not in GENERIC_PLACE_WORDS}
    want, have = words(expected), words(got)
    return not want or not have or bool(want & have)
