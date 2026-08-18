"""Rutas CRUD para la sección administrativa: usuarios, bicicletas, estaciones, tarifas."""

import json
import re
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

import requests
from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse

from app.db import bicicletas_repo, estaciones_repo, mensajes_soporte_repo, permisos_repo, respaldo_repo, tarifas_repo
from app.db.pocketbase import filter_literal, get_admin_client, PocketBaseError, registrar_auditoria
from app.middleware.auth import revocar_sesion
from app.middleware.permisos import requiere_permiso
from app.reportes.excel import ColumnaReporte, generar_excel_reporte
from app.reportes.pdf import generar_pdf_reporte
from app.templating import file_url, templates

router = APIRouter(prefix="/admin", tags=["admin"])

_CEDULA_PATTERN = re.compile(r"^[0-9]{10}$")


def _flash(request: Request, url: str, tipo: str, msg: str) -> RedirectResponse:
    request.session["flash"] = {"type": tipo, "msg": msg}
    return RedirectResponse(url, status_code=302)


def _ctx(request: Request, **extra) -> dict:
    return {"user": getattr(request.state, "user", None), **extra}


def _pb():
    """Admin client; resetea el singleton si el token expiró."""
    import app.db.pocketbase as pbmod
    try:
        return get_admin_client()
    except Exception:
        pbmod._admin_client = None
        return get_admin_client()


_ACCION_TIPO = {"crear": "crear", "editar": "editar", "eliminar": "eliminar"}
_MODULO_PLURAL = {
    "usuario": "usuarios", "bicicleta": "bicicletas",
    "estación": "estaciones", "tarifa": "tarifas", "permiso": "permisos",
}


