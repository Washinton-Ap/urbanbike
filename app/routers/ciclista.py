"""Rutas para el rol Ciclista — reservas, viaje activo, historial."""

import json
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import settings
from app.db import (
    alquileres_repo, codigos_descuento_repo, facturas_repo, infracciones_repo,
    membresias_repo, mensajes_soporte_repo, notificaciones_repo, promociones_repo,
    tarifas_repo, clickhouse as ch,
)
from app.db.pocketbase import filter_literal, get_admin_client, registrar_auditoria
from app.email_client import enviar_notificacion
from app.reportes.comun import ColumnaReporte
from app.reportes.excel import generar_excel_reporte
from app.reportes.factura import DatosFactura, LineaFactura, generar_factura_pdf
from app.reportes.pdf import generar_pdf_reporte
from app.templating import file_url, templates

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


# modelos_bicicleta.tipo_frenos guarda valores tecnicos en snake_case;
# el catalogo muestra una frase que un ciclista sin conocimientos tecnicos
# entienda, no solo el codigo.
_FRENOS_DISPLAY = {
    "disco_hidraulico": "Frenos de disco hidráulicos",
    "disco_mecanico":   "Frenos de disco mecánicos",
    "zapata":           "Frenos de zapata",
    "contrapedal":      "Frenos de contrapedal",
}


def _tarifas_por_categoria() -> dict:
    """Precio por categoria, para member y casual, hora/dia/semana -> permite
    mostrar el precio real del ciclista logueado (member) y, debajo, lo
    que pagaria sin membresia (casual). Se resuelve a 0.0 cuando falta un
    combo puntual, nunca se inventa. Compartida por _catalogo_bicicletas()
    (detalle por bicicleta) y _catalogo_agrupado() (punto 7, catálogo por
    categoría)."""
    tarifas: dict = {}
    try:
        for t in ch.query("""
            SELECT id_categoria, tipo_membresia, modalidad, precio
            FROM urbanbike_operativa.tarifas FINAL
            WHERE modalidad IN ('hora', 'dia', 'semana') AND estado = 'vigente'
              AND today() BETWEEN vigente_desde AND vigente_hasta
        """):
            tarifas.setdefault(t["id_categoria"], {})[
                (t["tipo_membresia"], t["modalidad"])
            ] = float(t["precio"])
    except Exception:
        pass
    return tarifas


DIAS_EXCLUSIVA_NUEVA = 14  # punto 4: "acceso anticipado a bicicletas nuevas"
# -- ventana en días desde bicicletas.fecha_adquisicion (dato real de
# ClickHouse) durante la cual solo un ciclista con membresía activa puede
# reservarla; un ciclista casual la ve en el catálogo pero no puede
# alquilarla hasta que pase la ventana. Número de días: decisión de
# producto (confirmada con Washington), el documento no fija uno.


def _bicicletas_exclusivas_nuevas() -> dict[str, date]:
    """{codigo: fecha_liberacion} de las bicicletas todavía dentro de la
    ventana de acceso anticipado (punto 4) -- fecha_liberacion es
    fecha_adquisicion + DIAS_EXCLUSIVA_NUEVA, para mostrarla en el badge
    ("exclusiva hasta el DD/MM"). Solo existe en ClickHouse (PocketBase no
    tiene fecha_adquisicion, ver el TODO de _catalogo_agrupado() abajo)."""
    try:
        filas = ch.query("""
            SELECT codigo, fecha_adquisicion
            FROM urbanbike_operativa.bicicletas FINAL
            WHERE dateDiff('day', fecha_adquisicion, today()) < %(dias)s
        """, {"dias": DIAS_EXCLUSIVA_NUEVA})
        return {
            f["codigo"]: f["fecha_adquisicion"] + timedelta(days=DIAS_EXCLUSIVA_NUEVA)
            for f in filas
        }
    except Exception:
        return {}


# TODO(desfase ClickHouse/PocketBase en disponibilidad -- ver TODO.md raíz):
# el `b.estado` que lee esta función (y _catalogo_bicicletas() abajo) viene
# de urbanbike_operativa.bicicletas en ClickHouse, pero reservar()/
# finalizar() de este mismo archivo -- y vig_devolver() en empleado.py --
# escriben el estado real de la bicicleta SOLO en PocketBase. El espejo
# entre ambas bases (bicicletas_repo.py:_espejar_pocketbase) es
# unidireccional ClickHouse -> PocketBase, nunca al revés (ver su
# docstring), así que un alquiler hecho por un ciclista no se refleja acá
# hasta que alguien edite esa bicicleta desde Admin/Gerente. Reproducido
# 16-ago-2026 al construir el catálogo del punto 7: reservar una bici como
# ciclista y esta pantalla la siguió mostrando "disponible". No se corrige
# ahora -- requiere decidir si se espeja también en sentido inverso o se
# migra el flujo de reserva del ciclista a ClickHouse (la migración ya
# estaba pendiente de antes, ver bicicletas_repo.py).
def _catalogo_agrupado(tipo_membresia: str = "casual") -> list[dict]:
    """Catálogo visible al ciclista (punto 7, "el producto del sistema"):
    bicicletas agrupadas por categoría con disponibilidad EN VIVO (cuántas
    hay disponibles ahora mismo, dato real de ClickHouse) y la tarifa por
    hora de esa categoría -- a diferencia de _catalogo_bicicletas() (una
    fila por bicicleta individual, usada en el wizard de alquiler), esto
    es la vista de "producto" agrupada que pide el punto 7."""
    filas = []
    try:
        filas = ch.query("""
            SELECT c.id AS id_categoria, c.nombre AS nombre, c.descripcion AS descripcion,
                   c.es_premium AS es_premium, c.orden AS orden,
                   count() AS total,
                   countIf(b.estado = 'disponible') AS disponibles,
                   countIf(b.estado = 'disponible'
                           AND dateDiff('day', b.fecha_adquisicion, today()) < %(dias)s) AS disponibles_exclusivas
            FROM urbanbike_operativa.bicicletas AS b FINAL
            INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
            INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
            WHERE c.activa = 1
            GROUP BY c.id, c.nombre, c.descripcion, c.es_premium, c.orden
            ORDER BY c.orden
        """, {"dias": DIAS_EXCLUSIVA_NUEVA})
    except Exception:
        return []

    es_member = tipo_membresia == "member"
    tarifas_por_categoria = _tarifas_por_categoria()
    catalogo = []
    for f in filas:
        tarifas_cat = tarifas_por_categoria.get(f["id_categoria"], {})
        # Punto 4: un ciclista casual no puede contar como "disponible" una
        # bicicleta que todavía está en su ventana de acceso anticipado
        # para miembros -- para él, esas unidades no son reservables hoy.
        disponibles_viewer = f["disponibles"] if es_member else f["disponibles"] - f["disponibles_exclusivas"]
        catalogo.append({
            "nombre": f["nombre"], "descripcion": f["descripcion"],
            "es_premium": bool(f["es_premium"]),
            "total": f["total"], "disponibles": disponibles_viewer,
            "exclusivas_member": f["disponibles_exclusivas"],
            "precio_hora_member": tarifas_cat.get((tipo_membresia, "hora"), 0.0),
            "precio_hora_casual": tarifas_cat.get(("casual", "hora"), 0.0),
        })
    return catalogo


def _catalogo_bicicletas(pb, bicicletas_pb: list[dict], tipo_membresia: str = "casual") -> list[dict]:
    """Catalogo real para tarjeta_bicicleta.html: bicicletas + modelo + marca +
    categoria de urbanbike_operativa, con el precio por dia de `tarifas`.

    El campo `estado` de acá tiene el mismo desfase con PocketBase que
    _catalogo_agrupado() de arriba -- ver el TODO en esa función y TODO.md.

    `bicicletas_pb` debe ser TODAS las bicicletas de PocketBase (sin filtro
    de estado): se usa solo para resolver el id real por codigo y armar
    detalle_url, no para decidir disponibilidad (eso ya viene de
    ClickHouse en el campo `estado` de cada fila).

    bicicleta_fotos (ClickHouse) todavia esta vacia. La foto real de
    cada bicicleta vive hoy en PocketBase (bicicletas.foto, el mismo
    campo que ya usa bicicleta_detalle()) -- se usa como respaldo aqui
    tambien. El componente dibuja la marca de agua solo cuando ninguna
    de las dos fuentes tiene nada.

    `tipo_membresia` ("member"/"casual") ya viene resuelto por el
    llamador via membresias_repo.tipo_membresia_real() -- ya NO es
    automatico por estar logueado como ciclista, depende de si su
    membresia esta activa hoy (ver docs/HOJA_DE_RUTA.md).
    """
    filas = ch.query("""
        SELECT b.id AS id_bicicleta, b.codigo AS codigo, b.estado AS estado,
               mar.nombre AS marca, m.nombre AS modelo,
               c.nombre AS categoria, c.es_premium AS es_premium, c.id AS id_categoria,
               m.enfoque AS enfoque, m.marchas AS marchas, m.tipo_frenos AS tipo_frenos,
               m.material_cuadro AS material_cuadro, m.suspension AS suspension,
               m.rodado AS rodado, m.peso_kg AS peso_kg,
               m.es_electrica AS es_electrica, m.autonomia_km AS autonomia_km
        FROM urbanbike_operativa.bicicletas AS b FINAL
        INNER JOIN urbanbike_operativa.modelos_bicicleta AS m FINAL ON m.id = b.id_modelo
        INNER JOIN urbanbike_operativa.marcas AS mar FINAL ON mar.id = m.id_marca
        INNER JOIN urbanbike_operativa.categorias AS c FINAL ON c.id = m.id_categoria
        ORDER BY c.orden, mar.nombre, b.codigo
    """)

    tarifas_por_categoria = _tarifas_por_categoria()

    # Promociones reales vigentes hoy (activa + dentro de fecha + dia de la
    # semana correcto). El descuento solo se aplica al precio member -- es
    # el precio que realmente va a pagar el ciclista logueado; el precio
    # casual de comparacion se deja intacto (ver docs/HOJA_DE_RUTA.md).
    promos_activas: list = []
    try:
        promos_activas = promociones_repo.activas_hoy()
    except Exception:
        pass

    # codigo -> registro de PocketBase, para el id real ("Alquilar esta
    # bicicleta" lleva al detalle correcto, el id de ClickHouse es otro
    # espacio de ids) y para la foto real (bicicletas.foto).
    pb_por_codigo = {b.get("codigo"): b for b in bicicletas_pb}

    exclusivas_nuevas = _bicicletas_exclusivas_nuevas()  # punto 4: acceso anticipado
    es_member_viewer = tipo_membresia == "member"

    catalogo = []
    for f in filas:
        codigo = f["codigo"]
        pb_bici = pb_por_codigo.get(codigo) or {}
        pb_id = pb_bici.get("id")
        foto_url = file_url("bicicletas", pb_id, pb_bici.get("foto", ""), "400x300") if pb_id else ""
        # modelos_bicicleta.nombre ya incluye la marca ("Trek FX 3 Disc");
        # tarjeta_bicicleta.html arma "{{ marca }} {{ modelo }}", así que aquí
        # se pasa el modelo sin el prefijo de marca para no duplicarla.
        prefijo = f["marca"] + " "
        modelo = f["modelo"][len(prefijo):] if f["modelo"].startswith(prefijo) else f["modelo"]
        tarifas_cat = tarifas_por_categoria.get(f["id_categoria"], {})
        precio_hora_base = tarifas_cat.get((tipo_membresia, "hora"), 0.0)
        precio_dia_base = tarifas_cat.get((tipo_membresia, "dia"), 0.0)
        precio_semana_base = tarifas_cat.get((tipo_membresia, "semana"), 0.0)

        es_member = tipo_membresia == "member"
        promo_hora, precio_hora_member = promociones_repo.promo_aplicable(
            promos_activas, id_categoria=f["id_categoria"], id_bicicleta=f["id_bicicleta"],
            modalidad="hora", precio=precio_hora_base, es_member=es_member,
        )
        promo_dia, precio_dia_member = promociones_repo.promo_aplicable(
            promos_activas, id_categoria=f["id_categoria"], id_bicicleta=f["id_bicicleta"],
            modalidad="dia", precio=precio_dia_base, es_member=es_member,
        )
        promo_semana, precio_semana_member = promociones_repo.promo_aplicable(
            promos_activas, id_categoria=f["id_categoria"], id_bicicleta=f["id_bicicleta"],
            modalidad="semana", precio=precio_semana_base, es_member=es_member,
        )

        catalogo.append({
            "codigo": codigo,
            "marca": f["marca"], "modelo": modelo, "categoria": f["categoria"],
            "es_premium": bool(f["es_premium"]), "enfoque": f["enfoque"],
            "marchas": f["marchas"],
            "frenos": _FRENOS_DISPLAY.get(f["tipo_frenos"], f["tipo_frenos"]),
            "material_cuadro": f["material_cuadro"], "suspension": f["suspension"],
            "rodado": f"R{f['rodado']}", "peso_kg": float(f["peso_kg"]),
            "es_electrica": bool(f["es_electrica"]), "autonomia_km": f["autonomia_km"],
            "estado": f["estado"],
            "precio_hora_member": precio_hora_member,
            "precio_dia_member":  precio_dia_member,
            "precio_semana_member": precio_semana_member,
            "precio_hora_casual": tarifas_cat.get(("casual", "hora"), 0.0),
            "precio_dia_casual":  tarifas_cat.get(("casual", "dia"), 0.0),
            "precio_semana_casual": tarifas_cat.get(("casual", "semana"), 0.0),
            # Precio original (sin promo) y datos de la promo aplicada, solo
            # presentes cuando de verdad hay un descuento activo -- para no
            # bajar el precio en silencio sin que el ciclista sepa por que.
            "precio_hora_sin_promo": precio_hora_base if promo_hora else None,
            "precio_dia_sin_promo": precio_dia_base if promo_dia else None,
            "precio_semana_sin_promo": precio_semana_base if promo_semana else None,
            # Ahorro real en dolares (precio original - precio final), solo
            # presente junto con su promo -- nunca "Ahorras $0" cuando no
            # hay ningun descuento aplicado.
            "ahorro_hora": round(precio_hora_base - precio_hora_member, 2) if promo_hora else None,
            "ahorro_dia": round(precio_dia_base - precio_dia_member, 2) if promo_dia else None,
            "ahorro_semana": round(precio_semana_base - precio_semana_member, 2) if promo_semana else None,
            "promo_hora": {"codigo": promo_hora["codigo"], "nombre": promo_hora["nombre"]} if promo_hora else None,
            "promo_dia": {"codigo": promo_dia["codigo"], "nombre": promo_dia["nombre"]} if promo_dia else None,
            "promo_semana": {"codigo": promo_semana["codigo"], "nombre": promo_semana["nombre"]} if promo_semana else None,
            "foto_url": foto_url,
            "detalle_url": f"/ciclista/bicicleta/{pb_id}" if pb_id else None,
            # Punto 4: acceso anticipado -- exclusiva_hasta viene solo si
            # está dentro de la ventana; bloqueada_exclusiva es lo que de
            # verdad usa la plantilla para deshabilitar "Alquilar".
            "exclusiva_hasta": exclusivas_nuevas.get(codigo),
            "bloqueada_exclusiva": codigo in exclusivas_nuevas and not es_member_viewer,
        })
    return catalogo


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


