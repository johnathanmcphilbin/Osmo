# OsmoMap

Interactive siting tool for salinity gradient (osmotic) energy installations. Scores river mouth locations 0–100 using discharge rates, ocean salinity, power grid proximity, and land access.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 — the map loads immediately from seed data for 8 European pilot sites.

## Scoring model

```
score = (salinity_delta × 0.4) + (flow_consistency × 0.3) + (grid_proximity × 0.2) + (land_access × 0.1)
```

Each factor is normalised to 0–100 before weighting. Flow consistency uses a log scale to handle the wide range of river discharges.

| Tier   | Score range |
|--------|-------------|
| High   | 70–100      |
| Medium | 40–69       |
| Low    | 0–39        |

## Re-scoring with live data

```bash
# Re-score from seed (no network calls)
python ingest.py

# Attempt live OSM power grid distances (best-effort, falls back to seed)
python ingest.py --refresh
```

Or POST to the running server:

```bash
curl -X POST http://localhost:5000/api/refresh
```

## API

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Map UI |
| `/api/sites` | GET | GeoJSON FeatureCollection |
| `/api/sites/<id>` | GET | Full site detail + seasonal chart data |
| `/api/export` | GET | CSV download of all scored sites |
| `/api/refresh` | POST | Re-run ingest pipeline |

## Data sources

- **USGS Water Services** — river discharge (parameterCd=00060)
- **Copernicus Marine Service (CMEMS)** — ocean salinity (GLOBAL_ANALYSISFORECAST_PHY_001_024)
- **OpenStreetMap / Overpass API** — power line proximity

## File structure

```
osmomap/
├── app.py              Flask application
├── ingest.py           Data fetching + scoring pipeline
├── models.py           SQLite schema + query helpers
├── static/
│   └── sites.geojson   Generated GeoJSON (auto-created on first run)
├── templates/
│   └── index.html      Single-page map frontend
├── data/
│   └── seed_sites.json Hardcoded pilot site parameters
├── requirements.txt
└── README.md
```
