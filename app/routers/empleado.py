"""Rutas para roles de empleado: operación, mantenimiento, vigilancia."""

import json
import math
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import settings
from app.db import (
    alquileres_repo, bicicletas_repo, infracciones_repo, inspecciones_repo, membresias_repo,
    mensajes_soporte_repo, notificaciones_repo, ordenes_repo, tarifas_repo, clickhouse as ch,
)
from app.db.permisos_repo import tiene_permiso
from app.db.pocketbase import filter_literal, get_admin_client, registrar_auditoria
from app.middleware.permisos import requiere_permiso
from app.reportes.excel import ColumnaReporte, generar_excel_reporte
from app.reportes.pdf import generar_pdf_reporte
from app.templating import templates

router = APIRouter(prefix="/empleado", tags=["empleado"])


def _ctx(request: Request, **extra) -> dict:
    return {"user": getattr(request.state, "user", None), **extra}


def _pb():
    import app.db.pocketbase as m
    try:
        return get_admin_client()
    except Exception:
        m._admin_client = None
        return get_admin_client()


def _flash(request: Request, url: str, tipo: str, msg: str) -> RedirectResponse:
    request.session["flash"] = {"type": tipo, "msg": msg}
    return RedirectResponse(url, status_code=302)


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duracion_hms(minutos: int) -> str:
    minutos = max(0, int(minutos))
    h, m = divmod(minutos, 60)
    return f"{h:02d}:{m:02d}:00"


def _tarifa_hora(bicicleta_codigo: str, tipo_membresia: str = "casual") -> float:
    """Compatibilidad temporal para los call sites que todavia solo
    piden 'hora' -- usa la fuente unica real (tarifas_repo), nunca la
    coleccion vieja de PocketBase. Devuelve 0.0 si no hay tarifa
    vigente, mismo comportamiento que antes (nunca levanta excepcion
    hacia el llamador)."""
    id_categoria = tarifas_repo.categoria_de_bicicleta(bicicleta_codigo)
    if not id_categoria:
        return 0.0
    resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, "hora")
    return resultado[0] if resultado else 0.0


# ── Fallback /empleado/dashboard → redirige según rol ──────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def empleado_dashboard_redirect(request: Request):
    rol = getattr(request.state, "user", {}).get("rol_slug", "")
    destinos = {
        "empleado-operacion":     "/empleado/operacion/dashboard",
        "empleado-mantenimiento": "/empleado/mantenimiento/dashboard",
        "empleado-vigilancia":    "/empleado/vigilancia/dashboard",
    }
    return RedirectResponse(destinos.get(rol, "/dashboard"), status_code=302)


# ══════════════════════════════════════════════════════════════════════════════
# OPERACIÓN
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/operacion/dashboard", response_class=HTMLResponse)
async def op_dashboard(request: Request):
    flash = request.session.pop("flash", None)
    stats = {"disponible": 0, "en_uso": 0, "mantenimiento": 0, "retirada": 0, "total": 0}
    try:
        for b in _pb().list_records("bicicletas", per_page=500).get("items", []):
            estado = b.get("estado", "disponible")
            stats[estado] = stats.get(estado, 0) + 1
            stats["total"] += 1
    except Exception:
        pass

    chart_labels = json.dumps(["Disponible", "En Uso", "Mantenimiento", "Retirada"])
    chart_values = json.dumps([stats["disponible"], stats["en_uso"], stats["mantenimiento"], stats["retirada"]])
    chart_colors = json.dumps(["#10B981", "#1E86BD", "#F59E0B", "#6B7280"])

    return templates.TemplateResponse(request, "empleado/operacion/dashboard.html", _ctx(request,
        title="Dashboard — Operación", flash=flash, stats=stats,
        chart_labels=chart_labels, chart_values=chart_values, chart_colors=chart_colors,
    ))


def _permisos_bicicletas(rol_slug: str, id_usuario: str = "") -> dict:
    """Flags reales de bicicletas:crear/actualizar/eliminar para el
    usuario de la sesión -- usados para ocultar botones que igual
    rechazaría requiere_permiso() en el backend (ver
    docs/HOJA_DE_RUTA.md secciones 39/40: Mantenimiento y Vigilancia
    ahora alcanzan esta pantalla, pero con permisos reales distintos a
    Operación). id_usuario se pasa para que una excepción individual
    (sección 42) también se refleje aquí -- sin esto, un usuario con una
    excepción real vería botones que no coinciden con lo que el backend
    en realidad le permite."""
    return {
        "puede_crear": tiene_permiso(rol_slug, "bicicletas:crear", id_usuario),
        "puede_actualizar": tiene_permiso(rol_slug, "bicicletas:actualizar", id_usuario),
        "puede_eliminar": tiene_permiso(rol_slug, "bicicletas:eliminar", id_usuario),
    }


@router.get("/operacion/inventario", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:leer"))])
async def op_inventario(
    request: Request,
    q: str = Query(""), marca: str = Query(""), categoria: str = Query(""),
    estado: str = Query(""), page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    per_page = 10
    filas, total = bicicletas_repo.listar(
        q=q, marca=marca, categoria=categoria, estado=estado, page=page, per_page=per_page,
    )
    fotos = bicicletas_repo.fotos_por_codigo([b["codigo"] for b in filas])
    for b in filas:
        if not b.get("foto_url"):
            b["foto_url"] = fotos.get(b["codigo"], "")
    user = getattr(request.state, "user", {})
    return templates.TemplateResponse(request, "empleado/operacion/inventario.html", _ctx(request,
        title="Inventario de Bicicletas", flash=flash, bicicletas=filas, total=total,
        page=max(1, page), per_page=per_page,
        total_paginas=max(1, -(-total // per_page)),
        q=q, marca=marca, categoria=categoria, estado=estado,
        marcas=bicicletas_repo.listar_marcas(), categorias=bicicletas_repo.listar_categorias(),
        **_permisos_bicicletas(user.get("rol_slug", ""), user.get("id", "")),
    ))


def _inventario_columnas_filas(bicicletas: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=14),
        ColumnaReporte("Marca", ancho=18),
        ColumnaReporte("Modelo", ancho=22),
        ColumnaReporte("Categoría", ancho=16),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Estación", ancho=22),
    ]
    filas = [
        [b["codigo"], b["marca"], b["modelo"], b["categoria"],
         ESTADO_BICI_LABEL.get(b["estado"], b["estado"]), b["estacion_nombre"] or "—"]
        for b in bicicletas
    ]
    return columnas, filas


def _inventario_subtitulo(q: str, marca: str, categoria: str, estado: str, total: int) -> str:
    partes = [f"Total: {total} bicicletas"]
    if q:
        partes.append(f'Búsqueda: "{q}"')
    if marca:
        partes.append(f"Marca: {marca}")
    if categoria:
        partes.append(f"Categoría: {categoria}")
    if estado:
        partes.append(f"Estado: {ESTADO_BICI_LABEL.get(estado, estado)}")
    return "  |  ".join(partes)


@router.get("/operacion/inventario/excel")
def op_inventario_excel(
    q: str = Query(""), marca: str = Query(""), categoria: str = Query(""), estado: str = Query(""),
):
    bicicletas, total = bicicletas_repo.listar(q=q, marca=marca, categoria=categoria, estado=estado, page=1, per_page=100_000)
    columnas, filas = _inventario_columnas_filas(bicicletas)
    return generar_excel_reporte(
        titulo="UrbanBike — Inventario de Bicicletas",
        subtitulo=_inventario_subtitulo(q, marca, categoria, estado, total),
        columnas=columnas, filas=filas, nombre_hoja="Inventario",
        nombre_archivo=f"urbanbike_inventario_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/operacion/inventario/pdf")
def op_inventario_pdf(
    q: str = Query(""), marca: str = Query(""), categoria: str = Query(""), estado: str = Query(""),
):
    bicicletas, total = bicicletas_repo.listar(q=q, marca=marca, categoria=categoria, estado=estado, page=1, per_page=100_000)
    columnas, filas = _inventario_columnas_filas(bicicletas)
    return generar_pdf_reporte(
        titulo="Inventario de Bicicletas",
        subtitulo=_inventario_subtitulo(q, marca, categoria, estado, total),
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_inventario_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/operacion/inventario/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:crear"))])
async def op_inventario_nueva(request: Request):
    flash = request.session.pop("flash", None)
    user = getattr(request.state, "user", {})
    return templates.TemplateResponse(request, "empleado/operacion/inventario_form.html", _ctx(request,
        title="Nueva bicicleta", flash=flash, modo="crear", bici=None,
        modelos=bicicletas_repo.listar_modelos(), estaciones=bicicletas_repo.listar_estaciones(),
        **_permisos_bicicletas(user.get("rol_slug", ""), user.get("id", "")),
    ))


@router.post("/operacion/inventario/crear", dependencies=[Depends(requiere_permiso("bicicletas:crear"))])
async def op_inventario_crear(
    request: Request,
    id_modelo: str = Form(...), estado: str = Form("disponible"),
    id_estacion: str = Form(""), numero_serie: str = Form(""),
    fecha_adquisicion: str = Form(""), observacion: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, "/empleado/operacion/inventario/nueva", "error", "Modelo no válido.")
        fecha = datetime.strptime(fecha_adquisicion, "%Y-%m-%d").date() if fecha_adquisicion else datetime.now(timezone.utc).date()
        nuevo_id = bicicletas_repo.crear(
            id_modelo=id_modelo, estado=estado, id_estacion=id_estacion,
            numero_serie=numero_serie, fecha_adquisicion=fecha, observacion=observacion,
            es_electrica=bool(modelo["es_electrica"]),
        )
        bici = bicicletas_repo.obtener(nuevo_id)
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "bicicletas",
            f"Bicicleta registrada desde inventario: {bici['codigo']}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/inventario", "success", f"Bicicleta {bici['codigo']} registrada correctamente.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/inventario/nueva", "error", str(e))


@router.get("/operacion/inventario/{bid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:leer"))])
async def op_inventario_detalle(request: Request, bid: str, modo: str = Query("ver")):
    flash = request.session.pop("flash", None)
    bici = bicicletas_repo.obtener(bid)
    if not bici:
        return _flash(request, "/empleado/operacion/inventario", "error", "Bicicleta no encontrada.")
    n_alquileres = bicicletas_repo.contar_alquileres(bid)
    user = getattr(request.state, "user", {})
    return templates.TemplateResponse(request, "empleado/operacion/inventario_form.html", _ctx(request,
        title=f"Bicicleta {bici['codigo']}", flash=flash, modo="editar" if modo == "editar" else "ver",
        bici=bici, n_alquileres=n_alquileres,
        modelos=bicicletas_repo.listar_modelos(), estaciones=bicicletas_repo.listar_estaciones(),
        **_permisos_bicicletas(user.get("rol_slug", ""), user.get("id", "")),
    ))


@router.post("/operacion/inventario/{bid}/editar", dependencies=[Depends(requiere_permiso("bicicletas:actualizar"))])
async def op_inventario_editar(
    request: Request, bid: str,
    codigo: str = Form(...), id_modelo: str = Form(...), estado: str = Form(...),
    id_estacion: str = Form(""), numero_serie: str = Form(""),
    fecha_adquisicion: str = Form(""), observacion: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, f"/empleado/operacion/inventario/{bid}", "error", "Modelo no válido.")
        fecha = datetime.strptime(fecha_adquisicion, "%Y-%m-%d").date() if fecha_adquisicion else date.today()
        bicicletas_repo.actualizar(
            bid, codigo=codigo, id_modelo=id_modelo, estado=estado, id_estacion=id_estacion,
            numero_serie=numero_serie, fecha_adquisicion=fecha, observacion=observacion,
            es_electrica=bool(modelo["es_electrica"]),
        )
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "bicicletas",
            f"Bicicleta actualizada: {codigo}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, f"/empleado/operacion/inventario/{bid}", "success", "Bicicleta actualizada.")
    except Exception as e:
        return _flash(request, f"/empleado/operacion/inventario/{bid}", "error", str(e))


@router.post("/operacion/inventario/{bid}/eliminar", dependencies=[Depends(requiere_permiso("bicicletas:eliminar"))])
async def op_inventario_eliminar(request: Request, bid: str):
    user = getattr(request.state, "user", {})
    bici = bicicletas_repo.obtener(bid)
    codigo = bici["codigo"] if bici else bid
    ok, motivo = bicicletas_repo.eliminar(bid)
    if ok:
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "eliminar", "bicicletas",
            f"Bicicleta eliminada: {codigo}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/inventario", "success", f"Bicicleta {codigo} eliminada.")
    return _flash(request, f"/empleado/operacion/inventario/{bid}", "error", motivo)