MAX_VIAJES_ACTIVOS = 4  # tope de bicicletas alquiladas a la vez por ciclista,
# ver docs/Requerimientos_Mejoras_UrbanBike.md punto 3 ("puede tener más de
# una bicicleta alquilada simultáneamente") -- el documento no fija un
# número, 4 es una decisión de producto (confirmada con Washington) para
# que un solo ciclista no acapare la flota.


def _viajes_activos(user_id: str) -> list[dict]:
    """Todos los viajes 'activo' (en curso) o 'pendiente_validacion' (el
    ciclista ya reportó la devolución, Vigilancia todavía no la confirmó)
    de un ciclista -- puede haber más de uno a la vez (hasta
    MAX_VIAJES_ACTIVOS), ver punto 3 del documento de requerimientos."""
    try:
        res = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = {filter_literal(user_id)} && '
                    '(estado = "activo" || estado = "pendiente_validacion")',
            sort="-fecha_inicio",
            per_page=MAX_VIAJES_ACTIVOS + 5,  # margen: nunca debería superarse, pero no trunca en silencio si un dato viejo lo hace
        )
        return res.get("items", [])
    except Exception:
        return []


def _viaje_activo(user_id: str) -> dict | None:
    """Un solo viaje activo cualquiera -- para los lugares que solo
    necesitan saber "¿tiene *algo* pendiente?" (ver _viajes_activos() para
    la lista completa, usada donde puede haber varios a la vez)."""
    items = _viajes_activos(user_id)
    return items[0] if items else None


def _pagos_pendientes(user_id: str) -> list[dict]:
    """Pagos de viajes ya 'completado' (Vigilancia confirmó la entrega)
    que todavía no están 'pagado' -- el paso "Pago" del flujo del punto 3
    en el dashboard. No incluye 'cancelado' (sin acción posible/pendiente
    para el ciclista, ver docs/HOJA_DE_RUTA.md sobre este estado)."""
    if not user_id:
        return []
    try:
        return _pb().list_records(
            "pagos",
            filter=f'ciclista_id = {filter_literal(user_id)} && '
                    'estado != "pagado" && estado != "cancelado"',
            sort="-fecha_generado",
            per_page=MAX_VIAJES_ACTIVOS + 5,
        ).get("items", [])
    except Exception:
        return []


def _infracciones_activas(user_id: str) -> int:
    try:
        res = _pb().list_records(
            "infracciones",
            filter=f'ciclista_id = {filter_literal(user_id)} && resuelta = false',
            per_page=1,
        )
        return res.get("totalItems", 0)
    except Exception:
        return 0


_UMBRAL_RECURRENTE = 5  # viajes completados en los ultimos 30 dias para el 20% en vez de 10%, ver finalizar()
_VENTANA_CLIENTE_FRECUENTE_DIAS = 30  # punto 0.2, redefinicion del 20-ago-2026 -- antes era "todo el historial"


def _viajes_completados_ultimos_30_dias(user_id: str) -> int:
    """Cuenta viajes 'completado' cuyo fecha_fin cae dentro de los
    ultimos _VENTANA_CLIENTE_FRECUENTE_DIAS dias. Redefinicion del punto
    0.2 (20-ago-2026): antes contaba TODO el historial sin ventana de
    tiempo -- ver docs/HOJA_DE_RUTA.md, decision explicita de Washington
    tras encontrar que este mecanismo ya cubria (con otro criterio) lo
    que 0.2 pedia como "cliente frecuente"."""
    try:
        hace_30_dias = (datetime.now(timezone.utc) - timedelta(days=_VENTANA_CLIENTE_FRECUENTE_DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = {filter_literal(user_id)} && estado = "completado" && '
                    f'fecha_fin >= {filter_literal(hace_30_dias)}',
            per_page=1,
        )
        return res.get("totalItems", 0)
    except Exception:
        return 0


# ── Dashboard ────────────────────────────────────────────────────────────────

def _tarjetas_pendientes(user_id: str) -> list[dict]:
    """Arma las tarjetas del flujo paso a paso del dashboard (punto 3):
    "reservado/en curso" y "devolución reportada" vienen de los viajes
    activos; "pago" viene de los pagos ya generados que todavía no están
    aprobados -- son dos consultas distintas porque un viaje recién deja
    de estar 'activo'/'pendiente_validacion' justo cuando se genera su
    pago (ver vig_devolver() en empleado.py), así que nunca se superponen.
    `paso` es el índice (1-4) resaltado en componentes/pasos_viaje.html."""
    tarjetas = []
    for v in _viajes_activos(user_id):
        paso = 2 if v.get("estado") == "pendiente_validacion" else 1
        tarjetas.append({
            "tipo": "viaje", "viaje": v, "paso": paso,
            "enlace": f"/ciclista/viaje-activo/{v['id']}",
            "titulo": f"{v.get('bicicleta_codigo', '—')} · desde {v.get('estacion_inicio_nombre') or '—'}",
        })
    for p in _pagos_pendientes(user_id):
        tarjetas.append({
            "tipo": "pago", "pago": p, "paso": 3,
            "enlace": f"/ciclista/pago/{p['id']}",
            "titulo": f"Pago pendiente · ${float(p.get('monto_total') or 0):.2f}",
        })
    return tarjetas


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    flash = request.session.pop("flash", None)
    user = getattr(request.state, "user", {})
    disponibles = 0
    total = 0
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
        disponibles=disponibles, total_bicicletas=total,
        tarjetas_pendientes=_tarjetas_pendientes(user.get("id", "")),
    ))


# ── Catálogo (punto 7 de docs/Requerimientos_Mejoras_UrbanBike.md) ─────────────

@router.get("/catalogo", response_class=HTMLResponse)
async def catalogo(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    tipo_membresia = "casual"
    try:
        tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))
    except Exception:
        pass
    return templates.TemplateResponse(request, "ciclista/catalogo.html", _ctx(request,
        title="Catálogo de Bicicletas", flash=flash,
        categorias=_catalogo_agrupado(tipo_membresia),
        es_member=(tipo_membresia == "member"),
    ))


# ── Alquilar ─────────────────────────────────────────────────────────────────

@router.get("/alquilar", response_class=HTMLResponse)
async def alquilar(request: Request):
    user = getattr(request.state, "user", {})
    # Un ciclista puede tener varios viajes activos a la vez (punto 3) --
    # solo se bloquea al llegar al tope, no ante el primer viaje activo.
    viajes_activos = _viajes_activos(user.get("id", ""))
    if len(viajes_activos) >= MAX_VIAJES_ACTIVOS:
        request.session["flash"] = {"type": "info", "msg":
            f"Ya tienes el máximo de bicicletas alquiladas a la vez ({MAX_VIAJES_ACTIVOS})."}
        return RedirectResponse(f"/ciclista/viaje-activo/{viajes_activos[0]['id']}", status_code=302)

    flash = request.session.pop("flash", None)
    bicicletas: list[dict] = []
    todas_bicicletas_pb: list[dict] = []
    estaciones: list[dict] = []
    try:
        pb = _pb()
        res_b = pb.list_records("bicicletas", filter='estado = "disponible"', sort="codigo", per_page=200)
        bicicletas = res_b.get("items", [])
        # Normaliza espacios en el nombre de estación para que coincida de forma
        # confiable con el nombre de las estaciones al comparar en el mapa.
        for b in bicicletas:
            b["estacion"] = (b.get("estacion") or "").strip()
        # Sin filtro de estado: el catálogo necesita el id de PocketBase de
        # TODAS las bicicletas reales (incluidas las en mantenimiento) para
        # que "Alquilar esta bicicleta" siempre tenga destino. La
        # disponibilidad se sigue mostrando aparte (badge de estado en la
        # tarjeta, aviso en el detalle), esto solo resuelve el enlace.
        res_todas = pb.list_records("bicicletas", sort="codigo", per_page=200)
        todas_bicicletas_pb = res_todas.get("items", [])
        res_e = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50)
        estaciones = res_e.get("items", [])
        for e in estaciones:
            e["nombre"] = (e.get("nombre") or "").strip()
    except Exception:
        pass

    try:
        tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))
        catalogo_bicicletas = _catalogo_bicicletas(pb, todas_bicicletas_pb, tipo_membresia)
        # El catalogo (esta pantalla) solo debe ofrecer lo que de verdad se
        # puede alquilar ahora mismo -- la ficha de detalle (bicicleta_detalle
        # mas abajo) sigue sin filtrar, sigue accesible por enlace directo.
        catalogo_bicicletas = [b for b in catalogo_bicicletas if b["estado"] == "disponible"]
    except Exception:
        catalogo_bicicletas = []

    return templates.TemplateResponse(request, "ciclista/alquilar.html", _ctx(request,
        title="Reservar Bicicleta", flash=flash,
        bicicletas=bicicletas, estaciones=estaciones,
        bicicletas_json=json.dumps(bicicletas),
        estaciones_json=json.dumps(estaciones),
        pb_url=settings.pb_url,
        catalogo_bicicletas=catalogo_bicicletas,
    ))


def _crear_viaje(
    pb, user: dict, user_id: str, bicicleta_id: str, bicicleta_codigo: str,
    estacion_inicio_id: str, estacion_inicio_nombre: str, modalidad: str,
    lat: float, lng: float, codigo_valido: dict | None, grupo_reserva_id: str = "",
) -> dict:
    """Crea UN viaje real + marca la bicicleta en_uso -- la auditoria la
    registra cada LLAMADOR (reservar()/reservar_grupo()), no esta funcion.
    Logica compartida entre reservar() (una bicicleta) y reservar_grupo()
    (varias a la vez, Tarea C2 del plan de factura unica). El codigo de
    descuento, si viene, solo se marca usado por el LLAMADOR (una sola vez
    por reserva, nunca una vez por bicicleta del grupo)."""
    nuevo_viaje = pb.create_record("viajes", {
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
        "descuento_codigo":       codigo_valido["codigo"] if codigo_valido else "",
        "descuento_porcentaje":   codigo_valido["porcentaje"] if codigo_valido else 0,
        "modalidad_actual":       modalidad,
        "inicio_segmento_actual": _ahora(),
        "grupo_reserva_id":       grupo_reserva_id,
    })
    pb.update_record("bicicletas", bicicleta_id, {"estado": "en_uso"})
    return nuevo_viaje


def _validar_reserva_comun(user: dict, user_id: str, bicicleta_codigos: list[str]) -> str | None:
    """Reglas de negocio compartidas entre reservar() (una bicicleta) y
    reservar_grupo() (varias a la vez) -- ronda de fix dedicada tras el
    hallazgo real de la 3a revisión independiente de la Task C5 (las dos
    funciones traían ~50 líneas de esta validación duplicadas, con
    riesgo real de que una regla cambiada en una no se replicara en la
    otra). Deja fuera la validación de modalidad y el tope
    MAX_VIAJES_ACTIVOS a propósito -- cada llamador ya los revisa antes
    de llegar acá, en el mismo orden relativo de siempre (modalidad,
    tope, y recién después esto). Devuelve el mensaje de error real si
    algo bloquea la reserva (bicicleta exclusiva de suscriptor,
    infracción activa, pago pendiente o cuenta bloqueada por rechazos
    repetidos), o None si no hay ningún bloqueo -- no toca la sesión ni
    redirige, eso lo hace el llamador."""
    exclusivas_nuevas = _bicicletas_exclusivas_nuevas()
    if any(codigo in exclusivas_nuevas for codigo in bicicleta_codigos):
        tipo_membresia_actual = membresias_repo.tipo_membresia_real(user.get("email", ""))
        if tipo_membresia_actual != "member":
            for codigo in bicicleta_codigos:
                if codigo in exclusivas_nuevas:
                    fecha_liberacion = exclusivas_nuevas[codigo].strftime("%d/%m/%Y")
                    return (f"{codigo} es una bicicleta nueva con acceso anticipado exclusivo para "
                            f"suscriptores hasta el {fecha_liberacion}.")

    if _infracciones_activas(user_id) > 0:
        return "Tienes infracciones pendientes de resolución. No puedes reservar hasta que sean resueltas."

    try:
        pb_check = _pb()
        pendientes = pb_check.list_records(
            "pagos",
            filter=f'ciclista_id = {filter_literal(user_id)} && (estado = "pendiente_efectivo" || estado = "verificacion_pendiente")',
            per_page=1,
        )
        if pendientes.get("totalItems", 0) > 0:
            return "Tienes pagos pendientes. Regula tu situación antes de hacer una nueva reserva."

        rechazados = pb_check.list_records(
            "pagos", filter=f'ciclista_id = {filter_literal(user_id)} && estado = "rechazado"', per_page=1,
        )
        if rechazados.get("totalItems", 0) > 2:
            return "Tu cuenta ha sido bloqueada temporalmente por pagos rechazados. Contacta a soporte."
    except Exception:
        pass

    return None


