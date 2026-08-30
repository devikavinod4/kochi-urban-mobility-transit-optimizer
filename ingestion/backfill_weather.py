"""
One-time backfill of historical hourly weather data for Kochi from
Open-Meteo's Historical Weather API (ERA5 reanalysis), covering the
same date range as existing traffic collection.

Run once. Re-running is safe (idempotent) due to the UNIQUE constraint
on observation_time.
"""

import json
import logging
import os
from datetime import date, timedelta
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
        logging.FileHandler(LOG_DIR / "weather_backfill.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

KOCHI_LAT = 9.9312
KOCHI_LON = 76.2673
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Match the start of your traffic data collection
BACKFILL_START = date(2026, 8, 17)
# Archive data has a short reporting lag; yesterday is safely available
BACKFILL_END = date.today() - timedelta(days=1)


def load_db_url() -> str:
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in .env")
    return db_url


def fetch_historical_weather(start: date, end: date) -> dict:
    """Fetch hourly temperature and precipitation for the given date range."""
    params = {
        "latitude": KOCHI_LAT,
        "longitude": KOCHI_LON,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": "temperature_2m,precipitation",
        "timezone": "Asia/Kolkata",
    }
    response = requests.get(ARCHIVE_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def insert_hourly_rows(conn, hourly: dict) -> int:
    """Insert each hourly observation; returns count of new rows inserted."""
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
    logger.info("Starting historical weather backfill: %s to %s", BACKFILL_START, BACKFILL_END)
    db_url = load_db_url()

    data = fetch_historical_weather(BACKFILL_START, BACKFILL_END)
    hourly = data["hourly"]
    total_hours = len(hourly["time"])
    logger.info("Fetched %d hourly observations from Open-Meteo archive.", total_hours)

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        inserted = insert_hourly_rows(conn, hourly)
    finally:
        conn.close()

    logger.info("Backfill complete: %d/%d new rows inserted (rest already existed).",
                inserted, total_hours)


if __name__ == "__main__":
    main()