"""
app.py — Flask application for OsmoMap.
Run: python app.py
"""

import csv
import io
import json
from pathlib import Path

from flask import Flask, jsonify, make_response, render_template, request

import ingest
import models

app = Flask(__name__)

GEOJSON_FILE = Path(__file__).parent / "static" / "sites.geojson"


def _ensure_geojson():
    if not GEOJSON_FILE.exists():
        print("No GeoJSON found — running ingest from seed data...")
        ingest.run(refresh=False)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    _ensure_geojson()
    return render_template("index.html")


@app.route("/api/sites")
def api_sites():
    _ensure_geojson()
    with open(GEOJSON_FILE) as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/sites/<int:site_id>")
def api_site_detail(site_id):
    detail = models.get_site_detail(site_id)
    if not detail:
        return jsonify({"error": "Site not found"}), 404

    # Attach seasonal data from GeoJSON (precomputed)
    if GEOJSON_FILE.exists():
        with open(GEOJSON_FILE) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            if feat["properties"]["id"] == site_id:
                detail["seasonal_flow"] = feat["properties"].get("seasonal_flow", [])
                break

    return jsonify(detail)


@app.route("/api/export")
def api_export():
    sites = models.get_all_sites_with_scores()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "name", "country", "river_name", "lat", "lon",
        "score", "score_tier", "salinity_delta", "flow_rate_m3s", "scored_at",
    ])

    # Enrich with GeoJSON extras
    gj_props = {}
    if GEOJSON_FILE.exists():
        with open(GEOJSON_FILE) as f:
            gj = json.load(f)
        for feat in gj["features"]:
            p = feat["properties"]
            gj_props[p["id"]] = p

    for s in sites:
        p = gj_props.get(s["id"], {})
        writer.writerow([
            s["id"], s["name"], s["country"], s["river_name"],
            s["lat"], s["lon"],
            s["score"], p.get("score_tier", ""),
            s["salinity_delta"], s["flow_rate_m3s"], s["scored_at"],
        ])

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv"
    resp.headers["Content-Disposition"] = "attachment; filename=osmomap_sites.csv"
    return resp


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    live = request.json.get("live", False) if request.is_json else False
    try:
        ingest.run(refresh=live)
        return jsonify({"status": "ok", "message": "Re-scored successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    models.init_db()
    _ensure_geojson()
    app.run(debug=True, port=5000)
