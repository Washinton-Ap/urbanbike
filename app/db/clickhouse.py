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

