"""Repositorio unico de acceso a bicicletas.

Fuente real (unica): urbanbike_operativa.bicicletas en ClickHouse.
Usado por los tres CRUD de bicicletas que existen hoy (admin, gerente,
empleado-operacion) para no tener la misma logica de acceso a datos
repetida tres veces.

Insertar/Actualizar siempre referencian un modelo YA EXISTENTE
(marca+categoria+specs de modelos_bicicleta) via id_modelo -- esta
pantalla no crea marcas ni modelos nuevos.

--------------------------------------------------------------------
PUENTE TEMPORAL hacia PocketBase (ver docs/HOJA_DE_RUTA.md):
El flujo de reserva del ciclista (ciclista/detalle_bicicleta.html,
resolucion de estacion por nombre, creacion del "viaje") todavia
depende de PocketBase de punta a punta y no se migra hoy. Para que una
bicicleta creada/editada/retirada aqui no quede invisible para ese
flujo, crear/actualizar/eliminar tambien espejan un registro minimo en
PocketBase (codigo/tipo/estado/estacion), buscado por `codigo`.

El espejo es best-effort y unidireccional (ClickHouse -> PocketBase,
nunca al reves): si la escritura en PocketBase falla, NUNCA se revierte
ni se bloquea la operacion real en ClickHouse (que ya tuvo exito antes
de intentar el espejo). El fallo solo se registra con logger.error,
visible en la consola/logs del proceso, para diagnostico y
sincronizacion manual si hiciera falta.

Cuando se migre el flujo de reserva del ciclista a ClickHouse, este
espejo (la funcion `_espejar_pocketbase` y todas sus llamadas) se debe
eliminar por completo -- no es arquitectura final.

Consecuencia real de la direccion unica del espejo (detectada 16-ago-2026,
ver TODO.md raiz): reservar()/finalizar() en app/routers/ciclista.py y
vig_devolver() en app/routers/empleado.py cambian el estado de la
bicicleta escribiendo SOLO en PocketBase -- eso nunca se refleja de
vuelta aqui, asi que el catalogo del ciclista (_catalogo_agrupado() y
_catalogo_bicicletas() en ciclista.py, que leen de ClickHouse) puede
mostrar disponibilidad desfasada hasta que alguien edite esa bicicleta
desde Admin/Gerente.
--------------------------------------------------------------------
"""

from __future__ import annotations

import logging
import math
from datetime import date

from app.db import clickhouse as ch
from app.db.pocketbase import filter_literal, get_admin_client
from app.templating import file_url

logger = logging.getLogger("urbanbike.bicicletas_repo")

DB = "urbanbike_operativa"
UUID_SIN_ESTACION = "00000000-0000-0000-0000-000000000000"
ESTADOS_VALIDOS = ("disponible", "en_uso", "mantenimiento", "retirada")

_TIPO_PB_POR_ELECTRICA = {True: "electric_bike", False: "classic_bike"}


# ── Catalogos para selects (marca+modelo+categoria ya existentes) ──────────

def listar_modelos() -> list[dict]:
    """[{id, label: 'Marca Modelo — Categoria', es_electrica}], para el <select>
    de Insertar/Actualizar. No crea marcas ni modelos nuevos."""
    filas = ch.query("""
        SELECT m.id AS id, mar.nombre AS marca, m.nombre AS modelo,
               c.nombre AS categoria, m.es_electrica AS es_electrica
        FROM urbanbike_operativa.modelos_bicicleta m FINAL
        INNER JOIN urbanbike_operativa.marcas mar FINAL ON mar.id = m.id_marca
        INNER JOIN urbanbike_operativa.categorias c FINAL ON c.id = m.id_categoria
        WHERE m.activo = 1
        ORDER BY mar.nombre, m.nombre
    """)
    for f in filas:
        f["label"] = f"{f['marca']} {f['modelo']} — {f['categoria']}"
    return filas


def listar_estaciones() -> list[dict]:
    """[{id, nombre}], incluye 'Sin asignar' con el UUID sentinela."""
    filas = ch.query("""
        SELECT id, nombre FROM urbanbike_operativa.estaciones FINAL
        WHERE activa = 1 ORDER BY nombre
    """)
    return filas


def listar_categorias() -> list[str]:
    return [r["nombre"] for r in ch.query("""
        SELECT DISTINCT nombre FROM urbanbike_operativa.categorias FINAL
        WHERE activa = 1 ORDER BY nombre
    """)]


def listar_marcas() -> list[str]:
    return [r["nombre"] for r in ch.query("""
        SELECT DISTINCT nombre FROM urbanbike_operativa.marcas FINAL
        WHERE activa = 1 ORDER BY nombre
    """)]