@router.get("/operacion/alquileres", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("alquileres:leer"))])
async def op_alquileres(
    request: Request,
    q: str = Query(""), estado: str = Query(""),
    fecha_desde: str = Query(""), fecha_hasta: str = Query(""),
    page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    per_page = 10
    fd = datetime.strptime(fecha_desde, "%Y-%m-%d").date() if fecha_desde else None
    fh = datetime.strptime(fecha_hasta, "%Y-%m-%d").date() if fecha_hasta else None
    filas, total = alquileres_repo.listar(
        q=q, estado=estado, fecha_desde=fd, fecha_hasta=fh, page=page, per_page=per_page,
    )

    # Bicicletas agrupadas por estación (datos reales de ClickHouse).
    por_estacion: dict[str, list[dict]] = {}
    for b in bicicletas_repo.listar(per_page=1000)[0]:
        por_estacion.setdefault(b["estacion_nombre"] or "Sin estación", []).append(b)

    return templates.TemplateResponse(request, "empleado/operacion/alquileres.html", _ctx(request,
        title="Gestión de Alquileres", flash=flash,
        alquileres=filas, total=total, page=max(1, page), per_page=per_page,
        total_paginas=max(1, -(-total // per_page)),
        por_estacion=por_estacion,
        q=q, estado=estado, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
    ))


def _alquileres_op_subtitulo(q: str, estado: str, fecha_desde: str, fecha_hasta: str, total: int) -> str:
    partes = [f"Total: {total} alquileres"]
    if q:
        partes.append(f'Búsqueda: "{q}"')
    partes.append(f"Estado: {ESTADO_ALQUILER_LABEL.get(estado, 'Todos')}")
    partes.append(f"Período: {fecha_desde or '—'} → {fecha_hasta or '—'}")
    return "  |  ".join(partes)


@router.get("/operacion/alquileres/excel")
def op_alquileres_excel(
    q: str = Query(""), estado: str = Query(""),
    fecha_desde: str = Query(""), fecha_hasta: str = Query(""),
):
    fd = datetime.strptime(fecha_desde, "%Y-%m-%d").date() if fecha_desde else None
    fh = datetime.strptime(fecha_hasta, "%Y-%m-%d").date() if fecha_hasta else None
    alquileres, total = alquileres_repo.listar(q=q, estado=estado, fecha_desde=fd, fecha_hasta=fh, page=1, per_page=100_000)
    filas = [_reportes_op_fila(a) for a in alquileres]
    fila_total = [f"Total: {total} alquileres"] + [None] * 8 + [sum(f[9] for f in filas)]
    return generar_excel_reporte(
        titulo="UrbanBike — Alquileres (Operación)",
        subtitulo=_alquileres_op_subtitulo(q, estado, fecha_desde, fecha_hasta, total),
        columnas=_reportes_op_columnas(), filas=filas, fila_total=fila_total, nombre_hoja="Alquileres",
        nombre_archivo=f"urbanbike_operacion_alquileres_workpanel_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/operacion/alquileres/pdf")
def op_alquileres_pdf(
    q: str = Query(""), estado: str = Query(""),
    fecha_desde: str = Query(""), fecha_hasta: str = Query(""),
):
    fd = datetime.strptime(fecha_desde, "%Y-%m-%d").date() if fecha_desde else None
    fh = datetime.strptime(fecha_hasta, "%Y-%m-%d").date() if fecha_hasta else None
    alquileres, total = alquileres_repo.listar(q=q, estado=estado, fecha_desde=fd, fecha_hasta=fh, page=1, per_page=100_000)
    filas = [_reportes_op_fila(a) for a in alquileres]
    fila_total = [f"Total: {total} alquileres"] + [None] * 8 + [sum(f[9] for f in filas)]
    return generar_pdf_reporte(
        titulo="Alquileres — Operación",
        subtitulo=_alquileres_op_subtitulo(q, estado, fecha_desde, fecha_hasta, total),
        columnas=_reportes_op_columnas(), filas=filas, fila_total=fila_total,
        nombre_archivo=f"urbanbike_operacion_alquileres_workpanel_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/operacion/alquileres/{viaje_id}/flujo", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("alquileres:leer"))])
async def op_alquiler_flujo(request: Request, viaje_id: str):
    """Vista de detalle: linea de tiempo visual del alquiler (componente
    flujo_alquiler), con datos reales de urbanbike_operativa.alquiler_eventos
    para los alquileres migrados hoy (ver ch.mapa_alquiler_por_viaje_pocketbase)."""
    codigo = viaje_id[:8].upper()
    bicicleta_codigo = "—"
    ciclista_nombre = "—"
    try:
        viaje = _pb().get_record("viajes", viaje_id)
        bicicleta_codigo = viaje.get("bicicleta_codigo", "—")
        ciclista_nombre = viaje.get("ciclista_nombre", "—")
    except Exception:
        pass

    eventos: list[dict] = []
    estado_actual: str | None = None

    id_alquiler = ch.mapa_alquiler_por_viaje_pocketbase().get(viaje_id)
    if id_alquiler:
        alquiler = ch.query_one("""
            SELECT a.codigo AS codigo, a.estado AS estado,
                   b.codigo AS bicicleta_codigo,
                   concat(u.nombre, ' ', u.apellido) AS ciclista_nombre
            FROM urbanbike_operativa.alquileres a FINAL
            JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = a.id_bicicleta
            JOIN urbanbike_operativa.usuarios u FINAL ON u.id = a.id_usuario
            WHERE a.id = %(id)s
        """, {"id": id_alquiler})
        if alquiler:
            codigo = alquiler["codigo"]
            bicicleta_codigo = alquiler["bicicleta_codigo"]
            ciclista_nombre = alquiler["ciclista_nombre"]
            estado_actual = alquiler["estado"]

        filas_eventos = ch.query("""
            SELECT estado_destino, fecha
            FROM urbanbike_operativa.alquiler_eventos
            WHERE id_alquiler = %(id)s
            ORDER BY secuencia
        """, {"id": id_alquiler})
        eventos = [
            {"estado_destino": f["estado_destino"], "fecha": f["fecha"].strftime("%H:%M")}
            for f in filas_eventos
        ]

    return templates.TemplateResponse(request, "empleado/operacion/alquiler_flujo.html", _ctx(request,
        title="Trayecto del alquiler", codigo=codigo,
        bicicleta_codigo=bicicleta_codigo, ciclista_nombre=ciclista_nombre,
        eventos=eventos, estado_actual=estado_actual,
    ))


@router.get("/operacion/alquileres/nuevo", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("alquileres:crear"))])
async def op_alquileres_nuevo(request: Request):
    flash = request.session.pop("flash", None)
    disponibles, _ = bicicletas_repo.listar(estado="disponible", per_page=200)
    # Cotizacion real (tarifa + promocion de mayor ahorro, si aplica) por
    # bicicleta, para la vista previa del formulario -- mismo calculo que
    # crear_presencial() usa para cobrar de verdad al confirmar.
    cotizaciones = {str(b["id"]): alquileres_repo.cotizar(b["id"]) for b in disponibles}
    return templates.TemplateResponse(request, "empleado/operacion/alquiler_form.html", _ctx(request,
        title="Alquiler manual", flash=flash, modo="crear", alquiler=None,
        bicicletas_disponibles=disponibles, estaciones=bicicletas_repo.listar_estaciones(),
        cotizaciones_json=json.dumps(cotizaciones, default=str),
    ))


@router.post("/operacion/alquileres/crear", dependencies=[Depends(requiere_permiso("alquileres:crear"))])
async def op_alquileres_crear(
    request: Request,
    bicicleta_id:       str = Form(...),
    estacion_inicio_id: str = Form(...),
    ciclista_nombre:    str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        nuevo_id = alquileres_repo.crear_presencial(
            id_bicicleta=bicicleta_id, id_estacion_inicio=estacion_inicio_id,
            nombre_ciclista=ciclista_nombre or "Cliente Presencial",
        )
        alq = alquileres_repo.obtener(nuevo_id)
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "alquileres",
            f"Alquiler manual presencial registrado: {alq['codigo']}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/alquileres", "success", f"Alquiler {alq['codigo']} registrado correctamente.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/alquileres/nuevo", "error", str(e))


@router.get("/operacion/alquileres/{id_alquiler}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("alquileres:leer"))])
async def op_alquileres_ver(request: Request, id_alquiler: str):
    flash = request.session.pop("flash", None)
    alquiler = alquileres_repo.obtener(id_alquiler)
    if not alquiler:
        return _flash(request, "/empleado/operacion/alquileres", "error", "Alquiler no encontrado.")
    filas_eventos = alquileres_repo.eventos(id_alquiler)
    eventos = [{"estado_destino": f["estado_destino"], "fecha": f["fecha"].strftime("%H:%M")} for f in filas_eventos]
    return templates.TemplateResponse(request, "empleado/operacion/alquiler_form.html", _ctx(request,
        title=f"Alquiler {alquiler['codigo']}", flash=flash, modo="ver", alquiler=alquiler,
        eventos=eventos, estado_actual=alquiler["estado"],
        estaciones=bicicletas_repo.listar_estaciones(),
    ))


@router.post("/operacion/alquileres/{id_alquiler}/cancelar", dependencies=[Depends(requiere_permiso("alquileres:eliminar"))])
async def op_alquileres_cancelar(request: Request, id_alquiler: str):
    user = getattr(request.state, "user", {})
    alquiler = alquileres_repo.obtener(id_alquiler)
    codigo = alquiler["codigo"] if alquiler else id_alquiler
    ok, motivo = alquileres_repo.cancelar(id_alquiler)
    if ok:
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "alquileres",
            f"Alquiler cancelado: {codigo}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/alquileres", "success", f"Alquiler {codigo} cancelado.")
    return _flash(request, f"/empleado/operacion/alquileres/{id_alquiler}", "error", motivo)


@router.post("/operacion/alquileres/{id_alquiler}/completar", dependencies=[Depends(requiere_permiso("alquileres:actualizar"))])
async def op_alquileres_completar(
    request: Request, id_alquiler: str,
    estacion_fin_id: str = Form(...),
):
    user = getattr(request.state, "user", {})
    alquiler = alquileres_repo.obtener(id_alquiler)
    codigo = alquiler["codigo"] if alquiler else id_alquiler
    ok, motivo = alquileres_repo.completar(id_alquiler, id_estacion_fin=estacion_fin_id)
    if ok:
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "alquileres",
            f"Alquiler completado (devuelto): {codigo}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/alquileres", "success", f"Alquiler {codigo} completado.")
    return _flash(request, f"/empleado/operacion/alquileres/{id_alquiler}", "error", motivo)


@router.get("/operacion/rebalanceo", response_class=HTMLResponse)
async def op_rebalanceo(request: Request):
    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    estaciones: list[dict] = []
    try:
        pb = _pb()
        bicicletas = pb.list_records("bicicletas", sort="codigo", per_page=500).get("items", [])
        estaciones = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/operacion/rebalanceo.html", _ctx(request,
        title="Rebalanceo de Bicicletas", flash=flash,
        bicicletas=bicicletas, estaciones=estaciones,
    ))


@router.post("/operacion/rebalanceo/trasladar")
async def op_rebalanceo_trasladar(
    request: Request,
    bicicleta_id:        str = Form(...),
    bicicleta_codigo:    str = Form(...),
    estacion_destino_id: str = Form(...),
    observaciones:       str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        bici = pb.get_record("bicicletas", bicicleta_id)
        origen = bici.get("estacion") or "—"
        destino = pb.get_record("estaciones", estacion_destino_id)
        destino_nombre = (destino.get("nombre") or "").strip()

        pb.update_record("bicicletas", bicicleta_id, {"estacion": destino_nombre, "estado": "disponible"})

        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "bicicletas",
            f"Rebalanceo: {bicicleta_codigo} trasladada de {origen} a {destino_nombre}"
            + (f" — {observaciones}" if observaciones else ""), request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/rebalanceo", "success",
                      f"Bicicleta {bicicleta_codigo} trasladada de {origen} a {destino_nombre}.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/rebalanceo", "error", str(e))


@router.get("/operacion/pagos", response_class=HTMLResponse)
async def op_pagos(request: Request):
    flash = request.session.pop("flash", None)
    pagos: list[dict] = []
    transferencias: list[dict] = []
    efectivo_pendiente: list[dict] = []
    try:
        pb = _pb()
        pagos = _pagos_del_dia(pb)
        transferencias = pb.list_records(
            "pagos", filter='estado = "verificacion_pendiente"',
            sort="-fecha_pago", per_page=200,
        ).get("items", [])
        efectivo_pendiente = pb.list_records(
            "pagos", filter='estado = "pendiente_efectivo"',
            sort="-fecha_pago", per_page=200,
        ).get("items", [])
    except Exception:
        pass

    total_pagado = sum(float(p.get("monto_total") or 0) for p in pagos if p.get("estado") == "pagado")
    total_pendiente = sum(float(p.get("monto_total") or 0) for p in pagos if p.get("estado") == "pendiente")

    return templates.TemplateResponse(request, "empleado/operacion/pagos.html", _ctx(request,
        title="Pagos del Día", flash=flash, pagos=pagos,
        transferencias=transferencias, efectivo_pendiente=efectivo_pendiente,
        total_pagado=total_pagado, total_pendiente=total_pendiente,
        pb_url=settings.pb_url,
    ))


ESTADO_PAGO_LABEL = {"pagado": "Pagado", "pendiente": "Pendiente"}


def _pagos_del_dia(pb) -> list[dict]:
    hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return pb.list_records(
        "pagos",
        filter=f'fecha_pago >= {filter_literal(f"{hoy} 00:00:00")} || estado = "pendiente"',
        sort="-fecha_pago", per_page=300,
    ).get("items", [])


def _pagos_columnas_filas(pagos: list[dict]) -> tuple[list[ColumnaReporte], list[list], list]:
    columnas = [
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Bicicleta", ancho=16),
        ColumnaReporte("Duración (min)", ancho=14, formato="entero"),
        ColumnaReporte("Monto", ancho=14, formato="moneda"),
        ColumnaReporte("Método", ancho=16),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Comprobante", ancho=20),
    ]
    filas = [
        [
            p.get("ciclista_nombre") or "—",
            p.get("tipo_bicicleta") or "—",
            int(p.get("duracion_minutos") or 0),
            float(p.get("monto_total") or 0),
            (p.get("metodo_pago") or "—").capitalize(),
            ESTADO_PAGO_LABEL.get(p.get("estado"), "Cancelado"),
            p.get("comprobante_numero") or "—",
        ]
        for p in pagos
    ]
    fila_total = [f"Total: {len(filas)} pagos", None, None, sum(f[3] for f in filas), None, None, None]
    return columnas, filas, fila_total


@router.get("/operacion/pagos/excel")
def op_pagos_excel():
    pagos = _pagos_del_dia(_pb())
    columnas, filas, fila_total = _pagos_columnas_filas(pagos)
    return generar_excel_reporte(
        titulo="UrbanBike — Pagos del Día",
        subtitulo=f"Total: {len(pagos)} pagos",
        columnas=columnas, filas=filas, fila_total=fila_total, nombre_hoja="Pagos",
        nombre_archivo=f"urbanbike_pagos_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/operacion/pagos/pdf")
