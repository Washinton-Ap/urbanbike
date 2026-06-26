"""Rutas para roles de empleado: operación, mantenimiento, vigilancia."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.db import clickhouse as ch
from app.db.pocketbase import get_admin_client, registrar_auditoria
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


@router.get("/operacion/inventario", response_class=HTMLResponse)
async def op_inventario(request: Request):
    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/operacion/inventario.html", _ctx(request,
        title="Inventario de Bicicletas", flash=flash, bicicletas=bicicletas,
    ))


@router.get("/operacion/alquileres", response_class=HTMLResponse)
async def op_alquileres(request: Request):
    flash = request.session.pop("flash", None)
    viajes: list[dict] = []
    bicicletas: list[dict] = []
    todas_bicicletas: list[dict] = []
    estaciones: list[dict] = []
    estaciones_nombres: dict[str, str] = {}
    filtro = request.query_params.get("estado", "")
    try:
        pb = _pb()
        fil = f'estado = "{filtro}"' if filtro else ""
        viajes = pb.list_records("viajes", filter=fil, sort="-fecha_inicio", per_page=200).get("items", [])
        bicicletas = pb.list_records("bicicletas", filter='estado = "disponible"', sort="codigo", per_page=200).get("items", [])
        todas_bicicletas = pb.list_records("bicicletas", sort="codigo", per_page=500).get("items", [])
        estaciones = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50).get("items", [])
        estaciones_nombres = {e["id"]: e.get("nombre", "") for e in estaciones}

        # Bicicletas agrupadas por estación
        por_estacion: dict[str, list[dict]] = {}
        for b in todas_bicicletas:
            por_estacion.setdefault(b.get("estacion") or "Sin estación", []).append(b)
    except Exception:
        por_estacion = {}

    return templates.TemplateResponse(request, "empleado/operacion/alquileres.html", _ctx(request,
        title="Gestión de Alquileres", flash=flash,
        viajes=viajes, bicicletas=bicicletas, estaciones=estaciones,
        estaciones_nombres=estaciones_nombres, por_estacion=por_estacion,
        filtro=filtro,
    ))


@router.post("/operacion/alquileres/crear")
async def op_alquileres_crear(
    request: Request,
    bicicleta_id:           str = Form(...),
    bicicleta_codigo:       str = Form(...),
    estacion_inicio_id:     str = Form(...),
    estacion_inicio_nombre: str = Form(...),
    ciclista_nombre:        str = Form(""),
):
    try:
        pb = _pb()
        # Buscar coords de la estación
        est = pb.get_record("estaciones", estacion_inicio_id)
        lat = est.get("latitud", 0) or 0
        lng = est.get("longitud", 0) or 0

        pb.create_record("viajes", {
            "ciclista_id":            "",
            "ciclista_nombre":        ciclista_nombre or "Registro presencial",
            "bicicleta_id":           bicicleta_id,
            "bicicleta_codigo":       bicicleta_codigo,
            "estacion_inicio_id":     estacion_inicio_id,
            "estacion_inicio_nombre": estacion_inicio_nombre,
            "latitud_inicio":         lat,
            "longitud_inicio":        lng,
            "latitud_actual":         lat,
            "longitud_actual":        lng,
            "estado":                 "activo",
            "fecha_inicio":           _ahora(),
        })
        pb.update_record("bicicletas", bicicleta_id, {"estado": "en_uso"})
        return _flash(request, "/empleado/operacion/alquileres", "success", "Alquiler registrado correctamente.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/alquileres", "error", str(e))


@router.post("/operacion/alquileres/{viaje_id}/cancelar")
async def op_alquileres_cancelar(request: Request, viaje_id: str):
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        pb.update_record("viajes", viaje_id, {"estado": "cancelado", "fecha_fin": _ahora()})
        bici_id = viaje.get("bicicleta_id", "")
        if bici_id:
            pb.update_record("bicicletas", bici_id, {"estado": "disponible"})
        return _flash(request, "/empleado/operacion/alquileres", "success", "Alquiler cancelado.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/alquileres", "error", str(e))


@router.post("/operacion/alquileres/{viaje_id}/completar")
async def op_alquileres_completar(
    request: Request,
    viaje_id: str,
    estacion_fin_id:     str = Form(...),
    estacion_fin_nombre: str = Form(...),
):
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        inicio_str = viaje.get("fecha_inicio", "")
        duracion = 0
        try:
            inicio   = datetime.fromisoformat(inicio_str.replace("Z", "+00:00"))
            duracion = max(1, int((datetime.now(timezone.utc) - inicio).total_seconds() / 60))
        except Exception:
            pass
        pb.update_record("viajes", viaje_id, {
            "estado": "completado", "fecha_fin": _ahora(),
            "estacion_fin_id": estacion_fin_id,
            "duracion_minutos": duracion,
        })
        bici_id = viaje.get("bicicleta_id", "")
        if bici_id:
            pb.update_record("bicicletas", bici_id, {"estado": "disponible", "estacion": estacion_fin_nombre})
        return _flash(request, "/empleado/operacion/alquileres", "success", f"Viaje completado en {estacion_fin_nombre}.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/alquileres", "error", str(e))


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
        destino_nombre = destino.get("nombre", "")

        pb.update_record("bicicletas", bicicleta_id, {"estacion": destino_nombre})

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
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pagos = pb.list_records(
            "pagos",
            filter=f'fecha_pago >= "{hoy} 00:00:00" || estado = "pendiente"',
            sort="-fecha_pago", per_page=300,
        ).get("items", [])
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
        return _flash(request, "/empleado/operacion/pagos", "success", "Recepción de efectivo confirmada.")
    except Exception as e:
        return _flash(request, "/empleado/operacion/pagos", "error", str(e))


# ══════════════════════════════════════════════════════════════════════════════
# MANTENIMIENTO
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


@router.get("/mantenimiento/ordenes", response_class=HTMLResponse)
async def mnt_ordenes(request: Request):
    flash = request.session.pop("flash", None)
    ordenes: list[dict] = []
    bicicletas: list[dict] = []
    filtro = request.query_params.get("estado", "")
    try:
        pb = _pb()
        fil = f'estado = "{filtro}"' if filtro else ""
        ordenes = pb.list_records("ordenes_mant", filter=fil, sort="-fecha_apertura", per_page=200).get("items", [])
        bicicletas = pb.list_records("bicicletas", sort="codigo", per_page=200).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/mantenimiento/ordenes.html", _ctx(request,
        title="Órdenes de Trabajo", flash=flash,
        ordenes=ordenes, bicicletas=bicicletas, filtro=filtro,
    ))


@router.post("/mantenimiento/ordenes/crear")
async def mnt_ordenes_crear(
    request: Request,
    bicicleta_id:     str = Form(...),
    bicicleta_codigo: str = Form(...),
    tipo:             str = Form("correctivo"),
    descripcion:      str = Form(...),
    tecnico_nombre:   str = Form(""),
):
    try:
        _pb().create_record("ordenes_mant", {
            "bicicleta_id":     bicicleta_id,
            "bicicleta_codigo": bicicleta_codigo,
            "tipo":             tipo,
            "descripcion":      descripcion,
            "estado":           "pendiente",
            "tecnico_nombre":   tecnico_nombre,
            "fecha_apertura":   _ahora(),
        })
        # Marcar bicicleta en mantenimiento
        _pb().update_record("bicicletas", bicicleta_id, {"estado": "mantenimiento"})
        return _flash(request, "/empleado/mantenimiento/ordenes", "success", "Orden creada correctamente.")
    except Exception as e:
        return _flash(request, "/empleado/mantenimiento/ordenes", "error", str(e))


@router.post("/mantenimiento/ordenes/{oid}/editar")
async def mnt_ordenes_editar(
    request: Request, oid: str,
    tipo:           str = Form(""),
    descripcion:    str = Form(""),
    estado:         str = Form(""),
    tecnico_nombre: str = Form(""),
):
    try:
        payload: dict = {}
        if tipo:           payload["tipo"]           = tipo
        if descripcion:    payload["descripcion"]    = descripcion
        if tecnico_nombre: payload["tecnico_nombre"] = tecnico_nombre
        if estado:
            payload["estado"] = estado
            if estado == "completado":
                payload["fecha_cierre"] = _ahora()
        _pb().update_record("ordenes_mant", oid, payload)
        return _flash(request, "/empleado/mantenimiento/ordenes", "success", "Orden actualizada.")
    except Exception as e:
        return _flash(request, "/empleado/mantenimiento/ordenes", "error", str(e))


@router.post("/mantenimiento/ordenes/{oid}/eliminar")
async def mnt_ordenes_eliminar(request: Request, oid: str):
    try:
        _pb().delete_record("ordenes_mant", oid)
        return _flash(request, "/empleado/mantenimiento/ordenes", "success", "Orden eliminada.")
    except Exception as e:
        return _flash(request, "/empleado/mantenimiento/ordenes", "error", str(e))


_CHECKLIST_ITEMS = [
    ("frenos",     "Frenos"),
    ("llantas",    "Llantas"),
    ("cadena",     "Cadena"),
    ("luces",      "Luces"),
    ("estructura", "Estructura"),
    ("manubrio",   "Manubrio"),
    ("sillin",     "Sillín"),
]


@router.get("/mantenimiento/inspeccion", response_class=HTMLResponse)
async def mnt_inspeccion(request: Request):
    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    try:
        bicicletas = _pb().list_records("bicicletas", sort="codigo", per_page=500).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/mantenimiento/inspeccion.html", _ctx(request,
        title="Inspección de Bicicletas", flash=flash,
        bicicletas=bicicletas, checklist=_CHECKLIST_ITEMS,
    ))


@router.post("/mantenimiento/inspeccion/registrar")
async def mnt_inspeccion_registrar(request: Request):
    user = getattr(request.state, "user", {})
    form = await request.form()
    bicicleta_id     = form.get("bicicleta_id", "")
    bicicleta_codigo = form.get("bicicleta_codigo", "")
    bateria          = form.get("bateria", "")
    observaciones    = form.get("observaciones", "")

    fallas: list[str] = []
    for clave, etiqueta in _CHECKLIST_ITEMS:
        if form.get(clave) == "mal":
            fallas.append(etiqueta)

    aprobada = len(fallas) == 0

    try:
        pb = _pb()
        if aprobada:
            pb.update_record("bicicletas", bicicleta_id, {"estado": "disponible"})
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "bicicletas",
                f"Inspección aprobada: {bicicleta_codigo} marcada como disponible"
                + (f" (batería: {bateria}%)" if bateria else "")
                + (f" — {observaciones}" if observaciones else ""), request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            return _flash(request, "/empleado/mantenimiento/inspeccion", "success",
                          f"Inspección aprobada. {bicicleta_codigo} está disponible nuevamente.")
        else:
            descripcion = f"Inspección reprobada — fallas detectadas: {', '.join(fallas)}."
            if observaciones:
                descripcion += f" Observaciones: {observaciones}"
            pb.create_record("ordenes_mant", {
                "bicicleta_id":     bicicleta_id,
                "bicicleta_codigo": bicicleta_codigo,
                "tipo":             "correctivo",
                "descripcion":      descripcion,
                "estado":           "pendiente",
                "tecnico_nombre":   "",
                "fecha_apertura":   _ahora(),
            })
            pb.update_record("bicicletas", bicicleta_id, {"estado": "mantenimiento"})
            registrar_auditoria(
                user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
                user.get("email", ""), "crear", "ordenes_mant",
                f"Inspección reprobada: orden de mantenimiento creada para {bicicleta_codigo} ({', '.join(fallas)})", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            return _flash(request, "/empleado/mantenimiento/inspeccion", "info",
                          f"Inspección reprobada. Se generó una orden de mantenimiento para {bicicleta_codigo}.")
    except Exception as e:
        return _flash(request, "/empleado/mantenimiento/inspeccion", "error", str(e))


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


# ══════════════════════════════════════════════════════════════════════════════
# VIGILANCIA
# ══════════════════════════════════════════════════════════════════════════════

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


@router.get("/vigilancia/devoluciones", response_class=HTMLResponse)
async def vig_devoluciones(request: Request):
    flash = request.session.pop("flash", None)
    viajes_activos: list[dict] = []
    estaciones: list[dict] = []
    try:
        pb = _pb()
        viajes_activos = pb.list_records("viajes", filter='estado = "activo"', sort="-fecha_inicio", per_page=200).get("items", [])
        estaciones = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50).get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "empleado/vigilancia/devoluciones.html", _ctx(request,
        title="Registrar Devoluciones", flash=flash,
        viajes=viajes_activos, estaciones=estaciones,
    ))


@router.post("/vigilancia/devolver/{viaje_id}")
async def vig_devolver(
    request: Request,
    viaje_id: str,
    estacion_fin_id:     str = Form(...),
    estacion_fin_nombre: str = Form(...),
    motivo:              str = Form("voluntaria"),
    observaciones:       str = Form(""),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        inicio_str = viaje.get("fecha_inicio", "")
        duracion   = 0
        try:
            inicio   = datetime.fromisoformat(inicio_str.replace("Z", "+00:00"))
            duracion = max(1, int((datetime.now(timezone.utc) - inicio).total_seconds() / 60))
        except Exception:
            pass
        pb.update_record("viajes", viaje_id, {
            "estado":           "completado",
            "estacion_fin_id":  estacion_fin_id,
            "fecha_fin":        _ahora(),
            "duracion_minutos": duracion,
        })
        bici_id = viaje.get("bicicleta_id", "")
        if bici_id:
            pb.update_record("bicicletas", bici_id, {"estado": "disponible", "estacion": estacion_fin_nombre})

        detalle = f"Devolución {motivo} registrada en {estacion_fin_nombre} (duración: {duracion} min)"
        if observaciones:
            detalle += f" — {observaciones}"
        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes", detalle, request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        return _flash(request, "/empleado/vigilancia/devoluciones", "success",
                      f"Devolución {motivo} registrada en {estacion_fin_nombre}. Duración: {duracion} min.")
    except Exception as e:
        return _flash(request, "/empleado/vigilancia/devoluciones", "error", str(e))


_LIMITE_ALERTA_MIN = 120


@router.get("/vigilancia/alertas", response_class=HTMLResponse)
async def vig_alertas(request: Request):
    flash = request.session.pop("flash", None)
    alertas: list[dict] = []
    try:
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


# ══════════════════════════════════════════════════════════════════════════════
# REPORTES
# ══════════════════════════════════════════════════════════════════════════════

_DIAS_SEMANA = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


@router.get("/operacion/reportes", response_class=HTMLResponse)
async def op_reportes(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    viajes: list[dict] = []
    try:
        viajes = _pb().list_records("viajes", sort="-fecha_inicio", per_page=500).get("items", [])
    except Exception:
        pass

    # Pagos confirmados hoy por este empleado
    pagos_turno: list[dict] = []
    total_efectivo_turno = 0.0
    total_transferencia_turno = 0.0
    try:
        hoy = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        pagos_turno = _pb().list_records(
            "pagos",
            filter=f'confirmado_por_empleado_id = "{user.get("id", "")}" && fecha_confirmacion >= "{hoy} 00:00:00"',
            sort="-fecha_confirmacion", per_page=300,
        ).get("items", [])
        total_efectivo_turno = sum(float(p.get("monto_total") or 0) for p in pagos_turno if p.get("metodo_pago") == "efectivo")
        total_transferencia_turno = sum(float(p.get("monto_total") or 0) for p in pagos_turno if p.get("metodo_pago") == "transferencia")
    except Exception:
        pass

    dia_counts = [0] * 7
    bici_counts: dict[str, int] = {}
    for v in viajes:
        try:
            dt = datetime.fromisoformat(v.get("fecha_inicio", "").replace("Z", "+00:00"))
            dia_counts[dt.weekday()] += 1
        except Exception:
            pass
        codigo = v.get("bicicleta_codigo") or "—"
        bici_counts[codigo] = bici_counts.get(codigo, 0) + 1

    top_bicis = sorted(bici_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    bici_labels = [b[0] for b in top_bicis]
    bici_values = [b[1] for b in top_bicis]

    return templates.TemplateResponse(request, "empleado/operacion/reportes.html", _ctx(request,
        title="Reportes — Operación", flash=flash,
        total_alquileres=len(viajes),
        dia_labels=json.dumps(_DIAS_SEMANA), dia_values=json.dumps(dia_counts),
        bici_labels=json.dumps(bici_labels), bici_values=json.dumps(bici_values),
        pagos_turno=pagos_turno,
        total_efectivo_turno=total_efectivo_turno,
        total_transferencia_turno=total_transferencia_turno,
    ))


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