def _log(request: Request, accion: str, detalle: str) -> None:
    """Registra una acción de CRUD en la bitácora de cambios y en la auditoría."""
    user = getattr(request.state, "user", {}) or {}
    try:
        _pb().create_record("bitacora_cambios", {
            "usuario_nombre": user.get("name") or user.get("email", "Admin"),
            "accion":  accion,
            "detalle": detalle,
            "fecha":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception:
        pass

    palabras = accion.lower().split(" ", 1)
    accion_tipo = _ACCION_TIPO.get(palabras[0], "editar")
    modulo = _MODULO_PLURAL.get(palabras[1], "sistema") if len(palabras) > 1 else "sistema"
    registrar_auditoria(
        user.get("pb_token", ""), user.get("id", ""),
        user.get("name") or user.get("email", "Admin"), user.get("email", ""),
        accion_tipo, modulo, detalle, request,
        usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
    )


# ── USUARIOS ──────────────────────────────────────────────────────────────────

@router.get("/usuarios", response_class=HTMLResponse)
def usuarios_list(request: Request):
    flash = request.session.pop("flash", None)
    items: list = []
    roles: list = []
    error: str | None = None
    try:
        pb = _pb()
        items = pb.list_records("users", sort="-created", per_page=100, expand="rol").get("items", [])
    except Exception as e:
        error = str(e)
    try:
        roles = _pb().list_records("roles", per_page=50, sort="nombre").get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "admin/usuarios.html", _ctx(request,
        title="Usuarios", items=items, roles=roles, flash=flash, error=error,
    ))


def _validar_avatar(avatar: UploadFile | None) -> tuple[bool, str | None]:
    """Mismo criterio que perfil.html/main.py: JPG/PNG/GIF, maximo 2MB."""
    tiene_avatar = avatar is not None and avatar.filename
    if not tiene_avatar:
        return False, None
    if avatar.content_type not in ("image/jpeg", "image/png", "image/gif"):
        return True, "La foto debe ser un archivo JPG, PNG o GIF."
    if avatar.size and avatar.size > 2 * 1024 * 1024:
        return True, "La foto no debe superar los 2 MB."
    return True, None


@router.post("/usuarios/crear")
def usuarios_crear(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    cedula: str = Form(""),
    rol: str = Form(""),
    avatar: UploadFile | None = File(None),
):
    tiene_avatar, error_avatar = _validar_avatar(avatar)
    if error_avatar:
        return _flash(request, "/admin/usuarios", "error", error_avatar)
    if cedula and not _CEDULA_PATTERN.match(cedula.strip()):
        return _flash(request, "/admin/usuarios", "error", "La cédula debe tener exactamente 10 dígitos numéricos.")
    try:
        # verified=True: a diferencia del registro público (que exige
        # código por correo, ver app/routers/auth.py), una cuenta creada
        # a mano por Admin ya es un acto de por sí verificado -- sin esto,
        # el login la bloquearía igual que a un registro público sin
        # confirmar. activo=True: mismo motivo, distinto campo -- sin
        # fijarlo, el valor por defecto de PocketBase es False, y la
        # cuenta cae en /auth/bloqueado igual que una cuenta desactivada
        # a propósito (hallazgo real encontrado probando esta misma
        # tarea, ver docs/HOJA_DE_RUTA.md sección 55).
        payload: dict = {"email": email, "password": password,
                         "passwordConfirm": password, "emailVisibility": True,
                         "verified": True, "activo": True}
        if name:   payload["name"] = name
        if cedula: payload["cedula"] = cedula
        if rol:    payload["rol"]  = rol
        pb = _pb()
        nuevo = pb.create_record("users", payload)

        if tiene_avatar:
            contenido = avatar.file.read()
            pb.update_record_with_file("users", nuevo["id"], {},
                {"avatar": (avatar.filename, contenido, avatar.content_type)})

        _log(request, "Crear usuario", f"Usuario creado: {email}")
        return _flash(request, "/admin/usuarios", "success", "Usuario creado correctamente.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))


@router.post("/usuarios/{uid}/editar")
def usuarios_editar(
    request: Request, uid: str,
    name: str = Form(""), rol: str = Form(""),
    email: str = Form(""), cedula: str = Form(""),
    motivo_bloqueo: str = Form(""),
    avatar: UploadFile | None = File(None),
    next: str = Form("/admin/usuarios"),
):
    """next: a donde redirigir al terminar -- por defecto /admin/usuarios
    (comportamiento de siempre), pero la pantalla de excepciones por
    usuario (sección 42) reutiliza esta misma ruta para cambiar el rol
    sin duplicar la lógica de asignación, pasando next=/admin/permisos-usuario/{uid}.

    motivo_bloqueo: siempre se guarda (incluso vacío, para poder
    borrarlo) -- es el texto real que ve el usuario en /auth/bloqueado
    mientras activo=false, ver docs/HOJA_DE_RUTA.md."""
    tiene_avatar, error_avatar = _validar_avatar(avatar)
    if error_avatar:
        return _flash(request, next, "error", error_avatar)
    if cedula and not _CEDULA_PATTERN.match(cedula.strip()):
        return _flash(request, next, "error", "La cédula debe tener exactamente 10 dígitos numéricos.")
    try:
        payload: dict = {"rol": rol, "motivo_bloqueo": motivo_bloqueo}
        if name:   payload["name"]  = name
        if email:  payload["email"] = email
        if cedula: payload["cedula"] = cedula
        pb = _pb()
        if tiene_avatar:
            contenido = avatar.file.read()
            pb.update_record_with_file("users", uid, payload,
                {"avatar": (avatar.filename, contenido, avatar.content_type)})
        else:
            pb.update_record("users", uid, payload)
        _log(request, "Editar usuario", f"Usuario actualizado (id: {uid})")
        return _flash(request, next, "success", "Usuario actualizado.")
    except Exception as e:
        return _flash(request, next, "error", str(e))


@router.post("/usuarios/{uid}/toggle-activo")
def usuarios_toggle_activo(request: Request, uid: str):
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid)
        nuevo = not bool(usuario.get("activo"))
        pb.update_record("users", uid, {"activo": nuevo})
        _log(request, "Editar usuario",
             f"Usuario {usuario.get('email', uid)} marcado como {'activo' if nuevo else 'bloqueado'}")
        return _flash(request, "/admin/usuarios", "success", "Estado del usuario actualizado.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))


@router.post("/usuarios/{uid}/cambiar-password")
def usuarios_cambiar_password(
    request: Request, uid: str,
    password: str = Form(...), password_confirm: str = Form(...),
):
    if password != password_confirm:
        return _flash(request, "/admin/usuarios", "error", "Las contraseñas no coinciden.")
    if len(password) < 8:
        return _flash(request, "/admin/usuarios", "error", "La contraseña debe tener al menos 8 caracteres.")
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid)
        pb.update_record("users", uid, {
            "password": password, "passwordConfirm": password_confirm,
        })
        _log(request, "Editar usuario", f"Contraseña restablecida para {usuario.get('email', uid)}")
        return _flash(request, "/admin/usuarios", "success", "Contraseña actualizada.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))


def _usuarios_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Nombre", ancho=24),
        ColumnaReporte("Email", ancho=30),
        ColumnaReporte("Cédula", ancho=14),
        ColumnaReporte("Rol", ancho=18),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Creado", ancho=14),
    ]
    filas = []
    for u in items:
        rol_obj = (u.get("expand") or {}).get("rol") or {}
        filas.append([
            u.get("name") or "—",
            u.get("email", ""),
            u.get("cedula") or "—",
            rol_obj.get("nombre") or rol_obj.get("slug") or "Sin rol",
            "Activo" if u.get("activo") else "Bloqueado",
            (u.get("created") or "")[:10],
        ])
    return columnas, filas


def _usuarios_items_o_none() -> list | None:
    """Trae los usuarios reales para exportar, o None si PocketBase esta
    inalcanzable (ver docs/HOJA_DE_RUTA.md seccion 66: mismo hueco real que
    en app/routers/auth.py -- sin este except, un ConnectionError se colaba
    sin capturar y tumbaba la ruta con un 500 crudo en vez de un error
    manejado)."""
    try:
        return _pb().list_records("users", sort="-created", per_page=100, expand="rol").get("items", [])
    except (PocketBaseError, requests.exceptions.RequestException):
        return None


@router.get("/usuarios/excel")
def usuarios_excel(request: Request):
    items = _usuarios_items_o_none()
    if items is None:
        return _flash(request, "/admin/usuarios", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _usuarios_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Usuarios",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas, nombre_hoja="Usuarios",
        nombre_archivo=f"urbanbike_usuarios_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/usuarios/pdf")
def usuarios_pdf(request: Request):
    items = _usuarios_items_o_none()
    if items is None:
        return _flash(request, "/admin/usuarios", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _usuarios_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Usuarios", subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_usuarios_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.post("/usuarios/{uid}/cerrar-sesion")
def usuarios_cerrar_sesion(request: Request, uid: str):
    """Cierra la sesión activa del usuario sin eliminar su cuenta -- acción
    independiente de usuarios_eliminar() (ver
    docs/Requerimientos_Mejoras_UrbanBike.md, punto 6). Reutiliza el mismo
    set de revocación; a diferencia de eliminar, el usuario puede volver a
    entrar normalmente con su próximo login (ver
    app/middleware/auth.py:limpiar_revocacion(), llamada desde
    app/routers/auth.py:login())."""
    admin_actual = getattr(request.state, "user", {}) or {}
    admin_nombre = admin_actual.get("name") or admin_actual.get("email") or "Un administrador"
    try:
        usuario = _pb().get_record("users", uid)
        revocar_sesion(uid, admin_nombre)
        _log(request, "Editar usuario", f"Sesión cerrada por admin para {usuario.get('email', uid)}")
        return _flash(request, "/admin/usuarios", "success", "Se cerró la sesión del usuario.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))


@router.post("/usuarios/{uid}/eliminar")
def usuarios_eliminar(request: Request, uid: str):
    admin_actual = getattr(request.state, "user", {}) or {}
    admin_nombre = admin_actual.get("name") or admin_actual.get("email") or "Un administrador"
    try:
        _pb().delete_record("users", uid)
        revocar_sesion(uid, admin_nombre)
        _log(request, "Eliminar usuario", f"Usuario eliminado (id: {uid})")
        return _flash(request, "/admin/usuarios", "success", "Usuario eliminado.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))


# ── BICICLETAS (urbanbike_operativa.bicicletas en ClickHouse, via
#    bicicletas_repo -- misma fuente que empleado/operacion/inventario y
#    gerente/bicicletas) ─────────────────────────────────────────────────────

def _completar_foto_pocketbase(items: list[dict]) -> None:
    """Respaldo de foto: bicicleta_fotos (ClickHouse) esta vacia hoy para
    las bicicletas reales originales (nunca se subio foto por ese camino),
    pero su espejo en PocketBase (bicicletas.foto) si tiene la foto real
    -- mismo patron de respaldo que ya usa ciclista.py/_catalogo_bicicletas.
    Solo se usa para las que no tienen foto_url de ClickHouse; muta `items`
    in place."""
    faltantes = [b for b in items if not b.get("foto_url")]
    if not faltantes:
        return
    try:
        pb_items = _pb().list_records("bicicletas", per_page=500).get("items", [])
    except Exception:
        return
    pb_por_codigo = {b.get("codigo"): b for b in pb_items}
    for b in faltantes:
        pb_bici = pb_por_codigo.get(b["codigo"])
        if pb_bici and pb_bici.get("foto"):
            b["foto_url"] = file_url("bicicletas", pb_bici["id"], pb_bici["foto"])


@router.get("/bicicletas", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:leer"))])
def bicicletas_list(request: Request):
    flash = request.session.pop("flash", None)
    items, total = bicicletas_repo.listar(per_page=1000)
    _completar_foto_pocketbase(items)
    return templates.TemplateResponse(request, "admin/bicicletas.html", _ctx(request,
        title="Bicicletas", items=items,
        modelos=bicicletas_repo.listar_modelos(), estaciones=bicicletas_repo.listar_estaciones(),
        flash=flash, error=None,
    ))


_ESTADO_BICI_LABEL = {
    "disponible": "Disponible", "en_uso": "En uso",
    "mantenimiento": "Mantenimiento", "retirada": "Retirada",
}


def _bicicletas_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=12),
        ColumnaReporte("Marca", ancho=16),
        ColumnaReporte("Modelo", ancho=22),
        ColumnaReporte("Categoría", ancho=14),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Estación", ancho=20),
        ColumnaReporte("Número de serie", ancho=18),
        ColumnaReporte("Fecha de adquisición", ancho=16),
    ]
    filas = [
        [
            b["codigo"], b["marca"], b["modelo"], b["categoria"],
            _ESTADO_BICI_LABEL.get(b["estado"], b["estado"]),
            b.get("estacion_nombre") or "Sin asignar",
            b.get("numero_serie") or "—",
            str(b["fecha_adquisicion"]) if b.get("fecha_adquisicion") else "—",
        ]
        for b in items
    ]
    return columnas, filas


@router.get("/bicicletas/excel")
def bicicletas_excel(request: Request):
    items, _ = bicicletas_repo.listar(per_page=1000)
    columnas, filas = _bicicletas_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Flota de Bicicletas",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas, nombre_hoja="Bicicletas",
        nombre_archivo=f"urbanbike_bicicletas_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/bicicletas/pdf")
def bicicletas_pdf(request: Request):
    items, _ = bicicletas_repo.listar(per_page=1000)
    columnas, filas = _bicicletas_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Flota de Bicicletas", subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_bicicletas_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


def _validar_foto(foto: UploadFile | None) -> tuple[bool, str | None]:
    """Valida que la foto sea jpg/png y no supere 3MB. Devuelve (tiene_foto, error)."""
    tiene_foto = foto is not None and foto.filename
    if not tiene_foto:
        return False, None
    if foto.content_type not in ("image/jpeg", "image/png"):
        return True, "La foto debe ser un archivo JPG o PNG."
    if foto.size and foto.size > 3 * 1024 * 1024:
        return True, "La foto no debe superar los 3 MB."
    return True, None


def _guardar_foto_si_hay(codigo: str, id_bicicleta: str, foto: UploadFile) -> None:
    """La foto se sube a PocketBase (usado solo como hosting de archivos,
    ver bicicletas_repo) y el puntero real queda en
    urbanbike_operativa.bicicleta_fotos."""
    pb_id = bicicletas_repo.obtener_mirror_pb_id(codigo)
    if not pb_id:
        return
    contenido = foto.file.read()
    pb = _pb()
    pb.update_record_with_file("bicicletas", pb_id, {},
        {"foto": (foto.filename, contenido, foto.content_type)})
    registro = pb.get_record("bicicletas", pb_id)
    if registro.get("foto"):
        url = file_url("bicicletas", pb_id, registro["foto"])
        bicicletas_repo.guardar_foto_principal(id_bicicleta, url)


@router.post("/bicicletas/crear", dependencies=[Depends(requiere_permiso("bicicletas:crear"))])
def bicicletas_crear(
    request: Request,
    id_modelo: str = Form(...), estado: str = Form("disponible"),
    id_estacion: str = Form(""), numero_serie: str = Form(""),
    fecha_adquisicion: str = Form(""), observacion: str = Form(""),
    foto: UploadFile | None = File(None),
):
    tiene_foto, error_foto = _validar_foto(foto)
    if error_foto:
        return _flash(request, "/admin/bicicletas", "error", error_foto)
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, "/admin/bicicletas", "error", "Modelo no válido.")
        fecha = datetime.strptime(fecha_adquisicion, "%Y-%m-%d").date() if fecha_adquisicion else datetime.now(timezone.utc).date()
        nuevo_id = bicicletas_repo.crear(
            id_modelo=id_modelo, estado=estado, id_estacion=id_estacion,
            numero_serie=numero_serie, fecha_adquisicion=fecha, observacion=observacion,
            es_electrica=bool(modelo["es_electrica"]),
        )
        bici = bicicletas_repo.obtener(nuevo_id)
        if tiene_foto:
            _guardar_foto_si_hay(bici["codigo"], nuevo_id, foto)
        _log(request, "Crear bicicleta", f"Bicicleta registrada: {bici['codigo']}")
        return _flash(request, "/admin/bicicletas", "success", "Bicicleta registrada.")
    except Exception as e:
        return _flash(request, "/admin/bicicletas", "error", str(e))


@router.post("/bicicletas/{bid}/editar", dependencies=[Depends(requiere_permiso("bicicletas:actualizar"))])
def bicicletas_editar(
    request: Request, bid: str,
    codigo: str = Form(...), id_modelo: str = Form(...), estado: str = Form(...),
    id_estacion: str = Form(""), numero_serie: str = Form(""),
    fecha_adquisicion: str = Form(""), observacion: str = Form(""),
    foto: UploadFile | None = File(None),
):
    tiene_foto, error_foto = _validar_foto(foto)
    if error_foto:
        return _flash(request, "/admin/bicicletas", "error", error_foto)
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, "/admin/bicicletas", "error", "Modelo no válido.")
        fecha = datetime.strptime(fecha_adquisicion, "%Y-%m-%d").date() if fecha_adquisicion else date.today()
        bicicletas_repo.actualizar(
            bid, codigo=codigo, id_modelo=id_modelo, estado=estado, id_estacion=id_estacion,
            numero_serie=numero_serie, fecha_adquisicion=fecha, observacion=observacion,
            es_electrica=bool(modelo["es_electrica"]),
        )
        if tiene_foto:
            _guardar_foto_si_hay(codigo, bid, foto)
        _log(request, "Editar bicicleta", f"Bicicleta actualizada: {codigo or bid}")
        return _flash(request, "/admin/bicicletas", "success", "Bicicleta actualizada.")
    except Exception as e:
        return _flash(request, "/admin/bicicletas", "error", str(e))


