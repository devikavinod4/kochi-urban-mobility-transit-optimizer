"""
Ingest current hourly weather data for Kochi from Open-Meteo's live
Forecast API, storing into raw.weather_hourly (same table used by
the historical backfill).

Designed to run hourly via GitHub Actions. Idempotent via the
UNIQUE(observation_time) constraint.
"""

import json
import logging
import os
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "weather_ingest.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

KOCHI_LAT = 9.9312
KOCHI_LON = 76.2673
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def load_db_url() -> str:
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in .env")
    return db_url


def fetch_current_weather() -> dict:
    """
    Fetch today's hourly forecast (includes the current/most recent hour
    with observed-quality data blended in, per Open-Meteo's model).
    """
    params = {
        "latitude": KOCHI_LAT,
        "longitude": KOCHI_LON,
        "hourly": "temperature_2m,precipitation",
        "timezone": "Asia/Kolkata",
        "past_days": 1,   # ensures the just-completed hour is included
        "forecast_days": 1,
    }
    response = requests.get(FORECAST_URL, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def insert_hourly_rows(conn, hourly: dict) -> int:
    """Insert each hourly row; ON CONFLICT skips hours already stored."""
    times = hourly["time"]
    temps = hourly["temperature_2m"]
    precip = hourly["precipitation"]

    inserted = 0
    with conn.cursor() as cur:
        for t, temp, rain in zip(times, temps, precip):
            record = {"time": t, "temperature_2m": temp, "precipitation": rain}
            cur.execute(
                """
                INSERT INTO raw.weather_hourly
                    (observation_time, temperature_celsius, precipitation_mm, raw_response)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (observation_time) DO NOTHING
                RETURNING weather_id;
                """,
                (t, temp, rain, json.dumps(record)),
            )
            if cur.fetchone() is not None:
                inserted += 1
    return inserted


def main() -> None:
    logger.info("Starting hourly weather ingestion run...")
    db_url = load_db_url()

    data = fetch_current_weather()
    hourly = data["hourly"]
    logger.info("Fetched %d hourly rows from Open-Meteo forecast API.", len(hourly["time"]))

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        inserted = insert_hourly_rows(conn, hourly)
    finally:
        conn.close()

    logger.info("Run complete: %d new row(s) inserted.", inserted)


if __name__ == "__main__":
    main()