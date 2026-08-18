"""Repositorio de acceso a inspecciones de devolucion (Nivel 2, ver
docs/HOJA_DE_RUTA.md).

Fuente real: urbanbike_operativa.checklist_items (12 items reales del
seed) e inspecciones/inspeccion_detalle en ClickHouse. Hasta el
06-ago-2026 el formulario de empleado/vigilancia/inspeccion.html usaba
una lista de 7 items inventados (_CHECKLIST_ITEMS en empleado.py) y
nunca escribia en estas tablas -- 0 filas reales en ambas.

Alcance de HOY (Nivel 2): registrar la inspeccion en si misma de forma
real (1 fila en inspecciones + 12 en inspeccion_detalle). La rama
"reprobada" del flujo (crear orden de mantenimiento, infraccion, cobro
por danos, actualizar bicicletas.estado) sigue escribiendo en
PocketBase, desconectada de las tablas reales -- eso es Nivel 3,
documentado como pendiente de prioridad alta en HOJA_DE_RUTA.md, no se
toca en este repositorio todavia.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.db import clickhouse as ch

UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"

RESULTADOS_VALIDOS = ("ok", "dano_leve", "dano_grave", "faltante")


def listar_checklist_items() -> list[dict]:
    """Los 12 items reales del catalogo, en el orden real del checklist."""
    return ch.query("""
        SELECT id, codigo, nombre, categoria, orden
        FROM urbanbike_operativa.checklist_items FINAL
        WHERE activo = 1
        ORDER BY orden
    """)


def resolver_bicicleta_id(codigo: str) -> str | None:
    """codigo (p.ej. 'UB-002') -> id real de urbanbike_operativa.bicicletas."""
    if not codigo:
        return None
    filas = ch.query(
        "SELECT id FROM urbanbike_operativa.bicicletas FINAL WHERE codigo = %(c)s",
        {"c": codigo},
    )
    return str(filas[0]["id"]) if filas else None


def resolver_alquiler_id(viaje_id_pocketbase: str) -> str:
    """viajes.id de PocketBase -> id real de alquileres, via
    id_origen_pocketbase (ver docs/HOJA_DE_RUTA.md seccion 17/18).
    Sentinela si el viaje no se ha migrado todavia (viaje en curso hoy)."""
    if not viaje_id_pocketbase:
        return UUID_SENTINELA
    mapa = ch.mapa_alquiler_por_viaje_pocketbase()
    return mapa.get(viaje_id_pocketbase, UUID_SENTINELA)


def asegurar_inspector(*, email: str, nombre_completo: str) -> str:
    """Devuelve el id real del usuario inspector, creandolo si no existe
    (busca por email) -- mismo patron que asegurar_usuario() en
    etl/07_migrar_viajes_pagos.py. Hoy no existe ningun usuario real con
    rol='vigilancia' en la base (confirmado en la auditoria del
    06-ago-2026), asi que la primera inspeccion real siempre lo crea."""
    if not email:
        return UUID_SENTINELA

    filas = ch.query(
        "SELECT id FROM urbanbike_operativa.usuarios FINAL WHERE email = %(email)s",
        {"email": email},
    )
    if filas:
        return str(filas[0]["id"])

    nombre, _, apellido = (nombre_completo or email).strip().partition(" ")
    nuevo_id = str(uuid.uuid4())
    ultimo = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM urbanbike_operativa.usuarios"
    ) or 0
    codigo = f"U-{ultimo + 1:04d}"
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.usuarios (id, codigo, nombre, apellido, email, rol, estado)
        VALUES (%(id)s, %(codigo)s, %(nombre)s, %(apellido)s, %(email)s, 'vigilancia', 'activo')
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "nombre": nombre or email,
        "apellido": apellido, "email": email,
    })
    return nuevo_id


def crear(*, id_alquiler: str, id_bicicleta: str, id_inspector: str,
          resultados: dict[str, str], observacion: str) -> tuple[str, bool]:
    """resultados: {codigo_item: resultado}. Escribe 1 fila en inspecciones
    y una por item real en inspeccion_detalle. Devuelve (id_inspeccion,
    tiene_dano)."""
    items = listar_checklist_items()
    tiene_dano = any(resultados.get(it["codigo"], "ok") != "ok" for it in items)
    ahora = datetime.now()
    nuevo_id = str(uuid.uuid4())

    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.inspecciones
            (id, id_alquiler, id_bicicleta, id_inspector, fecha_inicio, fecha_fin,
             estado, items_revisados, items_totales, tiene_dano, observacion)
        VALUES
            (%(id)s, %(id_alquiler)s, %(id_bicicleta)s, %(id_inspector)s, %(ahora)s, %(ahora)s,
             'certificada', %(revisados)s, %(totales)s, %(tiene_dano)s, %(obs)s)
    """, parameters={
        "id": nuevo_id, "id_alquiler": id_alquiler, "id_bicicleta": id_bicicleta,
        "id_inspector": id_inspector, "ahora": ahora,
        "revisados": len(resultados), "totales": len(items),
        "tiene_dano": 1 if tiene_dano else 0, "obs": observacion,
    })

    for it in items:
        resultado = resultados.get(it["codigo"], "ok")
        ch.get_client().command("""
            INSERT INTO urbanbike_operativa.inspeccion_detalle
                (id, id_inspeccion, id_item, resultado)
            VALUES (%(id)s, %(id_inspeccion)s, %(id_item)s, %(resultado)s)
        """, parameters={
            "id": str(uuid.uuid4()), "id_inspeccion": nuevo_id,
            "id_item": it["id"], "resultado": resultado,
        })

    return nuevo_id, tiene_dano


def ultima_para_bicicleta(id_bicicleta: str) -> dict | None:
    """La inspeccion real mas reciente de esta bicicleta, con su detalle
    por item (codigo/nombre/categoria/resultado). None si nunca se le
    hizo una inspeccion real."""
    if not id_bicicleta:
        return None
    filas = ch.query("""
        SELECT id, id_alquiler, id_bicicleta, id_inspector, fecha_inicio, fecha_fin,
               estado, items_revisados, items_totales, tiene_dano, observacion
        FROM urbanbike_operativa.inspecciones FINAL
        WHERE id_bicicleta = %(id)s
        ORDER BY fecha_inicio DESC
        LIMIT 1
    """, {"id": id_bicicleta})
    if not filas:
        return None
    inspeccion = filas[0]

    detalle = ch.query("""
        SELECT i.codigo AS codigo, i.nombre AS nombre, i.categoria AS categoria, d.resultado AS resultado
        FROM urbanbike_operativa.inspeccion_detalle d FINAL
        JOIN urbanbike_operativa.checklist_items i FINAL ON i.id = d.id_item
        WHERE d.id_inspeccion = %(id)s
        ORDER BY i.orden
    """, {"id": inspeccion["id"]})

    return {**inspeccion, "detalle": detalle}
