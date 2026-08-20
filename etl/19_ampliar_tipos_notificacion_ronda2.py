"""
ETL paso 17 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14): agrega los 8 tipos de notificacion nuevos que cierran los
ganchos reales identificados en el punto 0.4 de
docs/Plan_Mejoras_UrbanBike_V2.md (auditoria completa del catalogo de 22
tipos de notificacion en docs/HOJA_DE_RUTA.md):

  - viaje_iniciado               -- ciclista.py:reservar()
  - pago_rechazado               -- empleado.py:op_pagos_rechazar_transferencia()
  - promocion_nueva              -- gerente.py:promociones_crear()
  - devolucion_validada          -- empleado.py:vig_devolver()
  - cobro_pendiente              -- ciclista.py:pago_confirmar(), empleado.py (transferencia presencial)
  - devolucion_pendiente_validar -- ciclista.py:finalizar()
  - bici_disponible              -- empleado.py:vig_mantenimiento_certificar()
  - registro_nuevo               -- auth.py:registro_post()

Mismo mecanismo ya usado en etl/12/13/14: PATCH del schema completo de la
coleccion (la API de PocketBase no permite agregar un valor suelto a un
select existente). Idempotente: correrlo dos veces no falla ni duplica nada.
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
    print("Agregando tipos de notificacion nuevos (ronda 2)...")
    _agregar_valores_select_si_faltan(
        pb, "notificaciones", "tipo",
        ["viaje_iniciado", "pago_rechazado", "promocion_nueva", "devolucion_validada",
         "cobro_pendiente", "devolucion_pendiente_validar", "bici_disponible", "registro_nuevo"],
    )
    print("Listo.")


if __name__ == "__main__":
    main()
