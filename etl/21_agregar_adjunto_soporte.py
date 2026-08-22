"""
ETL paso 21 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14/15/18/19/20): expande `mensajes_soporte` para el punto 2.4 de
docs/Plan_Mejoras_UrbanBike_V2.md (chat de soporte, version completa).

Campos nuevos:
  - conversacion_id: reemplaza a `ciclista_id` como identificador real de
    "que hilo es este mensaje" -- un mismo ciclista ahora puede tener mas
    de una conversacion (agente distinto, motivo distinto). `ciclista_id`
    se queda (denormalizado igual que siempre en este proyecto), ya no
    identifica el hilo por si solo.
  - agente_id / agente_nombre: el empleado de Vigilancia elegido al
    iniciar esa conversacion puntual (nunca Admin, ver auditoria del
    punto 2.4) -- denormalizado en cada mensaje del mismo hilo para poder
    filtrar/listar sin JOIN, mismo criterio que `bicicleta_codigo` en
    ordenes_mantenimiento.
  - motivo: select (infraccion/consulta_general/otro), elegido una sola
    vez al iniciar el chat, denormalizado igual que agente_id.
  - adjunto: campo `file` real -- imagen/PDF o video, un archivo por
    mensaje (ver limites en app/db/mensajes_soporte_repo.py).
  - eliminado / eliminado_por / eliminado_en: soft-delete -- un mensaje de
    soporte puede ser evidencia real de un reclamo o de una promesa hecha
    por Vigilancia, asi que nunca se hace DELETE real (mismo criterio que
    la bitacora "append-only" y que ordenes_repo.eliminar()/
    bicicletas_repo.eliminar(), que bloquean el borrado si hay evidencia
    real asociada).

Backfill real (no solo agregar campos vacios): a la fecha de este script
existen 13 mensajes reales de pruebas anteriores de Washington
(2 conversaciones reales, sin `conversacion_id` porque el modelo viejo
identificaba el hilo solo con `ciclista_id`). Dejarlos con
`conversacion_id` vacio los volveria invisibles para siempre en la UI
nueva (que filtra por `conversacion_id`, no por `ciclista_id`) -- eso
seria perder evidencia real sin necesidad, lo mismo que el proyecto evita
en cualquier otro lado. El backfill les asigna `conversacion_id` =
`ciclista_id` (la misma agrupacion que ya tenian, exacta) y
`motivo = "otro"` (no hay forma real de reconstruir un motivo que nunca
se capturo) -- `agente_id` se deja vacio a proposito: el modelo viejo era
un buzon de rol completo, no de una persona, e inventar un agente puntual
para esas 13 filas seria fabricar un dato que nunca existio.

Mismo mecanismo que etl/15/18/20: PATCH del schema completo de la
coleccion. Idempotente en ambas partes (agregar campos y backfill).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS = [
    {"name": "conversacion_id", "type": "text", "required": False},
    {"name": "agente_id",       "type": "text", "required": False},
    {"name": "agente_nombre",   "type": "text", "required": False},
    {"name": "motivo", "type": "select", "required": False, "maxSelect": 1,
     "values": ["infraccion", "consulta_general", "otro"]},
    {"name": "adjunto", "type": "file", "required": False, "maxSelect": 1,
     "maxSize": 20 * 1024 * 1024,
     "mimeTypes": [
         "image/jpeg", "image/png", "image/gif", "application/pdf",
         "video/mp4", "video/quicktime", "video/webm",
     ]},
    {"name": "eliminado",      "type": "bool", "required": False},
    {"name": "eliminado_por",  "type": "text", "required": False},
    {"name": "eliminado_en",   "type": "text", "required": False},
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


def _backfill_conversacion_id(pb) -> None:
    items = pb.list_records("mensajes_soporte", per_page=500).get("items", [])
    pendientes = [m for m in items if not m.get("conversacion_id") and m.get("ciclista_id")]
    if not pendientes:
        print("  backfill: nada pendiente (0 mensajes sin conversacion_id).")
        return
    for m in pendientes:
        pb.update_record("mensajes_soporte", m["id"], {
            "conversacion_id": m["ciclista_id"],
            "motivo": m.get("motivo") or "otro",
        })
    print(f"  backfill: {len(pendientes)} mensajes reales migrados a conversacion_id = ciclista_id.")


def main() -> None:
    pb = get_admin_client()
    print("Agregando campos nuevos a mensajes_soporte...")
    _agregar_campos_si_faltan(pb, "mensajes_soporte", _CAMPOS_NUEVOS)
    print("Backfill de conversaciones reales existentes...")
    _backfill_conversacion_id(pb)
    print("Listo.")


if __name__ == "__main__":
    main()
