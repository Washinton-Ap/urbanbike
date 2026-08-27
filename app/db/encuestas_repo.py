"""Repositorio de la encuesta de satisfaccion opcional (punto 2.11 del
Plan V3, propuesta aprobada por Washington). Colecicon PocketBase real
`encuestas_satisfaccion` (ver etl/25_agregar_encuestas_satisfaccion.py):
3 preguntas con escala 1-5 (bicicleta, proceso de alquiler/devolucion,
satisfaccion general) + observaciones libres opcionales, referenciando
un viaje real ya completado y pagado.

Un viaje real solo puede tener 1 encuesta real -- el indice unico real
de PocketBase (`viaje_id`) es la garantia real contra un doble POST
(ej. el ciclista reabre el enlace de la notificacion despues de ya
haber respondido); `ya_respondida()` es solo para no ofrecer el
banner/formulario de nuevo en pantalla, no la unica defensa real."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.pocketbase import filter_literal, get_admin_client

_PREGUNTAS = ("calificacion_bicicleta", "calificacion_proceso", "calificacion_general")


def _pb():
    return get_admin_client()


def ya_respondida(viaje_id: str) -> bool:
    if not viaje_id:
        return False
    res = _pb().list_records(
        "encuestas_satisfaccion",
        filter=f"viaje_id = {filter_literal(viaje_id)}",
        per_page=1,
    )
    return res.get("totalItems", 0) > 0


def crear(*, viaje_id: str, ciclista_id: str, calificacion_bicicleta: int,
          calificacion_proceso: int, calificacion_general: int, observaciones: str = "") -> dict:
    """Crea la encuesta real -- si el viaje ya tiene una (doble POST real,
    ej. 2 pestañas abiertas), el indice unico de PocketBase rechaza el
    INSERT con un error real, que se relanza tal cual (el llamador ya
    revisa ya_respondida() antes de mostrar el formulario, asi que este
    caso es la defensa de ultima linea, no el camino esperado)."""
    return _pb().create_record("encuestas_satisfaccion", {
        "viaje_id": viaje_id, "ciclista_id": ciclista_id,
        "calificacion_bicicleta": calificacion_bicicleta,
        "calificacion_proceso": calificacion_proceso,
        "calificacion_general": calificacion_general,
        "observaciones": observaciones.strip(),
        "fecha": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })


def resumen() -> dict:
    """Promedio real por pregunta + comentarios reales, para la pantalla
    de Gerente. Nunca lanza: si PocketBase falla, devuelve el resumen
    vacio (0 respuestas, promedios en 0) en vez de tumbar la pantalla."""
    try:
        respuestas = _pb().list_records(
            "encuestas_satisfaccion", sort="-fecha", per_page=500,
        ).get("items", [])
    except Exception:
        respuestas = []

    total = len(respuestas)
    promedios = {}
    for pregunta in _PREGUNTAS:
        valores = [float(r.get(pregunta) or 0) for r in respuestas if r.get(pregunta)]
        promedios[pregunta] = round(sum(valores) / len(valores), 2) if valores else 0.0

    comentarios = [
        {
            "observaciones": r.get("observaciones", ""),
            "fecha": r.get("fecha", ""),
            "calificacion_general": r.get("calificacion_general", 0),
        }
        for r in respuestas if (r.get("observaciones") or "").strip()
    ]

    return {
        "total_respuestas": total,
        "promedio_bicicleta": promedios["calificacion_bicicleta"],
        "promedio_proceso": promedios["calificacion_proceso"],
        "promedio_general": promedios["calificacion_general"],
        "comentarios": comentarios,
    }


def total_pagos_aprobados() -> int:
    """Poblacion real que recibio la invitacion a la encuesta (mismo
    chokepoint real que la dispara, _notificar_pago_aprobado()) -- usado
    como denominador real de la tasa de respuesta en la pantalla de
    Gerente. Nunca lanza: 0 si PocketBase falla, la pantalla ya maneja
    una tasa de 0/0 sin dividir por cero."""
    try:
        return _pb().list_records(
            "pagos", filter='estado = "pagado"', per_page=1,
        ).get("totalItems", 0)
    except Exception:
        return 0
