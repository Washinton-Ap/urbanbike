"""Rutas para el rol Gerente — analítica sobre ClickHouse y gestión de usuarios."""

import json
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.db import bicicletas_repo, estaciones_repo, notificaciones_repo, promociones_repo, tarifas_repo, clickhouse as ch
from app.db.pocketbase import get_admin_client, registrar_auditoria
from app.middleware.permisos import requiere_permiso
from app.reportes.excel import ColumnaReporte, generar_excel_reporte
from app.reportes.pdf import generar_pdf_reporte
from app.templating import file_url, templates

router = APIRouter(prefix="/gerente", tags=["gerente"])

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
POR_PAGINA = 25


def _ctx(request: Request, **extra) -> dict:
    return {"user": getattr(request.state, "user", None), **extra}


def _pb():
    import app.db.pocketbase as pbmod
    try:
        return get_admin_client()
    except Exception:
        pbmod._admin_client = None
        return get_admin_client()


def _flash(request: Request, url: str, tipo: str, msg: str) -> RedirectResponse:
    request.session["flash"] = {"type": tipo, "msg": msg}
    return RedirectResponse(url, status_code=302)


_ACCION_TIPO = {"crear": "crear", "editar": "editar", "eliminar": "eliminar"}
_MODULO_PLURAL = {"bicicleta": "bicicletas", "estación": "estaciones", "tarifa": "tarifas", "usuario": "usuarios", "promoción": "promociones"}


def _log(request: Request, accion: str, detalle: str) -> None:
    """Registra una acción de CRUD del gerente en la bitácora de cambios y en la auditoría."""
    user = getattr(request.state, "user", {}) or {}
    try:
        _pb().create_record("bitacora_cambios", {
            "usuario_nombre": user.get("name") or user.get("email", "Gerente"),
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
        user.get("name") or user.get("email", "Gerente"), user.get("email", ""),
        accion_tipo, modulo, detalle, request,
        usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
    )


DB_TACTICA = "urbanbike_tactica"
DB_ESTRATEGICA = "urbanbike_estrategica"

NOMBRES_MES_CORTO = ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun",
                      "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Joins fijos de urbanbike_tactica.fact_viajes usados por _build_where: la
# membresia real se resuelve via dim_tarifa (no hay columna id_membresia en
# fact_viajes ni tabla dim_membresia en esta base), y el tipo de bicicleta via
# dim_tipos_bicicleta.es_electrica (no hay id_tipo_bicicleta: el grano real es
# id_modelo). Ver docs/HOJA_DE_RUTA.md -- este reporte agregaba sobre
# "urbanbike" (el CSV de Citibike, 3.7M filas) en vez de sobre los datos
# reales del negocio.
_JOINS_TACTICA = f"""
    LEFT JOIN {DB_TACTICA}.dim_tarifa df ON f.id_tarifa = df.id_tarifa
    LEFT JOIN {DB_TACTICA}.dim_tipos_bicicleta t ON f.id_modelo = t.id_modelo
"""


def _fecha_query(valor: str, nombre: str) -> date:
    """Valida un parametro de fecha que llega crudo desde query string (GET)
    antes de usarlo en cualquier SQL. Antes de esta correccion, fecha_inicio/
    fecha_fin se interpolaban directo en el texto del WHERE (ver auditoria de
    seguridad, docs/HOJA_DE_RUTA.md) -- un valor como
    "2023-01-01') UNION SELECT ...--" se ejecutaba tal cual. Ahora, si no es
    una fecha AAAA-MM-DD real, la request se rechaza aqui (400) y nunca llega
    a construir SQL."""
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"{nombre} inválida: '{valor}'. Formato esperado AAAA-MM-DD.",
        )


def _dia_semana_query(valor: str) -> int | None:
    """"" (sin filtro) o un digito 1-7. Cualquier otro valor se rechaza (400)
    en vez de interpolarse en el WHERE -- mismo criterio que _fecha_query."""
    if not valor:
        return None
    if valor.isdigit() and 1 <= int(valor) <= 7:
        return int(valor)
    raise HTTPException(status_code=400, detail=f"dia_semana inválido: '{valor}'. Debe ser 1-7.")


def _build_where(fecha_inicio: date, fecha_fin: date, membresia: str, tipo_bici: str) -> tuple[str, dict]:
    parts = [
        "f.es_prueba = 0",
        "f.fecha_inicio >= %(fecha_inicio)s",
        "f.fecha_inicio <= %(fecha_fin)s",
    ]
    params: dict = {
        "fecha_inicio": datetime.combine(fecha_inicio, time.min),
        "fecha_fin": datetime.combine(fecha_fin, time(23, 59, 59)),
    }
    if membresia == "member":
        parts.append("df.tipo_membresia = 'member'")
    elif membresia == "casual":
        parts.append("df.tipo_membresia = 'casual'")
    if tipo_bici == "classic_bike":
        parts.append("t.es_electrica = 0")
    elif tipo_bici == "electric_bike":
        parts.append("t.es_electrica = 1")
    return "WHERE " + " AND ".join(parts), params