@router.post("/bicicletas/{bid}/eliminar", dependencies=[Depends(requiere_permiso("bicicletas:eliminar"))])
def bicicletas_eliminar(request: Request, bid: str):
    bici = bicicletas_repo.obtener(bid)
    codigo = bici["codigo"] if bici else bid
    ok, motivo = bicicletas_repo.eliminar(bid)
    if ok:
        _log(request, "Eliminar bicicleta", f"Bicicleta eliminada: {codigo}")
        return _flash(request, "/admin/bicicletas", "success", "Bicicleta eliminada.")
    return _flash(request, "/admin/bicicletas", "error", motivo)


# ── ESTACIONES (urbanbike_operativa.estaciones en ClickHouse, via
#    estaciones_repo -- misma fuente que gerente/estaciones) ────────────────────

@router.get("/estaciones", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("estaciones:leer"))])
def estaciones_list(request: Request):
    flash = request.session.pop("flash", None)
    items, _ = estaciones_repo.listar(per_page=1000)
    return templates.TemplateResponse(request, "admin/estaciones.html", _ctx(request,
        title="Estaciones", items=items, flash=flash, error=None,
        estaciones_json=json.dumps(items, default=str),
    ))


def _estaciones_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Nombre", ancho=24),
        ColumnaReporte("Código", ancho=12),
        ColumnaReporte("Capacidad", ancho=12, formato="entero"),
        ColumnaReporte("Latitud", ancho=12, formato="decimal2"),
        ColumnaReporte("Longitud", ancho=12, formato="decimal2"),
        ColumnaReporte("Estado", ancho=12),
    ]
    filas = [
        [
            e.get("nombre") or "—", e.get("codigo") or "—", e.get("capacidad") or 0,
            e.get("latitud") or 0, e.get("longitud") or 0,
            "Activa" if e.get("activa") else "Inactiva",
        ]
        for e in items
    ]
    return columnas, filas


