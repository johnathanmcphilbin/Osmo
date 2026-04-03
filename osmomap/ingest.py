"""
ingest.py — data fetching, scoring, and GeoJSON generation for OsmoMap.

Usage:
    python ingest.py            # seed from local JSON, no live API calls
    python ingest.py --refresh  # attempt live API pulls, fall back to seed
"""

from __future__ import annotations

import argparse
import json
import math
import datetime
from pathlib import Path
from typing import Optional

import requests

import models

SEED_FILE = Path(__file__).parent / "data" / "seed_sites.json"
GEOJSON_FILE = Path(__file__).parent / "static" / "sites.geojson"

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

MAX_SALINITY = 36.0        # practical ocean max (PSU)
MAX_FLOW = 10_000.0        # m³/s — rough upper bound for normalisation
MAX_GRID_DIST = 50.0       # km — beyond this, grid_proximity → 0


def _norm(value: float, lo: float, hi: float) -> float:
    """Clamp and normalise value to 0–100."""
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100))


def score_site(salinity_delta: float, flow_rate_m3s: float,
               grid_distance_km: float, land_access_score: float):
    sal_norm = _norm(salinity_delta, 0, MAX_SALINITY)
    # Flow consistency: higher and steadier is better; use log scale
    flow_norm = _norm(math.log1p(flow_rate_m3s), 0, math.log1p(MAX_FLOW)) if flow_rate_m3s > 0 else 0.0
    grid_norm = _norm(MAX_GRID_DIST - grid_distance_km, 0, MAX_GRID_DIST)
    land_norm = _norm(land_access_score, 0, 100)

    score = (
        sal_norm  * 0.4 +
        flow_norm * 0.3 +
        grid_norm * 0.2 +
        land_norm * 0.1
    )

    breakdown = {
        "salinity_component":     round(sal_norm  * 0.4, 2),
        "flow_component":         round(flow_norm * 0.3, 2),
        "grid_proximity_component": round(grid_norm * 0.2, 2),
        "land_access_component":  round(land_norm * 0.1, 2),
        "salinity_delta_norm":    round(sal_norm, 2),
        "flow_norm":              round(flow_norm, 2),
        "grid_norm":              round(grid_norm, 2),
        "land_norm":              round(land_norm, 2),
    }
    return round(score, 2), breakdown


def score_tier(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Live data fetchers (best-effort, fall back to seed values)
# ---------------------------------------------------------------------------

def fetch_usgs_flow(site_id: str) -> Optional[float]:
    """Fetch latest discharge (ft³/s → m³/s) for a USGS gauge."""
    url = (
        "https://waterservices.usgs.gov/nwis/iv/"
        f"?format=json&sites={site_id}&parameterCd=00060"
    )
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        ts = r.json()["value"]["timeSeries"]
        if not ts:
            return None
        val = float(ts[0]["values"][0]["value"][0]["value"])
        return round(val * 0.0283168, 2)   # ft³/s → m³/s
    except Exception:
        return None


def fetch_grid_distance_osm(lat: float, lon: float) -> Optional[float]:
    """Query Overpass for nearest power line and return approx distance (km)."""
    query = f"""
    [out:json][timeout:15];
    (
      way["power"="line"](around:50000,{lat},{lon});
      relation["power"="line"](around:50000,{lat},{lon});
    );
    out center 1;
    """
    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            timeout=20,
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])
        if not elements:
            return None
        el = elements[0]
        el_lat = el.get("center", el).get("lat", lat)
        el_lon = el.get("center", el).get("lon", lon)
        # Haversine
        R = 6371.0
        dlat = math.radians(el_lat - lat)
        dlon = math.radians(el_lon - lon)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat)) * math.cos(math.radians(el_lat)) *
             math.sin(dlon / 2) ** 2)
        return round(R * 2 * math.asin(math.sqrt(a)), 2)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Seasonal chart data generator (synthetic but plausible)
# ---------------------------------------------------------------------------

SEASONAL_PATTERN = [0.8, 0.85, 1.0, 1.1, 1.05, 0.9, 0.75, 0.70, 0.80, 0.95, 1.05, 0.9]

def seasonal_flow(base_flow: float) -> list[dict]:
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return [
        {"month": m, "flow_rate_m3s": round(base_flow * f, 1)}
        for m, f in zip(months, SEASONAL_PATTERN)
    ]


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def load_seed() -> list[dict]:
    with open(SEED_FILE) as f:
        return json.load(f)


def run(refresh: bool = False):
    models.init_db()
    sites = load_seed()
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    features = []

    for s in sites:
        # Persist site record
        models.upsert_site({
            "id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"],
            "country": s["country"], "river_name": s["river_name"],
        })

        salinity_delta   = s["salinity_delta"]
        flow_rate_m3s    = s["flow_rate_m3s"]
        grid_distance_km = s["grid_distance_km"]
        land_access      = s["land_access_score"]

        if refresh:
            live_grid = fetch_grid_distance_osm(s["lat"], s["lon"])
            if live_grid is not None:
                grid_distance_km = live_grid
                print(f"  [OSM] {s['name']}: grid distance {live_grid} km")

        # Persist reading
        models.upsert_reading({
            "site_id": s["id"],
            "timestamp": now,
            "salinity_delta": salinity_delta,
            "flow_rate_m3s": flow_rate_m3s,
            "source": "live" if refresh else "seed",
        })

        score, breakdown = score_site(salinity_delta, flow_rate_m3s, grid_distance_km, land_access)
        models.upsert_score(s["id"], score, breakdown, now)

        tier = score_tier(score)
        feature = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
            "properties": {
                "id": s["id"],
                "name": s["name"],
                "country": s["country"],
                "river_name": s["river_name"],
                "score": score,
                "salinity_delta": salinity_delta,
                "flow_rate_m3s": flow_rate_m3s,
                "grid_distance_km": grid_distance_km,
                "land_access_score": land_access,
                "score_tier": tier,
                "breakdown": breakdown,
                "seasonal_flow": seasonal_flow(flow_rate_m3s),
                "last_updated": now[:7],   # YYYY-MM
            },
        }
        features.append(feature)
        print(f"  Scored {s['name']}: {score} ({tier})")

    geojson = {"type": "FeatureCollection", "features": features}
    GEOJSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GEOJSON_FILE, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"\nGeoJSON written to {GEOJSON_FILE} ({len(features)} sites)")
    return geojson


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OsmoMap ingest pipeline")
    parser.add_argument("--refresh", action="store_true",
                        help="Attempt live API data pulls")
    args = parser.parse_args()
    run(refresh=args.refresh)
