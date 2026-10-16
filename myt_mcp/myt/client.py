"""Client for the documented ManageYourTrip public API.

Docs: https://www.manageyourtrip.com/documentation#/ (endpoint list in
/_client/assets/html/documentation/main/main.controller.js). Auth is a per-tenant GUID.
The public API reads trips, itineraries, participants and the selected quotation; it cannot
write quotations (see quote_api.py).
"""

from __future__ import annotations

from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError

BASE_URL = "https://www.manageyourtrip.com/api"


class MYTError(IntegrationError):
    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


class MYTClient:
    def __init__(self, api_key: str, *, cache_seconds: float = 60.0, timeout: float = 45.0,
                 http: httpx.AsyncClient | None = None):
        if not api_key:
            raise MYTError("MYT is not connected yet: MYT_API_KEY is not configured on the server.")
        # The key goes in the query string as well as the header: MYT's Web API routes on action
        # parameters and `key` is one of them; without it most actions return 404.
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-api-key": api_key, "Accept": "application/json"},
            params={"key": api_key},
            timeout=timeout,
        )
        # GetTrip/v3 can exceed 1 MB; get_trip and get_quotation on the same trip share one download.
        self._v3_cache: TTLCache[dict[str, Any]] = TTLCache(cache_seconds, max_entries=16, track_fetch_time=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            resp = await self._http.get(path, params=params)
        except httpx.TimeoutException:
            raise MYTError("MYT did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise MYTError(f"Could not reach MYT ({type(e).__name__}). Check the server's internet connection.") from None
        if resp.status_code in (401, 403):
            raise MYTError(f"MYT refused the request ({resp.status_code}): {resp.text[:150]}", resp.status_code)
        if resp.status_code == 404:
            raise MYTError(f"MYT has no {path} for these parameters (404).", 404)
        if resp.status_code >= 500:
            raise MYTError(f"MYT is having problems right now ({resp.status_code}). Try again later.", resp.status_code)
        if resp.status_code >= 400:
            raise MYTError(f"MYT {path} returned {resp.status_code}: {resp.text[:150]}", resp.status_code)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            raise MYTError(f"MYT {path} returned something that is not JSON; its API may have changed.") from None

    # --- trips -------------------------------------------------------------

    async def get_trips(self, status_id: int | None = None, from_date: str | None = None,
                        country_id: int | None = None, name: str | None = None, skip: int | None = None) -> list[dict[str, Any]]:
        data = await self._get("/trip/GetTrips", statusId=status_id, fromDate=from_date, countryId=country_id, name=name, skip=skip)
        return data or []

    async def get_trip_by_number(self, trip_number: str | int) -> dict[str, Any]:
        try:
            data = await self._get("/trip/GetTripByTripNumber", tripNumber=trip_number)
        except MYTError as e:
            if e.status == 400 and "not found" in str(e).lower():
                raise MYTError(f"MYT has no trip number {trip_number}.", 400) from None
            raise
        if not data:
            raise MYTError(f"MYT has no trip number {trip_number}.")
        return data

    async def get_trip_v3(self, trip_id: int) -> dict[str, Any]:
        async def load() -> dict[str, Any]:
            data = await self._get("/trip/GetTrip/v3", tripId=trip_id)
            if not isinstance(data, dict):
                raise MYTError(f"MYT returned no data for trip {trip_id}.")
            return data

        return await self._v3_cache.get_or_load(trip_id, load)

    async def get_participants(self, trip_id: int) -> Any:
        return await self._get("/participants/GetTripParticipantList", tripId=trip_id)