def op_pagos_pdf():
    pagos = _pagos_del_dia(_pb())
    columnas, filas, fila_total = _pagos_columnas_filas(pagos)
    return generar_pdf_reporte(
        titulo="Pagos del Día",
        subtitulo=f"Total: {len(pagos)} pagos",
        columnas=columnas, filas=filas, fila_total=fila_total,
        nombre_archivo=f"urbanbike_pagos_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


def _notificar_pago_aprobado(pb, registro: dict) -> None:
    """Punto único real de la notificación "pago aprobado" (ver
    docs/Requerimientos_Mejoras_UrbanBike.md, punto 11.1) -- llamado desde
    cada camino real que marca un pago como 'pagado' (efectivo, tarjeta,
    transferencia verificada). `registro` es el pago tal como se leyó
    ANTES del update; monto_total/ciclista_id no cambian en la
    confirmación, así que no hace falta releerlo."""
    notificaciones_repo.notificar_usuario(
        pb, registro.get("ciclista_id", ""), tipo="pago_aprobado",
        titulo="Pago aprobado",
        mensaje=f"Tu pago de ${float(registro.get('monto_total') or 0):.2f} fue aprobado.",
        enlace="/ciclista/pagos",
    )


@router.get("/operacion/pagos/cobrar/{pago_id}", response_class=HTMLResponse)
async def op_pagos_cobrar(request: Request, pago_id: str):
    flash = request.session.pop("flash", None)
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
    except Exception:
        return _flash(request, "/empleado/operacion/alquileres", "error", "Pago no encontrado.")

    if registro.get("estado") == "pagado":
        return _flash(request, "/empleado/operacion/pagos", "info", "Este pago ya fue cobrado.")

    viaje: dict = {}
    try:
        viaje = pb.get_record("viajes", registro.get("viaje_id", ""))
    except Exception:
        pass

    cuentas: list[dict] = []
    try:
        cuentas = pb.list_records("cuentas_bancarias", filter="activa = true", sort="banco", per_page=50).get("items", [])
    except Exception:
        pass

    return templates.TemplateResponse(request, "empleado/operacion/cobrar_presencial.html", _ctx(request,
        title="Cobro Presencial", flash=flash, pago=registro, viaje=viaje, cuentas=cuentas,
        duracion_hms=_duracion_hms(registro.get("duracion_minutos") or 0),
    ))


@router.post("/operacion/pagos/cobrar/{pago_id}/confirmar")
async def op_pagos_cobrar_confirmar(
    request: Request,
    pago_id: str,
    metodo_pago:           str = Form(...),
    monto_recibido:        str = Form(""),
    numero_tarjeta:        str = Form(""),
    nombre_titular:        str = Form(""),
    mes_expiracion:        str = Form(""),
    anio_expiracion:       str = Form(""),
    numero_cuenta_origen:  str = Form(""),
    comprobante_imagen:    UploadFile | None = File(None),
):
    user = getattr(request.state, "user", {})
    volver = f"/empleado/operacion/pagos/cobrar/{pago_id}"
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("estado") == "pagado":
            return _flash(request, "/empleado/operacion/alquileres", "info", "Este pago ya fue cobrado.")

        ahora = datetime.now(timezone.utc)
        comprobante = registro.get("comprobante_numero") or f"UB-{ahora.strftime('%Y%m%d')}-{pago_id[-4:].upper()}"

        # ── Efectivo: el empleado cobra en el momento ────────────────────────
        if metodo_pago == "efectivo":
            try:
                monto = float(monto_recibido)
            except ValueError:
                return _flash(request, volver, "error", "Monto recibido no válido.")
            pb.update_record("pagos", pago_id, {
                "estado":                       "pagado",
                "metodo_pago":                  "efectivo",
                "fecha_pago":                   _ahora(),
                "fecha_confirmacion":           _ahora(),
                "comprobante_numero":           comprobante,
                "confirmado_por_empleado_id":   user.get("id", ""),
                "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
                "observaciones_pago":           f"Monto recibido: ${monto:.2f}",
                "es_presencial":                True,
                "empleado_id":                  user.get("id", ""),
            })
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Cobro presencial en efectivo (${monto:.2f}): comprobante {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            _notificar_pago_aprobado(pb, registro)
            return _flash(request, "/empleado/operacion/alquileres", "success", "Pago cobrado en efectivo.")

        # ── Tarjeta (simulado, igual que el flujo del ciclista) ──────────────
        if metodo_pago == "tarjeta":
            digitos = "".join(ch for ch in numero_tarjeta if ch.isdigit())
            if len(digitos) < 4 or not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
                return _flash(request, volver, "error", "Completa todos los datos de la tarjeta.")
            ultimos4 = digitos[-4:]
            pb.update_record("pagos", pago_id, {
                "estado":                       "pagado",
                "metodo_pago":                  "tarjeta",
                "fecha_pago":                   _ahora(),
                "fecha_confirmacion":           _ahora(),
                "comprobante_numero":           comprobante,
                "numero_tarjeta_ultimos4":      ultimos4,
                "confirmado_por_empleado_id":   user.get("id", ""),
                "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
                "es_presencial":                True,
                "empleado_id":                  user.get("id", ""),
            })
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Cobro presencial con tarjeta (•••• {ultimos4}): comprobante {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            _notificar_pago_aprobado(pb, registro)
            return _flash(request, "/empleado/operacion/alquileres", "success", "Pago cobrado con tarjeta.")

        # ── Transferencia (queda pendiente de verificación, igual que el ciclista) ──
        if metodo_pago == "transferencia":
            tiene_archivo = comprobante_imagen is not None and comprobante_imagen.filename
            if not numero_cuenta_origen.strip() or not tiene_archivo:
                return _flash(request, volver, "error",
                    "Ingresa el número de cuenta de origen y adjunta el comprobante de la transferencia.")
            if comprobante_imagen.content_type not in ("image/jpeg", "image/png", "application/pdf"):
                return _flash(request, volver, "error", "El comprobante debe ser JPG, PNG o PDF.")
            if comprobante_imagen.size and comprobante_imagen.size > 5 * 1024 * 1024:
                return _flash(request, volver, "error", "El comprobante no debe superar los 5 MB.")

            contenido = await comprobante_imagen.read()
            pb.update_record_with_file("pagos", pago_id, {
                "estado":               "verificacion_pendiente",
                "metodo_pago":          "transferencia",
                "comprobante_numero":   comprobante,
                "numero_cuenta_origen": numero_cuenta_origen.strip(),
                "es_presencial":        True,
                "empleado_id":          user.get("id", ""),
            }, {"comprobante_imagen": (comprobante_imagen.filename, contenido, comprobante_imagen.content_type)})

            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Comprobante de transferencia presencial subido para verificación: {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            return _flash(request, "/empleado/operacion/pagos", "info",
                          "Comprobante recibido. Queda pendiente de verificación.")

        return _flash(request, volver, "error", "Método de pago no válido.")
    except Exception as e:
        return _flash(request, volver, "error", str(e))


@router.post("/operacion/pagos/{pago_id}/registrar")
async def op_pagos_registrar(request: Request, pago_id: str):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("estado") != "pagado":
            ahora = datetime.now(timezone.utc)
            comprobante = registro.get("comprobante_numero") or f"UB-{ahora.strftime('%Y%m%d')}-{pago_id[-4:].upper()}"
            pb.update_record("pagos", pago_id, {
                "estado":             "pagado",
                "metodo_pago":        "efectivo",
                "fecha_pago":         _ahora(),
                "comprobante_numero": comprobante,
            })
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Pago en efectivo registrado manualmente: comprobante {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            _notificar_pago_aprobado(pb, registro)
        return _flash(request, "/empleado/operacion/pagos", "success", "Pago registrado como pagado en efectivo.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/pagos", "error", str(e))


@router.post("/operacion/pagos/{pago_id}/aprobar-transferencia")
async def op_pagos_aprobar_transferencia(
    request: Request, pago_id: str,
    observaciones: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("estado") != "verificacion_pendiente":
            return _flash(request, "/empleado/operacion/pagos", "error", "Este pago ya no está pendiente de verificación.")
        ahora = datetime.now(timezone.utc)
        comprobante = registro.get("comprobante_numero") or f"UB-{ahora.strftime('%Y%m%d')}-{pago_id[-4:].upper()}"
        pb.update_record("pagos", pago_id, {
            "estado":                       "pagado",
            "fecha_pago":                   _ahora(),
            "fecha_confirmacion":           _ahora(),
            "comprobante_numero":           comprobante,
            "confirmado_por_empleado_id":   user.get("id", ""),
            "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
            "observaciones_pago":           observaciones.strip(),
        })
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "pagos",
            f"Transferencia aprobada: comprobante {comprobante}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        _notificar_pago_aprobado(pb, registro)
        return _flash(request, "/empleado/operacion/pagos", "success", "Transferencia aprobada y pago confirmado.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/pagos", "error", str(e))


@router.post("/operacion/pagos/{pago_id}/rechazar-transferencia")
async def op_pagos_rechazar_transferencia(
    request: Request, pago_id: str,
    motivo: str = Form(...),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("estado") != "verificacion_pendiente":
            return _flash(request, "/empleado/operacion/pagos", "error", "Este pago ya no está pendiente de verificación.")
        pb.update_record("pagos", pago_id, {
            "estado":                       "rechazado",
            "fecha_confirmacion":           _ahora(),
            "confirmado_por_empleado_id":   user.get("id", ""),
            "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
            "observaciones_pago":           motivo.strip(),
        })
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "pagos",
            f"Transferencia rechazada: {motivo.strip()}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/operacion/pagos", "success", "Transferencia rechazada. Se notificó al ciclista.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/pagos", "error", str(e))


@router.post("/operacion/pagos/{pago_id}/confirmar-efectivo")
async def op_pagos_confirmar_efectivo(
    request: Request, pago_id: str,
    monto_recibido: str = Form(...),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("estado") != "pendiente_efectivo":
            return _flash(request, "/empleado/operacion/pagos", "error", "Este pago ya no está pendiente de cobro en efectivo.")
        try:
            monto = float(monto_recibido)
        except ValueError:
            return _flash(request, "/empleado/operacion/pagos", "error", "Monto recibido no válido.")
        ahora = datetime.now(timezone.utc)
        comprobante = registro.get("comprobante_numero") or f"UB-{ahora.strftime('%Y%m%d')}-{pago_id[-4:].upper()}"
        pb.update_record("pagos", pago_id, {
            "estado":                       "pagado",
            "metodo_pago":                  "efectivo",
            "fecha_pago":                   _ahora(),
            "fecha_confirmacion":           _ahora(),
            "comprobante_numero":           comprobante,
            "confirmado_por_empleado_id":   user.get("id", ""),
            "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
            "observaciones_pago":           f"Monto recibido: ${monto:.2f}",
        })
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "pagos",
            f"Recepción de efectivo confirmada (${monto:.2f}): comprobante {comprobante}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        _notificar_pago_aprobado(pb, registro)
        return _flash(request, "/empleado/operacion/pagos", "success", "Recepción de efectivo confirmada.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/pagos", "error", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# MANTENIMIENTO — solo recibe y trabaja órdenes; no las crea ni las cierra
# (esas acciones ahora corresponden a vigilancia).
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/mantenimiento/dashboard", response_class=HTMLResponse)
async def mnt_dashboard(request: Request):
    flash = request.session.pop("flash", None)
    en_mnt: list[dict] = []
    try:
        en_mnt = _pb().list_records("bicicletas", filter='estado = "mantenimiento"', per_page=500).get("items", [])
    except Exception:
        pass

    tipo_counts = {"classic_bike": 0, "electric_bike": 0}
    for b in en_mnt:
        tipo_counts[b.get("tipo", "classic_bike")] = tipo_counts.get(b.get("tipo", "classic_bike"), 0) + 1

    ordenes_pendientes = 0
    try:
        res = _pb().list_records("ordenes_mant", filter='estado = "pendiente"', per_page=1)
        ordenes_pendientes = res.get("totalItems", 0)
    except Exception:
        pass

    return templates.TemplateResponse(request, "empleado/mantenimiento/dashboard.html", _ctx(request,
        title="Dashboard — Mantenimiento", flash=flash,
        en_mnt=en_mnt, total_mnt=len(en_mnt), ordenes_pendientes=ordenes_pendientes,
        chart_labels=json.dumps(["Clásica", "Eléctrica"]),
        chart_values=json.dumps([tipo_counts["classic_bike"], tipo_counts["electric_bike"]]),
    ))


ESTADO_ORDEN_LABEL = {
    "abierta": "Abierta", "diagnostico": "Diagnóstico", "en_reparacion": "En reparación",
    "espera_repuesto": "Espera de repuesto", "cerrada": "Cerrada",
}
ORIGEN_ORDEN_LABEL = {
    "preventivo": "Preventivo", "devolucion": "Devolución", "reporte": "Reporte", "inspeccion": "Inspección",
}
TIPO_FALLA_LABEL = {
    "frenos": "Frenos", "transmision": "Transmisión", "neumatico": "Neumático",
    "electrico": "Eléctrico", "estructural": "Estructural", "otro": "Otro",
}
PRIORIDAD_LABEL = {"alta": "Alta", "media": "Media", "baja": "Baja"}


@router.get("/mantenimiento/ordenes", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:leer"))])
async def mnt_ordenes(
    request: Request,
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""),
    prioridad: str = Query(""), page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    per_page = 10
    filas, total = ordenes_repo.listar(
        q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, page=page, per_page=per_page,
    )
    fotos_bici = bicicletas_repo.fotos_por_codigo([o["bicicleta_codigo"] for o in filas])
    for o in filas:
        o["foto_url"] = fotos_bici.get(o["bicicleta_codigo"], "")
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes.html", _ctx(request,
        title="Órdenes de Mantenimiento", flash=flash, ordenes=filas, total=total,
        page=max(1, page), per_page=per_page,
        total_paginas=max(1, -(-total // per_page)),
        q=q, estado=estado, tecnico=tecnico, prioridad=prioridad,
        tecnicos=ordenes_repo.listar_tecnicos(),
        estados=ordenes_repo.ESTADOS_VALIDOS, estado_label=ESTADO_ORDEN_LABEL,
        prioridades=ordenes_repo.PRIORIDADES_VALIDAS, prioridad_label=PRIORIDAD_LABEL,
        origen_label=ORIGEN_ORDEN_LABEL, tipo_falla_label=TIPO_FALLA_LABEL,
    ))


def _ordenes_columnas_filas(ordenes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=12),
        ColumnaReporte("Bicicleta", ancho=12),
        ColumnaReporte("Origen", ancho=14),
        ColumnaReporte("Tipo de falla", ancho=14),
        ColumnaReporte("Prioridad", ancho=12),
        ColumnaReporte("Técnico", ancho=22),
        ColumnaReporte("Apertura", ancho=18),
        ColumnaReporte("Cierre", ancho=18),
        ColumnaReporte("Costo repuestos", ancho=14, formato="moneda"),
        ColumnaReporte("Costo mano de obra", ancho=16, formato="moneda"),
        ColumnaReporte("Estado", ancho=16),
    ]
    filas = [
        [
            o["codigo"], o["bicicleta_codigo"],
            ORIGEN_ORDEN_LABEL.get(o["origen"], o["origen"]),
            TIPO_FALLA_LABEL.get(o["tipo_falla"], o["tipo_falla"]),
            PRIORIDAD_LABEL.get(o["prioridad"], o["prioridad"]),
            o["tecnico_nombre"],
            o["fecha_apertura"].strftime("%Y-%m-%d %H:%M") if o.get("fecha_apertura") else "—",
            o["fecha_cierre"].strftime("%Y-%m-%d %H:%M") if o["estado_reparacion"] == "cerrada" else "—",
            float(o.get("costo_repuestos") or 0),
            float(o.get("costo_mano_obra") or 0),
            ESTADO_ORDEN_LABEL.get(o["estado_reparacion"], o["estado_reparacion"]),
        ]
        for o in ordenes
    ]
    return columnas, filas


def _ordenes_subtitulo(q: str, estado: str, tecnico: str, prioridad: str, total: int) -> str:
    partes = [f"Total: {total} órdenes"]
    if q:
        partes.append(f'Búsqueda: "{q}"')
    if estado:
        partes.append(f"Estado: {ESTADO_ORDEN_LABEL.get(estado, estado)}")
    if tecnico:
        nombre = next((t["nombre"] for t in ordenes_repo.listar_tecnicos() if str(t["id"]) == tecnico), tecnico)
        partes.append(f"Técnico: {nombre}")
    if prioridad:
        partes.append(f"Prioridad: {PRIORIDAD_LABEL.get(prioridad, prioridad)}")
    return "  |  ".join(partes)


@router.get("/mantenimiento/ordenes/excel")
def mnt_ordenes_excel(
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""), prioridad: str = Query(""),
):
    ordenes, total = ordenes_repo.listar(q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, page=1, per_page=100_000)
    columnas, filas = _ordenes_columnas_filas(ordenes)
    fila_total = [f"Total: {total} órdenes"] + [None] * 7 + [sum(f[8] for f in filas), sum(f[9] for f in filas), None]
    return generar_excel_reporte(
        titulo="UrbanBike — Órdenes de Mantenimiento",
        subtitulo=_ordenes_subtitulo(q, estado, tecnico, prioridad, total),
        columnas=columnas, filas=filas, fila_total=fila_total, nombre_hoja="Órdenes",
        nombre_archivo=f"urbanbike_ordenes_mantenimiento_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/mantenimiento/ordenes/pdf")
def mnt_ordenes_pdf(
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""), prioridad: str = Query(""),
):
    ordenes, total = ordenes_repo.listar(q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, page=1, per_page=100_000)
    columnas, filas = _ordenes_columnas_filas(ordenes)
    fila_total = [f"Total: {total} órdenes"] + [None] * 7 + [sum(f[8] for f in filas), sum(f[9] for f in filas), None]
    return generar_pdf_reporte(
        titulo="Órdenes de Mantenimiento",
        subtitulo=_ordenes_subtitulo(q, estado, tecnico, prioridad, total),
        columnas=columnas, filas=filas, fila_total=fila_total,
        nombre_archivo=f"urbanbike_ordenes_mantenimiento_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/mantenimiento/ordenes/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:crear"))])
async def mnt_ordenes_nueva(request: Request):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes_form.html", _ctx(request,
        title="Nueva orden de mantenimiento", flash=flash, modo="crear", orden=None,
        bicicletas=bicicletas_repo.listar(page=1, per_page=500)[0],
        tecnicos=ordenes_repo.listar_tecnicos(),
        origenes=ordenes_repo.ORIGENES_VALIDOS, origen_label=ORIGEN_ORDEN_LABEL,
        tipos_falla=ordenes_repo.TIPOS_FALLA_VALIDOS, tipo_falla_label=TIPO_FALLA_LABEL,
        prioridades=ordenes_repo.PRIORIDADES_VALIDAS, prioridad_label=PRIORIDAD_LABEL,
        estados=ordenes_repo.ESTADOS_VALIDOS, estado_label=ESTADO_ORDEN_LABEL,
    ))


@router.post("/mantenimiento/ordenes/crear", dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:crear"))])
async def mnt_ordenes_crear(
    request: Request,
    id_bicicleta: str = Form(...), origen: str = Form(...), tipo_falla: str = Form(...),
    prioridad: str = Form("media"), id_tecnico: str = Form(...), diagnostico: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        nuevo_id = ordenes_repo.crear(
            id_bicicleta=id_bicicleta, origen=origen, tipo_falla=tipo_falla,
            prioridad=prioridad, id_tecnico=id_tecnico, diagnostico=diagnostico,
        )
        orden = ordenes_repo.obtener(nuevo_id)
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "ordenes_mantenimiento",
            f"Orden de mantenimiento registrada: {orden['codigo']} ({orden['bicicleta_codigo']})", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/mantenimiento/ordenes", "success", f"Orden {orden['codigo']} registrada correctamente.")
    except Exception as e:
        return _flash(request, "/empleado/mantenimiento/ordenes/nueva", "error", str(e))


@router.get("/mantenimiento/ordenes/{oid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:leer"))])
async def mnt_ordenes_detalle(request: Request, oid: str, modo: str = Query("ver")):
    flash = request.session.pop("flash", None)
    orden = ordenes_repo.obtener(oid)
    if not orden:
        return _flash(request, "/empleado/mantenimiento/ordenes", "error", "Orden no encontrada.")
    n_repuestos = ordenes_repo.contar_repuestos(oid)
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes_form.html", _ctx(request,
        title=f"Orden {orden['codigo']}", flash=flash, modo="editar" if modo == "editar" else "ver",
        orden=orden, n_repuestos=n_repuestos,
        bicicletas=bicicletas_repo.listar(page=1, per_page=500)[0],
        tecnicos=ordenes_repo.listar_tecnicos(),
        origenes=ordenes_repo.ORIGENES_VALIDOS, origen_label=ORIGEN_ORDEN_LABEL,
        tipos_falla=ordenes_repo.TIPOS_FALLA_VALIDOS, tipo_falla_label=TIPO_FALLA_LABEL,
        prioridades=ordenes_repo.PRIORIDADES_VALIDAS, prioridad_label=PRIORIDAD_LABEL,
        estados=ordenes_repo.ESTADOS_VALIDOS, estado_label=ESTADO_ORDEN_LABEL,
    ))