@router.post("/reservar")
async def reservar(
    request: Request,
    bicicleta_id:          str = Form(...),
    bicicleta_codigo:      str = Form(...),
    estacion_inicio_id:    str = Form(...),
    estacion_inicio_nombre: str = Form(...),
    modalidad:              str = Form("hora"),
    latitud:               str = Form("0"),
    longitud:              str = Form("0"),
    codigo_descuento:      str = Form(""),
):
    user = getattr(request.state, "user", {})
    user_id = user.get("id", "")

    if modalidad not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    # Tope de bicicletas alquiladas a la vez (punto 3) -- ya no bloquea con
    # un solo viaje activo, un ciclista puede tener varios simultáneos.
    viajes_activos_actuales = _viajes_activos(user_id)
    if len(viajes_activos_actuales) >= MAX_VIAJES_ACTIVOS:
        request.session["flash"] = {"type": "error", "msg":
            f"Ya tienes el máximo de bicicletas alquiladas a la vez ({MAX_VIAJES_ACTIVOS})."}
        return RedirectResponse(f"/ciclista/viaje-activo/{viajes_activos_actuales[0]['id']}", status_code=302)

    # Punto 4/infracciones/garantía de pago -- reglas compartidas con
    # reservar_grupo(), ver _validar_reserva_comun().
    error_comun = _validar_reserva_comun(user, user_id, [bicicleta_codigo])
    if error_comun:
        request.session["flash"] = {"type": "error", "msg": error_comun}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    # Codigo de descuento personal (punto 13): se valida ANTES de crear el
    # viaje -- un codigo invalido/ajeno/usado corta aca, sin dejar un viaje
    # a medias. Se marca usado recien despues de que el viaje se creo de
    # verdad (ver mas abajo), nunca antes.
    codigo_valido = None
    if codigo_descuento.strip():
        codigo_valido = codigos_descuento_repo.obtener_valido(codigo_descuento, user_id)
        if not codigo_valido:
            request.session["flash"] = {"type": "error", "msg":
                "El código de descuento no es válido, ya fue usado, o no te pertenece."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

    try:
        pb = _pb()
        lat = float(latitud)
        lng = float(longitud)

        nuevo_viaje = _crear_viaje(
            pb, user, user_id, bicicleta_id, bicicleta_codigo,
            estacion_inicio_id, estacion_inicio_nombre, modalidad, lat, lng, codigo_valido,
        )
        if codigo_valido:
            codigos_descuento_repo.marcar_usado(codigo_valido["id"], nuevo_viaje["id"])

        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Viaje iniciado: {bicicleta_codigo} desde {estacion_inicio_nombre}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        notificaciones_repo.notificar_usuario(
            pb, user_id, tipo="viaje_iniciado",
            titulo="Viaje iniciado",
            mensaje=f"Iniciaste un viaje con la bicicleta {bicicleta_codigo} desde {estacion_inicio_nombre}.",
            enlace=f"/ciclista/viaje-activo/{nuevo_viaje['id']}",
        )

        request.session["flash"] = {"type": "success", "msg": f"Viaje iniciado en {estacion_inicio_nombre}. Buen viaje."}
        return RedirectResponse(f"/ciclista/viaje-activo/{nuevo_viaje['id']}", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al iniciar viaje: {e}"}
        return RedirectResponse("/ciclista/alquilar", status_code=302)


def _revertir_reserva_grupal(pb, grupo_reserva_id: str, user_id: str) -> None:
    """Deshace TODO lo que un intento fallido de reservar_grupo() ya haya
    escrito para este request (Tarea C2, ronda de fix 1 -- hallazgo real
    de revision: sin esto, un fallo a mitad del lote -- ej. un
    bicicleta_id invalido, o un error transitorio de PocketBase -- dejaba
    viajes 'activo' huerfanos, bicicletas atascadas en 'en_uso' y cero
    rastro en auditoria).

    Busca por grupo_reserva_id (unico por request, generado ANTES del
    primer create_record) en vez de confiar en una lista local en
    memoria: _crear_viaje() puede crear la fila de 'viajes' y fallar
    DESPUES, al marcar la bicicleta en_uso (ej. bicicleta_id que no
    existe) -- en ese caso el llamador nunca llega a registrar ese viaje
    puntual en su propia lista, pero la fila ya quedo escrita con este
    grupo_reserva_id, así que SI aparece en esta busqueda. Best-effort en
    cada paso (no se corta en el primer error) para revertir lo maximo
    posible aunque algo de esto tambien falle.

    La limpieza de notificaciones de abajo es defensiva por las dudas --
    desde la ronda de fix dedicada tras el hallazgo real de la 3a
    revision de la Task C5, reservar_grupo() ya NO manda la notificacion
    (ni el correo real que dispara notificar_usuario()) hasta que el
    grupo entero esta confirmado, asi que en el camino normal esta
    funcion nunca deberia encontrar ninguna que borrar."""
    try:
        creados = pb.list_records(
            "viajes", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        creados = []

    for viaje in creados:
        viaje_id = viaje.get("id", "")
        bicicleta_id = viaje.get("bicicleta_id", "")
        try:
            notifs = pb.list_records(
                "notificaciones",
                filter=f'usuario_id = {filter_literal(user_id)} && tipo = "viaje_iniciado" '
                       f'&& enlace = {filter_literal(f"/ciclista/viaje-activo/{viaje_id}")}',
                per_page=5,
            ).get("items", [])
            for notif in notifs:
                try:
                    pb.delete_record("notificaciones", notif["id"])
                except Exception:
                    pass
        except Exception:
            pass
        if bicicleta_id:
            try:
                pb.update_record("bicicletas", bicicleta_id, {"estado": "disponible"})
            except Exception:
                pass
        try:
            pb.delete_record("viajes", viaje_id)
        except Exception:
            pass


@router.post("/reservar-grupo")
async def reservar_grupo(
    request: Request,
    bicicleta_ids:          list[str] = Form(...),
    bicicleta_codigos:      list[str] = Form(...),
    estaciones_ids:         list[str] = Form(...),
    estaciones_nombres:     list[str] = Form(...),
    latitudes:              list[str] = Form(...),
    longitudes:             list[str] = Form(...),
    modalidad:              str = Form("hora"),
    codigo_descuento:       str = Form(""),
):
    """Reserva de varias bicicletas en una sola accion (punto 0.3): crea N
    viajes reales, todos con el mismo grupo_reserva_id, todo-o-nada -- si
    cualquier validacion falla para cualquier bicicleta del lote, no se
    crea ninguno (mismo criterio que el codigo de descuento en reservar():
    "sin dejar un viaje a medias"). El codigo de descuento, si viene, se
    aplica y se marca usado en el PRIMER viaje del grupo unicamente (es de
    un solo uso, no tiene sentido duplicarlo N veces)."""
    user = getattr(request.state, "user", {})
    user_id = user.get("id", "")

    n = len(bicicleta_ids)
    if n < 2:
        request.session["flash"] = {"type": "error", "msg": "Selecciona al menos 2 bicicletas para una reserva grupal."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
    if not (len(bicicleta_codigos) == len(estaciones_ids) == len(estaciones_nombres) == len(latitudes) == len(longitudes) == n):
        request.session["flash"] = {"type": "error", "msg": "Datos de la reserva grupal incompletos."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
    if len(set(bicicleta_ids)) != n:
        request.session["flash"] = {"type": "error", "msg":
            "No puedes reservar la misma bicicleta más de una vez en el mismo grupo."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    if modalidad not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    viajes_activos_actuales = _viajes_activos(user_id)
    if len(viajes_activos_actuales) + n > MAX_VIAJES_ACTIVOS:
        request.session["flash"] = {"type": "error", "msg":
            f"No puedes tener más de {MAX_VIAJES_ACTIVOS} bicicletas alquiladas a la vez "
            f"(ya tienes {len(viajes_activos_actuales)}, intentas agregar {n})."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    # Punto 4/infracciones/garantía de pago -- reglas compartidas con
    # reservar(), ver _validar_reserva_comun().
    error_comun = _validar_reserva_comun(user, user_id, bicicleta_codigos)
    if error_comun:
        request.session["flash"] = {"type": "error", "msg": error_comun}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    codigo_valido = None
    if codigo_descuento.strip():
        codigo_valido = codigos_descuento_repo.obtener_valido(codigo_descuento, user_id)
        if not codigo_valido:
            request.session["flash"] = {"type": "error", "msg":
                "El código de descuento no es válido, ya fue usado, o no te pertenece."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

    grupo_reserva_id = uuid.uuid4().hex
    pb = None
    viajes_creados: list[dict] = []
    try:
        pb = _pb()
        for i in range(n):
            viaje = _crear_viaje(
                pb, user, user_id, bicicleta_ids[i], bicicleta_codigos[i],
                estaciones_ids[i], estaciones_nombres[i], modalidad,
                float(latitudes[i]), float(longitudes[i]),
                codigo_valido if i == 0 else None,
                grupo_reserva_id=grupo_reserva_id,
            )
            viajes_creados.append(viaje)

        if codigo_valido:
            codigos_descuento_repo.marcar_usado(codigo_valido["id"], viajes_creados[0]["id"])

        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Reserva grupal de {n} bicicletas iniciada: {', '.join(bicicleta_codigos)} "
            f"(grupo {grupo_reserva_id})", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        # Notificaciones (con correo real, ver notificaciones_repo.notificar_usuario())
        # recién ACA, con el grupo entero ya confirmado -- ronda de fix
        # dedicada tras el hallazgo real de la 3a revisión de la Task C5:
        # antes se mandaban una por una DENTRO del bucle de creación, así
        # que un fallo a mitad del lote (ej. la bicicleta 3 de 3 con un
        # id invalido) ya habia mandado el correo real de las bicicletas
        # 1 y 2 -- el rollback de _revertir_reserva_grupal() borra el
        # registro de la campana, pero un correo real ya enviado no se
        # puede recuperar. Con esto, si algo falla antes de esta linea,
        # CERO correos/notificaciones salen para un intento que termino
        # revertido por completo.
        for viaje in viajes_creados:
            notificaciones_repo.notificar_usuario(
                pb, user_id, tipo="viaje_iniciado",
                titulo="Viaje iniciado",
                mensaje=f"Iniciaste un viaje con la bicicleta {viaje.get('bicicleta_codigo', '—')} "
                        f"(reserva grupal de {n} bicicletas).",
                enlace=f"/ciclista/viaje-activo/{viaje['id']}",
            )

        # Descuento de volumen (punto 0.2, 20-ago-2026): un codigo nuevo,
        # de un solo uso, para una reserva FUTURA -- igual que el codigo
        # de buena conducta, no se autoaplica a esta misma reserva (ya
        # esta confirmada y notificada arriba). No exige 0 infracciones
        # activas (es un premio al volumen de esta reserva, no a la
        # conducta general -- distinto del codigo de finalizar()).
        mensaje_volumen = ""
        if n >= 3:
            try:
                codigo_volumen = codigos_descuento_repo.generar(user_id, 15, viajes_creados[0]["id"])
                mensaje_volumen = f" Por reservar {n} bicicletas a la vez, ganaste un código de descuento del 15%: {codigo_volumen['codigo']}."
            except Exception:
                pass

        request.session["flash"] = {"type": "success", "msg":
            f"Reserva grupal de {n} bicicletas iniciada. Al devolver y pagar todas, recibirás una sola factura." + mensaje_volumen}
        return RedirectResponse(f"/ciclista/viaje-activo/{viajes_creados[0]['id']}", status_code=302)

    except Exception as e:
        # Todo-o-nada real (Tarea C2, ronda de fix 1): CUALQUIER fallo desde
        # aca hasta el return de exito de arriba -- dentro del bucle de
        # creacion, marcando el codigo de descuento usado, o registrando la
        # auditoria de exito -- debe dejar CERO viajes/bicicletas en_uso de
        # este intento, no un subconjunto. Se revierte por grupo_reserva_id
        # (ver _revertir_reserva_grupal) y SIEMPRE se deja un rastro real en
        # auditoria del intento fallido, para que no sea invisible salvo
        # inspeccionando la base directamente.
        if pb is not None:
            try:
                _revertir_reserva_grupal(pb, grupo_reserva_id, user_id)
            except Exception:
                pass
        if codigo_valido:
            # Ronda de fix dedicada tras el hallazgo real de la 3a revisión
            # de la Task C5 (ya senalado sin resolver en el fix round 1 de
            # C2): si marcar_usado() ya se aplico del lado de PocketBase
            # antes de que algo mas fallara, el codigo quedaba quemado para
            # una reserva que en los hechos nunca se concreto. Seguro de
            # llamar incluso si nunca llego a marcarse usado (ver docstring
            # de revertir_uso()).
            try:
                codigos_descuento_repo.revertir_uso(codigo_valido["id"])
            except Exception:
                pass
        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Reserva grupal fallida, revertida: {len(viajes_creados)} "
            f"de {n} bicicletas, motivo: {e}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        request.session["flash"] = {"type": "error", "msg": f"Error al iniciar la reserva grupal: {e}"}
        return RedirectResponse("/ciclista/alquilar", status_code=302)


# ── Detalle de bicicleta ─────────────────────────────────────────────────────

@router.get("/bicicleta/{bici_id}", response_class=HTMLResponse)
async def bicicleta_detalle(request: Request, bici_id: str):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    try:
        pb = _pb()
        bici = pb.get_record("bicicletas", bici_id)
    except Exception:
        request.session["flash"] = {"type": "error", "msg": "Bicicleta no encontrada."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    estacion: dict = {}
    try:
        nombre_bici = (bici.get("estacion") or "").strip().lower()
        if nombre_bici:
            for e in pb.list_records("estaciones", per_page=200).get("items", []):
                if (e.get("nombre") or "").strip().lower() == nombre_bici:
                    estacion = e
                    break
    except Exception:
        pass

    tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))
    precio_hora = _tarifa_hora(bici.get("codigo", ""), tipo_membresia)

    viajes_recientes: list[dict] = []
    try:
        viajes_recientes = pb.list_records(
            "viajes",
            filter=f'bicicleta_id = {filter_literal(bici_id)}',
            sort="-fecha_inicio", per_page=5,
        ).get("items", [])
    except Exception:
        pass

    en_limite_viajes = len(_viajes_activos(user.get("id", ""))) >= MAX_VIAJES_ACTIVOS

    # Ficha tecnica real: mismo JOIN que ya arma el catalogo
    # (bicicletas -> modelos_bicicleta -> marcas -> categorias), solo
    # que aqui filtramos al catalogo devuelto por el codigo de esta
    # bicicleta en particular. None si el codigo no tiene modelo real
    # asociado (no se fabrica nada en ese caso).
    catalogo_bici = None
    try:
        catalogo = _catalogo_bicicletas(pb, [bici], tipo_membresia)
        catalogo_bici = next((c for c in catalogo if c["codigo"] == bici.get("codigo")), None)
    except Exception:
        catalogo_bici = None

    return templates.TemplateResponse(request, "ciclista/detalle_bicicleta.html", _ctx(request,
        title=f"Bicicleta {bici.get('codigo', '')}", flash=flash,
        bici=bici, estacion=estacion, precio_hora=precio_hora,
        viajes_recientes=viajes_recientes, en_limite_viajes=en_limite_viajes,
        max_viajes_activos=MAX_VIAJES_ACTIVOS,
        catalogo_bici=catalogo_bici,
        bloqueada_exclusiva=bool(catalogo_bici and catalogo_bici.get("bloqueada_exclusiva")),
        pb_url=settings.pb_url,
    ))


# ── Viaje activo ─────────────────────────────────────────────────────────────

@router.get("/viaje-activo", response_class=HTMLResponse)
async def viaje_activo_redirigir(request: Request):
    """Compatibilidad con la URL vieja (sin id, de cuando un ciclista solo
    podía tener un viaje activo a la vez) -- redirige al primero de la
    lista real. Ver viaje_activo() para la ruta con id, la que ahora
    soporta varios viajes activos simultáneos (punto 3)."""
    user = getattr(request.state, "user", {})
    viajes = _viajes_activos(user.get("id", ""))
    if not viajes:
        request.session["flash"] = {"type": "info", "msg": "No tienes un viaje activo."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
    return RedirectResponse(f"/ciclista/viaje-activo/{viajes[0]['id']}", status_code=302)


@router.get("/viaje-activo/{viaje_id}", response_class=HTMLResponse)
async def viaje_activo(request: Request, viaje_id: str):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    try:
        viaje = _pb().get_record("viajes", viaje_id)
    except Exception:
        viaje = None
    if not viaje or viaje.get("ciclista_id") != user.get("id", "") or \
            viaje.get("estado") not in ("activo", "pendiente_validacion"):
        request.session["flash"] = {"type": "info", "msg": "No tienes un viaje activo con ese identificador."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    otros_viajes_activos = [v for v in _viajes_activos(user.get("id", "")) if v.get("id") != viaje_id]

    estaciones: list[dict] = []
    tipo_bicicleta = "classic_bike"
    precio_hora = 0.0  # ahora: precio de la modalidad ACTUAL del viaje (Tarea 9), no siempre "hora"
    # SIEMPRE el precio de la modalidad 'hora' -- distinto de precio_hora
    # cuando la modalidad activa es 'dia'/'semana'. Es el que usa
    # vig_devolver() (precio_hora_display) para el recargo por demora sin
    # importar la modalidad del segmento abierto; si el JS usara el precio
    # de 'dia'/'semana' para el recargo, el numero en vivo no coincidiria
    # con lo que se cobra de verdad.
    precio_hora_recargo = 0.0
    subtotal_segmentos_cerrados = 0.0
    try:
        pb = _pb()
        res = pb.list_records("estaciones", filter='activa = true', sort="nombre", per_page=50)
        estaciones = res.get("items", [])
        bici = pb.get_record("bicicletas", viaje.get("bicicleta_id", ""))
        tipo_bicicleta = bici.get("tipo") or "classic_bike"
        tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))

        modalidad_actual = viaje.get("modalidad_actual") or "hora"
        codigo_bici_viaje = viaje.get("bicicleta_codigo", "")
        # Con promocion aplicable ya descontada (mismo hallazgo/fix que
        # vig_devolver(), 17-ago-2026) -- para que el numero en vivo
        # coincida con lo que se cobrara de verdad. precio_hora_recargo
        # SIEMPRE via _tarifa_hora() (sin promo, sin importar la
        # modalidad activa): nunca se descuenta el multiplicador del
        # recargo por demora, "no tiene sentido descontar una
        # penalizacion" (mismo criterio de siempre).
        resultado_precio = tarifas_repo.precio_modalidad_con_promocion(codigo_bici_viaje, tipo_membresia, modalidad_actual)
        precio_hora = resultado_precio[0] if resultado_precio else 0.0
        precio_hora_recargo = _tarifa_hora(codigo_bici_viaje, tipo_membresia)
        subtotal_segmentos_cerrados = alquileres_repo.total_segmentos_cerrados(viaje_id)
    except Exception:
        pass

    return templates.TemplateResponse(request, "ciclista/viaje_activo.html", _ctx(request,
        title="Viaje Activo", flash=flash, viaje=viaje,
        otros_viajes_activos=otros_viajes_activos,
        estaciones=estaciones,
        estaciones_json=json.dumps(estaciones),
        tipo_bicicleta=tipo_bicicleta,
        precio_hora=precio_hora,  # precio de la modalidad actual del viaje (nombre de variable ya existente en el template)
        precio_hora_recargo=precio_hora_recargo,
        subtotal_segmentos_cerrados=subtotal_segmentos_cerrados,
    ))


@router.post("/finalizar")
async def finalizar(
    request: Request,
    viaje_id:             str = Form(...),
    estacion_fin_id:      str = Form(...),
    estacion_fin_nombre:  str = Form(...),
):
    """"Devolver bicicleta" -- reporte del ciclista de que terminó, NO
    el cierre real del viaje. Antes esta función calculaba el monto
    final y cobraba de inmediato; ahora solo deja constancia real de
    que el ciclista reportó la devolución (fecha_fin = cuándo lo
    reportó, estacion_fin_id = dónde dice que la dejó) y mueve el viaje
    a 'pendiente_validacion' -- ni el monto ni el pago se generan
    todavía. La bicicleta se queda 'en_uso' a propósito (no
    'mantenimiento'): todavía no está confirmada físicamente, así que
    ninguna otra pantalla debe ofrecerla como disponible.

    Mientras nadie de Vigilancia valide la entrega real
    (/empleado/vigilancia/devolver/{id}, ver empleado.py), el monto
    base ya queda fijo con la hora real de este reporte (fecha_fin) --
    decisión de negocio reconfirmada con Washington 17-ago-2026: la
    espera hasta que Vigilancia confirme NO es tiempo de uso real. Solo
    el recargo por demora (tras 5h de gracia desde este reporte) sigue
    corriendo hasta que Vigilancia confirme -- mismo cálculo en vivo
    que ya usaba el cronómetro de viaje-activo, ahora también visible
    para Vigilancia en devoluciones.html."""
    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        pb.get_record("viajes", viaje_id)  # 404 real si el id no existe

        pb.update_record("viajes", viaje_id, {
            "estado":          "pendiente_validacion",
            "estacion_fin_id": estacion_fin_id,
            "fecha_fin":       _ahora(),
        })

        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes",
            f"Devolución reportada en {estacion_fin_nombre} -- pendiente de validación de Vigilancia", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        notificaciones_repo.notificar_rol(
            "empleado-vigilancia", tipo="devolucion_pendiente_validar",
            titulo="Devolución por validar",
            mensaje=f"{user.get('name') or user.get('email', '')} reportó la devolución en "
                    f"{estacion_fin_nombre} -- pendiente de confirmar la entrega física.",
            enlace="/empleado/vigilancia/devoluciones",
        )

        # Código de descuento por buena conducta + cliente frecuente
        # (puntos 13 y 0.2, unificados el 20-ago-2026): se genera acá, al
        # reportar la devolución, si el ciclista no tiene infracciones
        # activas EN ESTE MOMENTO (no depende del resultado de la
        # inspección de Vigilancia de ESTE viaje, que todavía no pasó --
        # es un premio a su historial limpio hasta ahora, no a este viaje
        # en particular). 20% si completó _UMBRAL_RECURRENTE viajes o más
        # en los ULTIMOS 30 DIAS (antes era todo el historial, sin
        # ventana -- ver docs/HOJA_DE_RUTA.md), si no 10%.
        mensaje_extra = ""
        if _infracciones_activas(user.get("id", "")) == 0:
            porcentaje = 20 if _viajes_completados_ultimos_30_dias(user.get("id", "")) >= _UMBRAL_RECURRENTE else 10
            try:
                codigo_nuevo = codigos_descuento_repo.generar(user.get("id", ""), porcentaje, viaje_id)
                mensaje_extra = f" Ganaste un código de descuento del {porcentaje}%: {codigo_nuevo['codigo']}."
            except Exception:
                pass

        request.session["flash"] = {"type": "success", "msg":
            "Devolución reportada. Un empleado de Vigilancia confirmará la entrega física pronto." + mensaje_extra}
        return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al reportar la devolución: {e}"}
        return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)


@router.post("/cambiar-modalidad")
async def cambiar_modalidad(
    request: Request,
    viaje_id:        str = Form(...),
    modalidad_nueva: str = Form(...),
):
    if modalidad_nueva not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        if viaje.get("estado") != "activo":
            request.session["flash"] = {"type": "error", "msg":
                "Solo puedes cambiar la modalidad mientras el viaje sigue activo."}
            return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

        bici = pb.get_record("bicicletas", viaje.get("bicicleta_id", ""))
        bicicleta_codigo = bici.get("codigo", viaje.get("bicicleta_codigo", ""))
        tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))

        modalidad_actual = viaje.get("modalidad_actual") or "hora"
        inicio_actual = viaje.get("inicio_segmento_actual") or viaje.get("fecha_inicio")
        ahora = _ahora()

        # Se resuelve el precio del segmento SALIENTE antes de escribir nada
        # en ninguna base -- si esto falla, el viaje queda exactamente
        # como estaba. Con promocion aplicable (si hay alguna) ya
        # descontada -- mismo hallazgo/fix que vig_devolver() (17-ago-2026):
        # este es el SUBTOTAL real del segmento, nunca lleva recargo (los
        # segmentos intermedios siempre cierran con recargo=0.0), asi que
        # no hace falta separar un precio "sin promo" aca.
        resultado_actual = tarifas_repo.precio_modalidad_con_promocion(bicicleta_codigo, tipo_membresia, modalidad_actual)
        subtotal_segmento = None
        id_tarifa_actual = None
        if resultado_actual:
            precio_actual, id_tarifa_actual = resultado_actual
            if modalidad_actual == "hora":
                # Piso de 1 minuto (decidido con Washington, 16-ago-2026,
                # tras encontrar la discrepancia real en la Tarea 7): mismo
                # criterio que vig_devolver() -- nunca cobra menos de 1
                # minuto por segmento, ni siquiera si el cambio de
                # modalidad fue casi instantaneo.
                minutos_segmento = max(1, int((datetime.now(timezone.utc) - datetime.fromisoformat(
                    inicio_actual.replace("Z", "+00:00"))).total_seconds() / 60))
                subtotal_segmento = round(minutos_segmento / 60 * precio_actual, 2)
            else:
                subtotal_segmento = precio_actual

        # PocketBase PRIMERO -- es la fuente real del estado del viaje. Si
        # esto falla, no se llega a tocar ClickHouse: el viaje queda
        # exactamente como estaba, sin inconsistencia posible (decisión
        # confirmada con Washington: entre "cobrar de más" y "no cobrar
        # ese tramo" ante un fallo a mitad de camino, se prefiere lo
        # segundo -- más seguro para el ciclista que para UrbanBike, pero
        # nunca duplica un cobro).
        pb.update_record("viajes", viaje_id, {
            "modalidad_actual": modalidad_nueva,
            "inicio_segmento_actual": ahora,
        })

        # ClickHouse DESPUES: si esto falla, la modalidad YA cambió (el
        # paso anterior ya se comiteó) -- se avisa con un mensaje que
        # refleja la realidad, no un "no se pudo cambiar la modalidad"
        # generico que sugeriria que nada pasó cuando sí pasó.
        if subtotal_segmento is not None:
            try:
                alquileres_repo.cerrar_segmento(
                    viaje_id=viaje_id, ciclista_id=viaje.get("ciclista_id", ""),
                    bicicleta_codigo=bicicleta_codigo, modalidad=modalidad_actual,
                    id_tarifa=id_tarifa_actual, fecha_inicio=inicio_actual, fecha_fin=ahora,
                    subtotal=subtotal_segmento, recargo=0.0,
                )
            except Exception:
                request.session["flash"] = {"type": "info", "msg":
                    f"Modalidad cambiada a {modalidad_nueva}, pero hubo un problema registrando "
                    "el cobro del tramo anterior -- contacta a soporte si el monto final no coincide."}
                return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

        request.session["flash"] = {"type": "success", "msg":
            f"Modalidad cambiada a {modalidad_nueva}. El tramo anterior ya quedó cobrado."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"No se pudo cambiar la modalidad: {e}"}
    return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)


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
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Cobro en efectivo pendiente",
                mensaje=f"Un ciclista se acercará a pagar en efectivo con el código {comprobante}.",
                enlace="/empleado/operacion/pagos",
            )
            request.session["flash"] = {"type": "info", "msg":
                f"Dirígete al empleado de operación más cercano con el código de pago: {comprobante} para completar el pago."}
            return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

        # ── Tarjeta (simulado) ────────────────────────────────────────────────
        if metodo_pago == "tarjeta":
            if not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
                request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if not _luhn_valido(numero_tarjeta):
                request.session["flash"] = {"type": "error", "msg":
                    "El número de tarjeta no es válido. Prueba con 4242 4242 4242 4242, la tarjeta de pruebas estándar."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if not _expiracion_valida(mes_expiracion, anio_expiracion)[0]:
                request.session["flash"] = {"type": "error", "msg": "La fecha de expiración de la tarjeta no es válida."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            digitos = "".join(ch for ch in numero_tarjeta if ch.isdigit())
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
            notificaciones_repo.notificar_usuario(
                pb, registro.get("ciclista_id", user_id), tipo="pago_aprobado",
                titulo="Pago aprobado",
                mensaje=f"Tu pago de ${float(registro.get('monto_total') or 0):.2f} fue aprobado.",
                enlace="/ciclista/pagos",
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
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Transferencia pendiente de verificar",
                mensaje=f"Un ciclista subió un comprobante de transferencia (código {comprobante}) que espera verificación.",
                enlace="/empleado/operacion/pagos",
            )
            request.session["flash"] = {"type": "info", "msg":
                "Tu pago está en verificación. El empleado de operación lo confirmará en breve."}
            return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

        request.session["flash"] = {"type": "error", "msg": "Método de pago no válido."}
        return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al confirmar el pago: {e}"}
        return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)


@router.post("/borrar-comprobante/{pago_id}")
async def borrar_comprobante(request: Request, pago_id: str):
    user    = getattr(request.state, "user", {})
    user_id = user.get("id", "")
    try:
        pb = _pb()
        registro = pb.get_record("pagos", pago_id)
        if registro.get("ciclista_id") != user_id:
            request.session["flash"] = {"type": "error", "msg": "No tienes acceso a ese pago."}
            return RedirectResponse("/ciclista/historial", status_code=302)
        if registro.get("estado") != "verificacion_pendiente":
            request.session["flash"] = {"type": "error", "msg": "Solo puedes borrar el comprobante cuando el pago está en verificación pendiente."}
            return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)

        pb.update_record_with_file("pagos", pago_id,
            {"estado": "pendiente"},
            {"comprobante_imagen": ("", b"", "application/octet-stream")},
        )
        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "pagos",
            f"Comprobante de imagen borrado para reintentar: pago {pago_id}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        request.session["flash"] = {"type": "success", "msg": "Imagen eliminada. Puedes subir un nuevo comprobante."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al borrar el comprobante: {e}"}
    return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)