@router.get("/estaciones/excel")
def estaciones_excel(request: Request):
    items, total = estaciones_repo.listar(per_page=10000)
    columnas, filas = _estaciones_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Estaciones",
        subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas, nombre_hoja="Estaciones",
        nombre_archivo=f"urbanbike_estaciones_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/estaciones/pdf")
def estaciones_pdf(request: Request):
    items, total = estaciones_repo.listar(per_page=10000)
    columnas, filas = _estaciones_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Estaciones", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_estaciones_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


def _validar_estacion_form(codigo: str, nombre: str, latitud: str, longitud: str) -> str:
    if not codigo.strip() or not nombre.strip():
        return "Código y nombre son obligatorios."
    try:
        float(latitud); float(longitud)
    except ValueError:
        return "Selecciona una ubicación real con el buscador de lugar."
    return ""


@router.post("/estaciones/crear", dependencies=[Depends(requiere_permiso("estaciones:crear"))])
def estaciones_crear(
    request: Request,
    codigo: str = Form(...), nombre: str = Form(...), direccion: str = Form(""),
    capacidad: str = Form(""), latitud: str = Form(""), longitud: str = Form(""),
    activa: str = Form("true"),
):
    error = _validar_estacion_form(codigo, nombre, latitud, longitud)
    if error:
        return _flash(request, "/admin/estaciones", "error", error)
    if capacidad and not capacidad.strip().isdigit():
        return _flash(request, "/admin/estaciones", "error", "La capacidad debe ser un número entero.")
    try:
        nuevo_id = estaciones_repo.crear(
            codigo=codigo.strip(), nombre=nombre.strip(), direccion=direccion,
            latitud=float(latitud), longitud=float(longitud),
            capacidad=int(capacidad) if capacidad else 0, activa=activa == "true",
        )
        est = estaciones_repo.obtener(nuevo_id)
        _log(request, "Crear estación", f"Estación creada: {est['codigo']} — {est['nombre']}")
        return _flash(request, "/admin/estaciones", "success", f"Estación {est['codigo']} creada.")
    except Exception as e:
        return _flash(request, "/admin/estaciones", "error", str(e))


@router.post("/estaciones/{eid}/editar", dependencies=[Depends(requiere_permiso("estaciones:actualizar"))])
def estaciones_editar(
    request: Request, eid: str,
    codigo: str = Form(""), nombre: str = Form(""), direccion: str = Form(""),
    capacidad: str = Form(""), latitud: str = Form(""), longitud: str = Form(""),
    activa: str = Form("true"),
):
    error = _validar_estacion_form(codigo, nombre, latitud, longitud)
    if error:
        return _flash(request, "/admin/estaciones", "error", error)
    if capacidad and not capacidad.strip().isdigit():
        return _flash(request, "/admin/estaciones", "error", "La capacidad debe ser un número entero.")
    try:
        estaciones_repo.actualizar(
            eid, codigo=codigo.strip(), nombre=nombre.strip(), direccion=direccion,
            latitud=float(latitud), longitud=float(longitud),
            capacidad=int(capacidad) if capacidad else 0, activa=activa == "true",
        )
        _log(request, "Editar estación", f"Estación actualizada: {codigo or eid}")
        return _flash(request, "/admin/estaciones", "success", "Estación actualizada.")
    except Exception as e:
        return _flash(request, "/admin/estaciones", "error", str(e))


@router.post("/estaciones/{eid}/eliminar", dependencies=[Depends(requiere_permiso("estaciones:eliminar"))])
def estaciones_eliminar(request: Request, eid: str):
    est = estaciones_repo.obtener(eid)
    codigo = est["codigo"] if est else eid
    ok, motivo = estaciones_repo.eliminar(eid)
    if ok:
        _log(request, "Eliminar estación", f"Estación eliminada: {codigo}")
        return _flash(request, "/admin/estaciones", "success", f"Estación {codigo} eliminada.")
    return _flash(request, "/admin/estaciones", "error", motivo)


@router.get("/estaciones/buscar-lugar")
def estaciones_buscar_lugar(request: Request, q: str = Query("")) -> JSONResponse:
    if not q.strip():
        return JSONResponse([])
    params = urllib.parse.urlencode({
        "q": q.strip(),
        "format": "json",
        "limit": 5,
        "countrycodes": "ec",
        "accept-language": "es",
    })
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "UrbanBike-App/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        resultados = [
            {"nombre": item.get("display_name", ""), "lat": float(item["lat"]), "lng": float(item["lon"])}
            for item in data
        ]
        return JSONResponse(resultados)
    except Exception:
        return JSONResponse([])


# ── TARIFAS (urbanbike_operativa.tarifas en ClickHouse, via tarifas_repo --
#    misma fuente que gerente/tarifas y _catalogo_bicicletas del ciclista) ──────

@router.get("/tarifas", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("tarifas:leer"))])
def tarifas_list(request: Request):
    flash = request.session.pop("flash", None)
    items = tarifas_repo.listar()
    return templates.TemplateResponse(request, "admin/tarifas.html", _ctx(request,
        title="Tarifas", items=items, flash=flash, error=None,
        categorias=tarifas_repo.listar_categorias_ref(),
    ))


def _tarifas_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Categoría", ancho=16),
        ColumnaReporte("Membresía", ancho=12),
        ColumnaReporte("Modalidad", ancho=12),
        ColumnaReporte("Precio", ancho=12, formato="moneda"),
        ColumnaReporte("Min. gracia", ancho=12, formato="entero"),
        ColumnaReporte("Recargo/min", ancho=12, formato="moneda"),
        ColumnaReporte("Vigente desde", ancho=14),
        ColumnaReporte("Vigente hasta", ancho=14),
        ColumnaReporte("Estado", ancho=12),
    ]
    filas = [
        [
            t["categoria"], t["tipo_membresia"].capitalize(), t["modalidad"].capitalize(),
            t["precio"], t.get("minutos_gracia") or 0, t.get("recargo_minuto") or 0,
            str(t["vigente_desde"]), str(t["vigente_hasta"]),
            "Vigente" if t["estado"] == "vigente" else "Histórica",
        ]
        for t in items
    ]
    return columnas, filas


