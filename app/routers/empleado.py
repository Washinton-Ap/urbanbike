"""Rutas para roles de empleado: operación, mantenimiento, vigilancia."""

import json
import math
from datetime import date, datetime, timedelta, timezone

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
from app.templating import file_url, pb_public_base, templates

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
    try:
        id_categoria = tarifas_repo.categoria_de_bicicleta(bicicleta_codigo)
        if not id_categoria:
            return 0.0
        resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, "hora")
        return resultado[0] if resultado else 0.0
    except Exception:
        return 0.0


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

    # Punto 1.8: mismos filtros reales que ya usa op_pagos() (empleado.py) --
    # solo un conteo (per_page=1, totalItems), sin traer los registros completos.
    cobros_pendientes = 0
    try:
        pb = _pb()
        transferencias = pb.list_records("pagos", filter='estado = "verificacion_pendiente"', per_page=1).get("totalItems", 0)
        efectivo = pb.list_records("pagos", filter='estado = "pendiente_efectivo"', per_page=1).get("totalItems", 0)
        cobros_pendientes = transferencias + efectivo
    except Exception:
        pass

    pendientes = [{
        "titulo": "Cobros pendientes de verificar", "conteo": cobros_pendientes,
        "enlace": "/empleado/operacion/pagos", "color": "yellow", "icono": "dinero",
    }]

    chart_labels = json.dumps(["Disponible", "En Uso", "Mantenimiento", "Retirada"])
    chart_values = json.dumps([stats["disponible"], stats["en_uso"], stats["mantenimiento"], stats["retirada"]])
    chart_colors = json.dumps(["#10B981", "#1E86BD", "#F59E0B", "#6B7280"])

    return templates.TemplateResponse(request, "empleado/operacion/dashboard.html", _ctx(request,
        title="Dashboard — Operación", flash=flash, stats=stats, pendientes=pendientes,
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
    fotos = bicicletas_repo.fotos_por_codigo([b["codigo"] for b in filas], request=request)
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
    estacion_inicio_id: str = Form(""),
    ciclista_nombre:    str = Form(""),
):
    user = getattr(request.state, "user", {})
    # Punto 1.10 del Plan V3: estacion_inicio_id ya no lo elige el
    # empleado a mano -- lo autocompleta el JS con la estacion real de la
    # bicicleta elegida. Si llega vacío (bicicleta sin estación real
    # asignada en ClickHouse, o JS deshabilitado), se corta acá en vez de
    # crear un alquiler con una estación inventada o vacía.
    if not estacion_inicio_id:
        return _flash(request, "/empleado/operacion/alquileres/nuevo", "error",
                      "No se pudo determinar la estación real de la bicicleta elegida.")
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
        pb_url=pb_public_base(request),
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
    confirmación, así que no hace falta releerlo.

    También es el punto único real que CIERRA lo que quedó pendiente por
    este pago (aviso de "pago pendiente" del ciclista y "cobro pendiente"
    de Operación, ver notificaciones_repo.TIPOS_PROTEGIDOS) -- ya no basta
    con un clic en la campana, solo esto (la aprobación real) las resuelve."""
    notificaciones_repo.notificar_usuario(
        pb, registro.get("ciclista_id", ""), tipo="pago_aprobado",
        titulo="Pago aprobado",
        mensaje=f"Tu pago de ${float(registro.get('monto_total') or 0):.2f} fue aprobado.",
        enlace="/ciclista/pagos",
    )
    notificaciones_repo.resolver_pago(registro.get("id", ""), registro.get("ciclista_id", ""))


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
            # Punto 1.9 del Plan V3: el monto a pagar (registro.monto_total)
            # es fijo -- lo unico que se ingresa es lo recibido, y el
            # sistema rechaza si no alcanza (defensa real, no solo la
            # calculadora de vuelto del lado del cliente).
            monto_total_real = float(registro.get("monto_total") or 0)
            if monto < monto_total_real:
                return _flash(request, volver, "error",
                              f"El monto recibido (${monto:.2f}) es menor al total a cobrar (${monto_total_real:.2f}).")
            vuelto = round(monto - monto_total_real, 2)
            pb.update_record("pagos", pago_id, {
                "estado":                       "pagado",
                "metodo_pago":                  "efectivo",
                "fecha_pago":                   _ahora(),
                "fecha_confirmacion":           _ahora(),
                "comprobante_numero":           comprobante,
                "confirmado_por_empleado_id":   user.get("id", ""),
                "confirmado_por_empleado_nombre": user.get("name") or user.get("email", ""),
                "observaciones_pago":           f"Monto recibido: ${monto:.2f} -- vuelto: ${vuelto:.2f}",
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
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Transferencia presencial pendiente de verificar",
                mensaje=f"Se subió un comprobante de transferencia presencial (código {comprobante}) que espera verificación.",
                enlace="/empleado/operacion/pagos",
                referencia_id=pago_id,
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
        notificaciones_repo.notificar_usuario(
            pb, registro.get("ciclista_id", ""), tipo="pago_rechazado",
            titulo="Transferencia rechazada",
            mensaje=f"Tu comprobante de transferencia fue rechazado. Motivo: {motivo.strip()}. "
                    "Puedes intentar de nuevo desde Historial de Pagos.",
            enlace="/ciclista/pagos",
        )
        # Cierra el aviso de "cobro pendiente" de Operación -- la
        # verificación ya terminó (con rechazo), aunque el ciclista siga
        # debiendo el pago: su propio "pago pendiente" NO se cierra aquí,
        # sigue pendiente hasta que pague de verdad.
        notificaciones_repo.resolver_pendiente(
            tipo="cobro_pendiente", referencia_id=pago_id, rol_destino="empleado-operacion",
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
        # Punto 1.9 del Plan V3: el monto a cobrar (registro.monto_total)
        # es fijo -- se rechaza un monto recibido insuficiente en vez de
        # confiar en la calculadora de vuelto del lado del cliente.
        monto_total_real = float(registro.get("monto_total") or 0)
        if monto < monto_total_real:
            return _flash(request, "/empleado/operacion/pagos", "error",
                          f"El monto recibido (${monto:.2f}) es menor al total a cobrar (${monto_total_real:.2f}).")
        vuelto = round(monto - monto_total_real, 2)
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
            "observaciones_pago":           f"Monto recibido: ${monto:.2f} -- vuelto: ${vuelto:.2f}",
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

    # Punto 1.8: "ordenes por actualizar" = ordenes que Mantenimiento
    # todavia no empezo a trabajar (estado_reparacion='abierta' en
    # ordenes_repo/ClickHouse, la fuente real -- ver Parte 1 en
    # docs/HOJA_DE_RUTA.md seccion 83; el filtro viejo leia la coleccion
    # huerfana ordenes_mant de PocketBase, siempre desactualizada).
    ordenes_abiertas = 0
    ordenes_vencidas = 0
    try:
        _, ordenes_abiertas = ordenes_repo.listar(estado="abierta", page=1, per_page=1)
        ordenes_vencidas = len(ordenes_repo.listar_vencidas())
    except Exception:
        pass

    pendientes = [
        {"titulo": "Mantenimientos activos", "conteo": len(en_mnt),
         "enlace": "/empleado/mantenimiento/bicicletas", "color": "yellow", "icono": "llave"},
        {"titulo": "Órdenes por actualizar", "conteo": ordenes_abiertas,
         "enlace": "/empleado/mantenimiento/ordenes?estado=abierta", "color": "red", "icono": "reloj"},
        {"titulo": "Órdenes vencidas", "conteo": ordenes_vencidas,
         "enlace": "/empleado/mantenimiento/ordenes?vencida=1", "color": "red", "icono": "reloj"},
    ]

    return templates.TemplateResponse(request, "empleado/mantenimiento/dashboard.html", _ctx(request,
        title="Dashboard — Mantenimiento", flash=flash,
        en_mnt=en_mnt, total_mnt=len(en_mnt), pendientes=pendientes,
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


def _marcar_vencidas(ordenes: list[dict]) -> None:
    """Adjunta o['vencida'] = True/False en cada orden -- calculado en
    Python, no en Jinja (mismo criterio que o['foto_url'] mas abajo).
    Una orden 'cerrada' nunca es vencida, sin importar su fecha_limite."""
    ahora = datetime.now()
    for o in ordenes:
        o["vencida"] = bool(
            o["estado_reparacion"] != "cerrada"
            and o.get("fecha_limite")
            and o["fecha_limite"] < ahora
        )


@router.get("/mantenimiento/ordenes", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:leer"))])
async def mnt_ordenes(
    request: Request,
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""),
    prioridad: str = Query(""), vencida: str = Query(""), page: int = Query(1),
):
    # vencida llega como "1"/"" desde el link/checkbox del template (nunca bool
    # nativo -- un query param bool de FastAPI rechaza con 422 el "vencida="
    # vacio que emite el template cuando el filtro no esta marcado, mismo
    # motivo por el que _int_o_none existe en gerente.py para otro filtro).
    vencida = vencida == "1"
    flash = request.session.pop("flash", None)
    per_page = 10
    filas, total = ordenes_repo.listar(
        q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, vencida=vencida,
        page=page, per_page=per_page,
    )
    fotos_bici = bicicletas_repo.fotos_por_codigo([o["bicicleta_codigo"] for o in filas], request=request)
    for o in filas:
        o["foto_url"] = fotos_bici.get(o["bicicleta_codigo"], "")
    _marcar_vencidas(filas)
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes.html", _ctx(request,
        title="Órdenes de Mantenimiento", flash=flash, ordenes=filas, total=total,
        page=max(1, page), per_page=per_page,
        total_paginas=max(1, -(-total // per_page)),
        q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, vencida=vencida,
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
        ColumnaReporte("Fecha límite", ancho=14),
        ColumnaReporte("Cierre", ancho=18),
        ColumnaReporte("Costo repuestos", ancho=14, formato="moneda"),
        ColumnaReporte("Costo mano de obra", ancho=16, formato="moneda"),
        ColumnaReporte("Estado", ancho=16),
    ]
    ahora = datetime.now()
    filas = [
        [
            o["codigo"], o["bicicleta_codigo"],
            ORIGEN_ORDEN_LABEL.get(o["origen"], o["origen"]),
            TIPO_FALLA_LABEL.get(o["tipo_falla"], o["tipo_falla"]),
            PRIORIDAD_LABEL.get(o["prioridad"], o["prioridad"]),
            o["tecnico_nombre"],
            o["fecha_apertura"].strftime("%Y-%m-%d %H:%M") if o.get("fecha_apertura") else "—",
            (o["fecha_limite"].strftime("%Y-%m-%d") + (" (vencida)" if o["estado_reparacion"] != "cerrada" and o.get("fecha_limite") and o["fecha_limite"] < ahora else "")) if o.get("fecha_limite") else "—",
            o["fecha_cierre"].strftime("%Y-%m-%d %H:%M") if o["estado_reparacion"] == "cerrada" else "—",
            float(o.get("costo_repuestos") or 0),
            float(o.get("costo_mano_obra") or 0),
            ESTADO_ORDEN_LABEL.get(o["estado_reparacion"], o["estado_reparacion"]),
        ]
        for o in ordenes
    ]
    return columnas, filas


def _ordenes_subtitulo(q: str, estado: str, tecnico: str, prioridad: str, total: int, vencida: bool = False) -> str:
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
    if vencida:
        partes.append("Solo vencidas")
    return "  |  ".join(partes)


@router.get("/mantenimiento/ordenes/excel")
def mnt_ordenes_excel(
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""), prioridad: str = Query(""),
    vencida: str = Query(""),
):
    vencida = vencida == "1"
    ordenes, total = ordenes_repo.listar(q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, vencida=vencida, page=1, per_page=100_000)
    columnas, filas = _ordenes_columnas_filas(ordenes)
    fila_total = [f"Total: {total} órdenes"] + [None] * 8 + [sum(f[9] for f in filas), sum(f[10] for f in filas), None]
    return generar_excel_reporte(
        titulo="UrbanBike — Órdenes de Mantenimiento",
        subtitulo=_ordenes_subtitulo(q, estado, tecnico, prioridad, total, vencida),
        columnas=columnas, filas=filas, fila_total=fila_total, nombre_hoja="Órdenes",
        nombre_archivo=f"urbanbike_ordenes_mantenimiento_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/mantenimiento/ordenes/pdf")
def mnt_ordenes_pdf(
    q: str = Query(""), estado: str = Query(""), tecnico: str = Query(""), prioridad: str = Query(""),
    vencida: str = Query(""),
):
    vencida = vencida == "1"
    ordenes, total = ordenes_repo.listar(q=q, estado=estado, tecnico=tecnico, prioridad=prioridad, vencida=vencida, page=1, per_page=100_000)
    columnas, filas = _ordenes_columnas_filas(ordenes)
    fila_total = [f"Total: {total} órdenes"] + [None] * 8 + [sum(f[9] for f in filas), sum(f[10] for f in filas), None]
    return generar_pdf_reporte(
        titulo="Órdenes de Mantenimiento",
        subtitulo=_ordenes_subtitulo(q, estado, tecnico, prioridad, total, vencida),
        columnas=columnas, filas=filas, fila_total=fila_total,
        nombre_archivo=f"urbanbike_ordenes_mantenimiento_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/mantenimiento/ordenes/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:crear"))])
async def mnt_ordenes_nueva(request: Request, bicicleta_id: str = Query("")):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes_form.html", _ctx(request,
        title="Nueva orden de mantenimiento", flash=flash, modo="crear", orden=None,
        preseleccion_bicicleta_id=bicicleta_id,
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
    _marcar_vencidas([orden])
    # Punto 1.7: una orden cerrada nunca entra en modo edicion, ni siquiera
    # forzando ?modo=editar en la URL a mano.
    if modo == "editar" and orden["estado_reparacion"] == "cerrada":
        flash = {"type": "error", "msg": "Esta orden ya está cerrada -- no se puede editar."}
        modo = "ver"
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
    fecha_limite: str = Form(...),
):
    user = getattr(request.state, "user", {})
    try:
        # Punto 1.7 del Plan V3: una orden ya cerrada no se puede volver a
        # editar (ni siquiera el diagnostico u observaciones) -- cerrar es
        # un estado terminal real, no solo visual. Se revisa contra el
        # estado real en ClickHouse, no contra lo que haya llegado del
        # formulario (que podria estar desactualizado si dos personas
        # abrieron la misma orden a la vez).
        orden_actual = ordenes_repo.obtener(oid)
        if orden_actual and orden_actual["estado_reparacion"] == "cerrada":
            return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "error",
                          "Esta orden ya está cerrada -- no se puede editar.")

        # Los estados no retroceden (mismo punto 1.7): el indice en
        # ESTADOS_VALIDOS define el orden real del flujo de reparacion.
        if (orden_actual
                and ordenes_repo.ESTADOS_VALIDOS.index(estado_reparacion)
                < ordenes_repo.ESTADOS_VALIDOS.index(orden_actual["estado_reparacion"])):
            return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "error",
                          f"No puedes retroceder el estado de "
                          f"\"{ESTADO_ORDEN_LABEL[orden_actual['estado_reparacion']]}\" a "
                          f"\"{ESTADO_ORDEN_LABEL[estado_reparacion]}\".")

        # Punto 1.6: costo de repuestos/mano de obra no puede ser negativo
        # (el cero SI es un valor real y frecuente hoy -- 15 de 21 ordenes
        # cerradas reales tienen costo_repuestos=0 -- asi que solo se
        # bloquea lo que nunca tiene sentido: un costo negativo).
        costo_repuestos_f = float(costo_repuestos or 0)
        costo_mano_obra_f = float(costo_mano_obra or 0)
        if costo_repuestos_f < 0 or costo_mano_obra_f < 0:
            return _flash(request, f"/empleado/mantenimiento/ordenes/{oid}", "error",
                          "El costo de repuestos y el de mano de obra no pueden ser negativos.")

        # fecha_limite se interpreta como fin del dia del plazo (23:59:59) --
        # una orden con fecha_limite = hoy sigue sin estar "vencida" hasta
        # pasada la medianoche.
        fecha_limite_dt = datetime.strptime(fecha_limite, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        ordenes_repo.actualizar(
            oid, id_bicicleta=id_bicicleta, origen=origen, tipo_falla=tipo_falla,
            prioridad=prioridad, estado_reparacion=estado_reparacion, id_tecnico=id_tecnico,
            diagnostico=diagnostico,
            costo_repuestos=costo_repuestos_f, costo_mano_obra=costo_mano_obra_f,
            fecha_limite=fecha_limite_dt,
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
    """Punto 28 del Plan V3 (Prioridad 0.6): antes era una tabla de solo
    lectura sin ninguna acción -- ahora cada fila enlaza a la orden real
    de esa bicicleta (la más reciente, cualquier estado). Si esa orden
    todavía sigue abierta (no 'cerrada'), enlaza a verla/editarla; si no
    hay ninguna orden real, o la última ya se cerró (la bicicleta sigue
    en mantenimiento por un problema nuevo, no rastreado todavía),
    enlaza a crear una nueva con la bicicleta ya preseleccionada."""
    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", filter='estado = "mantenimiento"', sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    for b in bicicletas:
        codigo = b.get("codigo", "")
        orden = None
        try:
            orden = ordenes_repo.obtener_mas_reciente_por_bicicleta(codigo) if codigo else None
        except Exception:
            pass
        if orden and orden.get("estado_reparacion") != "cerrada":
            b["orden_enlace"] = f"/empleado/mantenimiento/ordenes/{orden['id']}"
            b["orden_texto"] = f"Ver orden {orden['codigo']}"
        else:
            id_ch = None
            try:
                id_ch = ordenes_repo.bicicleta_id_por_codigo(codigo) if codigo else None
            except Exception:
                pass
            b["orden_enlace"] = f"/empleado/mantenimiento/ordenes/nueva?bicicleta_id={id_ch}" if id_ch else "/empleado/mantenimiento/ordenes/nueva"
            b["orden_texto"] = "Crear orden"
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

    # Punto 1.8: 3 conteos reales, cada uno con la misma fuente que ya usa
    # su pantalla real (seguimiento.html, devoluciones.html, y la cola de
    # certificacion migrada en la Parte 1 -- ver docs/HOJA_DE_RUTA.md).
    pendientes_validacion = 0
    seguimientos_activos = 0
    try:
        pb = _pb()
        pendientes_validacion = pb.list_records(
            "viajes", filter='estado = "pendiente_validacion"', per_page=1,
        ).get("totalItems", 0)
        seguimientos_activos = pb.list_records(
            "viajes", filter='estado = "activo"', per_page=1,
        ).get("totalItems", 0)
    except Exception:
        pass

    reparaciones_certificar = 0
    try:
        reparaciones_certificar = len(ordenes_repo.listar_cerradas_pendientes_certificar())
    except Exception:
        pass

    # "Daños por verificar" y "disponibilidad por confirmar" del punto 1.8
    # apuntan, en el codigo real, a la MISMA cola (ver auditoria previa) --
    # una sola tarjeta, no dos numeros identicos repetidos.
    pendientes = [
        {"titulo": "Seguimientos activos", "conteo": seguimientos_activos,
         "enlace": "/empleado/vigilancia/seguimiento", "color": "blue", "icono": "ojo"},
        {"titulo": "Devoluciones por validar", "conteo": pendientes_validacion,
         "enlace": "/empleado/vigilancia/devoluciones", "color": "yellow", "icono": "reloj"},
        {"titulo": "Reparaciones por certificar", "conteo": reparaciones_certificar,
         "enlace": "/empleado/vigilancia/mantenimiento/cerrar", "color": "red", "icono": "llave"},
    ]

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
        pendientes=pendientes,
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


def _vig_seguimiento_estado(mins: int) -> str:
    """3 tramos reales del mapa de seguimiento (Plan V3, punto de revisión
    visual): usa la misma constante `_LIMITE_ALERTA_MIN` (120 min) que
    `_vig_alertas_data()`, pero el corte de "Rojo" es en `mins >= 120`
    (pedido explícito del punto: "120 minutos o más"), mientras que
    `_vig_alertas_data()` marca alerta en `mins > 120` (estrictamente mayor)
    -- a los 120 min exactos esta pantalla ya muestra Rojo pero la de
    "Alertas de Viajes" todavía no marca alerta. Diferencia real de 1 minuto
    en el límite, no un bug de esta función: no armonizar sin pedirlo, ya
    que "120 minutos o más" fue el requisito explícito para este punto.
    Con un tramo intermedio "próximo a vencer" (110-119) que esos otros 2
    puntos no necesitan. Compartida entre la pantalla (vía JS, misma lógica)
    y este export para no tener 2 fuentes de verdad sobre dónde cae cada
    corte."""
    if mins >= _LIMITE_ALERTA_MIN:
        return f"Rojo -- {_LIMITE_ALERTA_MIN} min o más"
    if mins >= _LIMITE_ALERTA_MIN - 10:
        return "Amarillo -- próximo a vencer"
    return "Celeste -- normal"


def _vig_seguimiento_columnas_filas(viajes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Estación de inicio", ancho=26),
        ColumnaReporte("Inicio", ancho=18),
        ColumnaReporte("Tiempo transcurrido (min)", ancho=22, formato="entero"),
        ColumnaReporte("Estado", ancho=24),
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
            _vig_seguimiento_estado(mins),
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
        [v.get("bicicleta_codigo", "") for v in viajes_activos + viajes_pendientes], request=request,
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
        modalidad_v = v.get("modalidad_actual") or "hora"
        # Igual que _tarifa_hora() ("nunca levanta excepcion hacia el
        # llamador") y que el bloque analogo de ciclista.py:viaje_activo()
        # de esta misma tarea -- categoria_de_bicicleta()/precio_modalidad()/
        # total_segmentos_cerrados() son consultas directas a ClickHouse
        # (ch.query_one()/ch.query()) sin try/except propio; sin este
        # try/except, un blip transitorio de ClickHouse tumbaria con un 500
        # sin manejar TODA la pagina de devoluciones (no solo el numero en
        # vivo), bloqueando el flujo operativo completo de Vigilancia.
        v["precio_hora"] = 0.0
        v["precio_hora_recargo"] = 0.0
        v["subtotal_segmentos_cerrados"] = 0.0
        try:
            # Con promocion aplicable ya descontada (mismo hallazgo/fix que
            # vig_devolver(), 17-ago-2026) -- para que el numero en vivo
            # coincida con lo que se cobrara de verdad. precio_hora_recargo
            # SIEMPRE via _tarifa_hora() (sin promo, sin importar la
            # modalidad activa): nunca se descuenta el multiplicador del
            # recargo por demora.
            resultado_v = tarifas_repo.precio_modalidad_con_promocion(v.get("bicicleta_codigo", ""), tipo_membresia, modalidad_v)
            v["precio_hora"] = resultado_v[0] if resultado_v else 0.0
            v["precio_hora_recargo"] = _tarifa_hora(v.get("bicicleta_codigo", ""), tipo_membresia) if pb is not None else 0.0
            v["subtotal_segmentos_cerrados"] = alquileres_repo.total_segmentos_cerrados(v["id"])
        except Exception:
            pass

    return templates.TemplateResponse(request, "empleado/vigilancia/devoluciones.html", _ctx(request,
        title="Registrar Devoluciones", flash=flash,
        viajes=viajes_activos, viajes_pendientes=viajes_pendientes, estaciones=estaciones,
    ))


# Ventana de gracia para que Vigilancia confirme la devolucion antes de
# que empiece a correr el recargo por demora. Cambiado de 5h a 1h el
# 26-ago-2026 (decision de Washington) -- ver docs/HOJA_DE_RUTA.md,
# seccion 91. Debe coincidir siempre con MINUTOS_GRACIA_DEMORA en
# app/static/js/costo-en-vivo.js, que solo refleja este calculo, nunca
# lo decide.
MINUTOS_GRACIA_DEMORA = 60


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
    La duración (duracion_minutos) y el recargo por demora se calculan
    aquí con la hora REAL de este momento -- pero el subtotal del
    segmento 'hora' se CONGELA en fecha_fin (el momento en que el
    ciclista reportó la devolución), no en 'ahora': la espera hasta
    esta confirmación es tiempo de espera, no tiempo de uso real
    (decisión de negocio reconfirmada con Washington 17-ago-2026, ver
    el bloque de cálculo del segmento 'hora' más abajo)."""
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

        # Cierre del ULTIMO segmento (punto 4 del spec) -- 'ahora' es la
        # hora REAL de confirmacion de Vigilancia, usada para
        # duracion_minutos y para el recargo por demora; el subtotal
        # del segmento 'hora' en si se congela en fecha_fin (ver mas
        # abajo), no en 'ahora'. Todo esto es solo calculo en Python,
        # sin escribir nada todavia -- si algo falla aca, el viaje
        # queda exactamente como estaba.
        ahora = datetime.now(timezone.utc)
        ahora_str = _ahora()
        modalidad_final = viaje.get("modalidad_actual") or "hora"
        inicio_segmento_final = viaje.get("inicio_segmento_actual") or viaje.get("fecha_inicio", "")

        tipo_membresia = "casual"
        try:
            ciclista_pb = pb.get_record("users", viaje.get("ciclista_id", ""))
            tipo_membresia = membresias_repo.tipo_membresia_real(ciclista_pb.get("email", ""))
        except Exception:
            pass

        bici_codigo_para_tarifa = viaje.get("bicicleta_codigo", "")
        id_categoria = tarifas_repo.categoria_de_bicicleta(bici_codigo_para_tarifa)
        resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, modalidad_final) if id_categoria else None
        # Promocion aplicable (si hay alguna) ya descontada -- SOLO para el
        # SUBTOTAL real del segmento (hallazgo/fix de la revision final del
        # plan de modalidad de tarifa real, 17-ago-2026: el cobro real
        # ignoraba promociones por completo, aunque la ficha SI las
        # mostraba con descuento). `resultado` (sin promo) se mantiene
        # aparte porque precio_hora_display (el multiplicador del recargo
        # por demora) nunca debe llevar descuento -- "no tiene sentido
        # descontar una penalizacion", mismo criterio ya aplicado a
        # descuento_monto.
        resultado_con_promo = (
            tarifas_repo.precio_modalidad_con_promocion(bici_codigo_para_tarifa, tipo_membresia, modalidad_final)
            if id_categoria else None
        )
        precio_hora_display = 0.0  # para el campo precio_hora de 'pagos', compatibilidad con facturas viejas
        id_tarifa_final = None

        retraso_min = 0.0
        subtotal_ultimo_segmento = 0.0
        if resultado and resultado_con_promo:
            precio_modalidad_final, id_tarifa_final = resultado
            precio_modalidad_final_con_promo, _ = resultado_con_promo
            inicio_dt = datetime.fromisoformat(inicio_segmento_final.replace("Z", "+00:00"))

            if modalidad_final == "hora":
                # Gracia (MINUTOS_GRACIA_DEMORA) desde que el ciclista reporto
                # la devolucion (fecha_fin del viaje), NO desde el inicio del
                # segmento.
                fecha_fin_reportada = viaje.get("fecha_fin", "")
                fin_dt = (datetime.fromisoformat(fecha_fin_reportada.replace("Z", "+00:00"))
                          if fecha_fin_reportada else ahora)

                # El subtotal del segmento abierto se CONGELA en fecha_fin
                # (el momento en que el ciclista reporto la devolucion) --
                # decision de negocio reconfirmada con Washington 17-ago-2026:
                # la espera hasta que Vigilancia confirme NO es tiempo de uso
                # real, es tiempo de espera -- solo el recargo por demora
                # (tras MINUTOS_GRACIA_DEMORA de gracia) cobra por esa
                # espera, nunca el subtotal. Restaura el diseno original de
                # la seccion 70 de
                # docs/HOJA_DE_RUTA.md, que la Tarea 7 del plan
                # "modalidad-tarifa-real" habia revertido sin reconfirmar.
                # Si el viaje no fue reportado antes (Vigilancia cierra un
                # viaje todavia 'activo'), fecha_fin_reportada esta vacio y
                # fin_dt = ahora -- mismo resultado que antes de este cambio,
                # porque no hubo espera que congelar.
                # Piso de 1 minuto (mismo criterio de siempre).
                minutos_ultimo_segmento = max(1, int((fin_dt - inicio_dt).total_seconds() / 60))
                subtotal_ultimo_segmento = round(minutos_ultimo_segmento / 60 * precio_modalidad_final_con_promo, 2)

                retraso_min = max(0.0, (ahora - fin_dt).total_seconds() / 60 - MINUTOS_GRACIA_DEMORA) if fecha_fin_reportada else 0.0
                precio_hora_display = precio_modalidad_final  # SIN promo -- multiplicador del recargo
            else:
                subtotal_ultimo_segmento = precio_modalidad_final_con_promo
                # Gracia (MINUTOS_GRACIA_DEMORA) desde que TERMINA la ventana
                # comprada (dia=24h, semana=7d), no desde el reporte -- con
                # tarifa plana, "demora" es exceder lo pagado (spec).
                horas_ventana = 24 if modalidad_final == "dia" else 24 * 7
                fin_ventana = inicio_dt + timedelta(hours=horas_ventana)
                retraso_min = max(0.0, (ahora - fin_ventana).total_seconds() / 60 - MINUTOS_GRACIA_DEMORA)
                precio_hora_resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, "hora")
                precio_hora_display = precio_hora_resultado[0] if precio_hora_resultado else 0.0

            recargo_demora = round(retraso_min / 60 * precio_hora_display, 2)
        else:
            recargo_demora = 0.0

        duracion = max(1, int((ahora - datetime.fromisoformat(
            viaje.get("fecha_inicio", "").replace("Z", "+00:00"))).total_seconds() / 60))

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
            actualizar_viaje["fecha_fin"] = ahora_str
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
            # tipo_membresia/recargo_demora ya se resolvieron arriba (con la
            # modalidad real del ultimo segmento, no siempre 'hora') --
            # reusados aca, sin recalcular por segunda vez.
            subtotal = round(alquileres_repo.total_segmentos_cerrados(viaje_id) + subtotal_ultimo_segmento, 2)

            # Descuento personal canjeado al iniciar este viaje (ver
            # ciclista.py:reservar()) -- solo sobre el subtotal, nunca sobre
            # el recargo por demora (no tiene sentido descontar una penalizacion).
            descuento_codigo = viaje.get("descuento_codigo") or ""
            descuento_porcentaje = float(viaje.get("descuento_porcentaje") or 0)
            descuento_monto = round(subtotal * descuento_porcentaje / 100, 2) if descuento_porcentaje else 0.0

            monto_total = round(subtotal + recargo_demora - descuento_monto, 2)
            pago_creado = pb.create_record("pagos", {
                "viaje_id":          viaje_id,
                "ciclista_id":       viaje.get("ciclista_id", ""),
                "ciclista_nombre":   viaje.get("ciclista_nombre") or "—",
                "duracion_minutos":  duracion,
                "tipo_bicicleta":    tipo_bicicleta,
                "tipo_membresia":    tipo_membresia,
                "precio_hora":       precio_hora_display,
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
                "grupo_reserva_id":  viaje.get("grupo_reserva_id") or "",
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
                referencia_id=pago_creado.get("id", ""),
            )

            if recargo_demora > 0:
                notificaciones_repo.notificar_usuario(
                    pb, viaje.get("ciclista_id", ""), tipo="penalizacion",
                    titulo="Recargo por demora aplicado",
                    mensaje=f"Se aplicó un recargo de ${recargo_demora:.2f} por demora en la devolución "
                            "(más de 1h desde que reportaste el fin del viaje).",
                    enlace="/ciclista/pagos",
                )

            # Cierra el aviso "devolución por validar" de Vigilancia (ver
            # ciclista.py:finalizar()) -- ya se validó de verdad, no basta
            # con que alguien lo haya descartado con un clic.
            notificaciones_repo.resolver_pendiente(
                tipo="devolucion_pendiente_validar", referencia_id=viaje_id, rol_destino="empleado-vigilancia",
            )

            notificaciones_repo.notificar_usuario(
                pb, viaje.get("ciclista_id", ""), tipo="devolucion_validada",
                titulo="Devolución confirmada",
                mensaje=f"Vigilancia confirmó la devolución de {viaje.get('bicicleta_codigo', '—')}. "
                        f"Duración real: {duracion} min.",
                enlace="/ciclista/historial",
            )

        detalle = f"Devolución {motivo} en {estacion_fin_nombre} (duración real: {duracion} min) — bicicleta retenida para inspección"
        if observaciones:
            detalle += f" — {observaciones}"

        # INSERT del ultimo segmento en ClickHouse -- al final a proposito
        # (ver nota de ordenamiento arriba): si esto falla, el viaje ya
        # esta completado, la bici ya esta en mantenimiento y el pago ya
        # se creo con el monto correcto (subtotal_ultimo_segmento no
        # depende de que este INSERT tenga exito). Solo faltaria esa fila
        # en el historial de alquileres -- se deja rastro real en la
        # auditoria para que no quede invisible del todo.
        if resultado and not existentes:
            try:
                alquileres_repo.cerrar_segmento(
                    viaje_id=viaje_id, ciclista_id=viaje.get("ciclista_id", ""),
                    bicicleta_codigo=bici_codigo_para_tarifa, modalidad=modalidad_final,
                    id_tarifa=id_tarifa_final, fecha_inicio=inicio_segmento_final,
                    fecha_fin=ahora_str, subtotal=subtotal_ultimo_segmento, recargo=recargo_demora,
                )
            except Exception as e:
                detalle += f" — AVISO: no se pudo registrar el último segmento en el historial ({e})"

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
        # Punto 1.8 del Plan V3: no se puede cobrar por daños si el
        # checklist no registró ningún ítem con "Con daños" -- se ignora
        # cualquier monto que haya llegado en el campo (bloqueado también
        # en el cliente, pero esto es lo que de verdad protege contra un
        # POST directo con el campo habilitado a mano).
        if not fallas:
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


def _con_nombre_ciclista(infracciones: list[dict]) -> list[dict]:
    """Resuelve ciclista_id -> nombre/correo reales de PocketBase antes de
    mostrar o exportar (punto 2.8, mitad "nombre del ciclista" -- la mitad
    de aviso/resolucion ya se resolvio en la seccion 89). Antes se
    mostraba el id crudo de PocketBase tal cual, tanto en pantalla como en
    los 2 exports. No muta las filas originales -- agrega
    ciclista_nombre/ciclista_email a una copia de cada una. Fetch por id
    individual (no batch): mismo patron ya usado en el resto de este
    archivo (ej. linea 1701/1798) para resolver un ciclista puntual, y el
    volumen real (decenas de infracciones) no justifica una consulta
    "IN" nueva."""
    pb = _pb()
    cache: dict[str, dict] = {}
    resultado = []
    for i in infracciones:
        cid = i.get("ciclista_id") or ""
        if cid and cid not in cache:
            try:
                u = pb.get_record("users", cid)
                cache[cid] = {"nombre": u.get("name") or u.get("email", ""), "email": u.get("email", "")}
            except Exception:
                cache[cid] = {"nombre": "", "email": ""}
        datos = cache.get(cid, {"nombre": "", "email": ""})
        i2 = dict(i)
        i2["ciclista_nombre"] = datos["nombre"] or cid or "—"
        i2["ciclista_email"] = datos["email"]
        resultado.append(i2)
    return resultado


@router.get("/vigilancia/infracciones", response_class=HTMLResponse)
async def vig_infracciones(request: Request):
    flash = request.session.pop("flash", None)
    infracciones: list[dict] = []
    try:
        infracciones = _pb().list_records("infracciones", sort="-fecha", per_page=500).get("items", [])
        infracciones = _con_nombre_ciclista(infracciones)
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
    infracciones = _pb().list_records("infracciones", sort="-fecha", per_page=500).get("items", [])
    return _con_nombre_ciclista(infracciones)


def _vig_infracciones_columnas_filas(infracciones: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Correo", ancho=26),
        ColumnaReporte("Tipo", ancho=18),
        ColumnaReporte("Descripción", ancho=34),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Fecha", ancho=18),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Resolución", ancho=34),
        ColumnaReporte("Resuelta por", ancho=22),
        ColumnaReporte("Fecha resolución", ancho=20),
    ]
    filas = [
        [
            i.get("ciclista_nombre") or i.get("ciclista_id") or "—",
            i.get("ciclista_email") or "—",
            i.get("tipo") or "—",
            i.get("descripcion") or "—",
            i.get("bicicleta_codigo") or "—",
            (i.get("fecha") or "—").replace("T", " ").replace("Z", "") if i.get("fecha") else "—",
            "Resuelta" if i.get("resuelta") else "Pendiente",
            i.get("resolucion") or "—",
            i.get("resuelta_por") or "—",
            (i.get("fecha_resolucion") or "—").replace("T", " ").replace("Z", "") if i.get("fecha_resolucion") else "—",
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
        fila_total=[f"Total: {len(infracciones)} infracciones", None, None, None, None, None, None, None, None, None],
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
        fila_total=[f"Total: {len(infracciones)} infracciones", None, None, None, None, None, None, None, None, None],
        nombre_archivo="urbanbike_vigilancia_infracciones.pdf",
    )


@router.get("/vigilancia/mantenimiento/cerrar", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("ordenes_mantenimiento:leer"))])
async def vig_mantenimiento_cerrar(request: Request):
    flash = request.session.pop("flash", None)
    ordenes = _vig_cerrar_mantenimiento_ordenes()
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
        orden = ordenes_repo.obtener(oid)
        if not orden:
            return _flash(request, "/empleado/vigilancia/mantenimiento/cerrar", "error", "Orden no encontrada.")

        bici = bicicletas_repo.obtener(orden["id_bicicleta"])
        if not bici:
            raise RuntimeError(
                f"Bicicleta {orden.get('bicicleta_codigo', orden['id_bicicleta'])} no tiene un id real en "
                "ClickHouse -- no se puede actualizar su estado real."
            )
        bicicletas_repo.actualizar(
            orden["id_bicicleta"], codigo=bici["codigo"], id_modelo=str(bici["id_modelo"]),
            estado="disponible", id_estacion=str(bici["id_estacion"] or ""),
            numero_serie=bici["numero_serie"], fecha_adquisicion=bici["fecha_adquisicion"],
            observacion=bici["observacion"], es_electrica=bool(bici["es_electrica"]),
        )
        notificaciones_repo.notificar_rol(
            "empleado-operacion", tipo="bici_disponible",
            titulo="Bicicleta disponible",
            mensaje=f"{orden.get('bicicleta_codigo', oid)} completó mantenimiento y está disponible nuevamente.",
            enlace="/empleado/operacion/bicicletas",
        )
        # observaciones_cierre no tiene columna propia en
        # urbanbike_operativa.ordenes_mantenimiento (a diferencia de la
        # ordenes_mant vieja de PocketBase) -- queda en la bitacora real,
        # unico registro de "quien certifico y con que observaciones"
        # desde esta migracion (ver docs/HOJA_DE_RUTA.md).
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "ordenes_mantenimiento",
            f"Mantenimiento certificado: orden {orden.get('codigo', oid)} de {orden.get('bicicleta_codigo', oid)}"
            + (f" — {observaciones_cierre.strip()}" if observaciones_cierre.strip() else ""), request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/vigilancia/mantenimiento/cerrar", "success",
                      "Mantenimiento certificado. Bicicleta disponible nuevamente.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/mantenimiento/cerrar", "error", str(e))