def _construir_factura_pago(registro: dict, viaje: dict, user: dict) -> DatosFactura:
    """Arma la factura con marca UrbanBike (punto 11) para UN pago de viaje
    -- compartida entre comprobante() (HTML) y comprobante_pago_pdf() (PDF)
    para no duplicar la lógica de armado de líneas. Las líneas de detalle
    (tarifa base / recargo por demora / cargo por daños / descuento) usan
    los campos separados que ya guarda vig_devolver()/vig_inspeccion_registrar()
    en 'pagos' (ver docs/superpowers/plans, rediseño del flujo alquiler,
    puntos 3 y 10) -- .get(..., 0) por si el registro es anterior a ese
    rediseño y no tiene los campos nuevos."""
    subtotal_base   = float(registro.get("subtotal") or registro.get("monto_total") or 0)
    recargo_demora  = float(registro.get("recargo_demora") or 0)
    cargo_danos     = float(registro.get("cargo_danos") or 0)
    descuento_monto = float(registro.get("descuento_monto") or 0)
    descuento_codigo = registro.get("descuento_codigo") or ""
    monto_total     = float(registro.get("monto_total") or 0)

    # 'tipo' == "cargo_danos": pago independiente de un viaje (registro
    # anterior al rediseño, que fusionó el cargo por daños dentro del pago
    # del viaje -- ver vig_inspeccion_registrar() en empleado.py). Se
    # conserva el manejo porque historial.html todavía distingue y muestra
    # estos registros; la línea usa su propia descripción, no "Tarifa base".
    if registro.get("tipo") == "cargo_danos":
        lineas = [LineaFactura(registro.get("descripcion_cargo") or "Cargo por daños", 1, subtotal_base, subtotal_base)]
    else:
        # Obtener segmentos de modalidad del viaje (Important #2: envoltura
        # try/except para que una falla de ClickHouse no rompa la pantalla de
        # comprobante; si falla la query, caemos al fallback seguro de
        # "Tarifa base" usando el monto confiable de pagos.subtotal).
        segmentos = []
        try:
            segmentos = ch.query(
                "SELECT modalidad, subtotal FROM urbanbike_operativa.alquileres "
                "WHERE id_origen_pocketbase = %(viaje_id)s AND origen = 'segmento_modalidad' "
                "ORDER BY fecha_inicio",
                {"viaje_id": viaje.get("id", "")},
            )
        except Exception:
            # Si ClickHouse falla, segmentos queda [], caemos al else
            pass

        # Important #1: reconciliación contra pagos.subtotal. El último
        # segmento de cada viaje se inserta en ClickHouse best-effort en
        # vig_devolver() -- si ese INSERT falla, pagos.subtotal es correcto
        # pero la fila del último segmento nunca llega a alquileres. Como
        # segmentos.size < segmento_count_real, la suma no va a coincidir
        # con subtotal_base. En ese caso, mostrar la factura con segmentos
        # incompletos sería engañoso (el cliente suma las líneas y obtiene
        # menos del TOTAL real), así que caemos al fallback confiable.
        segmentos_sum = sum(float(s["subtotal"]) for s in segmentos) if segmentos else 0.0
        segmentos_reconciliados = segmentos and abs(segmentos_sum - subtotal_base) <= 0.01

        if segmentos_reconciliados:
            # ReplacingMergeTree sin FINAL: cada fila (uuid4() nuevo) se
            # inserta exactamente una sola vez, nunca se duplica la clave de
            # orden, así que no hace falta deduplicar en la lectura.
            etiquetas = {"hora": "Tarifa por hora", "dia": "Tarifa por día", "semana": "Tarifa por semana"}
            lineas = [
                LineaFactura(etiquetas.get(s["modalidad"], "Tarifa"), 1, float(s["subtotal"]), float(s["subtotal"]))
                for s in segmentos
            ]
        else:
            # Pago anterior a este cambio, sin segmentos en alquileres, o
            # segmentos inconsistentes respecto a subtotal_base -- mostrar
            # "Tarifa base" confiable usando el monto de pagos.subtotal.
            lineas = [LineaFactura("Tarifa base (alquiler de bicicleta)", 1, subtotal_base, subtotal_base)]
    if recargo_demora > 0:
        lineas.append(LineaFactura("Recargo por demora en la devolución (>5h)", 1, recargo_demora, recargo_demora))
    if cargo_danos > 0:
        lineas.append(LineaFactura("Cargo por daños a la bicicleta", 1, cargo_danos, cargo_danos))
    if descuento_monto > 0:
        etiqueta = f"Descuento aplicado ({descuento_codigo})" if descuento_codigo else "Descuento aplicado"
        lineas.append(LineaFactura(etiqueta, 1, -descuento_monto, -descuento_monto))

    subtotal_sin_iva, iva = facturas_repo.desglosar_iva(monto_total)
    fecha_pago = (registro.get("fecha_pago") or registro.get("fecha_generado") or "—")[:19].replace("T", " ")
    comprobante_num = registro.get("comprobante_numero") or registro.get("id", "")

    return DatosFactura(
        numero=comprobante_num,
        fecha_emision=fecha_pago,
        fecha_vencimiento=fecha_pago,
        numero_pedido=viaje.get("id") or registro.get("viaje_id") or "—",
        cliente_nombre=registro.get("ciclista_nombre") or user.get("name") or user.get("email", ""),
        cliente_cedula=user.get("cedula", ""),
        cliente_extra=f"Bicicleta {viaje.get('bicicleta_codigo') or '—'} — "
                       f"Estación de salida: {viaje.get('estacion_inicio_nombre') or '—'} "
                       f"(duración {_duracion_hms(registro.get('duracion_minutos') or 0)})",
        metodo_pago=(registro.get("metodo_pago") or "—").capitalize(),
        lineas=lineas,
        subtotal=subtotal_sin_iva,
        iva=iva,
        descuento=descuento_monto,
        total=monto_total,
    )


