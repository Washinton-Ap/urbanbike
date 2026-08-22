"""
ETL paso 22 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14/15/18/19/20/21): agrega a `viajes` los campos de atribucion
real de una alerta atendida, para el punto 2.8 de
docs/Plan_Mejoras_UrbanBike_V2.md (trazabilidad de infracciones y
alertas).

Antes de este script, `viajes.alerta_atendida` era el unico dato --
un booleano sin quien, cuando, ni que se hizo. La pantalla
/empleado/vigilancia/alertas mostraba una columna "Acciones tomadas" que
en realidad solo repetia ese mismo booleano.

Campos nuevos:
  - alerta_atendida_por: nombre/email real del empleado de Vigilancia que
    marco la alerta como atendida (mismo criterio que `resuelta_por` en
    la coleccion `infracciones`, ya existente).
  - alerta_fecha_atencion: fecha real de esa accion (mismo formato ISO
    que usa `_ahora()` en app/routers/empleado.py).
  - alerta_nota: que se hizo realmente (se contacto al ciclista, se
    envio a alguien a verificar, etc.) -- sin esto, "atendida" no dice
    nada util a quien revise el historial despues.

Sin backfill: no hay forma real de reconstruir quien atendio una alerta
ya marcada `alerta_atendida=true` antes de este script -- se deja vacio
a proposito, no se fabrica un dato que nunca existio (mismo criterio que
`agente_id` vacio en el backfill de etl/21).

Mismo mecanismo que etl/15/18/20/21: PATCH del schema completo de la
coleccion. Idempotente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS = [
    {"name": "alerta_atendida_por",   "type": "text", "required": False},
    {"name": "alerta_fecha_atencion", "type": "text", "required": False},
    {"name": "alerta_nota",           "type": "text", "required": False},
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
    print("Agregando campos de trazabilidad de alertas a viajes...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPOS_NUEVOS)
    print("Listo.")


if __name__ == "__main__":
    main()
