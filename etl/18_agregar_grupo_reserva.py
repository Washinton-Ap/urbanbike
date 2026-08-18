"""
ETL paso 18 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/14/15): agrega 'grupo_reserva_id' a 'viajes' y 'pagos' -- soporte
real para el punto 0.3 de docs/Plan_Mejoras_UrbanBike_V2.md (factura
unica para varias bicicletas reservadas a la vez).

'viajes.grupo_reserva_id' se llena al crear el viaje (ver
ciclista.py:reservar_grupo()) cuando la reserva vino de una seleccion
multiple -- vacio para reservas individuales (compatibilidad con viajes
existentes). 'pagos.grupo_reserva_id' se copia del viaje al crear el
pago (ver empleado.py:vig_devolver()) para no tener que hacer join con
'viajes' en las pantallas que listan pagos (historial.html, pagos.html).

Mismo mecanismo que etl/15: PATCH del schema completo de la coleccion.
Idempotente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPO_GRUPO = [{"name": "grupo_reserva_id", "type": "text", "required": False}]


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
    print("Agregando grupo_reserva_id a viajes y pagos...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPO_GRUPO)
    _agregar_campos_si_faltan(pb, "pagos", _CAMPO_GRUPO)
    print("Listo.")


if __name__ == "__main__":
    main()