def _construir_factura_grupo(pagos: list[dict], viajes_por_id: dict, user: dict) -> DatosFactura:
    """Factura unica para un grupo de bicicletas reservadas a la vez (punto
    0.3): agrega las lineas de CADA pago del grupo (reusa la misma
    _construir_factura_pago() por pago para no duplicar el desglose de
    segmentos/recargo/danos/descuento, solo le antepone el codigo de la
    bicicleta a cada linea) y suma los totales, incluido el IVA ya
    calculado por cada factura individual (evita recalcularlo aparte con
    un segundo desglosar_iva() -- misma fuente de verdad, un solo lugar).
    Solo se llama cuando YA se confirmo que todos los pagos del grupo
    estan 'pagado' (ver comprobante_grupo() mas abajo) -- no valida eso
    aca."""
    todas_las_lineas: list[LineaFactura] = []
    total_grupo = 0.0
    subtotal_grupo = 0.0
    iva_grupo = 0.0
    descuento_grupo = 0.0
    bicicletas_desc = []

    for registro in pagos:
        viaje = viajes_por_id.get(registro.get("viaje_id", ""), {})
        factura_individual = _construir_factura_pago(registro, viaje, user)
        prefijo = f"{viaje.get('bicicleta_codigo', '—')} — "
        for linea in factura_individual.lineas:
            todas_las_lineas.append(LineaFactura(
                prefijo + linea.descripcion, linea.cantidad, linea.precio_unitario, linea.importe,
            ))
        total_grupo += factura_individual.total
        subtotal_grupo += factura_individual.subtotal
        iva_grupo += factura_individual.iva
        descuento_grupo += factura_individual.descuento
        bicicletas_desc.append(viaje.get("bicicleta_codigo", "—"))

    primer_pago = pagos[0]
    fecha_pago = max(
        (p.get("fecha_pago") or p.get("fecha_generado") or "")[:19].replace("T", " ") for p in pagos
    )
    grupo_reserva_id = primer_pago.get("grupo_reserva_id", "")

    return DatosFactura(
        numero=f"GRUPO-{grupo_reserva_id[:8]}",
        fecha_emision=fecha_pago,
        fecha_vencimiento=fecha_pago,
        numero_pedido=grupo_reserva_id,
        cliente_nombre=primer_pago.get("ciclista_nombre") or user.get("name") or user.get("email", ""),
        cliente_cedula=user.get("cedula", ""),
        cliente_extra=f"Reserva grupal de {len(pagos)} bicicletas: {', '.join(bicicletas_desc)}",
        metodo_pago="Varios" if len({p.get("metodo_pago") for p in pagos}) > 1 else (primer_pago.get("metodo_pago") or "—").capitalize(),
        lineas=todas_las_lineas,
        subtotal=subtotal_grupo,
        iva=iva_grupo,
        descuento=descuento_grupo,
        total=total_grupo,
    )


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
        factura=_construir_factura_pago(registro, viaje, user),
        soporte_email=settings.support_email,
    ))


