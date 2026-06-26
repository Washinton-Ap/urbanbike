"""Rutas para el rol Ciclista — reservas, viaje activo, historial."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import settings
from app.db.pocketbase import get_admin_client, registrar_auditoria
from app.templating import templates

router = APIRouter(prefix="/ciclista", tags=["ciclista"])


def _ctx(request: Request, **extra) -> dict:
    return {"user": getattr(request.state, "user", None), **extra}


def _pb():
    import app.db.pocketbase as m
    try:
        return get_admin_client()
    except Exception:
        m._admin_client = None
        return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Los ciclistas registrados en la plataforma se tarifican como "member"
# (la tarifa "casual" es para usuarios sin cuenta, fuera del alcance del sistema).
TIPO_MEMBRESIA = "member"


def _tarifa_hora(pb, tipo_bicicleta: str) -> float:
    try:
        res = pb.list_records(
            "tarifas",
            filter=f'tipo_bicicleta = "{tipo_bicicleta}" && tipo_usuario = "{TIPO_MEMBRESIA}" && activa = true',
            per_page=1,
        )
        items = res.get("items", [])
        if items:
            return float(items[0].get("precio_hora") or 0)
    except Exception:
        pass
    return 0.0


def _viaje_activo(user_id: str) -> dict | None:
    try:
        res = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = "{user_id}" && estado = "activo"',
            per_page=1,
        )
        items = res.get("items", [])
        return items[0] if items else None
    except Exception:
        return None


# ── Dashboard ────────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    flash = request.session.pop("flash", None)
    user = getattr(request.state, "user", {})
    disponibles = 0
    total = 0
    viaje = _viaje_activo(user.get("id", ""))
    try:
        pb = _pb()
        res_disp = pb.list_records("bicicletas", filter='estado = "disponible"', per_page=1)
        disponibles = res_disp.get("totalItems", 0)
        res_all = pb.list_records("bicicletas", per_page=1)
        total = res_all.get("totalItems", 0)
    except Exception:
        pass
    return templates.TemplateResponse(request, "ciclista/dashboard.html", _ctx(request,
        title="Mi Espacio", flash=flash,
        disponibles=disponibles, total_bicicletas=total, viaje_activo=viaje,
    ))


# ── Alquilar ─────────────────────────────────────────────────────────────────

@router.get("/alquilar", response_class=HTMLResponse)
async def alquilar(request: Request):
    user = getattr(request.state, "user", {})
    # Si ya tiene viaje activo → redirigir
    viaje = _viaje_activo(user.get("id", ""))
    if viaje:
        request.session["flash"] = {"type": "info", "msg": "Ya tienes un viaje activo."}
        return RedirectResponse("/ciclista/viaje-activo", status_code=302)

    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    estaciones: list[dict] = []
    tarifas: list[dict] = []
    try:
        pb = _pb()
        res_b = pb.list_records("bicicletas", filter='estado = "disponible"', sort="codigo", per_page=200)
        bicicletas = res_b.get("items", [])
        res_e = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50)
        estaciones = res_e.get("items", [])
        res_t = pb.list_records("tarifas", filter='activa = true', per_page=200)
        tarifas = res_t.get("items", [])
    except Exception:
        pass
    return templates.TemplateResponse(request, "ciclista/alquilar.html", _ctx(request,
        title="Reservar Bicicleta", flash=flash,
        bicicletas=bicicletas, estaciones=estaciones,
        bicicletas_json=json.dumps(bicicletas),
        estaciones_json=json.dumps(estaciones),
        tarifas_json=json.dumps(tarifas),
        pb_url=settings.pb_url,
    ))


@router.post("/reservar")
async def reservar(
    request: Request,
    bicicleta_id:          str = Form(...),
    bicicleta_codigo:      str = Form(...),
    estacion_inicio_id:    str = Form(...),
    estacion_inicio_nombre: str = Form(...),
    latitud:               str = Form("0"),
    longitud:              str = Form("0"),
):
    user = getattr(request.state, "user", {})
    user_id = user.get("id", "")

    # Verificar que no tenga viaje activo
    if _viaje_activo(user_id):
        request.session["flash"] = {"type": "error", "msg": "Ya tienes un viaje activo. Finalízalo primero."}
        return RedirectResponse("/ciclista/viaje-activo", status_code=302)

    # Garantía de pago: bloquear nuevas reservas si tiene pagos pendientes o rechazos repetidos
    try:
        pb_check = _pb()
        pendientes = pb_check.list_records(
            "pagos",
            filter=f'ciclista_id = "{user_id}" && (estado = "pendiente_efectivo" || estado = "verificacion_pendiente")',
            per_page=1,
        )
        if pendientes.get("totalItems", 0) > 0:
            request.session["flash"] = {"type": "error", "msg":
                "Tienes pagos pendientes. Regula tu situación antes de hacer una nueva reserva."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

        rechazados = pb_check.list_records(
            "pagos", filter=f'ciclista_id = "{user_id}" && estado = "rechazado"', per_page=1,
        )
        if rechazados.get("totalItems", 0) > 2:
            request.session["flash"] = {"type": "error", "msg":
                "Tu cuenta ha sido bloqueada temporalmente por pagos rechazados. Contacta a soporte."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)
    except Exception:
        pass

    try:
        pb = _pb()
        lat = float(latitud)
        lng = float(longitud)

        # Crear viaje
        pb.create_record("viajes", {
            "ciclista_id":            user_id,
            "ciclista_nombre":        user.get("name") or user.get("email", ""),
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

        # Marcar bicicleta como en_uso
        pb.update_record("bicicletas", bicicleta_id, {"estado": "en_uso"})

        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Viaje iniciado: {bicicleta_codigo} desde {estacion_inicio_nombre}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        request.session["flash"] = {"type": "success", "msg": f"Viaje iniciado en {estacion_inicio_nombre}. Buen viaje."}
        return RedirectResponse("/ciclista/viaje-activo", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al iniciar viaje: {e}"}
        return RedirectResponse("/ciclista/alquilar", status_code=302)


# ── Viaje activo ─────────────────────────────────────────────────────────────

@router.get("/viaje-activo", response_class=HTMLResponse)
async def viaje_activo(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    viaje = _viaje_activo(user.get("id", ""))
    if not viaje:
        request.session["flash"] = {"type": "info", "msg": "No tienes un viaje activo."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    estaciones: list[dict] = []
    tipo_bicicleta = "classic_bike"
    precio_hora = 0.0
    try:
        pb = _pb()
        res = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50)
        estaciones = res.get("items", [])
        bici = pb.get_record("bicicletas", viaje.get("bicicleta_id", ""))
        tipo_bicicleta = bici.get("tipo") or "classic_bike"
        precio_hora = _tarifa_hora(pb, tipo_bicicleta)
    except Exception:
        pass

    return templates.TemplateResponse(request, "ciclista/viaje_activo.html", _ctx(request,
        title="Viaje Activo", flash=flash, viaje=viaje,
        estaciones=estaciones,
        estaciones_json=json.dumps(estaciones),
        tipo_bicicleta=tipo_bicicleta,
        precio_hora=precio_hora,
    ))


@router.post("/finalizar")
async def finalizar(
    request: Request,
    viaje_id:             str = Form(...),
    estacion_fin_id:      str = Form(...),
    estacion_fin_nombre:  str = Form(...),
):
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)

        # Calcular duración exacta en segundos y minutos (redondeo hacia arriba para el cobro)
        inicio_str = viaje.get("fecha_inicio", "")
        ahora_dt   = datetime.now(timezone.utc)
        ahora_str  = _ahora()
        segundos   = 0
        try:
            inicio   = datetime.fromisoformat(inicio_str.replace("Z", "+00:00"))
            segundos = max(1, int((ahora_dt - inicio).total_seconds()))
        except Exception:
            segundos = 60
        duracion_minutos = max(1, -(-segundos // 60))  # redondeo hacia arriba

        # Determinar tipo de bicicleta y tarifa vigente
        bici_id = viaje.get("bicicleta_id", "")
        tipo_bicicleta = "classic_bike"
        if bici_id:
            try:
                bici = pb.get_record("bicicletas", bici_id)
                tipo_bicicleta = bici.get("tipo") or "classic_bike"
            except Exception:
                pass
        precio_hora = _tarifa_hora(pb, tipo_bicicleta)
        monto_total = round(segundos / 3600 * precio_hora, 2)

        # Actualizar viaje
        pb.update_record("viajes", viaje_id, {
            "estado":              "completado",
            "estacion_fin_id":     estacion_fin_id,
            "fecha_fin":           ahora_str,
            "duracion_minutos":    duracion_minutos,
            "latitud_actual":      viaje.get("latitud_inicio", 0),
            "longitud_actual":     viaje.get("longitud_inicio", 0),
        })

        # Liberar bicicleta
        if bici_id:
            pb.update_record("bicicletas", bici_id, {
                "estado":   "disponible",
                "estacion": estacion_fin_nombre,
            })

        # Crear registro de pago pendiente
        pago = pb.create_record("pagos", {
            "viaje_id":          viaje_id,
            "ciclista_id":       user.get("id", ""),
            "ciclista_nombre":   user.get("name") or user.get("email", ""),
            "duracion_minutos":  duracion_minutos,
            "tipo_bicicleta":    tipo_bicicleta,
            "tipo_membresia":    TIPO_MEMBRESIA,
            "precio_hora":       precio_hora,
            "monto_total":       monto_total,
            "estado":            "pendiente",
            "metodo_pago":       "",
            "fecha_pago":        "",
            "comprobante_numero": "",
        })

        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes",
            f"Viaje finalizado en {estacion_fin_nombre} (duración: {duracion_minutos} min, monto: ${monto_total:.2f})", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        return RedirectResponse(f"/ciclista/pago/{pago['id']}", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al finalizar: {e}"}
        return RedirectResponse("/ciclista/viaje-activo", status_code=302)


# ── Pago ─────────────────────────────────────────────────────────────────────

def _duracion_hms(minutos: int) -> str:
    minutos = max(0, int(minutos))
    h, m = divmod(minutos, 60)
    return f"{h:02d}:{m:02d}:00"


@router.get("/pago/{pago_id}", response_class=HTMLResponse)
async def pago(request: Request, pago_id: str):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    try:
        registro = _pb().get_record("pagos", pago_id)
    except Exception:
        request.session["flash"] = {"type": "error", "msg": "Pago no encontrado."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    if registro.get("ciclista_id") != user.get("id", ""):
        request.session["flash"] = {"type": "error", "msg": "No tienes acceso a ese pago."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    estado_pago = registro.get("estado", "pendiente")
    if estado_pago == "pagado":
        return RedirectResponse(f"/ciclista/comprobante/{pago_id}", status_code=302)

    cuentas: list[dict] = []
    try:
        cuentas = _pb().list_records("cuentas_bancarias", filter="activa = true", sort="banco", per_page=50).get("items", [])
    except Exception:
        pass

    return templates.TemplateResponse(request, "ciclista/pago.html", _ctx(request,
        title="Pagar Viaje", flash=flash, pago=registro,
        estado_pago=estado_pago,
        duracion_hms=_duracion_hms(registro.get("duracion_minutos") or 0),
        cuentas=cuentas,
    ))


def _generar_comprobante(pago_id: str) -> str:
    ahora = datetime.now(timezone.utc)
    return f"UB-{ahora.strftime('%Y%m%d')}-{pago_id[-4:].upper()}"


@router.post("/confirmar-pago")
async def confirmar_pago(
    request: Request,
    pago_id:               str = Form(...),
    metodo_pago:           str = Form(...),
    numero_cuenta_origen:  str = Form(""),
    comprobante_imagen:    UploadFile | None = File(None),
    numero_tarjeta:        str = Form(""),
    nombre_titular:        str = Form(""),
    mes_expiracion:        str = Form(""),
    anio_expiracion:       str = Form(""),
):
    user    = getattr(request.state, "user", {})
    user_id = user.get("id", "")
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("ciclista_id") != user_id:
            request.session["flash"] = {"type": "error", "msg": "No tienes acceso a ese pago."}
            return RedirectResponse("/ciclista/historial", status_code=302)

        if registro.get("estado") == "pagado":
            return RedirectResponse(f"/ciclista/comprobante/{pago_id}", status_code=302)

        comprobante = registro.get("comprobante_numero") or _generar_comprobante(pago_id)
        intento = (registro.get("intento_numero") or 0) + 1

        # ── Efectivo ──────────────────────────────────────────────────────────
        if metodo_pago == "efectivo":
            pb.update_record("pagos", pago_id, {
                "estado":             "pendiente_efectivo",
                "metodo_pago":        "efectivo",
                "comprobante_numero": comprobante,
                "intento_numero":     intento,
            })
            registrar_auditoria(
                user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Pago marcado para efectivo: código {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            request.session["flash"] = {"type": "info", "msg":
                f"Dirígete al empleado de operación más cercano con el código de pago: {comprobante} para completar el pago."}
            return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

        # ── Tarjeta (simulado) ────────────────────────────────────────────────
        if metodo_pago == "tarjeta":
            digitos = "".join(ch for ch in numero_tarjeta if ch.isdigit())
            if len(digitos) < 4 or not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
                request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            ultimos4 = digitos[-4:]
            pb.update_record("pagos", pago_id, {
                "estado":                 "pagado",
                "metodo_pago":            "tarjeta",
                "fecha_pago":             _ahora(),
                "comprobante_numero":     comprobante,
                "numero_tarjeta_ultimos4": ultimos4,
                "intento_numero":         intento,
            })
            registrar_auditoria(
                user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Pago confirmado (tarjeta •••• {ultimos4}): comprobante {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            return RedirectResponse(f"/ciclista/comprobante/{pago_id}", status_code=302)

        # ── Transferencia ─────────────────────────────────────────────────────
        if metodo_pago == "transferencia":
            tiene_archivo = comprobante_imagen is not None and comprobante_imagen.filename
            if not numero_cuenta_origen.strip() or not tiene_archivo:
                request.session["flash"] = {"type": "error", "msg":
                    "Ingresa el número de cuenta de origen y adjunta el comprobante de la transferencia."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if comprobante_imagen.content_type not in ("image/jpeg", "image/png", "application/pdf"):
                request.session["flash"] = {"type": "error", "msg": "El comprobante debe ser JPG, PNG o PDF."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if comprobante_imagen.size and comprobante_imagen.size > 5 * 1024 * 1024:
                request.session["flash"] = {"type": "error", "msg": "El comprobante no debe superar los 5 MB."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

            contenido = await comprobante_imagen.read()
            pb.update_record_with_file("pagos", pago_id, {
                "estado":                "verificacion_pendiente",
                "metodo_pago":           "transferencia",
                "comprobante_numero":    comprobante,
                "numero_cuenta_origen":  numero_cuenta_origen.strip(),
                "intento_numero":        intento,
            }, {"comprobante_imagen": (comprobante_imagen.filename, contenido, comprobante_imagen.content_type)})

            registrar_auditoria(
                user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
                user.get("email", ""), "editar", "pagos",
                f"Comprobante de transferencia subido para verificación: {comprobante}", request,
                usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
            )
            request.session["flash"] = {"type": "info", "msg":
                "Tu pago está en verificación. El empleado de operación lo confirmará en breve."}
            return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

        request.session["flash"] = {"type": "error", "msg": "Método de pago no válido."}
        return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al confirmar el pago: {e}"}
        return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)


@router.get("/comprobante/{pago_id}", response_class=HTMLResponse)
async def comprobante(request: Request, pago_id: str):
    user = getattr(request.state, "user", {})
    try:
        registro = _pb().get_record("pagos", pago_id)
    except Exception:
        request.session["flash"] = {"type": "error", "msg": "Comprobante no encontrado."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    if registro.get("ciclista_id") != user.get("id", ""):
        request.session["flash"] = {"type": "error", "msg": "No tienes acceso a ese comprobante."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    if registro.get("estado") != "pagado":
        return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

    viaje: dict = {}
    try:
        viaje = _pb().get_record("viajes", registro.get("viaje_id", ""))
    except Exception:
        pass

    return templates.TemplateResponse(request, "ciclista/comprobante.html", _ctx(request,
        title="Comprobante de Pago", pago=registro, viaje=viaje,
        duracion_hms=_duracion_hms(registro.get("duracion_minutos") or 0),
    ))


# ── Historial ─────────────────────────────────────────────────────────────────

@router.get("/historial", response_class=HTMLResponse)
async def historial(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    viajes: list[dict] = []
    estaciones_nombres: dict[str, str] = {}
    try:
        pb = _pb()
        res = pb.list_records(
            "viajes",
            filter=f'ciclista_id = "{user.get("id", "")}"',
            sort="-fecha_inicio",
            per_page=100,
        )
        viajes = res.get("items", [])
        estaciones_nombres = {
            e["id"]: e.get("nombre", "")
            for e in pb.list_records("estaciones", per_page=200).get("items", [])
        }
    except Exception:
        pass
    return templates.TemplateResponse(request, "ciclista/historial.html", _ctx(request,
        title="Mis Viajes", flash=flash, viajes=viajes,
        estaciones_nombres=estaciones_nombres,
    ))


@router.get("/perfil", response_class=HTMLResponse)
async def perfil(request: Request):
    return RedirectResponse("/perfil", status_code=302)


# ── Reportes ─────────────────────────────────────────────────────────────────

_MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


@router.get("/reportes", response_class=HTMLResponse)
async def reportes(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    viajes: list[dict] = []
    try:
        viajes = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = "{user.get("id", "")}"',
            sort="-fecha_inicio", per_page=500,
        ).get("items", [])
    except Exception:
        pass

    meses_counts: dict[tuple[int, int], int] = {}
    tiempo_total = 0
    completados = 0
    for v in viajes:
        try:
            dt = datetime.fromisoformat(v.get("fecha_inicio", "").replace("Z", "+00:00"))
            clave = (dt.year, dt.month)
            meses_counts[clave] = meses_counts.get(clave, 0) + 1
        except Exception:
            pass
        dur = v.get("duracion_minutos") or 0
        if dur:
            tiempo_total += dur
            completados += 1

    claves = sorted(meses_counts.keys())
    mes_labels = [f"{_MESES[m - 1]} {y}" for (y, m) in claves]
    mes_values = [meses_counts[c] for c in claves]
    duracion_prom = round(tiempo_total / completados, 1) if completados else 0

    return templates.TemplateResponse(request, "ciclista/reportes.html", _ctx(request,
        title="Mis Reportes", flash=flash,
        total_viajes=len(viajes), completados=completados,
        tiempo_total=tiempo_total, duracion_prom=duracion_prom,
        mes_labels=json.dumps(mes_labels), mes_values=json.dumps(mes_values),
    ))
