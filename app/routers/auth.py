"""
Rutas de autenticación: GET /auth/login, POST /auth/login, GET /auth/logout.

Flujo de login:
  1. Usuario envía email + password via formulario HTML.
  2. Se llama a PocketBase /api/collections/users/auth-with-password.
  3. Si ok, almacenamos en session: token PB, datos del usuario y rol.
  4. Redirigimos al dashboard (o al `next` si venía de una ruta protegida).
"""

import re
import secrets
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.db import notificaciones_repo
from app.db.pocketbase import (
    PocketBaseClient, PocketBaseError, filter_literal, get_admin_client,
    primer_email_por_rol, registrar_auditoria, rol_id_por_slug,
)
from app.middleware.auth import consultar_revocacion, limpiar_revocacion
from app.email_client import enviar_codigo_restablecimiento, enviar_codigo_verificacion
from app.templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/dashboard"):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "auth/login.html", {"next": next, "flash": flash})


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
    except PocketBaseError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"next": next, "error": "Correo o contraseña incorrectos."},
            status_code=401,
        )
    except requests.exceptions.RequestException:
        # PocketBase inalcanzable (down, reiniciando, etc.) -- causa real
        # distinta de credenciales incorrectas, y antes ni siquiera se
        # atrapaba: requests.exceptions.ConnectionError no es una
        # PocketBaseError, así que se colaba como excepción sin capturar y
        # tumbaba la request entera con un 500 genérico (ver
        # docs/HOJA_DE_RUTA.md, bug real reportado en /auth/restablecer,
        # mismo patrón en este mismo archivo).
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"next": next, "error": "No se pudo conectar con el servicio de autenticación. Intenta de nuevo en un momento."},
            status_code=503,
        )

    token  = data["token"]
    record = data["record"]

    if not record.get("verified", False):
        # Bloqueo real (no solo un aviso): sin sesion "user", AuthMiddleware
        # trata esto igual que un anonimo -- no hay forma de colarse a
        # ninguna ruta protegida sin verificar. Redirige directo al mismo
        # flujo de /auth/verificar que usa el registro (reenvia codigo
        # incluido), no a un mensaje muerto sin salida.
        request.session["verificar_email"] = email
        request.session["flash"] = {
            "type": "error",
            "msg": "Verifica tu correo antes de iniciar sesión. Ingresa el código que te enviamos (o pide uno nuevo).",
        }
        return RedirectResponse("/auth/verificar", status_code=302)

    # Obtener datos del rol (expand)
    pb.set_token(token)
    try:
        full = await run_in_threadpool(pb.get_record, "users", record["id"], "rol")
        rol_obj = full.get("expand", {}).get("rol", {})
    except Exception:
        rol_obj = {}

    if not record.get("activo", True):
        # Sesion limitada bajo una clave distinta a "user": AuthMiddleware
        # nunca la reconoce como sesion valida (rechaza cualquier ruta
        # protegida igual que a un anonimo), asi que no hace falta tocar
        # ROLE_RULES ni el resto del control de acceso. Los datos
        # especificos del rol (pagos pendientes / correo de gerente o
        # admin) se resuelven en vivo en /auth/bloqueado, no aca, para
        # que siempre reflejen el estado real del momento en que se ven.
        request.session["bloqueo"] = {
            "id":             record["id"],
            "email":          record.get("email", ""),
            "name":           record.get("name", email.split("@")[0]),
            "rol_slug":       rol_obj.get("slug", ""),
            "motivo_bloqueo": record.get("motivo_bloqueo", ""),
        }
        return RedirectResponse("/auth/bloqueado", status_code=302)

    user = {
        "id":        record["id"],
        "email":     record.get("email", ""),
        "name":      record.get("name", email.split("@")[0]),
        "pb_token":  token,
        "rol_id":    rol_obj.get("id", ""),
        "rol_slug":  rol_obj.get("slug", ""),
        "rol_nombre":rol_obj.get("nombre", ""),
        "avatar":    record.get("avatar", ""),
        "cedula":    record.get("cedula", ""),
        "telefono":  record.get("telefono", ""),
    }
    limpiar_revocacion(user["id"])
    request.session["user"] = user
    # Declaracion de uso del sistema: se re-exige en CADA login (no solo la
    # primera vez), asi que vive en la sesion -- AuthMiddleware redirige a
    # /auth/terminos en la siguiente request mientras esta bandera siga
    # activa, sin importar a donde apunte `safe_next` mas abajo.
    request.session["terminos_pendientes"] = True

    registrar_auditoria(token, user["id"], user["name"], user["email"],
                        "login", "sistema", "Inicio de sesión", request,
                        usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""))

    # Seguridad: solo redirigir a rutas internas
    safe_next = next if next.startswith("/") else "/dashboard"
    return RedirectResponse(safe_next, status_code=302)