def _grupo_reserva_facturable(pb, grupo_reserva_id: str, user_id: str) -> tuple[list[dict] | None, dict | None, dict | None]:
    """Trae y valida un grupo de reserva para facturación (Tasks C4/C5):
    devuelve (pagos_grupo, viajes_por_id, None) si el grupo existe, le
    pertenece al usuario, y TODOS sus pagos ya estan 'pagado'; en
    cualquier otro caso devuelve (None, None, flash) con el flash listo
    para sesión -- compartido entre comprobante_grupo() (HTML) y
    comprobante_grupo_pdf() para que las dos vistas nunca puedan divergir
    en qué cuenta como un grupo válido/completo."""
    try:
        viajes_grupo = pb.list_records(
            "viajes", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        viajes_grupo = []

    if not viajes_grupo or any(v.get("ciclista_id") != user_id for v in viajes_grupo):
        return None, None, {"type": "error", "msg": "Reserva grupal no encontrada."}

    viajes_por_id = {v["id"]: v for v in viajes_grupo}
    try:
        pagos_grupo = pb.list_records(
            "pagos", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        pagos_grupo = []

    if len(pagos_grupo) < len(viajes_grupo) or any(p.get("estado") != "pagado" for p in pagos_grupo):
        return None, None, {"type": "info", "msg":
            "La factura de esta reserva grupal todavía no está lista: faltan bicicletas del grupo "
            "por devolver o pagar."}

    return pagos_grupo, viajes_por_id, None


@router.get("/comprobante-grupo/{grupo_reserva_id}", response_class=HTMLResponse)
async def comprobante_grupo(request: Request, grupo_reserva_id: str):
    user = getattr(request.state, "user", {})
    pagos_grupo, viajes_por_id, flash = _grupo_reserva_facturable(_pb(), grupo_reserva_id, user.get("id", ""))
    if flash:
        request.session["flash"] = flash
        return RedirectResponse("/ciclista/historial", status_code=302)

    datos = _construir_factura_grupo(pagos_grupo, viajes_por_id, user)
    return templates.TemplateResponse(request, "ciclista/comprobante.html", _ctx(request,
        title="Factura de reserva grupal", pago={"id": grupo_reserva_id}, factura=datos, es_grupo=True,
        soporte_email=settings.support_email,
    ))


@router.get("/comprobante-grupo/{grupo_reserva_id}/pdf")
async def comprobante_grupo_pdf(request: Request, grupo_reserva_id: str):
    """PDF con marca UrbanBike de la factura de una reserva grupal --
    mismo contenido que comprobante_grupo() (HTML), mismo generador que
    comprobante_pago_pdf()/membresia_comprobante_pdf()
    (app.reportes.factura.generar_factura_pdf, ver punto 11)."""
    user = getattr(request.state, "user", {})
    pagos_grupo, viajes_por_id, flash = _grupo_reserva_facturable(_pb(), grupo_reserva_id, user.get("id", ""))
    if flash:
        request.session["flash"] = flash
        return RedirectResponse("/ciclista/historial", status_code=302)

    datos = _construir_factura_grupo(pagos_grupo, viajes_por_id, user)
    return generar_factura_pdf(
        datos, nombre_archivo=f"urbanbike_factura_grupo_{grupo_reserva_id[:8]}.pdf",
    )


@router.get("/comprobante/{pago_id}/pdf")
async def comprobante_pago_pdf(request: Request, pago_id: str):
    """PDF con marca UrbanBike del comprobante de UN pago (columna
    Comprobante de /ciclista/pagos) -- mismo contenido que comprobante.html
    (HTML), mismo generador que membresia_comprobante_pdf()
    (app.reportes.factura.generar_factura_pdf, ver punto 11)."""
    user = getattr(request.state, "user", {})
    try:
        registro = _pb().get_record("pagos", pago_id)
    except Exception:
        request.session["flash"] = {"type": "error", "msg": "Comprobante no encontrado."}
        return RedirectResponse("/ciclista/pagos", status_code=302)

    if registro.get("ciclista_id") != user.get("id", ""):
        request.session["flash"] = {"type": "error", "msg": "No tienes acceso a ese comprobante."}
        return RedirectResponse("/ciclista/pagos", status_code=302)

    if registro.get("estado") != "pagado":
        request.session["flash"] = {"type": "error", "msg": "Este pago todavía no está confirmado."}
        return RedirectResponse("/ciclista/pagos", status_code=302)

    viaje: dict = {}
    try:
        viaje = _pb().get_record("viajes", registro.get("viaje_id", ""))
    except Exception:
        pass

    comprobante_num = registro.get("comprobante_numero") or pago_id
    return generar_factura_pdf(
        _construir_factura_pago(registro, viaje, user),
        nombre_archivo=f"urbanbike_comprobante_{comprobante_num}.pdf",
    )


# ── Historial ─────────────────────────────────────────────────────────────────

def _historial_data(ciclista_id: str, q: str = "", estado: str = "") -> dict:
    """Datos del historial de UN ciclista -- ciclista_id siempre debe venir
    de request.state.user (la sesión autenticada), nunca de un parámetro
    de la URL/form, para no exponer el historial de otro ciclista (dato
    personal). Compartida entre la pantalla y el export para no duplicar
    la lógica ni, más importante, el filtro de seguridad."""
    viajes: list[dict] = []
    estaciones_nombres: dict[str, str] = {}
    bicis_por_id: dict[str, dict] = {}
    pagos_por_viaje: dict[str, list[dict]] = {}
    pagos_sueltos: list[dict] = []
    recibos_por_viaje: dict[str, dict] = {}
    try:
        pb = _pb()
        partes = [f'ciclista_id = {filter_literal(ciclista_id)}']
        if estado:
            partes.append(f'estado = {filter_literal(estado)}')
        texto = q.strip()
        if texto:
            lit = filter_literal(texto)
            partes.append(f'(bicicleta_codigo ~ {lit} || estacion_inicio_nombre ~ {lit})')
        filtro = " && ".join(partes)

        res = pb.list_records("viajes", filter=filtro, sort="-fecha_inicio", per_page=100)
        viajes = res.get("items", [])
        estaciones_nombres = {
            e["id"]: e.get("nombre", "")
            for e in pb.list_records("estaciones", per_page=200).get("items", [])
        }
        bicis_por_id = {
            b["id"]: b
            for b in pb.list_records("bicicletas", per_page=500).get("items", [])
        }
        # Se traen todos los pagos del ciclista (no solo los de los viajes listados
        # arriba), para que los cargos por daños también aparezcan en el historial.
        pagos = pb.list_records(
            "pagos", filter=f'ciclista_id = {filter_literal(ciclista_id)}', sort="-fecha_pago", per_page=300,
        ).get("items", [])
        ids_viajes_listados = {v["id"] for v in viajes}
        for p in pagos:
            vid = p.get("viaje_id") or ""
            if vid and vid in ids_viajes_listados:
                pagos_por_viaje.setdefault(vid, []).append(p)
            elif not vid:
                pagos_sueltos.append(p)
    except Exception:
        pass

    # Recibo real: solo para viajes cuyo alquiler real (migrado el
    # 30-jul-2026) llegó a estado 'facturado'. No se inventa un monto
    # para los que quedaron en 'devuelto' o 'cancelado'. `facturas` real
    # ya existe (backfill real de estas mismas filas, ver
    # docs/HOJA_DE_RUTA.md) -- id_factura viaja en la misma fila para
    # que el enlace de la plantilla resuelva contra la factura real, no
    # solo contra el monto/código sueltos de siempre.
    try:
        mapa_ids = ch.mapa_alquiler_por_viaje_pocketbase()
        ids_alquiler = [mapa_ids[v["id"]] for v in viajes if v["id"] in mapa_ids]
        if ids_alquiler:
            filas = ch.query("""
                SELECT a.id AS id, a.codigo AS codigo, a.total AS total,
                       e.fecha AS fecha_facturacion, f.id AS id_factura
                FROM urbanbike_operativa.alquileres a FINAL
                JOIN urbanbike_operativa.alquiler_eventos e
                    ON e.id_alquiler = a.id AND e.estado_destino = 'facturado'
                LEFT JOIN urbanbike_operativa.facturas f FINAL
                    ON f.id_alquiler = a.id
                WHERE a.estado = 'facturado' AND a.id IN %(ids)s
            """, {"ids": ids_alquiler})
            recibos_por_alquiler = {str(f["id"]): f for f in filas}
            for v in viajes:
                id_alq = mapa_ids.get(v["id"])
                if id_alq in recibos_por_alquiler:
                    recibos_por_viaje[v["id"]] = recibos_por_alquiler[id_alq]
    except Exception:
        pass

    return {
        "viajes": viajes, "estaciones_nombres": estaciones_nombres,
        "bicis_por_id": bicis_por_id, "pagos_por_viaje": pagos_por_viaje,
        "pagos_sueltos": pagos_sueltos, "recibos_por_viaje": recibos_por_viaje,
    }


@router.get("/historial", response_class=HTMLResponse)
async def historial(request: Request, q: str = "", estado: str = ""):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    d = _historial_data(user.get("id", ""), q, estado)
    return templates.TemplateResponse(request, "ciclista/historial.html", _ctx(request,
        title="Mis Viajes", flash=flash, viajes=d["viajes"],
        estaciones_nombres=d["estaciones_nombres"],
        bicis_por_id=d["bicis_por_id"], pagos_por_viaje=d["pagos_por_viaje"],
        pagos_sueltos=d["pagos_sueltos"], recibos_por_viaje=d["recibos_por_viaje"],
        q=q, estado=estado,
    ))


def _historial_columnas_filas(d: dict) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Tipo", ancho=12),
        ColumnaReporte("Estado", ancho=14),
        ColumnaReporte("Estación inicio", ancho=24),
        ColumnaReporte("Estación fin", ancho=24),
        ColumnaReporte("Fecha inicio", ancho=18),
        ColumnaReporte("Duración (min)", ancho=16, formato="entero"),
        ColumnaReporte("Monto", ancho=12, formato="moneda"),
        ColumnaReporte("Estado de pago", ancho=18),
        ColumnaReporte("Comprobante", ancho=16),
    ]
    estado_label = {"activo": "Activo", "completado": "Completado", "cancelado": "Cancelado"}
    filas = []
    for v in d["viajes"]:
        bici = d["bicis_por_id"].get(v.get("bicicleta_id"), {})
        pagos_v = d["pagos_por_viaje"].get(v["id"], [])
        pagados_v = [p for p in pagos_v if p.get("estado") == "pagado"]
        pago_unico = pagados_v[0] if pagados_v else (pagos_v[0] if pagos_v else None)
        recibo = d["recibos_por_viaje"].get(v["id"])

        if pago_unico:
            monto = float(pago_unico.get("monto_total") or 0)
            if pago_unico.get("tipo") == "cargo_danos":
                estado_pago = "Cargo por daños"
            elif pago_unico.get("estado") == "pagado":
                estado_pago = "Pagado"
            elif pago_unico.get("estado") == "pendiente_efectivo":
                estado_pago = "Pend. efectivo"
            elif pago_unico.get("estado") == "verificacion_pendiente":
                estado_pago = "En verificación"
            elif pago_unico.get("estado") == "rechazado":
                estado_pago = "Rechazado"
            else:
                estado_pago = "Pendiente"
        else:
            monto = 0.0
            estado_pago = "—"

        filas.append([
            v.get("bicicleta_codigo") or "S/N",
            "Eléctrica" if bici.get("tipo") == "electric_bike" else "Clásica",
            estado_label.get(v.get("estado"), v.get("estado") or "—"),
            v.get("estacion_inicio_nombre") or "—",
            d["estaciones_nombres"].get(v.get("estacion_fin_id"), "—") if v.get("estacion_fin_id") else "—",
            (v.get("fecha_inicio") or "—").replace("T", " ").replace("Z", ""),
            int(v.get("duracion_minutos") or 0),
            monto,
            estado_pago,
            recibo["codigo"] if recibo else "—",
        ])
    return columnas, filas


@router.get("/historial/excel")
async def historial_excel(request: Request, q: str = "", estado: str = ""):
    user = getattr(request.state, "user", {})
    d = _historial_data(user.get("id", ""), q, estado)
    columnas, filas = _historial_columnas_filas(d)
    fila_total = [f"Total: {len(d['viajes'])} viajes"] + [None] * 6 + [sum(f[7] for f in filas), None, None]
    return generar_excel_reporte(
        titulo="UrbanBike — Mi Historial de Viajes",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(d['viajes'])} viajes",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Mis Viajes",
        nombre_archivo="urbanbike_mi_historial.xlsx",
    )


@router.get("/historial/pdf")
async def historial_pdf(request: Request, q: str = "", estado: str = ""):
    user = getattr(request.state, "user", {})
    d = _historial_data(user.get("id", ""), q, estado)
    columnas, filas = _historial_columnas_filas(d)
    fila_total = [f"Total: {len(d['viajes'])} viajes"] + [None] * 6 + [sum(f[7] for f in filas), None, None]
    return generar_pdf_reporte(
        titulo="Mi Historial de Viajes",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(d['viajes'])} viajes",
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo="urbanbike_mi_historial.pdf",
        horizontal=True,
    )


# ── Historial de pagos (punto 2 de docs/Requerimientos_Mejoras_UrbanBike.md) ──
# Modulo separado de historial() de arriba: ese es el historial de VIAJES (con
# el pago embebido por viaje); este es el historial de PAGOS en si -- todo
# registro real de la coleccion "pagos" de este ciclista (viajes, cargos por
# danos), con fecha/estado/metodo filtrables, paginado, y el motivo de
# rechazo cuando aplica. Alcance deliberado: no incluye pagos de membresia
# (esos viven en urbanbike_operativa.pagos de ClickHouse, un backend
# completamente distinto -- ver membresias_repo.py -- y son parte de la fase
# de "Beneficios de membresia", todavia no implementada).

_ESTADOS_PAGO_LABEL = {
    "pendiente":             "Pendiente",
    "pendiente_efectivo":    "Pendiente efectivo",
    "verificacion_pendiente": "En verificación",
    "pagado":                "Aprobado",
    "rechazado":             "Rechazado",
    "cancelado":             "Cancelado",
}
_METODOS_PAGO_LABEL = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}
_PAGOS_POR_PAGINA = 10


def _fecha_pago_efectiva(p: dict) -> str:
    """Mejor fecha disponible para un pago, mas nueva primero: ninguna
    coleccion operativa de este proyecto (viajes/pagos/infracciones/
    bicicletas, verificado en vivo) tiene el created/updated automatico
    de PocketBase -- confiar en sort="-created" tumbaba /ciclista/pagos
    entero apenas PocketBase rechazaba el sort con 400 (bug real,
    reportado y corregido). fecha_generado es el campo real (seteado en
    empleado.py:vig_devolver() al crear el pago); los pagos creados ANTES
    de ese fix no lo tienen, asi que se cae a fecha_pago/fecha_confirmacion
    -- nunca revienta, en el peor caso ordena/filtra con cadena vacia."""
    return p.get("fecha_generado") or p.get("fecha_pago") or p.get("fecha_confirmacion") or ""


def _pagos_ciclista(id_usuario: str) -> list[dict]:
    """Todos los pagos reales de este ciclista, mas recientes primero --
    filtrado por ciclista_id en el propio PocketBase (no como
    gerente.py:_pagos_pb(), que trae los 2000 pagos globales porque esa
    vista es de todos los ciclistas). El orden se hace en Python (ver
    _fecha_pago_efectiva) -- nunca con sort= del lado de PocketBase, que
    exige que el campo exista en el schema de la coleccion."""
    items = _pb().list_records(
        "pagos",
        filter=f'ciclista_id = {filter_literal(id_usuario)}',
        per_page=500,
    ).get("items", [])
    items.sort(key=_fecha_pago_efectiva, reverse=True)
    return items


def _filtrar_pagos_ciclista(pagos: list[dict], estado: str, metodo: str, desde: str, hasta: str) -> list[dict]:
    """Mismo criterio que gerente.py:_filtrar_pagos(), pero la fecha usada
    para el rango es _fecha_pago_efectiva() -- fecha_pago sola queda vacia
    para pagos pendientes o rechazados (nunca llegaron a pagarse), asi que
    filtrar solo por ella excluiria justo los pagos rechazados que este
    modulo necesita mostrar."""
    out = []
    for p in pagos:
        if estado and p.get("estado") != estado:
            continue
        if metodo and p.get("metodo_pago") != metodo:
            continue
        fecha = _fecha_pago_efectiva(p)[:10]
        if desde and fecha and fecha < desde:
            continue
        if hasta and fecha and fecha > hasta:
            continue
        out.append(p)
    return out