@router.get("/tarifas/excel")
def tarifas_excel(request: Request):
    items = tarifas_repo.listar()
    columnas, filas = _tarifas_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Tarifas",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas, nombre_hoja="Tarifas",
        nombre_archivo=f"urbanbike_tarifas_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/tarifas/pdf")
def tarifas_pdf(request: Request):
    items = tarifas_repo.listar()
    columnas, filas = _tarifas_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Tarifas", subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_tarifas_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


def _validar_tarifa_form(precio: float, vigente_desde_s: str, vigente_hasta_s: str) -> str:
    if precio <= 0:
        return "El precio debe ser mayor a 0."
    try:
        vd = datetime.strptime(vigente_desde_s, "%Y-%m-%d").date()
        vh = datetime.strptime(vigente_hasta_s, "%Y-%m-%d").date()
    except ValueError:
        return "Fechas de vigencia inválidas."
    if vh < vd:
        return "La fecha 'vigente hasta' no puede ser anterior a 'vigente desde'."
    return ""


@router.post("/tarifas/crear", dependencies=[Depends(requiere_permiso("tarifas:crear"))])
def tarifas_crear(
    request: Request,
    id_categoria: str = Form(...), tipo_membresia: str = Form(...), modalidad: str = Form(...),
    precio: float = Form(...), minutos_gracia: int = Form(0), recargo_minuto: float = Form(0.0),
    vigente_desde: str = Form(...), vigente_hasta: str = Form("2099-12-31"),
    estado: str = Form("vigente"),
):
    error = _validar_tarifa_form(precio, vigente_desde, vigente_hasta)
    if error:
        return _flash(request, "/admin/tarifas", "error", error)
    try:
        tarifas_repo.crear(
            id_categoria=id_categoria, tipo_membresia=tipo_membresia, modalidad=modalidad,
            precio=precio, minutos_gracia=minutos_gracia, recargo_minuto=recargo_minuto,
            vigente_desde=datetime.strptime(vigente_desde, "%Y-%m-%d").date(),
            vigente_hasta=datetime.strptime(vigente_hasta, "%Y-%m-%d").date(),
            estado=estado,
        )
        _log(request, "Crear tarifa", f"Tarifa creada: {tipo_membresia} / {modalidad}")
        return _flash(request, "/admin/tarifas", "success", "Tarifa creada.")
    except Exception as e:
        return _flash(request, "/admin/tarifas", "error", str(e))


@router.post("/tarifas/{tid}/editar", dependencies=[Depends(requiere_permiso("tarifas:actualizar"))])
def tarifas_editar(
    request: Request, tid: str,
    id_categoria: str = Form(...), tipo_membresia: str = Form(...), modalidad: str = Form(...),
    precio: float = Form(...), minutos_gracia: int = Form(0), recargo_minuto: float = Form(0.0),
    vigente_desde: str = Form(...), vigente_hasta: str = Form("2099-12-31"),
    estado: str = Form("vigente"),
):
    error = _validar_tarifa_form(precio, vigente_desde, vigente_hasta)
    if error:
        return _flash(request, "/admin/tarifas", "error", error)
    try:
        tarifas_repo.actualizar(
            tid, id_categoria=id_categoria, tipo_membresia=tipo_membresia, modalidad=modalidad,
            precio=precio, minutos_gracia=minutos_gracia, recargo_minuto=recargo_minuto,
            vigente_desde=datetime.strptime(vigente_desde, "%Y-%m-%d").date(),
            vigente_hasta=datetime.strptime(vigente_hasta, "%Y-%m-%d").date(),
            estado=estado,
        )
        _log(request, "Editar tarifa", f"Tarifa actualizada: {tipo_membresia} / {modalidad} (id: {tid})")
        return _flash(request, "/admin/tarifas", "success", "Tarifa actualizada.")
    except Exception as e:
        return _flash(request, "/admin/tarifas", "error", str(e))


@router.post("/tarifas/{tid}/eliminar", dependencies=[Depends(requiere_permiso("tarifas:eliminar"))])
def tarifas_eliminar(request: Request, tid: str):
    tarifa = tarifas_repo.obtener(tid)
    etiqueta = f"{tarifa['categoria']}/{tarifa['tipo_membresia']}/{tarifa['modalidad']}" if tarifa else tid
    ok, motivo = tarifas_repo.eliminar(tid)
    if ok:
        _log(request, "Eliminar tarifa", f"Tarifa eliminada: {etiqueta}")
        return _flash(request, "/admin/tarifas", "success", "Tarifa eliminada.")
    return _flash(request, "/admin/tarifas", "error", motivo)


# ── BITÁCORA DE CAMBIOS ───────────────────────────────────────────────────────

@router.get("/bitacora", response_class=HTMLResponse)
def bitacora_list(request: Request):
    flash = request.session.pop("flash", None)
    items: list = []
    error: str | None = None
    try:
        items = _pb().list_records("bitacora_cambios", sort="-fecha", per_page=50).get("items", [])
    except Exception as e:
        error = str(e)
    return templates.TemplateResponse(request, "admin/bitacora.html", _ctx(request,
        title="Bitácora de Cambios", items=items, flash=flash, error=error,
    ))


def _bitacora_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Fecha/Hora", ancho=20),
        ColumnaReporte("Usuario", ancho=24),
        ColumnaReporte("Acción", ancho=16),
        ColumnaReporte("Detalle", ancho=55),
    ]
    filas = [
        [
            str(b.get("fecha") or "").replace("T", " ").replace("Z", ""),
            b.get("usuario_nombre") or "—", b.get("accion") or "—", b.get("detalle") or "—",
        ]
        for b in items
    ]
    return columnas, filas


def _bitacora_items_o_none() -> list | None:
    """Mismo hueco real que _usuarios_items_o_none (ver
    docs/HOJA_DE_RUTA.md seccion 66)."""
    try:
        return _pb().list_records("bitacora_cambios", sort="-fecha", per_page=50).get("items", [])
    except (PocketBaseError, requests.exceptions.RequestException):
        return None


@router.get("/bitacora/excel")
def bitacora_excel(request: Request):
    items = _bitacora_items_o_none()
    if items is None:
        return _flash(request, "/admin/bitacora", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _bitacora_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Bitácora de Cambios",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas, nombre_hoja="Bitácora",
        nombre_archivo=f"urbanbike_bitacora_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/bitacora/pdf")
