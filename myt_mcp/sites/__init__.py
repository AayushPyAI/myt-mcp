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
import logging
import os
import pkgutil
import re
import time
import zlib
from datetime import date
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

from myt_mcp.compose import Offer, SourceRead
from myt_mcp.ingest import STORE

log = logging.getLogger("myt_mcp")


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
    more_exist: bool = False          # True when the page has more than were loaded and the page's own total is not known: shown as 'N of N+' (29 Oct 2026: "30 of 30 read" next to "more cars exist")


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
_SLOTS: dict[int, Any] = {}      # one semaphore per event loop: how many pages the server's Chrome reads at the same time


def read_slots() -> Any:
    """Six tools called together made Europcar take 76 s instead of 19 s (27 Oct 2026: one Chrome, one CPU). SERVER_READS_AT_ONCE (default 2; 1 = strictly one after another) is how many pages it reads at once, the rest wait in a line."""
    import asyncio
    loop = asyncio.get_running_loop()
    if id(loop) not in _SLOTS:
        try:
            n = max(1, int(os.environ.get("SERVER_READS_AT_ONCE", "2")))
        except ValueError:
            n = 2
        _SLOTS[id(loop)] = asyncio.Semaphore(n)
    return _SLOTS[id(loop)]
PAUSE_FILE = Path(os.environ.get("MYT_PAUSE_FILE", "/tmp/myt-mcp/paused_sites.json"))     # wall-clock times: a pause survives a restart of the server and is seen by every process
SITE_MIN_SECONDS = {"viator_find": 15.0, "viator_activity": 15.0}      # Viator flagged the server's IP once (15 Oct 2026): slower and fewer reads there
SITE_MAX_PER_HOUR = {"viator_find": 20, "viator_activity": 20}
SITE_PAUSE_SECONDS = {"rentalcars_cars": 6 * 3600}      # Rentalcars.com showed "Human Verification" to the server's IP on 27 Oct 2026: it is tried again only every 6 hours, the operator's Chrome reads it meanwhile
SERVER_READ_SECONDS = 120.0      # the whole server read of one page, slot queue included: claude.ai ends a tool call after 180 s
DEFINITIVE = re.compile(r"do not retry|lists no flights?|no flights? available|has no flights|no results were found|no trains", re.I)      # the site's own "nothing for this search" answers
BLOCK_WORDS = re.compile(r"human check|human verification|confirm you are human|verify you are human|refuses|block page|captcha|access denied|unusual traffic|blocked by", re.I)


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
    seconds = SITE_PAUSE_SECONDS.get(site, PAUSE_SECONDS)
    _PAUSED_UNTIL[site] = time.monotonic() + seconds
    try:
        PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _load_pauses(); data[site] = time.time() + seconds
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
        blocked = await page.evaluate("() => /Ray ID|Access denied|Pardon Our Interruption|unusual traffic|An error occurred\\.\\s+We.ll be right back|Request blocked|403 Forbidden|Human Verification|confirm you are human|verify you are human/i.test((document.title + ' ' + document.body.innerText).slice(0, 900)) || /captcha/i.test(location.href)")
        if blocked is True:
            return json.dumps({"ok": False, "error": f"{site} shows a block page (it refuses the server's browser). Stop: do not retry and do not work around it."})
        return await page.evaluate("async () => (" + script + ")")

    try:
        _READS.setdefault(site, []).append(time.monotonic())
        try:
            async with read_slots():       # a short line for the one Chrome: at most SERVER_READS_AT_ONCE pages are read together
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


