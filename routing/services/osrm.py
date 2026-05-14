"""
OSRM client. One function, one HTTP call per planning request — which is
exactly the budget the assessment asks for.

OSRM gives us back distance, duration, and a polyline geometry, which is
everything downstream needs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import requests
from django.conf import settings

log = logging.getLogger(__name__)

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    """Raised when the upstream router fails or returns no usable route."""


@dataclass(frozen=True)
class Route:
    coords: list[tuple[float, float]]   # [(lat, lon), …]
    distance_miles: float
    duration_seconds: float


def route(
    start: tuple[float, float],
    end: tuple[float, float],
) -> Route:
    """Make a single OSRM /route request for start → end.

    ``start`` and ``end`` are (lat, lon) tuples.
    """
    # OSRM expects lon,lat in the URL.
    coords_str = f"{start[1]},{start[0]};{end[1]},{end[0]}"
    url = f"{settings.OSRM_BASE_URL.rstrip('/')}/route/v1/driving/{coords_str}"
    params = {
        "overview": "full",
        "geometries": "geojson",  # easier than decoding polyline6
        "alternatives": "false",
        "steps": "false",
    }
    headers = {"User-Agent": settings.HTTP_USER_AGENT, "Accept": "application/json"}

    try:
        r = requests.get(
            url, params=params, headers=headers,
            timeout=settings.HTTP_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("OSRM call failed: %s", exc)
        raise RoutingError(f"OSRM call failed: {exc}") from exc

    if body.get("code") != "Ok" or not body.get("routes"):
        raise RoutingError(f"OSRM returned no route (code={body.get('code')!r}).")

    route_obj = body["routes"][0]
    geometry = route_obj.get("geometry") or {}
    raw_coords = geometry.get("coordinates") or []
    if not raw_coords:
        raise RoutingError("OSRM returned an empty geometry.")

    # GeoJSON: [lon, lat]. Convert to (lat, lon).
    coords = [(c[1], c[0]) for c in raw_coords]

    return Route(
        coords=coords,
        distance_miles=route_obj["distance"] / METERS_PER_MILE,
        duration_seconds=route_obj["duration"],
    )
