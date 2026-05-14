"""
Unit tests for the geometry helpers, station index, and fuel planner.

These run without network or the real fuel_stations.json — every test builds
a tiny synthetic route + station set on the fly. Run with:

    .venv/bin/python manage.py test routing
"""
from __future__ import annotations

import math

from django.test import TestCase, override_settings

from routing.services.geometry import (
    EARTH_RADIUS_MILES,
    haversine_miles,
    index_polyline,
    point_at_miles,
    project_onto,
)
from routing.services.planner import PlanningError, plan_fuel
from routing.services.stations import RouteStation, Station, StationIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Miles per degree at the equator, matching the haversine constant used in
# geometry.py so synthetic test routes have *exactly* their advertised length.
MILES_PER_DEG = math.pi * EARTH_RADIUS_MILES / 180.0


def _straight_line_east(miles: float, steps: int = 200) -> list[tuple[float, float]]:
    """A straight east-west polyline at the equator. Total length == ``miles``."""
    deg = miles / MILES_PER_DEG
    return [(0.0, deg * i / (steps - 1)) for i in range(steps)]


def _station(id_, name, price, lat, lon, *, state="XX") -> Station:
    return Station(
        id=id_, name=name, address="", city="", state=state,
        price=price, lat=lat, lon=lon,
    )


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


class GeometryTests(TestCase):
    def test_haversine_known_distance(self):
        # NYC -> LA roughly 2451 mi (great-circle).
        d = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertAlmostEqual(d, 2451, delta=30)

    def test_index_polyline_cumulative(self):
        line = index_polyline(_straight_line_east(500))
        self.assertAlmostEqual(line.total_miles, 500, delta=2)
        self.assertEqual(line.cumulative_miles[0], 0.0)
        self.assertGreater(line.cumulative_miles[-1], 490)

    def test_project_point_on_line(self):
        line = index_polyline(_straight_line_east(500))
        proj = project_onto(line, 0.0, 200 / MILES_PER_DEG)
        self.assertAlmostEqual(proj.miles_along, 200, delta=2)
        self.assertLess(proj.perp_miles, 0.5)

    def test_project_point_off_line(self):
        line = index_polyline(_straight_line_east(500))
        # 15 mi north of the 300-mi mark — inside the spatial-index window.
        proj = project_onto(line, 15 / MILES_PER_DEG, 300 / MILES_PER_DEG)
        self.assertAlmostEqual(proj.miles_along, 300, delta=5)
        self.assertAlmostEqual(proj.perp_miles, 15, delta=1)

    def test_project_point_far_off_line_returns_infinity(self):
        # The spatial index intentionally won't search >2 cells (~34 mi) away,
        # which mirrors how the station filter rejects far-off candidates.
        line = index_polyline(_straight_line_east(500))
        proj = project_onto(line, 200 / MILES_PER_DEG, 250 / MILES_PER_DEG)
        self.assertEqual(proj.perp_miles, float("inf"))

    def test_point_at_miles(self):
        line = index_polyline(_straight_line_east(500))
        lat, lon = point_at_miles(line, 250)
        self.assertAlmostEqual(lat, 0.0, delta=0.01)
        self.assertAlmostEqual(lon * MILES_PER_DEG, 250, delta=2)


# ---------------------------------------------------------------------------
# Station index
# ---------------------------------------------------------------------------


class StationIndexTests(TestCase):
    def test_along_route_filters_to_corridor(self):
        line = index_polyline(_straight_line_east(500))
        on_route = _station(1, "ON", 3.00, 0.0, 200 / MILES_PER_DEG)
        # ~5° north ≈ 345 mi off-route.
        off_route = _station(2, "OFF", 3.00, 5.0, 200 / MILES_PER_DEG)
        idx = StationIndex([on_route, off_route])
        matches = idx.along_route(line, corridor_miles=20)
        self.assertEqual([m.station.id for m in matches], [1])

    def test_along_route_returns_sorted_by_miles_along(self):
        line = index_polyline(_straight_line_east(500))
        stations = [
            _station(1, "A", 3.00, 0.0, 400 / MILES_PER_DEG),
            _station(2, "B", 3.00, 0.0, 100 / MILES_PER_DEG),
            _station(3, "C", 3.00, 0.0, 250 / MILES_PER_DEG),
        ]
        idx = StationIndex(stations)
        matches = idx.along_route(line, corridor_miles=20)
        self.assertEqual([m.station.id for m in matches], [2, 3, 1])


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


