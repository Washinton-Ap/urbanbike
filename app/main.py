"""Punto de entrada de la aplicación FastAPI de UrbanBike."""

import json
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi import File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import clickhouse as ch
from app.db.pocketbase import PocketBaseClient, PocketBaseError, get_admin_client
from app.middleware.auth import AuthMiddleware
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import gerente as gerente_router
from app.routers import ciclista as ciclista_router
from app.routers import empleado as empleado_router
from app.templating import templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="UrbanBike", docs_url=None, redoc_url=None)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="ub_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=False,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(gerente_router.router)
app.include_router(ciclista_router.router)
app.include_router(empleado_router.router)


# ── Rutas principales ───────────────────────────────────────────────────────

@app.get("/")
def root():
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard")
def dashboard(request: Request):
    user = request.state.user
    rol  = user.get("rol_slug", "")

    destinos = {
        "gerente":                "/gerente/dashboard",
        "ciclista":               "/ciclista/dashboard",
        "empleado-operacion":     "/empleado/operacion/dashboard",
        "empleado-mantenimiento": "/empleado/mantenimiento/dashboard",
        "empleado-vigilancia":    "/empleado/vigilancia/dashboard",
    }
    if rol in destinos:
        return RedirectResponse(destinos[rol], status_code=302)

    # Admin dashboard con KPIs de ClickHouse + gráficas PocketBase
    flash = request.session.pop("flash", None)
    kpis: dict = {}
    ch_ok = True
    try:
        kpis = ch.query_one("""
            SELECT
              count()                           AS total_viajes,
              countDistinct(id_estacion_inicio)  AS total_estaciones,
              round(avg(duracion_min), 2)        AS dur_prom_min,
              countIf(id_membresia = 2)          AS viajes_member,
              countIf(id_membresia = 1)          AS viajes_casual,
              countIf(id_tipo_bicicleta = 1)     AS viajes_clasica,
              countIf(id_tipo_bicicleta = 2)     AS viajes_electrica
            FROM fact_viajes
        """) or {}
    except Exception:
        ch_ok = False

    # Datos PocketBase para gráficas
    rol_labels: list = []
    rol_values: list = []
    bike_labels: list = []
    bike_values: list = []
    bike_colors: list = []
    est_activas = 0
    est_inactivas = 0
    pb_ok = True
    try:
        pb = get_admin_client()
        users = pb.list_records("users", expand="rol", per_page=500).get("items", [])
        rol_map: dict = {}
        for u in users:
            slug = (u.get("expand") or {}).get("rol", {}).get("slug", "sin_rol")
            rol_map[slug] = rol_map.get(slug, 0) + 1
        rol_labels = list(rol_map.keys())
        rol_values = [rol_map[k] for k in rol_labels]

        bikes = pb.list_records("bicicletas", per_page=500).get("items", [])
        bike_map: dict = {"disponible": 0, "en_uso": 0, "mantenimiento": 0, "retirada": 0}
        for b in bikes:
            estado = b.get("estado", "disponible")
            bike_map[estado] = bike_map.get(estado, 0) + 1
        bike_labels = ["Disponible", "En Uso", "Mantenimiento", "Retirada"]
        bike_values = [bike_map["disponible"], bike_map["en_uso"], bike_map["mantenimiento"], bike_map["retirada"]]
        bike_colors = ["#10B981", "#1E86BD", "#F59E0B", "#6B7280"]

        estaciones = pb.list_records("estaciones", per_page=500).get("items", [])
        est_activas   = sum(1 for e in estaciones if e.get("activa"))
        est_inactivas = len(estaciones) - est_activas
    except Exception:
        pb_ok = False

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user, "flash": flash, "title": "Dashboard",
        "kpis": kpis, "ch_ok": ch_ok, "pb_ok": pb_ok,
        "rol_labels":    json.dumps(rol_labels),
        "rol_values":    json.dumps(rol_values),
        "bike_labels":   json.dumps(bike_labels),
        "bike_values":   json.dumps(bike_values),
        "bike_colors":   json.dumps(bike_colors),
        "est_activas":   est_activas,
        "est_inactivas": est_inactivas,
    })


@app.get("/perfil", response_class=HTMLResponse)
def perfil_get(request: Request):
    user  = request.state.user
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "perfil.html", {
        "user": user, "flash": flash, "title": "Mi Perfil",
    })


@app.post("/perfil", response_class=HTMLResponse)
def perfil_post(
    request: Request,
    name:          str = Form(""),
    password:      str = Form(""),
    password_conf: str = Form(""),
    avatar:        UploadFile | None = File(None),
):
    user = request.state.user
    pb   = PocketBaseClient()
    pb.set_token(user["pb_token"])

    errors: list[str] = []
    payload: dict = {}

    if name.strip():
        payload["name"] = name.strip()

    if password:
        if password != password_conf:
            errors.append("Las contraseñas no coinciden.")
        elif len(password) < 8:
            errors.append("La contraseña debe tener al menos 8 caracteres.")
        else:
            payload["password"]        = password
            payload["passwordConfirm"] = password_conf
            payload["oldPassword"]     = ""

    if errors:
        return templates.TemplateResponse(request, "perfil.html", {
            "user": user, "flash": None, "title": "Mi Perfil", "errors": errors,
        }, status_code=422)

    tiene_avatar = avatar is not None and avatar.filename

    if tiene_avatar:
        if avatar.content_type not in ("image/jpeg", "image/png", "image/gif"):
            errors.append("La foto debe ser un archivo JPG, PNG o GIF.")
        if avatar.size and avatar.size > 2 * 1024 * 1024:
            errors.append("La foto no debe superar los 2 MB.")
        if errors:
            return templates.TemplateResponse(request, "perfil.html", {
                "user": user, "flash": None, "title": "Mi Perfil", "errors": errors,
            }, status_code=422)

    if not payload and not tiene_avatar:
        request.session["flash"] = {"type": "info", "msg": "No hubo cambios que guardar."}
        return RedirectResponse("/perfil", status_code=302)

    try:
        if tiene_avatar:
            contenido = avatar.file.read()
            pb.update_record_with_file("users", user["id"], payload,
                {"avatar": (avatar.filename, contenido, avatar.content_type)})
        elif payload:
            pb.update_record("users", user["id"], payload)

        if "name" in payload:
            user["name"] = payload["name"]
        if tiene_avatar:
            actualizado = pb.get_record("users", user["id"])
            user["avatar"] = actualizado.get("avatar", "")
        if "name" in payload or tiene_avatar:
            request.session["user"] = user
        request.session["flash"] = {"type": "success", "msg": "Perfil actualizado correctamente."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al guardar: {e}"}

    return RedirectResponse("/perfil", status_code=302)
