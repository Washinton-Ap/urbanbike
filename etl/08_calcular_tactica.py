"""
ETL paso 8: llena urbanbike_tactica (fact_viajes + 5 dimensiones) desde
los datos reales de urbanbike_operativa migrados en el paso 7, calcula
resumen_viajes_diario (resumen precalculado dia x estacion x membresia x
tipo, usado por gerente/reportes y gerente/informe en vez de agregar
fact_viajes en vivo -- ver docs/HOJA_DE_RUTA.md) y los KPI tacticos en
kpi_resultados.

Carga completa (no incremental): cada dimension y fact_viajes se
truncan antes de recargarse completas -- es la forma mas simple de
mantenerlas consistentes en cada corrida del ETL cada hora (Airflow).
kpi_resultados es un historico de corridas: cada ejecucion agrega una
fila nueva por KPI con su propio fecha_calculo, nunca se trunca (a
proposito).

Idempotencia (corregido 06-ago-2026, ver docs/HOJA_DE_RUTA.md): antes,
las dimensiones no truncaban, solo reinsertaban -- como usan
ReplacingMergeTree eso "no rompia" nada logicamente (la ultima version
gana con FINAL), pero fisicamente duplicaba cada fila en cada corrida,
y los JOIN reales de app/routers/gerente.py no usan FINAL, asi que con
el DAG cada hora los reportes hubieran empezado a duplicar resultados.
dim_tiempo era el caso peor: usaba MergeTree simple (sin dedup posible
ni con FINAL) y crecia sin limite en cada corrida. Se corrigio
agregando TRUNCATE antes de cada carga (mismo patron que ya usaba
fact_viajes) y se recreo dim_tiempo como ReplacingMergeTree por
consistencia con el resto de las dimensiones (ver db/04_tactica_schema.sql).

Nota sobre nombres de id_objetivo/codigo_kpi: el documento academico de
clase (donde vive el catalogo real de objetivos tacticos) no esta en el
repo -- solo el esquema en estrella de urbanbike_tactica fue confirmado
contra ese documento. Los codigos usados aqui son descriptivos y estan
sujetos a renombrarse si el catalogo real trae otros.

Los KPI y todos los agregados de fact_viajes deben filtrar
WHERE es_prueba = 0 (ver docs/HOJA_DE_RUTA.md): el viaje 7j39ut1z9ztgan3
(20457 min) es una prueba de desarrollo real, no un alquiler real.
"""

import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from _snapshot import guardar_parquet  # noqa: E402

load_dotenv()

DB_OP = "urbanbike_operativa"
DB_TAC = "urbanbike_tactica"
UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"

NOMBRES_DIA = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
NOMBRES_MES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
               "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def get_client(database: str):
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=database,
    )


def cargar_dim_tiempo(tac, desde: date, hasta: date):
    tac.command("TRUNCATE TABLE dim_tiempo")
    filas = []
    d = desde
    while d <= hasta:
        filas.append([
            d, d.year, d.month, d.day, d.isoweekday(),
            NOMBRES_DIA[d.isoweekday() - 1], NOMBRES_MES[d.month],
            1 if d.isoweekday() >= 6 else 0, datetime.now(),
        ])
        d += timedelta(days=1)
    tac.insert(
        "dim_tiempo", filas,
        column_names=["fecha", "anio", "mes", "dia", "dia_semana", "nombre_dia", "nombre_mes", "es_fin_semana", "version"],
    )
    print(f"dim_tiempo: {len(filas)} dias ({desde} a {hasta})")


def cargar_dim_estaciones(op, tac):
    tac.command("TRUNCATE TABLE dim_estaciones")
    filas = op.query("""
        SELECT id, codigo, nombre, direccion, latitud, longitud, capacidad, now() AS version
        FROM estaciones FINAL
    """).result_rows
    tac.insert(
        "dim_estaciones", filas,
        column_names=["id_estacion", "codigo", "nombre_estacion", "direccion", "latitud", "longitud", "capacidad", "version"],
    )
    print(f"dim_estaciones: {len(filas)} filas")


def cargar_dim_tipos_bicicleta(op, tac):
    tac.command("TRUNCATE TABLE dim_tipos_bicicleta")
    filas = op.query("""
        SELECT m.id AS id_modelo, m.nombre AS nombre_modelo, ma.nombre AS marca,
               c.nombre AS categoria, c.es_premium, m.es_electrica, m.enfoque, now() AS version
        FROM modelos_bicicleta m FINAL
        JOIN marcas ma FINAL ON ma.id = m.id_marca
        JOIN categorias c FINAL ON c.id = m.id_categoria
    """).result_rows
    tac.insert(
        "dim_tipos_bicicleta", filas,
        column_names=["id_modelo", "nombre_modelo", "marca", "categoria", "es_premium", "es_electrica", "enfoque", "version"],
    )
    print(f"dim_tipos_bicicleta: {len(filas)} filas")