def _vig_cerrar_mantenimiento_ordenes() -> list[dict]:
    return ordenes_repo.listar_cerradas_pendientes_certificar()


def _vig_cerrar_mantenimiento_columnas_filas(ordenes: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Diagnóstico", ancho=36),
        ColumnaReporte("Técnico", ancho=22),
        ColumnaReporte("Cierre", ancho=18),
    ]
    filas = [
        [
            o.get("bicicleta_codigo") or "—",
            o.get("diagnostico") or "—",
            o.get("tecnico_nombre") or "—",
            o["fecha_cierre"].strftime("%Y-%m-%d %H:%M") if o.get("fecha_cierre") else "—",
        ]
        for o in ordenes
    ]
    return columnas, filas


@router.get("/vigilancia/mantenimiento/cerrar/excel")
def vig_mantenimiento_cerrar_excel():
    ordenes = _vig_cerrar_mantenimiento_ordenes()
    columnas, filas = _vig_cerrar_mantenimiento_columnas_filas(ordenes)
    return generar_excel_reporte(
        titulo="UrbanBike — Órdenes de Mantenimiento Pendientes de Certificar",
        subtitulo=f"Total: {len(ordenes)} órdenes cerradas por Mantenimiento, pendientes de certificar",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(ordenes)} órdenes", None, None, None],
        nombre_hoja="Pendientes Certificar",
        nombre_archivo="urbanbike_vigilancia_ordenes_pendientes_certificar.xlsx",
    )


