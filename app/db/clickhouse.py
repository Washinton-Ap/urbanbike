"""Cliente para consultas analíticas contra ClickHouse."""

from __future__ import annotations

import clickhouse_connect
from app.config import settings

_client: clickhouse_connect.driver.Client | None = None


def get_client() -> clickhouse_connect.driver.Client:
    global _client
    if _client is None:
        _client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_http_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_db,
        )
    return _client


def query(sql: str, params: dict | None = None) -> list[dict]:
    """Ejecuta una consulta y devuelve una lista de dicts."""
    result = get_client().query(sql, parameters=params or {})
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]


def query_one(sql: str, params: dict | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: dict | None = None):
    """Devuelve un único valor escalar."""
    result = get_client().query(sql, parameters=params or {})
    rows = result.result_rows
    return rows[0][0] if rows else None


def command(sql: str, params: dict | None = None) -> None:
    """INSERT / DDL sin resultado -- para las filas de segmento nuevas
    (ver docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md),
    nunca UPDATE."""
    get_client().command(sql, parameters=params or {})


def ping() -> bool:
    """Prueba de conexión: SELECT 1. Devuelve True si ClickHouse responde."""
    return scalar("SELECT 1") == 1


def mapa_alquiler_por_viaje_pocketbase() -> dict[str, str]:
    """{viaje_id_pocketbase: id_alquiler} SOLO para los 38 alquileres
    reales de la migracion historica (etl/07_migrar_viajes_pagos.py) --
    origen='migracion_historica' filtra los segmentos de modalidad
    nuevos (origen='segmento_modalidad', ver
    docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md),
    que tambien usan id_origen_pocketbase pero NO deben aparecer aca:
    los 4 consumidores reales de este mapa (ciclista.py, empleado.py,
    inspecciones_repo.py) asumen un solo alquiler por viaje, exactamente
    el contrato que tenian antes de este cambio."""
    filas = query(
        "SELECT id, id_origen_pocketbase FROM urbanbike_operativa.alquileres FINAL "
        "WHERE id_origen_pocketbase != '' AND origen = 'migracion_historica'"
    )
    return {f["id_origen_pocketbase"]: str(f["id"]) for f in filas}

