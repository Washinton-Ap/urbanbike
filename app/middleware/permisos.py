"""Dependencia de FastAPI para control de acceso fino por permiso (ver
docs/HOJA_DE_RUTA.md secciones 29/30). Se agrega ruta por ruta con
`dependencies=[Depends(requiere_permiso("recurso:accion"))]`, en vez de
la verificacion fija de rol que hoy vive en app/middleware/auth.py
(ROLE_RULES) -- esa sigue activa sin tocar; esta dependencia se suma
encima para las rutas migradas, no la reemplaza globalmente.
"""

from __future__ import annotations

from fastapi import Request

from app.db.permisos_repo import tiene_permiso


class PermisoDenegadoError(Exception):
    """Se captura en app/main.py y se convierte en el mismo tipo de
    redirect+flash que ya usa AuthMiddleware, para que el usuario vea
    exactamente el mismo comportamiento sea cual sea el mecanismo que
    lo bloqueo."""

    def __init__(self, mensaje: str = "No tienes permisos para realizar esta acción."):
        self.mensaje = mensaje


def requiere_permiso(codigo: str):
    """Fabrica de dependencia: requiere_permiso("bicicletas:crear")
    devuelve la funcion que FastAPI ejecuta antes del handler de la
    ruta. Lee el rol desde request.state.user (ya la puso AuthMiddleware
    en esta misma request) -- nunca de un parametro que el cliente
    pudiera manipular."""

    def _dependencia(request: Request) -> None:
        user = getattr(request.state, "user", None) or request.session.get("user") or {}
        rol_slug = user.get("rol_slug", "")
        id_usuario = user.get("id", "")
        if not tiene_permiso(rol_slug, codigo, id_usuario):
            raise PermisoDenegadoError()

    return _dependencia
