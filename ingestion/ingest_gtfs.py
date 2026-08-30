"""
One-time load of the official KMRL GTFS feed (extracted .txt/CSV files)
into raw.gtfs_* tables in Neon PostgreSQL.

Only loads files relevant to the project's scope (per data dictionary):
agency, stops, routes, trips, stop_times, calendar, shapes.
Re-running replaces each table's contents (static reference data).
"""

import logging
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "gtfs_ingest.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

GTFS_DIR = Path(__file__).resolve().parent.parent / "data" / "gtfs" / "extracted"

# Maps GTFS filename -> target table name. Only in-scope files listed.
GTFS_FILES = {
    "agency.txt": "gtfs_agency",
    "stops.txt": "gtfs_stops",
    "routes.txt": "gtfs_routes",
    "trips.txt": "gtfs_trips",
    "stop_times.txt": "gtfs_stop_times",
    "calendar.txt": "gtfs_calendar",
    "shapes.txt": "gtfs_shapes",
}


def load_db_url() -> str:
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not found in .env")
    return db_url


def load_gtfs_file(engine, filename: str, table_name: str) -> int:
    """Read one GTFS file and load it into its raw.gtfs_* table."""
    file_path = GTFS_DIR / filename
    if not file_path.exists():
        logger.warning("%s not found, skipping.", filename)
        return 0

    df = pd.read_csv(file_path)
    df.to_sql(table_name, engine, schema="raw", if_exists="replace", index=False)
    logger.info("Loaded %s -> raw.%s (%d rows)", filename, table_name, len(df))
    return len(df)


def main() -> None:
    logger.info("Starting GTFS load...")
    db_url = load_db_url()
    engine = create_engine(db_url)

    total_rows = 0
    for filename, table_name in GTFS_FILES.items():
        total_rows += load_gtfs_file(engine, filename, table_name)

    logger.info("GTFS load complete: %d total rows across %d tables.",
                total_rows, len(GTFS_FILES))


if __name__ == "__main__":
    main()