async def server_first(site: str, flag: str, origin: str, out: dict[str, Any], ready_path: str | None = None, default: bool = True) -> dict[str, Any]:
    """The server's own automation Chrome reads the page FIRST (the same script, the whole answer stays here: the model gets a short receipt and calls compose_answer(runs=[...]));
    when it cannot (no automation Chrome, the site paused after a block, a human check or block page, a timeout, a script error, the answer not accepted) the recipe comes back unchanged for the operator's Claude in Chrome,
    with the reason in `server_read`. Nothing is ever worked around: a block only means the other way is used."""
    if not server_reads(flag, default):      # default False: the site is read in the operator's Chrome unless the flag is set to 1 (Rentalcars.com: its prices follow the visitor's country)
        return out
    import asyncio
    budget = float(os.environ.get("SERVER_READ_SECONDS", str(SERVER_READ_SECONDS)))
    try:
        result = await asyncio.wait_for(read_in_server_browser(site, origin, out["url"], out, ready_path), timeout=budget)
    except asyncio.TimeoutError:      # claude.ai ends a tool call after 180 s (28 Oct 2026: Skyscanner sat on a check page and the whole call was lost): the recipe goes back in time
        result = {"ok": False, "error": f"the server's browser did not finish within {budget:.0f} s (a slow page or a check page)"}
    except Exception as e:      # whatever went wrong in the server's browser, the operator's Chrome is still there
        result = {"ok": False, "error": f"the server's browser failed ({type(e).__name__})"}
    if result.get("ok"):
        return result
    why = str(result.get("error") or "the server's browser could not read the page")
    if DEFINITIVE.search(why) and not BLOCK_WORDS.search(why):      # the site itself said there is nothing for this search (TAP, SATA, CP): reading it again in Chrome only finds the same (28 Oct 2026)
        return {"ok": False, "source": site, "server_read": {"tried": True, "ok": False, "why": why[:300]}, "error": why[:300],
                "next": "The site itself answered that it has nothing for this search (see `error`). Do NOT read it in Claude in Chrome: put it in not_checked with that reason (route not served / not available) and go on; never type a row."}
    out["server_read"] = {"tried": True, "ok": False, "why": why[:300]}
    out["how_to_read"] = ("The server's own browser could not read this page (see server_read.why). Read it in Claude in Chrome instead: open the url, run the script with the javascript tool, then call compose_answer with the receipt as the other recipes do. "
                          "Do not retry the server's read and never type a row.")
    return out


