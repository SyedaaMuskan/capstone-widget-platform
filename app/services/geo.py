"""IP -> geolocation with a provider fallback chain. Degrade, never fail."""
from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    pass


@dataclass(frozen=True)
class GeoResult:
    provider: str
    country: Optional[str]
    country_code: Optional[str]
    region: Optional[str]
    city: Optional[str]


class GeoProvider(Protocol):
    name: str

    def lookup(self, ip: str) -> GeoResult: ...


class IpApiProvider:
    """Provider A: ip-api.com (free, no key, 45 req/min)."""
    name = "ip-api.com"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, ip: str) -> GeoResult:
        r = httpx.get(f"http://ip-api.com/json/{ip}", params={"fields": "status,message,country,countryCode,regionName,city"}, timeout=self.timeout)
        r.raise_for_status()
        d = r.json()
        if d.get("status") != "success":
            raise ProviderError(d.get("message", "lookup failed"))
        return GeoResult(self.name, d.get("country"), d.get("countryCode"), d.get("regionName"), d.get("city"))


class IpapiCoProvider:
    """Provider B: ipapi.co (free tier, ~1000/day, no card)."""
    name = "ipapi.co"

    def __init__(self, timeout: float):
        self.timeout = timeout

    def lookup(self, ip: str) -> GeoResult:
        r = httpx.get(f"https://ipapi.co/{ip}/json/", timeout=self.timeout, headers={"User-Agent": "flyrank-widget-capstone/1.0"})
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise ProviderError(str(d.get("reason", "lookup failed")))
        return GeoResult(self.name, d.get("country_name"), d.get("country_code"), d.get("region"), d.get("city"))


class MockProvider:
    """Deterministic provider for proofs/tests. `down=True` simulates an outage."""

    def __init__(self, name: str, country: str, code: str, city: str):
        self.name, self._r, self.down = name, (country, code, city), False

    def lookup(self, ip: str) -> GeoResult:
        if self.down:
            raise ProviderError(f"{self.name} is down (simulated)")
        return GeoResult(self.name, self._r[0], self._r[1], "Mock Region", self._r[2])


class GeoChain:
    def __init__(self, providers: list, skip_private: bool = True):
        self.providers, self.skip_private = providers, skip_private

    def enrich(self, ip: Optional[str]) -> Optional[GeoResult]:
        """Try A, then B, ... Returns None if everything fails. Never raises."""
        if not ip:
            return None
        try:
            addr = ipaddress.ip_address(ip)
            if self.skip_private and (addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local):
                return None
        except ValueError:
            if self.skip_private:
                return None
        for provider in self.providers:
            try:
                result = provider.lookup(ip)
                if result:
                    return result
            except Exception as exc:  # any failure -> next provider
                logger.warning("geo provider %s failed: %s", getattr(provider, "name", "?"), exc)
        logger.warning("all geo providers failed; storing submission without geo")
        return None


def build_geo_chain(mode: str, timeout: float) -> GeoChain:
    if mode == "mock":
        return GeoChain([MockProvider("mock-a", "United States", "US", "Austin"),
                         MockProvider("mock-b", "Canada", "CA", "Toronto")], skip_private=False)
    return GeoChain([IpApiProvider(timeout), IpapiCoProvider(timeout)], skip_private=True)
