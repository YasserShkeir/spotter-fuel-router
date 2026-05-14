"""
Fuel-stop planner with selectable strategies.

The whole point of this module is to make the algorithmic choice **visible** —
the spec says "optimal mostly means cost effective" but reasonable people
disagree on what that means in detail. We expose three refuel strategies plus
two starting-tank conventions so the UI (and the reviewer) can A/B them on
the same route.

Strategies
----------

* ``look_ahead`` (default): cheapest reachable station + one-tank look-ahead.
  At each refuel, if a cheaper station is reachable on a full tank, buy only
  enough to reach the cheaper one (defer the bulk buy). Otherwise fill to
  full. On the final leg, buy only what's needed to reach the destination.
  Each refuel buys at least ``min_gallons_per_refuel`` (default 10) so the
  planner doesn't emit "$1 stops" when a cheaper station is just barely
  ahead. To make this enforceable, the picker also skips reachable stations
  too close to the current position (where filling the minimum would
  overflow the tank). Both apply on the last leg too; the trade-off is the
  truck may arrive with a few gallons of leftover fuel. Skip the floor with
  ``min_gallons_per_refuel=0``.

* ``cheapest_fill_full``: cheapest reachable station, always fill to full
  (or to destination on the last leg). Simpler, slightly worse — pays for
  unused fuel left in the tank when a cheaper station was ahead.

* ``furthest_fill_full``: the naive "maximize range per stop" strategy —
  pick the *farthest* reachable station (minimum stops), fill to full. Tends
  to skip cheaper-but-earlier stations entirely, so almost always the most
  expensive of the three. Included so the comparison UI can show the
  cost of *not* doing this.

Starting tank
-------------

* ``full_free``: the truck leaves the depot with a full tank that doesn't
  count toward the trip's fuel cost. This is the "fleet dispatcher" reading
  of the spec.
* ``fillup_at_origin``: the truck fills up at the nearest fuel station to
  the origin and pays for it. Adds a virtual stop at mile 0 to the response.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from django.conf import settings

from .geometry import IndexedPolyline, point_at_miles
from .stations import RouteStation

log = logging.getLogger(__name__)

RefuelStrategy = Literal["look_ahead", "cheapest_fill_full", "furthest_fill_full"]
StartingTank = Literal["full_free", "fillup_at_origin"]

# Look-ahead can compute a target that's only 1–2 gallons above the current
# tank when a cheaper station is just past the edge of range. Real fleets
# pre-auth ~10 gal and don't bother stopping for less, so we floor each
# refuel here. Doesn't apply on the last leg.
DEFAULT_MIN_GALLONS_PER_REFUEL = 10.0


class PlanningError(Exception):
    """Raised when no feasible fuel plan exists (e.g. a 700-mi gap with no station)."""


@dataclass(frozen=True)
class FuelStop:
    miles_along: float
    miles_driven_to_here: float
    gallons_purchased: float
    cost: float
    price_per_gallon: float
    station_id: int
    name: str
    address: str
    city: str
    state: str
    lat: float
    lon: float
    kind: str = "refuel"  # "refuel" | "origin_fillup"

    def as_dict(self) -> dict:
        return {
            "miles_along": round(self.miles_along, 2),
            "miles_driven_to_here": round(self.miles_driven_to_here, 2),
            "gallons_purchased": round(self.gallons_purchased, 3),
            "cost_usd": round(self.cost, 2),
            "price_per_gallon": round(self.price_per_gallon, 4),
            "kind": self.kind,
            "station": {
                "id": self.station_id,
                "name": self.name,
                "address": self.address,
                "city": self.city,
                "state": self.state,
                "lat": self.lat,
                "lon": self.lon,
            },
        }


@dataclass
class FuelPlan:
    total_distance_miles: float
    total_fuel_gallons: float
    total_fuel_cost_usd: float
    refuel_strategy: str
    starting_tank: str
    stops: list[FuelStop] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "total_distance_miles": round(self.total_distance_miles, 2),
            "total_fuel_gallons": round(self.total_fuel_gallons, 3),
            "total_fuel_cost_usd": round(self.total_fuel_cost_usd, 2),
            "refuel_strategy": self.refuel_strategy,
            "starting_tank": self.starting_tank,
            "stops": [s.as_dict() for s in self.stops],
        }


def _pick_station(
    reachable: list[tuple[int, RouteStation]],
    strategy: RefuelStrategy,
) -> tuple[int, RouteStation]:
    """Choose the next refuel from currently-reachable candidates."""
    if strategy == "furthest_fill_full":
        # Farthest reachable — minimize the number of stops.
        return max(reachable, key=lambda t: t[1].miles_along)
    # Both look_ahead and cheapest_fill_full start with "pick the cheapest";
    # they differ only in how much they buy. Tiebreak on closer-to-current
    # so we don't take pointless detours when prices are equal.
    return min(reachable, key=lambda t: (t[1].station.price, t[1].miles_along))


def plan_fuel(
    line: IndexedPolyline,
    stations: list[RouteStation],
    *,
    range_miles: float | None = None,
    mpg: float | None = None,
    refuel_strategy: RefuelStrategy = "look_ahead",
    starting_tank: StartingTank = "full_free",
    min_gallons_per_refuel: float = DEFAULT_MIN_GALLONS_PER_REFUEL,
) -> FuelPlan:
    """Compute a fuel plan for ``stations`` along ``line``.

    ``stations`` must already be filtered to those within the route corridor
    and sorted by ``miles_along``.
    """
    tank_capacity = range_miles if range_miles is not None else settings.VEHICLE_RANGE_MILES
    mpg_v = mpg if mpg is not None else settings.VEHICLE_MPG
    min_gallons = max(0.0, float(min_gallons_per_refuel))

    total_miles = line.total_miles
    plan = FuelPlan(
        total_distance_miles=total_miles,
        total_fuel_gallons=0.0,
        total_fuel_cost_usd=0.0,
        refuel_strategy=refuel_strategy,
        starting_tank=starting_tank,
        stops=[],
    )

    # The truck leaves with a full tank either way; what differs is whether
    # we charge for it.
    tank = tank_capacity
    ordered = sorted(stations, key=lambda r: r.miles_along)

    if starting_tank == "fillup_at_origin":
        # Bill the trip for the initial 500 mi at the price of the closest
        # station to the origin (the one you'd realistically top up at).
        if not ordered:
            raise PlanningError("No station near the origin to fill up at.")
        nearest_to_origin = min(ordered, key=lambda r: r.miles_along)
        gallons = tank_capacity / mpg_v
        cost = gallons * nearest_to_origin.station.price
        plan.total_fuel_gallons += gallons
        plan.total_fuel_cost_usd += cost
        # Add a virtual mile-0 stop so the UI can label the fillup.
        plan.stops.append(FuelStop(
            miles_along=0.0,
            miles_driven_to_here=0.0,
            gallons_purchased=gallons,
            cost=cost,
            price_per_gallon=nearest_to_origin.station.price,
            station_id=nearest_to_origin.station.id,
            name=nearest_to_origin.station.name,
            address=nearest_to_origin.station.address,
            city=nearest_to_origin.station.city,
            state=nearest_to_origin.station.state,
            lat=line.coords[0][0] if line.coords else nearest_to_origin.station.lat,
            lon=line.coords[0][1] if line.coords else nearest_to_origin.station.lon,
            kind="origin_fillup",
        ))

    if total_miles <= tank:
        return plan  # one-tank trip, no en-route refuels

    position = 0.0
    last_stop_idx = -1

    while position + tank < total_miles:
        reachable_end = position + tank
        reachable = [
            (i, r) for i, r in enumerate(ordered)
            if i > last_stop_idx and position < r.miles_along <= reachable_end
        ]
        if not reachable:
            raise PlanningError(
                f"No fuel station within {tank:.0f} mi of route mile {position:.0f}. "
                f"Try widening STATION_CORRIDOR_MILES or pick a route through more populated areas."
            )

        # Prefer stations far enough away that a min_gallons refuel won't
        # overflow the tank — otherwise the cap-to-capacity below silently
        # undermines the floor and we end up with a "$1 stop" anyway. Only
        # filter when at least one far-enough candidate exists; otherwise
        # we fall through to whatever's reachable and buy what fits.
        if min_gallons > 0:
            min_distance = max(0.0, min_gallons * mpg_v - (tank_capacity - tank))
            far_enough = [
                t for t in reachable
                if t[1].miles_along - position >= min_distance
            ]
            if far_enough:
                reachable = far_enough

        idx, best = _pick_station(reachable, refuel_strategy)

        miles_driven = best.miles_along - position
        tank -= miles_driven
        position = best.miles_along
        last_stop_idx = idx

        # How much fuel to buy depends on the strategy.
        look_end = position + tank_capacity
        on_last_leg = total_miles <= look_end

        if refuel_strategy == "look_ahead":
            if on_last_leg:
                target_fuel = total_miles - position
            else:
                cheaper_ahead = [
                    r for i, r in enumerate(ordered)
                    if i > last_stop_idx and position < r.miles_along <= look_end
                    and r.station.price < best.station.price
                ]
                if cheaper_ahead:
                    # Defer the bulk buy until the cheaper place.
                    nearest = min(cheaper_ahead, key=lambda r: r.miles_along)
                    target_fuel = nearest.miles_along - position
                else:
                    target_fuel = tank_capacity
        else:
            # cheapest_fill_full and furthest_fill_full both fill to full —
            # or to just-enough on the last leg.
            target_fuel = total_miles - position if on_last_leg else tank_capacity

        # Minimum-gallons floor. Applied on every stop, including the last
        # leg — if we tell the user "10 gal minimum per stop", we mean it.
        # On the last leg this may buy a few gallons more than needed to
        # reach the destination (truck arrives with leftover fuel); that's
        # the price of consistent semantics. Capped by tank capacity.
        if min_gallons > 0:
            target_fuel = max(target_fuel, tank + min_gallons * mpg_v)
        target_fuel = min(target_fuel, tank_capacity)

        miles_to_add = max(0.0, target_fuel - tank)
        gallons_to_buy = miles_to_add / mpg_v
        cost = gallons_to_buy * best.station.price

        tank += miles_to_add
        plan.total_fuel_gallons += gallons_to_buy
        plan.total_fuel_cost_usd += cost

        snap_lat, snap_lon = point_at_miles(line, best.miles_along)
        plan.stops.append(FuelStop(
            miles_along=best.miles_along,
            miles_driven_to_here=miles_driven,
            gallons_purchased=gallons_to_buy,
            cost=cost,
            price_per_gallon=best.station.price,
            station_id=best.station.id,
            name=best.station.name,
            address=best.station.address,
            city=best.station.city,
            state=best.station.state,
            lat=snap_lat,
            lon=snap_lon,
        ))

    return plan
