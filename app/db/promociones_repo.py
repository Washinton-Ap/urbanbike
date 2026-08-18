"""Repositorio unico de acceso a promociones.

Fuente real: urbanbike_operativa.promociones en ClickHouse. Tabla sin
ningun consumidor hasta el 06-ago-2026 (ni pantalla ni calculo de
precio la tocaban, ver docs/HOJA_DE_RUTA.md) -- las 2 filas que existian
eran 100% seed (FINDE15, ESTUD20), con el ORDER BY ya corregido en la
sesion anterior a este WorkPanel.

'Eliminar' solo borra de verdad si usos_actuales == 0: si ya es mayor a
cero, la promocion ya se aplico en al menos un alquiler real y borrarla
perderia esa referencia -- se bloquea sugiriendo desactivar (estado
'pausada'/'vencida') en su lugar. Mismo criterio que ordenes_mantenimiento
(no perder evidencia de algo que ya tuvo efecto real).
"""

from __future__ import annotations

import uuid
from datetime import date

from app.db import clickhouse as ch

TIPOS_DESCUENTO_VALIDOS = ("porcentaje", "monto")
APLICA_A_VALIDOS = ("todas", "categoria", "modalidad", "bicicleta")
ESTADOS_VALIDOS = ("activa", "pausada", "vencida")


def listar_categorias_ref() -> list[dict]:
    """[{id, nombre}] para el <select> cuando aplica_a == 'categoria'."""
    return ch.query("""
        SELECT id, nombre FROM urbanbike_operativa.categorias FINAL
        WHERE activa = 1 ORDER BY nombre
    """)


def listar_bicicletas_ref() -> list[dict]:
    """[{id, codigo}] para el <select> cuando aplica_a == 'bicicleta'."""
    return ch.query("""
        SELECT id, codigo FROM urbanbike_operativa.bicicletas FINAL ORDER BY codigo
    """)


_SELECT_BASE = """
    SELECT id, codigo, nombre, tipo_descuento, valor, aplica_a, id_referencia,
           dias_semana, fecha_inicio, fecha_fin, usos_maximos, usos_actuales, estado,
           solo_member
    FROM urbanbike_operativa.promociones FINAL
"""


def listar(*, q: str = "", estado: str = "", page: int = 1, per_page: int = 10) -> tuple[list[dict], int]:
    import math
    where = ["1=1"]
    params: dict = {}
    if q:
        where.append("(codigo ILIKE %(q)s OR nombre ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if estado:
        where.append("estado = %(estado)s")
        params["estado"] = estado
    where_sql = " AND ".join(where)

    total = ch.scalar(
        f"SELECT count() FROM urbanbike_operativa.promociones FINAL WHERE {where_sql}", params
    ) or 0

    page = max(1, page)
    total_paginas = max(1, math.ceil(total / per_page))
    page = min(page, total_paginas)
    offset = (page - 1) * per_page

    filas = ch.query(
        _SELECT_BASE + f" WHERE {where_sql} ORDER BY fecha_inicio DESC, codigo LIMIT {per_page} OFFSET {offset}",
        params,
    )
    return filas, total


def obtener(id_promo: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE id = %(id)s", {"id": id_promo})
    return filas[0] if filas else None


def crear(*, codigo: str, nombre: str, tipo_descuento: str, valor: float, aplica_a: str,
          id_referencia: str, dias_semana: str, fecha_inicio: date, fecha_fin: date,
          usos_maximos: int, estado: str, solo_member: bool = False) -> str:
    nuevo_id = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.promociones
            (id, codigo, nombre, tipo_descuento, valor, aplica_a, id_referencia,
             dias_semana, fecha_inicio, fecha_fin, usos_maximos, usos_actuales, estado,
             solo_member)
        VALUES
            (%(id)s, %(codigo)s, %(nombre)s, %(tipo_descuento)s, %(valor)s, %(aplica_a)s,
             %(id_referencia)s, %(dias_semana)s, %(fecha_inicio)s, %(fecha_fin)s,
             %(usos_maximos)s, 0, %(estado)s, %(solo_member)s)
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "nombre": nombre, "tipo_descuento": tipo_descuento,
        "valor": valor, "aplica_a": aplica_a, "id_referencia": id_referencia,
        "dias_semana": dias_semana, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
        "usos_maximos": usos_maximos, "estado": estado, "solo_member": int(solo_member),
    })
    return nuevo_id


