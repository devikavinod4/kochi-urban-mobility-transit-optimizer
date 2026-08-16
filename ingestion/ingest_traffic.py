"""
Ingest live traffic data from TomTom Routing API for all configured
OD pairs (both directions), storing summary metrics in Neon PostgreSQL.

Deduplicates route geometry via content hashing (raw.route_variants)
to avoid storing repeated polylines on every poll.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg2
import requests
import yaml
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TOMTOM_ROUTE_URL = (
    "https://api.tomtom.com/routing/1/calculateRoute/"
    "{origin_lat},{origin_lon}:{dest_lat},{dest_lon}/json"
)
REQUEST_TIMEOUT_SECONDS = 15
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "od_pairs.yaml"


def load_env() -> dict[str, str]:
    """Load required environment variables from .env, fail fast if missing."""
    load_dotenv()
    api_key = os.getenv("TOMTOM_API_KEY")
    db_url = os.getenv("DATABASE_URL")
    if not api_key:
        raise RuntimeError("TOMTOM_API_KEY not found in .env")
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in .env")
    logger.info("Environment variables loaded successfully.")
    return {"tomtom_api_key": api_key, "database_url": db_url}


def load_od_pairs(config_path: Path = CONFIG_PATH) -> list[dict[str, Any]]:
    """
    Parse od_pairs.yaml into a flat list of pollable legs.

    Each pair produces TWO legs (forward + reverse), matching the
    864 calls/day design documented in the YAML itself.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    legs = []
    for corridor in raw_config["corridors"]:
        for pair in corridor["pairs"]:
            base_id = f"{corridor['id']}_{pair['id']}"
            legs.append({
                "corridor_id": f"{base_id}_fwd",
                "label": pair["label"],
                "origin": pair["origin"],
                "destination": pair["destination"],
            })
            legs.append({
                "corridor_id": f"{base_id}_rev",
                "label": f"{pair['label']} (reverse)",
                "origin": pair["destination"],
                "destination": pair["origin"],
            })
    logger.info("Loaded %d legs from %d corridors.", len(legs), len(raw_config["corridors"]))
    return legs


def call_tomtom(origin: dict, destination: dict, api_key: str) -> dict[str, Any] | None:
    """
    Call TomTom's calculateRoute endpoint for one origin-destination leg.

    Returns the parsed JSON response, or None if the call failed after
    retries (a single leg's failure should never crash the whole run).
    """
    url = TOMTOM_ROUTE_URL.format(
        origin_lat=origin["lat"], origin_lon=origin["lon"],
        dest_lat=destination["lat"], dest_lon=destination["lon"],
    )
    params = {"key": api_key, "traffic": "true", "travelMode": "car"}

    for attempt in (1, 2):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("TomTom call failed (attempt %d/2): %s", attempt, exc)
    return None


def compute_geometry_hash(points: list[dict[str, float]]) -> str:
    """Hash the route's coordinate list to a short fingerprint for dedup."""
    serialized = json.dumps(points, sort_keys=False)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def points_to_linestring_wkt(points: list[dict[str, float]]) -> str:
    """Convert TomTom's points list into PostGIS WKT (note: lon before lat)."""
    coords = ", ".join(f"{p['longitude']} {p['latitude']}" for p in points)
    return f"LINESTRING({coords})"


def get_or_create_route_variant(
    conn, corridor_id: str, geometry_hash: str, wkt: str, length_meters: int
) -> int:
    """
    Look up an existing route_variant by (corridor_id, geometry_hash);
    insert a new one only if this exact geometry hasn't been seen before.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.route_variants
                (corridor_id, geometry_hash, route_geometry, length_meters)
            VALUES (%s, %s, ST_GeomFromText(%s, 4326), %s)
            ON CONFLICT (corridor_id, geometry_hash) DO NOTHING
            RETURNING route_variant_id;
            """,
            (corridor_id, geometry_hash, wkt, length_meters),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute(
            """
            SELECT route_variant_id FROM raw.route_variants
            WHERE corridor_id = %s AND geometry_hash = %s;
            """,
            (corridor_id, geometry_hash),
        )
        return cur.fetchone()[0]


def insert_snapshot(conn, corridor_id: str, pulled_at: datetime, summary: dict,
                     route_variant_id: int) -> bool:
    """Insert one traffic snapshot; returns False if it was a duplicate."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO raw.traffic_snapshots
                (corridor_id, pulled_at, travel_time_seconds, traffic_delay_seconds,
                 length_meters, traffic_length_meters, route_variant_id, raw_summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (corridor_id, pulled_at) DO NOTHING
            RETURNING snapshot_id;
            """,
            (
                corridor_id, pulled_at,
                summary["travelTimeInSeconds"], summary["trafficDelayInSeconds"],
                summary["lengthInMeters"], summary["trafficLengthInMeters"],
                route_variant_id, json.dumps(summary),
            ),
        )
        return cur.fetchone() is not None


def process_leg(conn, leg: dict[str, Any], api_key: str, pulled_at: datetime) -> bool:
    """Run one full leg: call TomTom, dedup geometry, insert snapshot."""
    response = call_tomtom(leg["origin"], leg["destination"], api_key)
    if response is None:
        logger.error("Skipping %s — TomTom call failed.", leg["corridor_id"])
        return False

    route = response["routes"][0]
    summary = route["summary"]
    points = route["legs"][0]["points"]

    geometry_hash = compute_geometry_hash(points)
    wkt = points_to_linestring_wkt(points)
    route_variant_id = get_or_create_route_variant(
        conn, leg["corridor_id"], geometry_hash, wkt, summary["lengthInMeters"]
    )
    inserted = insert_snapshot(conn, leg["corridor_id"], pulled_at, summary, route_variant_id)

    if inserted:
        logger.info(
            "%-12s OK — %d sec (delay %ds), variant #%d",
            leg["corridor_id"], summary["travelTimeInSeconds"],
            summary["trafficDelayInSeconds"], route_variant_id,
        )
    else:
        logger.warning("%s — duplicate snapshot skipped.", leg["corridor_id"])
    return inserted


def main() -> None:
    """Run one full polling cycle across all 18 legs."""
    logger.info("Starting traffic ingestion run...")
    env = load_env()
    legs = load_od_pairs()
    pulled_at = datetime.now(timezone.utc)

    conn = psycopg2.connect(env["database_url"])
    conn.autocommit = True

    success_count = 0
    try:
        for leg in legs:
            if process_leg(conn, leg, env["tomtom_api_key"], pulled_at):
                success_count += 1
    finally:
        conn.close()

    logger.info("Run complete: %d/%d legs stored successfully.", success_count, len(legs))


if __name__ == "__main__":
    main()