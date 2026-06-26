"""
ETL paso 2: Crea las tablas en ClickHouse y carga los Parquet generados en el paso 1.
Los archivos Parquet deben estar en data/parquet/ (montado en el contenedor
como /var/lib/clickhouse/user_files/parquet/).
"""

import os
import sys
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

load_dotenv()

SQL_DIR  = Path(__file__).parent / "sql"
OUT_DIR  = Path(__file__).parent.parent / "data" / "parquet"

PARQUET_FILES = [
    ("dim_tipos_bicicleta", "urbanbike.dim_tipos_bicicleta"),
    ("dim_membresia",       "urbanbike.dim_membresia"),
    ("dim_estaciones",      "urbanbike.dim_estaciones"),
    ("dim_tiempo",          "urbanbike.dim_tiempo"),
    ("fact_viajes",         "urbanbike.fact_viajes"),
]


def get_client():
    return clickhouse_connect.get_client(
        host     = os.getenv("CLICKHOUSE_HOST", "localhost"),
        port     = int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username = os.getenv("CLICKHOUSE_USER", "default"),
        password = os.getenv("CLICKHOUSE_PASSWORD", ""),
        database = "default",
    )


def run_sql_file(client, path: Path):
    sql = path.read_text(encoding="utf-8")
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            client.command(stmt)
    print(f"  OK: {path.name}")


def load_parquet(client, parquet_name: str, table: str):
    parquet_path = f"parquet/{parquet_name}.parquet"
    sql = f"""
        INSERT INTO {table}
        SELECT * FROM file('{parquet_path}', Parquet)
    """
    client.command(sql)
    count = client.command(f"SELECT COUNT() FROM {table}")
    print(f"  {table:45s} -> {count:>10,} filas cargadas")


def main():
    print("Conectando a ClickHouse...")
    client = get_client()
    version = client.command("SELECT version()")
    print(f"  ClickHouse {version} OK\n")

    print("Creando base de datos y tablas dimensionales...")
    run_sql_file(client, SQL_DIR / "01_dimensiones.sql")

    print("\nCreando tabla de hechos...")
    run_sql_file(client, SQL_DIR / "02_hechos.sql")

    print("\nCargando Parquet en ClickHouse:")
    missing = [p for p, _ in PARQUET_FILES if not (OUT_DIR / f"{p}.parquet").exists()]
    if missing:
        print(f"ERROR: Parquet faltantes: {missing}")
        print("Ejecuta primero: python etl/01_extract_to_parquet.py")
        sys.exit(1)

    for parquet_name, table in PARQUET_FILES:
        load_parquet(client, parquet_name, table)

    print("\nPaso 2 completado. Datos listos en ClickHouse.")


if __name__ == "__main__":
    main()