def actualizar(id_promo: str, *, codigo: str, nombre: str, tipo_descuento: str, valor: float,
               aplica_a: str, id_referencia: str, dias_semana: str, fecha_inicio: date,
               fecha_fin: date, usos_maximos: int, estado: str, solo_member: bool = False) -> None:
    # No se toca 'version': es la columna clave de ReplacingMergeTree y
    # ClickHouse rechaza su ALTER ... UPDATE directo (CANNOT_UPDATE_COLUMN),
    # igual que una columna de ORDER BY -- mismo patron que ordenes_repo.py.
    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.promociones
        UPDATE codigo = %(codigo)s, nombre = %(nombre)s, tipo_descuento = %(tipo_descuento)s,
               valor = %(valor)s, aplica_a = %(aplica_a)s, id_referencia = %(id_referencia)s,
               dias_semana = %(dias_semana)s, fecha_inicio = %(fecha_inicio)s,
               fecha_fin = %(fecha_fin)s, usos_maximos = %(usos_maximos)s, estado = %(estado)s,
               solo_member = %(solo_member)s
        WHERE id = %(id)s
    """, parameters={
        "id": id_promo, "codigo": codigo, "nombre": nombre, "tipo_descuento": tipo_descuento,
        "valor": valor, "aplica_a": aplica_a, "id_referencia": id_referencia,
        "dias_semana": dias_semana, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
        "usos_maximos": usos_maximos, "estado": estado, "solo_member": int(solo_member),
    }, settings={"mutations_sync": 1})


def incrementar_uso(id_promo: str) -> None:
    """Suma 1 a usos_actuales -- se llama cuando una promocion real se
    aplica de verdad a una transaccion (hoy: alquiler manual de
    Operacion, ver alquileres_repo.cotizar()/crear_presencial()). No se
    toca 'version' (ver nota de actualizar(), mismo motivo)."""
    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.promociones
        UPDATE usos_actuales = usos_actuales + 1
        WHERE id = %(id)s
    """, parameters={"id": id_promo}, settings={"mutations_sync": 1})


def eliminar(id_promo: str) -> tuple[bool, str]:
    """(True, '') si se borro; (False, motivo) si esta bloqueado."""
    promo = obtener(id_promo)
    if not promo:
        return False, "Promoción no encontrada."

    if promo["usos_actuales"] > 0:
        return False, (
            f"No se puede eliminar: ya se usó {promo['usos_actuales']} vez(es) en alquileres reales. "
            "Cambia su estado a 'Pausada' o 'Vencida' en su lugar."
        )

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.promociones DELETE WHERE id = %(id)s",
        parameters={"id": id_promo}, settings={"mutations_sync": 1},
    )
    return True, ""


# ── Aplicacion real del descuento (Parte 3: catalogo del ciclista) ─────────

def activas_hoy() -> list[dict]:
    """Promociones vigentes hoy: estado='activa', dentro de fecha_inicio/fin,
    y el dia de la semana actual esta en dias_semana (CSV, 1=lunes..7=domingo).
    Tabla chica: se trae completa y se filtra en Python, sin costo real."""
    hoy = date.today()
    dia_iso = str(hoy.isoweekday())
    filas = ch.query(f"""
        {_SELECT_BASE}
        WHERE estado = 'activa' AND toDate('{hoy.isoformat()}') BETWEEN fecha_inicio AND fecha_fin
    """)
    return [f for f in filas if dia_iso in [d.strip() for d in (f["dias_semana"] or "").split(",")]]


def _no_agotada(promo: dict) -> bool:
    """True si la promo todavia tiene usos disponibles (usos_maximos == 0
    significa sin limite). Criterio compartido entre disponibles_hoy()
    (listado que ve el ciclista) y promo_aplicable() (calculo real del
    precio) -- antes promo_aplicable() no lo revisaba, y una promocion ya
    agotada seguia bajando el precio real del catalogo y del cobro
    presencial. Ver docs/HOJA_DE_RUTA.md."""
    return promo["usos_maximos"] == 0 or promo["usos_actuales"] < promo["usos_maximos"]


def disponibles_hoy() -> list[dict]:
    """Como activas_hoy(), pero ademas excluye las agotadas -- activas_hoy()
    no lo filtra porque promo_aplicable() aplica su propio filtro (ver
    _no_agotada) al elegir la de mayor ahorro para una bicicleta puntual."""
    return [p for p in activas_hoy() if _no_agotada(p)]


def promo_aplicable(promos: list[dict], *, id_categoria, id_bicicleta, modalidad: str,
                     precio: float, es_member: bool = False) -> tuple[dict | None, float]:
    """(promo, precio_con_descuento) -- entre las promociones que aplican a
    esta combinacion (categoria/modalidad/bicicleta o 'todas') y que todavia
    tienen usos disponibles, la que da mayor ahorro real en dolares para
    este precio. (None, precio) si ninguna aplica.

    `es_member` (punto 4, "promociones exclusivas... para suscriptores"):
    una promo con solo_member=1 nunca se considera para un ciclista casual,
    sin importar cuanto ahorre -- se filtra acá para que ni el cálculo de
    precio del catálogo ni el cobro presencial de Operación se lo apliquen
    por error a quien no es suscriptor."""
    mejor: dict | None = None
    mejor_precio = precio
    for p in promos:
        if p.get("solo_member") and not es_member:
            continue
        aplica = (
            p["aplica_a"] == "todas"
            or (p["aplica_a"] == "categoria" and p["id_referencia"] == str(id_categoria))
            or (p["aplica_a"] == "modalidad" and p["id_referencia"] == modalidad)
            or (p["aplica_a"] == "bicicleta" and p["id_referencia"] == str(id_bicicleta))
        )
        if not aplica or not _no_agotada(p):
            continue
        valor = float(p["valor"])
        descuento = precio * valor / 100 if p["tipo_descuento"] == "porcentaje" else valor
        nuevo_precio = max(0.0, precio - descuento)
        if nuevo_precio < mejor_precio:
            mejor_precio = nuevo_precio
            mejor = p
    return mejor, round(mejor_precio, 2)
