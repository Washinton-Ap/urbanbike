"""Respaldo real de urbanbike_operativa para /admin/respaldo.

Catalogo fijo de 25 tablas (auditoria completa en
docs/HOJA_DE_RUTA.md): las transaccionales con identidad de negocio
real, agrupadas por categoria para la pantalla. Deja afuera el
catalogo estatico (roles/permisos/rol_permisos/usuario_permisos/
marcas/categorias/modelos_bicicleta/checklist_items/
planes_mantenimiento), config sensible de la empresa
(cuentas_bancarias), adjuntos vacios (bicicleta_fotos) y
urbanbike_operativa.auditoria (0 filas siempre: la bitacora real vive
en PocketBase, esta tabla de ClickHouse nunca se escribe).

`fecha_col` es None en las tablas sin una columna de fecha de negocio
real (algunas son detalle de otra tabla, sin fecha propia) -- el
filtro de rango simplemente no les aplica, se exportan completas.

`final` indica si la tabla es ReplacingMergeTree (hay que leer con
FINAL para no traer versiones viejas de una fila) -- las MergeTree
simples (bitacoras/eventos, nunca se actualizan) no lo necesitan.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

from app.db import clickhouse as ch

DB = "urbanbike_operativa"

TABLAS: dict[str, dict] = {
    "usuarios":                   {"categoria": "Personas",              "fecha_col": "fecha_registro",   "final": True},
    "bicicletas":                 {"categoria": "Flota",                 "fecha_col": "fecha_adquisicion", "final": True},
    "bicicleta_eventos":          {"categoria": "Flota",                 "fecha_col": "fecha",             "final": False},
    "estaciones":                 {"categoria": "Flota",                 "fecha_col": None,                "final": True},
    "tarifas":                    {"categoria": "Tarifas y promociones", "fecha_col": "vigente_desde",     "final": True},
    "promociones":                {"categoria": "Tarifas y promociones", "fecha_col": "fecha_inicio",      "final": True},
    "alquileres":                 {"categoria": "Alquileres",            "fecha_col": "fecha_reserva",     "final": True},
    "alquiler_eventos":           {"categoria": "Alquileres",            "fecha_col": "fecha",             "final": False},
    "metodos_pago":               {"categoria": "Pagos y facturación",   "fecha_col": None,                "final": True},
    "garantias":                  {"categoria": "Pagos y facturación",   "fecha_col": "fecha_solicitud",   "final": True},
    "cobros_automaticos":         {"categoria": "Pagos y facturación",   "fecha_col": "fecha_ejecucion",   "final": True},
    "facturas":                   {"categoria": "Pagos y facturación",   "fecha_col": "fecha_emision",     "final": True},
    "factura_detalle":            {"categoria": "Pagos y facturación",   "fecha_col": None,                "final": True},
    "pagos":                      {"categoria": "Pagos y facturación",   "fecha_col": "fecha",             "final": True},
    "gastos":                     {"categoria": "Pagos y facturación",   "fecha_col": "fecha",             "final": False},
    "repuestos":                  {"categoria": "Repuestos y mantenimiento", "fecha_col": None,             "final": True},
    "movimientos_repuesto":       {"categoria": "Repuestos y mantenimiento", "fecha_col": "fecha",          "final": False},
    "mantenimientos_programados": {"categoria": "Repuestos y mantenimiento", "fecha_col": "fecha_programada", "final": True},
    "ordenes_mantenimiento":      {"categoria": "Repuestos y mantenimiento", "fecha_col": "fecha_apertura", "final": True},
    "orden_repuesto":             {"categoria": "Repuestos y mantenimiento", "fecha_col": None,             "final": True},
    "inspecciones":               {"categoria": "Inspecciones",          "fecha_col": "fecha_inicio",      "final": True},
    "inspeccion_detalle":         {"categoria": "Inspecciones",          "fecha_col": None,                "final": True},
    "infracciones":               {"categoria": "Infracciones",          "fecha_col": "fecha",             "final": True},
    "membresia_tarifa":           {"categoria": "Membresías",            "fecha_col": "vigente_desde",     "final": True},
    "membresias":                 {"categoria": "Membresías",            "fecha_col": "fecha_inicio",      "final": False},
}

# ClickHouse -> tipo SQL generico (ejecutable en cualquier motor estandar,
# no algo especifico de ClickHouse). Los tipos parametrizados
# (Decimal(p,s), FixedString(n)) se resuelven aparte en _tipo_sql().
_TIPO_SIMPLE = {
    "UUID": "VARCHAR(36)",
    "String": "TEXT",
    "DateTime": "TIMESTAMP",
    "Date": "DATE",
    "UInt8": "SMALLINT", "UInt16": "INTEGER", "UInt32": "BIGINT", "UInt64": "BIGINT",
    "Int8": "SMALLINT", "Int16": "INTEGER", "Int32": "BIGINT", "Int64": "BIGINT",
}


def _tipo_sql(tipo_ch: str) -> str:
    tipo_ch = tipo_ch.strip()
    if tipo_ch.startswith("LowCardinality("):
        return _tipo_sql(tipo_ch[len("LowCardinality("):-1])
    if tipo_ch.startswith("Nullable("):
        return _tipo_sql(tipo_ch[len("Nullable("):-1])
    if tipo_ch.startswith("Decimal("):
        return f"DECIMAL({tipo_ch[len('Decimal('):-1]})"
    if tipo_ch.startswith("FixedString("):
        return f"CHAR({tipo_ch[len('FixedString('):-1]})"
    return _TIPO_SIMPLE.get(tipo_ch, "TEXT")


def categorias_con_tablas() -> dict[str, list[str]]:
    """{categoria: [tabla, ...]} en el orden de definicion, para la pantalla."""
    out: dict[str, list[str]] = {}
    for tabla, meta in TABLAS.items():
        out.setdefault(meta["categoria"], []).append(tabla)
    return out


def columnas(tabla: str) -> list[tuple[str, str]]:
    """[(nombre, tipo_clickhouse)] en el orden real de la tabla."""
    filas = ch.query(f"DESCRIBE TABLE {DB}.{tabla}")
    return [(f["name"], f["type"]) for f in filas]


def _filtro_fecha(tabla: str, desde: date | None, hasta: date | None) -> tuple[str, dict]:
    meta = TABLAS[tabla]
    if not meta["fecha_col"] or not desde or not hasta:
        return "", {}
    return f" WHERE {meta['fecha_col']} BETWEEN %(desde)s AND %(hasta)s", {"desde": desde, "hasta": hasta}


def obtener_filas(tabla: str, desde: date | None, hasta: date | None) -> tuple[list[str], list[list]]:
    """(nombres_columnas, filas) -- tabla debe venir de TABLAS (whitelist),
    nunca de un valor crudo de request, por eso el nombre se interpola
    directo sin riesgo real de inyeccion."""
    meta = TABLAS[tabla]
    nombres = [c[0] for c in columnas(tabla)]
    where_sql, params = _filtro_fecha(tabla, desde, hasta)
    sql = f"SELECT * FROM {DB}.{tabla}" + (" FINAL" if meta["final"] else "") + where_sql
    filas = ch.query(sql, params)
    return nombres, [[f.get(n) for n in nombres] for f in filas]


def _valor_csv(v) -> str:
    return "" if v is None else str(v)


def exportar_csv(tablas: list[str], desde: date | None, hasta: date | None) -> tuple[bytes, str]:
    """(contenido, nombre_archivo). Una sola tabla -> .csv directo;
    varias -> .zip con un .csv por tabla."""
    resultados = {t: obtener_filas(t, desde, hasta) for t in tablas}

    if len(tablas) == 1:
        (tabla,) = tablas
        nombres, filas = resultados[tabla]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(nombres)
        for fila in filas:
            w.writerow([_valor_csv(v) for v in fila])
        return buf.getvalue().encode("utf-8-sig"), f"respaldo_{tabla}.csv"

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for tabla, (nombres, filas) in resultados.items():
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(nombres)
            for fila in filas:
                w.writerow([_valor_csv(v) for v in fila])
            zf.writestr(f"{tabla}.csv", buf.getvalue().encode("utf-8-sig"))
    return zip_buf.getvalue(), "respaldo_urbanbike.zip"


def _valor_sql(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    # fechas, UUID, Decimal, texto: todos como literal de texto entre
    # comillas, escapando comillas simples reales (nunca concatenado
    # sin escapar -- mismo criterio que el resto del sistema).
    return "'" + str(v).replace("'", "''") + "'"


def exportar_sql(tablas: list[str], desde: date | None, hasta: date | None) -> tuple[bytes, str]:
    """.sql generico: CREATE TABLE aproximado (tipos genericos, sin
    motor/engine especifico de ClickHouse) + INSERT por fila. Ejecutable
    en cualquier motor SQL estandar (Postgres, MySQL, SQLite...)."""
    partes: list[str] = [
        "-- Respaldo UrbanBike -- generado desde /admin/respaldo\n"
        "-- Tipos SQL genericos (no especificos de ClickHouse); CREATE TABLE es aproximado,\n"
        "-- pensado para poder inspeccionar/restaurar los datos en cualquier motor estandar.\n"
    ]
    for tabla in tablas:
        cols = columnas(tabla)
        nombres = [c[0] for c in cols]
        partes.append(f"\n-- ── {tabla} ──────────────────────────────────────────────\n")
        partes.append(f"CREATE TABLE IF NOT EXISTS {tabla} (\n")
        partes.append(",\n".join(f"    {n} {_tipo_sql(t)}" for n, t in cols))
        partes.append("\n);\n\n")

        _, filas = obtener_filas(tabla, desde, hasta)
        columnas_sql = ", ".join(nombres)
        for fila in filas:
            valores = ", ".join(_valor_sql(v) for v in fila)
            partes.append(f"INSERT INTO {tabla} ({columnas_sql}) VALUES ({valores});\n")

    return "".join(partes).encode("utf-8"), "respaldo_urbanbike.sql"