def bitacora_pdf(request: Request):
    items = _bitacora_items_o_none()
    if items is None:
        return _flash(request, "/admin/bitacora", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _bitacora_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Bitácora de Cambios", subtitulo=f"Total: {len(items)} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_bitacora_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


# ── AUDITORÍA ─────────────────────────────────────────────────────────────────

def _auditoria_filtro(accion: str, modulo: str, usuario: str) -> str:
    """accion/modulo/usuario llegan como query params GET (?accion=...):
    aunque la UI normal los manda desde un <select>/input de texto, la
    URL es editable a mano antes de enviarse -- se tratan como no
    confiables igual que cualquier otro input de usuario (ver
    docs/HOJA_DE_RUTA.md, auditoria de seguridad)."""
    partes: list[str] = []
    if accion:
        partes.append(f'accion = {filter_literal(accion)}')
    if modulo:
        partes.append(f'modulo = {filter_literal(modulo)}')
    if usuario:
        partes.append(f'usuario_nombre ~ {filter_literal(usuario)}')
    return " && ".join(partes)


@router.get("/auditoria", response_class=HTMLResponse)
def auditoria_list(
    request: Request,
    accion:  str = Query(""),
    modulo:  str = Query(""),
    usuario: str = Query(""),
):
    flash = request.session.pop("flash", None)
    items: list = []
    error: str | None = None
    try:
        items = _pb().list_records(
            "auditoria",
            filter=_auditoria_filtro(accion, modulo, usuario),
            sort="-fecha", per_page=100,
        ).get("items", [])
    except Exception as e:
        error = str(e)
    return templates.TemplateResponse(request, "admin/auditoria.html", _ctx(request,
        title="Auditoría", items=items, flash=flash, error=error,
        f_accion=accion, f_modulo=modulo, f_usuario=usuario,
    ))


def _auditoria_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Fecha/Hora", ancho=20),
        ColumnaReporte("Usuario", ancho=26),
        ColumnaReporte("Email", ancho=32),
        ColumnaReporte("Rol", ancho=18),
        ColumnaReporte("Acción", ancho=12),
        ColumnaReporte("Módulo", ancho=16),
        ColumnaReporte("Detalle", ancho=50),
        ColumnaReporte("IP", ancho=16),
    ]
    keys = ["fecha", "usuario_nombre", "usuario_email", "usuario_rol", "accion", "modulo", "detalle", "ip_cliente"]
    filas = []
    for item in items:
        fila = []
        for key in keys:
            valor = item.get(key, "")
            if key == "fecha":
                valor = str(valor).replace("T", " ").replace("Z", "")
            fila.append(valor)
        filas.append(fila)
    return columnas, filas


def _auditoria_items_o_none(accion: str, modulo: str, usuario: str) -> list | None:
    """Mismo hueco real que _usuarios_items_o_none (ver
    docs/HOJA_DE_RUTA.md seccion 66)."""
    try:
        return _pb().list_records(
            "auditoria",
            filter=_auditoria_filtro(accion, modulo, usuario),
            sort="-fecha", per_page=100,
        ).get("items", [])
    except (PocketBaseError, requests.exceptions.RequestException):
        return None