@router.get("/vigilancia/mantenimiento/cerrar/pdf")
def vig_mantenimiento_cerrar_pdf():
    ordenes = _vig_cerrar_mantenimiento_ordenes()
    columnas, filas = _vig_cerrar_mantenimiento_columnas_filas(ordenes)
    return generar_pdf_reporte(
        titulo="Órdenes de Mantenimiento Pendientes de Certificar",
        subtitulo=f"Total: {len(ordenes)} órdenes cerradas por Mantenimiento, pendientes de certificar",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(ordenes)} órdenes", None, None, None],
        nombre_archivo="urbanbike_vigilancia_ordenes_pendientes_certificar.pdf",
    )


_LIMITE_ALERTA_MIN = 120


def _vig_alertas_data() -> list[dict]:
    """Viajes -- activos en vivo o ya finalizados -- que superan
    _LIMITE_ALERTA_MIN, con el tiempo excedido ya calculado -- compartida
    entre la pantalla y el export para no duplicar la logica (ver
    docs/HOJA_DE_RUTA.md). Antes del punto 2.8 esta funcion solo miraba
    viajes con estado="activo": en cuanto un viaje con alerta terminaba
    (completado/cancelado), la alerta desaparecia de esta pantalla para
    siempre -- sin historial real de que existio, quien la atendio o
    cuando. Ahora tambien trae viajes ya finalizados cuya duracion_minutos
    real supero el limite, para que quede como historial consultable.
    """
    alertas: list[dict] = []
    pb = _pb()
    viajes = pb.list_records(
        "viajes",
        filter=f'estado = "activo" || duracion_minutos > {_LIMITE_ALERTA_MIN}',
        sort="-fecha_inicio", per_page=300,
    ).get("items", [])
    ahora = datetime.now(timezone.utc)
    for v in viajes:
        activo = v.get("estado") == "activo"
        if activo:
            try:
                inicio = datetime.fromisoformat(v.get("fecha_inicio", "").replace("Z", "+00:00"))
                mins = int((ahora - inicio).total_seconds() / 60)
            except Exception:
                continue
        else:
            mins = int(v.get("duracion_minutos") or 0)
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
            "viaje_id":       v["id"],
            "ciclista":       v.get("ciclista_nombre") or "—",
            "email":          email or "—",
            "bicicleta":      v.get("bicicleta_codigo") or "—",
            "tiempo_total":   mins,
            "tiempo_exceso":  mins - _LIMITE_ALERTA_MIN,
            "atendida":       bool(v.get("alerta_atendida")),
            "activo":         activo,
            "atendida_por":   v.get("alerta_atendida_por") or "",
            "fecha_atencion": (v.get("alerta_fecha_atencion") or "").replace("T", " ").replace("Z", ""),
            "nota":           v.get("alerta_nota") or "",
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
async def vig_alertas_atender(request: Request, viaje_id: str, nota: str = Form("")):
    user = getattr(request.state, "user", {})
    nota = nota.strip()
    if not nota:
        return _flash(request, "/empleado/vigilancia/alertas", "error",
                       "Indica qué acción se tomó antes de marcar la alerta como atendida.")
    try:
        pb = _pb()
        pb.update_record("viajes", viaje_id, {
            "alerta_atendida":       True,
            "alerta_atendida_por":   user.get("name") or user.get("email", ""),
            "alerta_fecha_atencion": _ahora(),
            "alerta_nota":           nota,
        })
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes",
            f"Alerta de viaje atendida (id: {viaje_id}): {nota}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        return _flash(request, "/empleado/vigilancia/alertas", "success", "Alerta marcada como atendida.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/alertas", "error", str(e))