@router.post("/mantenimiento/ordenes/{oid}/editar", dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:actualizar"))])
async def mnt_ordenes_editar(
    request: Request, oid: str,
    id_bicicleta: str = Form(...), origen: str = Form(...), tipo_falla: str = Form(...),
    prioridad: str = Form(...), estado_reparacion: str = Form(...), id_tecnico: str = Form(...),
    diagnostico: str = Form(""), costo_repuestos: str = Form("0"), costo_mano_obra: str = Form("0"),
):
    user = getattr(request.state, "user", {})
    try:
        ordenes_repo.actualizar(
            oid, id_bicicleta=id_bicicleta, origen=origen, tipo_falla=tipo_falla,
            prioridad=prioridad, estado_reparacion=estado_reparacion, id_tecnico=id_tecnico,
            diagnostico=diagnostico,
            costo_repuestos=float(costo_repuestos or 0), costo_mano_obra=float(costo_mano_obra or 0),
        )
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "ordenes_mantenimiento",
            f"Orden actualizada (id: {oid})", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "success", "Orden actualizada.")
    except Exception as e:
        return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "error", str(e))


@router.post("/mantenimiento/ordenes/{oid}/eliminar", dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:eliminar"))])
async def mnt_ordenes_eliminar(request: Request, oid: str):
    user = getattr(request.state, "user", {})
    orden = ordenes_repo.obtener(oid)
    codigo = orden["codigo"] if orden else oid
    ok, motivo = ordenes_repo.eliminar(oid)
    if ok:
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "eliminar", "ordenes_mantenimiento",
            f"Orden eliminada: {codigo}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/mantenimiento/ordenes", "success", f"Orden {codigo} eliminada.")
    return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "error", motivo)


@router.get("/mantenimiento/bicicletas", response_class=HTMLResponse)
async def mnt_bicicletas(request: Request):
    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", filter='estado = "mantenimiento"', sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/mantenimiento/bicicletas.html", _ctx(request,
        title="Bicicletas en Mantenimiento", flash=flash, bicicletas=bicicletas,
    ))


def _mnt_bicicletas_columnas_filas(bicicletas: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=14),
        ColumnaReporte("Tipo", ancho=16),
        ColumnaReporte("Estación", ancho=22),
        ColumnaReporte("Notas", ancho=40),
    ]
    filas = [
        [
            b.get("codigo") or "—",
            "Eléctrica" if b.get("tipo") == "electric_bike" else "Clásica",
            b.get("estacion") or "—",
            b.get("notas") or "—",
        ]
        for b in bicicletas
    ]
    return columnas, filas


@router.get("/mantenimiento/bicicletas/excel")
def mnt_bicicletas_excel():
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", filter='estado = "mantenimiento"', sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    columnas, filas = _mnt_bicicletas_columnas_filas(bicicletas)
    return generar_excel_reporte(
        titulo="UrbanBike — Bicicletas en Mantenimiento",
        subtitulo=f"Total: {len(bicicletas)} bicicletas",
        columnas=columnas, filas=filas, nombre_hoja="Mantenimiento",
        nombre_archivo=f"urbanbike_bicicletas_mantenimiento_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/mantenimiento/bicicletas/pdf")
