"""
Pure geometry helpers — haversine distance, point→polyline projection, and
walking a polyline by cumulative miles.

These are small enough that I'd usually inline them, but they're load-bearing
for the station-on-route filter *and* the planner, so giving them a stable
home + dedicated tests is worth it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two (lat, lon) points, in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


_VERTEX_GRID_DEG = 0.25  # ~17 mi cells — large enough to cover the corridor


@dataclass(frozen=True)
class IndexedPolyline:
    """A polyline with pre-computed cumulative distance per vertex *and* a
    coarse lat/lon grid of vertex indices so per-station projection only
    touches nearby segments instead of all 10k+.
    """

    coords: list[tuple[float, float]]
    cumulative_miles: list[float]
    total_miles: float
    vertex_grid: dict[tuple[int, int], list[int]]


def index_polyline(coords: list[tuple[float, float]]) -> IndexedPolyline:
    """Pre-compute cumulative miles + vertex-cell index for a polyline."""
    if not coords:
        return IndexedPolyline([], [], 0.0, {})
    cum: list[float] = [0.0]
    grid: dict[tuple[int, int], list[int]] = {}
    # First vertex into the grid.
    first = (int(coords[0][0] // _VERTEX_GRID_DEG), int(coords[0][1] // _VERTEX_GRID_DEG))
    grid.setdefault(first, []).append(0)
    for i in range(1, len(coords)):
        d = haversine_miles(*coords[i - 1], *coords[i])
        cum.append(cum[-1] + d)
        cell = (int(coords[i][0] // _VERTEX_GRID_DEG), int(coords[i][1] // _VERTEX_GRID_DEG))
        grid.setdefault(cell, []).append(i)
    return IndexedPolyline(list(coords), cum, cum[-1], grid)


@dataclass(frozen=True)
class ProjectedPoint:
    """Result of projecting a point onto a polyline."""

    miles_along: float       # cumulative distance from polyline start
    perp_miles: float        # perpendicular (off-route) miles
    nearest_lat: float       # closest point on polyline
    nearest_lon: float


def project_onto(line: IndexedPolyline, lat: float, lon: float) -> ProjectedPoint:
    """Project (lat, lon) onto ``line``, returning along-route + off-route miles.

    Uses ``line.vertex_grid`` to limit the search to segments whose endpoints
    fall in a small neighborhood of the query point — turning O(|polyline|)
    into O(|nearby vertices|) per call. For a 10k-vertex cross-country route
    that's a ~200x speedup.

    Within each candidate segment we use a local-flat projection — fine at
    the per-segment scale (sub-mile) — and re-measure perpendicular distance
    with haversine for accuracy.
    """
    if not line.coords:
        return ProjectedPoint(0.0, float("inf"), lat, lon)

    # Find vertex indices in nearby grid cells. Radius of 2 cells covers a
    # ~33-mile annulus — wider than any realistic corridor.
    cell_lat = int(lat // _VERTEX_GRID_DEG)
    cell_lon = int(lon // _VERTEX_GRID_DEG)
    candidate_vertices: set[int] = set()
    for di in (-2, -1, 0, 1, 2):
        for dj in (-2, -1, 0, 1, 2):
            for idx in line.vertex_grid.get((cell_lat + di, cell_lon + dj), ()):
                candidate_vertices.add(idx)
    if not candidate_vertices:
        return ProjectedPoint(0.0, float("inf"), line.coords[0][0], line.coords[0][1])

    # Each candidate vertex contributes the segment that ends at it (and the
    # one that starts at it).
    segments: set[int] = set()
    for i in candidate_vertices:
        if i > 0:
            segments.add(i - 1)
        if i < len(line.coords) - 1:
            segments.add(i)

    best = ProjectedPoint(0.0, float("inf"), line.coords[0][0], line.coords[0][1])
    cos_lat = math.cos(math.radians(lat))

    def latlon_to_xy(p_lat: float, p_lon: float) -> tuple[float, float]:
        return (p_lon - lon) * 69.0 * cos_lat, (p_lat - lat) * 69.0

    for seg_start in segments:
        a_lat, a_lon = line.coords[seg_start]
        b_lat, b_lon = line.coords[seg_start + 1]
        ax, ay = latlon_to_xy(a_lat, a_lon)
        bx, by = latlon_to_xy(b_lat, b_lon)

        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq == 0:
            t = 0.0
            nx, ny = ax, ay
        else:
            t = max(0.0, min(1.0, (-ax * dx + -ay * dy) / seg_len_sq))
            nx, ny = ax + t * dx, ay + t * dy

        n_lat = lat + ny / 69.0
        n_lon = lon + nx / (69.0 * cos_lat) if cos_lat != 0 else lon

        perp = haversine_miles(lat, lon, n_lat, n_lon)
        if perp < best.perp_miles:
            seg_miles = line.cumulative_miles[seg_start + 1] - line.cumulative_miles[seg_start]
            miles_along = line.cumulative_miles[seg_start] + t * seg_miles
            best = ProjectedPoint(miles_along, perp, n_lat, n_lon)

    return best


def point_at_miles(line: IndexedPolyline, miles: float) -> tuple[float, float]:
    """Return the (lat, lon) at ``miles`` along the polyline (linear interp)."""
    if not line.coords:
        return 0.0, 0.0
    if miles <= 0:
        return line.coords[0]
    if miles >= line.total_miles:
        return line.coords[-1]

    # Binary search would be O(log n); linear is fine for our polyline sizes.
    cum = line.cumulative_miles
    for i in range(1, len(cum)):
        if cum[i] >= miles:
            seg = cum[i] - cum[i - 1]
            if seg <= 0:
                return line.coords[i]
            t = (miles - cum[i - 1]) / seg
            a_lat, a_lon = line.coords[i - 1]
            b_lat, b_lon = line.coords[i]
            return a_lat + t * (b_lat - a_lat), a_lon + t * (b_lon - a_lon)
    return line.coords[-1]