def _build_where_resumen(fecha_inicio: date, fecha_fin: date, membresia: str, tipo_bici: str) -> tuple[str, dict]:
    """Mismos filtros que _build_where, pero sobre resumen_viajes_diario
    (ver docs/HOJA_DE_RUTA.md): es_prueba ya se excluyo al llenar el
    resumen en el ETL, no hace falta filtrarlo aqui otra vez."""
    parts = [
        "r.fecha >= %(fecha_inicio)s",
        "r.fecha <= %(fecha_fin)s",
    ]
    params: dict = {"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin}
    if membresia == "member":
        parts.append("r.tipo_membresia = 'member'")
    elif membresia == "casual":
        parts.append("r.tipo_membresia = 'casual'")
    if tipo_bici == "classic_bike":
        parts.append("r.es_electrica = 0")
    elif tipo_bici == "electric_bike":
        parts.append("r.es_electrica = 1")
    return "WHERE " + " AND ".join(parts), params


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    flash = request.session.pop("flash", None)
    kpis: dict = {}
    ch_ok = True
    dow_labels: list = []
    dow_values: list = []
    top_labels: list = []
    top_values: list = []
    try:
        kpis = ch.query_one("""
            SELECT
              count()                            AS total_viajes,
              countDistinct(id_estacion_inicio)   AS total_estaciones,
              round(avg(duracion_min), 2)         AS dur_prom_min,
              round(avg(distancia_km), 2)         AS dist_prom_km,
              countIf(id_membresia = 2)           AS viajes_member,
              countIf(id_membresia = 1)           AS viajes_casual,
              countIf(id_tipo_bicicleta = 1)      AS viajes_clasica,
              countIf(id_tipo_bicicleta = 2)      AS viajes_electrica
            FROM fact_viajes
        """) or {}

        dow_rows = {r["dia"]: r["viajes"] for r in ch.query("""
            SELECT toDayOfWeek(fecha_inicio) AS dia, count() AS viajes
            FROM fact_viajes GROUP BY dia ORDER BY dia
        """)}
        dow_labels = DIAS
        dow_values = [dow_rows.get(i, 0) for i in range(1, 8)]

        top10 = ch.query("""
            SELECT e.nombre_estacion AS nombre, count() AS viajes
            FROM fact_viajes f
            LEFT JOIN dim_estaciones e ON f.id_estacion_inicio = e.id_estacion
            GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT 10
        """)
        top_labels = [str(r.get("nombre") or "N/A")[:30] for r in top10]
        top_values = [r["viajes"] for r in top10]

    except Exception:
        ch_ok = False

    return templates.TemplateResponse(request, "gerente/dashboard.html", _ctx(request,
        title="Dashboard — Gerente", flash=flash, kpis=kpis, ch_ok=ch_ok,
        dow_labels=json.dumps(dow_labels),
        dow_values=json.dumps(dow_values),
        top_labels=json.dumps(top_labels),
        top_values=json.dumps(top_values),
    ))


DIA_SEMANA_LABEL = {
    "1": "Lunes", "2": "Martes", "3": "Miércoles", "4": "Jueves",
    "5": "Viernes", "6": "Sábado", "7": "Domingo",
}


def _build_where_citibike(fecha_inicio: date, fecha_fin: date, dia_semana: int | None,
                           membresia: str, tipo_bici: str) -> tuple[str, dict]:
    parts = [
        "fecha_inicio >= %(fecha_inicio)s",
        "fecha_inicio <= %(fecha_fin)s",
    ]
    params: dict = {
        "fecha_inicio": datetime.combine(fecha_inicio, time.min),
        "fecha_fin": datetime.combine(fecha_fin, time(23, 59, 59)),
    }
    if dia_semana is not None:
        parts.append("toDayOfWeek(fecha_inicio) = %(dia_semana)s")
        params["dia_semana"] = dia_semana
    if membresia == "member":
        parts.append("id_membresia = 2")
    elif membresia == "casual":
        parts.append("id_membresia = 1")
    if tipo_bici == "classic_bike":
        parts.append("id_tipo_bicicleta = 1")
    elif tipo_bici == "electric_bike":
        parts.append("id_tipo_bicicleta = 2")
    return "WHERE " + " AND ".join(parts), params


def _citibike_subtitulo(fecha_inicio: str, fecha_fin: str, dia_semana: str, membresia: str, tipo_bici: str) -> str:
    mem_map = {"all": "Todos", "member": "Miembros", "casual": "Casuales"}
    bici_map = {"all": "Todos", "classic_bike": "Clásica", "electric_bike": "Eléctrica"}
    return (
        "Dataset académico de Citibike NYC — NO es la operación real de UrbanBike  |  "
        f"Período: {fecha_inicio} → {fecha_fin}  |  "
        f"Día: {DIA_SEMANA_LABEL.get(dia_semana, 'Todos')}  |  "
        f"Membresía: {mem_map.get(membresia, 'Todos')}  |  "
        f"Tipo: {bici_map.get(tipo_bici, 'Todos')}"
    )


def _citibike_kpis_y_graficas(fecha_inicio: date, fecha_fin: date, dia_semana: int | None,
                               membresia: str, tipo_bici: str) -> dict:
    """KPI general + día de semana, reutilizados de dashboard(), sobre el
    dataset académico de Citibike (urbanbike, CSV NYC 2023) -- nunca sobre
    urbanbike_tactica. La tabla de estaciones se maneja aparte, paginada
    (ver _citibike_estaciones_paginadas). Ver docs/HOJA_DE_RUTA.md."""
    kpis: dict = {}
    ch_ok = True
    dow_labels: list = []
    dow_values: list = []
    where, params = _build_where_citibike(fecha_inicio, fecha_fin, dia_semana, membresia, tipo_bici)
    try:
        kpis = ch.query_one(f"""
            SELECT
              count()                            AS total_viajes,
              countDistinct(id_estacion_inicio)   AS total_estaciones,
              round(avg(duracion_min), 2)         AS dur_prom_min,
              round(avg(distancia_km), 2)         AS dist_prom_km,
              countIf(id_membresia = 2)           AS viajes_member,
              countIf(id_membresia = 1)           AS viajes_casual,
              countIf(id_tipo_bicicleta = 1)      AS viajes_clasica,
              countIf(id_tipo_bicicleta = 2)      AS viajes_electrica
            FROM fact_viajes
            {where}
        """, params) or {}

        dow_rows = {r["dia"]: r["viajes"] for r in ch.query(f"""
            SELECT toDayOfWeek(fecha_inicio) AS dia, count() AS viajes
            FROM fact_viajes {where} GROUP BY dia ORDER BY dia
        """, params)}
        dow_labels = DIAS
        dow_values = [dow_rows.get(i, 0) for i in range(1, 8)]
    except Exception:
        ch_ok = False

    return {"kpis": kpis, "ch_ok": ch_ok, "dow_labels": dow_labels, "dow_values": dow_values}


def _citibike_estaciones_paginadas(where: str, params: dict, pagina: int) -> tuple[list[dict], int, int]:
    """Tabla paginada real de estaciones (mismo patrón que reportes())
    aplicada a las ~2,150 estaciones únicas del dataset Citibike, en vez
    de solo un top-10 estático."""
    total_filas = ch.scalar(f"SELECT countDistinct(id_estacion_inicio) FROM fact_viajes {where}", params) or 0
    total_paginas = max(1, (total_filas + POR_PAGINA - 1) // POR_PAGINA)
    pagina = max(1, min(pagina, total_paginas))
    offset = (pagina - 1) * POR_PAGINA

    estaciones = ch.query(f"""
        SELECT e.nombre_estacion AS nombre, count() AS viajes,
               round(avg(duracion_min), 1) AS dur_prom
        FROM fact_viajes f
        LEFT JOIN dim_estaciones e ON f.id_estacion_inicio = e.id_estacion
        {where}
        GROUP BY e.nombre_estacion
        ORDER BY viajes DESC
        LIMIT {POR_PAGINA} OFFSET {offset}
    """, params)
    return estaciones, total_filas, total_paginas


@router.get("/analisis-citibike", response_class=HTMLResponse)
def analisis_citibike(
    request: Request,
    fecha_inicio: str = Query("2023-09-30"),
    fecha_fin: str = Query("2023-10-31"),
    dia_semana: str = Query(""),
    membresia: str = Query("all"),
    tipo_bici: str = Query("all"),
    pagina: int = Query(1, ge=1),
):
    """Pantalla propia y separada para el dataset académico de Citibike --
    NUNCA se mezcla con gerente/reportes.html ni gerente/informe.html
    (esas dos usan urbanbike_tactica, datos reales del negocio, corregido
    hoy). Ver docs/HOJA_DE_RUTA.md."""
    flash = request.session.pop("flash", None)
    fi = _fecha_query(fecha_inicio, "fecha_inicio")
    ff = _fecha_query(fecha_fin, "fecha_fin")
    ds = _dia_semana_query(dia_semana)
    datos = _citibike_kpis_y_graficas(fi, ff, ds, membresia, tipo_bici)
    where, params = _build_where_citibike(fi, ff, ds, membresia, tipo_bici)

    estaciones: list[dict] = []
    total_filas = 0
    total_paginas = 1
    if datos["ch_ok"]:
        try:
            estaciones, total_filas, total_paginas = _citibike_estaciones_paginadas(where, params, pagina)
        except Exception:
            pass

    return templates.TemplateResponse(request, "gerente/analisis_citibike.html", _ctx(request,
        title="Análisis Histórico — Dataset Citibike", flash=flash,
        kpis=datos["kpis"], ch_ok=datos["ch_ok"],
        dow_labels=json.dumps(datos["dow_labels"]),
        dow_values=json.dumps(datos["dow_values"]),
        estaciones=estaciones, total_filas=total_filas,
        total_paginas=total_paginas, pagina=pagina,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin, dia_semana=dia_semana,
        membresia=membresia, tipo_bici=tipo_bici,
        dias_semana=DIA_SEMANA_LABEL,
    ))


def _citibike_estaciones_columnas_filas(filas_raw: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Estación", ancho=46),
        ColumnaReporte("Viajes", ancho=14, formato="entero"),
        ColumnaReporte("Duración Prom. (min)", ancho=22, formato="decimal1"),
    ]
    filas = [
        [r.get("nombre") or "N/A", int(r.get("viajes", 0)), float(r.get("dur_prom", 0))]
        for r in filas_raw
    ]
    return columnas, filas


def _citibike_estaciones_todas(where: str, params: dict, limite: int) -> list[dict]:
    return ch.query(f"""
        SELECT e.nombre_estacion AS nombre, count() AS viajes,
               round(avg(duracion_min), 1) AS dur_prom
        FROM fact_viajes f
        LEFT JOIN dim_estaciones e ON f.id_estacion_inicio = e.id_estacion
        {where}
        GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT {limite}
    """, params)


@router.get("/analisis-citibike/excel")
def analisis_citibike_excel(
    request: Request,
    fecha_inicio: str = Query("2023-09-30"),
    fecha_fin: str = Query("2023-10-31"),
    dia_semana: str = Query(""),
    membresia: str = Query("all"),
    tipo_bici: str = Query("all"),
):
    # Excel soporta miles de filas sin problema -- 5000 cubre con margen
    # las ~2,150 estaciones reales del dataset, sin cortar ninguna.
    fi = _fecha_query(fecha_inicio, "fecha_inicio")
    ff = _fecha_query(fecha_fin, "fecha_fin")
    ds = _dia_semana_query(dia_semana)
    where, params = _build_where_citibike(fi, ff, ds, membresia, tipo_bici)
    filas_raw = _citibike_estaciones_todas(where, params, limite=5000)
    columnas, filas = _citibike_estaciones_columnas_filas(filas_raw)
    fila_total = [f"Total: {len(filas_raw)} estaciones", sum(f[1] for f in filas), None]

    return generar_excel_reporte(
        titulo="UrbanBike — Análisis Histórico (Dataset Académico Citibike NYC 2023)",
        subtitulo=_citibike_subtitulo(fecha_inicio, fecha_fin, dia_semana, membresia, tipo_bici),
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Citibike NYC 2023",
        nombre_archivo="urbanbike_academico_citibike_estaciones.xlsx",
    )


@router.get("/analisis-citibike/pdf")
def analisis_citibike_pdf(
    request: Request,
    fecha_inicio: str = Query("2023-09-30"),
    fecha_fin: str = Query("2023-10-31"),
    dia_semana: str = Query(""),
    membresia: str = Query("all"),
    tipo_bici: str = Query("all"),
):
    # Un PDF con las ~2,150 estaciones reales serian decenas de paginas
    # ilegibles; se limita a las 100 con mas viajes y se avisa el total
    # real en el subtitulo y en la fila de totales, para no esconder que
    # es un recorte.
    LIMITE_PDF = 100
    fi = _fecha_query(fecha_inicio, "fecha_inicio")
    ff = _fecha_query(fecha_fin, "fecha_fin")
    ds = _dia_semana_query(dia_semana)
    where, params = _build_where_citibike(fi, ff, ds, membresia, tipo_bici)
    total_real = ch.scalar(f"SELECT countDistinct(id_estacion_inicio) FROM fact_viajes {where}", params) or 0
    filas_raw = _citibike_estaciones_todas(where, params, limite=LIMITE_PDF)
    columnas, filas = _citibike_estaciones_columnas_filas(filas_raw)
    fila_total = [f"Top {len(filas_raw)} de {total_real} estaciones", sum(f[1] for f in filas), None]

    subtitulo = (
        _citibike_subtitulo(fecha_inicio, fecha_fin, dia_semana, membresia, tipo_bici)
        + f"  |  Mostrando las {LIMITE_PDF} estaciones con más viajes (de {total_real} totales)"
    )

    return generar_pdf_reporte(
        titulo="Análisis Histórico (Dataset Académico Citibike NYC 2023)",
        subtitulo=subtitulo,
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo="urbanbike_academico_citibike_estaciones.pdf",
        horizontal=False,
    )


@router.get("/reportes", response_class=HTMLResponse)
def reportes(
    request: Request,
    fecha_inicio: str = Query("2026-06-07"),
    fecha_fin: str = Query("2026-07-29"),
    membresia: str = Query("all"),
    tipo_bici: str = Query("all"),
    pagina: int = Query(1, ge=1),
):
    flash = request.session.pop("flash", None)
    fi = _fecha_query(fecha_inicio, "fecha_inicio")
    ff = _fecha_query(fecha_fin, "fecha_fin")
    # Filtra sobre resumen_viajes_diario (precalculado por el ETL cada
    # hora), no sobre fact_viajes en vivo -- ver docs/HOJA_DE_RUTA.md.
    where, params = _build_where_resumen(fi, ff, membresia, tipo_bici)
    offset = (pagina - 1) * POR_PAGINA

    estaciones: list[dict] = []
    total_viajes = 0
    total_filas = 0
    total_paginas = 1
    chart_est_labels: list = []
    chart_est_values: list = []
    chart_dow_values: list = []
    chart_tipo_labels: list = []
    chart_tipo_values: list = []
    chart_tendencia_labels: list = []
    chart_tendencia_values: list = []
    ch_ok = True

    try:
        cnt = ch.query_one(f"""
            SELECT countDistinct(r.id_estacion_inicio) AS total_est,
                   sum(r.viajes) AS total_viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            {where}
        """, params)
        total_filas = cnt.get("total_est", 0) if cnt else 0
        total_viajes = cnt.get("total_viajes", 0) if cnt else 0
        total_paginas = max(1, (total_filas + POR_PAGINA - 1) // POR_PAGINA)

        estaciones = ch.query(f"""
            SELECT
              e.nombre_estacion AS nombre,
              sum(r.viajes)     AS viajes,
              round(sum(r.duracion_total_min) / sum(r.viajes), 1) AS dur_prom
            FROM {DB_TACTICA}.resumen_viajes_diario r
            LEFT JOIN {DB_TACTICA}.dim_estaciones e ON r.id_estacion_inicio = e.id_estacion
            {where}
            GROUP BY e.nombre_estacion
            ORDER BY viajes DESC
            LIMIT {POR_PAGINA} OFFSET {offset}
        """, params)

        top10 = ch.query(f"""
            SELECT e.nombre_estacion AS nombre, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            LEFT JOIN {DB_TACTICA}.dim_estaciones e ON r.id_estacion_inicio = e.id_estacion
            {where}
            GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT 10
        """, params)
        chart_est_labels = [str(r.get("nombre") or "N/A")[:28] for r in top10]
        chart_est_values = [r["viajes"] for r in top10]

        dow_rows = {r["dia"]: r["viajes"] for r in ch.query(f"""
            SELECT toDayOfWeek(r.fecha) AS dia, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            {where} GROUP BY dia ORDER BY dia
        """, params)}
        chart_dow_values = [dow_rows.get(i, 0) for i in range(1, 8)]

        tipo_rows = ch.query(f"""
            SELECT multiIf(r.es_electrica = 1, 'Eléctrica', 'Clásica') AS nombre,
                   round(sum(r.duracion_total_min) / sum(r.viajes), 1) AS dur_prom
            FROM {DB_TACTICA}.resumen_viajes_diario r
            {where}
            GROUP BY r.es_electrica ORDER BY r.es_electrica
        """, params)
        chart_tipo_labels = [str(r.get("nombre") or "N/A") for r in tipo_rows]
        chart_tipo_values = [r["dur_prom"] for r in tipo_rows]

        tendencia_rows = ch.query(f"""
            SELECT r.fecha AS dia, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            {where}
            GROUP BY dia ORDER BY dia
        """, params)
        chart_tendencia_labels = [r["dia"].strftime("%d/%m") if hasattr(r["dia"], "strftime") else str(r["dia"]) for r in tendencia_rows]
        chart_tendencia_values = [r["viajes"] for r in tendencia_rows]

    except Exception:
        ch_ok = False

    return templates.TemplateResponse(request, "gerente/reportes.html", _ctx(request,
        title="Reportes — Gerente", flash=flash, ch_ok=ch_ok,
        estaciones=estaciones,
        total_viajes=total_viajes, total_filas=total_filas,
        total_paginas=total_paginas, pagina=pagina,
        fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        membresia=membresia, tipo_bici=tipo_bici,
        chart_est_labels=json.dumps(chart_est_labels),
        chart_est_values=json.dumps(chart_est_values),
        chart_dow_labels=json.dumps(DIAS),
        chart_dow_values=json.dumps(chart_dow_values),
        chart_tipo_labels=json.dumps(chart_tipo_labels),
        chart_tipo_values=json.dumps(chart_tipo_values),
        chart_tendencia_labels=json.dumps(chart_tendencia_labels),
        chart_tendencia_values=json.dumps(chart_tendencia_values),
    ))


@router.get("/reportes/excel")
def export_excel(
    request: Request,
    fecha_inicio: str = Query("2026-06-07"),
    fecha_fin: str = Query("2026-07-29"),
    membresia: str = Query("all"),
    tipo_bici: str = Query("all"),
):
    fi = _fecha_query(fecha_inicio, "fecha_inicio")
    ff = _fecha_query(fecha_fin, "fecha_fin")
    where, params = _build_where(fi, ff, membresia, tipo_bici)
    rows = ch.query(f"""
        SELECT
          e.nombre_estacion             AS nombre,
          count()                       AS viajes,
          round(avg(f.duracion_min), 1) AS dur_prom
        FROM {DB_TACTICA}.fact_viajes f
        LEFT JOIN {DB_TACTICA}.dim_estaciones e ON f.id_estacion_inicio = e.id_estacion
        {_JOINS_TACTICA}
        {where}
        GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT 1000
    """, params)

    mem_map  = {"all": "Todos", "member": "Miembros", "casual": "Casuales"}
    bici_map = {"all": "Todos", "classic_bike": "Clásica", "electric_bike": "Eléctrica"}

    columnas = [
        ColumnaReporte("Estación", ancho=46),
        ColumnaReporte("Viajes", ancho=12, formato="entero"),
        ColumnaReporte("Duración Prom. (min)", ancho=24, formato="decimal1"),
    ]
    filas = [
        [row.get("nombre") or "N/A", int(row.get("viajes", 0)),
         float(row.get("dur_prom", 0))]
        for row in rows
    ]
    fila_total = [f"Total: {len(rows)} estaciones", sum(int(r.get("viajes", 0)) for r in rows), None]

    return generar_excel_reporte(
        titulo="UrbanBike — Reporte Analítico",
        subtitulo=(
            f"Período: {fecha_inicio} → {fecha_fin}  |  "
            f"Membresía: {mem_map.get(membresia, 'Todos')}  |  "
            f"Tipo: {bici_map.get(tipo_bici, 'Todos')}"
        ),
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Reporte Estaciones",
        nombre_archivo=f"urbanbike_reporte_{fecha_inicio}_{fecha_fin}.xlsx",
    )


# ── Reportes de Pagos ─────────────────────────────────────────────────────────

ESTADOS_PAGO = ["pendiente", "pagado", "verificacion_pendiente", "pendiente_efectivo", "rechazado", "cancelado"]
METODOS_PAGO = ["efectivo", "tarjeta", "transferencia"]


def _pagos_pb() -> list[dict]:
    return get_admin_client().list_records("pagos", sort="-fecha_pago", per_page=2000).get("items", [])


def _ultimo_mes_cerrado() -> tuple[int, int]:
    """Ultimo mes calendario ya terminado (punto 2.6, propuesta b para
    /gerente/informe) -- mismo criterio real que ya usa
    etl/09_calcular_estrategica.py:mes_completo() (un mes cuenta como
    cerrado recien cuando su ultimo dia ya paso), pero calculado aqui en
    vivo con aritmetica de fechas simple: el mes actual nunca esta
    cerrado, asi que el ultimo cerrado es siempre el mes calendario
    anterior a hoy."""
    hoy = date.today()
    anio, mes = hoy.year, hoy.month - 1
    if mes == 0:
        mes, anio = 12, anio - 1
    return anio, mes


def _ingresos_reales_mes(pagos: list[dict], anio: int, mes: int) -> float:
    """Ingresos reales (pagos.monto_total, solo estado='pagado') de un mes
    puntual -- misma formula real que ya usaba reportes_pagos() para el
    mes actual, ahora parametrizada por (anio, mes) para poder
    reutilizarla tambien desde informe() con el ultimo mes cerrado, sin
    duplicar el calculo."""
    mes_str = f"{anio:04d}-{mes:02d}"
    return sum(
        float(p.get("monto_total") or 0) for p in pagos
        if p.get("estado") == "pagado" and (p.get("fecha_pago") or "").startswith(mes_str)
    )


def _filtrar_pagos(pagos: list[dict], estado: str, metodo: str, fecha_inicio: str, fecha_fin: str) -> list[dict]:
    out = []
    for p in pagos:
        if estado != "all" and p.get("estado") != estado:
            continue
        if metodo != "all" and p.get("metodo_pago") != metodo:
            continue
        fecha = (p.get("fecha_pago") or "")[:10]
        if fecha_inicio and fecha and fecha < fecha_inicio:
            continue
        if fecha_fin and fecha and fecha > fecha_fin:
            continue
        out.append(p)
    return out


@router.get("/reportes/pagos", response_class=HTMLResponse)
def reportes_pagos(
    request: Request,
    estado: str = Query("all"),
    metodo: str = Query("all"),
    fecha_inicio: str = Query(""),
    fecha_fin: str = Query(""),
):
    from datetime import datetime, timezone
    import calendar

    flash = request.session.pop("flash", None)
    pb_ok = True
    pagos: list[dict] = []
    try:
        pagos = _pagos_pb()
    except Exception:
        pb_ok = False

    ahora = datetime.now(timezone.utc)
    hoy_str = ahora.strftime("%Y-%m-%d")
    mes_str = ahora.strftime("%Y-%m")
    dias_mes = calendar.monthrange(ahora.year, ahora.month)[1]

    pagados = [p for p in pagos if p.get("estado") == "pagado"]

    ingresos_dia = sum(float(p.get("monto_total") or 0) for p in pagados if (p.get("fecha_pago") or "").startswith(hoy_str))
    pagados_mes = [p for p in pagados if (p.get("fecha_pago") or "").startswith(mes_str)]
    ingresos_mes = _ingresos_reales_mes(pagos, ahora.year, ahora.month)
    ticket_promedio = (sum(float(p.get("monto_total") or 0) for p in pagados) / len(pagados)) if pagados else 0.0

    # Ingresos por día del mes actual
    ingresos_por_dia = [0.0] * dias_mes
    for p in pagados_mes:
        fecha = p.get("fecha_pago") or ""
        try:
            dia = int(fecha[8:10])
            if 1 <= dia <= dias_mes:
                ingresos_por_dia[dia - 1] += float(p.get("monto_total") or 0)
        except (ValueError, IndexError):
            pass
    chart_dias_labels = [str(d) for d in range(1, dias_mes + 1)]
    chart_dias_values = [round(v, 2) for v in ingresos_por_dia]

    # Distribución por método de pago (solo pagados)
    metodo_counts = {m: 0 for m in METODOS_PAGO}
    for p in pagados:
        m = p.get("metodo_pago")
        if m in metodo_counts:
            metodo_counts[m] += 1
    chart_metodo_labels = ["Efectivo", "Tarjeta", "Transferencia"]
    chart_metodo_values = [metodo_counts["efectivo"], metodo_counts["tarjeta"], metodo_counts["transferencia"]]

    # Pagos por estado
    estado_labels_map = {
        "pagado": "Pagado", "pendiente": "Pendiente",
        "verificacion_pendiente": "Verificación pendiente",
        "pendiente_efectivo": "Pendiente efectivo",
        "rechazado": "Rechazado", "cancelado": "Cancelado",
    }
    estado_counts: dict[str, int] = {}
    for p in pagos:
        e = p.get("estado") or "pendiente"
        estado_counts[e] = estado_counts.get(e, 0) + 1
    chart_estado_labels = [estado_labels_map.get(e, e) for e in estado_counts]
    chart_estado_values = list(estado_counts.values())

    pagos_filtrados = _filtrar_pagos(pagos, estado, metodo, fecha_inicio, fecha_fin)

    return templates.TemplateResponse(request, "gerente/reportes_pagos.html", _ctx(request,
        title="Reportes de Pagos", flash=flash, pb_ok=pb_ok,
        ingresos_dia=ingresos_dia, ingresos_mes=ingresos_mes, ticket_promedio=ticket_promedio,
        chart_dias_labels=json.dumps(chart_dias_labels),
        chart_dias_values=json.dumps(chart_dias_values),
        chart_metodo_labels=json.dumps(chart_metodo_labels),
        chart_metodo_values=json.dumps(chart_metodo_values),
        chart_estado_labels=json.dumps(chart_estado_labels),
        chart_estado_values=json.dumps(chart_estado_values),
        pagos=pagos_filtrados,
        estado=estado, metodo=metodo, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
        estados_pago=ESTADOS_PAGO, metodos_pago=METODOS_PAGO,
    ))


def _pagos_reporte_subtitulo(estado: str, metodo: str, fecha_inicio: str, fecha_fin: str) -> str:
    estado_map = {"all": "Todos", "pagado": "Pagado", "pendiente": "Pendiente",
                  "verificacion_pendiente": "Verificación pendiente", "pendiente_efectivo": "Pendiente efectivo",
                  "rechazado": "Rechazado", "cancelado": "Cancelado"}
    metodo_map = {"all": "Todos", "efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}
    return (
        f"Estado: {estado_map.get(estado, estado)}  |  Método: {metodo_map.get(metodo, metodo)}  |  "
        f"Período: {fecha_inicio or '—'} → {fecha_fin or '—'}"
    )


def _pagos_reporte_columnas_filas(pagos: list[dict]) -> tuple[list[ColumnaReporte], list[list], list]:
    metodo_label = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia"}
    estado_label = {"pagado": "Pagado", "pendiente": "Pendiente", "verificacion_pendiente": "Verificación pendiente",
                    "pendiente_efectivo": "Pendiente efectivo", "rechazado": "Rechazado", "cancelado": "Cancelado"}

    columnas = [
        ColumnaReporte("Nº comprobante", ancho=22),
        ColumnaReporte("Ciclista", ancho=26),
        ColumnaReporte("Fecha viaje", ancho=14),
        ColumnaReporte("Duración (min)", ancho=16, formato="entero"),
        ColumnaReporte("Método", ancho=16),
        ColumnaReporte("Monto", ancho=14, formato="moneda"),
        ColumnaReporte("Estado", ancho=22),
        ColumnaReporte("Confirmado por", ancho=24),
    ]
    filas = [
        [
            p.get("comprobante_numero") or "—",
            p.get("ciclista_nombre") or "—",
            (p.get("fecha_pago") or "—")[:10],
            int(p.get("duracion_minutos") or 0),
            metodo_label.get(p.get("metodo_pago"), p.get("metodo_pago") or "—"),
            float(p.get("monto_total") or 0),
            estado_label.get(p.get("estado"), p.get("estado") or "—"),
            p.get("confirmado_por_empleado_nombre") or "—",
        ]
        for p in pagos
    ]
    fila_total = [f"Total: {len(pagos)} pagos", None, None, None, None,
                  sum(float(p.get("monto_total") or 0) for p in pagos), None, None]
    return columnas, filas, fila_total


@router.get("/reportes/pagos/excel")
def reportes_pagos_excel(
    request: Request,
    estado: str = Query("all"),
    metodo: str = Query("all"),
    fecha_inicio: str = Query(""),
    fecha_fin: str = Query(""),
):
    pagos = _filtrar_pagos(_pagos_pb(), estado, metodo, fecha_inicio, fecha_fin)
    columnas, filas, fila_total = _pagos_reporte_columnas_filas(pagos)

    return generar_excel_reporte(
        titulo="UrbanBike — Reporte de Transacciones",
        subtitulo=_pagos_reporte_subtitulo(estado, metodo, fecha_inicio, fecha_fin),
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Reporte de Pagos",
        nombre_archivo=f"urbanbike_pagos_{fecha_inicio or 'todos'}_{fecha_fin or 'todos'}.xlsx",
    )


@router.get("/reportes/pagos/pdf")
def reportes_pagos_pdf(
    request: Request,
    estado: str = Query("all"),
    metodo: str = Query("all"),
    fecha_inicio: str = Query(""),
    fecha_fin: str = Query(""),
):
    pagos = _filtrar_pagos(_pagos_pb(), estado, metodo, fecha_inicio, fecha_fin)
    columnas, filas, fila_total = _pagos_reporte_columnas_filas(pagos)

    return generar_pdf_reporte(
        titulo="Reporte de Transacciones",
        subtitulo=_pagos_reporte_subtitulo(estado, metodo, fecha_inicio, fecha_fin),
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo=f"urbanbike_pagos_{fecha_inicio or 'todos'}_{fecha_fin or 'todos'}.pdf",
    )


_ROLES_EMPLEADO = ["empleado-operacion", "empleado-mantenimiento", "empleado-vigilancia"]
_ROLES_EMPLEADO_LABELS = {
    "empleado-operacion":     "Operación",
    "empleado-mantenimiento": "Mantenimiento",
    "empleado-vigilancia":    "Vigilancia",
}


def _roles_empleado_map(pb) -> dict[str, str]:
    """slug -> id de rol, solo para los 3 roles de empleado."""
    roles = pb.list_records("roles", per_page=50).get("items", [])
    return {r.get("slug"): r["id"] for r in roles if r.get("slug") in _ROLES_EMPLEADO}


def _empleados_pb() -> list[dict]:
    pb = get_admin_client()
    items = pb.list_records("users", expand="rol", sort="email", per_page=200).get("items", [])
    empleados: list[dict] = []
    for u in items:
        rol_obj = (u.get("expand") or {}).get("rol") or {}
        slug = (rol_obj.get("slug") or "").lower()
        if "empleado" in slug:
            empleados.append({
                "id": u.get("id", ""),
                "nombre": u.get("name") or u.get("email", ""),
                "email": u.get("email", ""),
                "rol": rol_obj.get("nombre") or rol_obj.get("slug") or "Sin rol",
                "rol_slug": slug,
                "verificado": bool(u.get("verified")),
                "activo": bool(u.get("activo")),
                "motivo_bloqueo": u.get("motivo_bloqueo") or "",
                "fecha_registro": (u.get("created") or "")[:10],
                "avatar": u.get("avatar") or "",
            })
    return empleados


@router.get("/empleados", response_class=HTMLResponse)
def empleados(request: Request):
    flash = request.session.pop("flash", None)
    empleados_list: list[dict] = []
    pb_ok = True
    try:
        empleados_list = _empleados_pb()
    except Exception:
        pb_ok = False
    return templates.TemplateResponse(request, "gerente/empleados.html", _ctx(request,
        title="Empleados — Gerente", flash=flash,
        empleados=empleados_list, pb_ok=pb_ok,
        roles_empleado=_ROLES_EMPLEADO, roles_empleado_labels=_ROLES_EMPLEADO_LABELS,
    ))


@router.post("/empleados/crear")
def empleados_crear(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    name: str = Form(""),
    rol_slug: str = Form(...),
):
    if rol_slug not in _ROLES_EMPLEADO:
        return _flash(request, "/gerente/empleados", "error", "Rol no válido. Solo puedes crear empleados.")
    try:
        pb = _pb()
        rol_id = _roles_empleado_map(pb).get(rol_slug)
        if not rol_id:
            return _flash(request, "/gerente/empleados", "error", "No se encontró el rol solicitado.")
        # verified=True: cuenta creada a mano por Gerente, no por registro
        # público -- sin esto el login la bloquearía pidiendo un código de
        # verificación que nunca se envió (ver app/routers/auth.py).
        payload: dict = {
            "email": email, "password": password, "passwordConfirm": password,
            "emailVisibility": True, "rol": rol_id, "activo": True, "verified": True,
        }
        if name:
            payload["name"] = name
        pb.create_record("users", payload)
        _log(request, "Crear usuario", f"Empleado creado: {email} ({_ROLES_EMPLEADO_LABELS.get(rol_slug, rol_slug)})")
        return _flash(request, "/gerente/empleados", "success", "Empleado creado correctamente.")
    except Exception as e:
        return _flash(request, "/gerente/empleados", "error", str(e))


@router.post("/empleados/{uid}/cambiar-rol")
def empleados_cambiar_rol(request: Request, uid: str, rol_slug: str = Form(...)):
    if rol_slug not in _ROLES_EMPLEADO:
        return _flash(request, "/gerente/empleados", "error", "Rol no válido. Solo puedes asignar roles de empleado.")
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid, expand="rol")
        rol_actual_slug = ((usuario.get("expand") or {}).get("rol") or {}).get("slug", "")
        if rol_actual_slug not in _ROLES_EMPLEADO:
            return _flash(request, "/gerente/empleados", "error",
                          "Solo puedes cambiar el rol de usuarios que ya son empleados.")
        rol_id = _roles_empleado_map(pb).get(rol_slug)
        if not rol_id:
            return _flash(request, "/gerente/empleados", "error", "No se encontró el rol solicitado.")
        pb.update_record("users", uid, {"rol": rol_id})
        _log(request, "Editar usuario",
             f"Rol de {usuario.get('email', uid)} cambiado a {_ROLES_EMPLEADO_LABELS.get(rol_slug, rol_slug)}")
        return _flash(request, "/gerente/empleados", "success", "Rol actualizado.")
    except Exception as e:
        return _flash(request, "/gerente/empleados", "error", str(e))


@router.post("/empleados/{uid}/bloquear")
def empleados_bloquear(request: Request, uid: str, motivo_bloqueo: str = Form("")):
    """Gerente no tenia antes ninguna forma de bloquear un empleado (solo
    Admin, via /admin/usuarios/{uid}/toggle-activo, sin motivo). Mismo
    guard que cambiar-rol: solo aplica sobre usuarios que ya son
    empleados, para que Gerente no pueda tocar cuentas fuera de su
    alcance."""
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid, expand="rol")
        rol_actual_slug = ((usuario.get("expand") or {}).get("rol") or {}).get("slug", "")
        if rol_actual_slug not in _ROLES_EMPLEADO:
            return _flash(request, "/gerente/empleados", "error",
                          "Solo puedes bloquear usuarios que ya son empleados.")
        pb.update_record("users", uid, {"activo": False, "motivo_bloqueo": motivo_bloqueo})
        _log(request, "Editar usuario",
             f"Empleado {usuario.get('email', uid)} bloqueado" + (f": {motivo_bloqueo}" if motivo_bloqueo else ""))
        return _flash(request, "/gerente/empleados", "success", "Empleado bloqueado.")
    except Exception as e:
        return _flash(request, "/gerente/empleados", "error", str(e))


@router.post("/empleados/{uid}/reactivar")
def empleados_reactivar(request: Request, uid: str):
    try:
        pb = _pb()
        usuario = pb.get_record("users", uid, expand="rol")
        rol_actual_slug = ((usuario.get("expand") or {}).get("rol") or {}).get("slug", "")
        if rol_actual_slug not in _ROLES_EMPLEADO:
            return _flash(request, "/gerente/empleados", "error",
                          "Solo puedes reactivar usuarios que ya son empleados.")
        pb.update_record("users", uid, {"activo": True, "motivo_bloqueo": ""})
        _log(request, "Editar usuario", f"Empleado {usuario.get('email', uid)} reactivado")
        return _flash(request, "/gerente/empleados", "success", "Empleado reactivado.")
    except Exception as e:
        return _flash(request, "/gerente/empleados", "error", str(e))


@router.get("/empleados/excel")
def empleados_excel(request: Request):
    empleados_list = _empleados_pb()

    columnas = [
        ColumnaReporte("Nombre", ancho=32),
        ColumnaReporte("Tipo de empleado", ancho=24),
        ColumnaReporte("Correo electrónico", ancho=38),
        ColumnaReporte("Estado de cuenta", ancho=18),
        ColumnaReporte("Fecha de registro", ancho=18),
    ]
    claves = ["nombre", "rol", "email", "verificado", "fecha_registro"]
    filas = []
    for emp in empleados_list:
        fila = []
        for key in claves:
            valor = emp.get(key, "")
            if key == "verificado":
                valor = "Verificado" if valor else "Pendiente"
            fila.append(valor)
        filas.append(fila)

    return generar_excel_reporte(
        titulo="UrbanBike — Empleados del Sistema",
        subtitulo=f"Total: {len(empleados_list)} empleados",
        columnas=columnas,
        filas=filas,
        nombre_hoja="Empleados",
        nombre_archivo=f"urbanbike_empleados_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


# ── Bicicletas — WorkPanel (lista+filtro+paginación+4 modos, ver sección 26) ───

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


@router.get("/bicicletas", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:leer"))])
def bicicletas_list(
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
    return templates.TemplateResponse(request, "gerente/bicicletas.html", _ctx(request,
        title="Bicicletas", flash=flash, items=filas, total=total,
        page=max(1, page), per_page=per_page, total_paginas=max(1, -(-total // per_page)),
        q=q, marca=marca, categoria=categoria, estado=estado,
        marcas=bicicletas_repo.listar_marcas(), categorias=bicicletas_repo.listar_categorias(),
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
def bicicletas_excel(
    request: Request,
    q: str = Query(""), marca: str = Query(""), categoria: str = Query(""), estado: str = Query(""),
):
    items, total = bicicletas_repo.listar(q=q, marca=marca, categoria=categoria, estado=estado, per_page=10000)
    columnas, filas = _bicicletas_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Bicicletas", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas, nombre_hoja="Bicicletas",
        nombre_archivo=f"urbanbike_bicicletas_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/bicicletas/pdf")
def bicicletas_pdf(
    request: Request,
    q: str = Query(""), marca: str = Query(""), categoria: str = Query(""), estado: str = Query(""),
):
    items, total = bicicletas_repo.listar(q=q, marca=marca, categoria=categoria, estado=estado, per_page=10000)
    columnas, filas = _bicicletas_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Bicicletas", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_bicicletas_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/bicicletas/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:crear"))])
def bicicletas_nueva(request: Request):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "gerente/bicicletas_form.html", _ctx(request,
        title="Nueva bicicleta", flash=flash, modo="crear", bici=None,
        modelos=bicicletas_repo.listar_modelos(), estaciones=bicicletas_repo.listar_estaciones(),
    ))


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
        return _flash(request, "/gerente/bicicletas/nueva", "error", error_foto)
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, "/gerente/bicicletas/nueva", "error", "Modelo no válido.")
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
        return _flash(request, "/gerente/bicicletas", "success", f"Bicicleta {bici['codigo']} registrada correctamente.")
    except Exception as e:
        return _flash(request, "/gerente/bicicletas/nueva", "error", str(e))


@router.get("/bicicletas/{bid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("bicicletas:leer"))])
def bicicletas_detalle(request: Request, bid: str, modo: str = Query("ver")):
    flash = request.session.pop("flash", None)
    bici = bicicletas_repo.obtener(bid)
    if not bici:
        return _flash(request, "/gerente/bicicletas", "error", "Bicicleta no encontrada.")
    if not bici.get("foto_url"):
        fotos = bicicletas_repo.fotos_por_codigo([bici["codigo"]], request=request)
        bici["foto_url"] = fotos.get(bici["codigo"], "")
    n_alquileres = bicicletas_repo.contar_alquileres(bid)
    return templates.TemplateResponse(request, "gerente/bicicletas_form.html", _ctx(request,
        title=f"Bicicleta {bici['codigo']}", flash=flash, modo="editar" if modo == "editar" else "ver",
        bici=bici, n_alquileres=n_alquileres,
        modelos=bicicletas_repo.listar_modelos(), estaciones=bicicletas_repo.listar_estaciones(),
    ))


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
        return _flash(request, f"/gerente/bicicletas/{bid}?modo=editar", "error", error_foto)
    try:
        modelo = next((m for m in bicicletas_repo.listar_modelos() if str(m["id"]) == id_modelo), None)
        if not modelo:
            return _flash(request, f"/gerente/bicicletas/{bid}?modo=editar", "error", "Modelo no válido.")
        fecha = datetime.strptime(fecha_adquisicion, "%Y-%m-%d").date() if fecha_adquisicion else date.today()
        bicicletas_repo.actualizar(
            bid, codigo=codigo, id_modelo=id_modelo, estado=estado, id_estacion=id_estacion,
            numero_serie=numero_serie, fecha_adquisicion=fecha, observacion=observacion,
            es_electrica=bool(modelo["es_electrica"]),
        )
        if tiene_foto:
            _guardar_foto_si_hay(codigo, bid, foto)
        _log(request, "Editar bicicleta", f"Bicicleta actualizada: {codigo or bid}")
        return _flash(request, f"/gerente/bicicletas/{bid}", "success", "Bicicleta actualizada.")
    except Exception as e:
        return _flash(request, f"/gerente/bicicletas/{bid}?modo=editar", "error", str(e))


@router.post("/bicicletas/{bid}/eliminar", dependencies=[Depends(requiere_permiso("bicicletas:eliminar"))])
def bicicletas_eliminar(request: Request, bid: str):
    bici = bicicletas_repo.obtener(bid)
    codigo = bici["codigo"] if bici else bid
    ok, motivo = bicicletas_repo.eliminar(bid)
    if ok:
        _log(request, "Eliminar bicicleta", f"Bicicleta eliminada: {codigo}")
        return _flash(request, "/gerente/bicicletas", "success", f"Bicicleta {codigo} eliminada.")
    return _flash(request, f"/gerente/bicicletas/{bid}", "error", motivo)


# ── Estaciones — WorkPanel (lista+filtro+paginación+4 modos, ver sección 26) ───

@router.get("/estaciones", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("estaciones:leer"))])
def estaciones_list(
    request: Request,
    q: str = Query(""), activa: str = Query(""), page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    per_page = 10
    filas, total = estaciones_repo.listar(q=q, activa=activa, page=page, per_page=per_page)
    # El mapa muestra siempre la red completa (sin paginar/filtrar) -- es un
    # resumen visual, no la tabla del WorkPanel.
    todas, _ = estaciones_repo.listar(per_page=1000)
    return templates.TemplateResponse(request, "gerente/estaciones.html", _ctx(request,
        title="Estaciones", flash=flash, items=filas, total=total,
        page=max(1, page), per_page=per_page, total_paginas=max(1, -(-total // per_page)),
        q=q, activa=activa, estaciones_json=json.dumps(todas, default=str),
    ))


def _estaciones_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=12),
        ColumnaReporte("Nombre", ancho=24),
        ColumnaReporte("Dirección", ancho=28),
        ColumnaReporte("Capacidad", ancho=12, formato="entero"),
        ColumnaReporte("Latitud", ancho=12, formato="decimal2"),
        ColumnaReporte("Longitud", ancho=12, formato="decimal2"),
        ColumnaReporte("Estado", ancho=12),
    ]
    filas = [
        [
            e["codigo"], e["nombre"], e.get("direccion") or "—",
            e.get("capacidad") or 0, e.get("latitud") or 0, e.get("longitud") or 0,
            "Activa" if e.get("activa") else "Inactiva",
        ]
        for e in items
    ]
    return columnas, filas


@router.get("/estaciones/excel")
def estaciones_excel(request: Request, q: str = Query(""), activa: str = Query("")):
    items, total = estaciones_repo.listar(q=q, activa=activa, per_page=10000)
    columnas, filas = _estaciones_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Estaciones", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas, nombre_hoja="Estaciones",
        nombre_archivo=f"urbanbike_estaciones_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/estaciones/pdf")
def estaciones_pdf(request: Request, q: str = Query(""), activa: str = Query("")):
    items, total = estaciones_repo.listar(q=q, activa=activa, per_page=10000)
    columnas, filas = _estaciones_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Estaciones", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_estaciones_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/estaciones/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("estaciones:crear"))])
def estaciones_nueva(request: Request):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "gerente/estaciones_form.html", _ctx(request,
        title="Nueva estación", flash=flash, modo="crear", est=None,
    ))


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
    capacidad: int = Form(0), latitud: str = Form(""), longitud: str = Form(""),
    activa: str = Form("true"),
):
    error = _validar_estacion_form(codigo, nombre, latitud, longitud)
    if error:
        return _flash(request, "/gerente/estaciones/nueva", "error", error)
    try:
        nuevo_id = estaciones_repo.crear(
            codigo=codigo.strip(), nombre=nombre.strip(), direccion=direccion,
            latitud=float(latitud), longitud=float(longitud), capacidad=capacidad,
            activa=activa == "true",
        )
        est = estaciones_repo.obtener(nuevo_id)
        _log(request, "Crear estación", f"Estación creada: {est['codigo']} — {est['nombre']}")
        return _flash(request, "/gerente/estaciones", "success", f"Estación {est['codigo']} creada.")
    except Exception as e:
        return _flash(request, "/gerente/estaciones/nueva", "error", str(e))


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


