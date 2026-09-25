"""Export every table in the Neon database to CSV for analysis.

Writes one file per table to data/exports/<schema>/<table>.csv, e.g.
    data/exports/public/fact_travel_time.csv
    data/exports/raw/gtfs_stops.csv

PostGIS geometry/geography columns are written as WKT text
(e.g. "LINESTRING(76.28 9.98, ...)") so they are readable in pandas/Excel.

Usage (from the repo root):
    python ingestion/export_to_csv.py
"""

import sys

import psycopg2
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db import REPO_ROOT, get_engine, list_tables

EXPORT_DIR = REPO_ROOT / "data" / "exports"


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def build_select(conn, schema, table):
    """SELECT every column in table order, converting spatial columns to WKT."""
    columns = conn.execute(
        text(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
            """
        ),
        {"schema": schema, "table": table},
    ).all()

    select_list = []
    for name, udt_name in columns:
        col = quote_ident(name)
        if udt_name in ("geometry", "geography"):
            select_list.append(f"ST_AsText({col}) AS {col}")
        else:
            select_list.append(col)

    return f"SELECT {', '.join(select_list)} FROM {quote_ident(schema)}.{quote_ident(table)}"


def export_table(engine, schema, table):
    out_path = EXPORT_DIR / schema / f"{table}.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with engine.connect() as conn:
        query = build_select(conn, schema, table)

    # COPY streams rows straight to the file, so large tables never sit in memory
    raw_conn = engine.raw_connection()
    try:
        with raw_conn.cursor() as cur, open(out_path, "w", encoding="utf-8", newline="") as f:
            cur.copy_expert(f"COPY ({query}) TO STDOUT WITH (FORMAT CSV, HEADER)", f)
            rows = cur.rowcount
    finally:
        raw_conn.close()

    return out_path, rows


def main():
    engine = get_engine()

    try:
        with engine.connect() as conn:
            tables = list_tables(conn)

        if not tables:
            sys.exit("No tables found to export.")

        print(f"Exporting {len(tables)} table(s) to {EXPORT_DIR.relative_to(REPO_ROOT)}/")
        for schema, table in tables:
            out_path, rows = export_table(engine, schema, table)
            print(f"  {schema}.{table:<40} {rows:>10,} rows -> {out_path.relative_to(REPO_ROOT)}")

    # The COPY runs on the raw psycopg2 cursor, so its errors aren't wrapped by SQLAlchemy
    except (SQLAlchemyError, psycopg2.Error) as exc:
        sys.exit(f"Export failed:\n  {exc.__class__.__name__}: {exc.args[0] if exc.args else exc}")

    print("Done.")


if __name__ == "__main__":
    main()
