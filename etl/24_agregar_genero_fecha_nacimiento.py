"""
ETL paso 24 (unico, NO forma parte del DAG horario -- mismo patron que
etl/15/18/20/21/22/23): agrega genero y fecha de nacimiento al registro
de ciclistas (punto 1.13 del Plan V3).

Campos nuevos en `users`:
  - genero: texto libre validado en el router (app/routers/auth.py,
    _GENEROS_VALIDOS: femenino/masculino/otro/prefiero_no_decir) -- texto
    plano en vez de un "select" de PocketBase, mismo criterio que
    cedula/telefono (la validacion real vive en el servidor, no en el
    esquema).
  - fecha_nacimiento: fecha real de nacimiento, capturada solo desde el
    registro nuevo (auth.py:registro_post). Sin backfill: no hay forma
    real de reconstruir la fecha de nacimiento de las cuentas ya
    existentes -- quedan vacias, mismo criterio que otros campos nuevos
    de este proyecto (ver etl/20/22).

Mismo mecanismo que etl/21/22/23: PATCH del schema completo de la
coleccion. Idempotente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS = [
    {"name": "genero", "type": "text", "required": False},
    {"name": "fecha_nacimiento", "type": "date", "required": False},
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
    print("Agregando campos genero y fecha_nacimiento a users...")
    _agregar_campos_si_faltan(pb, "users", _CAMPOS_NUEVOS)
    print("Listo.")


if __name__ == "__main__":
    main()