@router.get("/estaciones/{eid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("estaciones:leer"))])
def estaciones_detalle(request: Request, eid: str, modo: str = Query("ver")):
    flash = request.session.pop("flash", None)
    est = estaciones_repo.obtener(eid)
    if not est:
        return _flash(request, "/gerente/estaciones", "error", "Estación no encontrada.")
    n_bicis = estaciones_repo.contar_bicicletas(eid)
    n_alquileres = estaciones_repo.contar_alquileres(eid)
    return templates.TemplateResponse(request, "gerente/estaciones_form.html", _ctx(request,
        title=f"Estación {est['codigo']}", flash=flash, modo="editar" if modo == "editar" else "ver",
        est=est, n_bicis=n_bicis, n_alquileres=n_alquileres,
    ))


@router.post("/estaciones/{eid}/editar", dependencies=[Depends(requiere_permiso("estaciones:actualizar"))])
def estaciones_editar(
    request: Request, eid: str,
    codigo: str = Form(...), nombre: str = Form(...), direccion: str = Form(""),
    capacidad: int = Form(0), latitud: str = Form(""), longitud: str = Form(""),
    activa: str = Form("true"),
):
    error = _validar_estacion_form(codigo, nombre, latitud, longitud)
    if error:
        return _flash(request, f"/gerente/estaciones/{eid}?modo=editar", "error", error)
    try:
        estaciones_repo.actualizar(
            eid, codigo=codigo.strip(), nombre=nombre.strip(), direccion=direccion,
            latitud=float(latitud), longitud=float(longitud), capacidad=capacidad,
            activa=activa == "true",
        )
        _log(request, "Editar estación", f"Estación actualizada: {codigo}")
        return _flash(request, f"/gerente/estaciones/{eid}", "success", "Estación actualizada.")
    except Exception as e:
        return _flash(request, f"/gerente/estaciones/{eid}?modo=editar", "error", str(e))


@router.post("/estaciones/{eid}/eliminar", dependencies=[Depends(requiere_permiso("estaciones:eliminar"))])
def estaciones_eliminar(request: Request, eid: str):
    est = estaciones_repo.obtener(eid)
    codigo = est["codigo"] if est else eid
    ok, motivo = estaciones_repo.eliminar(eid)
    if ok:
        _log(request, "Eliminar estación", f"Estación eliminada: {codigo}")
        return _flash(request, "/gerente/estaciones", "success", f"Estación {codigo} eliminada.")
    return _flash(request, f"/gerente/estaciones/{eid}", "error", motivo)


# ── Tarifas ──────────────────────────────────────────────────────────────────

@router.get("/tarifas", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("tarifas:leer"))])
def tarifas_list(request: Request):
    flash = request.session.pop("flash", None)
    items = tarifas_repo.listar()
    return templates.TemplateResponse(request, "gerente/tarifas.html", _ctx(request,
        title="Tarifas", items=items, flash=flash,
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
        titulo="UrbanBike — Tarifas", subtitulo=f"Total: {len(items)} registros",
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
    """Devuelve un mensaje de error, o '' si el formulario es valido."""
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
        return _flash(request, "/gerente/tarifas", "error", error)
    try:
        tarifas_repo.crear(
            id_categoria=id_categoria, tipo_membresia=tipo_membresia, modalidad=modalidad,
            precio=precio, minutos_gracia=minutos_gracia, recargo_minuto=recargo_minuto,
            vigente_desde=datetime.strptime(vigente_desde, "%Y-%m-%d").date(),
            vigente_hasta=datetime.strptime(vigente_hasta, "%Y-%m-%d").date(),
            estado=estado,
        )
        _log(request, "Crear tarifa", f"Tarifa creada: {tipo_membresia} / {modalidad}")
        return _flash(request, "/gerente/tarifas", "success", "Tarifa creada.")
    except Exception as e:
        return _flash(request, "/gerente/tarifas", "error", str(e))


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
        return _flash(request, "/gerente/tarifas", "error", error)
    try:
        tarifas_repo.actualizar(
            tid, id_categoria=id_categoria, tipo_membresia=tipo_membresia, modalidad=modalidad,
            precio=precio, minutos_gracia=minutos_gracia, recargo_minuto=recargo_minuto,
            vigente_desde=datetime.strptime(vigente_desde, "%Y-%m-%d").date(),
            vigente_hasta=datetime.strptime(vigente_hasta, "%Y-%m-%d").date(),
            estado=estado,
        )
        _log(request, "Editar tarifa", f"Tarifa actualizada: {tipo_membresia} / {modalidad} (id: {tid})")
        return _flash(request, "/gerente/tarifas", "success", "Tarifa actualizada.")
    except Exception as e:
        return _flash(request, "/gerente/tarifas", "error", str(e))


@router.post("/tarifas/{tid}/eliminar", dependencies=[Depends(requiere_permiso("tarifas:eliminar"))])
def tarifas_eliminar(request: Request, tid: str):
    tarifa = tarifas_repo.obtener(tid)
    etiqueta = f"{tarifa['categoria']}/{tarifa['tipo_membresia']}/{tarifa['modalidad']}" if tarifa else tid
    ok, motivo = tarifas_repo.eliminar(tid)
    if ok:
        _log(request, "Eliminar tarifa", f"Tarifa eliminada: {etiqueta}")
        return _flash(request, "/gerente/tarifas", "success", "Tarifa eliminada.")
    return _flash(request, "/gerente/tarifas", "error", motivo)


@router.get("/informe", response_class=HTMLResponse)
def informe(request: Request):
    """Punto 2.6 del Plan V2, propuesta (b) (docs/superpowers/plans/
    2026-08-21-punto-2.6-auditoria-diseno.md): antes agregaba "toda la
    vida" sin ningun periodo, sin poder compararse con nada, y mostraba
    "ingresos estimados" (viajes x tarifa promedio general) en vez de un
    ingreso real. Ahora acota todo al ultimo mes ya cerrado (mismo
    criterio real que etl/09_calcular_estrategica.py:mes_completo(), ver
    _ultimo_mes_cerrado()) y reemplaza el ingreso estimado por el ingreso
    real que ya calcula reportes_pagos() para ese mismo mes
    (_ingresos_reales_mes(), reutilizada, no duplicada)."""
    flash = request.session.pop("flash", None)
    ch_ok = True
    anio, mes = _ultimo_mes_cerrado()
    periodo_yyyymm = anio * 100 + mes

    total_viajes = 0
    precio_promedio = 0.0
    top5: list[dict] = []
    tipo_labels: list = []
    tipo_values: list = []
    membresia_labels: list = []
    membresia_values: list = []
    top5_labels: list = []
    top5_values: list = []

    try:
        # Lee resumen_viajes_diario (precalculado por el ETL cada hora),
        # no fact_viajes en vivo -- ver docs/HOJA_DE_RUTA.md. Acotado al
        # ultimo mes cerrado (antes agregaba todo el historico sin
        # ningun periodo, sin poder compararse con nada -- punto 2.6).
        total_row = ch.query_one(f"""
            SELECT sum(viajes) AS total FROM {DB_TACTICA}.resumen_viajes_diario
            WHERE toYYYYMM(fecha) = %(periodo)s
        """, {"periodo": periodo_yyyymm})
        total_viajes = total_row.get("total", 0) if total_row else 0

        top5 = ch.query(f"""
            SELECT e.nombre_estacion AS nombre, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            LEFT JOIN {DB_TACTICA}.dim_estaciones e ON r.id_estacion_inicio = e.id_estacion
            WHERE toYYYYMM(r.fecha) = %(periodo)s
            GROUP BY e.nombre_estacion ORDER BY viajes DESC LIMIT 5
        """, {"periodo": periodo_yyyymm})
        top5_labels = [str(r.get("nombre") or "N/A") for r in top5]
        top5_values = [r["viajes"] for r in top5]

        tipo_rows = ch.query(f"""
            SELECT multiIf(r.es_electrica = 1, 'Eléctrica', 'Clásica') AS nombre, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            WHERE toYYYYMM(r.fecha) = %(periodo)s
            GROUP BY r.es_electrica ORDER BY r.es_electrica
        """, {"periodo": periodo_yyyymm})
        tipo_labels = [str(r.get("nombre") or "N/A") for r in tipo_rows]
        tipo_values = [r["viajes"] for r in tipo_rows]

        membresia_rows = ch.query(f"""
            SELECT r.tipo_membresia AS nombre, sum(r.viajes) AS viajes
            FROM {DB_TACTICA}.resumen_viajes_diario r
            WHERE toYYYYMM(r.fecha) = %(periodo)s
            GROUP BY r.tipo_membresia
        """, {"periodo": periodo_yyyymm})
        membresia_labels = [str(r.get("nombre") or "N/A") for r in membresia_rows]
        membresia_values = [r["viajes"] for r in membresia_rows]
    except Exception:
        ch_ok = False

    try:
        precios = ch.query("""
            SELECT precio FROM urbanbike_operativa.tarifas FINAL
            WHERE modalidad = 'hora' AND estado = 'vigente'
              AND today() BETWEEN vigente_desde AND vigente_hasta
        """)
        precios_validos = [float(p["precio"]) for p in precios]
        if precios_validos:
            precio_promedio = sum(precios_validos) / len(precios_validos)
    except Exception:
        pass

    try:
        ingresos_reales = _ingresos_reales_mes(_pagos_pb(), anio, mes)
    except Exception:
        ingresos_reales = 0.0

    periodo_label = f"{NOMBRES_MES_CORTO[mes]} {anio}"

    return templates.TemplateResponse(request, "gerente/informe.html", _ctx(request,
        title="Informe General — Gerente", flash=flash, ch_ok=ch_ok,
        titulo="Informe General", subtitulo=f"Reporte de indicadores clave — {periodo_label} (último mes cerrado)",
        periodo_label=periodo_label,
        total_viajes=total_viajes,
        precio_promedio=precio_promedio,
        ingresos_reales=ingresos_reales,
        top5=top5,
        tipo_labels=json.dumps(tipo_labels),
        tipo_values=json.dumps(tipo_values),
        membresia_labels=json.dumps(membresia_labels),
        membresia_values=json.dumps(membresia_values),
        top5_labels=json.dumps(top5_labels),
        top5_values=json.dumps(top5_values),
    ))


# ══════════════════════════════════════════════════════════════════════════════
# INFORME ESTRATÉGICO — evolución mensual (nivel estratégico, ver docs/HOJA_DE_RUTA.md)
# ══════════════════════════════════════════════════════════════════════════════

def _int_o_none(valor: str) -> int | None:
    """Convierte el valor crudo de un <select> de filtro (querystring,
    siempre str) a int, o None si viene vacío ("Año desde"/"Mes desde"
    sin elegir) o no es un entero válido -- evita el 422 que FastAPI
    tiraría si estos parámetros fueran tipados como int | None
    directamente (una cadena vacía no es un int válido para Pydantic,
    a diferencia de los filtros str existentes en el resto del archivo,
    donde "" sí es un valor válido)."""
    try:
        return int(valor) if valor else None
    except ValueError:
        return None


def _estrategico_meses(
    *, anio_desde: int | None = None, mes_desde: int | None = None,
    anio_hasta: int | None = None, mes_hasta: int | None = None,
) -> list[dict]:
    """Lee resumen_mensual_ingresos + resumen_mensual_demanda de
    urbanbike_estrategica (precalculadas por etl/09_calcular_estrategica.py)
    y las combina por (anio, mes) -- sin agregar fact_viajes en vivo, mismo
    criterio ya aplicado al nivel tactico (ver docs/HOJA_DE_RUTA.md
    sección 33). resumen_mensual_demanda tiene grano por estación; se
    re-agrega aquí por mes (sum/avg ponderado sobre una tabla ya chica,
    no sobre el hecho crudo -- misma distinción de la sección 33).
    Muestra todos los meses que ya tengan fila real, cualquiera que sea
    el número -- no asume que sea exactamente uno.

    anio_desde/mes_desde/anio_hasta/mes_hasta: filtro opcional de rango de
    mes/año, aplicado en Python sobre el resultado ya agregado (no en el
    SELECT de ClickHouse) -- la tabla es chica (11 estaciones × meses
    reales), mismo criterio de "agregación cara vs. lookup barato" que ya
    usa esta función. Solo filtra qué filas ya calculadas se devuelven, no
    cambia la agregación en sí."""
    ingresos_rows = ch.query(f"""
        SELECT anio, mes, total_alquileres, ingresos_brutos, descuentos,
               recargos, gastos, ganancia_neta
        FROM {DB_ESTRATEGICA}.resumen_mensual_ingresos FINAL
        ORDER BY anio, mes
    """)
    demanda_rows = ch.query(f"""
        SELECT anio, mes,
               sum(total_viajes) AS total_viajes_mes,
               sum(total_viajes * duracion_prom_min) / sum(total_viajes) AS duracion_prom_min
        FROM {DB_ESTRATEGICA}.resumen_mensual_demanda FINAL
        GROUP BY anio, mes
        ORDER BY anio, mes
    """)
    demanda_map = {(r["anio"], r["mes"]): r for r in demanda_rows}

    meses = []
    for r in ingresos_rows:
        d = demanda_map.get((r["anio"], r["mes"]), {})
        meses.append({
            "anio": r["anio"], "mes": r["mes"],
            "periodo_label": f"{NOMBRES_MES_CORTO[r['mes']]} {r['anio']}",
            "total_alquileres": int(r["total_alquileres"]),
            "ingresos_brutos": float(r["ingresos_brutos"]),
            "descuentos": float(r["descuentos"]),
            "recargos": float(r["recargos"]),
            "gastos": float(r["gastos"]),
            "ganancia_neta": float(r["ganancia_neta"]),
            "total_viajes": int(d.get("total_viajes_mes") or 0),
            "duracion_prom_min": round(float(d.get("duracion_prom_min") or 0), 1),
        })
    if anio_desde is not None and mes_desde is not None:
        meses = [m for m in meses if (m["anio"], m["mes"]) >= (anio_desde, mes_desde)]
    if anio_hasta is not None and mes_hasta is not None:
        meses = [m for m in meses if (m["anio"], m["mes"]) <= (anio_hasta, mes_hasta)]
    return meses


@router.get("/estrategico", response_class=HTMLResponse)
def estrategico(request: Request, anio_desde: str = Query(""), mes_desde: str = Query(""),
                 anio_hasta: str = Query(""), mes_hasta: str = Query("")):
    flash = request.session.pop("flash", None)
    ch_ok = True
    meses: list[dict] = []
    meses_disponibles: list[dict] = []
    anio_desde, mes_desde = _int_o_none(anio_desde), _int_o_none(mes_desde)
    anio_hasta, mes_hasta = _int_o_none(anio_hasta), _int_o_none(mes_hasta)

    try:
        meses_disponibles = _estrategico_meses()
        meses = _estrategico_meses(anio_desde=anio_desde, mes_desde=mes_desde,
                                    anio_hasta=anio_hasta, mes_hasta=mes_hasta)
    except Exception:
        ch_ok = False

    chart_labels = [m["periodo_label"] for m in meses]
    chart_ganancia = [m["ganancia_neta"] for m in meses]
    chart_viajes = [m["total_viajes"] for m in meses]

    anios_disponibles = sorted({m["anio"] for m in meses_disponibles})
    meses_num_disponibles = sorted({m["mes"] for m in meses_disponibles})

    # Querystring del filtro activo, para reenviar a los exports -- solo
    # incluye los parametros que realmente vienen seteados (ya convertidos
    # a int/None arriba). Emitir los 4 siempre, aunque sea con valor vacio,
    # obligaria a /estrategico/excel|pdf a aceptar "" como valor de un
    # int -- mismo motivo por el que las 3 rutas reciben estos 4 filtros
    # como str y los convierten con _int_o_none() en vez de tiparlos
    # directo como int | None (a diferencia de los filtros str existentes
    # como en gerente/bicicletas.html, donde "" ya es un valor valido).
    filtro_qs = urllib.parse.urlencode({
        k: v for k, v in {
            "anio_desde": anio_desde, "mes_desde": mes_desde,
            "anio_hasta": anio_hasta, "mes_hasta": mes_hasta,
        }.items() if v is not None
    })

    return templates.TemplateResponse(request, "gerente/estrategico.html", _ctx(request,
        title="Informe Estratégico — Gerente", flash=flash, ch_ok=ch_ok,
        titulo="Informe Estratégico", subtitulo="Evolución mensual — urbanbike_estrategica (precalculado)",
        meses=meses, anios_disponibles=anios_disponibles, meses_num_disponibles=meses_num_disponibles,
        nombres_mes=NOMBRES_MES_CORTO, filtro_qs=filtro_qs,
        anio_desde=anio_desde, mes_desde=mes_desde, anio_hasta=anio_hasta, mes_hasta=mes_hasta,
        chart_labels=json.dumps(chart_labels),
        chart_ganancia=json.dumps(chart_ganancia),
        chart_viajes=json.dumps(chart_viajes),
    ))


def _estrategico_columnas_filas(meses: list[dict]) -> tuple[list[ColumnaReporte], list[list], list]:
    columnas = [
        ColumnaReporte("Período", ancho=14),
        ColumnaReporte("Alquileres", ancho=12, formato="entero"),
        ColumnaReporte("Ingresos brutos", ancho=16, formato="moneda"),
        ColumnaReporte("Descuentos", ancho=14, formato="moneda"),
        ColumnaReporte("Recargos", ancho=12, formato="moneda"),
        ColumnaReporte("Ganancia neta*", ancho=16, formato="moneda"),
        ColumnaReporte("Viajes", ancho=12, formato="entero"),
        ColumnaReporte("Duración prom. (min)", ancho=20, formato="decimal1"),
    ]
    filas = [
        [m["periodo_label"], m["total_alquileres"], m["ingresos_brutos"], m["descuentos"],
         m["recargos"], m["ganancia_neta"], m["total_viajes"], m["duracion_prom_min"]]
        for m in meses
    ]
    fila_total = [
        f"Total: {len(meses)} meses cerrados", sum(m["total_alquileres"] for m in meses),
        sum(m["ingresos_brutos"] for m in meses), sum(m["descuentos"] for m in meses),
        sum(m["recargos"] for m in meses), sum(m["ganancia_neta"] for m in meses),
        sum(m["total_viajes"] for m in meses), None,
    ]
    return columnas, filas, fila_total


_ESTRATEGICO_SUBTITULO = (
    "* Ganancia neta sin gastos reales (urbanbike_operativa.gastos sin datos migrados aún) — "
    "ver docs/HOJA_DE_RUTA.md. resumen_mensual_flota pendiente: requiere más historial."
)


@router.get("/estrategico/excel")
def estrategico_excel(request: Request, anio_desde: str = Query(""), mes_desde: str = Query(""),
                       anio_hasta: str = Query(""), mes_hasta: str = Query("")):
    meses = _estrategico_meses(anio_desde=_int_o_none(anio_desde), mes_desde=_int_o_none(mes_desde),
                                anio_hasta=_int_o_none(anio_hasta), mes_hasta=_int_o_none(mes_hasta))
    columnas, filas, fila_total = _estrategico_columnas_filas(meses)
    return generar_excel_reporte(
        titulo="UrbanBike — Informe Estratégico (Evolución Mensual)",
        subtitulo=_ESTRATEGICO_SUBTITULO,
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_hoja="Evolución Mensual",
        nombre_archivo="urbanbike_estrategico_evolucion_mensual.xlsx",
    )


@router.get("/estrategico/pdf")
def estrategico_pdf(request: Request, anio_desde: str = Query(""), mes_desde: str = Query(""),
                     anio_hasta: str = Query(""), mes_hasta: str = Query("")):
    meses = _estrategico_meses(anio_desde=_int_o_none(anio_desde), mes_desde=_int_o_none(mes_desde),
                                anio_hasta=_int_o_none(anio_hasta), mes_hasta=_int_o_none(mes_hasta))
    columnas, filas, fila_total = _estrategico_columnas_filas(meses)
    return generar_pdf_reporte(
        titulo="Informe Estratégico — Evolución Mensual",
        subtitulo=_ESTRATEGICO_SUBTITULO,
        columnas=columnas,
        filas=filas,
        fila_total=fila_total,
        nombre_archivo="urbanbike_estrategico_evolucion_mensual.pdf",
    )


# ══════════════════════════════════════════════════════════════════════════════
# PROMOCIONES — WorkPanel (lista+filtro+paginación+4 modos), ver docs/HOJA_DE_RUTA.md
# ══════════════════════════════════════════════════════════════════════════════

DIAS_SEMANA_LABEL = {"1": "Lun", "2": "Mar", "3": "Mié", "4": "Jue", "5": "Vie", "6": "Sáb", "7": "Dom"}


def _dias_form_a_csv(dias: list[str]) -> str:
    validos = [d for d in dias if d in DIAS_SEMANA_LABEL]
    return ",".join(sorted(validos, key=int)) if validos else "1,2,3,4,5,6,7"


@router.get("/promociones", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("promociones:leer"))])
def promociones_list(
    request: Request, q: str = Query(""), estado: str = Query(""), page: int = Query(1),
):
    flash = request.session.pop("flash", None)
    per_page = 10
    filas, total = promociones_repo.listar(q=q, estado=estado, page=page, per_page=per_page)
    for f in filas:
        f["dias_semana_label"] = ", ".join(
            DIAS_SEMANA_LABEL.get(d.strip(), d.strip()) for d in (f["dias_semana"] or "").split(",") if d.strip()
        )
    return templates.TemplateResponse(request, "gerente/promociones.html", _ctx(request,
        title="Promociones", flash=flash, promociones=filas, total=total,
        page=max(1, page), per_page=per_page, total_paginas=max(1, -(-total // per_page)),
        q=q, estado=estado,
    ))


def _promociones_columnas_filas(items: list[dict]) -> tuple[list[ColumnaReporte], list[list]]:
    columnas = [
        ColumnaReporte("Código", ancho=14),
        ColumnaReporte("Nombre", ancho=24),
        ColumnaReporte("Descuento", ancho=14),
        ColumnaReporte("Aplica a", ancho=16),
        ColumnaReporte("Días", ancho=18),
        ColumnaReporte("Vigencia", ancho=22),
        ColumnaReporte("Usos", ancho=12),
        ColumnaReporte("Estado", ancho=12),
        ColumnaReporte("Miembros", ancho=12),
    ]
    _estado_label = {"activa": "Activa", "pausada": "Pausada", "vencida": "Vencida"}
    filas = []
    for p in items:
        descuento = f"{int(p['valor'])}%" if p["tipo_descuento"] == "porcentaje" else f"USD {float(p['valor']):.2f}"
        vigencia = f"{p['fecha_inicio']} → {p['fecha_fin']}"
        usos = f"{p['usos_actuales']}/{p['usos_maximos']}" if p["usos_maximos"] > 0 else str(p["usos_actuales"])
        filas.append([
            p["codigo"], p["nombre"], descuento,
            "Todas" if p["aplica_a"] == "todas" else p["aplica_a"].capitalize(),
            p.get("dias_semana_label") or p.get("dias_semana") or "—",
            vigencia, usos, _estado_label.get(p["estado"], p["estado"]),
            "Solo miembros" if p.get("solo_member") else "Todos",
        ])
    return columnas, filas


@router.get("/promociones/excel")
def promociones_excel(request: Request, q: str = Query(""), estado: str = Query("")):
    items, total = promociones_repo.listar(q=q, estado=estado, per_page=10000)
    for f in items:
        f["dias_semana_label"] = ", ".join(
            DIAS_SEMANA_LABEL.get(d.strip(), d.strip()) for d in (f["dias_semana"] or "").split(",") if d.strip()
        )
    columnas, filas = _promociones_columnas_filas(items)
    return generar_excel_reporte(
        titulo="UrbanBike — Promociones", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas, nombre_hoja="Promociones",
        nombre_archivo=f"urbanbike_promociones_{datetime.now().strftime('%Y%m%d')}.xlsx",
    )


@router.get("/promociones/pdf")
def promociones_pdf(request: Request, q: str = Query(""), estado: str = Query("")):
    items, total = promociones_repo.listar(q=q, estado=estado, per_page=10000)
    for f in items:
        f["dias_semana_label"] = ", ".join(
            DIAS_SEMANA_LABEL.get(d.strip(), d.strip()) for d in (f["dias_semana"] or "").split(",") if d.strip()
        )
    columnas, filas = _promociones_columnas_filas(items)
    return generar_pdf_reporte(
        titulo="Promociones", subtitulo=f"Total: {total} registros",
        columnas=columnas, filas=filas,
        nombre_archivo=f"urbanbike_promociones_{datetime.now().strftime('%Y%m%d')}.pdf",
    )


@router.get("/promociones/nueva", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("promociones:crear"))])
def promociones_nueva(request: Request):
    flash = request.session.pop("flash", None)
    return templates.TemplateResponse(request, "gerente/promociones_form.html", _ctx(request,
        title="Nueva promoción", flash=flash, modo="crear", promo=None,
        categorias=promociones_repo.listar_categorias_ref(), bicicletas=promociones_repo.listar_bicicletas_ref(),
        dias_semana_opciones=DIAS_SEMANA_LABEL,
    ))


