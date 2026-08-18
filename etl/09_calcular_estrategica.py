"""
ETL paso 9: resume urbanbike_tactica.fact_viajes hacia los consolidados
mensuales de urbanbike_estrategica.

Solo se calcula un mes cuando ya termino por completo (ultimo dia del
mes < hoy): un mes en curso daria un "total del mes" parcial que se
veria como definitivo y no lo es. Con los datos reales de hoy
(2026-06-07 a 2026-07-29) el unico mes que ya cerro es junio 2026;
julio 2026 se omite porque todavia le faltan dias.

resumen_mensual_flota NO se calcula hoy para ningun mes: solo existe el
estado ACTUAL de la flota (snapshot de hoy en
urbanbike_operativa.bicicletas), no hay historial de como estaba la
flota en junio. Insertar el snapshot de hoy como si fuera "el estado de
junio" seria enganoso, asi que se deja pendiente hasta que exista un
historial real de cambios de estado.

ingresos_brutos/descuentos/recargos/ganancia_neta solo cuentan viajes
con estado_final='facturado' (pago confirmado); total_alquileres cuenta
todo viaje cerrado (devuelto + facturado) como medida de actividad, no
de ingreso. gastos queda en 0 porque urbanbike_operativa.gastos no
tiene datos reales todavia -- ganancia_neta hoy es en realidad un techo
(ingresos sin restar costos reales), no una ganancia neta real.

Siempre filtra es_prueba = 0 (ver docs/HOJA_DE_RUTA.md).

Idempotencia (corregido 06-ago-2026, ver docs/HOJA_DE_RUTA.md): antes,
el script recalculaba TODOS los meses ya cerrados en cada corrida, para
siempre -- un mes cerrado nunca cambia, asi que con el DAG cada hora
esto hubiera insertado 24 versiones identicas del mismo mes por dia sin
ningun beneficio (confirmado con dos corridas seguidas: mismos valores,
solo crecimiento fisico de la tabla). Se agrego una guarda que salta
cualquier mes que ya tenga una fila en resumen_mensual_ingresos -- un
mes cerrado se calcula una sola vez en la vida de este script.
"""

import os
import sys
from datetime import datetime, date
from pathlib import Path
import calendar

import clickhouse_connect
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from _snapshot import guardar_parquet  # noqa: E402

load_dotenv()

DB_TAC = "urbanbike_tactica"
DB_EST = "urbanbike_estrategica"


def get_client(database: str):
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=database,
    )


def meses_ya_calculados(est) -> set[tuple[int, int]]:
    filas = est.query("SELECT anio, mes FROM resumen_mensual_ingresos").result_rows
    return {(int(a), int(m)) for a, m in filas}


def meses_disponibles(tac) -> list[tuple[int, int]]:
    filas = tac.query("""
        SELECT DISTINCT toYear(fecha_inicio) AS anio, toMonth(fecha_inicio) AS mes
        FROM fact_viajes WHERE es_prueba = 0
        ORDER BY anio, mes
    """).result_rows
    return [(int(a), int(m)) for a, m in filas]


def mes_completo(anio: int, mes: int) -> bool:
    ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return ultimo_dia < date.today()


def calcular_ingresos(tac, est, anio: int, mes: int):
    total_alquileres = tac.query("""
        SELECT count() FROM fact_viajes
        WHERE es_prueba = 0 AND toYear(fecha_inicio) = %(a)s AND toMonth(fecha_inicio) = %(m)s
          AND estado_final IN ('devuelto', 'facturado')
    """, parameters={"a": anio, "m": mes}).result_rows[0][0]

    ingresos = tac.query("""
        SELECT sum(subtotal), sum(descuento), sum(recargo), sum(total) FROM fact_viajes
        WHERE es_prueba = 0 AND toYear(fecha_inicio) = %(a)s AND toMonth(fecha_inicio) = %(m)s
          AND estado_final = 'facturado'
    """, parameters={"a": anio, "m": mes}).result_rows[0]
    ingresos_brutos, descuentos, recargos, total_facturado = (float(x or 0) for x in ingresos)
    gastos = 0.0  # urbanbike_operativa.gastos no tiene datos reales todavia
    ganancia_neta = total_facturado - gastos

    est.command("""
        INSERT INTO resumen_mensual_ingresos
            (anio, mes, total_alquileres, ingresos_brutos, descuentos, recargos, gastos, ganancia_neta, version)
        VALUES (%(anio)s, %(mes)s, %(ta)s, %(ib)s, %(d)s, %(r)s, %(g)s, %(gn)s, now())
    """, parameters={
        "anio": anio, "mes": mes, "ta": total_alquileres, "ib": ingresos_brutos,
        "d": descuentos, "r": recargos, "g": gastos, "gn": ganancia_neta,
    })
    print(f"  resumen_mensual_ingresos {anio}-{mes:02d}: {total_alquileres} alquileres, "
          f"ingresos facturados={total_facturado:.2f}, ganancia_neta (sin gastos reales)={ganancia_neta:.2f}")


