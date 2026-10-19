"""Selected Places mini-site webhook: generate/refresh the customer trip link after a quote exists.

POST https://minisite.selectedplaces.co.il/site-link-webhook.php
Body: auth_code, trip_id, optional version. The endpoint syncs the trip, builds the FillFaster form,
forwards details to Salesforce and can send notification emails — so callers must only fire it after
the operator says the quote is ready.
"""

from __future__ import annotations

from typing import Any

import httpx

from myt_mcp.errors import IntegrationError

DEFAULT_URL = "https://minisite.selectedplaces.co.il/site-link-webhook.php"


class MinisiteError(IntegrationError):
    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


class MinisiteClient:
    def __init__(self, auth_code: str, *, url: str = DEFAULT_URL, timeout: float = 90.0,
                 http: httpx.AsyncClient | None = None):
        self._auth_code = (auth_code or "").strip()
        self._url = (url or DEFAULT_URL).strip() or DEFAULT_URL
        self._http = http or httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"})
        self._owns_http = http is None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def require_auth(self) -> None:
        if not self._auth_code:
            raise MinisiteError("The mini-site webhook is not connected: MINISITE_AUTH_CODE is not set on the server.")

    def payload(self, trip_id: int | str, version: str | int | None = None) -> dict[str, str]:
        body = {"auth_code": self._auth_code, "trip_id": str(trip_id)}
        if version is not None and str(version).strip() != "":
            body["version"] = str(version).strip()
        return body

    async def generate_trip_link(self, trip_id: int | str, version: str | int | None = None) -> dict[str, Any]:
        """POST the webhook and return its JSON (status, message, trip_url)."""
        self.require_auth()
        try:
            resp = await self._http.post(self._url, json=self.payload(trip_id, version),
                                         headers={"Content-Type": "application/json"})
        except httpx.TimeoutException:
            raise MinisiteError("The mini-site webhook did not answer in time. The quote was not changed. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise MinisiteError(f"Could not reach the mini-site webhook ({type(e).__name__}). Nothing was confirmed sent.") from None
        data = _json_body(resp)
        if resp.status_code == 401 or (isinstance(data, dict) and "unauthorized" in str(data.get("message", "")).lower()):
            raise MinisiteError("The mini-site webhook refused the request (invalid or missing auth code). Check MINISITE_AUTH_CODE.", 401)
        if resp.status_code == 400 or (isinstance(data, dict) and data.get("message") == "Please add trip id"):
            raise MinisiteError("The mini-site webhook needs a trip_id.", 400)
        if resp.status_code == 405:
            raise MinisiteError("The mini-site webhook only accepts POST.", 405)
        if resp.status_code == 502 or (isinstance(data, dict) and "fetching data from the API" in str(data.get("message", "")).lower()):
            raise MinisiteError("The mini-site webhook could not fetch this trip from ManageYourTrip. Check the trip_id and that the quote exists.", 502)
        if resp.status_code >= 400:
            message = data.get("message") if isinstance(data, dict) else None
            raise MinisiteError(f"The mini-site webhook rejected the request ({resp.status_code}): {message or resp.text[:200]}", resp.status_code)
        if not isinstance(data, dict):
            raise MinisiteError("The mini-site webhook returned something that is not JSON; it may have changed.")
        if str(data.get("status", "")).lower() == "error":
            raise MinisiteError(data.get("message") or "The mini-site webhook reported an error.")
        return data


def _json_body(resp: httpx.Response) -> Any:
    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError:
        return None