@router.get("/pagos", response_class=HTMLResponse)
async def historial_pagos(
    request: Request,
    estado: str = "", metodo: str = "",
    desde: str = "", hasta: str = "",
    pagina: int = 1,
):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    pb_ok = True
    pagos: list[dict] = []
    try:
        pagos = _pagos_ciclista(user.get("id", ""))
    except Exception:
        pb_ok = False

    grupos_completos = {
        gid for gid in {p.get("grupo_reserva_id") for p in pagos if p.get("grupo_reserva_id")}
        if all(p.get("estado") == "pagado" for p in pagos if p.get("grupo_reserva_id") == gid)
    }

    filtrados = _filtrar_pagos_ciclista(pagos, estado, metodo, desde, hasta)
    total = len(filtrados)
    total_paginas = max(1, -(-total // _PAGOS_POR_PAGINA))
    pagina = max(1, min(pagina, total_paginas))
    inicio = (pagina - 1) * _PAGOS_POR_PAGINA
    pagina_items = filtrados[inicio:inicio + _PAGOS_POR_PAGINA]

    return templates.TemplateResponse(request, "ciclista/pagos.html", _ctx(request,
        title="Historial de Pagos", flash=flash, pb_ok=pb_ok,
        pagos=pagina_items, total=total, pagina=pagina, total_paginas=total_paginas,
        estado=estado, metodo=metodo, desde=desde, hasta=hasta,
        estados_pago=_ESTADOS_PAGO_LABEL, metodos_pago=_METODOS_PAGO_LABEL,
        grupos_completos=grupos_completos,
    ))


def _pagos_columnas_filas(pagos: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Fecha", ancho=14),
        ColumnaReporte("Concepto", ancho=18),
        ColumnaReporte("Monto", ancho=12, formato="moneda"),
        ColumnaReporte("Método", ancho=16),
        ColumnaReporte("Estado", ancho=18),
        ColumnaReporte("Comprobante", ancho=16),
        ColumnaReporte("Motivo de rechazo", ancho=32),
    ]
    filas = [
        [
            (_fecha_pago_efectiva(p) or "—")[:10],
            "Cargo por daños" if p.get("tipo") == "cargo_danos" else "Viaje",
            float(p.get("monto_total") or 0),
            _METODOS_PAGO_LABEL.get(p.get("metodo_pago"), p.get("metodo_pago") or "—"),
            _ESTADOS_PAGO_LABEL.get(p.get("estado"), p.get("estado") or "—"),
            p.get("comprobante_numero") or "—",
            p.get("observaciones_pago") or "—" if p.get("estado") == "rechazado" else "—",
        ]
        for p in pagos
    ]
    return columnas, filas


@router.get("/pagos/excel")
async def historial_pagos_excel(request: Request, estado: str = "", metodo: str = "", desde: str = "", hasta: str = ""):
    user = getattr(request.state, "user", {})
    filtrados = _filtrar_pagos_ciclista(_pagos_ciclista(user.get("id", "")), estado, metodo, desde, hasta)
    columnas, filas = _pagos_columnas_filas(filtrados)
    return generar_excel_reporte(
        titulo="UrbanBike — Mi Historial de Pagos",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(filtrados)} pagos",
        columnas=columnas, filas=filas, nombre_hoja="Mis Pagos",
        nombre_archivo="urbanbike_mis_pagos.xlsx",
    )


@router.get("/pagos/pdf")
async def historial_pagos_pdf(request: Request, estado: str = "", metodo: str = "", desde: str = "", hasta: str = ""):
    user = getattr(request.state, "user", {})
    filtrados = _filtrar_pagos_ciclista(_pagos_ciclista(user.get("id", "")), estado, metodo, desde, hasta)
    columnas, filas = _pagos_columnas_filas(filtrados)
    return generar_pdf_reporte(
        titulo="Mi Historial de Pagos",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(filtrados)} pagos",
        columnas=columnas, filas=filas,
        nombre_archivo="urbanbike_mis_pagos.pdf",
        horizontal=True,
    )


def _recibo_real(id_alquiler: str) -> dict | None:
    """Recibo real (codigo, total, fecha_facturacion) -- solo si el
    alquiler llego a estado 'facturado'. Mismo query que ya usa
    historial() para la fila 'Comprobante'."""
    filas = ch.query("""
        SELECT a.id AS id, a.codigo AS codigo, a.total AS total,
               e.fecha AS fecha_facturacion
        FROM urbanbike_operativa.alquileres a FINAL
        JOIN urbanbike_operativa.alquiler_eventos e
            ON e.id_alquiler = a.id AND e.estado_destino = 'facturado'
        WHERE a.estado = 'facturado' AND a.id = %(id)s
    """, {"id": id_alquiler})
    return filas[0] if filas else None


