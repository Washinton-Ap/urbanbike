"""
ETL paso 12 (unico, NO forma parte del DAG horario -- ver
docs/HOJA_DE_RUTA.md): crea las 2 colecciones nuevas de PocketBase que
necesita el rediseno del flujo alquiler/devolucion (punto 13 de
docs/Requerimientos_Mejoras_UrbanBike.md):

  - codigos_descuento: codigo de descuento personal 10%/20% por buena
    conducta (ciclista_id, codigo, porcentaje, usado, ...).
  - notificaciones: campana de notificaciones (usuario_id o rol_destino,
    tipo, titulo, mensaje, leida, ...).

Ademas agrega los campos nuevos que necesitan `viajes` y `pagos`
(colecciones ya existentes): `descuento_codigo`/`descuento_porcentaje` en
viajes (el codigo canjeado al iniciar), y `subtotal`/`recargo_demora`/
`cargo_danos`/`descuento_codigo`/`descuento_monto` en pagos (lineas
separadas del cobro final, ver plan).

PocketBase en este proyecto no tiene migraciones (colecciones creadas a
mano via admin UI, ver pocketbase/entrypoint.sh) -- este script es el
equivalente programatico para no depender de crearlas/editarlas a mano.

Reglas de acceso (listRule/viewRule/createRule/updateRule/deleteRule =
null): mismo criterio que TODAS las colecciones operativas existentes
(pagos, infracciones, viajes, etc. -- verificado en vivo contra la
API admin) -- solo el superusuario (el admin client que ya usa toda la
app) puede leer/escribir, nunca un usuario normal directo.

Idempotente: si la coleccion ya existe (GET /api/collections la lista),
no la vuelve a crear -- correrlo dos veces no falla ni duplica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CODIGOS_DESCUENTO = {
    "name": "codigos_descuento",
    "type": "base",
    "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    "fields": [
        {"name": "ciclista_id",     "type": "text",   "required": False},
        {"name": "codigo",          "type": "text",   "required": False},
        {"name": "porcentaje",      "type": "number", "required": False},
        {"name": "usado",           "type": "bool",   "required": False},
        {"name": "fecha_generado",  "type": "text",   "required": False},
        {"name": "fecha_usado",     "type": "text",   "required": False},
        {"name": "viaje_id_origen", "type": "text",   "required": False},
        {"name": "viaje_id_uso",    "type": "text",   "required": False},
    ],
}

_NOTIFICACIONES = {
    "name": "notificaciones",
    "type": "base",
    "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    "fields": [
        {"name": "usuario_id",   "type": "text", "required": False},
        {"name": "rol_destino",  "type": "text", "required": False},
        {"name": "tipo", "type": "select", "required": False, "maxSelect": 1,
         "values": ["falla", "pago_aprobado", "pago_pendiente", "penalizacion", "orden_asignada"]},
        {"name": "titulo",  "type": "text", "required": False},
        {"name": "mensaje", "type": "text", "required": False, "max": 2000},
        {"name": "enlace",  "type": "text", "required": False},
        {"name": "leida",   "type": "bool", "required": False},
        {"name": "fecha",   "type": "text", "required": False},
    ],
}


_CAMPOS_NUEVOS_VIAJES = [
    {"name": "descuento_codigo",     "type": "text",   "required": False},
    {"name": "descuento_porcentaje", "type": "number", "required": False},
]

_CAMPOS_NUEVOS_PAGOS = [
    {"name": "subtotal",          "type": "number", "required": False},
    {"name": "recargo_demora",    "type": "number", "required": False},
    {"name": "cargo_danos",       "type": "number", "required": False},
    {"name": "descuento_codigo",  "type": "text",    "required": False},
    {"name": "descuento_monto",   "type": "number", "required": False},
    # Bug real encontrado despues de correr esta migracion (ver
    # docs/HOJA_DE_RUTA.md): NINGUNA coleccion operativa de este proyecto
    # (viajes, pagos, infracciones, bicicletas -- verificado en vivo) tiene
    # el created/updated automatico de PocketBase; ciclista.py:_pagos_ciclista()
    # asumia que si lo tenia y ordenaba con sort="-created", que PocketBase
    # rechaza con 400 apenas el campo no existe -- tumbaba /ciclista/pagos
    # entero ("No se pudo conectar con PocketBase"). fecha_generado es el
    # campo real, mismo patron ya usado en el resto del esquema (fecha de
    # texto explicita, nunca el timestamp automatico de PocketBase).
    {"name": "fecha_generado",    "type": "text",   "required": False},
]


def _crear_si_falta(pb, definicion: dict) -> None:
    nombre = definicion["name"]
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    if any(c.get("name") == nombre for c in existentes):
        print(f"  {nombre}: ya existe, sin cambios.")
        return
    pb._post("/api/collections", definicion)
    print(f"  {nombre}: creada.")


def _agregar_campos_si_faltan(pb, nombre_coleccion: str, campos_nuevos: list[dict]) -> None:
    """PATCH del schema completo -- la API de PocketBase reemplaza el
    array `fields` entero, no permite agregar un campo suelto. Se lee la
    coleccion real, se le agregan solo los campos que todavia no tiene
    (por nombre) y se manda de vuelta completa. Idempotente: correrlo de
    nuevo no duplica nada porque el chequeo de "ya existe" es por nombre
    de campo."""
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == nombre_coleccion), None)
    if not coleccion:
        print(f"  {nombre_coleccion}: coleccion no encontrada, se omite.")
        return
    nombres_actuales = {f["name"] for f in coleccion["fields"]}
    faltantes = [c for c in campos_nuevos if c["name"] not in nombres_actuales]
    if not faltantes:
        print(f"  {nombre_coleccion}: los campos nuevos ya existen, sin cambios.")
        return
    coleccion["fields"] = coleccion["fields"] + faltantes
    pb._session.patch(f"{pb.base_url}/api/collections/{coleccion['id']}", json=coleccion).raise_for_status()
    print(f"  {nombre_coleccion}: agregados {[c['name'] for c in faltantes]}.")


def _agregar_valores_select_si_faltan(pb, nombre_coleccion: str, nombre_campo: str, valores_nuevos: list[str]) -> None:
    """Un select de PocketBase rechaza cualquier valor fuera de su lista
    `values` -- agregar 'pago_pendiente' como tipo de notificacion real
    (ver docs/HOJA_DE_RUTA.md, campana) exige extender esa lista en la
    coleccion ya existente, no solo en la definicion de este script.
    Mismo patron de PATCH del schema completo que _agregar_campos_si_faltan."""
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == nombre_coleccion), None)
    if not coleccion:
        print(f"  {nombre_coleccion}.{nombre_campo}: coleccion no encontrada, se omite.")
        return
    campo = next((f for f in coleccion["fields"] if f["name"] == nombre_campo), None)
    if not campo:
        print(f"  {nombre_coleccion}.{nombre_campo}: campo no encontrado, se omite.")
        return
    faltantes = [v for v in valores_nuevos if v not in campo["values"]]
    if not faltantes:
        print(f"  {nombre_coleccion}.{nombre_campo}: los valores nuevos ya existen, sin cambios.")
        return
    campo["values"] = campo["values"] + faltantes
    pb._session.patch(f"{pb.base_url}/api/collections/{coleccion['id']}", json=coleccion).raise_for_status()
    print(f"  {nombre_coleccion}.{nombre_campo}: agregados valores {faltantes}.")


def main() -> None:
    pb = get_admin_client()
    print("Creando colecciones del flujo alquiler/devolucion...")
    _crear_si_falta(pb, _CODIGOS_DESCUENTO)
    _crear_si_falta(pb, _NOTIFICACIONES)
    print("Agregando campos nuevos a colecciones existentes...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPOS_NUEVOS_VIAJES)
    _agregar_campos_si_faltan(pb, "pagos", _CAMPOS_NUEVOS_PAGOS)
    print("Agregando valores nuevos a selects existentes...")
    _agregar_valores_select_si_faltan(pb, "notificaciones", "tipo", ["pago_pendiente"])
    print("Listo.")


if __name__ == "__main__":
    main()
