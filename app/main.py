"""Punto de entrada de la aplicación FastAPI de UrbanBike."""

import json
from pathlib import Path

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi import File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db import clickhouse as ch, notificaciones_repo
from app.db.pocketbase import PocketBaseClient, PocketBaseError, get_admin_client
from app.middleware.auth import AuthMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.permisos import PermisoDenegadoError
from app.reportes.comun import ReporteVacioError
from app.routers import auth as auth_router
from app.routers import admin as admin_router
from app.routers import gerente as gerente_router
from app.routers import ciclista as ciclista_router
from app.routers import empleado as empleado_router
from app.routers import institucional as institucional_router
from app.guia_contenido import GUIA
from app.templating import templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="UrbanBike", docs_url=None, redoc_url=None)

app.add_middleware(AuthMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="ub_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=settings.is_production,
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

@app.exception_handler(PermisoDenegadoError)
async def permiso_denegado_handler(request: Request, exc: PermisoDenegadoError):
    """Mismo comportamiento (redirect + flash) que AuthMiddleware ya usa
    para su verificacion de rol por prefijo -- una ruta migrada a
    requiere_permiso() se ve identica al usuario final, cambia solo el
    mecanismo interno (ver docs/HOJA_DE_RUTA.md secciones 29/30)."""
    request.session["flash"] = {"type": "error", "msg": exc.mensaje}
    return RedirectResponse("/dashboard", status_code=302)


@app.exception_handler(ReporteVacioError)
async def reporte_vacio_handler(request: Request, exc: ReporteVacioError):
    """Mismo patrón que permiso_denegado_handler: flash + redirect en vez
    de dejar que el StreamingResponse se genere vacío. El redirect vuelve
    a la página desde la que se pidió el export (Referer) -- solo si es
    del mismo origen, para no abrir un open-redirect con un Referer
    falsificado."""
    import urllib.parse
    request.session["flash"] = {"type": "error", "msg": "No hay datos para exportar. El reporte está vacío."}
    referer = request.headers.get("referer", "")
    destino = "/dashboard"
    if referer:
        partes = urllib.parse.urlparse(referer)
        if partes.netloc == request.url.netloc:
            destino = partes.path or "/dashboard"
            if partes.query:
                destino += f"?{partes.query}"
    return RedirectResponse(destino, status_code=302)


app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(gerente_router.router)
app.include_router(ciclista_router.router)
app.include_router(empleado_router.router)
app.include_router(institucional_router.router)


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
    cedula:        str = Form(""),
):
    user = request.state.user
    pb   = PocketBaseClient()
    pb.set_token(user["pb_token"])

    errors: list[str] = []
    payload: dict = {}

    if name.strip():
        payload["name"] = name.strip()

    if cedula.strip():
        if not cedula.strip().isdigit() or len(cedula.strip()) != 10:
            errors.append("La cédula debe tener exactamente 10 dígitos numéricos.")
        else:
            payload["cedula"] = cedula.strip()

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
        if "cedula" in payload:
            user["cedula"] = payload["cedula"]
        if tiene_avatar:
            actualizado = pb.get_record("users", user["id"])
            user["avatar"] = actualizado.get("avatar", "")
        if "name" in payload or "cedula" in payload or tiene_avatar:
            request.session["user"] = user
        request.session["flash"] = {"type": "success", "msg": "Perfil actualizado correctamente."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al guardar: {e}"}

    return RedirectResponse("/perfil", status_code=302)


@app.post("/perfil/borrar-avatar")
def perfil_borrar_avatar(request: Request):
    user = request.state.user
    pb   = PocketBaseClient()
    pb.set_token(user["pb_token"])
    try:
        pb.update_record_with_file("users", user["id"], {}, {"avatar": ("", b"", "application/octet-stream")})
        user["avatar"] = ""
        request.session["user"] = user
        request.session["flash"] = {"type": "success", "msg": "Avatar eliminado correctamente."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al eliminar el avatar: {e}"}
    return RedirectResponse("/perfil", status_code=302)


# ── Campana de notificaciones (punto 13/11.1) — compartida por los 3 actores,
# igual que /dashboard y /perfil de arriba, ver app/static/js/campana-notificaciones.js ──

@app.get("/notificaciones")
def notificaciones_listar(request: Request):
    user = request.state.user
    usuario_id, rol_slug = user.get("id", ""), user.get("rol_slug", "")
    items = notificaciones_repo.listar_no_leidas(usuario_id, rol_slug, limite=15)
    return JSONResponse({
        "total": notificaciones_repo.contar_no_leidas(usuario_id, rol_slug),
        # El frontend (campana-notificaciones.js) usa esto para decidir cuáles
        # no se pueden descartar con un clic -- se manda desde acá, en vez de
        # duplicar la lista a mano en JS, para que nunca queden desincronizadas.
        "tipos_protegidos": sorted(notificaciones_repo.TIPOS_PROTEGIDOS),
        "items": [
            {
                "id": n.get("id", ""),
                "tipo": n.get("tipo", ""),
                "titulo": n.get("titulo", ""),
                "mensaje": n.get("mensaje", ""),
                "enlace": n.get("enlace", ""),
                "fecha": n.get("fecha", ""),
            }
            for n in items
        ],
    })


@app.post("/notificaciones/{nid}/marcar-leida")
def notificaciones_marcar_leida(request: Request, nid: str):
    user = request.state.user
    n = notificaciones_repo.obtener(nid)
    # Solo el dueño puntual o alguien con el rol al que se difundio puede
    # marcarla leida -- mismo criterio de propiedad que ya usa
    # ciclista.py para pagos/comprobantes ajenos.
    if n and (n.get("usuario_id") == user.get("id", "") or
              (n.get("rol_destino") and n.get("rol_destino") == user.get("rol_slug", ""))):
        # Una notificacion de accion pendiente (pago por cobrar/verificar,
        # devolucion por validar) no se descarta con un clic -- solo
        # desaparece cuando notificaciones_repo.resolver_pendiente() la
        # cierra desde el punto real donde esa accion se resolvio. Rechazo
        # explicito aqui, no solo en el frontend: un POST directo a este
        # endpoint no puede saltarse la regla.
        if n.get("tipo") in notificaciones_repo.TIPOS_PROTEGIDOS:
            return JSONResponse({"ok": False, "motivo": "pendiente"})
        notificaciones_repo.marcar_leida(nid)
    return JSONResponse({"ok": True})


@app.post("/notificaciones/marcar-todas")
def notificaciones_marcar_todas(request: Request):
    user = request.state.user
    tocadas = notificaciones_repo.marcar_todas_leidas(user.get("id", ""), user.get("rol_slug", ""))
    return JSONResponse({"ok": True, "tocadas": tocadas})


# ── Guía de uso por rol (punto 1.9) -- mismo patrón que /dashboard y
# /perfil de arriba: ruta compartida sin prefijo de rol, el contenido
# varía según user["rol_slug"] (ver app/guia_contenido.py) ────────────────

@app.get("/guia", response_class=HTMLResponse)
def guia(request: Request):
    user = request.state.user
    rol = user.get("rol_slug", "")
    contenido = GUIA.get(rol)
    return templates.TemplateResponse(request, "guia.html", {
        "user": user, "title": "Guía de uso",
        "contenido": contenido,
    })
