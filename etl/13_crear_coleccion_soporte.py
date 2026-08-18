"""
ETL paso 13 (unico, NO forma parte del DAG horario -- mismo criterio que
etl/12_crear_colecciones_flujo.py): crea la coleccion de PocketBase que
necesita el chat interno de soporte (punto 12 de
docs/Requerimientos_Mejoras_UrbanBike.md, Opcion B -- ver
docs/HOJA_DE_RUTA.md seccion 68):

  - mensajes_soporte: un renglon por mensaje de una conversacion
    ciclista <-> soporte (Vigilancia/Admin). Una conversacion = todos los
    mensajes con el mismo `ciclista_id`, sin coleccion de "conversaciones"
    aparte -- no hace falta, el ciclista_id ya la identifica de punta a
    punta.

Tambien agrega el valor nuevo "mensaje_soporte" al select `tipo` de la
coleccion `notificaciones` ya existente (mismo mecanismo que ya se uso
para agregar "pago_pendiente" en etl/12) -- el chat reutiliza la campana
de notificaciones real para avisar de mensajes nuevos entre paginas, sin
sondeo aparte (ver docs/HOJA_DE_RUTA.md seccion 68).

Reglas de acceso (listRule/viewRule/createRule/updateRule/deleteRule =
null): mismo criterio que TODAS las colecciones operativas existentes
(notificaciones, codigos_descuento, etc.) -- solo el superusuario (el
admin client que ya usa toda la app) puede leer/escribir.

Idempotente: si la coleccion ya existe, no la vuelve a crear.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_MENSAJES_SOPORTE = {
    "name": "mensajes_soporte",
    "type": "base",
    "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    "fields": [
        {"name": "ciclista_id",  "type": "text",   "required": False},
        {"name": "autor_id",     "type": "text",   "required": False},
        {"name": "autor_rol",    "type": "text",   "required": False},
        {"name": "autor_nombre", "type": "text",   "required": False},
        {"name": "texto",        "type": "text",   "required": False, "max": 2000},
        {"name": "leido",        "type": "bool",   "required": False},
        {"name": "fecha",        "type": "text",   "required": False},
    ],
}


def _crear_si_falta(pb, definicion: dict) -> None:
    """Mismo criterio que etl/12_crear_colecciones_flujo.py (no se
    importa de ahi: cada script numerado del ETL es autocontenido)."""
    nombre = definicion["name"]
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    if any(c.get("name") == nombre for c in existentes):
        print(f"  {nombre}: ya existe, sin cambios.")
        return
    pb._post("/api/collections", definicion)
    print(f"  {nombre}: creada.")


def _agregar_valores_select_si_faltan(pb, nombre_coleccion: str, nombre_campo: str, valores_nuevos: list[str]) -> None:
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
    print("Creando coleccion de soporte...")
    _crear_si_falta(pb, _MENSAJES_SOPORTE)
    print("Agregando valor nuevo al select notificaciones.tipo...")
    _agregar_valores_select_si_faltan(pb, "notificaciones", "tipo", ["mensaje_soporte"])
    print("Listo.")


if __name__ == "__main__":
    main()