def mnt_bicicletas_pdf():
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", filter='estado = "mantenimiento"', sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    columnas, filas = _mnt_bicicletas_columnas_filas(bicicletas)
    return generar_pdf_reporte(
        titulo="Bicicletas en Mantenimiento",
        subtitulo=f"Total: {len(bicicletas)} bicicletas",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_bicicletas_mantenimiento_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


# ══════════════════════════════════════════════════════════════════════════════
# VIGILANCIA
# ══════════════════════════════════════════════════════════════════════════════

_LIMITE_INFRACCIONES_BLOQUEO = 3

_CATEGORIA_CHECKLIST_LABEL = {
    "frenos": "Frenos", "transmision": "Transmisión", "ruedas": "Ruedas",
    "luces": "Luces", "cuadro": "Cuadro", "accesorios": "Accesorios",
}

# Categoria real del checklist -> tipo_falla real de ordenes_mantenimiento
# (ver ordenes_repo.ESTADOS_VALIDOS/TIPOS_FALLA_VALIDOS). Usado al generar
# automaticamente la orden de una devolucion reprobada (Nivel 3).
_CATEGORIA_A_TIPO_FALLA = {
    "frenos": "frenos", "transmision": "transmision", "ruedas": "neumatico",
    "luces": "electrico", "cuadro": "estructural", "accesorios": "otro",
}


@router.get("/vigilancia/dashboard", response_class=HTMLResponse)
async def vig_dashboard(request: Request):
    flash = request.session.pop("flash", None)
    estaciones: list[dict] = []
    try:
        estaciones = _pb().list_records("estaciones", sort="nombre", per_page=500).get("items", [])
    except Exception:
        pass
    activas   = sum(1 for e in estaciones if e.get("activa"))
    inactivas = len(estaciones) - activas

    pendientes_validacion = 0
    try:
        pendientes_validacion = _pb().list_records(
            "viajes", filter='estado = "pendiente_validacion"', per_page=1,
        ).get("totalItems", 0)
    except Exception:
        pass

    viajes_hoy   = 0
    retrasos_hoy = 0
    dur_prom_hoy = 0.0
    top_activas: list[dict] = []
    ch_ok = True
    try:
        res_hoy = ch.query_one("""
            SELECT count() AS total, countIf(duracion_min > 60) AS retrasos,
                   round(avg(duracion_min), 1) AS dur_prom
            FROM fact_viajes
            WHERE fecha_inicio >= toDateTime('2023-10-31 00:00:00')
              AND fecha_inicio <  toDateTime('2023-11-01 00:00:00')
        """) or {}
        viajes_hoy   = res_hoy.get("total", 0)
        retrasos_hoy = res_hoy.get("retrasos", 0)
        dur_prom_hoy = res_hoy.get("dur_prom", 0.0)
        top_activas = ch.query("""
            SELECT e.nombre_estacion AS nombre, count() AS viajes,
                   countIf(duracion_min > 60) AS retrasos
            FROM fact_viajes f
            LEFT JOIN dim_estaciones e ON f.id_estacion_inicio = e.id_estacion
            WHERE fecha_inicio >= toDateTime('2023-10-31 00:00:00')
              AND fecha_inicio <  toDateTime('2023-11-01 00:00:00')
            GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT 10
        """)
    except Exception:
        ch_ok = False

    return templates.TemplateResponse(request, "empleado/vigilancia/dashboard.html", _ctx(request,
        title="Dashboard — Vigilancia", flash=flash,
        estaciones=estaciones, activas=activas, inactivas=inactivas,
        pendientes_validacion=pendientes_validacion,
        viajes_hoy=viajes_hoy, retrasos_hoy=retrasos_hoy, dur_prom_hoy=dur_prom_hoy,
        top_activas=top_activas, ch_ok=ch_ok,
        chart_labels=json.dumps([str(r.get("nombre") or "N/A")[:25] for r in top_activas]),
        chart_viajes=json.dumps([r["viajes"] for r in top_activas]),
        chart_retraso=json.dumps([r["retrasos"] for r in top_activas]),
    ))


@router.get("/vigilancia/seguimiento", response_class=HTMLResponse)
async def vig_seguimiento(request: Request):
    flash = request.session.pop("flash", None)
    viajes_activos: list[dict] = []
    estaciones: list[dict] = []
    try:
        pb = _pb()
        viajes_activos = pb.list_records("viajes", filter='estado = "activo"', sort="-fecha_inicio", per_page=200).get("items", [])
        estaciones = pb.list_records("estaciones", sort="nombre", per_page=50).get("items", [])
    except Exception:
        pass

    return templates.TemplateResponse(request, "empleado/vigilancia/seguimiento.html", _ctx(request,
        title="Seguimiento de Viajes Activos", flash=flash,
        viajes=viajes_activos,
        estaciones_json=json.dumps(estaciones),
        viajes_json=json.dumps(viajes_activos),
    ))


def _vig_tiempo_transcurrido_min(fecha_inicio: str) -> int:
    """Mismo calculo que el JS de seguimiento.html/devoluciones.html
    (actualizarTiempos()), replicado en Python para el export -- el
    minuto exacto depende de cuando se genera el archivo, igual que en
    pantalla."""
    try:
        inicio = datetime.fromisoformat(fecha_inicio.replace("Z", "+00:00"))
        return max(0, int((datetime.now(timezone.utc) - inicio).total_seconds() / 60))
    except Exception:
        return 0


def _vig_seguimiento_columnas_filas(viajes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Estación de inicio", ancho=26),
        ColumnaReporte("Inicio", ancho=18),
        ColumnaReporte("Tiempo transcurrido (min)", ancho=22, formato="entero"),
        ColumnaReporte("Alerta", ancho=14),
    ]
    filas = []
    for v in viajes:
        mins = _vig_tiempo_transcurrido_min(v.get("fecha_inicio", ""))
        filas.append([
            v.get("bicicleta_codigo") or "—",
            v.get("ciclista_nombre") or "—",
            v.get("estacion_inicio_nombre") or "—",
            (v.get("fecha_inicio") or "—").replace("T", " ").replace("Z", ""),
            mins,
            f"Supera {_LIMITE_ALERTA_MIN} min" if mins > _LIMITE_ALERTA_MIN else "Normal",
        ])
    return columnas, filas


def _vig_seguimiento_viajes() -> list[dict]:
    return _pb().list_records("viajes", filter='estado = "activo"', sort="-fecha_inicio", per_page=200).get("items", [])


@router.get("/vigilancia/seguimiento/excel")
def vig_seguimiento_excel():
    viajes = _vig_seguimiento_viajes()
    columnas, filas = _vig_seguimiento_columnas_filas(viajes)
    fila_total = [f"Total: {len(viajes)} viajes activos", None, None, None, None, None]
    return generar_excel_reporte(
        titulo="UrbanBike — Seguimiento de Viajes Activos",
        subtitulo=f"Total: {len(viajes)} viajes activos en este momento",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Viajes Activos",
        nombre_archivo="urbanbike_vigilancia_seguimiento.xlsx",
    )


@router.get("/vigilancia/seguimiento/pdf")
def vig_seguimiento_pdf():
    viajes = _vig_seguimiento_viajes()
    columnas, filas = _vig_seguimiento_columnas_filas(viajes)
    fila_total = [f"Total: {len(viajes)} viajes activos", None, None, None, None, None]
    return generar_pdf_reporte(
        titulo="Seguimiento de Viajes Activos",
        subtitulo=f"Total: {len(viajes)} viajes activos en este momento",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo="urbanbike_vigilancia_seguimiento.pdf",
    )


@router.get("/vigilancia/devoluciones", response_class=HTMLResponse)
async def vig_devoluciones(request: Request):
    flash = request.session.pop("flash", None)
    viajes_activos: list[dict] = []
    viajes_pendientes: list[dict] = []
    estaciones: list[dict] = []
    try:
        pb = _pb()
        viajes_activos = pb.list_records("viajes", filter='estado = "activo"', sort="-fecha_inicio", per_page=200).get("items", [])
        viajes_pendientes = pb.list_records(
            "viajes", filter='estado = "pendiente_validacion"', sort="-fecha_fin", per_page=200,
        ).get("items", [])
        estaciones = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50).get("items", [])
    except Exception:
        pb = None

    fotos_bici = bicicletas_repo.fotos_por_codigo(
        [v.get("bicicleta_codigo", "") for v in viajes_activos + viajes_pendientes]
    )
    for v in viajes_activos:
        v["foto_url"] = fotos_bici.get(v.get("bicicleta_codigo", ""), "")

    # Costo en vivo por fila (mismo criterio que el cronómetro del ciclista,
    # ver /static/js/costo-en-vivo.js): el valor real se refresca client-side,
    # esto solo da un primer número al cargar la página sin JS todavía.
    estaciones_nombre = {e["id"]: e.get("nombre", "") for e in estaciones}
    for v in viajes_pendientes:
        v["foto_url"] = fotos_bici.get(v.get("bicicleta_codigo", ""), "")
        v["estacion_fin_nombre"] = estaciones_nombre.get(v.get("estacion_fin_id", ""), "—")
        tipo_membresia = "casual"
        if pb is not None:
            try:
                ciclista_pb = pb.get_record("users", v.get("ciclista_id", ""))
                tipo_membresia = membresias_repo.tipo_membresia_real(ciclista_pb.get("email", ""))
            except Exception:
                pass
        v["precio_hora"] = _tarifa_hora(v.get("bicicleta_codigo", ""), tipo_membresia) if pb is not None else 0.0

    return templates.TemplateResponse(request, "empleado/vigilancia/devoluciones.html", _ctx(request,
        title="Registrar Devoluciones", flash=flash,
        viajes=viajes_activos, viajes_pendientes=viajes_pendientes, estaciones=estaciones,
    ))


@router.post("/vigilancia/devolver/{viaje_id}")
async def vig_devolver(
    request: Request,
    viaje_id: str,
    estacion_fin_id:     str = Form(""),
    estacion_fin_nombre: str = Form(""),
    motivo:              str = Form("voluntaria"),
    observaciones:       str = Form(""),
):
    """Confirmación real de Vigilancia -- funciona para los dos orígenes
    reales: 'activo' (recibida en persona, junto al ciclista -- pide
    estación por formulario, como siempre) y 'pendiente_validacion' (el
    ciclista ya reportó dónde la dejó desde /ciclista/finalizar -- la
    estación real ya vive en el viaje, no hace falta pedirla de nuevo).
    La duración/monto se calculan aquí, con la hora REAL de este
    momento, nunca con la hora en que el ciclista reportó -- eso es lo
    que hace que la espera cuente como parte del cobro real."""
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        origen_pendiente_validacion = viaje.get("estado") == "pendiente_validacion"

        if not estacion_fin_id:
            estacion_fin_id = viaje.get("estacion_fin_id", "")
        if not estacion_fin_nombre and estacion_fin_id:
            try:
                estacion_fin_nombre = pb.get_record("estaciones", estacion_fin_id).get("nombre", "")
            except Exception:
                pass
        estacion_fin_nombre = estacion_fin_nombre or "—"
        if origen_pendiente_validacion:
            motivo = "reportada por el ciclista, validada"

        # Recargo por demora >5h (punto 13, punto 10): las primeras 5h desde
        # que el ciclista REPORTO la devolucion (no desde que Vigilancia la
        # confirma) van al cobro normal; de ahi en adelante es un recargo
        # aparte, nunca mezclado en el mismo numero. Solo aplica cuando el
        # origen es 'pendiente_validacion' -- si Vigilancia recibe la
        # bicicleta en persona, el ciclista esta presente, no hay espera
        # posible.
        ahora = datetime.now(timezone.utc)
        inicio_str = viaje.get("fecha_inicio", "")
        fecha_fin_reportada_str = viaje.get("fecha_fin", "") if origen_pendiente_validacion else ""
        duracion = 0
        retraso_min = 0.0
        try:
            inicio = datetime.fromisoformat(inicio_str.replace("Z", "+00:00"))
            if fecha_fin_reportada_str:
                fecha_fin_reportada = datetime.fromisoformat(fecha_fin_reportada_str.replace("Z", "+00:00"))
                duracion = max(1, int((fecha_fin_reportada - inicio).total_seconds() / 60))
                retraso_min = max(0.0, (ahora - fecha_fin_reportada).total_seconds() / 60 - 300)
            else:
                duracion = max(1, int((ahora - inicio).total_seconds() / 60))
        except Exception:
            pass

        actualizar_viaje = {
            "estado":           "completado",
            "estacion_fin_id":  estacion_fin_id,
            "duracion_minutos": duracion,
        }
        if not origen_pendiente_validacion:
            # Recien se define fecha_fin aca -- si venia de 'pendiente_validacion'
            # ya la tenia (el momento real en que el ciclista reporto), y NO se
            # sobreescribe con la hora de confirmacion de Vigilancia (bug real
            # corregido: antes se pisaba siempre, perdiendo el dato real de
            # cuando el ciclista terminó el viaje).
            actualizar_viaje["fecha_fin"] = _ahora()
        pb.update_record("viajes", viaje_id, actualizar_viaje)

        bici_id = viaje.get("bicicleta_id", "")
        tipo_bicicleta = "classic_bike"
        if bici_id:
            try:
                bici = pb.get_record("bicicletas", bici_id)
                tipo_bicicleta = bici.get("tipo") or "classic_bike"
            except Exception:
                pass
            # La bicicleta queda retenida en mantenimiento hasta que vigilancia
            # complete la inspección de devolución -- recién ahora, nunca
            # antes (si venía de 'pendiente_validacion' seguía 'en_uso').
            pb.update_record("bicicletas", bici_id, {"estado": "mantenimiento", "estacion": estacion_fin_nombre})

        # Crear el pago real del viaje -- recién ahora, con el monto ya
        # congelado a la duración real hasta este momento. Idempotente:
        # si por algún motivo ya existe uno para este viaje, no duplica.
        existentes = pb.list_records("pagos", filter=f'viaje_id = {filter_literal(viaje_id)}', per_page=1).get("items", [])
        if not existentes:
            # El ciclista de este viaje no es el usuario de la sesion (aca
            # esta logueado el empleado de vigilancia), asi que hay que
            # resolver su email real desde PocketBase antes de poder
            # preguntar por su membresia -- mismo patron ya usado para
            # infracciones (pb.get_record("users", ciclista_id)).
            tipo_membresia = "casual"
            try:
                ciclista_pb = pb.get_record("users", viaje.get("ciclista_id", ""))
                tipo_membresia = membresias_repo.tipo_membresia_real(ciclista_pb.get("email", ""))
            except Exception:
                pass
            precio_hora = _tarifa_hora(viaje.get("bicicleta_codigo", ""), tipo_membresia)
            subtotal = round(duracion / 60 * precio_hora, 2)
            recargo_demora = round(retraso_min / 60 * precio_hora, 2)

            # Descuento personal canjeado al iniciar este viaje (ver
            # ciclista.py:reservar()) -- solo sobre el subtotal, nunca sobre
            # el recargo por demora (no tiene sentido descontar una penalizacion).
            descuento_codigo = viaje.get("descuento_codigo") or ""
            descuento_porcentaje = float(viaje.get("descuento_porcentaje") or 0)
            descuento_monto = round(subtotal * descuento_porcentaje / 100, 2) if descuento_porcentaje else 0.0

            monto_total = round(subtotal + recargo_demora - descuento_monto, 2)
            pb.create_record("pagos", {
                "viaje_id":          viaje_id,
                "ciclista_id":       viaje.get("ciclista_id", ""),
                "ciclista_nombre":   viaje.get("ciclista_nombre") or "—",
                "duracion_minutos":  duracion,
                "tipo_bicicleta":    tipo_bicicleta,
                "tipo_membresia":    tipo_membresia,
                "precio_hora":       precio_hora,
                "subtotal":          subtotal,
                "recargo_demora":    recargo_demora,
                "cargo_danos":       0,
                "descuento_codigo":  descuento_codigo,
                "descuento_monto":   descuento_monto,
                "monto_total":       monto_total,
                "estado":            "pendiente",
                "metodo_pago":       "",
                "fecha_pago":        "",
                "fecha_generado":    _ahora(),
                "comprobante_numero": "",
            })

            # Aviso real de que hay algo que pagar (punto 13/11.1): antes solo
            # se notificaba cuando el pago pasaba a "pagado" -- el caso
            # contrario, que el viaje termino con saldo pendiente, no
            # avisaba nada. Se dispara siempre que se crea el pago
            # (independiente de si hubo recargo), con el monto real.
            notificaciones_repo.notificar_usuario(
                pb, viaje.get("ciclista_id", ""), tipo="pago_pendiente",
                titulo="Tienes un pago pendiente",
                mensaje=f"Tu viaje finalizó con un pago pendiente de ${monto_total:.2f}. "
                        "Puedes pagarlo desde Historial de Pagos.",
                enlace="/ciclista/pagos",
            )

            if recargo_demora > 0:
                notificaciones_repo.notificar_usuario(
                    pb, viaje.get("ciclista_id", ""), tipo="penalizacion",
                    titulo="Recargo por demora aplicado",
                    mensaje=f"Se aplicó un recargo de ${recargo_demora:.2f} por demora en la devolución "
                            "(más de 5h desde que reportaste el fin del viaje).",
                    enlace="/ciclista/pagos",
                )

        detalle = f"Devolución {motivo} en {estacion_fin_nombre} (duración real: {duracion} min) — bicicleta retenida para inspección"
        if observaciones:
            detalle += f" — {observaciones}"
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes", detalle, request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        return RedirectResponse(f"/empleado/vigilancia/inspeccion/{bici_id}", status_code=302)
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/devoluciones", "error", str(e))


def _vig_devoluciones_columnas_filas(viajes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Estación de inicio", ancho=26),
        ColumnaReporte("Inicio", ancho=18),
        ColumnaReporte("Tiempo transcurrido (min)", ancho=22, formato="entero"),
    ]
    filas = [
        [
            v.get("bicicleta_codigo") or "—",
            v.get("ciclista_nombre") or "—",
            v.get("estacion_inicio_nombre") or "—",
            (v.get("fecha_inicio") or "—").replace("T", " ").replace("Z", ""),
            _vig_tiempo_transcurrido_min(v.get("fecha_inicio", "")),
        ]
        for v in viajes
    ]
    return columnas, filas


