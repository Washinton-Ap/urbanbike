"""Repositorio unico de acceso a alquileres.

Fuente real: urbanbike_operativa.alquileres en ClickHouse. Usado por el
WorkPanel de Operacion (empleado/operacion/alquileres.html).

'Eliminar' se implementa como 'Cancelar' (estado -> 'cancelado'), NUNCA
un borrado real: un alquiler es evidencia de una transaccion. Solo se
permite desde 'reservado'/'en_curso' -- cancelar algo ya 'facturado'
seria una nota de credito, un caso distinto que no se resuelve aqui.

Cada vez que este repositorio cambia el estado de una bicicleta
(crear/cancelar/completar), lo hace llamando a
`bicicletas_repo.actualizar()` -- el mismo repositorio compartido del
WorkPanel de bicicletas, que ya sincroniza el espejo hacia PocketBase.
No se duplica esa logica aqui.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.db import bicicletas_repo, promociones_repo, clickhouse as ch

DB = "urbanbike_operativa"
ESTADOS_CANCELABLES = ("reservado", "en_curso")
UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"

_SELECT_BASE = """
    SELECT a.id AS id, a.codigo AS codigo, a.estado AS estado,
           a.fecha_reserva AS fecha_reserva, a.fecha_inicio AS fecha_inicio,
           a.fecha_fin AS fecha_fin, a.minutos_reales AS minutos_reales,
           a.minutos_contratados AS minutos_contratados, a.modalidad AS modalidad,
           a.subtotal AS subtotal, a.descuento AS descuento, a.recargo AS recargo,
           a.total AS total, a.id_promocion AS id_promocion, a.es_prueba AS es_prueba,
           b.id AS id_bicicleta, b.codigo AS bicicleta_codigo,
           u.id AS id_usuario, concat(u.nombre, ' ', u.apellido) AS ciclista_nombre,
           ei.id AS id_estacion_inicio, ei.nombre AS estacion_inicio_nombre,
           ef.id AS id_estacion_fin, ifNull(ef.nombre, '') AS estacion_fin_nombre
    FROM urbanbike_operativa.alquileres a FINAL
    JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = a.id_bicicleta
    JOIN urbanbike_operativa.usuarios u FINAL ON u.id = a.id_usuario
    JOIN urbanbike_operativa.estaciones ei FINAL ON ei.id = a.id_estacion_inicio
    LEFT JOIN urbanbike_operativa.estaciones ef FINAL ON ef.id = toUUIDOrNull(a.id_estacion_fin)
"""


def listar(*, q: str = "", estado: str = "", fecha_desde: date | None = None,
           fecha_hasta: date | None = None, incluir_prueba: bool = True,
           page: int = 1, per_page: int = 10) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if q:
        where.append("(b.codigo ILIKE %(q)s OR u.nombre ILIKE %(q)s OR u.apellido ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if estado:
        where.append("a.estado = %(estado)s")
        params["estado"] = estado
    if fecha_desde:
        where.append("toDate(a.fecha_inicio) >= %(fd)s")
        params["fd"] = fecha_desde
    if fecha_hasta:
        where.append("toDate(a.fecha_inicio) <= %(fh)s")
        params["fh"] = fecha_hasta
    if not incluir_prueba:
        # Excluye viajes de prueba de desarrollo (ver HOJA_DE_RUTA.md sección 8):
        # todo informe que muestre duración/ingresos debe filtrar es_prueba=0.
        where.append("a.es_prueba = 0")
    where_sql = " AND ".join(where)

    total = ch.scalar(f"""
        SELECT count() FROM urbanbike_operativa.alquileres a FINAL
        JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = a.id_bicicleta
        JOIN urbanbike_operativa.usuarios u FINAL ON u.id = a.id_usuario
        WHERE {where_sql}
    """, params) or 0

    import math
    page = max(1, page)
    total_paginas = max(1, math.ceil(total / per_page))
    page = min(page, total_paginas)
    offset = (page - 1) * per_page

    filas = ch.query(
        _SELECT_BASE + f" WHERE {where_sql} ORDER BY a.fecha_inicio DESC LIMIT {per_page} OFFSET {offset}",
        params,
    )
    return filas, total


def obtener(id_alquiler: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE a.id = %(id)s", {"id": id_alquiler})
    return filas[0] if filas else None


def eventos(id_alquiler: str) -> list[dict]:
    return ch.query("""
        SELECT secuencia, estado_origen, estado_destino, fecha, rol_actor, observacion
        FROM urbanbike_operativa.alquiler_eventos
        WHERE id_alquiler = %(id)s ORDER BY secuencia
    """, {"id": id_alquiler})


def _siguiente_codigo() -> str:
    maximo = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM urbanbike_operativa.alquileres FINAL "
        "WHERE codigo LIKE 'A-%'"
    ) or 0
    return f"A-{maximo + 1:06d}"


def _siguiente_secuencia(id_alquiler: str) -> int:
    return (ch.scalar(
        "SELECT max(secuencia) FROM urbanbike_operativa.alquiler_eventos WHERE id_alquiler = %(id)s",
        {"id": id_alquiler},
    ) or 0) + 1


def _insertar_evento(id_alquiler: str, origen: str, destino: str, fecha: datetime,
                      id_actor: str, rol_actor: str, observacion: str) -> None:
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.alquiler_eventos
            (id_alquiler, secuencia, estado_origen, estado_destino, fecha, id_actor, rol_actor, observacion)
        VALUES (%(id_alquiler)s, %(secuencia)s, %(origen)s, %(destino)s, %(fecha)s, %(actor)s, %(rol)s, %(obs)s)
    """, parameters={
        "id_alquiler": id_alquiler, "secuencia": _siguiente_secuencia(id_alquiler),
        "origen": origen, "destino": destino, "fecha": fecha,
        "actor": id_actor, "rol": rol_actor, "obs": observacion,
    })


