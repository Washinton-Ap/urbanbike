"""Proteccion CSRF real: un token por sesion, verificado en cada
POST/PUT/PATCH/DELETE con formulario (ver docs/HOJA_DE_RUTA.md,
auditoria de seguridad). Antes no existia ningun mecanismo dedicado --
la unica mitigacion era SameSite=Lax en la cookie de sesion (indirecta,
no pensada para esto).
"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
METODOS_PROTEGIDOS = {"POST", "PUT", "PATCH", "DELETE"}
_CONTENT_TYPES_FORM = ("application/x-www-form-urlencoded", "multipart/form-data")


def get_csrf_token(request: Request) -> str:
    """Token real de esta sesion (se genera una sola vez y se reutiliza,
    no uno nuevo por request). Expuesto a las plantillas como global de
    Jinja (app/templating.py) para el campo oculto de cada <form>."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


class CSRFMiddleware(BaseHTTPMiddleware):
    """Debe registrarse de forma que corra DESPUES de que SessionMiddleware
    haya poblado request.session (ver orden real en app/main.py)."""

    async def dispatch(self, request: Request, call_next):
        # Se asegura de que el token exista desde la primera request (el
        # GET que renderiza el formulario), para que el campo oculto
        # siempre tenga un valor real que coincida con el que se valida
        # en el POST subsecuente de esa misma sesion.
        get_csrf_token(request)

        if request.method in METODOS_PROTEGIDOS:
            content_type = request.headers.get("content-type", "")
            if any(ct in content_type for ct in _CONTENT_TYPES_FORM):
                # BaseHTTPMiddleware solo re-envia el body al handler real
                # si algo llamo a request.body() (lo cachea en request._body);
                # request.form() por si solo usa request.stream(), que NO se
                # cachea para el downstream -- sin este await, el endpoint
                # real recibiria un body vacio y Form(...) fallaria con 422.
                await request.body()
                form = await request.form()
                enviado = form.get(CSRF_FORM_FIELD, "")
                esperado = request.session.get(CSRF_SESSION_KEY, "")
                if not esperado or not secrets.compare_digest(str(enviado), str(esperado)):
                    return PlainTextResponse(
                        "Solicitud rechazada: token CSRF inválido o ausente. "
                        "Recarga la página e intenta de nuevo.",
                        status_code=403,
                    )

        return await call_next(request)