def fotos_por_codigo(codigos: list[str], request=None) -> dict[str, str]:
    """{codigo: foto_url} para un conjunto de bicicletas: ClickHouse
    (bicicleta_fotos) primero, espejo de PocketBase (bicicletas.foto) como
    respaldo -- mismo patron ya usado en ciclista.py/admin.py/gerente.py.
    Reutilizable en cualquier pantalla que solo tenga el codigo (inventario,
    ordenes de mantenimiento, devoluciones).

    `request` opcional, se reenvia a file_url() para que la URL derive del
    host publico real (tunel) en vez del host interno de PocketBase --
    mismo motivo que en avatar_url()/file_url() (app/templating.py). Sin
    request, cae al fallback de pb_public_base() (PB_PUBLIC_URL o
    settings.pb_url)."""
    codigos = list({c for c in codigos if c})
    if not codigos:
        return {}

    filas = ch.query("""
        SELECT b.codigo AS codigo, ifNull(f.url, '') AS foto_url
        FROM urbanbike_operativa.bicicletas b FINAL
        LEFT JOIN urbanbike_operativa.bicicleta_fotos f FINAL ON f.id_bicicleta = b.id AND f.es_principal = 1
        WHERE b.codigo IN %(codigos)s
    """, {"codigos": codigos})
    resultado = {f["codigo"]: f["foto_url"] for f in filas}

    faltantes = [c for c in codigos if not resultado.get(c)]
    if faltantes:
        try:
            pb_items = get_admin_client().list_records("bicicletas", per_page=500).get("items", [])
            pb_por_codigo = {b.get("codigo"): b for b in pb_items}
            for c in faltantes:
                pb_bici = pb_por_codigo.get(c)
                if pb_bici and pb_bici.get("foto"):
                    resultado[c] = file_url("bicicletas", pb_bici["id"], pb_bici["foto"], request=request)
        except Exception:
            pass
    return resultado


# ── Lectura de bicicletas (lista + detalle) ─────────────────────────────────

_SELECT_BASE = """
    SELECT b.id AS id, b.codigo AS codigo, b.estado AS estado,
           b.numero_serie AS numero_serie, b.fecha_adquisicion AS fecha_adquisicion,
           b.km_acumulados AS km_acumulados, b.minutos_uso AS minutos_uso,
           b.fecha_ultimo_mantenimiento AS fecha_ultimo_mantenimiento,
           b.observacion AS observacion,
           m.id AS id_modelo, mar.nombre AS marca, m.nombre AS modelo,
           c.nombre AS categoria, c.es_premium AS es_premium, m.es_electrica AS es_electrica,
           e.id AS id_estacion, ifNull(e.nombre, '') AS estacion_nombre,
           ifNull(f.url, '') AS foto_url
    FROM urbanbike_operativa.bicicletas b FINAL
    INNER JOIN urbanbike_operativa.modelos_bicicleta m FINAL ON m.id = b.id_modelo
    INNER JOIN urbanbike_operativa.marcas mar FINAL ON mar.id = m.id_marca
    INNER JOIN urbanbike_operativa.categorias c FINAL ON c.id = m.id_categoria
    LEFT JOIN urbanbike_operativa.estaciones e FINAL ON e.id = b.id_estacion
    LEFT JOIN urbanbike_operativa.bicicleta_fotos f FINAL ON f.id_bicicleta = b.id AND f.es_principal = 1
"""


def listar(*, q: str = "", marca: str = "", categoria: str = "", estado: str = "",
           page: int = 1, per_page: int = 10) -> tuple[list[dict], int]:
    where = ["1=1"]
    params: dict = {}
    if q:
        where.append("(b.codigo ILIKE %(q)s OR mar.nombre ILIKE %(q)s OR m.nombre ILIKE %(q)s)")
        params["q"] = f"%{q}%"
    if marca:
        where.append("mar.nombre = %(marca)s")
        params["marca"] = marca
    if categoria:
        where.append("c.nombre = %(categoria)s")
        params["categoria"] = categoria
    if estado:
        where.append("b.estado = %(estado)s")
        params["estado"] = estado
    where_sql = " AND ".join(where)

    total = ch.scalar(f"""
        SELECT count() FROM urbanbike_operativa.bicicletas b FINAL
        INNER JOIN urbanbike_operativa.modelos_bicicleta m FINAL ON m.id = b.id_modelo
        INNER JOIN urbanbike_operativa.marcas mar FINAL ON mar.id = m.id_marca
        INNER JOIN urbanbike_operativa.categorias c FINAL ON c.id = m.id_categoria
        WHERE {where_sql}
    """, params) or 0

    page = max(1, page)
    total_paginas = max(1, math.ceil(total / per_page))
    page = min(page, total_paginas)
    offset = (page - 1) * per_page

    filas = ch.query(
        _SELECT_BASE + f" WHERE {where_sql} ORDER BY b.codigo LIMIT {per_page} OFFSET {offset}",
        params,
    )
    return filas, total


