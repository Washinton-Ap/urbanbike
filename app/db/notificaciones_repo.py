"""Campana de notificaciones (ver docs/Requerimientos_Mejoras_UrbanBike.md,
puntos 11.1 y 13): centro simple, sin infraestructura de tiempo real nueva
-- se lee al cargar la página y se refresca con el mismo sondeo de 4s que
ya usa app/static/js/sesion-tiempo-real.js para la sesión.

Colección PocketBase `notificaciones` (creada por
etl/12_crear_colecciones_flujo.py). Cada fila tiene exactamente uno de
`usuario_id` (destinatario puntual, ej. un ciclista o un técnico) o
`rol_destino` (difusión a todo un rol, ej. "empleado-mantenimiento" cuando
se asigna una orden nueva) -- nunca los dos a la vez.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.pocketbase import filter_literal, get_admin_client


def _pb():
    return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def crear(*, tipo: str, titulo: str, mensaje: str, usuario_id: str = "", rol_destino: str = "", enlace: str = "") -> dict:
    """Exactamente una de usuario_id/rol_destino debe venir llena --
    quien llama decide si es un aviso puntual o una difusión de rol."""
    return _pb().create_record("notificaciones", {
        "usuario_id":  usuario_id,
        "rol_destino": rol_destino,
        "tipo":        tipo,
        "titulo":      titulo,
        "mensaje":     mensaje,
        "enlace":      enlace,
        "leida":       False,
        "fecha":       _ahora(),
    })


def _filtro_destinatario(usuario_id: str, rol_slug: str) -> str:
    partes = [f'usuario_id = {filter_literal(usuario_id)}']
    if rol_slug:
        partes.append(f'rol_destino = {filter_literal(rol_slug)}')
    return "(" + " || ".join(partes) + ")"


def listar_no_leidas(usuario_id: str, rol_slug: str, limite: int = 20) -> list[dict]:
    if not usuario_id:
        return []
    try:
        res = _pb().list_records(
            "notificaciones",
            filter=f'{_filtro_destinatario(usuario_id, rol_slug)} && leida = false',
            sort="-fecha", per_page=limite,
        )
        return res.get("items", [])
    except Exception:
        return []


def contar_no_leidas(usuario_id: str, rol_slug: str) -> int:
    if not usuario_id:
        return 0
    try:
        res = _pb().list_records(
            "notificaciones",
            filter=f'{_filtro_destinatario(usuario_id, rol_slug)} && leida = false',
            per_page=1,
        )
        return res.get("totalItems", 0)
    except Exception:
        return 0


def obtener(id_notificacion: str) -> dict | None:
    try:
        return _pb().get_record("notificaciones", id_notificacion)
    except Exception:
        return None


def marcar_leida(id_notificacion: str) -> None:
    _pb().update_record("notificaciones", id_notificacion, {"leida": True})


def marcar_todas_leidas(usuario_id: str, rol_slug: str) -> int:
    """Devuelve cuántas se marcaron -- PocketBase no tiene update masivo,
    así que se hace una a una (volumen esperado bajo, mismo criterio que
    permisos_repo.set_excepcion_masiva())."""
    no_leidas = listar_no_leidas(usuario_id, rol_slug, limite=200)
    for n in no_leidas:
        marcar_leida(n["id"])
    return len(no_leidas)


def notificar_usuario(pb, usuario_id: str, *, tipo: str, titulo: str, mensaje: str, enlace: str = "") -> None:
    """Punto único real para avisar a un usuario puntual (ver
    docs/Requerimientos_Mejoras_UrbanBike.md, punto 11.1): crea la
    notificación de la campana Y manda el correo real, resolviendo
    nombre/email desde PocketBase `users` -- así ciclista.py/empleado.py
    no repiten esa resolución en cada disparador. Best-effort de punta a
    punta: ni la campana ni el correo deben poder tumbar el flujo real
    (pago, inspección, devolución) que los dispara."""
    if not usuario_id:
        return
    try:
        crear(usuario_id=usuario_id, tipo=tipo, titulo=titulo, mensaje=mensaje, enlace=enlace)
    except Exception:
        pass
    try:
        usuario = pb.get_record("users", usuario_id)
        email = usuario.get("email", "")
        nombre = usuario.get("name") or email
        if email:
            from app.email_client import enviar_notificacion
            enviar_notificacion(email, nombre, titulo, mensaje)
    except Exception:
        pass


def notificar_rol(rol_destino: str, *, tipo: str, titulo: str, mensaje: str, enlace: str = "") -> None:
    """Difusión a todo un rol (ej. 'empleado-mantenimiento' cuando se
    asigna una orden nueva) -- solo campana, sin correo masivo a todo el
    equipo. El destinatario puntual de la acción (ej. el técnico
    asignado) recibe su propio aviso vía notificar_usuario()."""
    try:
        crear(rol_destino=rol_destino, tipo=tipo, titulo=titulo, mensaje=mensaje, enlace=enlace)
    except Exception:
        pass