@override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10, STATION_CORRIDOR_MILES=20)
class PlannerTests(TestCase):
    def _line(self, miles: float):
        return index_polyline(_straight_line_east(miles))

    def _rs(self, miles_along: float, price: float, sid: int = 1) -> RouteStation:
        return RouteStation(
            station=_station(sid, f"S{sid}", price, 0, miles_along / MILES_PER_DEG),
            miles_along=miles_along,
            perp_miles=0,
        )

    def test_short_trip_no_refuel(self):
        line = self._line(300)
        plan = plan_fuel(line, [self._rs(150, 3.00)])
        self.assertEqual(plan.stops, [])
        self.assertEqual(plan.total_fuel_cost_usd, 0)

    def test_single_refuel(self):
        line = self._line(800)
        plan = plan_fuel(line, [
            self._rs(300, 4.00, sid=1),
            self._rs(450, 3.00, sid=2),
        ])
        # Among reachable on first tank, $3.00 wins.
        self.assertEqual([s.station_id for s in plan.stops], [2])
        # Tank arriving at 450 = 500 − 450 = 50 mi. Last leg = 800 − 450 = 350 mi.
        # Need 300 mi more = 30 gal at $3.00.
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 30.0, places=1)
        self.assertAlmostEqual(plan.total_fuel_cost_usd, 90.0, places=2)

    def test_prefers_cheaper_reachable_station(self):
        line = self._line(900)
        plan = plan_fuel(line, [
            self._rs(200, 4.50, sid=1),
            self._rs(400, 3.10, sid=2),
            self._rs(450, 3.50, sid=3),
        ])
        self.assertEqual(plan.stops[0].station_id, 2)

    def test_defers_buy_when_cheaper_ahead(self):
        # 1100 mi trip so the 2nd stop can actually reach the destination.
        line = self._line(1100)
        plan = plan_fuel(line, [
            self._rs(300, 4.00, sid=1),
            self._rs(700, 2.00, sid=2),
        ])
        self.assertEqual([s.station_id for s in plan.stops], [1, 2])
        # Tank arriving at stop1 = 500 − 300 = 200 mi. Need 400 mi to reach
        # the $2 station → buy 200 mi = 20 gal at $4.
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 20.0, places=1)
        self.assertAlmostEqual(plan.stops[0].cost, 80.0, places=2)

    def test_fills_to_full_when_nothing_cheaper_ahead(self):
        # 1100 mi: stop1 cheap ($2), stop2 expensive ($4) — fill up at stop1.
        line = self._line(1100)
        plan = plan_fuel(line, [
            self._rs(300, 2.00, sid=1),
            self._rs(700, 4.00, sid=2),
        ])
        # At stop1: tank 200 mi, fill to 500 → buy 300 mi = 30 gal at $2.
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 30.0, places=1)

    def test_last_refuel_buys_only_what_is_needed(self):
        line = self._line(700)
        plan = plan_fuel(line, [self._rs(300, 3.00, sid=1)])
        # Tank at 300 = 200 mi. Destination 700 → need 400 mi more.
        # Buy 200 mi = 20 gal at $3.00.
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 20.0, places=1)

    def test_raises_when_no_station_in_range(self):
        line = self._line(900)
        # Only station is 550 mi out — unreachable on a 500 mi tank.
        with self.assertRaises(PlanningError):
            plan_fuel(line, [self._rs(550, 3.00, sid=1)])

    def test_look_ahead_enforces_minimum_gallons(self):
        # Force a "$1 stop": expensive station near edge of range, cheaper
        # one just past it. Without the floor look-ahead buys ~1 gal at the
        # expensive stop (only 30 mi needed to reach the cheap one).
        line = self._line(1000)
        stations = [
            self._rs(480, 5.00, sid=1),
            self._rs(510, 2.00, sid=2),
        ]
        plan = plan_fuel(line, stations, refuel_strategy="look_ahead")
        # First stop must be the expensive one (only reachable from origin).
        self.assertEqual(plan.stops[0].station_id, 1)
        # And it must be a meaningful refuel, not a dollar stop.
        self.assertGreaterEqual(plan.stops[0].gallons_purchased, 10.0)

    def test_min_gallons_zero_restores_raw_look_ahead(self):
        # Passing min_gallons_per_refuel=0 disables the floor — useful when
        # callers want the true cost-optimal plan and don't care about
        # tiny stops.
        line = self._line(1000)
        stations = [
            self._rs(480, 5.00, sid=1),
            self._rs(510, 2.00, sid=2),
        ]
        plan = plan_fuel(
            line, stations,
            refuel_strategy="look_ahead",
            min_gallons_per_refuel=0,
        )
        # Tank arriving at stop1 = 500 − 480 = 20 mi. Target to reach the
        # cheap stop2 = 510 − 480 = 30 mi. Buy 30 − 20 = 10 mi = 1 gal.
        self.assertAlmostEqual(plan.stops[0].gallons_purchased, 1.0, places=1)

    def test_multistop_long_trip(self):
        line = self._line(1800)
        plan = plan_fuel(line, [
            self._rs(200, 3.50, sid=1),
            self._rs(500, 2.50, sid=2),
            self._rs(900, 3.00, sid=3),
            self._rs(1300, 2.80, sid=4),
            self._rs(1600, 3.20, sid=5),
        ])
        self.assertGreaterEqual(len(plan.stops), 2)
        self.assertGreater(plan.total_fuel_cost_usd, 0)
        # The last refuel must leave the truck within one tank of the dest.
        self.assertLessEqual(1800 - plan.stops[-1].miles_along, 500)