def obtener(id_bicicleta: str) -> dict | None:
    filas = ch.query(_SELECT_BASE + " WHERE b.id = %(id)s", {"id": id_bicicleta})
    return filas[0] if filas else None


def contar_alquileres(id_bicicleta: str) -> int:
    return ch.scalar(
        "SELECT count() FROM urbanbike_operativa.alquileres FINAL WHERE id_bicicleta = %(id)s",
        {"id": id_bicicleta},
    ) or 0


def _siguiente_codigo() -> str:
    maximo = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 4))) FROM urbanbike_operativa.bicicletas FINAL "
        "WHERE codigo LIKE 'UB-%'"
    ) or 0
    return f"UB-{maximo + 1:03d}"


# ── Espejo best-effort hacia PocketBase (puente temporal) ───────────────────

def _espejar_pocketbase(operacion: str, codigo: str, id_ch: str, datos_pb: dict | None) -> None:
    """Nunca lanza. Un fallo aqui no debe afectar al llamador: la
    operacion real en ClickHouse ya tuvo exito antes de esta llamada."""
    try:
        pb = get_admin_client()
        existentes = pb.list_records("bicicletas", filter=f'codigo = {filter_literal(codigo)}', per_page=1).get("items", [])
        if operacion == "eliminar":
            if existentes:
                pb.delete_record("bicicletas", existentes[0]["id"])
        elif existentes:
            pb.update_record("bicicletas", existentes[0]["id"], datos_pb)
        else:
            pb.create_record("bicicletas", {"codigo": codigo, **(datos_pb or {})})
    except Exception as e:
        logger.error(
            "ESPEJO POCKETBASE FALLO (%s) codigo=%s id_clickhouse=%s error=%s -- "
            "la operacion en ClickHouse (fuente real) SI se aplico correctamente. "
            "Revisar y sincronizar el espejo a mano si hace falta.",
            operacion, codigo, id_ch, e,
        )


def obtener_mirror_pb_id(codigo: str) -> str | None:
    """Id en PocketBase del espejo de esta bicicleta (por codigo), para
    poder subirle una foto (PocketBase se usa aqui solo como hosting de
    archivos -- ver nota de puente temporal al inicio del archivo)."""
    try:
        existentes = get_admin_client().list_records(
            "bicicletas", filter=f'codigo = {filter_literal(codigo)}', per_page=1,
        ).get("items", [])
        return existentes[0]["id"] if existentes else None
    except Exception as e:
        logger.error("No se pudo resolver el espejo PocketBase de %s para subir foto: %s", codigo, e)
        return None


def guardar_foto_principal(id_bicicleta: str, url: str) -> None:
    """Reemplaza la foto principal de la bicicleta en bicicleta_fotos.
    Borra la fila anterior (si existe) y luego inserta -- mas simple y
    seguro que un INSERT de 'nueva version' con la misma clave, ya que
    aqui no vale la pena arriesgarse a otro bug de clave de orden como
    el de bicicletas.estado."""
    import uuid as _uuid
    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.bicicleta_fotos DELETE WHERE id_bicicleta = %(id)s AND es_principal = 1",
        parameters={"id": id_bicicleta}, settings={"mutations_sync": 1},
    )
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.bicicleta_fotos (id, id_bicicleta, url, es_principal, orden)
        VALUES (%(id)s, %(id_bicicleta)s, %(url)s, 1, 0)
    """, parameters={"id": str(_uuid.uuid4()), "id_bicicleta": id_bicicleta, "url": url})


# ── Escritura (fuente real = ClickHouse; espejo = best-effort) ─────────────

def crear(*, id_modelo: str, estado: str, id_estacion: str, numero_serie: str,
          fecha_adquisicion: date, observacion: str, es_electrica: bool) -> str:
    import uuid
    nuevo_id = str(uuid.uuid4())
    codigo = _siguiente_codigo()
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.bicicletas
            (id, codigo, id_modelo, id_estacion, numero_serie, estado,
             fecha_adquisicion, observacion)
        VALUES
            (%(id)s, %(codigo)s, %(id_modelo)s, %(id_estacion)s, %(numero_serie)s,
             %(estado)s, %(fecha_adquisicion)s, %(observacion)s)
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "id_modelo": id_modelo,
        "id_estacion": id_estacion or UUID_SIN_ESTACION, "numero_serie": numero_serie,
        "estado": estado, "fecha_adquisicion": fecha_adquisicion, "observacion": observacion,
    })

    _espejar_pocketbase("crear", codigo, nuevo_id, {
        "tipo": _TIPO_PB_POR_ELECTRICA[es_electrica], "estado": estado, "notas": observacion,
    })
    return nuevo_id


def _registrar_evento_estado(id_bicicleta: str, *, estado_origen: str, estado_destino: str) -> None:
    """Linea de tiempo de la bicicleta (ver docs/HOJA_DE_RUTA.md seccion
    28) -- solo se llama cuando el estado de verdad cambio. id_actor/
    rol_actor quedan en su sentinela/vacio por defecto: actualizar() no
    recibe el actor real desde ninguno de sus 5 llamadores hoy (a
    diferencia de alquiler_eventos), asi que no se inventa uno."""
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.bicicleta_eventos
            (id_bicicleta, estado_origen, estado_destino)
        VALUES (%(id_bicicleta)s, %(origen)s, %(destino)s)
    """, parameters={
        "id_bicicleta": id_bicicleta, "origen": estado_origen, "destino": estado_destino,
    })


