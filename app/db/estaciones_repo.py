"""Repositorio unico de acceso a estaciones.

Fuente real (unica): urbanbike_operativa.estaciones en ClickHouse (11
filas reales). Hasta esta sesion, gerente/estaciones.html operaba 100%
contra la coleccion `estaciones` de PocketBase (9 registros, mirror
armado a mano en una sesion anterior sin ningun mecanismo real de
sincronizacion) -- mismo patron de "dos fuentes de verdad" que tenia
`tarifas` antes de conectarse a datos reales (ver docs/HOJA_DE_RUTA.md).

--------------------------------------------------------------------
PUENTE TEMPORAL hacia PocketBase (mismo patron que bicicletas_repo.py):
el flujo de reserva del ciclista y varias pantallas de vigilancia/
operacion todavia leen estaciones desde PocketBase (filtro activa=true,
resolucion por nombre) porque ese flujo no se migra hoy (ver punto 14
de la hoja de ruta). Para no romper esas pantallas, crear/actualizar/
eliminar tambien espejan un registro minimo en PocketBase (codigo/
nombre/activa/capacidad/latitud/longitud), buscado por `codigo`.

El espejo es best-effort y unidireccional (ClickHouse -> PocketBase,
nunca al reves): si la escritura en PocketBase falla, NUNCA se revierte
ni se bloquea la operacion real en ClickHouse, que ya tuvo exito antes
de intentar el espejo.
--------------------------------------------------------------------

Regla de "Eliminar" (confirmada antes de implementar, mismo criterio
que bicicletas/ordenes/promociones/tarifas): si la estacion tiene al
menos 1 bicicleta real asignada (id_estacion) o aparece como inicio/fin
de al menos 1 alquiler real, el borrado se bloquea sugiriendo cambiar
`activa` a false en su lugar; si no tiene ninguna de las dos, se borra
de verdad.
"""

from __future__ import annotations

import logging
import math
import uuid

from app.db import clickhouse as ch
from app.db.pocketbase import filter_literal, get_admin_client

logger = logging.getLogger("urbanbike.estaciones_repo")

DB = "urbanbike_operativa"

_SELECT_BASE = """
    SELECT id, codigo, nombre, direccion, latitud, longitud, capacidad, activa
    FROM urbanbike_operativa.estaciones FINAL
"""