def cargar_dim_usuario(op, tac):
    tac.command("TRUNCATE TABLE dim_usuario")
    filas = op.query("""
        SELECT id, codigo, rol, estado, fecha_registro, now() AS version
        FROM usuarios FINAL
    """).result_rows
    tac.insert(
        "dim_usuario", filas,
        column_names=["id_usuario", "codigo", "rol", "estado", "fecha_registro", "version"],
    )
    print(f"dim_usuario: {len(filas)} filas")


def cargar_dim_tarifa(op, tac):
    tac.command("TRUNCATE TABLE dim_tarifa")
    filas = list(op.query("""
        SELECT t.id AS id_tarifa, c.nombre AS categoria, t.tipo_membresia, t.modalidad,
               t.precio, t.vigente_desde, now() AS version
        FROM tarifas t FINAL
        JOIN categorias c FINAL ON c.id = t.id_categoria
    """).result_rows)
    # Fila "desconocida" para los alquileres sin pago asociado (id_tarifa sentinela).
    filas.append([uuid.UUID(UUID_SENTINELA), "desconocida", "desconocida", "hora", 0, date(1970, 1, 1), datetime.now()])
    tac.insert(
        "dim_tarifa", filas,
        column_names=["id_tarifa", "categoria", "tipo_membresia", "modalidad", "precio", "vigente_desde", "version"],
    )
    print(f"dim_tarifa: {len(filas)} filas (incluye 1 fila 'desconocida')")


def cargar_fact_viajes(op, tac):
    tac.command("TRUNCATE TABLE fact_viajes")
    columnas = ["id_alquiler", "codigo", "id_usuario", "id_modelo", "id_tarifa",
                "id_estacion_inicio", "id_estacion_fin", "fecha_inicio", "fecha_fin",
                "duracion_min", "estado_final", "subtotal", "descuento", "recargo",
                "total", "es_prueba"]
    filas = op.query("""
        SELECT a.id AS id_alquiler, a.codigo, a.id_usuario, b.id_modelo, a.id_tarifa,
               a.id_estacion_inicio,
               ifNull(toUUIDOrNull(a.id_estacion_fin), a.id_estacion_inicio) AS id_estacion_fin,
               a.fecha_inicio, a.fecha_fin, a.minutos_reales, a.estado,
               a.subtotal, a.descuento, a.recargo, a.total, a.es_prueba
        FROM alquileres a FINAL
        JOIN bicicletas b FINAL ON b.id = a.id_bicicleta
        WHERE a.estado IN ('devuelto', 'facturado')
    """).result_rows
    tac.insert("fact_viajes", filas, column_names=columnas)
    print(f"fact_viajes: {len(filas)} viajes cerrados cargados")

    # datos/proceso: area de trabajo intermedia de esta corrida (ver
    # docs/datos_README.md) -- el fact_viajes recalculado completo.
    guardar_parquet("proceso", "08_fact_viajes", filas, columnas)
    return len(filas)


def cargar_resumen_viajes_diario(tac):
    """Resumen precalculado dia x estacion x membresia x tipo (ver
    docs/HOJA_DE_RUTA.md): gerente/reportes y gerente/informe agregaban
    fact_viajes en vivo en cada request, contradiciendo el principio de
    "nunca calcular en el momento de la consulta" ya aplicado a
    kpi_resultados. Este resumen deja hecho el JOIN + GROUP BY caro una
    vez por corrida del ETL; las pantallas solo filtran/re-agregan sobre
    esta tabla ya reducida. Se reconstruye completa cada corrida
    (TRUNCATE + INSERT SELECT), mismo criterio de idempotencia que
    fact_viajes/dim_* (seccion 18): nunca UPDATE, nunca crece sin limite.
    """
    tac.command("TRUNCATE TABLE resumen_viajes_diario")
    columnas = ["fecha", "id_estacion_inicio", "tipo_membresia", "es_electrica",
                "viajes", "duracion_total_min", "fecha_calculo"]
    filas = tac.query("""
        SELECT
            toDate(f.fecha_inicio) AS fecha,
            f.id_estacion_inicio   AS id_estacion_inicio,
            df.tipo_membresia      AS tipo_membresia,
            t.es_electrica         AS es_electrica,
            count()                AS viajes,
            sum(f.duracion_min)    AS duracion_total_min,
            now()                  AS fecha_calculo
        FROM fact_viajes f
        LEFT JOIN dim_tarifa df ON f.id_tarifa = df.id_tarifa
        LEFT JOIN dim_tipos_bicicleta t ON f.id_modelo = t.id_modelo
        WHERE f.es_prueba = 0
        GROUP BY fecha, id_estacion_inicio, tipo_membresia, es_electrica
    """).result_rows
    tac.insert("resumen_viajes_diario", filas, column_names=columnas)
    print(f"resumen_viajes_diario: {len(filas)} filas (dia x estacion x membresia x tipo)")

    # datos/proceso: mismo criterio que fact_viajes -- snapshot real de
    # esta corrida.
    guardar_parquet("proceso", "08_resumen_viajes_diario", filas, columnas)
    return len(filas)


