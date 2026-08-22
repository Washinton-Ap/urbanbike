"""
ETL paso 22 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14/15/18/19/20/21): agrega `fecha_limite` a
urbanbike_operativa.ordenes_mantenimiento para el punto 2.7 de
docs/Plan_Mejoras_UrbanBike_V2.md ("Mantenimiento -- fecha limite de
reparacion"): una bicicleta en mantenimiento representa perdida de
ingresos mientras no este disponible, asi que cada orden real deberia
tener un plazo esperado, no solo fecha de apertura.

Primer script de `etl/` que migra una tabla de CLICKHOUSE en vez de una
coleccion de PocketBase (12-21 son todos PocketBase) -- el mecanismo es
distinto: ALTER TABLE ... ADD COLUMN IF NOT EXISTS (DDL nativo idempotente
de ClickHouse, no hace falta el patron manual de "leer schema y comparar
nombres" que usa etl/21) + ALTER TABLE ... UPDATE (mutacion sincrona) para
el backfill.

Columna nueva:
  - fecha_limite: DateTime, sentinel toDateTime('1970-01-01 00:00:00')
    para "no establecida" -- misma convencion que fecha_cierre y las
    otras 5 columnas de fecha "opcional" de este esquema (nunca
    Nullable, ver db/01_operativa_schema.sql).

Backfill real (no solo agregar la columna vacia): a la fecha de este
script existen ordenes reales sin fecha_limite (creadas antes de este
cambio). Dejarlas en el sentinel las excluiria para siempre del filtro
"vencida" de ordenes_repo.listar_vencidas() aunque llevaran meses
abiertas -- se les calcula fecha_limite = fecha_apertura + N dias segun
prioridad (mismo mapeo que ordenes_repo.PLAZO_DIAS_POR_PRIORIDAD:
alta=2, media=5, baja=10), incluidas las que ya estan 'cerrada' (para
que el historial sea consistente, aunque una orden cerrada nunca cuenta
como "vencida").

Idempotente en ambas partes: agregar columna (ADD COLUMN IF NOT EXISTS)
y backfill (solo toca filas con fecha_limite todavia en el sentinel).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db import clickhouse as ch  # noqa: E402

_TABLA = "urbanbike_operativa.ordenes_mantenimiento"
_SENTINEL = "toDateTime('1970-01-01 00:00:00')"


def _agregar_columna_si_falta() -> None:
    existe = ch.query(
        "SELECT name FROM system.columns "
        "WHERE database = 'urbanbike_operativa' AND table = 'ordenes_mantenimiento' "
        "AND name = 'fecha_limite'"
    )
    if existe:
        print("  fecha_limite: la columna ya existe, sin cambios.")
        return
    ch.command(f"""
        ALTER TABLE {_TABLA}
        ADD COLUMN IF NOT EXISTS fecha_limite DateTime DEFAULT {_SENTINEL} AFTER fecha_apertura
    """)
    print("  fecha_limite: columna agregada.")


def _backfill_fecha_limite() -> None:
    pendientes = ch.scalar(f"""
        SELECT count() FROM {_TABLA} FINAL WHERE fecha_limite = {_SENTINEL}
    """) or 0
    if not pendientes:
        print("  backfill: nada pendiente (0 ordenes reales sin fecha_limite).")
        return
    ch.get_client().command(f"""
        ALTER TABLE {_TABLA}
        UPDATE fecha_limite = fecha_apertura + INTERVAL multiIf(prioridad = 'alta', 2, prioridad = 'baja', 10, 5) DAY
        WHERE fecha_limite = {_SENTINEL}
    """, settings={"mutations_sync": 1})
    print(f"  backfill: {pendientes} orden(es) real(es) migradas (fecha_limite = fecha_apertura + dias segun prioridad).")


def main() -> None:
    print("Agregando fecha_limite a ordenes_mantenimiento...")
    _agregar_columna_si_falta()
    print("Backfill de ordenes reales existentes...")
    _backfill_fecha_limite()
    print("Listo.")


if __name__ == "__main__":
    main()
