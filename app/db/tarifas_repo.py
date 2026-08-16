"""Repositorio unico de acceso a tarifas.

Fuente real: urbanbike_operativa.tarifas en ClickHouse -- la misma que
lee _catalogo_bicicletas() (app/routers/ciclista.py) para el precio
real del catalogo. Hasta el 06-ago-2026, gerente/tarifas.html editaba
una coleccion de PocketBase completamente distinta y desconectada
(tipo_bicicleta/tipo_usuario/precio_hora, sin modalidad ni categoria) --
"editar tarifa" ahi no cambiaba nada del precio real. Este repositorio
reemplaza esa conexion (ver docs/HOJA_DE_RUTA.md).

ORDER BY corregido preventivamente el 06-ago-2026 (id_categoria,
tipo_membresia, modalidad, vigente_desde) -> id, antes de construir la
primera edicion real (ver seccion 0 de HOJA_DE_RUTA.md).

'Eliminar' solo borra de verdad si ningun alquiler real referencia esa
tarifa -- perderla borraria el precio histórico de un alquiler ya
facturado. Si tiene alquileres asociados, se bloquea sugiriendo marcar
estado='historica' en su lugar (igual criterio que bicicletas/ordenes).
"""

from __future__ import annotations

import uuid
from datetime import date

from app.db import clickhouse as ch

TIPOS_MEMBRESIA_VALIDOS = ("member", "casual")
MODALIDADES_VALIDAS = ("hora", "dia", "semana")
ESTADOS_VALIDOS = ("vigente", "historica")


def listar_categorias_ref() -> list[dict]:
    """[{id, nombre}] para el <select> de categoria."""
    return ch.query("""
        SELECT id, nombre FROM urbanbike_operativa.categorias FINAL
        WHERE activa = 1 ORDER BY orden, nombre
    """)


_SELECT_BASE = """
    SELECT t.id AS id, t.id_categoria AS id_categoria, c.nombre AS categoria,
           t.tipo_membresia AS tipo_membresia, t.modalidad AS modalidad,
           t.precio AS precio, t.minutos_gracia AS minutos_gracia,
           t.recargo_minuto AS recargo_minuto, t.vigente_desde AS vigente_desde,
           t.vigente_hasta AS vigente_hasta, t.estado AS estado
    FROM urbanbike_operativa.tarifas t FINAL
    JOIN urbanbike_operativa.categorias c FINAL ON c.id = t.id_categoria
"""


def listar() -> list[dict]:
    return ch.query(_SELECT_BASE + " ORDER BY c.orden, t.tipo_membresia, t.modalidad")