def calcular_kpis(tac, n_viajes: int):
    ahora = datetime.now()
    kpis = list(tac.query("""
        SELECT sum(total) FROM fact_viajes WHERE estado_final = 'facturado' AND es_prueba = 0
    """).result_rows[0]) + list(tac.query("""
        SELECT avg(duracion_min) FROM fact_viajes WHERE es_prueba = 0
    """).result_rows[0])
    ingresos_confirmados = float(kpis[0] or 0)
    duracion_promedio = float(kpis[1] or 0)

    ticket_promedio = float(tac.query("""
        SELECT avg(total) FROM fact_viajes WHERE estado_final = 'facturado' AND es_prueba = 0
    """).result_rows[0][0] or 0)

    op = get_client(DB_OP)
    flota = op.query("""
        SELECT countIf(estado = 'mantenimiento') AS en_mant,
               countIf(estado = 'disponible') AS disponible, count() AS total
        FROM bicicletas FINAL
    """).result_rows[0]
    pct_mantenimiento = round(100 * flota[0] / flota[2], 2) if flota[2] else 0
    pct_disponible = round(100 * flota[1] / flota[2], 2) if flota[2] else 0

    empleados_activos = op.query("""
        SELECT count() FROM usuarios FINAL WHERE rol != 'ciclista' AND estado = 'activo'
    """).result_rows[0][0]

    repuestos = op.query("""
        SELECT countIf(stock_actual < stock_minimo) AS bajo, count() AS total
        FROM repuestos FINAL WHERE activo = 1
    """).result_rows[0]
    pct_repuestos_bajo_minimo = round(100 * repuestos[0] / repuestos[1], 2) if repuestos[1] else 0

    # OM-0316 excluida a proposito: orden de prueba documentada en
    # docs/HOJA_DE_RUTA.md seccion 22 ("Orden de prueba para verificar
    # flujo_orden.html"), no una reparacion real -- mismo criterio que
    # es_prueba en alquileres, aplicado aqui por codigo porque
    # ordenes_mantenimiento no tiene esa columna.
    tiempo_resolucion = op.query("""
        SELECT avg(dateDiff('minute', fecha_apertura, fecha_cierre))
        FROM ordenes_mantenimiento FINAL
        WHERE estado_reparacion = 'cerrada' AND codigo != 'OM-0316'
    """).result_rows[0][0]
    tiempo_resolucion_min = round(float(tiempo_resolucion or 0), 2)

    infracciones_activas = op.query("""
        SELECT count() FROM infracciones FINAL WHERE estado = 'activa'
    """).result_rows[0][0]

    filas = [
        ("OBJ-T-GER-01", "KPI-INGRESOS-CONFIRMADOS", ingresos_confirmados, ahora, "gerencia"),
        ("OBJ-T-OPE-01", "KPI-DURACION-PROMEDIO-MIN", round(duracion_promedio, 2), ahora, "operacion"),
        ("OBJ-T-MAN-01", "KPI-FLOTA-EN-MANTENIMIENTO-PCT", pct_mantenimiento, ahora, "mantenimiento"),
        ("OBJ-T-GER-02", "KPI-TICKET-PROMEDIO-ALQUILER", round(ticket_promedio, 2), ahora, "gerencia"),
        ("OBJ-T-ADM-01", "KPI-EMPLEADOS-ACTIVOS", float(empleados_activos), ahora, "administracion"),
        ("OBJ-T-OPE-02", "KPI-FLOTA-DISPONIBLE-PCT", pct_disponible, ahora, "operacion"),
        ("OBJ-T-MAN-02", "KPI-REPUESTOS-BAJO-MINIMO-PCT", pct_repuestos_bajo_minimo, ahora, "mantenimiento"),
        ("OBJ-T-MAN-03", "KPI-TIEMPO-RESOLUCION-ORDEN-MIN", tiempo_resolucion_min, ahora, "mantenimiento"),
        ("OBJ-T-VIG-01", "KPI-INFRACCIONES-ACTIVAS", float(infracciones_activas), ahora, "vigilancia"),
    ]
    tac.insert(
        "kpi_resultados", filas,
        column_names=["id_objetivo", "codigo_kpi", "valor", "fecha_calculo", "departamento"],
    )
    print("\nKPI calculados:")
    for f in filas:
        print(f"  [{f[4]}] {f[1]} = {f[2]}")
    print(f"\n(base: {n_viajes} viajes cerrados reales, excluyendo es_prueba=1)")


def main():
    op = get_client(DB_OP)
    tac = get_client(DB_TAC)

    rango = op.query("SELECT min(fecha_inicio), max(fecha_fin) FROM alquileres FINAL").result_rows[0]
    cargar_dim_tiempo(tac, rango[0].date(), rango[1].date())
    cargar_dim_estaciones(op, tac)
    cargar_dim_tipos_bicicleta(op, tac)
    cargar_dim_usuario(op, tac)
    cargar_dim_tarifa(op, tac)
    n = cargar_fact_viajes(op, tac)
    cargar_resumen_viajes_diario(tac)
    calcular_kpis(tac, n)


if __name__ == "__main__":
    main()
