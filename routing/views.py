"""
The whole API surface lives in one view: POST /api/route/.

  Inputs:  start + finish (each a {query} string or {lat, lon} pair)
  Outputs: route geometry (GeoJSON LineString), fuel stops, total fuel cost.

External calls per request, in order:
  - geocode(start)        — Nominatim       (skipped if {lat, lon} supplied)
  - geocode(finish)       — Nominatim       (skipped if {lat, lon} supplied)
  - route(start, finish)  — OSRM            ★ the single routing-API call ★
"""
from __future__ import annotations

import logging
import time

import requests
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from .serializers import RouteRequestSerializer
from .services.geocoding import GeocodingError, geocode
from .services.geometry import index_polyline
from .services.osrm import RoutingError, route
from .services.planner import PlanningError, plan_fuel
from .services.stations import get_index

log = logging.getLogger(__name__)


def _resolve(loc: dict) -> dict:
    """Turn a validated location dict into {label, lat, lon}, geocoding if needed."""
    if "lat" in loc and "lon" in loc and not loc.get("query"):
        return {
            "label": loc.get("label") or f"{loc['lat']:.5f}, {loc['lon']:.5f}",
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
        }
    q = loc.get("query") or loc.get("label") or ""
    result = geocode(q)
    return {
        "label": loc.get("label") or result.label,
        "lat": result.lat,
        "lon": result.lon,
    }


@api_view(["POST"])
@throttle_classes([AnonRateThrottle])
def plan_route(request):
    t0 = time.perf_counter()
    serializer = RouteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # 1) Resolve start + finish to coordinates.
    try:
        start = _resolve(data["start"])
        finish = _resolve(data["finish"])
    except GeocodingError as exc:
        return Response(
            {"error": "geocoding_failed", "detail": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # 2) Single OSRM call.
    try:
        r = route((start["lat"], start["lon"]), (finish["lat"], finish["lon"]))
    except RoutingError as exc:
        return Response(
            {"error": "routing_failed", "detail": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    line = index_polyline(r.coords)

    # 3) Pull stations along the route — purely local, no network.
    index = get_index()
    candidates = index.along_route(line)

    # 4) Plan the cheapest-reachable fuel stops.
    options = data.get("options") or {}
    try:
        plan = plan_fuel(
            line, candidates,
            refuel_strategy=options.get("refuel_strategy") or "look_ahead",
            starting_tank=options.get("starting_tank") or "full_free",
        )
    except PlanningError as exc:
        return Response(
            {"error": "no_feasible_plan", "detail": str(exc)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000
    log.info(
        "Planned %s mi · %s stops · $%.2f · %.0f ms",
        f"{r.distance_miles:.0f}",
        len(plan.stops),
        plan.total_fuel_cost_usd,
        elapsed_ms,
    )

    return Response({
        "inputs": {"start": start, "finish": finish},
        "route": {
            "distance_miles": round(r.distance_miles, 2),
            "duration_seconds": round(r.duration_seconds, 1),
            # GeoJSON LineString: [[lon, lat], …]
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in r.coords],
            },
        },
        "fuel": plan.as_dict(),
        "meta": {
            "vehicle_range_miles": settings.VEHICLE_RANGE_MILES,
            "vehicle_mpg": settings.VEHICLE_MPG,
            "station_corridor_miles": settings.STATION_CORRIDOR_MILES,
            "stations_considered": len(candidates),
            "elapsed_ms": round(elapsed_ms, 1),
        },
    }, status=status.HTTP_200_OK)


@api_view(["GET"])
@throttle_classes([AnonRateThrottle])
def geocode_search(request):
    """Nominatim address-autocomplete proxy.

    Lives on the server (not in the browser) for three reasons: keeps the
    user's IP out of OSM's logs, gives us a single polite User-Agent, and
    makes it trivial to add caching / rate-limiting later.
    """
    q = (request.GET.get("q") or "").strip()
    if not q or len(q) < 3:
        return Response([])
    url = f"{settings.NOMINATIM_BASE_URL.rstrip('/')}/search"
    params = {
        "q": q,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": 5,
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
        log.warning("Geocode search failed: %s", exc)
        return Response(
            {"error": "geocoding_failed", "detail": str(exc)},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response([
        {
            "label": row.get("display_name"),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "type": row.get("type"),
            "class": row.get("class"),
        }
        for row in rows if "lat" in row and "lon" in row
    ])