def listar(*, q: str = "", activa: str = "", page: int = 1, per_page: int = 10) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if q:
        where.append("(nombre ILIKE %(q)s OR codigo ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if activa in ("1", "0"):
        where.append("activa = %(activa)s")
        params["activa"] = int(activa)
    where_sql = " AND ".join(where)

    total = ch.scalar(f"""
        SELECT count() FROM urbanbike_operativa.estaciones FINAL WHERE {where_sql}
    """, params) or 0

    page = max(1, page)
    total_paginas = max(1, math.ceil(total / per_page))
    page = min(page, total_paginas)
    offset = (page - 1) * per_page

    filas = ch.query(
        _SELECT_BASE + f" WHERE {where_sql} ORDER BY nombre LIMIT {per_page} OFFSET {offset}",
        params,
    )
    return filas, total


def obtener(id_estacion: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE id = %(id)s", {"id": id_estacion})
    return filas[0] if filas else None


def contar_bicicletas(id_estacion: str) -> int:
    return ch.scalar(
        "SELECT count() FROM urbanbike_operativa.bicicletas FINAL WHERE id_estacion = %(id)s",
        {"id": id_estacion},
    ) or 0


def contar_alquileres(id_estacion: str) -> int:
    """Referencias reales como estacion de inicio o de fin -- id_estacion_fin
    es String (sentinela '' si no aplica), no UUID, por eso el toUUIDOrNull."""
    return ch.scalar("""
        SELECT count() FROM urbanbike_operativa.alquileres FINAL
        WHERE id_estacion_inicio = %(id)s OR toUUIDOrNull(id_estacion_fin) = %(id)s
    """, {"id": id_estacion}) or 0


# ── Espejo best-effort hacia PocketBase (puente temporal) ───────────────────

def _espejar_pocketbase(operacion: str, codigo: str, id_ch: str, datos_pb: dict | None) -> None:
    """Nunca lanza. Un fallo aqui no debe afectar al llamador: la
    operacion real en ClickHouse ya tuvo exito antes de esta llamada."""
    try:
        pb = get_admin_client()
        existentes = pb.list_records("estaciones", filter=f'codigo = {filter_literal(codigo)}', per_page=1).get("items", [])
        if operacion == "eliminar":
            if existentes:
                pb.delete_record("estaciones", existentes[0]["id"])
        elif existentes:
            pb.update_record("estaciones", existentes[0]["id"], datos_pb)
        else:
            pb.create_record("estaciones", {"codigo": codigo, **(datos_pb or {})})
    except Exception as e:
        logger.error(
            "ESPEJO POCKETBASE FALLO (%s) codigo=%s id_clickhouse=%s error=%s -- "
            "la operacion en ClickHouse (fuente real) SI se aplico correctamente. "
            "Revisar y sincronizar el espejo a mano si hace falta.",
            operacion, codigo, id_ch, e,
        )


# ── Escritura (fuente real = ClickHouse; espejo = best-effort) ─────────────

def crear(*, codigo: str, nombre: str, direccion: str = "", latitud: float,
          longitud: float, capacidad: int, activa: bool = True) -> str:
    nuevo_id = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.estaciones
            (id, codigo, nombre, direccion, latitud, longitud, capacidad, activa)
        VALUES
            (%(id)s, %(codigo)s, %(nombre)s, %(direccion)s, %(latitud)s, %(longitud)s,
             %(capacidad)s, %(activa)s)
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "nombre": nombre, "direccion": direccion,
        "latitud": latitud, "longitud": longitud, "capacidad": capacidad,
        "activa": 1 if activa else 0,
    })
    _espejar_pocketbase("crear", codigo, nuevo_id, {
        "nombre": nombre, "activa": activa, "capacidad": capacidad,
        "latitud": latitud, "longitud": longitud,
    })
    return nuevo_id


def actualizar(id_estacion: str, *, codigo: str, nombre: str, direccion: str = "",
               latitud: float, longitud: float, capacidad: int, activa: bool) -> None:
    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.estaciones
        UPDATE codigo = %(codigo)s, nombre = %(nombre)s, direccion = %(direccion)s,
               latitud = %(latitud)s, longitud = %(longitud)s, capacidad = %(capacidad)s,
               activa = %(activa)s
        WHERE id = %(id)s
    """, parameters={
        "id": id_estacion, "codigo": codigo, "nombre": nombre, "direccion": direccion,
        "latitud": latitud, "longitud": longitud, "capacidad": capacidad,
        "activa": 1 if activa else 0,
    }, settings={"mutations_sync": 1})
    _espejar_pocketbase("actualizar", codigo, id_estacion, {
        "nombre": nombre, "activa": activa, "capacidad": capacidad,
        "latitud": latitud, "longitud": longitud,
    })


def eliminar(id_estacion: str) -> tuple[bool, str]:
    """(True, '') si se borro; (False, motivo) si esta bloqueado por
    tener bicicletas o alquileres reales asociados."""
    est = obtener(id_estacion)
    if not est:
        return False, "Estación no encontrada."

    n_bicis = contar_bicicletas(id_estacion)
    if n_bicis > 0:
        return False, (
            f"No se puede eliminar: tiene {n_bicis} bicicleta(s) real(es) asignada(s). "
            "Cambia su estado a 'Inactiva' en su lugar."
        )
    n_alquileres = contar_alquileres(id_estacion)
    if n_alquileres > 0:
        return False, (
            f"No se puede eliminar: tiene {n_alquileres} alquiler(es) real(es) asociado(s) "
            "(como estación de inicio o de fin). Cambia su estado a 'Inactiva' en su lugar."
        )

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.estaciones DELETE WHERE id = %(id)s",
        parameters={"id": id_estacion}, settings={"mutations_sync": 1},
    )
    _espejar_pocketbase("eliminar", est["codigo"], id_estacion, None)
    return True, ""
