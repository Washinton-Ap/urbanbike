"""
ETL paso 20 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14/19): agrega el campo `referencia_id` a la coleccion
`notificaciones`, necesario para el fix real del bug de descarte
prematuro (una notificacion de "accion pendiente" -- pago por cobrar,
transferencia por verificar, devolucion por validar -- ya no se puede
descartar con un clic; solo se cierra cuando la accion real que
referencia (un pago o un viaje puntual) se resuelve del todo, ver
app/db/notificaciones_repo.py:resolver_pendiente()).

Mismo mecanismo ya usado en etl/12 (_agregar_campos_si_faltan): PATCH del
schema completo de la coleccion. Idempotente: correrlo dos veces no falla
ni duplica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPO_REFERENCIA_ID = [
    {"name": "referencia_id", "type": "text", "required": False},
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
    print("Agregando referencia_id a notificaciones...")
    _agregar_campos_si_faltan(pb, "notificaciones", _CAMPO_REFERENCIA_ID)
    print("Listo.")


if __name__ == "__main__":
    main()
