"""Check that the Neon Postgres credentials in .env work.

Connects, prints server details, and lists every user table with its row count.

Usage (from the repo root):
    python ingestion/check_connection.py
"""

import sys

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import get_engine, list_tables


def main():
    engine = get_engine()

    try:
        with engine.connect() as conn:
            info = conn.execute(
                text("SELECT current_database(), current_user, version()")
            ).one()
            print("Connected to Neon")
            print(f"  Database: {info[0]}")
            print(f"  User:     {info[1]}")
            print(f"  Server:   {info[2].split(',')[0]}")

            tables = list_tables(conn)
            if not tables:
                print("\nNo tables found. Check that POSTGRES_DB is the database you ingested into.")
                return

            print(f"\n{len(tables)} table(s):")
            for schema, table in tables:
                count = conn.execute(
                    text(f'SELECT count(*) FROM "{schema}"."{table}"')
                ).scalar()
                print(f"  {schema}.{table:<40} {count:>10,} rows")

    except SQLAlchemyError as exc:
        sys.exit(f"Connection failed:\n  {exc.__class__.__name__}: {exc.args[0] if exc.args else exc}")


if __name__ == "__main__":
    main()