@router.get("/auditoria/excel")
def auditoria_excel(
    request: Request,
    accion:  str = Query(""),
    modulo:  str = Query(""),
    usuario: str = Query(""),
):
    items = _auditoria_items_o_none(accion, modulo, usuario)
    if items is None:
        return _flash(request, "/admin/auditoria", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _auditoria_columnas_filas(items)

    return generar_excel_reporte(
        titulo="UrbanBike — Registro de Auditoría",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas,
        filas=filas,
        nombre_hoja="Auditoría",
        nombre_archivo=f"urbanbike_auditoria_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/auditoria/pdf")
def auditoria_pdf(
    request: Request,
    accion:  str = Query(""),
    modulo:  str = Query(""),
    usuario: str = Query(""),
):
    items = _auditoria_items_o_none(accion, modulo, usuario)
    if items is None:
        return _flash(request, "/admin/auditoria", "error", "No se pudo generar el archivo: no se pudo conectar con el servicio de datos. Intenta de nuevo en un momento.")
    columnas, filas = _auditoria_columnas_filas(items)

    return generar_pdf_reporte(
        titulo="Registro de Auditoría",
        subtitulo=f"Total: {len(items)} registros",
        columnas=columnas,
        filas=filas,
        nombre_archivo=f"urbanbike_auditoria_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


# ── REPORTES ──────────────────────────────────────────────────────────────────

@router.get("/reportes", response_class=HTMLResponse)
def reportes(request: Request):
    flash = request.session.pop("flash", None)
    error: str | None = None

    rol_labels: list = []
    rol_values: list = []
    bici_labels: list = []
    bici_values: list = []
    est_labels: list = []
    est_values: list = []
    total_usuarios = total_bicis = total_estaciones = 0

    try:
        pb = _pb()

        usuarios = pb.list_records("users", expand="rol", per_page=500).get("items", [])
        rol_counts: dict[str, int] = {}
        for u in usuarios:
            rol_obj = (u.get("expand") or {}).get("rol") or {}
            nombre = rol_obj.get("nombre") or rol_obj.get("slug") or "Sin rol"
            rol_counts[nombre] = rol_counts.get(nombre, 0) + 1
        rol_labels = list(rol_counts.keys())
        rol_values = list(rol_counts.values())
        total_usuarios = len(usuarios)

        bicis = pb.list_records("bicicletas", per_page=500).get("items", [])
        bici_counts = {"disponible": 0, "en_uso": 0, "mantenimiento": 0, "retirada": 0}
        for b in bicis:
            estado = b.get("estado", "disponible")
            bici_counts[estado] = bici_counts.get(estado, 0) + 1
        bici_labels = ["Disponible", "En uso", "Mantenimiento", "Retirada"]
        bici_values = [bici_counts["disponible"], bici_counts["en_uso"],
                       bici_counts["mantenimiento"], bici_counts["retirada"]]
        total_bicis = len(bicis)

        # El dataset es exclusivamente de Nueva York (no existe campo "ciudad" en
        # estaciones); se reporta su distribución por estado operativo.
        estaciones = pb.list_records("estaciones", per_page=500).get("items", [])
        activas = sum(1 for e in estaciones if e.get("activa"))
        inactivas = len(estaciones) - activas
        est_labels = ["Activas", "Inactivas"]
        est_values = [activas, inactivas]
        total_estaciones = len(estaciones)

    except Exception as e:
        error = str(e)

    return templates.TemplateResponse(request, "admin/reportes.html", _ctx(request,
        title="Reportes", flash=flash, error=error,
        total_usuarios=total_usuarios, total_bicis=total_bicis, total_estaciones=total_estaciones,
        rol_labels=json.dumps(rol_labels), rol_values=json.dumps(rol_values),
        bici_labels=json.dumps(bici_labels), bici_values=json.dumps(bici_values),
        est_labels=json.dumps(est_labels), est_values=json.dumps(est_values),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# ROLES Y PERMISOS — matriz rol×permiso real (ver docs/HOJA_DE_RUTA.md sección 41)
# ══════════════════════════════════════════════════════════════════════════════

_RECURSO_LABEL = {
    "bicicletas": "Bicicletas", "alquileres": "Alquileres",
    "ordenes_mantenimiento": "Órdenes de Mantenimiento", "tarifas": "Tarifas",
    "promociones": "Promociones", "estaciones": "Estaciones",
    "usuarios": "Usuarios", "reportes": "Reportes", "auditoria": "Auditoría",
    "infracciones": "Infracciones", "permisos": "Permisos",
}


@router.get("/permisos", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_matriz(request: Request):
    flash = request.session.pop("flash", None)
    datos = permisos_repo.listar_matriz()
    return templates.TemplateResponse(request, "admin/permisos.html", _ctx(request,
        title="Roles y Permisos", flash=flash,
        roles=datos["roles"], grupos=datos["grupos"], grant_set=datos["grant_set"],
        recurso_label=_RECURSO_LABEL,
    ))


@router.post("/permisos/toggle", dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_toggle(request: Request, id_rol: str = Form(...), id_permiso: str = Form(...)):
    user = getattr(request.state, "user", {})
    rol = permisos_repo.obtener_rol(id_rol)
    permiso = permisos_repo.obtener_permiso(id_permiso)
    if not rol or not permiso:
        return _flash(request, "/admin/permisos", "error", "Rol o permiso no encontrado.")
    try:
        otorgado_por = permisos_repo.resolver_usuario_por_email(user.get("email", ""))
        nuevo_estado = permisos_repo.toggle(id_rol, id_permiso, otorgado_por)
        accion = "otorgado" if nuevo_estado else "revocado"
        _log(request, "Editar permiso", f"Permiso {accion}: {permiso['codigo']} → {rol['nombre']}")
        return _flash(request, "/admin/permisos", "success", f"Permiso {permiso['codigo']} {accion} para {rol['nombre']}.")
    except Exception as e:
        return _flash(request, "/admin/permisos", "error", str(e))


# ── Excepciones por usuario individual (ver docs/HOJA_DE_RUTA.md sección 42) ──

@router.get("/permisos-usuario", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_usuario_buscar(request: Request):
    """Tabla completa de usuarios reales por defecto -- mismo
    pb.list_records() que ya usa admin/usuarios.html, no una lista vacía
    hasta escribir algo. El buscador filtra en vivo esa misma tabla ya
    visible con filtrarTabla() (JS existente, table-search.js), igual
    patrón que admin/bitacora.html -- sin round-trip al servidor."""
    flash = request.session.pop("flash", None)
    resultados: list[dict] = []
    error: str | None = None
    try:
        pb = _pb()
        resultados = pb.list_records("users", sort="-created", per_page=100, expand="rol").get("items", [])
        for u in resultados:
            rol_obj = (u.get("expand") or {}).get("rol") or {}
            u["rol_nombre"] = rol_obj.get("nombre") or rol_obj.get("slug") or "Sin rol"
    except Exception as e:
        error = str(e)
    return templates.TemplateResponse(request, "admin/permisos_usuario_buscar.html", _ctx(request,
        title="Excepciones por Usuario", flash=flash, resultados=resultados, error=error,
    ))


@router.get("/permisos-usuario/{uid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_usuario_detalle(request: Request, uid: str):
    flash = request.session.pop("flash", None)
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid, expand="rol")
    except Exception:
        return _flash(request, "/admin/permisos-usuario", "error", "Usuario no encontrado.")

    rol_obj = (usuario.get("expand") or {}).get("rol") or {}
    rol_slug = rol_obj.get("slug", "")
    usuario["rol_nombre"] = rol_obj.get("nombre") or rol_obj.get("slug") or "Sin rol"
    usuario["rol_id"] = rol_obj.get("id", "")

    grupos = permisos_repo.listar_permisos_usuario(uid, rol_slug)
    roles_pb = pb.list_records("roles", per_page=50, sort="nombre").get("items", [])

    # Resumen de 4 indicadores (Lectura/Escritura/Actualizar/Eliminar), ya
    # como acción masiva real (ver docs/HOJA_DE_RUTA.md sección 44) --
    # 'todos'/'parcial'/'ninguno' por acción, más el conteo real de
    # recursos, para decidir si el botón otorga lo que falte o revoca
    # todo. Reutiliza listar_permisos_usuario() vía resumen_por_accion(),
    # sin ninguna consulta nueva más allá de la que esa función ya hace.
    resumen = permisos_repo.resumen_por_accion(uid, rol_slug)

    return templates.TemplateResponse(request, "admin/permisos_usuario_detalle.html", _ctx(request,
        title=f"Excepciones — {usuario.get('name') or usuario.get('email')}", flash=flash,
        usuario=usuario, grupos=grupos, roles=roles_pb, recurso_label=_RECURSO_LABEL,
        resumen=resumen,
    ))


@router.post("/permisos-usuario/{uid}/toggle", dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_usuario_toggle(
    request: Request, uid: str,
    id_permiso: str = Form(...), accion: str = Form(...),
):
    user = getattr(request.state, "user", {})
    permiso = permisos_repo.obtener_permiso(id_permiso)
    if not permiso or accion not in ("otorgar", "revocar", "quitar"):
        return _flash(request, f"/admin/permisos-usuario/{uid}", "error", "Solicitud inválida.")
    try:
        otorgado_por = permisos_repo.resolver_usuario_por_email(user.get("email", ""))
        permisos_repo.set_excepcion_usuario(uid, id_permiso, accion, otorgado_por)
        etiqueta = {"otorgar": "otorgado", "revocar": "revocado", "quitar": "vuelto a heredar del rol"}[accion]
        _log(request, "Editar permiso", f"Excepción de {permiso['codigo']} {etiqueta} (usuario id: {uid})")
        return _flash(request, f"/admin/permisos-usuario/{uid}", "success", f"Permiso {permiso['codigo']}: {etiqueta}.")
    except Exception as e:
        return _flash(request, f"/admin/permisos-usuario/{uid}", "error", str(e))


_ETIQUETA_ACCION = {"leer": "Lectura", "crear": "Escritura", "actualizar": "Actualizar", "eliminar": "Eliminar"}


@router.post("/permisos-usuario/{uid}/toggle-masivo", dependencies=[Depends(requiere_permiso("permisos:actualizar"))])
def permisos_usuario_toggle_masivo(
    request: Request, uid: str,
    accion: str = Form(...), direccion: str = Form(...),
):
    """Otorga o revoca una acción (leer/crear/actualizar/eliminar) en
    TODOS los recursos aplicables de una sola vez -- ver
    docs/HOJA_DE_RUTA.md sección 44. direccion siempre viene calculada
    por el propio botón en la plantilla (no depende de qué estado tenga
    el usuario en este momento del lado del cliente), así que no hace
    falta releer el estado antes de decidir qué hacer -- set_excepcion_masiva()
    ya evalúa recurso por recurso qué le falta o le sobra."""
    if accion not in _ETIQUETA_ACCION or direccion not in ("otorgar", "revocar"):
        return _flash(request, f"/admin/permisos-usuario/{uid}", "error", "Solicitud inválida.")
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid, expand="rol")
    except Exception:
        return _flash(request, "/admin/permisos-usuario", "error", "Usuario no encontrado.")
    rol_slug = ((usuario.get("expand") or {}).get("rol") or {}).get("slug", "")
    user = getattr(request.state, "user", {})
    try:
        otorgado_por = permisos_repo.resolver_usuario_por_email(user.get("email", ""))
        tocados = permisos_repo.set_excepcion_masiva(uid, rol_slug, accion, direccion == "otorgar", otorgado_por)
        etiqueta = _ETIQUETA_ACCION[accion]
        verbo = "otorgado" if direccion == "otorgar" else "revocado"
        _log(request, "Editar permiso", f"{etiqueta} {verbo} en {tocados} recurso(s) (usuario id: {uid})")
        if tocados:
            msg = f"{etiqueta}: {verbo} en {tocados} recurso(s)."
        else:
            msg = f"{etiqueta} ya estaba {'otorgado' if direccion == 'otorgar' else 'revocado'} en todos los recursos aplicables."
        return _flash(request, f"/admin/permisos-usuario/{uid}", "success", msg)
    except Exception as e:
        return _flash(request, f"/admin/permisos-usuario/{uid}", "error", str(e))


# ── RESPALDO ─────────────────────────────────────────────────────────────────

@router.get("/respaldo", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("respaldo:exportar"))])
def respaldo_form(request: Request):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "admin/respaldo.html", _ctx(request,
        title="Respaldo del sistema", flash=flash,
        categorias=respaldo_repo.categorias_con_tablas(),
    ))


def _validar_tablas(tablas: list[str]) -> list[str]:
    """Whitelist real contra respaldo_repo.TABLAS -- nunca se confia en
    el nombre de tabla que llega del formulario tal cual."""
    return [t for t in tablas if t in respaldo_repo.TABLAS]


def _parse_fecha_respaldo(valor: str) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


@router.get("/respaldo/csv", dependencies=[Depends(requiere_permiso("respaldo:exportar"))])
def respaldo_csv(
    request: Request,
    tablas: list[str] = Query(default=[]),
    desde: str = Query(""), hasta: str = Query(""),
):
    tablas_validas = _validar_tablas(tablas)
    if not tablas_validas:
        return _flash(request, "/admin/respaldo", "error", "Selecciona al menos una tabla.")
    user = getattr(request.state, "user", {})
    contenido, nombre_archivo = respaldo_repo.exportar_csv(
        tablas_validas, _parse_fecha_respaldo(desde), _parse_fecha_respaldo(hasta),
    )
    _log(request, "Editar respaldo", f"Respaldo CSV generado: {len(tablas_validas)} tabla(s) ({', '.join(tablas_validas)})")
    media = "application/zip" if nombre_archivo.endswith(".zip") else "text/csv"
    return StreamingResponse(
        iter([contenido]), media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


@router.get("/respaldo/sql", dependencies=[Depends(requiere_permiso("respaldo:exportar"))])
def respaldo_sql(
    request: Request,
    tablas: list[str] = Query(default=[]),
    desde: str = Query(""), hasta: str = Query(""),
):
    tablas_validas = _validar_tablas(tablas)
    if not tablas_validas:
        return _flash(request, "/admin/respaldo", "error", "Selecciona al menos una tabla.")
    contenido, nombre_archivo = respaldo_repo.exportar_sql(
        tablas_validas, _parse_fecha_respaldo(desde), _parse_fecha_respaldo(hasta),
    )
    _log(request, "Editar respaldo", f"Respaldo SQL generado: {len(tablas_validas)} tabla(s) ({', '.join(tablas_validas)})")
    return StreamingResponse(
        iter([contenido]), media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


# ── SOPORTE (chat interno, punto 12 Opción B -- ver docs/HOJA_DE_RUTA.md
#    sección 68). Espejo exacto de /empleado/vigilancia/soporte, mismo repo
#    -- Admin ve y responde todas las conversaciones igual que Vigilancia. ──

@router.get("/soporte", response_class=HTMLResponse)
def admin_soporte_lista(request: Request):
    flash = request.session.pop("flash", None)
    conversaciones = mensajes_soporte_repo.listar_conversaciones()
    return templates.TemplateResponse(request, "admin/soporte.html", _ctx(request,
        title="Soporte", flash=flash, conversaciones=conversaciones,
        base_url="/admin/soporte",
    ))


@router.get("/soporte/{ciclista_id}", response_class=HTMLResponse)
def admin_soporte_detalle(request: Request, ciclista_id: str):
    flash = request.session.pop("flash", None)
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    if not mensajes:
        return _flash(request, "/admin/soporte", "error", "Esa conversación no existe.")
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="admin")
    ciclista_nombre = next((m["autor_nombre"] for m in mensajes if m.get("autor_rol") == "ciclista"), ciclista_id)
    return templates.TemplateResponse(request, "admin/soporte_detalle.html", _ctx(request,
        title=f"Soporte — {ciclista_nombre}", flash=flash, mensajes=mensajes,
        ciclista_id=ciclista_id, ciclista_nombre=ciclista_nombre, soy_ciclista=False,
        poll_url=f"/admin/soporte/{ciclista_id}/mensajes",
        enviar_url=f"/admin/soporte/{ciclista_id}/enviar",
        base_url="/admin/soporte",
    ))


@router.post("/soporte/{ciclista_id}/enviar")
def admin_soporte_enviar(request: Request, ciclista_id: str, texto: str = Form(...)):
    user = getattr(request.state, "user", {})
    try:
        mensajes_soporte_repo.enviar(
            ciclista_id=ciclista_id, autor_id=user.get("id", ""),
            autor_rol=user.get("rol_slug", ""), autor_nombre=user.get("name") or user.get("email", ""),
            texto=texto,
        )
    except ValueError as e:
        return _flash(request, f"/admin/soporte/{ciclista_id}", "error", str(e))
    except Exception:
        return _flash(request, f"/admin/soporte/{ciclista_id}", "error", "No se pudo enviar la respuesta. Intenta de nuevo.")
    return RedirectResponse(f"/admin/soporte/{ciclista_id}", status_code=302)


@router.get("/soporte/{ciclista_id}/mensajes")
def admin_soporte_mensajes(request: Request, ciclista_id: str):
    """JSON liviano para el sondeo de 4s de la conversación abierta
    (app/static/js/chat-soporte.js)."""
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="admin")
    return JSONResponse({
        "items": [
            {
                "id": m.get("id", ""),
                "autor_rol": m.get("autor_rol", ""),
                "autor_nombre": m.get("autor_nombre", ""),
                "texto": m.get("texto", ""),
                "fecha": m.get("fecha", ""),
            }
            for m in mensajes
        ],
    })
