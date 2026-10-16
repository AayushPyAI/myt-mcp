"""One shared Playwright connection to a Chrome started with --remote-debugging-port.

Integrations that need a real browser use it: Ofran (when the server's own IP is blocked) and the
logged-in hotel sites (RateHawk, Arbitrip). The connection is opened once and reused; each site
keeps one tab, reused across calls; calls on the same site take turns.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx

from myt_mcp.errors import IntegrationError

log = logging.getLogger("myt_mcp.browser")
T = TypeVar("T")

FETCH_JS = """async ([method, url, body, headers]) => {
    const r = await fetch(url, {method, credentials: 'same-origin',
        headers: Object.assign({'Accept': 'application/json'}, body ? {'Content-Type': 'application/json'} : {}, headers || {}),
        body: body ? JSON.stringify(body) : undefined});
    return {status: r.status, url: r.url, text: await r.text()};
}"""


class BrowserError(IntegrationError):
    pass


class BrowserSession:
    def __init__(self, cdp_url: str, timeout: float = 60.0):
        self.cdp_url = cdp_url
        self.timeout = timeout
        self._pw = None
        self._browser = None
        self._pages: dict[str, Any] = {}
        self._connect_lock = asyncio.Lock()
        self._site_locks: dict[str, asyncio.Lock] = {}

    async def _connect(self):
        async with self._connect_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                raise BrowserError("Playwright is not installed on the server (pip install playwright).") from None
            await self._reset()
            await self._ensure_window()
            try:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.connect_over_cdp(self.cdp_url, timeout=self.timeout * 1000)
            except Exception:
                log.warning("could not attach to %s", self.cdp_url, exc_info=True)
                await self._reset()
                raise BrowserError(f"No browser is listening at {self.cdp_url}. Open the automation Chrome window and try again.") from None
            return self._browser

    async def _ensure_window(self) -> None:
        """Chrome keeps running on macOS after its last window is closed, and Playwright can't attach
        to it in that state. Open a blank tab first if there is no page."""
        try:
            async with httpx.AsyncClient(base_url=self.cdp_url, timeout=5) as client:
                targets = (await client.get("/json/list")).json()
                if not any(t.get("type") == "page" for t in targets):
                    await client.put("/json/new?about:blank")
        except (httpx.HTTPError, ValueError):
            pass  # connect_over_cdp below reports the problem

    async def _reset(self) -> None:
        """Drop the Playwright session. The Chrome window stays open (we only attached to it)."""
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                log.debug("ignoring error while stopping playwright", exc_info=True)
        self._pw = self._browser = None
        self._pages.clear()

    async def page(self, origin: str, start_url: str):
        """The tab for `origin`: reused if open, else an existing tab on that site, else a new one."""
        page = self._pages.get(origin)
        if page is not None and not page.is_closed():
            return page
        browser = await self._connect()
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = next((p for p in context.pages if p.url.startswith(origin)), None)
        if page is None:
            page = await context.new_page()
            try:
                await page.goto(start_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
            except Exception:
                raise BrowserError(f"The automation browser could not open {origin}.") from None
        self._pages[origin] = page
        return page

    async def _discard(self, origin: str, page: Any) -> None:
        """Drop a tab that failed. The last tab is blanked instead of closed (Chrome keeps one window)."""
        self._pages.pop(origin, None)
        try:
            if len(page.context.pages) > 1:
                await page.close()
            else:
                await page.goto("about:blank")
        except Exception:
            log.debug("could not discard the failed tab", exc_info=True)

    async def run(self, origin: str, start_url: str, action: Callable[[Any], Awaitable[T]]) -> T:
        """Run `action(page)` on the site's tab, one call per site at a time. If the tab or the
        browser went away mid-call, reconnect once and retry."""
        lock = self._site_locks.setdefault(origin, asyncio.Lock())
        async with lock:
            for attempt in (1, 2):
                page = await self.page(origin, start_url)
                try:
                    return await asyncio.wait_for(action(page), self.timeout)
                except IntegrationError:
                    raise
                except asyncio.TimeoutError:
                    raise BrowserError(f"{origin} did not answer in time. Try again in a minute.") from None
                except Exception as e:
                    reason = (str(e).splitlines() or [type(e).__name__])[0][:140]
                    if attempt == 2:
                        log.exception("browser action failed on %s", origin)
                        raise BrowserError(f"The {origin} tab stopped responding ({reason}). Check the automation Chrome window and try again.") from None
                    await self._discard(origin, page)   # retry on a fresh tab, not the one that just failed
                    if self._browser is None or not self._browser.is_connected():
                        await self._reset()
        raise AssertionError("unreachable")

    async def fetch(self, origin: str, start_url: str, method: str, url: str,
                    body: dict | None = None, headers: dict | None = None) -> dict[str, Any]:
        """fetch() from inside the site's tab, so the request carries that tab's cookies and network.
        Returns {"status", "url", "text"}."""
        async def action(page: Any) -> dict[str, Any]:
            try:
                return await page.evaluate(FETCH_JS, [method, url, body, headers])
            except Exception as e:
                if "Failed to fetch" in str(e):   # the page's own request was refused or the network dropped
                    raise BrowserError(f"The request to {origin} failed in the browser. The site refused it (for example an input "
                                       "out of range) or the connection dropped. Try other inputs or try again.") from None
                raise

        return await self.run(origin, start_url, action)

    async def aclose(self) -> None:
        await self._reset()
