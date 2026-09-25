"""Shared Neon Postgres connection helpers for the ingestion scripts."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

# Each setting can use our names (.env.example) or the names Neon's
# "Connect" dialog generates (PGHOST, PGUSER, ...)
VAR_NAMES = {
    "host": ["POSTGRES_HOST", "PGHOST"],
    "port": ["POSTGRES_PORT", "PGPORT"],
    "database": ["POSTGRES_DB", "PGDATABASE"],
    "username": ["POSTGRES_USER", "PGUSER"],
    "password": ["POSTGRES_PASSWORD", "PGPASSWORD"],
}

# Schemas that belong to Postgres / Neon / PostGIS rather than our data
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "tiger", "tiger_data", "topology")


def first_set(names):
    return next((os.getenv(name) for name in names if os.getenv(name)), None)


def get_engine():
    if not ENV_PATH.exists():
        sys.exit(f"No .env file at {ENV_PATH}. Copy .env.example to .env and fill it in.")
    load_dotenv(ENV_PATH)

    # A full connection string wins if present
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        url = make_url(database_url).set(drivername="postgresql+psycopg2")
    else:
        values = {key: first_set(names) for key, names in VAR_NAMES.items()}
        values["port"] = values["port"] or "5432"

        missing = [" / ".join(VAR_NAMES[key]) for key, value in values.items() if not value]
        if missing:
            sys.exit(
                f"Loaded {ENV_PATH} but these values are missing or empty:\n  "
                + "\n  ".join(missing)
                + "\nAlternatively set DATABASE_URL to the full Neon connection string."
            )

        # URL.create escapes special characters in the password
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=values["username"],
            password=values["password"],
            host=values["host"],
            port=int(values["port"]),
            database=values["database"],
        )

    # Neon only accepts SSL connections
    return create_engine(url, connect_args={"sslmode": "require", "connect_timeout": 10})


def list_tables(conn):
    """Return (schema, table) pairs for every user table, excluding PostGIS metadata."""
    return conn.execute(
        text(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN :system_schemas
              AND table_name <> 'spatial_ref_sys'
            ORDER BY table_schema, table_name
            """
        ),
        {"system_schemas": SYSTEM_SCHEMAS},
    ).all()