def actualizar(id_bicicleta: str, *, codigo: str, id_modelo: str, estado: str,
               id_estacion: str, numero_serie: str, fecha_adquisicion: date,
               observacion: str, es_electrica: bool) -> None:
    # ALTER ... UPDATE (mutacion in-place), no INSERT de una "nueva version":
    # esta tabla tenia ORDER BY (estado, id) hasta que se corrigio hoy a
    # ORDER BY id (ver docs/HOJA_DE_RUTA.md seccion 9) -- un INSERT con
    # estado distinto habria creado una fila duplicada en vez de
    # reemplazar la existente (ReplacingMergeTree solo deduplica filas
    # con la MISMA clave de orden completa). mutations_sync=1 para que
    # el cambio sea visible de inmediato al recargar la pantalla, no
    # async.
    #
    # El estado anterior se lee ANTES del UPDATE -- es la unica forma de
    # saber si de verdad cambio (bicicleta_eventos solo registra
    # transiciones reales, no cada guardado del formulario aunque el
    # estado se haya dejado igual).
    actual = obtener(id_bicicleta)
    estado_anterior = actual["estado"] if actual else None

    ch.get_client().command("""
        ALTER TABLE urbanbike_operativa.bicicletas
        UPDATE codigo = %(codigo)s, id_modelo = %(id_modelo)s, id_estacion = %(id_estacion)s,
               numero_serie = %(numero_serie)s, estado = %(estado)s,
               fecha_adquisicion = %(fecha_adquisicion)s, observacion = %(observacion)s
        WHERE id = %(id)s
    """, parameters={
        "id": id_bicicleta, "codigo": codigo, "id_modelo": id_modelo,
        "id_estacion": id_estacion or UUID_SIN_ESTACION, "numero_serie": numero_serie,
        "estado": estado, "fecha_adquisicion": fecha_adquisicion, "observacion": observacion,
    }, settings={"mutations_sync": 1})

    if estado_anterior is not None and estado_anterior != estado:
        _registrar_evento_estado(id_bicicleta, estado_origen=estado_anterior, estado_destino=estado)

    _espejar_pocketbase("actualizar", codigo, id_bicicleta, {
        "tipo": _TIPO_PB_POR_ELECTRICA[es_electrica], "estado": estado, "notas": observacion,
    })


def eliminar(id_bicicleta: str) -> tuple[bool, str]:
    """(True, '') si se borro; (False, motivo) si esta bloqueado por
    tener alquileres reales asociados (no se debe perder ese historial)."""
    bici = obtener(id_bicicleta)
    if not bici:
        return False, "Bicicleta no encontrada."

    n_alquileres = contar_alquileres(id_bicicleta)
    if n_alquileres > 0:
        return False, (
            f"No se puede eliminar: tiene {n_alquileres} alquiler(es) real(es) asociado(s). "
            "Cambia su estado a 'Retirada' en vez de eliminarla."
        )

    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.bicicletas DELETE WHERE id = %(id)s",
        parameters={"id": id_bicicleta},
        settings={"mutations_sync": 1},
    )
    # Sin esto, bicicleta_fotos quedaria con una fila huerfana apuntando
    # a un id_bicicleta que ya no existe.
    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.bicicleta_fotos DELETE WHERE id_bicicleta = %(id)s",
        parameters={"id": id_bicicleta},
        settings={"mutations_sync": 1},
    )

    _espejar_pocketbase("eliminar", bici["codigo"], id_bicicleta, None)
    return True, ""