def _sincronizar_bicicleta(id_bicicleta: str, *, estado: str, id_estacion: str | None = None) -> None:
    """Reusa bicicletas_repo.actualizar() (mismo repositorio del WorkPanel
    de bicicletas) para que el espejo hacia PocketBase se mantenga
    sincronizado automaticamente, sin duplicar esa logica aqui."""
    bici = bicicletas_repo.obtener(id_bicicleta)
    if not bici:
        return
    bicicletas_repo.actualizar(
        id_bicicleta,
        codigo=bici["codigo"], id_modelo=str(bici["id_modelo"]), estado=estado,
        id_estacion=str(id_estacion) if id_estacion else str(bici["id_estacion"] or ""),
        numero_serie=bici["numero_serie"], fecha_adquisicion=bici["fecha_adquisicion"],
        observacion=bici["observacion"], es_electrica=bool(bici["es_electrica"]),
    )


def _crear_usuario_presencial(nombre_completo: str) -> str:
    """Usuario real nuevo (rol=ciclista) para un cliente presencial sin
    cuenta -- nunca un sentinela compartido entre clientes distintos."""
    partes = (nombre_completo or "Cliente Presencial").strip().split(maxsplit=1)
    nombre = partes[0] if partes else "Cliente"
    apellido = partes[1] if len(partes) > 1 else ""

    nuevo_id = str(uuid.uuid4())
    siguiente = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM urbanbike_operativa.usuarios FINAL"
    ) or 0
    codigo = f"U-{siguiente + 1:04d}"
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.usuarios (id, codigo, nombre, apellido, email, rol, estado)
        VALUES (%(id)s, %(codigo)s, %(nombre)s, %(apellido)s, '', 'ciclista', 'activo')
    """, parameters={"id": nuevo_id, "codigo": codigo, "nombre": nombre, "apellido": apellido})
    return nuevo_id


def _resolver_tarifa(id_modelo: str) -> dict | None:
    """{id_tarifa, precio, id_categoria} de la tarifa casual/hora vigente
    de la categoria de este modelo (un cliente presencial sin cuenta se
    tarifica como 'casual', igual que el resto del sistema). None si no
    hay tarifa vigente para esa categoria (no deberia pasar hoy -- las 4
    categorias reales tienen tarifa casual/hora vigente)."""
    return ch.query_one("""
        SELECT t.id AS id_tarifa, t.precio AS precio, m.id_categoria AS id_categoria
        FROM urbanbike_operativa.modelos_bicicleta m FINAL
        JOIN urbanbike_operativa.tarifas t FINAL ON t.id_categoria = m.id_categoria
        WHERE m.id = %(id_modelo)s AND t.tipo_membresia = 'casual' AND t.modalidad = 'hora'
          AND t.estado = 'vigente'
        LIMIT 1
    """, {"id_modelo": id_modelo})


def cotizar(id_bicicleta: str) -> dict:
    """Precio real (tarifa casual/hora vigente) + promocion aplicable
    (mayor ahorro real -- mismo criterio y mismo helper que
    _catalogo_bicicletas() en ciclista.py) para una bicicleta. Reutilizado
    por el formulario de Insertar (vista previa antes de confirmar) y por
    crear_presencial() (cobro real), para no calcular el precio dos veces
    con criterios distintos.

    {id_tarifa, precio_base, promo: {id, codigo, nombre} | None,
     descuento, total} -- precio_base=descuento=total=0 si la bicicleta
    o su categoria no resuelven una tarifa real (no se inventa un precio)."""
    bici = bicicletas_repo.obtener(id_bicicleta)
    tarifa = _resolver_tarifa(str(bici["id_modelo"])) if bici else None
    if not tarifa:
        return {"id_tarifa": UUID_SENTINELA, "precio_base": 0.0, "promo": None, "descuento": 0.0, "total": 0.0}

    precio_base = float(tarifa["precio"])
    promos = promociones_repo.activas_hoy()
    promo, precio_final = promociones_repo.promo_aplicable(
        promos, id_categoria=tarifa["id_categoria"], id_bicicleta=id_bicicleta,
        modalidad="hora", precio=precio_base,
    )
    return {
        "id_tarifa": str(tarifa["id_tarifa"]),
        "precio_base": precio_base,
        "promo": {"id": str(promo["id"]), "codigo": promo["codigo"], "nombre": promo["nombre"]} if promo else None,
        "descuento": round(precio_base - precio_final, 2),
        "total": precio_final,
    }


def crear_presencial(*, id_bicicleta: str, id_estacion_inicio: str, nombre_ciclista: str,
                      es_prueba: bool = False) -> str:
    """Alquiler manual para un cliente presencial sin cuenta: crea un
    usuario real nuevo (nunca un sentinela compartido), cotiza el precio
    real (tarifa vigente + promocion aplicable si hay alguna, ver
    cotizar()) e inserta reservado+en_curso con la misma fecha_inicio
    (recogida inmediata, igual que el resto de alquileres manuales de
    este sistema)."""
    bici = bicicletas_repo.obtener(id_bicicleta)
    if not bici:
        raise ValueError("Bicicleta no encontrada.")

    id_usuario = _crear_usuario_presencial(nombre_ciclista)
    cotizacion = cotizar(id_bicicleta)

    nuevo_id = str(uuid.uuid4())
    codigo = _siguiente_codigo()
    ahora = datetime.now()

    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.alquileres
            (id, codigo, id_usuario, id_bicicleta, id_tarifa, id_promocion, id_estacion_inicio,
             modalidad, cantidad_contratada, minutos_contratados, fecha_reserva,
             fecha_inicio, estado, subtotal, descuento, total, es_prueba)
        VALUES
            (%(id)s, %(codigo)s, %(id_usuario)s, %(id_bicicleta)s, %(id_tarifa)s, %(id_promocion)s,
             %(id_estacion)s, 'hora', 1, 60, %(ahora)s, %(ahora)s, 'en_curso',
             %(subtotal)s, %(descuento)s, %(total)s, %(es_prueba)s)
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "id_usuario": id_usuario, "id_bicicleta": id_bicicleta,
        "id_tarifa": cotizacion["id_tarifa"],
        "id_promocion": cotizacion["promo"]["id"] if cotizacion["promo"] else "",
        "id_estacion": id_estacion_inicio, "ahora": ahora,
        "subtotal": cotizacion["precio_base"], "descuento": cotizacion["descuento"],
        "total": cotizacion["total"], "es_prueba": 1 if es_prueba else 0,
    })

    _insertar_evento(nuevo_id, "", "reservado", ahora, id_usuario, "ciclista",
                      f"Alquiler manual presencial ({codigo})")
    _insertar_evento(nuevo_id, "reservado", "en_curso", ahora, id_usuario, "ciclista",
                      "Recogida inmediata (registro presencial)")

    _sincronizar_bicicleta(id_bicicleta, estado="en_uso")

    if cotizacion["promo"]:
        promociones_repo.incrementar_uso(cotizacion["promo"]["id"])

    return nuevo_id


def cancelar(id_alquiler: str) -> tuple[bool, str]:
    alq = obtener(id_alquiler)
    if not alq:
        return False, "Alquiler no encontrado."
    if alq["estado"] not in ESTADOS_CANCELABLES:
        return False, (
            f"No se puede cancelar: el alquiler ya está en estado '{alq['estado']}'. "
            "Cancelar algo ya facturado sería una nota de crédito, un caso distinto "
            "que no se resuelve en este WorkPanel."
        )

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.alquileres UPDATE estado = 'cancelado' WHERE id = %(id)s",
        parameters={"id": id_alquiler}, settings={"mutations_sync": 1},
    )
    _insertar_evento(id_alquiler, alq["estado"], "cancelado", datetime.now(),
                      str(alq["id_usuario"]), "operacion", "Cancelado desde el WorkPanel de Operación")
    _sincronizar_bicicleta(str(alq["id_bicicleta"]), estado="disponible")
    return True, ""


def completar(id_alquiler: str, *, id_estacion_fin: str) -> tuple[bool, str]:
    """Registra la devolucion (en_curso -> devuelto). No calcula factura
    ni cobra: eso es un flujo separado (cobrar_presencial.html), fuera
    de alcance aqui."""
    alq = obtener(id_alquiler)
    if not alq:
        return False, "Alquiler no encontrado."
    if alq["estado"] != "en_curso":
        return False, f"Solo se puede completar un alquiler 'en curso' (estado actual: '{alq['estado']}')."

    ahora = datetime.now()
    minutos_reales = max(0, int((ahora - alq["fecha_inicio"]).total_seconds() // 60))

    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.alquileres
        UPDATE estado = 'devuelto', fecha_fin = %(ff)s, minutos_reales = %(mr)s,
               id_estacion_fin = %(ef)s
        WHERE id = %(id)s
    """, parameters={
        "id": id_alquiler, "ff": ahora, "mr": minutos_reales, "ef": id_estacion_fin,
    }, settings={"mutations_sync": 1})

    _insertar_evento(id_alquiler, "en_curso", "devuelto", ahora,
                      str(alq["id_usuario"]), "operacion", "Devolución registrada desde el WorkPanel de Operación")
    _sincronizar_bicicleta(str(alq["id_bicicleta"]), estado="disponible", id_estacion=id_estacion_fin)
    return True, ""


