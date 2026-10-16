"""Builds the outside-system clients once, on first use, from the settings. Tools ask this object
for clients instead of creating them, so connections and caches are shared and tests can inject fakes."""

from __future__ import annotations

from myt_mcp.browser import BrowserSession
from myt_mcp.config import Settings
from myt_mcp.errors import IntegrationError
from myt_mcp.gyg.client import GygClient
from myt_mcp.israir.client import IsrairClient
from myt_mcp.kiwitaxi.client import KiwitaxiClient
from myt_mcp.lounges import aspire as aspire_api
from myt_mcp.myt.client import MYTClient
from myt_mcp.ofran.client import OfranClient
from myt_mcp.ofran.transport import BrowserTransport, HttpTransport
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.sata.client import SataClient
from myt_mcp.trenitalia.client import TrenitaliaClient
from myt_mcp.viator.client import ViatorClient


class Services:
    def __init__(self, settings: Settings, *, myt: MYTClient | None = None, ofran: OfranClient | None = None,
                 trenitalia: TrenitaliaClient | None = None, viator: ViatorClient | None = None,
                 sata: SataClient | None = None, aspire: aspire_api.AspireClient | None = None,
                 gyg: GygClient | None = None, kiwitaxi: KiwitaxiClient | None = None, israir: IsrairClient | None = None):
        self.settings = settings
        self._myt = myt
        self._ofran = ofran
        self._trenitalia = trenitalia
        self._viator = viator
        self._sata = sata
        self._aspire = aspire
        self._gyg = gyg
        self._kiwitaxi = kiwitaxi
        self._israir = israir
        self._browser: BrowserSession | None = None

    def myt(self) -> MYTClient:
        if self._myt is None:
            self._myt = MYTClient(self.settings.myt_api_key, cache_seconds=self.settings.myt_cache_seconds)
        return self._myt

    def browser(self) -> BrowserSession:
        if self._browser is None:
            if not self.settings.browser_cdp_url:
                raise IntegrationError("No automation browser is configured (BROWSER_CDP_URL).")
            self._browser = BrowserSession(self.settings.browser_cdp_url)
        return self._browser

    def ofran(self) -> OfranClient:
        s = self.settings
        if not s.ofran_enabled:
            raise IntegrationError("Ofran price checks are switched off on the server (OFRAN_ENABLED=false). Ask the operator for the car price instead.")
        if self._ofran is None:
            transport = BrowserTransport(self.browser()) if s.ofran_use_browser else HttpTransport(proxy=s.ofran_proxy)
            limiter = SiteLimiter("Ofran", s.scrape_min_interval_seconds, s.scrape_max_per_hour)
            self._ofran = OfranClient(transport, limiter=limiter, search_cache_minutes=s.scrape_cache_minutes)
        return self._ofran

    def trenitalia(self) -> TrenitaliaClient:
        s = self.settings
        if not s.trenitalia_enabled:
            raise IntegrationError("Trenitalia checks are switched off on the server (TRENITALIA_ENABLED=false). Ask the operator for the train price instead.")
        if self._trenitalia is None:
            limiter = SiteLimiter("Trenitalia", max(s.scrape_min_interval_seconds, 3.0), s.scrape_max_per_hour)
            self._trenitalia = TrenitaliaClient(limiter=limiter, search_cache_minutes=s.scrape_cache_minutes)
        return self._trenitalia

    def viator(self) -> ViatorClient:
        s = self.settings
        if not s.viator_enabled:
            raise IntegrationError("Viator checks are switched off on the server (VIATOR_ENABLED=false). Use GetYourGuide or ask the operator.")
        if self._viator is None:
            limiter = SiteLimiter("Viator", max(s.scrape_min_interval_seconds, 15.0), min(s.scrape_max_per_hour, 20))   # Viator flagged our IP once (2026-10-15): slower and fewer
            self._viator = ViatorClient(self.browser(), limiter=limiter, cache_minutes=max(s.scrape_cache_minutes, 30.0))
        return self._viator

    def sata(self) -> SataClient:
        s = self.settings
        if not s.sata_enabled:
            raise IntegrationError("SATA fare checks are switched off on the server (SATA_ENABLED=false). Ask the operator for the fare.")
        if self._sata is None:
            limiter = SiteLimiter("SATA", s.scrape_min_interval_seconds, s.scrape_max_per_hour)
            self._sata = SataClient(self.browser(), limiter=limiter, cache_minutes=s.scrape_cache_minutes)
        return self._sata

    def aspire(self) -> aspire_api.AspireClient:
        s = self.settings
        if not s.aspire_enabled:
            raise IntegrationError("Aspire lounge checks are switched off on the server (ASPIRE_ENABLED=false). Ask the operator for the lounge price.")
        if self._aspire is None:
            transport = aspire_api.BrowserTransport(self.browser()) if s.browser_cdp_url else aspire_api.HttpTransport()
            limiter = SiteLimiter("Aspire", max(s.scrape_min_interval_seconds / 2, 1.0), s.scrape_max_per_hour)
            self._aspire = aspire_api.AspireClient(transport, limiter=limiter, cache_minutes=s.scrape_cache_minutes)
        return self._aspire

    def gyg(self) -> GygClient:
        s = self.settings
        if not s.gyg_enabled:
            raise IntegrationError("GetYourGuide detail checks are switched off on the server (GYG_ENABLED=false). Use the GetYourGuide connector's cards.")
        if self._gyg is None:
            limiter = SiteLimiter("GetYourGuide", s.scrape_min_interval_seconds, s.scrape_max_per_hour)
            self._gyg = GygClient(self.browser(), limiter=limiter, cache_minutes=s.scrape_cache_minutes, http_first=True)
        return self._gyg

    def kiwitaxi(self) -> KiwitaxiClient:
        s = self.settings
        if not s.kiwitaxi_enabled:
            raise IntegrationError("Kiwitaxi transfer checks are switched off on the server (KIWITAXI_ENABLED=false). Ask the operator for the transfer price.")
        if self._kiwitaxi is None:
            limiter = SiteLimiter("Kiwitaxi", max(s.scrape_min_interval_seconds, 5.0), min(s.scrape_max_per_hour, 30))
            self._kiwitaxi = KiwitaxiClient(limiter=limiter, cache_minutes=s.scrape_cache_minutes)
        return self._kiwitaxi

    def israir(self) -> IsrairClient:
        s = self.settings
        if not s.israir_enabled:
            raise IntegrationError("Israir fare checks are switched off on the server (ISRAIR_ENABLED=false). Ask the operator for the flight price.")
        if self._israir is None:
            limiter = SiteLimiter("Israir", max(s.scrape_min_interval_seconds, 5.0), min(s.scrape_max_per_hour, 30))
            self._israir = IsrairClient(limiter=limiter, cache_minutes=s.scrape_cache_minutes)
        return self._israir

    def check_trip(self, trip_id: int | None) -> None:
        """While testing on the client's account, only the trips in ALLOWED_TRIP_IDS may be touched.
        Called before any request is sent to MYT."""
        allowed = self.settings.allowed_trip_ids
        if allowed and trip_id not in allowed:
            raise IntegrationError(f"Trip {trip_id} is outside the allowed test trips {sorted(allowed)}; nothing was requested from MYT. "
                                   "If {trip_id} is the trip NUMBER shown in MYT (what operators call \"trip 906\"), it is not the trip_id: "
                                   "call find_trip with that number first and use the trip_id it returns.".replace("{trip_id}", str(trip_id)))

    async def aclose(self) -> None:
        for client in (self._myt, self._ofran, self._trenitalia, self._viator, self._sata, self._aspire, self._gyg, self._kiwitaxi, self._israir, self._browser):
            if client is not None:
                await client.aclose()