def obtener(id_tarifa: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE t.id = %(id)s", {"id": id_tarifa})
    return filas[0] if filas else None


def contar_alquileres(id_tarifa: str) -> int:
    return ch.scalar(
        "SELECT count() FROM urbanbike_operativa.alquileres FINAL WHERE id_tarifa = %(id)s",
        {"id": id_tarifa},
    ) or 0


def crear(*, id_categoria: str, tipo_membresia: str, modalidad: str, precio: float,
          minutos_gracia: int, recargo_minuto: float, vigente_desde: date,
          vigente_hasta: date, estado: str) -> str:
    nuevo_id = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.tarifas
            (id, id_categoria, tipo_membresia, modalidad, precio, minutos_gracia,
             recargo_minuto, vigente_desde, vigente_hasta, estado)
        VALUES
            (%(id)s, %(id_categoria)s, %(tipo_membresia)s, %(modalidad)s, %(precio)s,
             %(minutos_gracia)s, %(recargo_minuto)s, %(vigente_desde)s, %(vigente_hasta)s,
             %(estado)s)
    """, parameters={
        "id": nuevo_id, "id_categoria": id_categoria, "tipo_membresia": tipo_membresia,
        "modalidad": modalidad, "precio": precio, "minutos_gracia": minutos_gracia,
        "recargo_minuto": recargo_minuto, "vigente_desde": vigente_desde,
        "vigente_hasta": vigente_hasta, "estado": estado,
    })
    return nuevo_id


def actualizar(id_tarifa: str, *, id_categoria: str, tipo_membresia: str, modalidad: str,
               precio: float, minutos_gracia: int, recargo_minuto: float,
               vigente_desde: date, vigente_hasta: date, estado: str) -> None:
    # No se toca 'version': columna clave de ReplacingMergeTree, ClickHouse
    # rechaza su ALTER ... UPDATE directo (ver docs/HOJA_DE_RUTA.md seccion 20).
    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.tarifas
        UPDATE id_categoria = %(id_categoria)s, tipo_membresia = %(tipo_membresia)s,
               modalidad = %(modalidad)s, precio = %(precio)s,
               minutos_gracia = %(minutos_gracia)s, recargo_minuto = %(recargo_minuto)s,
               vigente_desde = %(vigente_desde)s, vigente_hasta = %(vigente_hasta)s,
               estado = %(estado)s
        WHERE id = %(id)s
    """, parameters={
        "id": id_tarifa, "id_categoria": id_categoria, "tipo_membresia": tipo_membresia,
        "modalidad": modalidad, "precio": precio, "minutos_gracia": minutos_gracia,
        "recargo_minuto": recargo_minuto, "vigente_desde": vigente_desde,
        "vigente_hasta": vigente_hasta, "estado": estado,
    }, settings={"mutations_sync": 1})


def categoria_de_bicicleta(codigo: str) -> str | None:
    """id_categoria real (UUID de ClickHouse) para una bicicleta por su
    codigo -- mismo join que ya usa _catalogo_bicicletas() en
    ciclista.py, extraido aca para que _tarifa_hora() (el camino de
    cobro real) tambien pueda resolverlo, en vez de solo tipo_bicicleta
    classic/electric como hacia la coleccion vieja de PocketBase (ver
    docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md)."""
    fila = ch.query_one("""
        SELECT m.id_categoria AS id_categoria
        FROM urbanbike_operativa.bicicletas b FINAL
        INNER JOIN urbanbike_operativa.modelos_bicicleta m FINAL ON m.id = b.id_modelo
        WHERE b.codigo = %(codigo)s
    """, {"codigo": codigo})
    return str(fila["id_categoria"]) if fila else None


def precio_modalidad(id_categoria: str, tipo_membresia: str, modalidad: str) -> tuple[float, str] | None:
    """Precio real vigente + id de la fila de tarifa usada, para una
    categoria/membresia/modalidad -- fuente unica real de precios
    (reemplaza _tarifa_hora(), que leia la coleccion vieja de
    PocketBase tarifas, sin categoria ni dia/semana). None si no hay
    tarifa vigente para ese combo -- nunca se inventa un precio."""
    fila = ch.query_one("""
        SELECT id, precio FROM urbanbike_operativa.tarifas FINAL
        WHERE id_categoria = %(id_categoria)s AND tipo_membresia = %(tipo_membresia)s
          AND modalidad = %(modalidad)s AND estado = 'vigente'
          AND today() BETWEEN vigente_desde AND vigente_hasta
    """, {"id_categoria": id_categoria, "tipo_membresia": tipo_membresia, "modalidad": modalidad})
    return (float(fila["precio"]), str(fila["id"])) if fila else None


def eliminar(id_tarifa: str) -> tuple[bool, str]:
    """(True, '') si se borro; (False, motivo) si esta bloqueado."""
    tarifa = obtener(id_tarifa)
    if not tarifa:
        return False, "Tarifa no encontrada."

    n_alquileres = contar_alquileres(id_tarifa)
    if n_alquileres > 0:
        return False, (
            f"No se puede eliminar: {n_alquileres} alquiler(es) real(es) usan esta tarifa. "
            "Cambia su estado a 'Histórica' en su lugar."
        )

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.tarifas DELETE WHERE id = %(id)s",
        parameters={"id": id_tarifa}, settings={"mutations_sync": 1},
    )
    return True, ""