# ── Segmentos de modalidad (cambio de modalidad a mitad de viaje) ───────────
#
# Historial real de segmentos de modalidad, en urbanbike_operativa.alquileres
# -- ver docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md.
# Append-only puro: cada fila se inserta ya completa, nunca se hace UPDATE
# sobre una fila ya insertada.
#
# Nota real: id_usuario/id_bicicleta/id_estacion_inicio (columnas UUID de
# alquileres que referencian dimensiones de ClickHouse, no ids de
# PocketBase) se dejan con su valor DEFAULT -- no hay una forma real de
# resolverlos sin otro join innecesario para este proposito (el vinculo
# real es id_origen_pocketbase, que si es preciso). cantidad_contratada/
# minutos_contratados tampoco se completan -- no aportan nada al calculo
# real de esta tarea.
#
# Estas filas usan origen='segmento_modalidad' (a diferencia de
# origen='migracion_historica' del resto de este repositorio) y se
# insertan sin id_bicicleta/id_usuario reales -- por eso listar()/obtener()
# de arriba (INNER JOIN sobre esas columnas) nunca las muestra: quedan
# invisibles para el WorkPanel de Operacion a proposito.

def cerrar_segmento(*, viaje_id: str, ciclista_id: str, bicicleta_codigo: str,
                     modalidad: str, id_tarifa: str, fecha_inicio: str, fecha_fin: str,
                     subtotal: float, recargo: float) -> None:
    ch.command("""
        INSERT INTO urbanbike_operativa.alquileres
            (id, id_origen_pocketbase, id_tarifa, modalidad,
             fecha_inicio, fecha_fin, estado, subtotal, recargo, total, origen)
        VALUES
            (%(id)s, %(viaje_id)s, %(id_tarifa)s, %(modalidad)s,
             %(fecha_inicio)s, %(fecha_fin)s, 'facturado', %(subtotal)s, %(recargo)s,
             %(total)s, 'segmento_modalidad')
    """, {
        "id": str(uuid.uuid4()), "viaje_id": viaje_id, "id_tarifa": id_tarifa,
        "modalidad": modalidad, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
        "subtotal": round(subtotal, 2), "recargo": round(recargo, 2),
        "total": round(subtotal + recargo, 2),
    })