@router.get("/terminos", response_class=HTMLResponse)
async def terminos_page(request: Request, next: str = "/dashboard"):
    # No usa PUBLIC_PREFIXES para saltarse esto: /auth/terminos SI necesita
    # sesion iniciada (a diferencia de /auth/login o /auth/registro), solo
    # que AuthMiddleware no la exige aca porque todo "/auth/" queda fuera de
    # su chequeo -- se valida a mano, igual que hace registro_page() arriba.
    if not request.session.get("user"):
        return RedirectResponse(f"/auth/login?next={next}", status_code=302)
    safe_next = next if next.startswith("/") else "/dashboard"
    return templates.TemplateResponse(request, "auth/terminos.html", {"next": safe_next})


@router.post("/terminos")
async def terminos_post(
    request: Request,
    terminos_aceptados: str = Form(""),
    next: str = Form("/dashboard"),
):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/auth/login", status_code=302)

    safe_next = next if next.startswith("/") else "/dashboard"

    if not terminos_aceptados:
        # Defensa real, no solo del boton deshabilitado del lado del cliente
        # (ver auth/terminos.html): un POST directo sin el checkbox no limpia
        # la bandera, asi que AuthMiddleware lo vuelve a mandar aca.
        return templates.TemplateResponse(request, "auth/terminos.html", {
            "next": safe_next,
            "error": "Debes marcar la casilla para continuar.",
        }, status_code=422)

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        pb = get_admin_client()
        await run_in_threadpool(pb.update_record, "users", user["id"], {
            "terminos_aceptados_en": ahora,
        })
    except Exception:
        # Best-effort, igual que registrar_auditoria(): la bandera de sesion
        # (mas abajo) es el gate real -- si PocketBase esta caido un
        # instante, no tiene sentido atrapar al usuario sin poder avanzar
        # por no poder escribir un campo informativo.
        pass

    request.session.pop("terminos_pendientes", None)
    registrar_auditoria(user.get("pb_token", ""), user["id"], user.get("name", ""), user.get("email", ""),
                        "actualizar", "usuarios", "Aceptó la declaración de uso del sistema", request,
                        usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""))
    return RedirectResponse(safe_next, status_code=302)


_CEDULA_PATTERN = re.compile(r"^[0-9]{10}$")
_TELEFONO_PATTERN = re.compile(r"^[0-9]{10}$")
_CODIGO_VIGENCIA_MIN = 15
# Punto 1.13 del Plan V3 -- mismas 4 opciones que el <select> de registro.html.
_GENEROS_VALIDOS = ("femenino", "masculino", "otro", "prefiero_no_decir")