def calcular_demanda(tac, est, anio: int, mes: int):
    filas = tac.query("""
        SELECT id_estacion_inicio, count() AS total_viajes, avg(duracion_min) AS dur_prom, now() AS version
        FROM fact_viajes
        WHERE es_prueba = 0 AND toYear(fecha_inicio) = %(a)s AND toMonth(fecha_inicio) = %(m)s
          AND estado_final IN ('devuelto', 'facturado')
        GROUP BY id_estacion_inicio
    """, parameters={"a": anio, "m": mes}).result_rows

    est.insert(
        "resumen_mensual_demanda",
        [[anio, mes, r[0], r[1], r[2], r[3]] for r in filas],
        column_names=["anio", "mes", "id_estacion", "total_viajes", "duracion_prom_min", "version"],
    )
    print(f"  resumen_mensual_demanda {anio}-{mes:02d}: {len(filas)} estaciones con actividad "
          f"(muestra chica, {sum(r[1] for r in filas)} viajes en total -- interpretar con cautela)")


def main():
    tac = get_client(DB_TAC)
    est = get_client(DB_EST)

    meses = meses_disponibles(tac)
    print(f"Meses con datos reales: {meses}")

    ya_calculados = meses_ya_calculados(est)
    if ya_calculados:
        print(f"Meses ya calculados antes, se saltan (idempotencia): {sorted(ya_calculados)}")

    for anio, mes in meses:
        if (anio, mes) in ya_calculados:
            print(f"  {anio}-{mes:02d}: OMITIDO, ya tiene resumen calculado (un mes cerrado no cambia)")
            continue
        if not mes_completo(anio, mes):
            ultimo_dia = date(anio, mes, calendar.monthrange(anio, mes)[1])
            print(f"  {anio}-{mes:02d}: OMITIDO, el mes termina el {ultimo_dia} y todavia no llega esa fecha")
            continue
        calcular_ingresos(tac, est, anio, mes)
        calcular_demanda(tac, est, anio, mes)

    print("\nresumen_mensual_flota: NO calculado para ningun mes -- solo existe el estado "
          "ACTUAL de la flota (sin historial por mes). Pendiente hasta que exista ese historial.")

    # datos/terminado: consolidado final validado de esta corrida (ver
    # docs/datos_README.md) -- estado completo de ambos resumenes, no
    # solo lo nuevo, para que el archivo siempre refleje "lo terminado"
    # aunque esta corrida no haya calculado ningun mes nuevo.
    ingresos_final = est.query(
        "SELECT anio, mes, total_alquileres, ingresos_brutos, descuentos, recargos, gastos, ganancia_neta "
        "FROM resumen_mensual_ingresos FINAL ORDER BY anio, mes"
    ).result_rows
    guardar_parquet(
        "terminado", "09_resumen_mensual_ingresos", ingresos_final,
        ["anio", "mes", "total_alquileres", "ingresos_brutos", "descuentos", "recargos", "gastos", "ganancia_neta"],
    )
    demanda_final = est.query(
        "SELECT anio, mes, id_estacion, total_viajes, duracion_prom_min "
        "FROM resumen_mensual_demanda FINAL ORDER BY anio, mes, id_estacion"
    ).result_rows
    guardar_parquet(
        "terminado", "09_resumen_mensual_demanda", demanda_final,
        ["anio", "mes", "id_estacion", "total_viajes", "duracion_prom_min"],
    )


if __name__ == "__main__":
    main()
