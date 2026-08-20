"""Códigos de descuento personales por buena conducta (10%/20%, ver
docs/Requerimientos_Mejoras_UrbanBike.md punto 13).

Distinto de `promociones` (ClickHouse, campañas compartidas con código
público y límite de usos total): un código de este repo solo lo puede
canjear el ciclista dueño (`ciclista_id`), una sola vez -- coleccion
PocketBase `codigos_descuento`, creada por etl/12_crear_colecciones_flujo.py.

Se genera en ciclista.py:finalizar() cuando el ciclista no tiene
infracciones activas al momento de reportar la devolución. Se canjea en
ciclista.py:reservar(), en el paso de confirmación de tarifa del
siguiente viaje.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db.pocketbase import filter_literal, get_admin_client


def _pb():
    return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generar(ciclista_id: str, porcentaje: int, viaje_id_origen: str) -> dict:
    """Crea un código nuevo, sin usar. El texto del código nunca se
    reutiliza entre ciclistas (uuid4 real), así que no hace falta
    comprobar colisión."""
    codigo = f"UB-{uuid.uuid4().hex[:6].upper()}"
    return _pb().create_record("codigos_descuento", {
        "ciclista_id":       ciclista_id,
        "codigo":            codigo,
        "porcentaje":        porcentaje,
        "usado":             False,
        "fecha_generado":    _ahora(),
        "fecha_usado":       "",
        "viaje_id_origen":   viaje_id_origen,
        "viaje_id_uso":      "",
    })


def obtener_valido(codigo: str, ciclista_id: str) -> dict | None:
    """Lectura, sin marcar nada -- válido si existe, pertenece a este
    ciclista y todavía no fue usado. None en cualquier otro caso
    (código ajeno, ya usado, o inexistente -- mismo mensaje genérico
    para las tres cosas del lado del llamador, no hay que distinguir
    "no es tuyo" de "no existe")."""
    if not codigo.strip():
        return None
    try:
        res = _pb().list_records(
            "codigos_descuento",
            filter=f'codigo = {filter_literal(codigo.strip().upper())} && '
                    f'ciclista_id = {filter_literal(ciclista_id)} && usado = false',
            per_page=1,
        )
        items = res.get("items", [])
        return items[0] if items else None
    except Exception:
        return None


def marcar_usado(id_codigo: str, viaje_id_uso: str) -> None:
    _pb().update_record("codigos_descuento", id_codigo, {
        "usado": True, "fecha_usado": _ahora(), "viaje_id_uso": viaje_id_uso,
    })


def revertir_uso(id_codigo: str) -> None:
    """Deshace marcar_usado() -- para cuando una reserva que ya lo marcó
    usado termina revertida por completo (ej. reservar_grupo() falla a
    mitad del lote y hace rollback de los viajes creados, ver
    _revertir_reserva_grupal() en ciclista.py). Sin esto, el código
    queda quemado para un ciclista que en los hechos nunca completó la
    reserva -- hallazgo real de la 3a ronda de revisión de la Task C5,
    ya había quedado señalado sin resolver en el fix round 1 de C2 (ver
    docs/HOJA_DE_RUTA.md). Seguro de llamar incluso si el código nunca
    llegó a marcarse usado -- deja los mismos valores por defecto que
    generar() ya usa, así que no hay diferencia observable entre
    "nunca se marcó" y "se marcó y se revirtió"."""
    _pb().update_record("codigos_descuento", id_codigo, {
        "usado": False, "fecha_usado": "", "viaje_id_uso": "",
    })