def _generar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def _emitir_codigo(pb, user_id: str, email: str, nombre: str) -> bool:
    """Genera un código real de 6 dígitos, lo guarda en el usuario con su
    expiración (15 min) y lo envía por correo. Devuelve si el correo salió
    (best-effort -- el código igual queda guardado aunque el envío falle,
    así /auth/verificar/reenviar puede reintentar sin regenerar dos veces)."""
    codigo = _generar_codigo()
    expira = (datetime.now(timezone.utc) + timedelta(minutes=_CODIGO_VIGENCIA_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await run_in_threadpool(pb.update_record, "users", user_id, {
        "codigo_verificacion": codigo,
        "codigo_verificacion_expira": expira,
    })
    return await run_in_threadpool(enviar_codigo_verificacion, email, nombre, codigo)


async def _emitir_codigo_reset(pb, user_id: str, email: str, nombre: str) -> bool:
    """Mismo patrón exacto que _emitir_codigo, para restablecimiento de
    contraseña en vez de verificación de cuenta -- código propio
    (codigo_reset/codigo_reset_expira), mismo campo `email` que llama."""
    codigo = _generar_codigo()
    expira = (datetime.now(timezone.utc) + timedelta(minutes=_CODIGO_VIGENCIA_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await run_in_threadpool(pb.update_record, "users", user_id, {
        "codigo_reset": codigo,
        "codigo_reset_expira": expira,
    })
    return await run_in_threadpool(enviar_codigo_restablecimiento, email, nombre, codigo)


@router.get("/registro", response_class=HTMLResponse)
async def registro_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(request, "auth/registro.html", {})


@router.post("/registro")
async def registro_post(
    request: Request,
    nombre:        str = Form(...),
    apellido:      str = Form(...),
    email:         str = Form(...),
    cedula:        str = Form(...),
    telefono:      str = Form(...),
    genero:        str = Form(...),
    fecha_nacimiento: str = Form(...),
    password:      str = Form(...),
    password_conf: str = Form(...),
    terminos_aceptados: str = Form(""),
):
    def error(msg: str, status_code: int = 422):
        return templates.TemplateResponse(request, "auth/registro.html", {
            "error": msg, "nombre": nombre, "apellido": apellido,
            "email": email, "cedula": cedula, "telefono": telefono,
            "genero": genero, "fecha_nacimiento": fecha_nacimiento,
        }, status_code=status_code)

    nombre   = nombre.strip()
    apellido = apellido.strip()
    email    = email.strip().lower()
    cedula   = cedula.strip()
    telefono = telefono.strip()

    if not nombre or not apellido:
        return error("Nombre y apellido son obligatorios.")
    if not _CEDULA_PATTERN.match(cedula):
        return error("La cédula debe tener exactamente 10 dígitos numéricos.")
    if not _TELEFONO_PATTERN.match(telefono):
        return error("El teléfono debe tener exactamente 10 dígitos numéricos.")
    if genero not in _GENEROS_VALIDOS:
        return error("Selecciona un género válido.")
    # Punto 1.13 del Plan V3: nadie puede haber nacido en el futuro --
    # defensa real, no solo el `max` del <input type="date"> del cliente
    # (un POST directo puede saltarselo sin problema).
    try:
        fecha_nacimiento_dt = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
    except ValueError:
        return error("Fecha de nacimiento inválida.")
    if fecha_nacimiento_dt > datetime.now(timezone.utc).date():
        return error("La fecha de nacimiento no puede ser una fecha futura.")
    if password != password_conf:
        return error("Las contraseñas no coinciden.")
    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")
    if not terminos_aceptados:
        # Defensa real, no solo del lado del cliente (ver auth/registro.html,
        # que ya deshabilita el submit hasta marcar el checkbox): un POST
        # directo a esta ruta sin pasar por el modal no puede crear la cuenta.
        return error("Debes aceptar la declaración de uso del sistema para continuar.")

    try:
        pb = get_admin_client()
        dup_cedula = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'cedula = {filter_literal(cedula)}', per_page=1,
        )
        if dup_cedula.get("totalItems", 0) > 0:
            return error("Ya existe una cuenta registrada con esa cédula.")

        rol_id = await run_in_threadpool(rol_id_por_slug, "ciclista")
        if not rol_id:
            return error("No se pudo completar el registro. Intenta más tarde.", 500)

        nombre_completo = f"{nombre} {apellido}"
        nuevo = await run_in_threadpool(pb.create_record, "users", {
            "email":           email,
            "password":        password,
            "passwordConfirm": password_conf,
            "emailVisibility": True,
            "name":            nombre_completo,
            "cedula":          cedula,
            "telefono":        telefono,
            "genero":          genero,
            "fecha_nacimiento": fecha_nacimiento_dt.strftime("%Y-%m-%d"),
            "rol":             rol_id,
            "activo":          True,
            "verified":        False,
            # Hora del servidor, no del cliente (evita desfaces/manipulacion
            # de reloj) -- momento real en que se marco y confirmo el checkbox.
            "terminos_aceptados_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except PocketBaseError as e:
        # Bug real encontrado y corregido (ver docs/HOJA_DE_RUTA.md): el
        # mensaje superior de PocketBase para CUALQUIER fallo de validación
        # es siempre el genérico "Failed to create record." -- el motivo
        # real (ej. correo duplicado) solo vive en el detalle por campo
        # (`e.data`), que antes se descartaba por completo en
        # `PocketBaseClient._handle()`. El `if "email" in str(e)` de acá
        # nunca podía coincidir con nada, así que un correo duplicado real
        # (el caso más común) siempre caía en el mensaje genérico de abajo.
        if "email" in e.data:
            return error("Ya existe una cuenta registrada con ese correo.")
        if "cedula" in e.data:
            return error("La cédula no tiene un formato válido o ya está en uso.")
        return error("No se pudo completar el registro. Verifica los datos e intenta de nuevo.")
    except requests.exceptions.RequestException:
        # Mismo hueco real que en login()/verificar_post()/restablecer_post()
        # (ver docs/HOJA_DE_RUTA.md): requests.exceptions.ConnectionError
        # (PocketBase inalcanzable) no es una PocketBaseError, así que sin
        # esta rama se colaba como excepción sin capturar y tumbaba la
        # request con un 500 genérico en vez de este mensaje.
        return error("No se pudo completar el registro. Intenta de nuevo en un momento.", 503)

    correo_enviado = await _emitir_codigo(pb, nuevo["id"], email, nombre_completo)

    registrar_auditoria(
        "", nuevo["id"], nombre_completo, email, "crear", "usuarios",
        "Registro público de ciclista (pendiente de verificación)", request, usuario_rol="ciclista",
    )

    notificaciones_repo.notificar_rol(
        "admin", tipo="registro_nuevo",
        titulo="Nuevo registro de ciclista",
        mensaje=f"{nombre_completo} ({email}) se registró como ciclista.",
        enlace="/admin/usuarios",
    )

    request.session["verificar_email"] = email
    request.session["flash"] = {
        "type": "info",
        "msg": ("Te enviamos un código de verificación a tu correo."
                if correo_enviado else
                "Cuenta creada, pero no pudimos enviarte el correo. Usa \"Reenviar código\" para intentar de nuevo."),
    }
    return RedirectResponse("/auth/verificar", status_code=302)


@router.get("/verificar", response_class=HTMLResponse)
async def verificar_page(request: Request, email: str = ""):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    if email:
        request.session["verificar_email"] = email.strip().lower()
    destino = request.session.get("verificar_email")
    if not destino:
        return RedirectResponse("/auth/login", status_code=302)
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "auth/verificar.html", {
        "email": destino, "flash": flash,
    })


@router.post("/verificar")
async def verificar_post(request: Request, codigo: str = Form(...)):
    destino = request.session.get("verificar_email")
    if not destino:
        return RedirectResponse("/auth/login", status_code=302)

    def error(msg: str):
        return templates.TemplateResponse(request, "auth/verificar.html", {
            "email": destino, "error": msg,
        }, status_code=422)

    try:
        pb = get_admin_client()
        res = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'email = {filter_literal(destino)}', per_page=1,
        )
        items = res.get("items", [])
        if not items:
            return error("No encontramos esa cuenta. Regístrate de nuevo.")
        user = items[0]

        codigo_real = (user.get("codigo_verificacion") or "").strip()
        expira_raw  = user.get("codigo_verificacion_expira") or ""
        vencido = True
        if expira_raw:
            try:
                expira = datetime.fromisoformat(expira_raw.replace("Z", "+00:00"))
                vencido = datetime.now(timezone.utc) > expira
            except Exception:
                vencido = True

        if not codigo_real or vencido:
            return error("El código venció. Pide uno nuevo con \"Reenviar código\".")
        if not secrets.compare_digest(codigo.strip(), codigo_real):
            return error("El código no es correcto. Intenta de nuevo.")

        await run_in_threadpool(pb.update_record, "users", user["id"], {
            "verified": True,
            "codigo_verificacion": "",
            "codigo_verificacion_expira": None,
        })
    except (PocketBaseError, requests.exceptions.RequestException):
        # requests.exceptions.ConnectionError (PocketBase inalcanzable) no
        # es una PocketBaseError -- sin este segundo tipo en el except, se
        # colaba como excepción sin capturar y tumbaba la request con un
        # 500 genérico (ver docs/HOJA_DE_RUTA.md, bug real reproducido).
        return error("No se pudo verificar la cuenta. Intenta de nuevo.")

    request.session.pop("verificar_email", None)
    request.session["flash"] = {"type": "success", "msg": "Correo verificado. Ya puedes iniciar sesión."}
    return RedirectResponse("/auth/login", status_code=302)


@router.post("/verificar/reenviar")
async def verificar_reenviar(request: Request):
    destino = request.session.get("verificar_email")
    if not destino:
        return RedirectResponse("/auth/login", status_code=302)

    try:
        pb = get_admin_client()
        res = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'email = {filter_literal(destino)}', per_page=1,
        )
        items = res.get("items", [])
        if items:
            await _emitir_codigo(pb, items[0]["id"], destino, items[0].get("name") or destino)
    except Exception:
        pass

    # Mismo mensaje exista o no la cuenta -- no revela si un correo está
    # registrado (ver auditoria de seguridad, mismo criterio que el resto
    # del sistema).
    request.session["flash"] = {"type": "info", "msg": "Si la cuenta existe, te reenviamos un código nuevo."}
    return RedirectResponse("/auth/verificar", status_code=302)


@router.get("/olvide", response_class=HTMLResponse)
async def olvide_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "auth/olvide.html", {"flash": flash})


@router.post("/olvide")
async def olvide_post(request: Request, email: str = Form(...)):
    email = email.strip().lower()

    try:
        pb = get_admin_client()
        res = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'email = {filter_literal(email)}', per_page=1,
        )
        items = res.get("items", [])
        if items:
            user = items[0]
            # Solo cuentas verificadas y activas -- una cuenta sin verificar
            # todavía no tiene nada que resetear (ver /auth/verificar), y una
            # cuenta bloqueada (activo=False) no debe poder saltarse
            # /auth/bloqueado restableciendo su propia contraseña.
            if user.get("verified", False) and user.get("activo", True):
                await _emitir_codigo_reset(pb, user["id"], email, user.get("name") or email)
    except Exception:
        pass

    # Mismo mensaje exista o no la cuenta, esté verificada/activa o no --
    # no revela nada de quién está registrado (mismo criterio ya usado en
    # /auth/verificar/reenviar, ver auditoria de seguridad).
    request.session["reset_email"] = email
    request.session["flash"] = {
        "type": "info",
        "msg": "Si el correo existe en nuestro sistema, te enviamos instrucciones para restablecer tu contraseña.",
    }
    return RedirectResponse("/auth/restablecer", status_code=302)