def _validar_promo_form(codigo: str, nombre: str, valor: float, fecha_inicio_s: str, fecha_fin_s: str,
                         exigir_inicio_futuro: bool = False) -> str:
    """Devuelve un mensaje de error, o '' si el formulario es valido.

    `exigir_inicio_futuro` (punto 1.11 del Plan V3, solo en creacion): una
    promocion NUEVA no puede empezar en el pasado. No se aplica al editar
    una promocion ya existente -- una promocion real que ya esta corriendo
    (fecha_inicio en el pasado) debe poder seguir editandose (ajustar el
    valor, usos_maximos, etc.) sin que esta regla la bloquee por una fecha
    que nunca fue el motivo de la edicion."""
    if not codigo.strip() or not nombre.strip():
        return "Código y nombre son obligatorios."
    if valor <= 0:
        return "El valor del descuento debe ser mayor a 0."
    try:
        fi = datetime.strptime(fecha_inicio_s, "%Y-%m-%d").date()
        ff = datetime.strptime(fecha_fin_s, "%Y-%m-%d").date()
    except ValueError:
        return "Fechas inválidas."
    if exigir_inicio_futuro and fi < date.today():
        return "La fecha de inicio de una promoción nueva no puede ser anterior a hoy."
    if ff < fi:
        return "La fecha de fin no puede ser anterior a la fecha de inicio."
    return ""


