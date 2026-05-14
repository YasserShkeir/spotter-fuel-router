"""
Fuel-station index.

The CSV has ~8k stations. At startup we load the precomputed JSON
(``fuel_stations.json``) — produced by ``precompute_stations.py`` — and build
a coarse lat/lon grid index. Queries against a route polyline first bbox-prune
to the relevant grid cells (handful of hundreds of stations) and then do
exact point→polyline projection only on those candidates.

End-to-end cost on a typical cross-country route: low single-digit milliseconds.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .geometry import IndexedPolyline, project_onto

log = logging.getLogger(__name__)

_GRID_DEG = 0.5  # ~35 mi cells at mid-latitudes — small enough for fast prune


@dataclass(frozen=True)
class Station:
    id: int
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lon: float

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "address": self.address,
            "city": self.city, "state": self.state, "price": self.price,
            "lat": self.lat, "lon": self.lon,
        }


@dataclass(frozen=True)
class RouteStation:
    """A station projected onto a specific route polyline."""

    station: Station
    miles_along: float
    perp_miles: float


class StationIndex:
    def __init__(self, stations: list[Station]) -> None:
        self.stations = stations
        # Bucket stations into a coarse lat/lon grid for cheap bbox queries.
        self.grid: dict[tuple[int, int], list[Station]] = {}
        for s in stations:
            self.grid.setdefault(self._cell(s.lat, s.lon), []).append(s)

    @staticmethod
    def _cell(lat: float, lon: float) -> tuple[int, int]:
        return int(lat // _GRID_DEG), int(lon // _GRID_DEG)

    def _bbox_candidates(self, line: IndexedPolyline, pad_miles: float) -> list[Station]:
        """Return stations whose cell touches the polyline's bbox + padding."""
        if not line.coords:
            return []
        lats = [c[0] for c in line.coords]
        lons = [c[1] for c in line.coords]
        # Convert pad miles to degrees. 1° lat ≈ 69 mi; 1° lon at lat 49 (≈top
        # of US lower-48) ≈ 45 mi, so /45 is a safe upper bound for the
        # northernmost stations and yields no false negatives.
        pad_lat = pad_miles / 69.0
        pad_lon = pad_miles / 45.0
        min_lat, max_lat = min(lats) - pad_lat, max(lats) + pad_lat
        min_lon, max_lon = min(lons) - pad_lon, max(lons) + pad_lon

        lo_i, hi_i = int(min_lat // _GRID_DEG), int(max_lat // _GRID_DEG)
        lo_j, hi_j = int(min_lon // _GRID_DEG), int(max_lon // _GRID_DEG)

        out: list[Station] = []
        for i in range(lo_i, hi_i + 1):
            for j in range(lo_j, hi_j + 1):
                out.extend(self.grid.get((i, j), ()))
        return out

    def along_route(
        self, line: IndexedPolyline, corridor_miles: float | None = None,
    ) -> list[RouteStation]:
        """Return stations within ``corridor_miles`` of the route, sorted by
        miles-along-route. Two-pass: cheap bbox prune, then exact projection.
        """
        corridor = corridor_miles or settings.STATION_CORRIDOR_MILES
        candidates = self._bbox_candidates(line, pad_miles=corridor)

        out: list[RouteStation] = []
        for s in candidates:
            proj = project_onto(line, s.lat, s.lon)
            if proj.perp_miles <= corridor:
                out.append(RouteStation(
                    station=s,
                    miles_along=proj.miles_along,
                    perp_miles=proj.perp_miles,
                ))
        out.sort(key=lambda r: r.miles_along)
        return out


# ---------------------------------------------------------------------------
# Module-level singleton with thread-safe lazy init.
# ---------------------------------------------------------------------------

_index: StationIndex | None = None
_lock = threading.Lock()


def _load_from_disk(path: Path) -> list[Station]:
    if not path.exists():
        log.warning("Stations file not found at %s — index will be empty.", path)
        return []
    with path.open() as f:
        rows = json.load(f)
    return [Station(**r) for r in rows]


def get_index() -> StationIndex:
    """Return the singleton StationIndex, building it on first call."""
    global _index
    if _index is not None:
        return _index
    with _lock:
        if _index is None:
            stations = _load_from_disk(Path(settings.STATIONS_JSON_PATH))
            _index = StationIndex(stations)
    return _index


def reset_index_for_tests(stations: list[Station]) -> None:
    """Replace the singleton with a hand-built index. Test-only."""
    global _index
    _index = StationIndex(stations)
