"""Repositorio unico de acceso a ordenes de mantenimiento.

Fuente real: urbanbike_operativa.ordenes_mantenimiento en ClickHouse.
Migradas el 30-jul-2026 las 4 ordenes reales que existian en PocketBase
(ordenes_mant, todas 'completado' -> 'cerrada' aqui); el mapeo de
origen/tipo_falla/tecnico quedo documentado y aprobado antes de migrar
(ver docs/HOJA_DE_RUTA.md). La fila 'OM-0311' es un residuo huerfano del
seed original (bicicleta fantasma), no una orden real -- no se toca.

ORDER BY corregido el 30-jul-2026: la tabla tenia
ORDER BY (estado_reparacion, prioridad, fecha_apertura), mismo bug que
bicicletas/alquileres (estado_reparacion es mutable). Se recreo con
ORDER BY id antes de construir este repositorio.

'Eliminar' solo borra de verdad si la orden sigue 'abierta' Y no tiene
repuestos reales consumidos (orden_repuesto) -- no se debe perder
evidencia de un trabajo ya en curso o con costo real asociado.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

from app.db import clickhouse as ch

DB = "urbanbike_operativa"
ESTADOS_VALIDOS = ("abierta", "diagnostico", "en_reparacion", "espera_repuesto", "cerrada")
ORIGENES_VALIDOS = ("preventivo", "devolucion", "reporte", "inspeccion")
TIPOS_FALLA_VALIDOS = ("frenos", "transmision", "neumatico", "electrico", "estructural", "otro")
PRIORIDADES_VALIDAS = ("alta", "media", "baja")

# Punto 2.7 del plan de mejoras: plazo esperado de reparacion segun
# prioridad -- una bicicleta en mantenimiento representa perdida de
# ingresos mientras no este disponible. Valores de negocio razonables,
# no confirmados formalmente por Washington todavia (facil de ajustar,
# un solo dict).
PLAZO_DIAS_POR_PRIORIDAD = {"alta": 2, "media": 5, "baja": 10}


def _fecha_limite_por_defecto(prioridad: str, desde: datetime) -> datetime:
    """Plazo por defecto = fecha de apertura + dias segun prioridad
    (PLAZO_DIAS_POR_PRIORIDAD, default 5 si la prioridad no esta
    mapeada -- no deberia pasar, PRIORIDADES_VALIDAS ya la valida antes)."""
    from datetime import timedelta
    dias = PLAZO_DIAS_POR_PRIORIDAD.get(prioridad, 5)
    return desde + timedelta(days=dias)


def listar_tecnicos() -> list[dict]:
    """[{id, nombre}] para el <select> de tecnico -- solo usuarios rol=mantenimiento."""
    return ch.query("""
        SELECT id, concat(nombre, ' ', apellido) AS nombre
        FROM urbanbike_operativa.usuarios FINAL
        WHERE rol = 'mantenimiento' ORDER BY nombre
    """)


def tecnico_con_menos_carga() -> str | None:
    """id del tecnico real (rol=mantenimiento) con menos ordenes abiertas
    (estado_reparacion != 'cerrada') hoy -- usado para generar automatico
    una orden real sin obligar a vigilancia a elegir tecnico (Nivel 3,
    ver docs/HOJA_DE_RUTA.md seccion 23). id_tecnico es obligatorio en el
    esquema y ordenes_repo.listar() hace INNER JOIN contra usuarios por
    ese campo -- una orden sin tecnico real quedaria invisible en el
    panel de mantenimiento, el mismo tipo de bug que se esta corrigiendo
    aqui. Reasignable despues desde el WorkPanel como cualquier orden."""
    filas = ch.query("""
        SELECT t.id AS id, count(o.id) AS abiertas
        FROM urbanbike_operativa.usuarios t FINAL
        LEFT JOIN urbanbike_operativa.ordenes_mantenimiento o FINAL
            ON o.id_tecnico = t.id AND o.estado_reparacion != 'cerrada'
        WHERE t.rol = 'mantenimiento'
        GROUP BY t.id, t.nombre
        ORDER BY abiertas ASC, t.nombre ASC
        LIMIT 1
    """)
    return str(filas[0]["id"]) if filas else None


_SELECT_BASE = """
    SELECT o.id AS id, o.codigo AS codigo, o.origen AS origen,
           o.tipo_falla AS tipo_falla, o.prioridad AS prioridad,
           o.estado_reparacion AS estado_reparacion, o.diagnostico AS diagnostico,
           o.fecha_apertura AS fecha_apertura, o.fecha_limite AS fecha_limite, o.fecha_cierre AS fecha_cierre,
           o.costo_repuestos AS costo_repuestos, o.costo_mano_obra AS costo_mano_obra,
           b.id AS id_bicicleta, b.codigo AS bicicleta_codigo,
           t.id AS id_tecnico, concat(t.nombre, ' ', t.apellido) AS tecnico_nombre
    FROM urbanbike_operativa.ordenes_mantenimiento o FINAL
    INNER JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = o.id_bicicleta
    INNER JOIN urbanbike_operativa.usuarios t FINAL ON t.id = o.id_tecnico
