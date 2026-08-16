"""
ETL paso 15 (unico, NO forma parte del DAG horario): agrega los 2
campos nuevos que necesita el segmento ABIERTO de un viaje (modalidad
de tarifa real, ver docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md):

  - modalidad_actual: modalidad del segmento en curso (hora/dia/semana).
  - inicio_segmento_actual: cuando empezo ESE segmento (no siempre
    igual a viajes.fecha_inicio, si ya hubo cambios de modalidad antes).

Mismo patron que etl/12_crear_colecciones_flujo.py (PATCH del schema
completo -- PocketBase no permite agregar un campo suelto). Idempotente:
correrlo dos veces no falla ni duplica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS_VIAJES = [
    {"name": "modalidad_actual", "type": "select", "required": False, "maxSelect": 1,
     "values": ["hora", "dia", "semana"]},
    {"name": "inicio_segmento_actual", "type": "text", "required": False},
]


def _agregar_campos_si_faltan(pb, nombre_coleccion: str, campos_nuevos: list[dict]) -> None:
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


def main() -> None:
    pb = get_admin_client()
    print("Agregando campos de modalidad a viajes...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPOS_NUEVOS_VIAJES)
    print("Listo.")


if __name__ == "__main__":
    main()