def total_segmentos_cerrados(viaje_id: str) -> float:
    """Suma real de todos los segmentos ya cerrados de un viaje -- sin
    FINAL porque cada fila se escribe una sola vez y nunca se vuelve a
    tocar (append-only puro, no hay nada que fusionar)."""
    fila = ch.query_one(
        "SELECT sum(total) AS total FROM urbanbike_operativa.alquileres "
        "WHERE id_origen_pocketbase = %(viaje_id)s AND origen = 'segmento_modalidad'",
        {"viaje_id": viaje_id},
    )
    return float(fila["total"] or 0) if fila else 0.0


def segmentos_modalidad(viaje_id: str) -> list[dict]:
    """Cada segmento de modalidad real ya cerrado de un viaje (ver
    cerrar_segmento() y vig_devolver() en empleado.py, que inserta el
    ultimo segmento al finalizar) -- {modalidad, subtotal} en el orden en
    que se cursaron. Usado por _construir_factura_pago() (ciclista.py)
    para las lineas de la factura/detalle de un viaje, y por la vista de
    detalle de viaje (punto 2.3). Nunca lanza: si ClickHouse falla,
    devuelve [] y el llamador cae a su propio fallback (mismo contrato
    que ya tenia esta consulta cuando vivia inline en ciclista.py)."""
    try:
        return ch.query(
            "SELECT modalidad, subtotal FROM urbanbike_operativa.alquileres "
            "WHERE id_origen_pocketbase = %(viaje_id)s AND origen = 'segmento_modalidad' "
            "ORDER BY fecha_inicio",
            {"viaje_id": viaje_id},
        )
    except Exception:
        return []