def _vig_alertas_columnas_filas(alertas: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Ciclista", ancho=24),
        ColumnaReporte("Contacto", ancho=28),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Viaje", ancho=12),
        ColumnaReporte("Tiempo total (min)", ancho=18, formato="entero"),
        ColumnaReporte("Tiempo excedido (min)", ancho=20, formato="entero"),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Atendida por", ancho=22),
        ColumnaReporte("Fecha atención", ancho=20),
        ColumnaReporte("Acción tomada", ancho=34),
    ]
    filas = [
        [
            a["ciclista"], a["email"], a["bicicleta"],
            "Activo" if a["activo"] else "Finalizado",
            a["tiempo_total"], a["tiempo_exceso"],
            "Atendida" if a["atendida"] else "Pendiente",
            a["atendida_por"] or "—",
            a["fecha_atencion"] or "—",
            a["nota"] or "—",
        ]
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
        fila_total=[f"Total: {len(alertas)} alertas", None, None, None, None, None, None, None, None, None],
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
        fila_total=[f"Total: {len(alertas)} alertas", None, None, None, None, None, None, None, None, None],
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
    # Punto 2.6/87: la fuente real de ordenes es ordenes_repo/ClickHouse
    # (mismo patron que /mantenimiento/ordenes y el dashboard) -- la
    # coleccion ordenes_mant de PocketBase es huerfana desde el punto 1.8
    # Parte 1 (ver docs/HOJA_DE_RUTA.md seccion 83) y quedaba mostrando un
    # total incompleto sin ningun aviso.
    ordenes: list[dict] = []
    total = 0
    try:
        ordenes, total = ordenes_repo.listar(page=1, per_page=100_000)
    except Exception:
        pass

    estado_counts = {e: 0 for e in ordenes_repo.ESTADOS_VALIDOS}
    preventivo = 0
    for o in ordenes:
        estado_counts[o["estado_reparacion"]] = estado_counts.get(o["estado_reparacion"], 0) + 1
        if o["origen"] == "preventivo":
            preventivo += 1
    correctivo = len(ordenes) - preventivo

    estado_labels = [ESTADO_ORDEN_LABEL[e] for e in ordenes_repo.ESTADOS_VALIDOS]
    estado_values = [estado_counts[e] for e in ordenes_repo.ESTADOS_VALIDOS]
    tipo_labels = ["Preventivo", "Correctivo"]
    tipo_values = [preventivo, correctivo]

    return templates.TemplateResponse(request, "empleado/mantenimiento/reportes.html", _ctx(request,
        title="Reportes — Mantenimiento", flash=flash,
        total_ordenes=total,
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


# ── Soporte (chat interno, punto 12 Opción B; expandido punto 2.4 -- ver
#    docs/HOJA_DE_RUTA.md secciones 68 y 85). El documento de requerimientos
#    dice explícitamente que Vigilancia da soporte a los ciclistas -- Admin
#    también puede entrar (ruta espejo en admin.py, mismo repo), con
#    supervisión total incluidas las conversaciones borradas, por el mismo
#    criterio que estaciones/tarifas/promociones. ───────────────────────────

def _mensaje_json(m: dict) -> dict:
    """Misma forma que ciclista.py:_mensaje_json() -- compartida entre el
    render inicial (Jinja) y el sondeo de 4s (JSON)."""
    return {
        "id": m.get("id", ""),
        "autor_rol": m.get("autor_rol", ""),
        "autor_id": m.get("autor_id", ""),
        "autor_nombre": m.get("autor_nombre", ""),
        "texto": m.get("texto", ""),
        "fecha": m.get("fecha", ""),
        "adjunto_url": file_url("mensajes_soporte", m.get("id", ""), m.get("adjunto", "")),
        "adjunto_nombre": m.get("adjunto", ""),
    }


async def _leer_adjunto_soporte(archivo: UploadFile | None) -> tuple[str, bytes, str] | None:
    if archivo is None or not archivo.filename:
        return None
    mensajes_soporte_repo.validar_adjunto(archivo.content_type, archivo.size)
    contenido = await archivo.read()
    return (archivo.filename, contenido, archivo.content_type)


@router.get("/vigilancia/soporte", response_class=HTMLResponse)
async def vig_soporte_lista(request: Request):
    flash = request.session.pop("flash", None)
    conversaciones = mensajes_soporte_repo.listar_conversaciones()
    return templates.TemplateResponse(request, "empleado/vigilancia/soporte.html", _ctx(request,
        title="Soporte", flash=flash, conversaciones=conversaciones,
        motivo_label=mensajes_soporte_repo.MOTIVO_LABEL, base_url="/empleado/vigilancia/soporte",
    ))


@router.get("/vigilancia/soporte/{conversacion_id}", response_class=HTMLResponse)
async def vig_soporte_detalle(request: Request, conversacion_id: str):
    flash = request.session.pop("flash", None)
    user = getattr(request.state, "user", {})
    conv = mensajes_soporte_repo.obtener_conversacion(conversacion_id)
    if not conv:
        return _flash(request, "/empleado/vigilancia/soporte", "error", "Esa conversación no existe.")
    mensajes = mensajes_soporte_repo.listar_hilo(conversacion_id)
    mensajes_soporte_repo.marcar_leidos(conversacion_id, para_rol="empleado-vigilancia")
    ciclista_nombre = conv.get("autor_nombre") or conv.get("ciclista_id", "")
    return templates.TemplateResponse(request, "empleado/vigilancia/soporte_detalle.html", _ctx(request,
        title=f"Soporte — {ciclista_nombre}", flash=flash, mensajes=[_mensaje_json(m) for m in mensajes],
        conversacion_id=conversacion_id, ciclista_nombre=ciclista_nombre, soy_ciclista=False,
        propio_id=user.get("id", ""),
        agente_nombre=conv.get("agente_nombre", ""),
        motivo_label=mensajes_soporte_repo.MOTIVO_LABEL.get(conv.get("motivo", ""), "—"),
        poll_url=f"/empleado/vigilancia/soporte/{conversacion_id}/mensajes",
        enviar_url=f"/empleado/vigilancia/soporte/{conversacion_id}/enviar",
        eliminar_url_base=f"/empleado/vigilancia/soporte/{conversacion_id}/eliminar-mensaje",
        eliminar_conversacion_url=f"/empleado/vigilancia/soporte/{conversacion_id}/eliminar",
        puede_borrar_conversacion=True,
        puede_moderar=True,
        base_url="/empleado/vigilancia/soporte",
    ))


@router.post("/vigilancia/soporte/{conversacion_id}/enviar")
async def vig_soporte_enviar(
    request: Request, conversacion_id: str,
    texto: str = Form(""), adjunto: UploadFile | None = File(None),
):
    user = getattr(request.state, "user", {})
    try:
        archivo = await _leer_adjunto_soporte(adjunto)
        mensajes_soporte_repo.enviar(
            conversacion_id=conversacion_id, autor_id=user.get("id", ""),
            autor_rol=user.get("rol_slug", ""), autor_nombre=user.get("name") or user.get("email", ""),
            texto=texto, archivo=archivo,
        )
    except ValueError as e:
        return _flash(request, f"/empleado/vigilancia/soporte/{conversacion_id}", "error", str(e))
    except Exception:
        return _flash(request, f"/empleado/vigilancia/soporte/{conversacion_id}", "error", "No se pudo enviar la respuesta. Intenta de nuevo.")
    return RedirectResponse(f"/empleado/vigilancia/soporte/{conversacion_id}", status_code=302)


@router.post("/vigilancia/soporte/{conversacion_id}/eliminar-mensaje/{mensaje_id}")
async def vig_soporte_eliminar_mensaje(request: Request, conversacion_id: str, mensaje_id: str):
    """Vigilancia modera: puede ocultar cualquier mensaje de la
    conversación (punto 32 del Plan V3), no solo los suyos -- ver
    mensajes_soporte_repo.eliminar_mensaje(puede_moderar=True)."""
    user = getattr(request.state, "user", {})
    ok, motivo_error = mensajes_soporte_repo.eliminar_mensaje(
        mensaje_id, actor_id=user.get("id", ""), puede_moderar=True)
    if not ok:
        return _flash(request, f"/empleado/vigilancia/soporte/{conversacion_id}", "error", motivo_error)
    return RedirectResponse(f"/empleado/vigilancia/soporte/{conversacion_id}", status_code=302)


@router.post("/vigilancia/soporte/{conversacion_id}/eliminar")
async def vig_soporte_eliminar_conversacion(request: Request, conversacion_id: str):
    """Borra (soft-delete) TODA la conversación -- reservado a Vigilancia/
    Admin por el propio prefijo de ruta, nunca expuesto a /ciclista/."""
    user = getattr(request.state, "user", {})
    mensajes_soporte_repo.eliminar_conversacion(conversacion_id, actor_id=user.get("id", ""))
    return _flash(request, "/empleado/vigilancia/soporte", "success", "Conversación eliminada.")


@router.get("/vigilancia/soporte/{conversacion_id}/mensajes")
async def vig_soporte_mensajes(request: Request, conversacion_id: str):
    """JSON liviano para el sondeo de 4s de la conversación abierta
    (app/static/js/chat-soporte.js)."""
    mensajes = mensajes_soporte_repo.listar_hilo(conversacion_id)
    mensajes_soporte_repo.marcar_leidos(conversacion_id, para_rol="empleado-vigilancia")
    return JSONResponse({"items": [_mensaje_json(m) for m in mensajes]})
