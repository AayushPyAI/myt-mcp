"""How requests reach ofran.co.il. Two transports with the same interface:

* HttpTransport: direct HTTPS with one pooled client, optionally through a proxy. For a server
  running outside India (Ofran answers 403 to Indian IPs).
* BrowserTransport: runs fetch() inside an ofran.co.il tab of the shared automation browser
  (myt_mcp.browser), so requests use that browser's network (e.g. a VPN extension).

Both turn every failure into an OfranError with a message the operator can act on.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import httpx

from myt_mcp.browser import BrowserSession
from myt_mcp.errors import IntegrationError

log = logging.getLogger("myt_mcp.ofran")
BASE_URL = "https://ofran.co.il"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
BLOCKED = "Ofran refused this connection (403 Access Denied). It blocks Indian IPs: run the server outside India, set OFRAN_PROXY, or set OFRAN_USE_BROWSER=true with a VPN on in the automation browser."


class OfranError(IntegrationError):
    pass


class Transport(Protocol):
    async def request(self, method: str, path: str, body: dict | None = None) -> Any: ...
    async def aclose(self) -> None: ...


CHALLENGE_MARKERS = ("captcha", "just a moment", "verify you are human", "cf-challenge", "challenge-platform")


def parse_response(status: int, text: str, path: str) -> Any:
    """Shared status and body checks for both transports."""
    head = text[:2000].lower()
    if any(m in head for m in CHALLENGE_MARKERS) and not head.lstrip().startswith(("{", "[")):
        raise OfranError("Ofran asked for a human check (captcha). Stopping so the account isn't flagged; "
                         "try again later, or open ofran.co.il in the browser and complete the check.")
    if status == 403 or "Access Denied" in text[:500]:
        raise OfranError(BLOCKED)
    if status == 429:
        raise OfranError("Ofran is limiting requests right now (429). Wait a minute and try again.")
    if status >= 500:
        raise OfranError(f"Ofran's site is having problems ({status}). Try again later.")
    if status >= 400:
        raise OfranError(f"Ofran {path} returned {status}; the site may have changed.")
    try:
        return json.loads(text)
    except ValueError:
        raise OfranError(f"Ofran {path} returned a page instead of data; the site may have changed or blocked the request.") from None


class HttpTransport:
    def __init__(self, proxy: str | None = None, timeout: float = 60.0, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            base_url=BASE_URL, proxy=proxy, timeout=timeout,
            headers={"User-Agent": UA, "Accept": "application/json"},
        )

    async def request(self, method: str, path: str, body: dict | None = None) -> Any:
        try:
            resp = await self._client.request(method, path, json=body)
        except httpx.TimeoutException:
            raise OfranError("Ofran did not answer in time. Try again in a minute.") from None
        except httpx.ProxyError:
            raise OfranError("The proxy in OFRAN_PROXY refused the connection; check its address and login.") from None
        except httpx.HTTPError as e:
            raise OfranError(f"Could not reach Ofran ({type(e).__name__}). Check the server's internet connection.") from None
        return parse_response(resp.status_code, resp.text, path)

    async def aclose(self) -> None:
        await self._client.aclose()


class BrowserTransport:
    """Sends Ofran requests from an ofran.co.il tab of the shared automation browser, so they use
    that browser's network (e.g. a VPN extension). For running from a country Ofran blocks."""

    def __init__(self, session: BrowserSession):
        self._session = session

    async def request(self, method: str, path: str, body: dict | None = None) -> Any:
        result = await self._session.fetch(BASE_URL, f"{BASE_URL}/en", method, path, body)
        return parse_response(result["status"], result["text"], path)

    async def aclose(self) -> None:
        """The shared session is closed by its owner."""
