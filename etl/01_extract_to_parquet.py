"""
ETL paso 1: Lee CSVs de Citibike, limpia los datos y genera archivos Parquet
con las tablas dimensionales y la tabla de hechos.
"""

import sys
from pathlib import Path

import duckdb

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
OUT_DIR = Path(__file__).parent.parent / "data" / "parquet"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    csv_files = list(RAW_DIR.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: No se encontraron CSV en {RAW_DIR}")
        sys.exit(1)

    print(f"Archivos encontrados: {[f.name for f in csv_files]}")

    con = duckdb.connect()

    # Carga y limpieza de todos los CSV en una sola relación
    raw_path = str(RAW_DIR / "*.csv")
    con.execute(f"""
        CREATE OR REPLACE VIEW raw AS
        SELECT *
        FROM read_csv(
            '{raw_path}',
            columns = {{
                'ride_id':             'VARCHAR',
                'rideable_type':       'VARCHAR',
                'started_at':          'TIMESTAMP',
                'ended_at':            'TIMESTAMP',
                'start_station_name':  'VARCHAR',
                'start_station_id':    'VARCHAR',
                'end_station_name':    'VARCHAR',
                'end_station_id':      'VARCHAR',
                'start_lat':           'DOUBLE',
                'start_lng':           'DOUBLE',
                'end_lat':             'DOUBLE',
                'end_lng':             'DOUBLE',
                'member_casual':       'VARCHAR'
            }},
            nullstr = '',
            ignore_errors = true
        )
        WHERE
            start_station_id IS NOT NULL
            AND end_station_id   IS NOT NULL
            AND end_lat          IS NOT NULL
            AND end_lng          IS NOT NULL
            AND ended_at > started_at
            AND date_diff('minute', started_at, ended_at) > 0
            AND date_diff('minute', started_at, ended_at) <= 1440
    """)

    total = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
    print(f"Filas limpias: {total:,}")

    # ── dim_tipos_bicicleta ─────────────────────────────────────────────
    print("Generando dim_tipos_bicicleta...")
    con.execute("""
        COPY (
            SELECT
                ROW_NUMBER() OVER (ORDER BY rideable_type)::UTINYINT AS id_tipo,
                rideable_type AS nombre,
                CASE rideable_type
                    WHEN 'electric_bike' THEN 'Bicicleta eléctrica'
                    WHEN 'classic_bike'  THEN 'Bicicleta clásica'
                    ELSE 'Otro'
                END AS descripcion
            FROM (SELECT DISTINCT rideable_type FROM raw)
        ) TO 'data/parquet/dim_tipos_bicicleta.parquet' (FORMAT PARQUET)
    """)

    # ── dim_membresia ───────────────────────────────────────────────────
    print("Generando dim_membresia...")
    con.execute("""
        COPY (
            SELECT
                ROW_NUMBER() OVER (ORDER BY member_casual)::UTINYINT AS id_membresia,
                member_casual AS tipo
            FROM (SELECT DISTINCT member_casual FROM raw)
        ) TO 'data/parquet/dim_membresia.parquet' (FORMAT PARQUET)
    """)

    # ── dim_estaciones ──────────────────────────────────────────────────
    print("Generando dim_estaciones...")
    con.execute("""
        COPY (
            SELECT
                id_estacion,
                nombre_estacion,
                AVG(lat) AS latitud,
                AVG(lng) AS longitud
            FROM (
                SELECT start_station_id AS id_estacion,
                       start_station_name AS nombre_estacion,
                       start_lat AS lat, start_lng AS lng
                FROM raw
                UNION ALL
                SELECT end_station_id, end_station_name, end_lat, end_lng
                FROM raw
            )
            GROUP BY id_estacion, nombre_estacion
        ) TO 'data/parquet/dim_estaciones.parquet' (FORMAT PARQUET)
    """)

    # ── dim_tiempo ──────────────────────────────────────────────────────
    print("Generando dim_tiempo...")
    con.execute("""
        COPY (
            SELECT DISTINCT
                fecha,
                YEAR(fecha)::USMALLINT        AS anio,
                MONTH(fecha)::UTINYINT         AS mes,
                DAY(fecha)::UTINYINT           AS dia,
                ISODOW(fecha)::UTINYINT        AS dia_semana,
                DAYNAME(fecha)                 AS nombre_dia,
                MONTHNAME(fecha)               AS nombre_mes,
                (ISODOW(fecha) >= 6)::UTINYINT AS es_fin_semana
            FROM (
                SELECT started_at::DATE AS fecha FROM raw
            )
            ORDER BY fecha
        ) TO 'data/parquet/dim_tiempo.parquet' (FORMAT PARQUET)
    """)

    # ── fact_viajes ─────────────────────────────────────────────────────
    print("Generando fact_viajes (puede tardar unos minutos)...")
    con.execute("""
        COPY (
            SELECT
                r.ride_id,
                t.id_tipo::UTINYINT                                       AS id_tipo_bicicleta,
                r.started_at                                               AS fecha_inicio,
                r.ended_at                                                 AS fecha_fin,
                r.start_station_id                                         AS id_estacion_inicio,
                r.end_station_id                                           AS id_estacion_fin,
                r.start_lat                                                AS lat_inicio,
                r.start_lng                                                AS lng_inicio,
                r.end_lat                                                  AS lat_fin,
                r.end_lng                                                  AS lng_fin,
                m.id_membresia::UTINYINT                                   AS id_membresia,
                date_diff('second', r.started_at, r.ended_at) / 60.0      AS duracion_min,
                -- Haversine distance en km
                2 * 6371 * ASIN(SQRT(
                    POWER(SIN(RADIANS(r.end_lat  - r.start_lat)  / 2), 2) +
                    COS(RADIANS(r.start_lat)) * COS(RADIANS(r.end_lat)) *
                    POWER(SIN(RADIANS(r.end_lng  - r.start_lng)  / 2), 2)
                ))                                                         AS distancia_km
            FROM raw r
            JOIN (SELECT rideable_type, ROW_NUMBER() OVER (ORDER BY rideable_type)::UTINYINT AS id_tipo
                  FROM (SELECT DISTINCT rideable_type FROM raw)) t
                ON r.rideable_type = t.rideable_type
            JOIN (SELECT member_casual, ROW_NUMBER() OVER (ORDER BY member_casual)::UTINYINT AS id_membresia
                  FROM (SELECT DISTINCT member_casual FROM raw)) m
                ON r.member_casual = m.member_casual
        ) TO 'data/parquet/fact_viajes.parquet' (
            FORMAT PARQUET,
            ROW_GROUP_SIZE 100000
        )
    """)

    print("\nParquet generados en data/parquet/:")
    for f in sorted(OUT_DIR.glob("*.parquet")):
        size_mb = f.stat().st_size / 1_048_576
        print(f"  {f.name:40s} {size_mb:6.1f} MB")

    print("\nPaso 1 completado.")


if __name__ == "__main__":
    main()