@router.get("/vigilancia/devoluciones/excel")
def vig_devoluciones_excel():
    viajes = _vig_seguimiento_viajes()
    columnas, filas = _vig_devoluciones_columnas_filas(viajes)
    return generar_excel_reporte(
        titulo="UrbanBike — Viajes Activos (Pendientes de Devolución)",
        subtitulo=f"Total: {len(viajes)} viajes activos en este momento",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(viajes)} viajes activos", None, None, None, None],
        nombre_hoja="Viajes Activos",
        nombre_archivo="urbanbike_vigilancia_devoluciones.xlsx",
    )


@router.get("/vigilancia/devoluciones/pdf")
def vig_devoluciones_pdf():
    viajes = _vig_seguimiento_viajes()
    columnas, filas = _vig_devoluciones_columnas_filas(viajes)
    return generar_pdf_reporte(
        titulo="Viajes Activos — Pendientes de Devolución",
        subtitulo=f"Total: {len(viajes)} viajes activos en este momento",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(viajes)} viajes activos", None, None, None, None],
        nombre_archivo="urbanbike_vigilancia_devoluciones.pdf",
    )


def _viaje_para_inspeccion(pb, bici_id: str) -> dict | None:
    """Viaje real más reciente 'completado' de esta bicicleta -- fuente
    real para vincular la inspección al ciclista/pago correctos.

    Antes esto vivía en request.session['devolucion_ctx'], escrito
    únicamente por vig_devolver() -- si Vigilancia llegaba a esta
    pantalla por cualquier otro camino (ej. navegando directo por URL
    con el bici_id), ctx quedaba vacío y el bloque de infracción/cargo
    por daños se saltaba en silencio (ver docs/HOJA_DE_RUTA.md). Ahora
    se deriva siempre de la fila real de `viajes`, sin importar cómo
    se llegó aquí."""
    items = pb.list_records(
        "viajes",
        filter=f'bicicleta_id = {filter_literal(bici_id)} && estado = "completado"',
        sort="-fecha_fin", per_page=1,
    ).get("items", [])
    return items[0] if items else None


@router.get("/vigilancia/inspeccion/{bici_id}", response_class=HTMLResponse)
async def vig_inspeccion(request: Request, bici_id: str):
    flash = request.session.pop("flash", None)
    bici: dict = {}
    viaje: dict | None = None
    pago: dict | None = None
    try:
        pb = _pb()
        bici = pb.get_record("bicicletas", bici_id)
        viaje = _viaje_para_inspeccion(pb, bici_id)
        if viaje:
            pagos_v = pb.list_records(
                "pagos", filter=f'viaje_id = {filter_literal(viaje["id"])}', per_page=1,
            ).get("items", [])
            pago = pagos_v[0] if pagos_v else None
    except Exception:
        pass
    tiene_pago_pendiente = bool(pago) and pago.get("estado") != "pagado"

    checklist_items = inspecciones_repo.listar_checklist_items()
    checklist = [(it["codigo"], it["nombre"]) for it in checklist_items]

    # Ultima inspeccion real de esta bicicleta (Nivel 2, ver docs/HOJA_DE_RUTA.md):
    # si nunca se le hizo una, el checklist visual arranca vacio -- no se
    # inventa un avance de ejemplo.
    id_bicicleta_real = inspecciones_repo.resolver_bicicleta_id(bici.get("codigo", "")) if bici else None
    inspeccion_real = inspecciones_repo.ultima_para_bicicleta(id_bicicleta_real) if id_bicicleta_real else None

    resultado_por_codigo = {d["codigo"]: d["resultado"] for d in inspeccion_real["detalle"]} if inspeccion_real else {}
    items_revisados = inspeccion_real["items_revisados"] if inspeccion_real else 0
    items_totales = inspeccion_real["items_totales"] if inspeccion_real else len(checklist_items)

    categorias = []
    items_por_categoria: dict[str, list] = {}
    categoria_activa = ""
    for slug, etiqueta in _CATEGORIA_CHECKLIST_LABEL.items():
        items_cat = [it for it in checklist_items if it["categoria"] == slug]
        revisados_cat = [it for it in items_cat if it["codigo"] in resultado_por_codigo]
        if revisados_cat:
            items_por_categoria[slug] = [
                {"codigo": it["codigo"], "nombre": it["nombre"], "resultado": resultado_por_codigo[it["codigo"]]}
                for it in revisados_cat
            ]
        estado_cat = (
            "completa" if items_cat and len(revisados_cat) == len(items_cat)
            else "en_revision" if revisados_cat else "pendiente"
        )
        if estado_cat != "completa" and not categoria_activa:
            categoria_activa = slug
        categorias.append({"slug": slug, "etiqueta": etiqueta, "estado": estado_cat})
    if not categoria_activa and categorias:
        categoria_activa = categorias[-1]["slug"]

    return templates.TemplateResponse(request, "empleado/vigilancia/inspeccion.html", _ctx(request,
        title="Inspección de Bicicleta", flash=flash,
        bici=bici, viaje=viaje, tiene_pago_pendiente=tiene_pago_pendiente, checklist=checklist,
        categorias=categorias, categoria_activa=categoria_activa,
        items_por_categoria=items_por_categoria,
        items_revisados=items_revisados, items_totales=items_totales,
    ))


@router.post("/vigilancia/inspeccion/{bici_id}/registrar")
async def vig_inspeccion_registrar(request: Request, bici_id: str):
    user = getattr(request.state, "user", {})
    form = await request.form()
    bateria       = form.get("bateria", "")
    observaciones = form.get("observaciones", "")
    cargo_danos_raw = form.get("cargo_danos", "")
    # Derivado siempre de la fila real de `viajes` (ver
    # _viaje_para_inspeccion) -- nunca de sesión, para que la infracción y
    # el cargo por daños no dependan de por qué camino llegó Vigilancia
    # a esta pantalla (ver docs/HOJA_DE_RUTA.md).
    viaje: dict | None = None

    checklist_items = inspecciones_repo.listar_checklist_items()
    fallas: list[str] = []
    resultados: dict[str, str] = {}
    for it in checklist_items:
        # El formulario solo captura OK/Con danos (binario); "mal" se
        # guarda como dano_leve -- es la interpretacion mas conservadora
        # que el formulario de hoy puede respaldar (no reclama "grave" ni
        # "faltante", que son mas especificos de lo que esta UI captura).
        # dano_grave/faltante quedan disponibles en el esquema para cuando
        # el formulario capture ese detalle (fuera de alcance hoy).
        resultado = "dano_leve" if form.get(it["codigo"]) == "mal" else "ok"
        resultados[it["codigo"]] = resultado
        if resultado != "ok":
            fallas.append(it["nombre"])
    aprobada = len(fallas) == 0

    try:
        pb = _pb()
        bici = pb.get_record("bicicletas", bici_id)
        bicicleta_codigo = bici.get("codigo") or bici_id
        viaje = _viaje_para_inspeccion(pb, bici_id)

        id_bicicleta_real = inspecciones_repo.resolver_bicicleta_id(bicicleta_codigo)
        id_alquiler_real = inspecciones_repo.resolver_alquiler_id(viaje["id"] if viaje else "")

        pago = None
        if viaje:
            pagos_v = pb.list_records(
                "pagos", filter=f'viaje_id = {filter_literal(viaje["id"])}', per_page=1,
            ).get("items", [])
            pago = pagos_v[0] if pagos_v else None
        tiene_pago_pendiente = bool(pago) and pago.get("estado") != "pagado"

        # ── Nivel 2 (ver docs/HOJA_DE_RUTA.md): registro real de la
        # inspeccion en inspecciones/inspeccion_detalle. Best-effort: si
        # falla, no bloquea el Nivel 3 (lo que de verdad mueve
        # bicicletas/ordenes/infracciones, y si eso falla SI debe
        # avisarle al vigilante -- por eso no comparte el except silencioso).
        try:
            if id_bicicleta_real:
                id_inspector_real = inspecciones_repo.asegurar_inspector(
                    email=user.get("email", ""), nombre_completo=user.get("name", ""),
                )
                inspecciones_repo.crear(
                    id_alquiler=id_alquiler_real, id_bicicleta=id_bicicleta_real,
                    id_inspector=id_inspector_real, resultados=resultados,
                    observacion=observaciones,
                )
        except Exception:
            pass

        # ── Nivel 3 (ver docs/HOJA_DE_RUTA.md seccion 23): el estado real
        # de la bicicleta se mueve en ClickHouse via bicicletas_repo, no
        # solo en PocketBase -- esto es lo que corrige el riesgo real
        # (una bicicleta reprobada podia seguir apareciendo disponible en
        # el catalogo del ciclista, que lee ClickHouse). Si no se puede
        # resolver el id real, se corta aca en vez de fingir exito.
        if not id_bicicleta_real:
            raise RuntimeError(
                f"La bicicleta {bicicleta_codigo} no tiene un id real en ClickHouse -- "
                "no se puede actualizar su estado real."
            )
        bici_ch = bicicletas_repo.obtener(id_bicicleta_real)
        if not bici_ch:
            raise RuntimeError(f"Bicicleta {bicicleta_codigo} (id={id_bicicleta_real}) no encontrada en ClickHouse.")

        def _mover_estado_bicicleta(nuevo_estado: str) -> None:
            bicicletas_repo.actualizar(
                id_bicicleta_real,
                codigo=bici_ch["codigo"], id_modelo=str(bici_ch["id_modelo"]), estado=nuevo_estado,
                id_estacion=str(bici_ch["id_estacion"] or ""), numero_serie=bici_ch["numero_serie"],
                fecha_adquisicion=bici_ch["fecha_adquisicion"], observacion=bici_ch["observacion"],
                es_electrica=bool(bici_ch["es_electrica"]),
            )

        if aprobada:
            _mover_estado_bicicleta("disponible")
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "bicicletas",
                f"Inspección de devolución aprobada: {bicicleta_codigo} disponible"
                + (f" (batería: {bateria}%)" if bateria else "")
                + (f" — {observaciones}" if observaciones else ""), request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            msg = f"Inspección aprobada. {bicicleta_codigo} está disponible nuevamente."
            if tiene_pago_pendiente:
                msg += " Nota: el ciclista tiene un pago pendiente de este viaje."
            return _flash(request, "/empleado/vigilancia/devoluciones", "success", msg)

        # ── Reprobada: orden de mantenimiento real + infracción real (Nivel 3) ──
        descripcion = f"Inspección de devolución reprobada — fallas detectadas: {', '.join(fallas)}."
        if observaciones:
            descripcion += f" Observaciones: {observaciones}"

        tipo_falla = next(
            (_CATEGORIA_A_TIPO_FALLA.get(it["categoria"], "otro")
             for it in checklist_items if resultados.get(it["codigo"]) != "ok"),
            "otro",
        )
        id_tecnico = ordenes_repo.tecnico_con_menos_carga()
        if not id_tecnico:
            raise RuntimeError("No hay ningún técnico real (rol=mantenimiento) para asignar la orden.")
        id_orden_nueva = ordenes_repo.crear(
            id_bicicleta=id_bicicleta_real, origen="inspeccion", tipo_falla=tipo_falla,
            prioridad="media", id_tecnico=id_tecnico, diagnostico=descripcion,
        )
        _mover_estado_bicicleta("mantenimiento")
        orden_nueva = ordenes_repo.obtener(id_orden_nueva)
        codigo_orden = orden_nueva["codigo"] if orden_nueva else "—"

        # Difusion a Mantenimiento (punto 13: "Asignación de la falla al
        # Empleado de Mantenimiento") -- a todo el rol, no al tecnico
        # puntual: id_tecnico es un id de urbanbike_operativa.usuarios
        # (ClickHouse), sin puente directo hoy hacia el id de sesion de
        # PocketBase que necesita notificar_usuario().
        notificaciones_repo.notificar_rol(
            "empleado-mantenimiento", tipo="orden_asignada",
            titulo="Nueva orden de mantenimiento",
            mensaje=f"Se generó la orden {codigo_orden} para {bicicleta_codigo} ({', '.join(fallas)}).",
            enlace="/empleado/mantenimiento/ordenes",
        )

        # Cargo adicional por daños, si el empleado ingresó un monto --
        # decision confirmada con Washington (ver docs/HOJA_DE_RUTA.md
        # seccion 23): se guarda como infracciones.monto_multa (registro
        # de auditoria) Y ahora TAMBIEN se suma al pago real del viaje
        # (antes quedaba desconectado del monto que el ciclista de
        # verdad paga -- ver docs/superpowers/plans, rediseno del flujo).
        cargo_danos = 0.0
        try:
            cargo_danos = float(cargo_danos_raw)
        except (TypeError, ValueError):
            cargo_danos = 0.0

        if cargo_danos > 0 and viaje:
            pagos_viaje = pb.list_records(
                "pagos", filter=f'viaje_id = {filter_literal(viaje["id"])}', per_page=1,
            ).get("items", [])
            if pagos_viaje:
                pago_actual = pagos_viaje[0]
                subtotal = float(pago_actual.get("subtotal") or 0)
                recargo_demora = float(pago_actual.get("recargo_demora") or 0)
                descuento_monto = float(pago_actual.get("descuento_monto") or 0)
                nuevo_monto_total = round(subtotal + recargo_demora + cargo_danos - descuento_monto, 2)
                pb.update_record("pagos", pago_actual["id"], {
                    "cargo_danos": cargo_danos,
                    "monto_total": nuevo_monto_total,
                })

        ciclista_id = (viaje.get("ciclista_id") if viaje else "") or ""
        ciclista_nombre = (viaje.get("ciclista_nombre") if viaje else "") or "—"
        if ciclista_id:
            ciclista_pb = pb.get_record("users", ciclista_id)
            id_usuario_real = infracciones_repo.resolver_o_crear_usuario(
                email=ciclista_pb.get("email", ""),
                nombre_completo=ciclista_pb.get("name") or ciclista_nombre,
                rol="ciclista",
            )
            infracciones_repo.crear(
                id_usuario=id_usuario_real, tipo="dano_bicicleta", descripcion=descripcion,
                id_alquiler=id_alquiler_real, monto_multa=cargo_danos,
            )

            # Bloqueo del ciclista por acumulacion de infracciones pendientes:
            # sigue contra PocketBase (users.activo es lo que de verdad usa el
            # login) -- fuera de alcance de hoy, ver infracciones_repo.py.
            pb.create_record("infracciones", {
                "ciclista_id":       ciclista_id,
                "tipo":              "dano_bicicleta",
                "descripcion":       descripcion,
                "bicicleta_id":      bici_id,
                "bicicleta_codigo":  bicicleta_codigo,
                "resuelta":          False,
                "fecha":             _ahora(),
                "notificada_por":    user.get("name") or user.get("email", ""),
            })
            total_pendientes = pb.list_records(
                "infracciones",
                filter=f'ciclista_id = {filter_literal(ciclista_id)} && resuelta = false',
                per_page=1,
            ).get("totalItems", 0)
            if total_pendientes >= _LIMITE_INFRACCIONES_BLOQUEO:
                pb.update_record("users", ciclista_id, {
                    "activo": False,
                    "motivo_bloqueo": (
                        f"Cuenta bloqueada automáticamente por acumular {total_pendientes} "
                        "infracciones sin resolver. Resuélvelas con el equipo de vigilancia "
                        "para reactivar tu cuenta."
                    ),
                })

            mensaje_ciclista = f"Se detectaron fallas en {bicicleta_codigo} al devolverla: {', '.join(fallas)}."
            if cargo_danos > 0:
                mensaje_ciclista += f" Se generó un cargo por daños de ${cargo_danos:.2f}."
            notificaciones_repo.notificar_usuario(
                pb, ciclista_id, tipo="falla", titulo="Falla detectada en tu devolución",
                mensaje=mensaje_ciclista, enlace="/ciclista/pagos",
            )
            # Notificación propia de la infracción (ver docs/HOJA_DE_RUTA.md
            # sección 69) -- antes iba mezclada dentro del mensaje de "falla"
            # de arriba, ahora es su propio tipo, independiente del cargo por
            # daño (ese sigue siendo parte del aviso de "falla", no de este).
            notificaciones_repo.notificar_usuario(
                pb, ciclista_id, tipo="infraccion", titulo="Se registró una infracción en tu cuenta",
                mensaje=f"Infracción por daño en {bicicleta_codigo}: {descripcion}",
                enlace="/ciclista/infracciones",
            )

        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "ordenes_mantenimiento",
            f"Inspección de devolución reprobada: orden generada para {bicicleta_codigo} ({', '.join(fallas)})"
            + (f"; infracción registrada a {ciclista_nombre}" if ciclista_id else "")
            + (f"; cargo por daños de ${cargo_danos:.2f}" if cargo_danos > 0 else ""), request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        msg = f"Inspección reprobada. Se generó una orden de mantenimiento para {bicicleta_codigo}"
        msg += " y se registró una infracción al ciclista." if ciclista_id else "."
        if cargo_danos > 0:
            msg += f" Se generó un cargo por daños de ${cargo_danos:.2f}."
        return _flash(request, "/empleado/vigilancia/devoluciones", "info", msg)
    except Exception as e:
        return _flash(request, f"/empleado/vigilancia/inspeccion/{bici_id}", "error", str(e))