@router.get("/comprobante/{id_alquiler}/pdf")
async def comprobante_alquiler_pdf(request: Request, id_alquiler: str):
    """PDF real del comprobante, reutilizando generar_pdf_reporte() (membrete +
    fuentes ya registradas). Solo permite descargar el comprobante de un
    alquiler que sea del propio ciclista logueado (via el mismo mapa
    viaje<->alquiler que ya usa historial()) y que este 'facturado' -- misma
    regla de siempre, nada inventado para alquileres sin facturar."""
    user = getattr(request.state, "user", {})
    ids_alquiler_propios: set[str] = set()
    try:
        pb = _pb()
        viajes_propios = pb.list_records(
            "viajes", filter=f'ciclista_id = {filter_literal(user.get("id", ""))}', per_page=200,
        ).get("items", [])
        mapa_ids = ch.mapa_alquiler_por_viaje_pocketbase()
        ids_alquiler_propios = {mapa_ids[v["id"]] for v in viajes_propios if v["id"] in mapa_ids}
    except Exception:
        pass

    if id_alquiler not in ids_alquiler_propios:
        request.session["flash"] = {"type": "error", "msg": "Comprobante no encontrado."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    recibo = _recibo_real(id_alquiler)
    if not recibo:
        request.session["flash"] = {"type": "error", "msg": "Este alquiler todavía no está facturado."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    alq = alquileres_repo.obtener(id_alquiler)

    columnas = [
        ColumnaReporte("Campo", ancho=26),
        ColumnaReporte("Detalle", ancho=42),
    ]
    filas = [
        ["Código de alquiler", recibo["codigo"]],
        ["Ciclista", (alq["ciclista_nombre"] if alq else None) or user.get("name") or user.get("email", "")],
        ["Bicicleta", alq["bicicleta_codigo"] if alq else "—"],
        ["Estación de inicio", alq["estacion_inicio_nombre"] if alq else "—"],
        ["Fecha de facturación", recibo["fecha_facturacion"].strftime("%Y-%m-%d %H:%M")],
        ["Monto total", f"${float(recibo['total']):.2f}"],
    ]

    return generar_pdf_reporte(
        titulo="Comprobante de Alquiler",
        subtitulo=f"Código {recibo['codigo']}",
        columnas=columnas,
        filas=filas,
        nombre_archivo=f"urbanbike_comprobante_{recibo['codigo']}.pdf",
        horizontal=False,
    )


# ── Promociones ───────────────────────────────────────────────────────────────

_MODALIDAD_LABEL = {"hora": "Por hora", "dia": "Por día", "semana": "Por semana"}


def _promo_aplica_a_label(promo: dict, categorias: dict[str, str], bicicletas: dict[str, str]) -> str:
    """Texto legible de a que aplica una promocion, resolviendo el
    id_referencia real (categoria/bicicleta) en vez de solo mostrar el
    tipo generico -- gerente/promociones.html solo muestra el tipo
    ("Categoria"), pero aca el ciclista necesita saber CUAL categoria o
    CUAL bicicleta para decidir si le sirve."""
    aplica_a = promo["aplica_a"]
    ref = promo["id_referencia"]
    if aplica_a == "categoria":
        return f"Categoría: {categorias.get(ref, ref)}"
    if aplica_a == "modalidad":
        return f"Modalidad: {_MODALIDAD_LABEL.get(ref, ref)}"
    if aplica_a == "bicicleta":
        return f"Bicicleta: {bicicletas.get(ref, ref)}"
    return "Todas las bicicletas"


@router.get("/promociones", response_class=HTMLResponse)
async def promociones(request: Request):
    """Catalogo de promociones que un ciclista realmente podria
    aprovechar hoy: mismo filtro real que ya usa el precio del catalogo
    (promociones_repo.activas_hoy(), estado + vigencia + dia de semana),
    mas el filtro de agotadas que activas_hoy() no aplica (ver
    promociones_repo.disponibles_hoy())."""
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    es_member = False
    try:
        es_member = membresias_repo.tipo_membresia_real(user.get("email", "")) == "member"
    except Exception:
        pass
    items: list[dict] = []
    ch_ok = True
    try:
        promos = promociones_repo.disponibles_hoy()
        categorias = {str(c["id"]): c["nombre"] for c in promociones_repo.listar_categorias_ref()}
        bicicletas = {str(b["id"]): b["codigo"] for b in promociones_repo.listar_bicicletas_ref()}
        for p in promos:
            items.append({
                "codigo": p["codigo"],
                "nombre": p["nombre"],
                "tipo_descuento": p["tipo_descuento"],
                "valor": float(p["valor"]),
                "aplica_a_label": _promo_aplica_a_label(p, categorias, bicicletas),
                "fecha_fin": p["fecha_fin"],
                # Punto 4: se muestran igual a un ciclista casual (para que
                # sepa que existen y le sirvan de incentivo a suscribirse),
                # pero marcadas como bloqueadas -- promo_aplicable() ya las
                # excluye de verdad del cálculo de precio si no es member.
                "solo_member": bool(p.get("solo_member")),
                "bloqueada": bool(p.get("solo_member")) and not es_member,
            })
        items.sort(key=lambda p: (p["bloqueada"], p["fecha_fin"]))
    except Exception:
        ch_ok = False

    return templates.TemplateResponse(request, "ciclista/promociones.html", _ctx(request,
        title="Promociones", flash=flash, promociones=items, ch_ok=ch_ok, es_member=es_member,
    ))


# ── Membresia ─────────────────────────────────────────────────────────────────

def _luhn_valido(numero: str) -> bool:
    """Algoritmo de Luhn real -- valida el formato de un numero de
    tarjeta (que sea matematicamente posible), nunca si existe de
    verdad. Mismo algoritmo que usa cualquier formulario de pago real
    del lado del cliente antes de tocar una pasarela.

    El Luhn puro NO descarta un numero relleno de un solo digito repetido
    (ej. 16 ceros: suma 0, 0 % 10 == 0 -- pasa Luhn matematicamente) --
    exactamente el caso que pide rechazar
    docs/Requerimientos_Mejoras_UrbanBike.md punto 1 ("rellenos de
    ceros"), asi que se rechaza aparte antes de aplicar el algoritmo."""
    digitos = [int(c) for c in numero if c.isdigit()]
    if not (13 <= len(digitos) <= 19):
        return False
    if len(set(digitos)) == 1:
        return False
    total = 0
    for i, d in enumerate(reversed(digitos)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _marca_tarjeta(numero: str) -> str:
    """Deteccion de marca por prefijo (regla publica de cada red, no
    verifica nada real) -- solo para que el comprobante simulado se vea
    con una marca en vez de 'simulada' generica."""
    digitos = "".join(c for c in numero if c.isdigit())
    if digitos.startswith(("34", "37")):
        return "amex"
    if digitos.startswith("4"):
        return "visa"
    if digitos.startswith(("51", "52", "53", "54", "55")):
        return "mastercard"
    if digitos.startswith("6"):
        return "discover"
    return "simulada"


def _expiracion_valida(mes: str, anio: str) -> tuple[bool, int, int]:
    """Valida que mes/anio sean un mes de calendario real (1-12) y un
    anio de 4 digitos razonable. Devuelve (ok, mes_int, anio_int) --
    mes_int/anio_int solo son validos si ok es True."""
    if not mes.isdigit() or not anio.isdigit():
        return False, 0, 0
    m, a = int(mes), int(anio)
    if not (1 <= m <= 12) or not (2000 <= a <= 2999):
        return False, 0, 0
    return True, m, a


def _margen_minimo_expiracion() -> tuple[int, int]:
    """(anio, mes) del primer mes de calendario que cumple el margen
    minimo de 1 mes desde hoy -- una tarjeta cuyo (anio, mes) de
    caducidad sea anterior a este par no alcanza para registrar una
    membresia (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 1)."""
    hoy = date.today()
    total_meses = hoy.year * 12 + (hoy.month - 1) + 1
    return total_meses // 12, total_meses % 12 + 1


def _codigo_membresia(fila: dict) -> str:
    """Mismo criterio que _generar_comprobante() para pagos de alquiler
    (PocketBase): un codigo legible derivado del id real, no un campo
    guardado aparte -- la tabla membresias no tiene columna 'codigo'."""
    fecha = fila["fecha_inicio"]
    return f"MB-{fecha.strftime('%Y%m%d')}-{str(fila['id'])[-4:].upper()}"


def _factura_pdf(factura: dict, *, usuario_nombre: str, usuario_email: str):
    """PDF real de factura (encabezado + detalle de línea + IVA
    desglosado), compartido entre la factura de membresía y la de
    alquiler -- mismo documento, distinto origen del cargo. Reutiliza
    generar_pdf_reporte() (membrete + fuentes ya registradas)."""
    lineas = facturas_repo.detalle(factura["id"])
    numero_completo = f"{factura['serie']}-{factura['numero']}"
    columnas = [
        ColumnaReporte("Concepto", ancho=34),
        ColumnaReporte("Cantidad", ancho=10, formato="entero"),
        ColumnaReporte("Precio Unit.", ancho=14, formato="moneda"),
        ColumnaReporte("Subtotal", ancho=14, formato="moneda"),
    ]
    filas = [
        [l["concepto"], int(l["cantidad"]), float(l["precio_unitario"]), float(l["subtotal"])]
        for l in lineas
    ]
    filas.append(["Subtotal", None, None, float(factura["subtotal"])])
    filas.append([f"IVA ({int(facturas_repo.IVA_TASA * 100)}%)", None, None, float(factura["impuesto"])])
    fila_total = ["TOTAL", None, None, float(factura["total"])]

    return generar_pdf_reporte(
        titulo=f"Factura {numero_completo}",
        subtitulo=(
            f"Simulación académica — RUC no aplica  ·  Cliente: {usuario_nombre} ({usuario_email})  ·  "
            f"Fecha: {factura['fecha_emision'].strftime('%Y-%m-%d %H:%M')}"
        ),
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo=f"urbanbike_factura_{numero_completo}.pdf",
        horizontal=False,
    )


@router.get("/membresia", response_class=HTMLResponse)
async def membresia(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    ch_ok = True
    estado: dict | None = None
    activa = False
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        if id_usuario:
            estado = membresias_repo.estado_actual(id_usuario)
            activa = membresias_repo.esta_activa(id_usuario)
    except Exception:
        ch_ok = False

    return templates.TemplateResponse(request, "ciclista/membresia.html", _ctx(request,
        title="Membresía", flash=flash, ch_ok=ch_ok, estado=estado, activa=activa,
        precio=membresias_repo.precio_vigente(),
    ))


@router.post("/membresia/cancelar")
async def membresia_cancelar(request: Request, csrf_token: str = Form(...)):
    user = getattr(request.state, "user", {})
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        if not id_usuario:
            raise ValueError("No se pudo resolver el usuario real.")
        resultado = membresias_repo.cancelar(id_usuario)
        if not resultado["ok"]:
            request.session["flash"] = {"type": "error", "msg": resultado["motivo"]}
        elif resultado["reembolsado"]:
            request.session["flash"] = {"type": "success", "msg":
                f"Membresía cancelada — reembolso simulado de ${resultado['monto_reembolsado']:.2f} "
                f"registrado (dentro de las {membresias_repo.VENTANA_REEMBOLSO_HORAS}h desde el cobro)."}
        else:
            request.session["flash"] = {"type": "info", "msg":
                f"Membresía cancelada. Ya pasaron más de {membresias_repo.VENTANA_REEMBOLSO_HORAS}h desde "
                "el cobro de este período, así que no aplica reembolso."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"No se pudo cancelar la membresía: {e}"}
    return RedirectResponse("/ciclista/membresia", status_code=302)


@router.get("/membresia/pagar", response_class=HTMLResponse)
async def membresia_pagar(request: Request):
    """Wizard de 3 pasos (tarjeta simulada -> confirmar -> exito) que
    reemplaza el boton unico -- ver docs/HOJA_DE_RUTA.md. Los 2 primeros
    pasos son 100% client-side (nada se escribe todavia); el POST real
    sigue siendo el mismo /membresia/activar de siempre."""
    user = getattr(request.state, "user", {})
    activa = False
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        if id_usuario:
            activa = membresias_repo.esta_activa(id_usuario)
    except Exception:
        pass
    if activa:
        return RedirectResponse("/ciclista/membresia", status_code=302)

    return templates.TemplateResponse(request, "ciclista/membresia_pagar.html", _ctx(request,
        title="Activar Membresía", precio=membresias_repo.precio_vigente(),
    ))


@router.post("/membresia/activar")
async def membresia_activar(
    request: Request,
    numero_tarjeta:  str = Form(""),
    nombre_titular:  str = Form(""),
    mes_expiracion:  str = Form(""),
    anio_expiracion: str = Form(""),
):
    user = getattr(request.state, "user", {})

    if not _luhn_valido(numero_tarjeta):
        request.session["flash"] = {"type": "error", "msg":
            "El número de tarjeta no es válido (falló la verificación de formato). Prueba con 4242 4242 4242 4242, la tarjeta de pruebas estándar."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
    if not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
        request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta simulada."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)

    exp_ok, mes_exp, anio_exp = _expiracion_valida(mes_expiracion, anio_expiracion)
    if not exp_ok:
        request.session["flash"] = {"type": "error", "msg": "La fecha de expiración de la tarjeta no es válida."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
    anio_margen, mes_margen = _margen_minimo_expiracion()
    if (anio_exp, mes_exp) < (anio_margen, mes_margen):
        request.session["flash"] = {"type": "error", "msg":
            "La tarjeta debe tener al menos 1 mes de vigencia desde hoy para poder suscribirte."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)

    digitos = "".join(c for c in numero_tarjeta if c.isdigit())
    try:
        id_usuario = infracciones_repo.resolver_o_crear_usuario(
            email=user.get("email", ""), nombre_completo=user.get("name", ""), rol="ciclista",
        )
        id_membresia = membresias_repo.activar(
            id_usuario,
            ultimos4=digitos[-4:], marca_tarjeta=_marca_tarjeta(digitos),
            exp_mes=int(mes_expiracion), exp_anio=int(anio_expiracion),
        )
        request.session["flash"] = {"type": "success", "msg": "Membresía activada (pago simulado registrado)."}
        return RedirectResponse(f"/ciclista/membresia/comprobante/{id_membresia}", status_code=302)
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"No se pudo activar la membresía: {e}"}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)


def _construir_factura_membresia(fila: dict, user: dict, codigo: str) -> DatosFactura:
    """Arma la factura con marca UrbanBike (punto 11) para UNA membresía --
    compartida entre membresia_comprobante() (HTML) y
    membresia_comprobante_pdf() (PDF). Una sola línea de concepto (no hay
    recargo/daños/descuento en membresías, a diferencia de los pagos de
    viaje -- ver _construir_factura_pago())."""
    precio = float(fila["precio"])
    subtotal_sin_iva, iva = facturas_repo.desglosar_iva(precio)
    fecha_pago = fila["fecha_registro"].strftime("%Y-%m-%d %H:%M")

    return DatosFactura(
        numero=codigo,
        fecha_emision=fecha_pago,
        fecha_vencimiento=fecha_pago,
        numero_pedido=str(fila["id"]),
        cliente_nombre=user.get("name") or user.get("email", ""),
        cliente_cedula=user.get("cedula", ""),
        cliente_extra=f"Período: {fila['fecha_inicio'].strftime('%d/%m/%Y')} — "
                       f"{fila['fecha_fin'].strftime('%d/%m/%Y')} (30 días)",
        metodo_pago="Tarjeta (simulado)",
        lineas=[LineaFactura("Membresía mensual UrbanBike", 1, precio, precio)],
        subtotal=subtotal_sin_iva,
        iva=iva,
        descuento=0.0,
        total=precio,
        nota="MODO DEMOSTRACIÓN — pago simulado, ningún cargo real se procesó.",
    )


@router.get("/membresia/comprobante/{id_membresia}", response_class=HTMLResponse)
async def membresia_comprobante(request: Request, id_membresia: str):
    user = getattr(request.state, "user", {})
    request.session.pop("flash", None)  # ya se muestra el bloque de exito propio de esta pantalla
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        fila = membresias_repo.obtener(id_membresia, id_usuario) if id_usuario else None
    except Exception:
        fila = None

    if not fila:
        request.session["flash"] = {"type": "error", "msg": "Comprobante no encontrado."}
        return RedirectResponse("/ciclista/membresia", status_code=302)

    codigo = _codigo_membresia(fila)
    return templates.TemplateResponse(request, "ciclista/membresia_comprobante.html", _ctx(request,
        title="Comprobante de Membresía", membresia=fila,
        codigo=codigo, usuario_nombre=user.get("name") or user.get("email", ""),
        factura=_construir_factura_membresia(fila, user, codigo),
        soporte_email=settings.support_email,
    ))


@router.get("/membresia/comprobante/{id_membresia}/pdf")
async def membresia_comprobante_pdf(request: Request, id_membresia: str):
    """PDF con marca UrbanBike, mismo generador que comprobante_pago_pdf()
    (app.reportes.factura.generar_factura_pdf, ver punto 11)."""
    user = getattr(request.state, "user", {})
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        fila = membresias_repo.obtener(id_membresia, id_usuario) if id_usuario else None
    except Exception:
        fila = None

    if not fila:
        request.session["flash"] = {"type": "error", "msg": "Comprobante no encontrado."}
        return RedirectResponse("/ciclista/membresia", status_code=302)

    codigo = _codigo_membresia(fila)
    return generar_factura_pdf(
        _construir_factura_membresia(fila, user, codigo),
        nombre_archivo=f"urbanbike_membresia_{codigo}.pdf",
    )


@router.get("/factura/{id_factura}/pdf")
async def factura_pdf(request: Request, id_factura: str):
    """Factura real (distinta del comprobante): desglose de IVA sobre el
    mismo monto ya cobrado -- ver facturas_repo para el criterio. Ruta
    genérica compartida entre el origen membresía y el origen alquiler
    -- misma tabla real (`facturas`), un solo PDF (_factura_pdf)."""
    user = getattr(request.state, "user", {})
    try:
        id_usuario = membresias_repo.resolver_id_usuario_por_email(user.get("email", ""))
        factura = facturas_repo.obtener(id_factura, id_usuario) if id_usuario else None
    except Exception:
        factura = None

    if not factura:
        request.session["flash"] = {"type": "error", "msg": "Factura no encontrada."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    return _factura_pdf(
        factura, usuario_nombre=user.get("name") or user.get("email", ""),
        usuario_email=user.get("email", ""),
    )


# ── Infracciones ─────────────────────────────────────────────────────────────

def _mis_infracciones(ciclista_id: str) -> list[dict]:
    """ciclista_id siempre de request.state.user -- mismo criterio de
    seguridad que _historial_data()."""
    return _pb().list_records(
        "infracciones",
        filter=f'ciclista_id = {filter_literal(ciclista_id)}',
        sort="-fecha", per_page=200,
    ).get("items", [])


@router.get("/infracciones", response_class=HTMLResponse)
async def infracciones(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    items: list[dict] = []
    try:
        items = _mis_infracciones(user.get("id", ""))
    except Exception:
        pass
    return templates.TemplateResponse(request, "ciclista/infracciones.html", _ctx(request,
        title="Mis Infracciones", flash=flash, infracciones=items,
    ))


def _mis_infracciones_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Tipo", ancho=18),
        ColumnaReporte("Descripción", ancho=40),
        ColumnaReporte("Bicicleta", ancho=14),
        ColumnaReporte("Fecha", ancho=18),
        ColumnaReporte("Estado", ancho=14),
    ]
    filas = [
        [
            i.get("tipo") or "—",
            i.get("descripcion") or "—",
            i.get("bicicleta_codigo") or "—",
            (i.get("fecha") or "—").replace("T", " ").replace("Z", "") if i.get("fecha") else "—",
            "Resuelta" if i.get("resuelta") else "Pendiente",
        ]
        for i in items
    ]
    return columnas, filas


@router.get("/infracciones/excel")
async def infracciones_excel(request: Request):
    user = getattr(request.state, "user", {})
    items = _mis_infracciones(user.get("id", ""))
    columnas, filas = _mis_infracciones_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Mis Infracciones",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(items)} infracciones",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(items)} infracciones", None, None, None, None],
        nombre_hoja="Mis Infracciones",
        nombre_archivo="urbanbike_mis_infracciones.xlsx",
    )


@router.get("/infracciones/pdf")
async def infracciones_pdf(request: Request):
    user = getattr(request.state, "user", {})
    items = _mis_infracciones(user.get("id", ""))
    columnas, filas = _mis_infracciones_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Mis Infracciones",
        subtitulo=f"Ciclista: {user.get('name') or user.get('email', '')}  |  Total: {len(items)} infracciones",
        columnas=columnas,
        filas=filas,
        fila_total=[f"Total: {len(items)} infracciones", None, None, None, None],
        nombre_archivo="urbanbike_mis_infracciones.pdf",
    )


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
            filter=f'ciclista_id = {filter_literal(user.get("id", ""))}',
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


# ── Soporte (chat interno, punto 12 Opción B -- ver docs/HOJA_DE_RUTA.md
#    sección 68) ─────────────────────────────────────────────────────────────

@router.get("/soporte", response_class=HTMLResponse)
async def soporte(request: Request):
    user = getattr(request.state, "user", {})
    flash = request.session.pop("flash", None)
    ciclista_id = user.get("id", "")
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    # Al abrir la conversación, lo que mandó el staff queda leído -- mismo
    # criterio que abrir la campana de notificaciones.
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="ciclista")
    return templates.TemplateResponse(request, "ciclista/soporte.html", _ctx(request,
        title="Soporte", flash=flash, mensajes=mensajes, soy_ciclista=True,
        poll_url="/ciclista/soporte/mensajes", enviar_url="/ciclista/soporte/enviar",
        soporte_email=settings.support_email,
    ))


@router.post("/soporte/enviar")
async def soporte_enviar(request: Request, texto: str = Form(...)):
    user = getattr(request.state, "user", {})
    try:
        mensajes_soporte_repo.enviar(
            ciclista_id=user.get("id", ""), autor_id=user.get("id", ""),
            autor_rol="ciclista", autor_nombre=user.get("name") or user.get("email", ""),
            texto=texto,
        )
    except ValueError as e:
        request.session["flash"] = {"type": "error", "msg": str(e)}
    except Exception:
        request.session["flash"] = {"type": "error", "msg": "No se pudo enviar el mensaje. Intenta de nuevo."}
    return RedirectResponse("/ciclista/soporte", status_code=302)


@router.get("/soporte/mensajes")
async def soporte_mensajes(request: Request):
    """JSON liviano para el sondeo de 4s de la conversación abierta
    (app/static/js/chat-soporte.js) -- misma idea que GET /notificaciones,
    sin recargar la página."""
    user = getattr(request.state, "user", {})
    ciclista_id = user.get("id", "")
    mensajes = mensajes_soporte_repo.listar_hilo(ciclista_id)
    mensajes_soporte_repo.marcar_leidos(ciclista_id, para_rol="ciclista")
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
