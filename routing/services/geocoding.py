"""
Nominatim geocoding for the user-supplied start/finish strings.

Counted *separately* from the routing-API call budget — the spec restricts
calls to the "free map/routing API", not the geocoder. We still keep it to
**at most one call per location**, and the FE can skip it entirely by passing
{lat, lon} directly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

log = logging.getLogger(__name__)


class GeocodingError(Exception):
    pass


@dataclass(frozen=True)
class GeocodeResult:
    label: str
    lat: float
    lon: float


def geocode(query: str) -> GeocodeResult:
    """Resolve a US-bounded address string to (label, lat, lon)."""
    q = (query or "").strip()
    if not q:
        raise GeocodingError("Empty query.")

    url = f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/search"
    params = {
        "q": q,
        "format": "jsonv2",
        "limit": 1,
        "addressdetails": 0,
        "countrycodes": "us",
    }
    headers = {
        "User-Agent": settings.HTTP_USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en",
    }
    try:
        r = requests.get(
            url, params=params, headers=headers,
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        rows = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Nominatim call failed for %r: %s", q, exc)
        raise GeocodingError(f"Nominatim call failed: {exc}") from exc

    if not rows:
        raise GeocodingError(f"No location found for {q!r}.")

    row = rows[0]
    try:
        return GeocodeResult(
            label=row.get("display_name") or q,
            lat=float(row["lat"]),
            lon=float(row["lon"]),
        )
    except (KeyError, ValueError) as exc:
        raise GeocodingError(f"Bad Nominatim response: {exc}") from exc