@router.get("/vigilancia/infracciones", response_class=HTMLResponse)
async def vig_infracciones(request: Request):
    flash = request.session.pop("flash", None)
    infracciones: list[dict] = []
    try:
        infracciones = _pb().list_records("infracciones", sort="-fecha", per_page=500).get("items", [])
    except Exception:
        pass
    total = len(infracciones)
    pendientes = sum(1 for i in infracciones if not i.get("resuelta"))
    resueltas = total - pendientes
    return templates.TemplateResponse(request, "empleado/vigilancia/infracciones.html", _ctx(request,
        title="Infracciones", flash=flash, infracciones=infracciones,
        total=total, pendientes=pendientes, resueltas=resueltas,
    ))


@router.post("/vigilancia/infracciones/{iid}/resolver")
async def vig_infracciones_resolver(
    request: Request, iid: str,
    resolucion: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        infra = pb.get_record("infracciones", iid)
        pb.update_record("infracciones", iid, {
            "resuelta":         True,
            "resolucion":       resolucion.strip(),
            "fecha_resolucion": _ahora(),
            "resuelta_por":     user.get("name") or user.get("email", ""),
        })
        ciclista_id = infra.get("ciclista_id", "")
        if ciclista_id:
            pendientes = pb.list_records(
                "infracciones",
                filter=f'ciclista_id = {filter_literal(ciclista_id)} && resuelta = false',
                per_page=1,
            ).get("totalItems", 0)
            if pendientes == 0:
                pb.update_record("users", ciclista_id, {"activo": True, "motivo_bloqueo": ""})
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "infracciones",
            f"Infracción resuelta (id: {iid})" + (f": {resolucion.strip()}" if resolucion.strip() else ""), request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/vigilancia/infracciones", "success", "Infracción marcada como resuelta.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/infracciones", "error", str(e))


def _vig_infracciones_data() -> list[dict]:
    return _pb().list_records("infracciones", sort="-fecha", per_page=500).get("items", [])


def _vig_infracciones_columnas_filas(infracciones: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Tipo", ancho=18),
        ColumnaReporte("Descripción", ancho=34),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Fecha", ancho=18),
        ColumnaReporte("Estado", ancho=14),
    ]
    filas = [
        [
            i.get("ciclista_id") or "—",
            i.get("tipo") or "—",
            i.get("descripcion") or "—",
            i.get("bicicleta_codigo") or "—",
            (i.get("fecha") or "—").replace("T", " ").replace("Z", "") if i.get("fecha") else "—",
            "Resuelta" if i.get("resuelta") else "Pendiente",
        ]
        for i in infracciones
    ]
    return columnas, filas


@router.get("/vigilancia/infracciones/excel")
def vig_infracciones_excel():
    infracciones = _vig_infracciones_data()
    columnas, filas = _vig_infracciones_columnas_filas(infracciones)
    pendientes = sum(1 for i in infracciones if not i.get("resuelta"))
    return generar_excel_reporte(
        titulo="UrbanBike — Registro de Infracciones",
        subtitulo=f"Total: {len(infracciones)} infracciones  |  Pendientes: {pendientes}  |  Resueltas: {len(infracciones) - pendientes}",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(infracciones)} infracciones", None, None, None, None, None],
        nombre_hoja="Infracciones",
        nombre_archivo="urbanbike_vigilancia_infracciones.xlsx",
    )


@router.get("/vigilancia/infracciones/pdf")
def vig_infracciones_pdf():
    infracciones = _vig_infracciones_data()
    columnas, filas = _vig_infracciones_columnas_filas(infracciones)
    pendientes = sum(1 for i in infracciones if not i.get("resuelta"))
    return generar_pdf_reporte(
        titulo="Registro de Infracciones",
        subtitulo=f"Total: {len(infracciones)} infracciones  |  Pendientes: {pendientes}  |  Resueltas: {len(infracciones) - pendientes}",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(infracciones)} infracciones", None, None, None, None, None],
        nombre_archivo="urbanbike_vigilancia_infracciones.pdf",
    )


@router.get("/vigilancia/mantenimiento/cerrar", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:leer"))])
async def vig_mantenimiento_cerrar(request: Request):
    flash = request.session.pop("flash", None)
    ordenes: list[dict] = []
    try:
        ordenes = _pb().list_records(
            "ordenes_mant", filter='estado = "en_proceso"',
            sort="-fecha_apertura", per_page=200,
        ).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/vigilancia/cerrar_mantenimiento.html", _ctx(request,
        title="Certificar Mantenimiento", flash=flash, ordenes=ordenes,
    ))


@router.post("/vigilancia/mantenimiento/{oid}/certificar", dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:actualizar"))])
async def vig_mantenimiento_certificar(
    request: Request, oid: str,
    observaciones_cierre: str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        orden = pb.get_record("ordenes_mant", oid)
        pb.update_record("ordenes_mant", oid, {
            "estado":               "completado",
            "fecha_cierre":         _ahora(),
            "observaciones_cierre": observaciones_cierre.strip(),
            "certificada_por":      user.get("name") or user.get("email", ""),
        })
        bici_id = orden.get("bicicleta_id", "")
        if bici_id:
            pb.update_record("bicicletas", bici_id, {"estado": "disponible"})
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "ordenes_mant",
            f"Mantenimiento certificado: orden de {orden.get('bicicleta_codigo', oid)}"
            + (f" — {observaciones_cierre.strip()}" if observaciones_cierre.strip() else ""), request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/vigilancia/mantenimiento/cerrar", "success",
                      "Mantenimiento certificado. Bicicleta disponible nuevamente.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/mantenimiento/cerrar", "error", str(e))


def _vig_cerrar_mantenimiento_ordenes() -> list[dict]:
    return _pb().list_records(
        "ordenes_mant", filter='estado = "en_proceso"',
        sort="-fecha_apertura", per_page=200,
    ).get("items", [])


def _vig_cerrar_mantenimiento_columnas_filas(ordenes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Descripción", ancho=36),
        ColumnaReporte("Técnico", ancho=22),
        ColumnaReporte("Apertura", ancho=18),
    ]
    filas = [
        [
            o.get("bicicleta_codigo") or "—",
            o.get("descripcion") or "—",
            o.get("tecnico_nombre") or "—",
            (o.get("fecha_apertura") or "—").replace("T", " ").replace("Z", ""),
        ]
        for o in ordenes
    ]
    return columnas, filas


@router.get("/vigilancia/mantenimiento/cerrar/excel")
def vig_mantenimiento_cerrar_excel():
    ordenes = _vig_cerrar_mantenimiento_ordenes()
    columnas, filas = _vig_cerrar_mantenimiento_columnas_filas(ordenes)
    return generar_excel_reporte(
        titulo="UrbanBike — Órdenes de Mantenimiento en Proceso",
        subtitulo=f"Total: {len(ordenes)} órdenes en proceso, pendientes de certificar",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(ordenes)} órdenes", None, None, None],
        nombre_hoja="Órdenes en Proceso",
        nombre_archivo="urbanbike_vigilancia_ordenes_en_proceso.xlsx",
    )


@router.get("/vigilancia/mantenimiento/cerrar/pdf")
def vig_mantenimiento_cerrar_pdf():
    ordenes = _vig_cerrar_mantenimiento_ordenes()
    columnas, filas = _vig_cerrar_mantenimiento_columnas_filas(ordenes)
    return generar_pdf_reporte(
        titulo="Órdenes de Mantenimiento en Proceso",
        subtitulo=f"Total: {len(ordenes)} órdenes en proceso, pendientes de certificar",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(ordenes)} órdenes", None, None, None],
        nombre_archivo="urbanbike_vigilancia_ordenes_en_proceso.pdf",
    )


_LIMITE_ALERTA_MIN = 120


def _vig_alertas_data() -> list[dict]:
    """Viajes activos que superan _LIMITE_ALERTA_MIN, con el tiempo
    excedido ya calculado -- compartida entre la pantalla y el export
    para no duplicar la logica (ver docs/HOJA_DE_RUTA.md)."""
    alertas: list[dict] = []
    pb = _pb()
    viajes_activos = pb.list_records("viajes", filter='estado = "activo"', sort="-fecha_inicio", per_page=200).get("items", [])
    ahora = datetime.now(timezone.utc)
    for v in viajes_activos:
        try:
            inicio = datetime.fromisoformat(v.get("fecha_inicio", "").replace("Z", "+00:00"))
            mins = int((ahora - inicio).total_seconds() / 60)
        except Exception:
            continue
        if mins <= _LIMITE_ALERTA_MIN:
            continue
        email = ""
        ciclista_id = v.get("ciclista_id", "")
        if ciclista_id:
            try:
                email = pb.get_record("users", ciclista_id).get("email", "")
            except Exception:
                pass
        alertas.append({
            "viaje_id":      v["id"],
            "ciclista":      v.get("ciclista_nombre") or "—",
            "email":         email or "—",
            "bicicleta":     v.get("bicicleta_codigo") or "—",
            "tiempo_total":  mins,
            "tiempo_exceso": mins - _LIMITE_ALERTA_MIN,
            "atendida":      bool(v.get("alerta_atendida")),
        })
    return alertas


@router.get("/vigilancia/alertas", response_class=HTMLResponse)
async def vig_alertas(request: Request):
    flash = request.session.pop("flash", None)
    alertas: list[dict] = []
    try:
        alertas = _vig_alertas_data()
    except Exception:
        pass

    return templates.TemplateResponse(request, "empleado/vigilancia/alertas.html", _ctx(request,
        title="Alertas de Viajes", flash=flash, alertas=alertas, limite_min=_LIMITE_ALERTA_MIN,
    ))


@router.post("/vigilancia/alertas/{viaje_id}/atender")
async def vig_alertas_atender(request: Request, viaje_id: str):
    try:
        _pb().update_record("viajes", viaje_id, {"alerta_atendida": True})
        return _flash(request, "/empleado/vigilancia/alertas", "success", "Alerta marcada como atendida.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/alertas", "error", str(e))


def _vig_alertas_columnas_filas(alertas: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Contacto", ancho=28),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Tiempo total (min)", ancho=18, formato="entero"),
        ColumnaReporte("Tiempo excedido (min)", ancho=20, formato="entero"),
        ColumnaReporte("Acciones tomadas", ancho=18),
    ]
    filas = [
        [a["ciclista"], a["email"], a["bicicleta"], a["tiempo_total"], a["tiempo_exceso"],
         "Atendida" if a["atendida"] else "Pendiente"]
        for a in alertas
    ]
    return columnas, filas


@router.get("/vigilancia/alertas/excel")
def vig_alertas_excel():
    alertas = _vig_alertas_data()
    columnas, filas = _vig_alertas_columnas_filas(alertas)
    pendientes = sum(1 for a in alertas if not a["atendida"])
    return generar_excel_reporte(
        titulo="UrbanBike — Alertas de Viajes",
        subtitulo=f"Viajes que superaron {_LIMITE_ALERTA_MIN} min: {len(alertas)}  |  Pendientes: {pendientes}",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(alertas)} alertas", None, None, None, None, None],
        nombre_hoja="Alertas",
        nombre_archivo="urbanbike_vigilancia_alertas.xlsx",
    )


