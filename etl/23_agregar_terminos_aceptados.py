"""
ETL paso 23 (unico, NO forma parte del DAG horario -- mismo patron que
etl/15/18/20/21/22): agrega el campo de aceptacion de la Declaracion de
Uso del Sistema (modal de terminos y condiciones, punto de lanzamiento).

Campo nuevo en `users`:
  - terminos_aceptados_en: fecha/hora (UTC) de la ULTIMA aceptacion real
    del checkbox -- se sobrescribe en cada aceptacion (registro publico Y
    cada login exitoso de cualquier rol, ver app/routers/auth.py y
    app/middleware/auth.py). Campo unico, no un log de eventos: se decidio
    asi a proposito (ver conversacion del punto de lanzamiento) porque el
    requisito real es "cuando acepto por ultima vez", no una traza legal
    de cada evento -- si eso llegara a hacer falta, se agrega una
    coleccion de log aparte despues, sin tocar este campo.

Mismo mecanismo que etl/21/22: PATCH del schema completo de la coleccion.
Idempotente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS = [
    {"name": "terminos_aceptados_en", "type": "date", "required": False},
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
    print("Agregando campo terminos_aceptados_en a users...")
    _agregar_campos_si_faltan(pb, "users", _CAMPOS_NUEVOS)
    print("Listo.")


if __name__ == "__main__":
    main()