@override_settings(VEHICLE_RANGE_MILES=500, VEHICLE_MPG=10, STATION_CORRIDOR_MILES=20)
class StrategyAndStartingTankTests(TestCase):
    """Compare the three refuel strategies + the two starting-tank modes
    against a hand-crafted route where the answer is obvious.
    """

    def _line(self, miles: float):
        return index_polyline(_straight_line_east(miles))

    def _rs(self, miles_along: float, price: float, sid: int = 1) -> RouteStation:
        return RouteStation(
            station=_station(sid, f"S{sid}", price, 0, miles_along / MILES_PER_DEG),
            miles_along=miles_along,
            perp_miles=0,
        )

    def test_cheapest_fill_full_picks_cheapest_but_overfills(self):
        # 1500 mi trip. Cheapest stations are at 200 ($2) and 700 ($2).
        # look_ahead buys minimum at 200 to reach 700; cheapest_fill_full
        # fills to full at 200, paying more total but leaving fewer stops.
        line = self._line(1500)
        stations = [
            self._rs(200, 2.00, sid=1),
            self._rs(450, 4.00, sid=2),
            self._rs(700, 2.00, sid=3),
            self._rs(1100, 3.50, sid=4),
        ]
        look_ahead = plan_fuel(line, stations, refuel_strategy="look_ahead")
        cheapest_fill = plan_fuel(line, stations, refuel_strategy="cheapest_fill_full")
        # Both pick the same cheap stations; cheapest_fill_full pays more
        # because it doesn't defer the bulk buy.
        self.assertEqual(
            [s.station_id for s in look_ahead.stops],
            [s.station_id for s in cheapest_fill.stops],
        )
        self.assertGreaterEqual(
            cheapest_fill.total_fuel_cost_usd,
            look_ahead.total_fuel_cost_usd,
        )

    def test_furthest_fill_full_skips_cheap_stations(self):
        line = self._line(1100)
        # Cheap station at 200 ($1), expensive at 450 ($5). On a full tank
        # both are reachable. furthest picks 450 (the farther one); the
        # other strategies pick 200.
        stations = [
            self._rs(200, 1.00, sid=1),
            self._rs(450, 5.00, sid=2),
            self._rs(900, 3.00, sid=3),
        ]
        furthest = plan_fuel(line, stations, refuel_strategy="furthest_fill_full")
        cheapest = plan_fuel(line, stations, refuel_strategy="cheapest_fill_full")
        self.assertEqual(furthest.stops[0].station_id, 2)  # the $5 one
        self.assertEqual(cheapest.stops[0].station_id, 1)  # the $1 one
        self.assertGreater(furthest.total_fuel_cost_usd, cheapest.total_fuel_cost_usd)

    def test_fillup_at_origin_charges_for_starting_tank(self):
        # Short trip that needs no en-route refuel. With full_free the
        # cost is $0; with fillup_at_origin we pay for 50 gallons at the
        # nearest station's price.
        line = self._line(300)
        stations = [self._rs(50, 3.00, sid=1)]
        free = plan_fuel(line, stations, starting_tank="full_free")
        paid = plan_fuel(line, stations, starting_tank="fillup_at_origin")
        self.assertEqual(free.total_fuel_cost_usd, 0)
        self.assertEqual(len(free.stops), 0)
        # 500 mi / 10 mpg = 50 gal × $3 = $150
        self.assertAlmostEqual(paid.total_fuel_cost_usd, 150.0, places=2)
        self.assertEqual(len(paid.stops), 1)
        self.assertEqual(paid.stops[0].kind, "origin_fillup")