@router.post("/promociones/crear", dependencies=[Depends(requiere_permiso("promociones:crear"))])
def promociones_crear(
    request: Request,
    codigo: str = Form(...), nombre: str = Form(...),
    tipo_descuento: str = Form(...), valor: float = Form(...),
    aplica_a: str = Form("todas"), id_referencia: str = Form(""),
    dias: list[str] = Form([]),
    fecha_inicio: str = Form(...), fecha_fin: str = Form(...),
    usos_maximos: int = Form(0), solo_member: bool = Form(False),
):
    error = _validar_promo_form(codigo, nombre, valor, fecha_inicio, fecha_fin, exigir_inicio_futuro=True)
    if error:
        return _flash(request, "/gerente/promociones/nueva", "error", error)
    try:
        nuevo_id = promociones_repo.crear(
            codigo=codigo.strip(), nombre=nombre.strip(), tipo_descuento=tipo_descuento,
            valor=valor, aplica_a=aplica_a, id_referencia=id_referencia if aplica_a != "todas" else "",
            dias_semana=_dias_form_a_csv(dias),
            fecha_inicio=datetime.strptime(fecha_inicio, "%Y-%m-%d").date(),
            fecha_fin=datetime.strptime(fecha_fin, "%Y-%m-%d").date(),
            usos_maximos=usos_maximos, estado="activa", solo_member=solo_member,
        )
        promo = promociones_repo.obtener(nuevo_id)
        _log(request, "Crear promoción", f"Promoción creada: {promo['codigo']} — {promo['nombre']}")
        notificaciones_repo.notificar_rol(
            "ciclista", tipo="promocion_nueva",
            titulo="Nueva promoción disponible",
            mensaje=f"Hay una nueva promoción activa: {promo['nombre']} ({promo['codigo']}).",
            enlace="/ciclista/promociones",
        )
        return _flash(request, "/gerente/promociones", "success", f"Promoción {promo['codigo']} creada correctamente.")
    except Exception as e:
        return _flash(request, "/gerente/promociones/nueva", "error", str(e))


