"""Middleware de autenticación y control de acceso por rol."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

PUBLIC_PREFIXES = ("/auth/", "/static/")

EMPLEADOS = {"admin", "empleado-operacion", "empleado-mantenimiento", "empleado-vigilancia"}

ROLE_RULES: dict[str, set[str]] = {
    "/admin":                  {"admin"},
    "/gerente":                {"admin", "gerente"},
    "/ciclista":               {"admin", "ciclista"},
    # Sub-rutas de empleado (más específicas primero)
    "/empleado/operacion":     {"admin", "empleado-operacion"},
    "/empleado/mantenimiento": {"admin", "empleado-mantenimiento"},
    "/empleado/vigilancia":    {"admin", "empleado-vigilancia"},
    # Fallback para /empleado/dashboard
    "/empleado":               EMPLEADOS,
    # Apartado institucional (punto 8): Gerente + los 3 roles de Empleado,
    # ninguno de los cuales comparte prefijo -- ver app/routers/institucional.py
    "/institucional":          EMPLEADOS | {"gerente"},
}

# Excepción puntual, NO parte del loop general de ROLE_RULES (ver
# docs/HOJA_DE_RUTA.md secciones 39/40): Mantenimiento y Vigilancia
# necesitan poder leer (y Vigilancia además actualizar) el inventario de
# bicicletas, pero la regla general "/empleado/operacion" los bloquearía
# antes de llegar a la ruta -- el loop general no tiene noción de "la
# regla más específica gana" (evaluado y descartado por riesgo, ver
# sección 39: tocar ese algoritmo afecta el mecanismo de acceso de toda
# la app). Esta excepción cubre EXACTAMENTE este prefijo y nada más; el
# permiso fino real (bicicletas:crear/actualizar/eliminar) lo sigue
# aplicando requiere_permiso() en cada ruta, sin cambios.
INVENTARIO_PREFIX = "/empleado/operacion/inventario"
INVENTARIO_ROLES_EXTRA = {"admin", "empleado-operacion", "empleado-mantenimiento", "empleado-vigilancia"}

# Excepcion puntual, mismo criterio que INVENTARIO_PREFIX (NO parte del
# loop general de ROLE_RULES): un ciclista bloqueado tiene una sesion
# limitada bajo request.session["bloqueo"] (nunca "user", ver
# app/routers/auth.py:login()) y la pantalla de bloqueo le ofrece un
# enlace real a su propio historial de pagos -- sin esta excepcion ese
# enlace lo mandaria de vuelta a login (sin "user" no pasa el chequeo
# de abajo), que lo volveria a mandar a /auth/bloqueado en cuanto
# metiera sus credenciales de nuevo, sin llegar nunca al historial.
# Se reconstruye un request.state.user minimo (solo lo que usa esa
# ruta: id/email/name/rol_slug, nunca pb_token) para no tener que
# tocar el codigo real de historial().
HISTORIAL_BLOQUEADO_PATH = "/ciclista/historial"

# Revocacion de sesion en memoria de proceso (ver docs/Requerimientos_Mejoras_UrbanBike.md,
# punto 6): las sesiones son cookies firmadas del lado del cliente (SessionMiddleware),
# sin tabla de sesiones en el servidor -- este set es el unico lugar donde "eliminar una
# cuenta" o "cerrar la sesion de un usuario conectado" (accion independiente desde
# /admin/usuarios, ver app/routers/admin.py:usuarios_cerrar_sesion) pueden dejar rastro
# para que la siguiente request de ese usuario deje de pasar, aunque su cookie de sesion
# siga siendo valida. Vive en memoria porque la app corre en un solo proceso (sin
# workers=N en ningun lado del repo); si eso cambia, este mecanismo necesita moverse a
# un almacen compartido.
#
# La entrada NUNCA se borra sola al consumirse en dispatch() -- se queda hasta el
# siguiente login exitoso de ese usuario (ver app/routers/auth.py:login(), que llama
# limpiar_revocacion()). Eso es a proposito: "cerrar sesion" debe tumbar TODAS las
# sesiones activas de ese usuario (varios dispositivos/pestañas con cookies validas
# distintas), no solo la primera que haga una request -- si se borrara al consumirse,
# un segundo dispositivo con sesion abierta se quedaria conectado.
#
# Guarda user_id -> nombre del admin que revoco, no solo un set de ids: el toast en
# tiempo real ("El administrador X cerro tu sesion", ver
# app/static/js/sesion-tiempo-real.js y GET /auth/estado-sesion) necesita saber
# quien fue, y ese dato solo esta disponible en el momento de la revocacion.
_SESIONES_REVOCADAS: dict[str, str] = {}


def revocar_sesion(user_id: str, admin_nombre: str = "Un administrador") -> None:
    """Fuerza que la proxima request de este usuario (en cualquier dispositivo con
    sesion activa) sea tratada como no autenticada. Llamada por admin.py al eliminar
    una cuenta y al cerrar la sesion de un usuario conectado sin eliminarlo."""
    if user_id:
        _SESIONES_REVOCADAS[user_id] = admin_nombre


def consultar_revocacion(user_id: str) -> str | None:
    """Nombre del admin que revoco la sesion de este usuario, o None si no esta
    revocada. A diferencia del chequeo en dispatch(), NO limpia la sesion -- lo usa
    GET /auth/estado-sesion (app/routers/auth.py), que primero necesita leer el
    nombre antes de que el llamador decida borrar la sesion."""
    return _SESIONES_REVOCADAS.get(user_id)


def limpiar_revocacion(user_id: str) -> None:
    """Quita a este usuario del set de revocacion -- se llama en cada login exitoso
    (ver app/routers/auth.py:login()) para que una revocacion pasada (cierre de sesion
    forzado, o una cuenta eliminada y vuelta a crear con el mismo id) no le impida
    volver a entrar con una sesion nueva."""
    _SESIONES_REVOCADAS.pop(user_id, None)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        user = request.session.get("user")
        if user and user.get("id") in _SESIONES_REVOCADAS:
            request.session.clear()
            user = None
        if not user:
            bloqueo = request.session.get("bloqueo")
            if bloqueo and bloqueo.get("rol_slug") == "ciclista" and path == HISTORIAL_BLOQUEADO_PATH:
                request.state.user = {
                    "id": bloqueo.get("id", ""), "email": bloqueo.get("email", ""),
                    "name": bloqueo.get("name", ""), "rol_slug": "ciclista",
                }
                response = await call_next(request)
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                return response
            return RedirectResponse(f"/auth/login?next={path}", status_code=302)

        request.state.user = user

        rol = user.get("rol_slug", "")

        if path.startswith(INVENTARIO_PREFIX):
            if rol not in INVENTARIO_ROLES_EXTRA:
                return self._rechazar(request)
        else:
            for prefix, allowed_roles in ROLE_RULES.items():
                if path.startswith(prefix) and rol not in allowed_roles:
                    return self._rechazar(request)

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    @staticmethod
    def _rechazar(request: Request) -> RedirectResponse:
        request.session["flash"] = {
            "type": "error",
            "msg": "No tienes permisos para acceder a esa sección.",
        }
        return RedirectResponse("/dashboard", status_code=302)
