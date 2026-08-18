"""
ETL paso 14 (unico, NO forma parte del DAG horario -- mismo criterio que
etl/12/13): agrega los 3 tipos de notificacion nuevos que necesitan las
2 mejoras cerradas hoy sobre el catalogo de notificaciones auditado
(ver docs/HOJA_DE_RUTA.md seccion 69):

  - membresia_por_vencer -- aviso anticipado real (app/db/membresias_repo.py:procesar_por_vencer_hoy).
  - membresia_vencida    -- aviso real al vencer sin renovacion (app/db/membresias_repo.py:procesar_vencidas_hoy).
  - infraccion           -- notificacion propia, separada del mensaje
    generico de "falla" donde iba mezclada (app/routers/empleado.py).

Mismo mecanismo ya usado en etl/12 (agregar "pago_pendiente") y etl/13
(agregar "mensaje_soporte") -- PATCH del schema completo de la
coleccion, porque la API de PocketBase no permite agregar un valor
suelto a un select existente.

Idempotente: si el valor ya esta en la lista, no lo vuelve a agregar.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402


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
    print("Agregando tipos de notificacion nuevos...")
    _agregar_valores_select_si_faltan(
        pb, "notificaciones", "tipo",
        ["membresia_por_vencer", "membresia_vencida", "infraccion"],
    )
    print("Listo.")


if __name__ == "__main__":
    main()