"""


def listar(*, q: str = "", estado: str = "", tecnico: str = "", prioridad: str = "",
           vencida: bool = False, page: int = 1, per_page: int = 10) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if q:
        where.append("(o.codigo ILIKE %(q)s OR b.codigo ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if estado:
        where.append("o.estado_reparacion = %(estado)s")
        params["estado"] = estado
    if tecnico:
        where.append("o.id_tecnico = %(tecnico)s")
        params["tecnico"] = tecnico
    if prioridad:
        where.append("o.prioridad = %(prioridad)s")
        params["prioridad"] = prioridad
    if vencida:
        # Punto 2.7: 'vencida' = no cerrada Y su plazo ya paso. El
        # guard fecha_limite > sentinel es defensivo (deberia ser
        # imposible tras el backfill de etl/22, pero evita falsos
        # positivos si alguna fila quedara sin migrar).
        where.append("o.estado_reparacion != 'cerrada' AND o.fecha_limite > toDateTime('1970-01-01 00:00:00') AND o.fecha_limite < now()")
    where_sql = " AND ".join(where)

    total = ch.scalar(f"""
        SELECT count() FROM urbanbike_operativa.ordenes_mantenimiento o FINAL
        INNER JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = o.id_bicicleta
        WHERE {where_sql}
    """, params) or 0

    page = max(1, page)
    total_paginas = max(1, math.ceil(total / per_page))
    page = min(page, total_paginas)
    offset = (page - 1) * per_page

    filas = ch.query(
        _SELECT_BASE + f" WHERE {where_sql} ORDER BY o.fecha_apertura DESC LIMIT {per_page} OFFSET {offset}",
        params,
    )
    return filas, total


def obtener(id_orden: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE o.id = %(id)s", {"id": id_orden})
    return filas[0] if filas else None


def obtener_mas_reciente_por_bicicleta(codigo_bicicleta: str) -> dict | None:
    """La orden real más reciente (cualquier estado) de esa bicicleta por
    código -- usada por empleado/mantenimiento/bicicletas.html (punto 28
    del Plan V3, Prioridad 0.6) para enlazar cada fila a su orden real en
    vez de dejarla como tabla de solo lectura sin ninguna acción."""
    filas = ch.query(
        _SELECT_BASE + " WHERE b.codigo = %(codigo)s ORDER BY o.fecha_apertura DESC LIMIT 1",
        {"codigo": codigo_bicicleta},
    )
    return filas[0] if filas else None


def bicicleta_id_por_codigo(codigo: str) -> str | None:
    """id real de ClickHouse (urbanbike_operativa.bicicletas) para un
    código -- para preseleccionar la bicicleta al crear una orden nueva
    desde una pantalla que solo conoce el código (ver el mismo punto de
    arriba)."""
    fila = ch.query(
        "SELECT id FROM urbanbike_operativa.bicicletas FINAL WHERE codigo = %(codigo)s LIMIT 1",
        {"codigo": codigo},
    )
    return str(fila[0]["id"]) if fila else None


def listar_cerradas_pendientes_certificar() -> list[dict]:
    """Ordenes que Mantenimiento ya cerro (estado_reparacion='cerrada')
    pero cuya bicicleta sigue en 'mantenimiento' -- la cola real que
    Vigilancia certifica antes de liberar la bicicleta a 'disponible'
    (ver docs/HOJA_DE_RUTA.md: esta pantalla leia hasta ahora la
    coleccion huerfana `ordenes_mant` de PocketBase, desconectada de
    esta tabla desde la migracion del 30-jul-2026). En cuanto Vigilancia
    certifica y bicicletas_repo mueve la bicicleta a 'disponible', la
    orden deja de aparecer aqui sola -- no hace falta una columna nueva
    de 'certificada'."""
    return ch.query(_SELECT_BASE + """
        WHERE o.estado_reparacion = 'cerrada' AND b.estado = 'mantenimiento'
        ORDER BY o.fecha_cierre DESC
    """)


def listar_vencidas() -> list[dict]:
    """Ordenes reales que siguen abiertas (cualquier estado != 'cerrada')
    y ya pasaron su fecha_limite -- la cola real de perdida de ingresos
    activa que motiva el punto 2.7 del plan de mejoras. Usada por la
    tarjeta "Ordenes vencidas" del dashboard de Mantenimiento."""
    return ch.query(_SELECT_BASE + """
        WHERE o.estado_reparacion != 'cerrada'
          AND o.fecha_limite > toDateTime('1970-01-01 00:00:00')
          AND o.fecha_limite < now()
        ORDER BY o.fecha_limite ASC
    """)


def contar_repuestos(id_orden: str) -> int:
    return ch.scalar(
        "SELECT count() FROM urbanbike_operativa.orden_repuesto WHERE id_orden = %(id)s",
        {"id": id_orden},
    ) or 0


def _siguiente_codigo() -> str:
    maximo = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 4))) FROM urbanbike_operativa.ordenes_mantenimiento FINAL "
        "WHERE codigo LIKE 'OM-%'"
    ) or 0
    return f"OM-{maximo + 1:04d}"


def crear(*, id_bicicleta: str, origen: str, tipo_falla: str, prioridad: str,
          id_tecnico: str, diagnostico: str, fecha_limite: datetime | None = None) -> str:
    nuevo_id = str(uuid.uuid4())
    codigo = _siguiente_codigo()
    ahora = datetime.now()
    if fecha_limite is None:
        fecha_limite = _fecha_limite_por_defecto(prioridad, ahora)
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.ordenes_mantenimiento
            (id, codigo, id_bicicleta, origen, tipo_falla, prioridad, estado_reparacion,
             id_tecnico, diagnostico, fecha_apertura, fecha_limite)
        VALUES
            (%(id)s, %(codigo)s, %(id_bicicleta)s, %(origen)s, %(tipo_falla)s, %(prioridad)s,
             'abierta', %(id_tecnico)s, %(diagnostico)s, %(ahora)s, %(fecha_limite)s)
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "id_bicicleta": id_bicicleta, "origen": origen,
        "tipo_falla": tipo_falla, "prioridad": prioridad, "id_tecnico": id_tecnico,
        "diagnostico": diagnostico, "ahora": ahora, "fecha_limite": fecha_limite,
    })
    return nuevo_id


def actualizar(id_orden: str, *, id_bicicleta: str, origen: str, tipo_falla: str,
               prioridad: str, estado_reparacion: str, id_tecnico: str, diagnostico: str,
               costo_repuestos: float, costo_mano_obra: float, fecha_limite: datetime) -> None:
    # ALTER ... UPDATE (mutacion in-place): ver nota de ORDER BY al inicio del
    # archivo -- esta tabla tenia estado_reparacion en la clave de orden hasta
    # que se corrigio hoy, mismo bug que bicicletas.estado.
    orden_actual = obtener(id_orden)
    sets = [
        "id_bicicleta = %(id_bicicleta)s", "origen = %(origen)s", "tipo_falla = %(tipo_falla)s",
        "prioridad = %(prioridad)s", "estado_reparacion = %(estado_reparacion)s",
        "id_tecnico = %(id_tecnico)s", "diagnostico = %(diagnostico)s",
        "costo_repuestos = %(costo_repuestos)s", "costo_mano_obra = %(costo_mano_obra)s",
        "fecha_limite = %(fecha_limite)s",
    ]
    params: dict = {
        "id": id_orden, "id_bicicleta": id_bicicleta, "origen": origen, "tipo_falla": tipo_falla,
        "prioridad": prioridad, "estado_reparacion": estado_reparacion, "id_tecnico": id_tecnico,
        "diagnostico": diagnostico, "costo_repuestos": costo_repuestos, "costo_mano_obra": costo_mano_obra,
        "fecha_limite": fecha_limite,
    }
    # fecha_cierre solo se registra la primera vez que la orden pasa a
    # 'cerrada' -- no se pisa si ya estaba cerrada y se vuelve a guardar.
    if estado_reparacion == "cerrada" and (not orden_actual or orden_actual["estado_reparacion"] != "cerrada"):
        sets.append("fecha_cierre = %(fecha_cierre)s")
        params["fecha_cierre"] = datetime.now()

    ch.get_client().command(f"""
        ALTER TABLE urbanbike_operativa.ordenes_mantenimiento
        UPDATE {", ".join(sets)}
        WHERE id = %(id)s
    """, parameters=params, settings={"mutations_sync": 1})


def eliminar(id_orden: str) -> tuple[bool, str]:
    """(True, '') si se borro; (False, motivo) si esta bloqueado.

    Solo se permite el borrado real si la orden sigue 'abierta' (no ha
    avanzado de estado) y no tiene repuestos reales consumidos -- borrar
    una orden con trabajo o costo real asociado perderia esa evidencia.
    """
    orden = obtener(id_orden)
    if not orden:
        return False, "Orden no encontrada."

    if orden["estado_reparacion"] != "abierta":
        return False, (
            f"No se puede eliminar: la orden ya avanzó a estado '{orden['estado_reparacion']}'. "
            "Solo se puede borrar una orden que sigue en 'Abierta'."
        )

    n_repuestos = contar_repuestos(id_orden)
    if n_repuestos > 0:
        return False, f"No se puede eliminar: tiene {n_repuestos} repuesto(s) real(es) consumido(s)."

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.ordenes_mantenimiento DELETE WHERE id = %(id)s",
        parameters={"id": id_orden}, settings={"mutations_sync": 1},
    )
    return True, ""
