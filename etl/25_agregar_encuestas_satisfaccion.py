"""
ETL paso 25 (unico, NO forma parte del DAG horario -- mismo criterio que
etl/12_crear_colecciones_flujo.py / etl/13_crear_coleccion_soporte.py):
crea la coleccion de PocketBase para la encuesta de satisfaccion opcional
(punto 2.11 del Plan V3, propuesta aprobada por Washington):

  - encuestas_satisfaccion: una fila por encuesta real respondida por un
    ciclista sobre un viaje puntual ya completado y pagado. 3 preguntas
    con escala 1-5 (bicicleta, proceso de alquiler/devolucion,
    satisfaccion general) + observaciones libres opcionales. Un viaje
    real solo puede tener una encuesta real (index unico sobre
    viaje_id) -- evita que el banner del comprobante, si se reabre la
    pagina, deje respondido el mismo viaje dos veces.

Tambien agrega el valor nuevo "encuesta_satisfaccion" al select
notificaciones.tipo (mismo mecanismo ya usado en etl/12/13/14/19).

Reglas de acceso (listRule/viewRule/createRule/updateRule/deleteRule =
null): mismo criterio que todas las colecciones operativas existentes --
solo el superusuario (el admin client que ya usa toda la app) puede
leer/escribir.

Idempotente: si la coleccion ya existe, no la vuelve a crear.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_ENCUESTAS_SATISFACCION = {
    "name": "encuestas_satisfaccion",
    "type": "base",
    "listRule": None, "viewRule": None, "createRule": None, "updateRule": None, "deleteRule": None,
    "fields": [
        {"name": "viaje_id",               "type": "text",   "required": True},
        {"name": "ciclista_id",            "type": "text",   "required": True},
        {"name": "calificacion_bicicleta", "type": "number", "required": True, "min": 1, "max": 5},
        {"name": "calificacion_proceso",   "type": "number", "required": True, "min": 1, "max": 5},
        {"name": "calificacion_general",   "type": "number", "required": True, "min": 1, "max": 5},
        {"name": "observaciones",          "type": "text",   "required": False, "max": 1000},
        {"name": "fecha",                  "type": "text",   "required": False},
    ],
    "indexes": ["CREATE UNIQUE INDEX idx_encuesta_viaje ON encuestas_satisfaccion (viaje_id)"],
}


def _crear_si_falta(pb, definicion: dict) -> None:
    """Mismo criterio que etl/13_crear_coleccion_soporte.py (no se
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
    print("Creando coleccion de encuestas de satisfaccion...")
    _crear_si_falta(pb, _ENCUESTAS_SATISFACCION)
    print("Agregando valor nuevo al select notificaciones.tipo...")
    _agregar_valores_select_si_faltan(pb, "notificaciones", "tipo", ["encuesta_satisfaccion"])
    print("Listo.")


if __name__ == "__main__":
    main()
