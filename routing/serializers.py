"""
Input validation for POST /api/route/.

Each location can be either:
  * a free-text ``query`` string (we geocode it via Nominatim), or
  * a pre-resolved ``{lat, lon, label?}``  (we trust it — zero geocode calls).

``options`` controls planner behavior; both fields are optional and default to
the smartest setting (look-ahead with a free starting tank).
"""
from __future__ import annotations

from rest_framework import serializers


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, allow_blank=False, max_length=255)
    label = serializers.CharField(required=False, allow_blank=False, max_length=255)
    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lon = serializers.FloatField(required=False, min_value=-180, max_value=180)

    def validate(self, attrs):
        has_query = bool(attrs.get("query"))
        has_coords = "lat" in attrs and "lon" in attrs
        if not (has_query or has_coords):
            raise serializers.ValidationError(
                "Provide either `query` (text) or both `lat` and `lon`."
            )
        return attrs


class OptionsSerializer(serializers.Serializer):
    refuel_strategy = serializers.ChoiceField(
        choices=["look_ahead", "cheapest_fill_full", "furthest_fill_full"],
        default="look_ahead",
        required=False,
    )
    starting_tank = serializers.ChoiceField(
        choices=["full_free", "fillup_at_origin"],
        default="full_free",
        required=False,
    )


class RouteRequestSerializer(serializers.Serializer):
    start = LocationSerializer()
    finish = LocationSerializer()
    options = OptionsSerializer(required=False, default=dict)
