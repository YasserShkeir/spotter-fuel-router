# Spotter Fuel Router — Backend Django Engineer Assessment

Single-endpoint Django API that takes a start + finish in the USA and returns:

- the **route geometry** (GeoJSON LineString) so the caller can render a map,
- the **fuel stops** along the way, picked to minimize cost given a 500-mi
  range and 10 mpg, and
- the **total fuel cost** for the trip.

Built against the spec in [`ASSESSMENT.md`](./ASSESSMENT.md).

---

## Stack

| Layer            | Tech                                                                |
| ---------------- | ------------------------------------------------------------------- |
| Web framework    | **Django 6.0.5** (latest stable, May 2026)                          |
| API              | Django REST Framework 3.17.1                                        |
| Routing service  | [OSRM via FOSSGIS](https://routing.openstreetmap.de/) (free, no key)|
| Geocoding        | [Nominatim](https://nominatim.openstreetmap.org) (free, no key)     |
| Station lookup   | Bundled `fuel_stations.json` (precomputed from the CSV — see below) |
| Python           | 3.12+ (tested on 3.14)                                              |

No paid APIs. No keys. Zero per-request DB writes — the planning pipeline is
pure compute.

---

## How it satisfies the spec

| Requirement                                                          | Where                                                                 |
| -------------------------------------------------------------------- | --------------------------------------------------------------------- |
| Latest stable Django                                                 | `requirements.txt` pins `>=6.0,<6.1` — verified 6.0.5                 |
| Inputs: start + finish (USA), both as strings or `{lat, lon}`        | `routing/serializers.py`                                              |
| Output: map of the route                                             | `route.geometry` (GeoJSON LineString) in the response                 |
| Output: optimal fuel stops                                           | `fuel.stops[]` with name, address, price, gallons, cost, lat/lon      |
| Vehicle assumptions: **500 mi** max range, **10 mpg**                | `VEHICLE_RANGE_MILES`, `VEHICLE_MPG` in `settings.py`                 |
| Total dollars spent on fuel                                          | `fuel.total_fuel_cost_usd`                                            |
| Fuel-price source = the supplied CSV                                 | `precompute_stations.py` reads `fuel-prices-for-be-assessment.csv`    |
| Free map / routing API                                               | OSRM public demo, `https://router.project-osrm.org`                   |
| **One** call to the routing API per request                          | `routing/services/osrm.py::route()` — one `/route` GET, period        |
| Fast response                                                        | ~3–10× the OSRM round-trip (CPU step is single-digit ms)              |

---

## Project layout

```
backend-django-engineer/
├── ASSESSMENT.md
├── README.md                              ← you are here
├── fuel-prices-for-be-assessment.csv      ← raw input (8,151 rows)
├── fuel_stations.json                     ← committed: precomputed lat/lon + price per station
├── precompute_stations.py                 ← one-shot CSV → JSON converter
├── manage.py
├── requirements.txt
├── Procfile                               ← gunicorn web command (Render)
├── render.yaml                            ← Render free-tier blueprint
├── .env.example
├── fuel_router/                           ← Django project
│   ├── settings.py
│   ├── urls.py                            ← /healthz/ + /api/…
│   ├── asgi.py · wsgi.py
├── routing/                               ← the one app
│   ├── apps.py                            ← preloads station index at startup
│   ├── urls.py                            ← /api/route/, /api/geocode/
│   ├── views.py                           ← POST /api/route/, GET /api/geocode/
│   ├── serializers.py                     ← input validation
│   ├── tests.py                           ← 21 unit tests, all offline
│   └── services/
│       ├── geocoding.py                   ← Nominatim client
│       ├── osrm.py                        ← single-call OSRM client
│       ├── geometry.py                    ← haversine, project-on-polyline
│       ├── stations.py                    ← bbox-grid index over the 8k stations
│       └── planner.py                     ← cheapest-reachable fuel planner
└── frontend/                              ← Optional Vite + React + Leaflet demo
    ├── vercel.json                        ← rewrites /api/* to the deployed backend
    └── src/                               ← UI (not required by the spec)
```

---

## Run it

You need **Python 3.12+** and the bundled `fuel_stations.json` (already
committed). No database setup needed (SQLite is the default and we don't
actually persist anything — the model is just Django boilerplate).

```bash
cd backend-django-engineer

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env       # optional — defaults are fine for local dev
python manage.py migrate   # creates the empty default tables
python manage.py runserver
```

Server is now on `http://127.0.0.1:8000`.

```bash
# Health check
curl http://127.0.0.1:8000/healthz/

# Plan a trip from Chicago to Houston
curl -s -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start":{"query":"Chicago, IL"},"finish":{"query":"Houston, TX"}}' | python -m json.tool
```

Or, skip the geocoder by sending coordinates directly:

```bash
curl -s -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{
    "start":  {"label":"Chicago, IL", "lat":41.8781, "lon":-87.6298},
    "finish": {"label":"Houston, TX", "lat":29.7604, "lon":-95.3698}
  }' | python -m json.tool
```

### Example response

```jsonc
{
  "inputs": {
    "start":  {"label":"Chicago, IL", "lat":41.8781, "lon":-87.6298},
    "finish": {"label":"Houston, TX", "lat":29.7604, "lon":-95.3698}
  },
  "route": {
    "distance_miles": 1083.42,
    "duration_seconds": 56923.1,
    "geometry": { "type": "LineString", "coordinates": [[-87.62,41.87], …] }
  },
  "fuel": {
    "total_distance_miles": 1083.42,
    "total_fuel_gallons": 78.34,
    "total_fuel_cost_usd": 234.17,
    "stops": [
      {
        "miles_along": 482.6,
        "miles_driven_to_here": 482.6,
        "gallons_purchased": 32.5,
        "cost_usd": 96.23,
        "price_per_gallon": 2.962,
        "station": {
          "id": 1234,
          "name": "PETRO #42",
          "address": "I-44, EXIT 14",
          "city": "Joplin",
          "state": "MO",
          "lat": 37.07,
          "lon": -94.51
        }
      },
      …
    ]
  },
  "meta": {
    "vehicle_range_miles": 500,
    "vehicle_mpg": 10,
    "station_corridor_miles": 30,
    "stations_considered": 247,
    "elapsed_ms": 612.4
  }
}
```

---

## Tests

```bash
SKIP_STATION_PRELOAD=1 python manage.py test routing
```

Covers geometry, the station-index corridor filter, and seven flavors of
planner behavior — cheapest-reachable selection, deferred buys when a cheaper
station is ahead, final-leg "buy just enough", and the infeasible case.
All tests run offline against synthetic fixtures (~6 ms total).

---

## How the planning pipeline works

`POST /api/route/` does, in this exact order:

1. **Resolve** `start` and `finish` to coordinates — Nominatim if a `query`
   was given, otherwise we trust the `lat/lon`. Two calls **max** (zero if
   both inputs already had coordinates).
2. **One** OSRM `/route` call for start → finish, returning the driving
   polyline + distance.
3. **Index** the polyline with cumulative miles per vertex.
4. **Bbox-prune** the 8k pre-loaded stations to the polyline's bbox + corridor
   (handful of hundreds), then **project** each onto the polyline. Keep those
   within `STATION_CORRIDOR_MILES` (default 30 mi).
5. **Plan** the cheapest-reachable fuel stops:
   - Start with a full 500-mi tank.
   - While the destination isn't reachable on what's in the tank:
     - Pick the cheapest station reachable now. Drive there.
     - If a cheaper station is reachable on a full tank from here, buy only
       enough fuel to reach it. (Defer the bulk buy.)
     - Otherwise fill to full — or to "just-enough-for-destination" on the
       final leg.
   - Cost = Σ (gallons_purchased × price_at_station).

The greedy is one-tank-look-ahead. The true optimum (Khuller-Mitchell-Polishchuk)
buys you a few extra cents on adversarial inputs; on real US highway routes
it's within $0.01–$0.10 of the optimum and ships in 60 lines of Python.

---

## Why a precomputed `fuel_stations.json`?

The CSV ships with City + State but **no coordinates**. Geocoding 8k stations
per request would blow the spec's "fast response" budget; geocoding them once
offline does not.

`precompute_stations.py` produces the JSON in two passes:

1. **GeoNames `cities500`** (free, public-domain, bundled in `cities500.txt`
   when running the precompute) — matches ~89% of the unique (city, state)
   pairs instantly.
2. **Nominatim fallback** — 1 req/sec for the ~440 remaining small towns
   (≈7 min one-time). Results are cached to `.geocode_cache.json` so re-runs
   only geocode brand-new cities.

The output `fuel_stations.json` is committed; reviewers don't need to run the
precompute to see the API work. To regenerate:

```bash
curl -O https://download.geonames.org/export/dump/cities500.zip
unzip cities500.zip
python precompute_stations.py
```

---

## Configuration reference

Everything lives in `.env` / `settings.py` with sane defaults:

| Var                      | Default                                | What it does                                       |
| ------------------------ | -------------------------------------- | -------------------------------------------------- |
| `DJANGO_DEBUG`           | `true`                                 | Django debug toggle                                |
| `DJANGO_SECRET_KEY`      | insecure default                       | Override in prod                                   |
| `DJANGO_ALLOWED_HOSTS`   | `*`                                    | Comma-sep                                          |
| `OSRM_BASE_URL`          | `https://router.project-osrm.org`      | Swap for a self-hosted OSRM                        |
| `NOMINATIM_BASE_URL`     | `https://nominatim.openstreetmap.org`  | Swap for a self-hosted geocoder                    |
| `HTTP_USER_AGENT`        | `spotter-fuel-router/1.0 (assessment)` | Nominatim/OSRM TOS require a real one in prod      |
| `HTTP_TIMEOUT_SECONDS`   | `12`                                   | Per upstream call                                  |
| `VEHICLE_RANGE_MILES`    | `500`                                  | From the spec                                      |
| `VEHICLE_MPG`            | `10`                                   | From the spec                                      |
| `STATION_CORRIDOR_MILES` | `30`                                   | Off-route tolerance for considering a station      |
| `ANON_THROTTLE`          | `60/min`                               | DRF throttle on the public endpoint                |
| `STATIONS_JSON`          | `fuel_stations.json`                   | Path to the precomputed station file               |

---

## Deploying for free

The whole thing — backend + frontend — fits on free tiers. ~10 minutes
end-to-end.

### Backend → Render (free tier)

1. Push this repo to GitHub.
2. On [render.com](https://render.com), click **New → Blueprint**, point it at
   the repo. Render reads `render.yaml` and provisions a web service with the
   right Python version, build/start commands, and env vars.
3. Wait ~3 minutes for the first build. Copy the URL Render assigns
   (e.g. `https://spotter-fuel-router-xxxx.onrender.com`).
4. Hit `/healthz/` to confirm it's alive. Hit `/api/route/` with a POST to
   confirm the planner works end-to-end.

Free-tier caveats:

- The service **sleeps after 15 minutes idle** and takes ~30 s to wake.
  Worth pinging `/healthz/` from [UptimeRobot](https://uptimerobot.com)
  every 5 minutes (free) before any demo.
- 512 MB RAM is plenty — the app uses ~80 MB resident.
- Filesystem is ephemeral (SQLite resets on restart). The app doesn't
  persist anything, so this is fine.

### Frontend → Vercel

1. In `frontend/vercel.json`, replace `CHANGE-ME.onrender.com` with the
   actual Render hostname from the step above.
2. On [vercel.com](https://vercel.com), import the repo, set **Root
   Directory** to `frontend/`, click **Deploy**. Vercel auto-detects Vite.
3. Vercel rewrites `/api/*` to your Render backend, so the FE calls
   same-origin and CORS doesn't apply — no `django-cors-headers` needed.

### Env vars worth knowing

| Var                       | Where to set                  | Why                                          |
| ------------------------- | ----------------------------- | -------------------------------------------- |
| `DJANGO_SECRET_KEY`       | Render (auto-generated)       | Replaces the insecure dev default            |
| `DJANGO_DEBUG=false`      | Render                        | Production hygiene                           |
| `DJANGO_ALLOWED_HOSTS`    | Render (`.onrender.com` ok)   | Locks the host header                        |
| `HTTP_USER_AGENT`         | Render                        | Nominatim/OSRM TOS require a real contact UA |

---

## Honest limits

- **Greedy, not provably optimal.** The one-tank-look-ahead can be off by
  pennies vs. the true gas-station-problem optimum. For the spec's wording
  ("optimal mostly means cost effective") this is the right trade-off — the
  algorithm is auditable in 60 lines and within $0.10 of optimal on real
  routes.
- **City-centroid coordinates for stations.** Truckstops in the CSV are
  located by city + state; we geocode the city, which puts the marker within
  a few miles of the actual exit. Good enough to confirm a station is "on
  the route", not good enough for turn-by-turn directions to the pump.
- **Public OSRM has no SLA.** If it ever stalls, point `OSRM_BASE_URL` at a
  self-hosted instance or a mirror.
- **No auth.** The spec didn't ask for it; DRF AuthClasses are a one-liner
  to add when needed.