@router.get("/promociones/{pid}", response_class=HTMLResponse, dependencies=[Depends(requiere_permiso("promociones:leer"))])
def promociones_detalle(request: Request, pid: str, modo: str = Query("ver")):
    flash = request.session.pop("flash", None)
    promo = promociones_repo.obtener(pid)
    if not promo:
        return _flash(request, "/gerente/promociones", "error", "Promoción no encontrada.")
    promo["dias_lista"] = [d.strip() for d in (promo["dias_semana"] or "").split(",") if d.strip()]
    return templates.TemplateResponse(request, "gerente/promociones_form.html", _ctx(request,
        title=f"Promoción {promo['codigo']}", flash=flash, modo="editar" if modo == "editar" else "ver",
        promo=promo, categorias=promociones_repo.listar_categorias_ref(),
        bicicletas=promociones_repo.listar_bicicletas_ref(), dias_semana_opciones=DIAS_SEMANA_LABEL,
    ))


@router.post("/promociones/{pid}/editar", dependencies=[Depends(requiere_permiso("promociones:actualizar"))])
def promociones_editar(
    request: Request, pid: str,
    codigo: str = Form(...), nombre: str = Form(...),
    tipo_descuento: str = Form(...), valor: float = Form(...),
    aplica_a: str = Form("todas"), id_referencia: str = Form(""),
    dias: list[str] = Form([]),
    fecha_inicio: str = Form(...), fecha_fin: str = Form(...),
    usos_maximos: int = Form(0), estado: str = Form(...), solo_member: bool = Form(False),
):
    error = _validar_promo_form(codigo, nombre, valor, fecha_inicio, fecha_fin)
    if error:
        return _flash(request, f"/gerente/promociones/{pid}?modo=editar", "error", error)
    try:
        promociones_repo.actualizar(
            pid, codigo=codigo.strip(), nombre=nombre.strip(), tipo_descuento=tipo_descuento,
            valor=valor, aplica_a=aplica_a, id_referencia=id_referencia if aplica_a != "todas" else "",
            dias_semana=_dias_form_a_csv(dias),
            fecha_inicio=datetime.strptime(fecha_inicio, "%Y-%m-%d").date(),
            fecha_fin=datetime.strptime(fecha_fin, "%Y-%m-%d").date(),
            usos_maximos=usos_maximos, estado=estado, solo_member=solo_member,
        )
        _log(request, "Editar promoción", f"Promoción actualizada: {codigo}")
        return _flash(request, f"/gerente/promociones/{pid}", "success", "Promoción actualizada.")
    except Exception as e:
        return _flash(request, f"/gerente/promociones/{pid}?modo=editar", "error", str(e))


@router.post("/promociones/{pid}/eliminar", dependencies=[Depends(requiere_permiso("promociones:eliminar"))])
def promociones_eliminar(request: Request, pid: str):
    promo = promociones_repo.obtener(pid)
    codigo = promo["codigo"] if promo else pid
    ok, motivo = promociones_repo.eliminar(pid)
    if ok:
        _log(request, "Eliminar promoción", f"Promoción eliminada: {codigo}")
        return _flash(request, "/gerente/promociones", "success", f"Promoción {codigo} eliminada.")
    return _flash(request, f"/gerente/promociones/{pid}", "error", motivo)
