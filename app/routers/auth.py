"""
Rutas de autenticación: GET /auth/login, POST /auth/login, GET /auth/logout.

Flujo de login:
  1. Usuario envía email + password via formulario HTML.
  2. Se llama a PocketBase /api/collections/users/auth-with-password.
  3. Si ok, almacenamos en session: token PB, datos del usuario y rol.
  4. Redirigimos al dashboard (o al `next` si venía de una ruta protegida).
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.db.pocketbase import PocketBaseClient, PocketBaseError, registrar_auditoria
from app.templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/dashboard"):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "auth/login.html", {"next": next})


@router.post("/login")
async def login(
    request: Request,
    email:    str = Form(...),
    password: str = Form(...),
    next:     str = Form("/dashboard"),
):
    pb = PocketBaseClient()
    try:
        data = await run_in_threadpool(pb.auth_user, email, password)
    except PocketBaseError as e:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"next": next, "error": "Correo o contraseña incorrectos."},
            status_code=401,
        )

    token  = data["token"]
    record = data["record"]

    # Obtener datos del rol (expand)
    pb.set_token(token)
    try:
        full = await run_in_threadpool(pb.get_record, "users", record["id"], "rol")
        rol_obj = full.get("expand", {}).get("rol", {})
    except Exception:
        rol_obj = {}

    user = {
        "id":        record["id"],
        "email":     record.get("email", ""),
        "name":      record.get("name", email.split("@")[0]),
        "pb_token":  token,
        "rol_id":    rol_obj.get("id", ""),
        "rol_slug":  rol_obj.get("slug", ""),
        "rol_nombre":rol_obj.get("nombre", ""),
        "avatar":    record.get("avatar", ""),
    }
    request.session["user"] = user

    registrar_auditoria(token, user["id"], user["name"], user["email"],
                        "login", "sistema", "Inicio de sesión", request,
                        usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""))

    # Seguridad: solo redirigir a rutas internas
    safe_next = next if next.startswith("/") else "/dashboard"
    return RedirectResponse(safe_next, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    user = request.session.get("user") or {}
    if user:
        registrar_auditoria(user.get("pb_token", ""), user.get("id", ""),
                            user.get("name", ""), user.get("email", ""),
                            "logout", "sistema", "Cierre de sesión", request,
                            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""))
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=302)
