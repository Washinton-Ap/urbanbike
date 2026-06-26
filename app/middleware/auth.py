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
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        user = request.session.get("user")
        if not user:
            return RedirectResponse(f"/auth/login?next={path}", status_code=302)

        request.state.user = user

        rol = user.get("rol_slug", "")
        for prefix, allowed_roles in ROLE_RULES.items():
            if path.startswith(prefix) and rol not in allowed_roles:
                request.session["flash"] = {
                    "type": "error",
                    "msg": "No tienes permisos para acceder a esa sección.",
                }
                return RedirectResponse("/dashboard", status_code=302)

        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response
