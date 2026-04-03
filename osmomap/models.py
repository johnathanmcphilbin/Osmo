import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "osmomap.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            country TEXT,
            river_name TEXT
        );

        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            salinity_delta REAL,
            flow_rate_m3s REAL,
            source TEXT,
            FOREIGN KEY (site_id) REFERENCES sites(id)
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL UNIQUE,
            score REAL NOT NULL,
            breakdown_json TEXT,
            scored_at TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites(id)
        );
    """)
    conn.commit()
    conn.close()


def upsert_site(site: dict):
    conn = get_db()
    conn.execute(
        """INSERT INTO sites (id, name, lat, lon, country, river_name)
           VALUES (:id, :name, :lat, :lon, :country, :river_name)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, lat=excluded.lat, lon=excluded.lon,
             country=excluded.country, river_name=excluded.river_name""",
        site,
    )
    conn.commit()
    conn.close()


def upsert_reading(reading: dict):
    conn = get_db()
    conn.execute(
        """INSERT INTO readings (site_id, timestamp, salinity_delta, flow_rate_m3s, source)
           VALUES (:site_id, :timestamp, :salinity_delta, :flow_rate_m3s, :source)""",
        reading,
    )
    conn.commit()
    conn.close()


def upsert_score(site_id: int, score: float, breakdown: dict, scored_at: str):
    conn = get_db()
    conn.execute(
        """INSERT INTO scores (site_id, score, breakdown_json, scored_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(site_id) DO UPDATE SET
             score=excluded.score,
             breakdown_json=excluded.breakdown_json,
             scored_at=excluded.scored_at""",
        (site_id, score, json.dumps(breakdown), scored_at),
    )
    conn.commit()
    conn.close()


def get_all_sites_with_scores():
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.name, s.lat, s.lon, s.country, s.river_name,
               sc.score, sc.breakdown_json, sc.scored_at,
               r.salinity_delta, r.flow_rate_m3s
        FROM sites s
        LEFT JOIN scores sc ON sc.site_id = s.id
        LEFT JOIN (
            SELECT site_id, salinity_delta, flow_rate_m3s
            FROM readings
            WHERE id IN (SELECT MAX(id) FROM readings GROUP BY site_id)
        ) r ON r.site_id = s.id
        ORDER BY sc.score DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_site_detail(site_id: int):
    conn = get_db()
    row = conn.execute("""
        SELECT s.id, s.name, s.lat, s.lon, s.country, s.river_name,
               sc.score, sc.breakdown_json, sc.scored_at,
               r.salinity_delta, r.flow_rate_m3s
        FROM sites s
        LEFT JOIN scores sc ON sc.site_id = s.id
        LEFT JOIN (
            SELECT site_id, salinity_delta, flow_rate_m3s
            FROM readings
            WHERE id IN (SELECT MAX(id) FROM readings GROUP BY site_id)
        ) r ON r.site_id = s.id
        WHERE s.id = ?
    """, (site_id,)).fetchone()

    readings = conn.execute("""
        SELECT timestamp, salinity_delta, flow_rate_m3s, source
        FROM readings WHERE site_id = ? ORDER BY timestamp
    """, (site_id,)).fetchall()

    conn.close()

    if not row:
        return None

    detail = dict(row)
    detail["readings"] = [dict(r) for r in readings]
    if detail.get("breakdown_json"):
        detail["breakdown"] = json.loads(detail["breakdown_json"])
    return detail
