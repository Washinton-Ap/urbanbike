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

import threading
from datetime import datetime, timezone

from app.db.pocketbase import filter_literal, get_admin_client


def _pb():
    return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Tipos cuya notificación representa una acción todavía pendiente de
# resolverse del todo (pago por cobrar/verificar, devolución por validar
# físicamente) -- estas NUNCA se descartan con un clic (ver
# notificaciones_marcar_leida()/notificaciones_marcar_todas() en main.py,
# que las rechazan explícitamente). El único camino real para que
# desaparezcan es resolver_pendiente(), llamado desde el punto exacto del
# código donde la acción subyacente se completa de verdad (pago aprobado
# o rechazado, devolución validada por Vigilancia) -- nunca por la sola
# interacción del usuario con la campana.
TIPOS_PROTEGIDOS = frozenset({"pago_pendiente", "cobro_pendiente", "devolucion_pendiente_validar"})


def crear(*, tipo: str, titulo: str, mensaje: str, usuario_id: str = "", rol_destino: str = "",
          enlace: str = "", referencia_id: str = "") -> dict:
    """Exactamente una de usuario_id/rol_destino debe venir llena --
    quien llama decide si es un aviso puntual o una difusión de rol.
    referencia_id identifica el registro real (pago, viaje, ...) cuya
    resolución cierra esta notificación cuando tipo está en
    TIPOS_PROTEGIDOS -- ver resolver_pendiente()."""
    return _pb().create_record("notificaciones", {
        "usuario_id":    usuario_id,
        "rol_destino":   rol_destino,
        "tipo":          tipo,
        "titulo":        titulo,
        "mensaje":       mensaje,
        "enlace":        enlace,
        "referencia_id": referencia_id,
        "leida":         False,
        "fecha":         _ahora(),
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
    permisos_repo.set_excepcion_masiva()). Las de TIPOS_PROTEGIDOS se
    saltan a propósito: 'marcar todas' tampoco puede descartar una acción
    que sigue pendiente, ver resolver_pendiente()."""
    no_leidas = listar_no_leidas(usuario_id, rol_slug, limite=200)
    tocadas = 0
    for n in no_leidas:
        if n.get("tipo") in TIPOS_PROTEGIDOS:
            continue
        marcar_leida(n["id"])
        tocadas += 1
    return tocadas


def resolver_pendiente(*, tipo: str, referencia_id: str, usuario_id: str = "", rol_destino: str = "") -> int:
    """Único camino real para cerrar una notificación de TIPOS_PROTEGIDOS:
    se llama desde el punto del código donde la acción subyacente
    (referencia_id -- un pago o un viaje real) se resolvió de verdad, no
    desde una interacción de clic. Exactamente uno de usuario_id/rol_destino
    debe venir lleno, igual que en crear(). Best-effort: nunca debe poder
    tumbar el flujo real (pago, devolución) que la dispara.

    También cierra las notificaciones PREVIAS a este fix, que no tienen
    referencia_id (campo agregado en etl/20) -- sin este fallback se
    quedarían bloqueadas para siempre, sin ninguna acción real que las
    pudiera resolver. Es una concesión deliberada solo para datos viejos:
    de aquí en adelante toda notificación protegida nace con referencia_id
    real, así que el fallback deja de tener candidatas con el tiempo."""
    if not referencia_id or not (usuario_id or rol_destino):
        return 0
    destinatario = f'usuario_id = {filter_literal(usuario_id)}' if usuario_id \
        else f'rol_destino = {filter_literal(rol_destino)}'
    try:
        res = _pb().list_records(
            "notificaciones",
            filter=f'{destinatario} && tipo = {filter_literal(tipo)} '
                   f'&& (referencia_id = {filter_literal(referencia_id)} || referencia_id = "") && leida = false',
            per_page=20,
        )
        items = res.get("items", [])
    except Exception:
        return 0
    for n in items:
        try:
            marcar_leida(n["id"])
        except Exception:
            pass
    return len(items)


def notificar_usuario(pb, usuario_id: str, *, tipo: str, titulo: str, mensaje: str,
                       enlace: str = "", referencia_id: str = "") -> None:
    """Punto único real para avisar a un usuario puntual (ver
    docs/Requerimientos_Mejoras_UrbanBike.md, punto 11.1): crea la
    notificación de la campana Y manda el correo real, resolviendo
    nombre/email desde PocketBase `users` -- así ciclista.py/empleado.py
    no repiten esa resolución en cada disparador. Best-effort de punta a
    punta: ni la campana ni el correo deben poder tumbar el flujo real
    (pago, inspección, devolución) que los dispara.

    El envío del correo (punto 1.14 del Plan V3, ver docs/HOJA_DE_RUTA.md
    sección 109/110) se dispara en un hilo aparte, sin esperarlo: medido
    en real, el handshake SMTP contra Brevo tarda 7-9s de punta a punta
    (mayormente esperando el saludo inicial del servidor, no la conexión
    TCP en sí, que es instantánea) -- bloqueaba el único event loop de
    FastAPI entero ese tiempo, para CUALQUIER usuario de la app, cada vez
    que se disparaba un correo en cualquier parte del sistema (viaje
    iniciado, devolución validada, pago aprobado -- no solo transferencia).
    El correo real sigue llegando igual, solo que unos segundos después de
    que el ciclista/empleado ya recibió su respuesta -- ver
    email_client.py:_enviar_correo(), que ahora deja un log real de éxito
    (antes solo lo hacía en caso de fallo) como única traza de que sí
    salió, ya que quien llamó a esta función ya terminó para cuando el
    envío real se resuelve."""
    if not usuario_id:
        return
    try:
        crear(usuario_id=usuario_id, tipo=tipo, titulo=titulo, mensaje=mensaje,
              enlace=enlace, referencia_id=referencia_id)
    except Exception:
        pass
    try:
        usuario = pb.get_record("users", usuario_id)
        email = usuario.get("email", "")
        nombre = usuario.get("name") or email
        if email:
            from app.email_client import enviar_notificacion
            threading.Thread(
                target=enviar_notificacion, args=(email, nombre, titulo, mensaje),
                daemon=True,
            ).start()
    except Exception:
        pass


def notificar_rol(rol_destino: str, *, tipo: str, titulo: str, mensaje: str,
                   enlace: str = "", referencia_id: str = "") -> None:
    """Difusión a todo un rol (ej. 'empleado-mantenimiento' cuando se
    asigna una orden nueva) -- solo campana, sin correo masivo a todo el
    equipo. El destinatario puntual de la acción (ej. el técnico
    asignado) recibe su propio aviso vía notificar_usuario()."""
    try:
        crear(rol_destino=rol_destino, tipo=tipo, titulo=titulo, mensaje=mensaje,
              enlace=enlace, referencia_id=referencia_id)
    except Exception:
        pass


def resolver_pago(pago_id: str, ciclista_id: str) -> None:
    """Punto único real para cerrar TODO lo que quedó pendiente por un pago
    concreto cuando este se aprueba (tarjeta inmediata, efectivo o
    transferencia verificada) -- ver empleado.py:_notificar_pago_aprobado()
    y ciclista.py:confirmar_pago() (tarjeta), los únicos caminos reales que
    marcan un pago 'pagado'. Cierra tanto el aviso del ciclista
    ('pago_pendiente') como el de Operación ('cobro_pendiente'), best-effort."""
    if not pago_id:
        return
    if ciclista_id:
        resolver_pendiente(tipo="pago_pendiente", referencia_id=pago_id, usuario_id=ciclista_id)
    resolver_pendiente(tipo="cobro_pendiente", referencia_id=pago_id, rol_destino="empleado-operacion")