def clock24(text: Any) -> str | None:
    """'5:30 AM' -> '05:30', '1:00 PM' -> '13:00', '23:30' -> '23:30' (the server's Chrome speaks US English, the operator's does not): the same clock for every reader."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*", str(text or ""))
    if not m:
        return None if text in (None, "") else str(text)
    h, mi, ap = int(m.group(1)), m.group(2), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi}"


def day_month(text: Any) -> str | None:
    """'Mar 7' -> '7 Mar' (US order to the order the operator's Chrome shows); '7 Mar' and anything else stay as they are."""
    m = re.fullmatch(r"\s*([A-Z][a-z]{2})\s+(\d{1,2})\s*", str(text or ""))
    return f"{int(m.group(2))} {m.group(1)}" if m else (None if text in (None, "") else str(text))


# Pages whose security policy blocks a post to another address (seen: ingest received nothing from them): their scripts return the answer in parts, with no address to post to
NO_POST = {"getyourguide_find", "getyourguide_activity", "viator_find", "viator_activity", "ratehawk_hotels", "cp_trains", "sata"}
SLIM_SITES = {"ratehawk_hotels"}      # their parts are made short enough for ONE tool output (emit.js SLIM) and joined by the server before they are read (join_slim_parts)


def embed_wishes(out: Any, site: str | None = None) -> Any:
    """The operator's wishes for THIS script (and the filters it was given) travel inside the script's own answer: the model passes ONE `wishes` to compose_answer for every source,
    so a source whose recipe had other wishes (checked bag, refundable) was judged by the wrong ones (seen 23 Oct 2026: a fare with no bag and no refund became 'Best fit')."""
    if isinstance(out, dict) and out.get("script"):
        out.setdefault("tab", "Open the url in a NEW tab (tabs_create_mcp), never in the operator's current tab: their own work is open there (27 Oct 2026: a search replaced the operator's Booking.com flight search). "
                              "Close that tab when you have the receipt.")      # a recipe may bring its own rule (iWay: its own tab, in front)
        head = "await (async () => {\n"
        base = public_base()
        if base and site in NO_POST:     # the page's security policy stops the post, so the script gets no address to post to (once the chat's Claude declined to run a GetYourGuide script that posts to this server: "sends page data to an unfamiliar outside web address", 26 Oct 2026; a model's choice, not a block)
            token = STORE.new_run(site, out.get("wishes") or {}, out.get("filters_used"))      # compose_answer tells from it that a recipe was issued and not used; a slim script carries only this token
            if site in SLIM_SITES:
                out["script"] = out["script"].replace(head, head + f"  const SLIM = true;\n  const WK = {json.dumps(token)};\n", 1)
                out["how_the_answer_comes_back"] = ("This page cannot send its answer to the server: the script returns it in short parts (window.__mytParts), each small enough to show in ONE output of the browser tool (it cuts at about 1,000 characters). "
                                                    "The script's answer is part 1 and says how many parts there are: run `window.__mytParts[1]`, `window.__mytParts[2]` ... one by one, and pass EVERY part to compose_answer exactly as it is (no slicing, no retyping), "
                                                    "each as its own item of `site_results` with the recipe's own `site` key. A part you did not see whole is run again, never completed by hand.")
            else:
                if out.get("wishes"):
                    carried = {"wishes": out.get("wishes") or {}, **({"filters_used": out["filters_used"]} if out.get("filters_used") else {})}
                    out["script"] = out["script"].replace(head, head + f"  const WISHES = {json.dumps(carried, ensure_ascii=False)};\n", 1)
                out["how_the_answer_comes_back"] = "This page cannot send its answer to the server: the script returns it in parts (window.__mytParts). Pass each part to compose_answer exactly as it is, with the recipe's own `site` key."
        elif base and site:       # the answer goes from the page straight to this server (myt_mcp/ingest.py); the wishes stay here
            token = STORE.new_run(site, out.get("wishes") or {}, out.get("filters_used"))
            out["script"] = out["script"].replace(head, head + f"  const INGEST = {json.dumps({'url': f'{base}/ingest/{token}', 'token': token})};\n", 1)
            out["ingest"] = token
            out["before_you_run"] = "The page must be at least 1200 px wide (the script reports window.innerWidth): in a narrow page (side panel open) RateHawk and Skyscanner show a mobile layout in which the scripts find nothing. A resize_window call can report success and change nothing while the side panel is open (28 Oct 2026: it said done and the width stayed 720): read window.innerWidth again after it. If it is still under 1200, ask the operator to close or shrink the side panel or to zoom the page out (Ctrl and minus, about 67%), then run the script."
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
        elif isinstance(data, dict) and data.get("wk") and data.get("run"):        # a slim part 1: the server kept the wishes of that recipe call
            kept = STORE.wishes_of(data["wk"])
            if kept:
                found[_run_key(item)] = {"wishes": kept[0], "filters_used": kept[1]}
    return found


SLIM_ONLY_KEYS = {"fmt", "cols", "common", "path_base", "rows", "part", "parts", "wk", "more", "note", "crc"}


def join_slim_parts(site_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The slim parts of one script run (emit.js SLIM: the head, the columns and the wishes' token in part 1, only rows in the others) become ONE answer, the plain rows the converter reads, with the wishes the server kept.
    A run with a part missing is left out: check_parts has already said which part to run again."""
    runs: dict[tuple[str, str], dict[int, tuple[dict[str, Any], dict[str, Any]]]] = {}
    out: list[dict[str, Any]] = []
    for item in site_results:
        try:
            data = json.loads(item.get("result", ""))
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("fmt") == "slim" and data.get("run") and data.get("parts"):
            runs.setdefault((str(item.get("site", "")), str(data["run"])), {})[int(data.get("part", 0))] = (data, item)
        else:
            out.append(item)
    for (site, run), got in runs.items():
        total = max(int(d["parts"]) for d, _ in got.values())
        if sorted(got) != list(range(1, total + 1)):
            continue
        first = got[1][0]
        cols, common, base = first.get("cols") or [], first.get("common") or {}, first.get("path_base") or ""
        rows: list[dict[str, Any]] = []
        for n in range(1, total + 1):
            for values in got[n][0].get("rows") or []:
                row = dict(common)
                row.update(zip(cols, values))
                if row.get("path") and "path" in cols:
                    row["path"] = base + row["path"]
                rows.append(row)
        joined: dict[str, Any] = {"site": site, "result": json.dumps({**{k: v for k, v in first.items() if k not in SLIM_ONLY_KEYS}, "rows": rows}),
                                  "url": next((str(i.get("url")) for _, i in got.values() if i.get("url")), "")}
        kept = STORE.wishes_of(first.get("wk")) if first.get("wk") else None
        if kept:
            joined["wishes"], joined["filters_used"] = kept
        out.append(joined)
    return out


def group_title(activity: str | None, day: date) -> str:
    """'<activity>, 07 Mar 2027': the date is added only when the activity's name does not already say it (28 Oct 2026: 'Lisbon activities 7 Mar 2027, 07 Mar 2027')."""
    name = (activity or "Activity").strip()
    said = {f"{day:%d %b %Y}", f"{day.day} {day:%b %Y}", f"{day.day} {day:%B %Y}", f"{day:%d %B %Y}", day.isoformat()}
    return name if any(x.lower() in name.lower() for x in said) else f"{name}, {day:%d %b %Y}"


_PART_NOTE = re.compile(r"^(?P<head>.+?sorted by price \(low to high\): )(?P<read>\d+) of (?P<of>\S+) (?P<tail>hotels, the cheapest first\.)$")


def merge_part_notes(notes: list[str]) -> list[str]:
    """A list passed in parts (RateHawk hotels: 3 parts) says 'read sorted by price: 12 of 256 hotels', '13 of 256', '5 of 256': one note with the sum (28 Oct 2026), and an identical note once."""
    out: list[str] = []
    merged: dict[tuple[str, str, str], int] = {}
    slot: dict[tuple[str, str, str], int] = {}
    for n in notes:
        m = _PART_NOTE.match(n)
        if not m:
            if n not in out:
                out.append(n)
            continue
        key = (m["head"], m["of"], m["tail"])
        merged[key] = merged.get(key, 0) + int(m["read"])
        if key not in slot:
            slot[key] = len(out)
            out.append(n)
    for key, i in slot.items():
        out[i] = f"{key[0]}{merged[key]} of {key[1]} {key[2]}"
    return out


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
    searched: dict[str, dict[Any, int]] = {}
    links: dict[str, dict[str | None, str]] = {}      # one link per leg: a trip's outbound and return pages are both sources
    problems += check_parts(site_results)
    site_results = join_slim_parts(site_results)
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
        search_of = getattr(mod, "search_of", None)
        search = search_of(item_wishes.get("expect") or {}) if search_of else None      # (key, label) of the search this answer is for, when a source is read several times for different things
        rows = mod.convert(expand(item.get("result", "")), item_wishes, (group_for or {}).get(site, getattr(mod, "GROUP", "Options")))
        problems += rows.problems
        notes += rows.extra_notes
        by_price = by_price or rows.sorted_by_price
        seen = reads.setdefault(site, {f"{o.group}|{o.link}|{o.name}|{o.price_total}" for o in offers if o.source == getattr(mod, "SOURCE", site)})
        for o in rows.offers:
            key = f"{o.group}|{o.link}|{o.name}|{o.price_total}"      # the options of one activity share its page link: the name and the price tell them apart; the same car at the same price on the way back is another row
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
        elif search and rows.total is not None:      # one source, several searches (two Bensaude hotels, the two legs of a transfer): each search has its own total and they add up (28 Oct 2026: "18 of 9 read", "29 of 24 read")
            totals = searched.setdefault(site, {})
            totals[search[0]] = max(totals.get(search[0], 0), rows.total or 0)
            read, of = len(seen) or None, sum(totals.values())
        else:
            read, of = len(seen) or None, rows.total or (cur.of if cur else None)
        if item.get("url"):
            links.setdefault(site, {})[search[1] if search else (item_wishes.get("expect") or {}).get("leg")] = item["url"]
        mine = links.get(site) or {}
        link = (next(iter(mine.values())) if len(mine) == 1 else "; ".join(f"{leg}: {url}" if leg else url for leg, url in mine.items())) if mine else (cur.link if cur else None)
        sources[site] = SourceRead(name=src_name, read=read, of=of, link=link, more=rows.more_exist or bool(cur and cur.more))
    return offers, list(sources.values()), problems, by_price, merge_part_notes(notes)



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


MAX_PART_TRIES = 2                      # failed passes of one site's parts before the server says stop (26 Oct 2026: the assistant kept re-running RateHawk in a loop)
PART_FAIL_WINDOW = 45 * 60
_PART_FAILS: dict[str, list[float]] = {}


def note_part_failure(site: str) -> int:
    """Counts this failed pass of `site`'s parts (the last 45 minutes) and returns how many there were."""
    now = time.time()
    tries = [t for t in _PART_FAILS.get(site, []) if now - t < PART_FAIL_WINDOW] + [now]
    _PART_FAILS[site] = tries
    return len(tries)


def checksum_problem(raw: str) -> str | None:
    """Each part ends with `,"crc":"<crc32 of the text before it>"}` (emit.js). None when it matches; else what is wrong."""
    text = raw.strip()
    cut = text.rfind(',"crc":"')
    if cut < 0 or not text.endswith('"}'):
        return "has no checksum (it was cut or rewritten)"
    expected = format(zlib.crc32((text[:cut] + "}").encode("utf-8")), "08x")
    return None if text[cut + 8:-2] == expected else "does not match its checksum (a character was changed while it was passed on)"


def _escape_non_ascii(text: str) -> str:
    """What emit.js does: every character from U+007F up is written as \\uXXXX (one escape per UTF-16 unit, so an emoji is a surrogate pair)."""
    out = []
    for c in text:
        o = ord(c)
        if o < 0x7F:
            out.append(c)
        elif o > 0xFFFF:
            o -= 0x10000
            out.append(f"\\u{0xD800 + (o >> 10):04x}\\u{0xDC00 + (o & 0x3FF):04x}")
        else:
            out.append(f"\\u{o:04x}")
    return "".join(out)


_REPAIRS = (                             # what a model does when it types a part back: writes \\u twice, writes the hex in capitals, turns an escape into the character itself
    lambda t: re.sub(r"\\\\u([0-9a-fA-F]{4})", r"\\u\1", t),
    lambda t: re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: "\\u" + m.group(1).lower(), t),
    _escape_non_ascii,
)


def repaired_part(raw: str) -> str | None:
    """A part that fails its checksum only because of how the escapes were typed back (28 Oct 2026: the assistant wrote \\\\u20ac for \\u20ac). The text is accepted ONLY when one of these
    rewrites gives back the exact text the script made, which the script's own checksum proves; then the repaired text is returned. Information that is gone (a no-break space typed as a plain space) is not guessed."""
    text = raw.strip()
    cut = text.rfind(',"crc":"')
    if cut < 0 or not text.endswith('"}'):
        return None
    given = text[cut + 8:-2]
    body = text[:cut] + "}"
    for mask in range(1, 8):
        candidate = body
        for i, fix in enumerate(_REPAIRS):
            if mask >> i & 1:
                candidate = fix(candidate)
        if format(zlib.crc32(candidate.encode("utf-8")), "08x") == given:
            return candidate[:-1] + ',"crc":"' + given + '"}'
    return None


def part_shape(raw: str) -> str:
    """What a failed part looks like, for the message and the log: its backslashes, doubled escapes and characters above ASCII (no data is repeated)."""
    backslashes = raw.count("\\")
    doubled = len(re.findall(r"\\\\u[0-9a-fA-F]{4}", raw))
    non_ascii = sum(1 for c in raw if ord(c) > 126)
    return f"{backslashes} backslashes, {doubled} doubled \\u escapes, {non_ascii} non-ASCII characters"


def _flat(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def near_sites(site: str, mods: dict[str, Any]) -> list[str]:
    """The recipe keys a display name could mean ('GetYourGuide' -> the find and the activity keys; 'RateHawk Hotels' -> ratehawk_hotels)."""
    flat = _flat(site)
    return sorted(k for k in mods if flat and (flat in _flat(k) or _flat(k) in flat))


def _head_keys(item: dict[str, Any]) -> tuple[str | None, set[str]]:
    try:
        d = json.loads(item.get("result") or "")
    except (TypeError, ValueError):
        return None, set()
    return (str(d.get("run")) if isinstance(d, dict) and d.get("run") else None), (set(d) if isinstance(d, dict) else set())


def result_shapes(items: list[dict[str, Any]]) -> dict[str, set[str]]:
    """The keys of the answers of each run: only the first part of an answer in parts carries the head (url_path, query_text...), the others are found by their run."""
    shapes: dict[str, set[str]] = {}
    for item in items:
        run, keys = _head_keys(item)
        if run:
            shapes.setdefault(run, set()).update(keys)
    return shapes


def key_by_result_shape(item: dict[str, Any], candidates: list[str], mods: dict[str, Any], shapes: dict[str, set[str]]) -> str | None:
    """Of several recipe keys a display name could mean, the one whose RESULT_MARKS (keys only its answers have) are all in this answer; None when no key or more than one fits."""
    run, keys = _head_keys(item)
    keys = keys | shapes.get(run or "", set())
    fits = [k for k in candidates if getattr(mods.get(k), "RESULT_MARKS", None) and set(mods[k].RESULT_MARKS) <= keys]
    return fits[0] if len(fits) == 1 else None


def resolve_site_names(items: list[dict[str, Any]], mods: dict[str, Any], issued: set[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The assistant sometimes names a site by its display name ('GetYourGuide', 'RateHawk'; seen 24 and 26 Oct 2026) and the whole answer was refused. A name that means exactly ONE recipe key
    is read as that key; a name that fits several is read as the one key whose recipe this chat issued for this kind of answer (`issued`); anything else stays unknown and is refused as before."""
    out, fixed = [], {}
    shapes = result_shapes(items)
    for item in items:
        site = str(item.get("site", ""))
        if not site or site in mods:
            out.append(item)
            continue
        near = near_sites(site, mods)
        live = [k for k in near if k in issued]
        pick = near[0] if len(near) == 1 else live[0] if len(live) == 1 else None
        if pick is None and len(near) > 1:
            pick = key_by_result_shape(item, live if len(live) > 1 else near, mods, shapes)      # "Viator" with a list recipe AND a page recipe issued: the rows say which one they are
        if pick:
            fixed[site] = pick
            out.append({**item, "site": pick})
        else:
            out.append(item)
    return out, fixed


def unknown_site(site: str, mods: dict[str, Any]) -> str:
    """The site name is the recipe's own key ('getyourguide_find'): a display name ('GetYourGuide', 'Ratehawk') is refused with the keys it could mean (24-26 Oct 2026: both were sent and the rows were dropped)."""
    near = near_sites(site, mods)
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
            received = str(item.get("result", ""))
            why = checksum_problem(received)
            fixed = repaired_part(received) if why else None
            if fixed:
                item["result"] = fixed          # the script's own checksum proves this is the text it made
                item["repaired"] = True
                log.info("PARTS %s part %s of %s: repaired a typed-back part (%s)", item.get("site"), data.get("part"), data.get("parts"), part_shape(received))
                why = None
            if why:
                log.info("PARTS %s part %s of %s: %s (%s)", item.get("site"), data.get("part"), data.get("parts"), why, part_shape(received))
                bad.append(f"{item.get('site')}: part {data.get('part')} of {data.get('parts')} {why} (the server received {len(received)} characters, {part_shape(received)}): run window.__mytParts[{int(data.get('part', 1)) - 1}] again in the same Chrome tab and pass it exactly as it is, from ONE output; never join an output that was cut ([TRUNCATED]) or retype it")
            key = (str(item.get("site", "")), str(data["run"]))
            runs.setdefault(key, {})[int(data.get("part", 0))] = len(data.get("rows") or [])
            if data.get("rows_read") is not None or key not in meta:      # a slim part after the first carries only its rows: it must not wipe the count part 1 gave
                meta[key] = (int(data["parts"]), int(data.get("rows_read") or 0))
    problems = list(dict.fromkeys(bad))
    for key, got in runs.items():
        parts, rows_read = meta[key]
        missing = [i for i in range(1, parts + 1) if i not in got]
        if missing:
            problems.append(f"{key[0]}: part(s) {', '.join(map(str, missing))} of {parts} are missing: run window.__mytParts[<number minus 1>] in the same Chrome tab (the answer's `more` line) and pass each part unchanged as its own item of site_results")
        elif sum(got.values()) != rows_read:
            problems.append(f"{key[0]}: the parts hold {sum(got.values())} rows but the script read {rows_read}: run the script again and pass every part unchanged")
    failing = {p.split(":", 1)[0] for p in problems}
    for site in {k[0] for k in runs} - failing:
        _PART_FAILS.pop(site, None)         # this site's parts arrived whole: the count starts again
    for site in sorted(failing):
        tries = note_part_failure(site)
        if tries >= MAX_PART_TRIES:
            problems.append(f"{site}: STOP, its parts failed {tries} times. Do not run it again. Put {site} in not_checked with the reason 'could not be read: its parts did not reach the server intact' and call compose_answer again; the answer then says so.")
    return problems


GENERIC_PLACE_WORDS = {"airport", "station", "railway", "terminal", "international", "intl", "city", "center", "centre", "downtown", "the", "of", "de", "da", "di", "and"}


_ALIAS_GROUPS: list[set[str]] | None = None


def alias_groups() -> list[set[str]]:
    """The names one place goes by (myt_mcp/sites/place_aliases.json), read once."""
    global _ALIAS_GROUPS
    if _ALIAS_GROUPS is None:
        try:
            _ALIAS_GROUPS = [set(g) for g in json.loads((Path(__file__).parent / "place_aliases.json").read_text(encoding="utf-8")).get("groups", [])]
        except (OSError, ValueError):
            _ALIAS_GROUPS = []
    return _ALIAS_GROUPS


def place_words(text: str | None) -> set[str]:
    """The distinctive words of a place (no accents, no 'airport', 'station'...), plus every other name of the same place from the alias table."""
    import unicodedata
    plain = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    words = {w for w in re.sub(r"[^a-z0-9]+", " ", plain).split() if w not in GENERIC_PLACE_WORDS}
    for group in alias_groups():
        if words & group:
            words |= group
    return words


def place_matches(expected: str | None, got: str | None) -> bool:
    """Is the place the page searched the place that was asked? Compared by the DISTINCTIVE words (not 'airport', 'station'...): 'Faro Airport' is 'Portugal, Faro Airport', never 'Spain, Malaga Airport'; a place's other names count
    as the same word ('Lisbon Airport' is 'Humberto Delgado Airport (LIS)': place_aliases.json). An empty side is not a reason to refuse."""
    want, have = place_words(expected), place_words(got)
    return not want or not have or bool(want & have)
