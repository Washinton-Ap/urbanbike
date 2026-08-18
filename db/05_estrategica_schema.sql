-- ============================================================
-- UrbanBike S.A.  Base ESTRATEGICA en ClickHouse
-- Nivel superior de la particion en tres bases (ver
-- docs/HOJA_DE_RUTA.md, seccion 1.2). Consolidados de largo plazo,
-- un renglon por periodo (mes), pensados para alimentarse desde
-- urbanbike_tactica -- nunca directo desde urbanbike_operativa.
--
-- ReplacingMergeTree(version) porque un mes en curso se recalcula en
-- cada corrida del ETL hasta que cierra; la ultima version por
-- (anio, mes) es la vigente.
-- ============================================================

CREATE DATABASE IF NOT EXISTS urbanbike_estrategica;

-- Ingresos, gastos y ganancia neta consolidados del mes. Se alimenta
-- de urbanbike_tactica.fact_viajes (subtotal/descuento/recargo/total).
CREATE TABLE IF NOT EXISTS urbanbike_estrategica.resumen_mensual_ingresos
(
    anio            UInt16,
    mes             UInt8,
    total_alquileres UInt32,
    ingresos_brutos Decimal(14, 2),
    descuentos      Decimal(14, 2),
    recargos        Decimal(14, 2),
    gastos          Decimal(14, 2),
    ganancia_neta   Decimal(14, 2),
    version         DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (anio, mes);

-- Demanda por estacion y mes: volumen de viajes y duracion promedio.
-- Se alimenta de urbanbike_tactica.fact_viajes + dim_estaciones.
CREATE TABLE IF NOT EXISTS urbanbike_estrategica.resumen_mensual_demanda
(
    anio             UInt16,
    mes              UInt8,
    id_estacion      UUID,
    total_viajes     UInt32,
    duracion_prom_min Float32,
    version          DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (anio, mes, id_estacion);

-- Estado de la flota por categoria y mes: disponibilidad y desgaste.
-- Se alimenta de urbanbike_tactica.dim_tipos_bicicleta + KPI de
-- utilizacion/mantenimiento ya calculados en urbanbike_tactica.
CREATE TABLE IF NOT EXISTS urbanbike_estrategica.resumen_mensual_flota
(
    anio                  UInt16,
    mes                   UInt8,
    categoria             LowCardinality(String),
    bicicletas_activas    UInt32,
    bicicletas_mantenimiento UInt32,
    km_acumulados         Decimal(14, 2),
    disponibilidad_pct    Decimal(5, 2),
    version               DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (anio, mes, categoria);