@router.get("/restablecer", response_class=HTMLResponse)
async def restablecer_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/dashboard")
    destino = request.session.get("reset_email")
    if not destino:
        return RedirectResponse("/auth/olvide", status_code=302)
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "auth/restablecer.html", {
        "email": destino, "flash": flash,
    })


@router.post("/restablecer")
async def restablecer_post(
    request: Request,
    codigo:        str = Form(...),
    password:      str = Form(...),
    password_conf: str = Form(...),
):
    destino = request.session.get("reset_email")
    if not destino:
        return RedirectResponse("/auth/olvide", status_code=302)

    def error(msg: str):
        return templates.TemplateResponse(request, "auth/restablecer.html", {
            "email": destino, "error": msg,
        }, status_code=422)

    if password != password_conf:
        return error("Las contraseñas no coinciden.")
    if len(password) < 8:
        return error("La contraseña debe tener al menos 8 caracteres.")

    try:
        pb = get_admin_client()
        res = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'email = {filter_literal(destino)}', per_page=1,
        )
        items = res.get("items", [])
        if not items:
            return error("El código no es correcto o venció. Pide uno nuevo.")
        user = items[0]

        codigo_real = (user.get("codigo_reset") or "").strip()
        expira_raw  = user.get("codigo_reset_expira") or ""
        vencido = True
        if expira_raw:
            try:
                expira = datetime.fromisoformat(expira_raw.replace("Z", "+00:00"))
                vencido = datetime.now(timezone.utc) > expira
            except Exception:
                vencido = True

        if not codigo_real or vencido:
            return error("El código venció. Pide uno nuevo con \"Reenviar código\".")
        if not secrets.compare_digest(codigo.strip(), codigo_real):
            return error("El código no es correcto. Intenta de nuevo.")

        await run_in_threadpool(pb.update_record, "users", user["id"], {
            "password":            password,
            "passwordConfirm":     password_conf,
            "codigo_reset":        "",
            "codigo_reset_expira": None,
        })
    except (PocketBaseError, requests.exceptions.RequestException):
        # Causa real del 500 reportado por Washington, reproducida con
        # PocketBase apagado a propósito (ver docs/HOJA_DE_RUTA.md):
        # requests.exceptions.ConnectionError NO es una PocketBaseError,
        # así que se colaba sin capturar y tumbaba la request entera con
        # un 500 genérico de Starlette en vez de este mensaje.
        return error("No se pudo restablecer la contraseña. Intenta de nuevo.")

    request.session.pop("reset_email", None)
    request.session["flash"] = {"type": "success", "msg": "Contraseña actualizada. Ya puedes iniciar sesión."}
    return RedirectResponse("/auth/login", status_code=302)