@router.get("/vigilancia/alertas/pdf")
def vig_alertas_pdf():
    alertas = _vig_alertas_data()
    columnas, filas = _vig_alertas_columnas_filas(alertas)
    pendientes = sum(1 for a in alertas if not a["atendida"])
    return generar_pdf_reporte(
        titulo="Alertas de Viajes",
        subtitulo=f"Viajes que superaron {_LIMITE_ALERTA_MIN} min: {len(alertas)}  |  Pendientes: {pendientes}",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(alertas)} alertas", None, None, None, None, None],
        nombre_archivo="urbanbike_vigilancia_alertas.pdf",
    )


# ══════════════════════════════════════════════════════════════════════════════
# REPORTES
# ══════════════════════════════════════════════════════════════════════════════

_DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


ESTADOS_ALQUILER_REPORTE = ["reservado", "en_curso", "devuelto", "facturado", "cancelado"]
ESTADO_ALQUILER_LABEL = {
    "reservado": "Reservado", "en_curso": "En curso", "devuelto": "Devuelto",
    "facturado": "Facturado", "cancelado": "Cancelado",
}
POR_PAGINA_REPORTE = 20


def _parse_fecha_reporte(valor: str) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _reportes_op_columnas() -> list[ColumnaReporte]:
    return [
        ColumnaReporte("Código", ancho=14),
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Estación inicio", ancho=22),
        ColumnaReporte("Estación fin", ancho=22),
        ColumnaReporte("Fecha inicio", ancho=18),
        ColumnaReporte("Fecha fin", ancho=18),
        ColumnaReporte("Modalidad", ancho=13),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Total", ancho=12, formato="moneda"),
    ]


def _reportes_op_fila(a: dict) -> list:
    return [
        a["codigo"],
        a["ciclista_nombre"],
        a["bicicleta_codigo"],
        a["estacion_inicio_nombre"],
        a["estacion_fin_nombre"] or "—",
        a["fecha_inicio"].strftime("%Y-%m-%d %H:%M") if a.get("fecha_inicio") else "—",
        a["fecha_fin"].strftime("%Y-%m-%d %H:%M") if a.get("fecha_fin") else "—",
        (a.get("modalidad") or "—").capitalize(),
        ESTADO_ALQUILER_LABEL.get(a["estado"], a["estado"]),
        float(a.get("total") or 0),
    ]


def _reportes_op_subtitulo(estado: str, fecha_desde: str, fecha_hasta: str) -> str:
    return (
        f"Estado: {ESTADO_ALQUILER_LABEL.get(estado, 'Todos')}  |  "
        f"Período: {fecha_desde or '—'} → {fecha_hasta or '—'}"
    )


ESTADO_BICI_LABEL = {
    "disponible": "Disponible", "en_uso": "En uso",
    "mantenimiento": "Mantenimiento", "retirada": "Retirada",
}


def _bicicletas_por_categoria_estado() -> list[dict]:
    """Informe compuesto: COUNT(*) GROUP BY categoria, estado sobre el
    catálogo real de bicicletas (urbanbike_operativa)."""
    return ch.query("""
        SELECT c.nombre AS categoria, b.estado AS estado, count() AS total
        FROM urbanbike_operativa.bicicletas b FINAL
        INNER JOIN urbanbike_operativa.modelos_bicicleta m FINAL ON m.id = b.id_modelo
        INNER JOIN urbanbike_operativa.categorias c FINAL ON c.id = m.id_categoria
        GROUP BY c.nombre, b.estado ORDER BY c.nombre, b.estado
    """)


def _bicicletas_categoria_estado_columnas_filas(filas_raw: list[dict]) -> tuple[list[ColumnaReporte], list[list], list]:
    columnas = [
        ColumnaReporte("Categoría", ancho=22),
        ColumnaReporte("Estado", ancho=22),
        ColumnaReporte("Bicicletas", ancho=14, formato="entero"),
    ]
    filas = [
        [r["categoria"] or "N/A", ESTADO_BICI_LABEL.get(r["estado"], r["estado"]), int(r["total"])]
        for r in filas_raw
    ]
    fila_total = [f"Total: {sum(f[2] for f in filas)} bicicletas", None, None]
    return columnas, filas, fila_total


@router.get("/operacion/reportes", response_class=HTMLResponse)
async def op_reportes(
    request: Request,
    estado: str = Query(""),
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
    page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    alquileres, total = alquileres_repo.listar(
        estado=estado,
        fecha_desde=_parse_fecha_reporte(fecha_desde),
        fecha_hasta=_parse_fecha_reporte(fecha_hasta),
        incluir_prueba=False,
        page=page, per_page=POR_PAGINA_REPORTE,
    )
    total_paginas = max(1, math.ceil(total / POR_PAGINA_REPORTE))
    total_monto = sum(float(a.get("total") or 0) for a in alquileres)

    bicis_categoria_estado = _bicicletas_por_categoria_estado()
    total_bicicletas = sum(int(r["total"]) for r in bicis_categoria_estado)

    return templates.TemplateResponse(request, "empleado/operacion/reportes.html", _ctx(request,
        title="Reportes — Operación", flash=flash,
        titulo="Reporte de Alquileres", subtitulo="Operación — datos reales de urbanbike_operativa",
        alquileres=alquileres, total=total, total_monto=total_monto,
        page=page, total_paginas=total_paginas,
        estado=estado, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        estados=ESTADOS_ALQUILER_REPORTE, estado_label=ESTADO_ALQUILER_LABEL,
        bicis_categoria_estado=bicis_categoria_estado, total_bicicletas=total_bicicletas,
    ))


@router.get("/operacion/reportes/excel")
def op_reportes_excel(
    estado: str = Query(""), fecha_desde: str = Query(""), fecha_hasta: str = Query(""),
):
    alquileres, total = alquileres_repo.listar(
        estado=estado,
        fecha_desde=_parse_fecha_reporte(fecha_desde),
        fecha_hasta=_parse_fecha_reporte(fecha_hasta),
        incluir_prueba=False,
        page=1, per_page=100_000,
    )
    filas = [_reportes_op_fila(a) for a in alquileres]
    fila_total = [f"Total: {total} alquileres"] + [None] * 8 + [sum(f[9] for f in filas)]

    return generar_excel_reporte(
        titulo="UrbanBike — Reporte de Alquileres (Operación)",
        subtitulo=_reportes_op_subtitulo(estado, fecha_desde, fecha_hasta),
        columnas=_reportes_op_columnas(),
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Alquileres",
        nombre_archivo=f"urbanbike_operacion_alquileres_{fecha_desde or 'todos'}_{fecha_hasta or 'todos'}.xlsx",
    )


@router.get("/operacion/reportes/pdf")
def op_reportes_pdf(
    estado: str = Query(""), fecha_desde: str = Query(""), fecha_hasta: str = Query(""),
):
    alquileres, total = alquileres_repo.listar(
        estado=estado,
        fecha_desde=_parse_fecha_reporte(fecha_desde),
        fecha_hasta=_parse_fecha_reporte(fecha_hasta),
        incluir_prueba=False,
        page=1, per_page=100_000,
    )
    filas = [_reportes_op_fila(a) for a in alquileres]
    fila_total = [f"Total: {total} alquileres"] + [None] * 8 + [sum(f[9] for f in filas)]

    return generar_pdf_reporte(
        titulo="Reporte de Alquileres — Operación",
        subtitulo=_reportes_op_subtitulo(estado, fecha_desde, fecha_hasta),
        columnas=_reportes_op_columnas(),
        filas=filas,
        fila_total=fila_total,
        nombre_archivo=f"urbanbike_operacion_alquileres_{fecha_desde or 'todos'}_{fecha_hasta or 'todos'}.pdf",
    )


@router.get("/operacion/reportes/bicicletas/excel")
def op_reportes_bicicletas_excel():
    filas_raw = _bicicletas_por_categoria_estado()
    columnas, filas, fila_total = _bicicletas_categoria_estado_columnas_filas(filas_raw)
    return generar_excel_reporte(
        titulo="UrbanBike — Bicicletas por Categoría y Estado",
        subtitulo="Operación — catálogo real de urbanbike_operativa",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Bicicletas",
        nombre_archivo="urbanbike_operacion_bicicletas_categoria_estado.xlsx",
    )


@router.get("/operacion/reportes/bicicletas/pdf")
def op_reportes_bicicletas_pdf():
    filas_raw = _bicicletas_por_categoria_estado()
    columnas, filas, fila_total = _bicicletas_categoria_estado_columnas_filas(filas_raw)
    return generar_pdf_reporte(
        titulo="Bicicletas por Categoría y Estado",
        subtitulo="Operación — catálogo real de urbanbike_operativa",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo="urbanbike_operacion_bicicletas_categoria_estado.pdf",
    )


@router.get("/mantenimiento/reportes", response_class=HTMLResponse)
async def mnt_reportes(request: Request):
    flash = request.session.pop("flash", None)
    ordenes: list[dict] = []
    try:
        ordenes = _pb().list_records("ordenes_mant", per_page=500).get("items", [])
    except Exception:
        pass

    estado_counts = {"pendiente": 0, "en_proceso": 0, "completado": 0, "cancelado": 0}
    tipo_counts = {"preventivo": 0, "correctivo": 0}
    for o in ordenes:
        estado = o.get("estado", "pendiente")
        estado_counts[estado] = estado_counts.get(estado, 0) + 1
        tipo = o.get("tipo", "correctivo")
        tipo_counts[tipo] = tipo_counts.get(tipo, 0) + 1

    estado_labels = ["Pendiente", "En proceso", "Completado", "Cancelado"]
    estado_values = [estado_counts["pendiente"], estado_counts["en_proceso"],
                     estado_counts["completado"], estado_counts["cancelado"]]
    tipo_labels = ["Preventivo", "Correctivo"]
    tipo_values = [tipo_counts["preventivo"], tipo_counts["correctivo"]]

    return templates.TemplateResponse(request, "empleado/mantenimiento/reportes.html", _ctx(request,
        title="Reportes — Mantenimiento", flash=flash,
        total_ordenes=len(ordenes),
        estado_labels=json.dumps(estado_labels), estado_values=json.dumps(estado_values),
        tipo_labels=json.dumps(tipo_labels), tipo_values=json.dumps(tipo_values),
    ))


@router.get("/vigilancia/reportes", response_class=HTMLResponse)
async def vig_reportes(request: Request):
    flash = request.session.pop("flash", None)
    viajes: list[dict] = []
    try:
        viajes = _pb().list_records(
            "viajes", filter='estado = "completado"', sort="-fecha_fin", per_page=500,
        ).get("items", [])
    except Exception:
        pass

    LIMITE_MIN = 60
    a_tiempo = 0
    tardias = 0
    for v in viajes:
        dur = v.get("duracion_minutos") or 0
        if dur and dur > LIMITE_MIN:
            tardias += 1
        else:
            a_tiempo += 1

    return templates.TemplateResponse(request, "empleado/vigilancia/reportes.html", _ctx(request,
        title="Reportes — Vigilancia", flash=flash,
        total_devoluciones=len(viajes), limite_min=LIMITE_MIN,
        a_tiempo=a_tiempo, tardias=tardias,
        dev_labels=json.dumps(["A tiempo", "Tardías"]),
        dev_values=json.dumps([a_tiempo, tardias]),
    ))


# ── Soporte (chat interno, punto 12 Opción B -- ver docs/HOJA_DE_RUTA.md
#    sección 68). El documento de requerimientos dice explícitamente que
#    Vigilancia da soporte a los ciclistas -- Admin también puede entrar
#    (ruta espejo en admin.py, mismo repo) por el mismo criterio que
#    estaciones/tarifas/promociones. ────────────────────────────────────────

@router.get("/vigilancia/soporte", response_class=HTMLResponse)
async def vig_soporte_lista(request: Request):
    flash = request.session.pop("flash", None)
    conversaciones = mensajes_soporte_repo.listar_conversaciones()
    return templates.TemplateResponse(request, "empleado/vigilancia/soporte.html", _ctx(request,
        title="Soporte", flash=flash, conversaciones=conversaciones,
        base_url="/empleado/vigilancia/soporte",
    ))


@router.get("/vigilancia/soporte/{ciclista_id}", response_class=HTMLResponse)
async def vig_soporte_detalle(request: Request, ciclista_id: str):
    flash = request.session.pop("flash", None)
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    if not mensajes:
        return _flash(request, "/empleado/vigilancia/soporte", "error", "Esa conversación no existe.")
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="empleado-vigilancia")
    ciclista_nombre = next((m["autor_nombre"] for m in mensajes if m.get("autor_rol") == "ciclista"), ciclista_id)
    return templates.TemplateResponse(request, "empleado/vigilancia/soporte_detalle.html", _ctx(request,
        title=f"Soporte — {ciclista_nombre}", flash=flash, mensajes=mensajes,
        ciclista_id=ciclista_id, ciclista_nombre=ciclista_nombre, soy_ciclista=False,
        poll_url=f"/empleado/vigilancia/soporte/{ciclista_id}/mensajes",
        enviar_url=f"/empleado/vigilancia/soporte/{ciclista_id}/enviar",
        base_url="/empleado/vigilancia/soporte",
    ))


@router.post("/vigilancia/soporte/{ciclista_id}/enviar")
async def vig_soporte_enviar(request: Request, ciclista_id: str, texto: str = Form(...)):
    user = getattr(request.state, "user", {})
    try:
        mensajes_soporte_repo.enviar(
            ciclista_id=ciclista_id, autor_id=user.get("id", ""),
            autor_rol=user.get("rol_slug", ""), autor_nombre=user.get("name") or user.get("email", ""),
            texto=texto,
        )
    except ValueError as e:
        return _flash(request, f"/empleado/vigilancia/soporte/{ciclista_id}", "error", str(e))
    except Exception:
        return _flash(request, f"/empleado/vigilancia/soporte/{ciclista_id}", "error", "No se pudo enviar la respuesta. Intenta de nuevo.")
    return RedirectResponse(f"/empleado/vigilancia/soporte/{ciclista_id}", status_code=302)


@router.get("/vigilancia/soporte/{ciclista_id}/mensajes")
async def vig_soporte_mensajes(request: Request, ciclista_id: str):
    """JSON liviano para el sondeo de 4s de la conversación abierta
    (app/static/js/chat-soporte.js)."""
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="empleado-vigilancia")
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
