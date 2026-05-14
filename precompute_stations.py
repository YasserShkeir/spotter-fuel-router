"""
One-shot pre-geocoding script.

The fuel-prices CSV has Truckstop Name + City + State but **no coordinates**,
and at request time we can't afford to geocode 8k+ rows. So we run this once
offline: read the CSV, look up each unique (city, state) against a bundled
GeoNames snapshot, fall back to Nominatim for the long tail, and write
``fuel_stations.json`` next to ``manage.py``. The Django app then loads that
JSON at startup -- zero network calls in the hot path.

Run it whenever the CSV or `cities500.txt` changes:

    .venv/bin/python precompute_stations.py

It's idempotent and uses a local cache so re-runs only geocode genuinely-new
cities.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "fuel-prices-for-be-assessment.csv"
CITIES500 = ROOT / "cities500.txt"
OUTPUT = ROOT / "fuel_stations.json"
NOMINATIM_CACHE = ROOT / ".geocode_cache.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "spotter-eld-backend-assessment/1.0 (assessment@spotter.ai)"
RATE_LIMIT_S = 1.05  # be polite — Nominatim public TOS is ≤1 req/sec

CANADIAN_PROVINCES = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}

log = logging.getLogger("precompute")


def _normalize(name: str) -> str:
    """Normalize a city name for fuzzy matching.

    Handles 'Saint Louis' vs 'St. Louis', 'Mt. Vernon' vs 'Mount Vernon',
    'Mc Graw' vs 'McGraw', and stray punctuation/whitespace differences.
    """
    n = name.upper().strip()
    n = re.sub(r"\bSAINT\b", "ST", n)
    n = re.sub(r"\bMOUNT\b", "MT", n)
    n = re.sub(r"\bFORT\b", "FT", n)
    return re.sub(r"[^A-Z]", "", n)


def _load_geonames_lookup() -> dict[tuple[str, str], tuple[float, float]]:
    """Build {(normalized_city, STATE) -> (lat, lon)} from cities500.txt.

    We index both the primary asciiname and every alternatenames entry so
    e.g. 'McGraw' resolves whether the CSV writes it as 'McGraw' or 'Mc Graw'.
    """
    if not CITIES500.exists():
        log.warning("cities500.txt not found at %s — all cities go to Nominatim", CITIES500)
        return {}

    lookup: dict[tuple[str, str], tuple[float, float, int]] = {}
    with CITIES500.open(encoding="utf-8") as f:
        for line in f:
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 15 or cols[8] != "US":
                continue
            state = cols[10].strip().upper()
            if not state:
                continue
            try:
                lat, lon = float(cols[4]), float(cols[5])
            except ValueError:
                continue
            try:
                pop = int(cols[14]) if cols[14] else 0
            except ValueError:
                pop = 0

            names = [cols[2]] + (cols[3].split(",") if cols[3] else [])
            for raw in names:
                key = (_normalize(raw), state)
                if not key[0]:
                    continue
                prev = lookup.get(key)
                # Keep the most-populated row when a (name, state) collides —
                # 'Springfield, MO' should resolve to the big one, not a hamlet.
                if prev is None or pop > prev[2]:
                    lookup[key] = (lat, lon, pop)

    return {k: (v[0], v[1]) for k, v in lookup.items()}


def _load_geocode_cache() -> dict[str, list[float] | None]:
    if NOMINATIM_CACHE.exists():
        try:
            return json.loads(NOMINATIM_CACHE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_geocode_cache(cache: dict[str, list[float] | None]) -> None:
    NOMINATIM_CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _nominatim_geocode(city: str, state: str) -> tuple[float, float] | None:
    """One polite Nominatim lookup. Returns None on hard miss."""
    params = {
        "q": f"{city}, {state}, USA",
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
    }
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        rows = r.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Nominatim failed for %s, %s: %s", city, state, exc)
        return None
    if not rows:
        return None
    try:
        return float(rows[0]["lat"]), float(rows[0]["lon"])
    except (KeyError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-nominatim",
        action="store_true",
        help="Skip Nominatim fallback; cities not in cities500 will be omitted.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    log.info("Loading GeoNames cities500 lookup…")
    geonames = _load_geonames_lookup()
    log.info("  %s normalized (name, state) keys", f"{len(geonames):,}")

    cache = _load_geocode_cache()
    log.info("Loaded geocode cache: %s entries", f"{len(cache):,}")

    log.info("Reading truckstop CSV: %s", CSV_PATH)
    with CSV_PATH.open() as f:
        rows = list(csv.DictReader(f))

    # Unique (city, state) pairs that need a coordinate
    pairs: dict[tuple[str, str], tuple[float, float] | None] = {}
    skipped_canadian = 0
    for row in rows:
        city = row["City"].strip()
        state = row["State"].strip().upper()
        if state in CANADIAN_PROVINCES:
            skipped_canadian += 1
            continue
        pairs[(city, state)] = None
    log.info("Unique US (city, state) pairs: %s (skipped %s Canadian rows)",
             f"{len(pairs):,}", skipped_canadian)

    # 1) GeoNames pass
    hits_geonames = 0
    for key in pairs:
        city, state = key
        coord = geonames.get((_normalize(city), state))
        if coord is not None:
            pairs[key] = coord
            hits_geonames += 1
    log.info("GeoNames matched: %s/%s (%.1f%%)",
             f"{hits_geonames:,}", f"{len(pairs):,}",
             hits_geonames / max(len(pairs), 1) * 100)

    # 2) Nominatim fallback for the misses
    misses = [k for k, v in pairs.items() if v is None]
    hits_nominatim = 0
    hits_cache = 0
    if args.no_nominatim:
        log.info("Skipping Nominatim fallback (per --no-nominatim).")
    else:
        log.info("Resolving %s remaining cities via Nominatim @ 1 req/sec…",
                 f"{len(misses):,}")
        last = 0.0
        for i, (city, state) in enumerate(misses, 1):
            cache_key = f"{_normalize(city)}|{state}"
            if cache_key in cache:
                hit = cache[cache_key]
                if hit:
                    pairs[(city, state)] = (hit[0], hit[1])
                    hits_cache += 1
                continue

            # Honor the 1 req/sec policy.
            elapsed = time.monotonic() - last
            if elapsed < RATE_LIMIT_S:
                time.sleep(RATE_LIMIT_S - elapsed)
            last = time.monotonic()

            result = _nominatim_geocode(city, state)
            if result is not None:
                pairs[(city, state)] = result
                hits_nominatim += 1
                cache[cache_key] = [result[0], result[1]]
            else:
                cache[cache_key] = None

            if i % 25 == 0:
                log.info("  %s/%s — last: %s, %s -> %s",
                         i, len(misses), city, state, result)
                _save_geocode_cache(cache)

        _save_geocode_cache(cache)
        log.info("Nominatim: %s new hits, %s cache hits", hits_nominatim, hits_cache)

    # 3) Build final station list
    stations = []
    missing_keys = []
    for row in rows:
        city = row["City"].strip()
        state = row["State"].strip().upper()
        if state in CANADIAN_PROVINCES:
            continue
        coord = pairs.get((city, state))
        if coord is None:
            missing_keys.append((city, state))
            continue
        try:
            price = float(row["Retail Price"])
        except (ValueError, KeyError):
            continue
        stations.append({
            "id": int(row["OPIS Truckstop ID"]),
            "name": row["Truckstop Name"].strip(),
            "address": row["Address"].strip(),
            "city": city,
            "state": state,
            "price": round(price, 4),
            "lat": round(coord[0], 6),
            "lon": round(coord[1], 6),
        })

    OUTPUT.write_text(json.dumps(stations, indent=1))
    log.info("Wrote %s stations to %s", f"{len(stations):,}", OUTPUT)
    log.info("Dropped %s stations whose city could not be geocoded.",
             f"{len(set(missing_keys)):,}")
    if missing_keys and args.verbose:
        for k in sorted(set(missing_keys))[:20]:
            log.info("  unresolved: %s", k)

    return 0


if __name__ == "__main__":
    sys.exit(main())
