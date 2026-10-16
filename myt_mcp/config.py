"""All server settings, read once from the environment and validated at start-up."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(Exception):
    """A setting is missing or malformed. Raised at start-up, before the server accepts requests."""


def _csv(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    myt_api_key: str = ""
    mcp_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8000
    allowed_hosts: tuple[str, ...] = ("127.0.0.1:*", "localhost:*")
    # Empty = every trip allowed. While testing on the client's account: their test trip only.
    allowed_trip_ids: frozenset[int] = frozenset()
    ofran_proxy: str | None = None
    # Chrome started with --remote-debugging-port, shared by integrations that need a real browser.
    browser_cdp_url: str | None = None
    # Send Ofran requests through that browser (its VPN) instead of directly. Local testing from India.
    ofran_use_browser: bool = False
    # Scraping safety (sites without an official API): kill switch, pacing, hourly cap, repeat cache.
    ofran_enabled: bool = True
    trenitalia_enabled: bool = True
    viator_enabled: bool = True
    aspire_enabled: bool = True
    gyg_enabled: bool = True
    kiwitaxi_enabled: bool = True
    israir_enabled: bool = True
    sata_enabled: bool = True
    scrape_min_interval_seconds: float = 5.0
    scrape_max_per_hour: int = 60
    scrape_cache_minutes: float = 10.0
    myt_cache_seconds: float = 60.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        try:
            trip_ids = frozenset(int(x) for x in _csv(env.get("ALLOWED_TRIP_IDS", "")))
        except ValueError:
            raise ConfigError("ALLOWED_TRIP_IDS must be comma-separated trip ids, e.g. 276310") from None
        try:
            port = int(env.get("PORT", "8000"))
            min_interval = float(env.get("SCRAPE_MIN_INTERVAL_SECONDS", "5"))
            max_per_hour = int(env.get("SCRAPE_MAX_PER_HOUR", "60"))
            cache_minutes = float(env.get("SCRAPE_CACHE_MINUTES", "10"))
        except ValueError:
            raise ConfigError("PORT, SCRAPE_MIN_INTERVAL_SECONDS, SCRAPE_MAX_PER_HOUR and SCRAPE_CACHE_MINUTES must be numbers") from None
        return cls(
            myt_api_key=env.get("MYT_API_KEY", "").strip(),
            mcp_secret=env.get("MCP_SECRET", "").strip(),
            host=env.get("HOST", "127.0.0.1"),
            port=port,
            allowed_hosts=_csv(env.get("ALLOWED_HOSTS", "127.0.0.1:*,localhost:*")),
            allowed_trip_ids=trip_ids,
            ofran_proxy=env.get("OFRAN_PROXY") or None,
            # OFRAN_BROWSER_CDP is the older name for BROWSER_CDP_URL + OFRAN_USE_BROWSER=true
            browser_cdp_url=env.get("BROWSER_CDP_URL") or env.get("OFRAN_BROWSER_CDP") or None,
            ofran_use_browser=env.get("OFRAN_USE_BROWSER", "").lower() in ("1", "true", "yes") or bool(env.get("OFRAN_BROWSER_CDP")),
            ofran_enabled=env.get("OFRAN_ENABLED", "true").lower() not in ("0", "false", "no"),
            trenitalia_enabled=env.get("TRENITALIA_ENABLED", "true").lower() not in ("0", "false", "no"),
            viator_enabled=env.get("VIATOR_ENABLED", "true").lower() not in ("0", "false", "no"),
            aspire_enabled=env.get("ASPIRE_ENABLED", "true").lower() not in ("0", "false", "no"),
            gyg_enabled=env.get("GYG_ENABLED", "true").lower() not in ("0", "false", "no"),
            kiwitaxi_enabled=env.get("KIWITAXI_ENABLED", "true").lower() not in ("0", "false", "no"),
            israir_enabled=env.get("ISRAIR_ENABLED", "true").lower() not in ("0", "false", "no"),
            sata_enabled=env.get("SATA_ENABLED", "true").lower() not in ("0", "false", "no"),
            scrape_min_interval_seconds=min_interval,
            scrape_max_per_hour=max_per_hour,
            scrape_cache_minutes=cache_minutes,
        )

    def __post_init__(self) -> None:
        if self.ofran_use_browser and not self.browser_cdp_url:
            raise ConfigError("OFRAN_USE_BROWSER=true needs BROWSER_CDP_URL (e.g. http://127.0.0.1:9333)")
        if self.scrape_min_interval_seconds < 1 or not 1 <= self.scrape_max_per_hour <= 300:
            raise ConfigError("SCRAPE_MIN_INTERVAL_SECONDS must be at least 1 and SCRAPE_MAX_PER_HOUR between 1 and 300")

    def require_secret(self) -> None:
        if len(self.mcp_secret) < 24:
            raise ConfigError("MCP_SECRET must be a random string of at least 24 characters")