@router.post("/restablecer/reenviar")
async def restablecer_reenviar(request: Request):
    destino = request.session.get("reset_email")
    if not destino:
        return RedirectResponse("/auth/olvide", status_code=302)

    try:
        pb = get_admin_client()
        res = await run_in_threadpool(
            pb.list_records, "users",
            filter=f'email = {filter_literal(destino)}', per_page=1,
        )
        items = res.get("items", [])
        if items and items[0].get("verified", False) and items[0].get("activo", True):
            await _emitir_codigo_reset(pb, items[0]["id"], destino, items[0].get("name") or destino)
    except Exception:
        pass

    request.session["flash"] = {"type": "info", "msg": "Si la cuenta existe, te reenviamos un código nuevo."}
    return RedirectResponse("/auth/restablecer", status_code=302)


_ROLES_EMPLEADO = {"empleado-operacion", "empleado-mantenimiento", "empleado-vigilancia"}


@router.get("/bloqueado", response_class=HTMLResponse)
async def bloqueado(request: Request):
    """Pantalla real de cuenta bloqueada -- solo alcanzable con la sesion
    limitada que arma login() (clave "bloqueo", nunca "user"). Sin esa
    sesion, no hay nada que mostrar: redirige a login como cualquier
    ruta protegida haria."""
    info = request.session.get("bloqueo")
    if not info:
        return RedirectResponse("/auth/login", status_code=302)

    rol_slug = info.get("rol_slug", "")
    tiene_pago_pendiente = False
    correo_contacto: str | None = None

    try:
        if rol_slug == "ciclista":
            pb = get_admin_client()
            res = pb.list_records(
                "pagos",
                filter=(
                    f'ciclista_id = {filter_literal(info["id"])} && '
                    '(estado = "pendiente" || estado = "pendiente_efectivo" || estado = "verificacion_pendiente")'
                ),
                per_page=1,
            )
            tiene_pago_pendiente = res.get("totalItems", 0) > 0
        elif rol_slug in _ROLES_EMPLEADO:
            correo_contacto = primer_email_por_rol("gerente")
        elif rol_slug == "gerente":
            correo_contacto = primer_email_por_rol("admin")
    except Exception:
        pass

    return templates.TemplateResponse(request, "auth/bloqueado.html", {
        "info": info,
        "motivo": (info.get("motivo_bloqueo") or "").strip(),
        "rol_slug": rol_slug,
        "tiene_pago_pendiente": tiene_pago_pendiente,
        "correo_contacto": correo_contacto,
        "soporte_email": settings.support_email,
    })


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


@router.get("/estado-sesion")
async def estado_sesion(request: Request):
    """Sondeo liviano (ver app/static/js/sesion-tiempo-real.js) para que un usuario
    conectado detecte en tiempo real que un admin le cerro la sesion desde
    /admin/usuarios, sin esperar a que haga clic o navegue (ver
    docs/Requerimientos_Mejoras_UrbanBike.md, punto 6). /auth/ esta fuera de
    AuthMiddleware (PUBLIC_PREFIXES), asi que el chequeo de revocacion se hace
    aca a mano en vez de dejar que el middleware limpie la sesion primero --
    necesitamos leer el nombre del admin ANTES de perder el dato."""
    user = request.session.get("user")
    if not user:
        return JSONResponse({"activo": False})
    admin_nombre = consultar_revocacion(user.get("id", ""))
    if admin_nombre:
        request.session.clear()
        return JSONResponse({"activo": False, "cerrada_por_admin": admin_nombre})
    # Conteo de notificaciones no leidas (campana, ver punto 13): pasajero en
    # el mismo sondeo de 4s que ya existe para sesion, sin timer nuevo.
    no_leidas = notificaciones_repo.contar_no_leidas(user.get("id", ""), user.get("rol_slug", ""))
    return JSONResponse({"activo": True, "notificaciones_no_leidas": no_leidas})
