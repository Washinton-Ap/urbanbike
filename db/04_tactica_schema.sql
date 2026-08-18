-- ============================================================
-- UrbanBike S.A.  Base TACTICA en ClickHouse
-- Nivel intermedio de la particion en tres bases (ver
-- docs/HOJA_DE_RUTA.md, seccion 1.2). Esquema en estrella para los
-- informes compuestos del nivel tactico: fact_viajes mas cinco
-- dimensiones, y una tabla de KPI ya precalculados.
--
-- Fuente de los datos (cuando el ETL de Airflow los cargue, sesion
-- futura): urbanbike_operativa.alquileres/usuarios/tarifas/bicicletas/
-- estaciones/modelos_bicicleta, NO el dataset crudo de Citibike. La
-- base "urbanbike" (etl/sql/*.sql) es el analisis exploratorio sobre
-- Citibike y queda aparte.
--
-- Convenciones heredadas de db/01_operativa_schema.sql:
--   ReplacingMergeTree(version) = entidad con estado
--   MergeTree                   = evento/hecho inmutable (solo INSERT)
--   LowCardinality(String)      = campo tipo enumeracion
--   Decimal(10,2)               = dinero
-- ============================================================

CREATE DATABASE IF NOT EXISTS urbanbike_tactica;

-- ------------------------------------------------------------
-- DIMENSIONES
-- ------------------------------------------------------------

-- Un dia por fila. El ETL (etl/08_calcular_tactica.py) hace TRUNCATE +
-- reload completo en cada corrida (mismo patron que fact_viajes), asi
-- que ReplacingMergeTree es solo defensivo aqui -- pero MergeTree
-- simple no deduplica nunca, ni con FINAL: una corrida del ETL antes
-- de tener el TRUNCATE dejo esta tabla creciendo sin limite en cada
-- ejecucion (bug real encontrado el 06-ago-2026 en la auditoria previa
-- a Airflow, ver docs/HOJA_DE_RUTA.md).
CREATE TABLE IF NOT EXISTS urbanbike_tactica.dim_tiempo
(
    fecha         Date,
    anio          UInt16,
    mes           UInt8,
    dia           UInt8,
    dia_semana    UInt8,   -- 1=Lunes, 7=Domingo
    nombre_dia    String,
    nombre_mes    String,
    es_fin_semana UInt8,
    version       DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY fecha;

-- Copia analitica de urbanbike_operativa.estaciones.
CREATE TABLE IF NOT EXISTS urbanbike_tactica.dim_estaciones
(
    id_estacion     UUID,        -- = urbanbike_operativa.estaciones.id
    codigo          String,      -- E-01
    nombre_estacion String,
    direccion       String,
    latitud         Decimal(9, 6),
    longitud        Decimal(9, 6),
    capacidad       UInt16,
    version         DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id_estacion;

-- Grano: modelo de bicicleta (no la unidad fisica). Denormaliza marca
-- y categoria para no tener que unir tres tablas en cada informe.
CREATE TABLE IF NOT EXISTS urbanbike_tactica.dim_tipos_bicicleta
(
    id_modelo      UUID,         -- = urbanbike_operativa.modelos_bicicleta.id
    nombre_modelo  String,
    marca          String,
    categoria      LowCardinality(String),  -- Premium|Estandar|Electrica|Urbana|Montana
    es_premium     UInt8,
    es_electrica   UInt8,
    enfoque        LowCardinality(String),  -- urbano|montana|ruta|paseo|carga
    version        DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id_modelo;

-- Atributos de segmentacion del usuario para los informes tacticos;
-- sin datos de contacto (email/telefono se quedan en la operativa).
CREATE TABLE IF NOT EXISTS urbanbike_tactica.dim_usuario
(
    id_usuario     UUID,         -- = urbanbike_operativa.usuarios.id
    codigo         String,       -- U-0001
    rol            LowCardinality(String),
    estado         LowCardinality(String),
    fecha_registro DateTime,
    version        DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id_usuario;

-- Espejo de urbanbike_operativa.tarifas: la tarifa va por categoria
-- de bicicleta y tipo de membresia, no por bicicleta individual.
CREATE TABLE IF NOT EXISTS urbanbike_tactica.dim_tarifa
(
    id_tarifa       UUID,        -- = urbanbike_operativa.tarifas.id
    categoria       LowCardinality(String),
    tipo_membresia  LowCardinality(String),  -- member|casual
    modalidad       LowCardinality(String),  -- hora|dia|semana
    precio          Decimal(10, 2),
    vigente_desde   Date,
    version         DateTime
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id_tarifa;

-- ------------------------------------------------------------
-- HECHOS
-- ------------------------------------------------------------

-- Un viaje cerrado por fila. Se carga una vez que el alquiler llega a
-- estado 'cerrado' en la operativa; por eso es insert-only (MergeTree).
CREATE TABLE IF NOT EXISTS urbanbike_tactica.fact_viajes
(
    id_alquiler        UUID,     -- = urbanbike_operativa.alquileres.id
    codigo             String,   -- A-010482
    id_usuario         UUID,
    id_modelo          UUID,
    id_tarifa          UUID,
    id_estacion_inicio UUID,
    id_estacion_fin    UUID,
    fecha_inicio       DateTime,
    fecha_fin          DateTime,
    duracion_min       Float32,
    estado_final       LowCardinality(String),  -- cerrado|cancelado
    subtotal           Decimal(10, 2),
    descuento          Decimal(10, 2),
    recargo            Decimal(10, 2),
    total              Decimal(10, 2),
    es_prueba          UInt8    -- copiado de alquileres.es_prueba; todo KPI/informe
                                -- que calcule duracion, ingresos o promedios debe
                                -- filtrar WHERE es_prueba = 0 (ver docs/HOJA_DE_RUTA.md)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(fecha_inicio)
ORDER BY (fecha_inicio, id_estacion_inicio)
SETTINGS index_granularity = 8192;

-- ------------------------------------------------------------
-- RESUMEN PRECALCULADO (para informes compuestos, ver docs/HOJA_DE_RUTA.md)
-- ------------------------------------------------------------

-- Grano dia x estacion x membresia x tipo de bicicleta: el minimo comun
-- que soporta los filtros en vivo (fecha, membresia, tipo de bici) y las
-- formas de agrupar (por estacion, por dia de semana, por tipo, por dia)
-- que usan gerente/reportes y gerente/informe, sin agregar sobre
-- fact_viajes en cada request. El ETL (etl/08_calcular_tactica.py) la
-- recarga completa cada corrida -- mismo patron TRUNCATE + INSERT SELECT
-- que fact_viajes/dim_*, nunca UPDATE. duracion_total_min permite
-- reconstruir el promedio ponderado correcto (sum/sum) al re-agregar en
-- vivo sobre este resumen ya reducido.
CREATE TABLE IF NOT EXISTS urbanbike_tactica.resumen_viajes_diario
(
    fecha               Date,                    -- toDate(fecha_inicio)
    id_estacion_inicio  UUID,                     -- = dim_estaciones.id_estacion
    tipo_membresia      LowCardinality(String),   -- member|casual (via dim_tarifa)
    es_electrica        UInt8,                    -- via dim_tipos_bicicleta
    viajes              UInt32,                   -- count()
    duracion_total_min  Float64,                  -- sum(duracion_min)
    fecha_calculo       DateTime                  -- trazabilidad, igual que kpi_resultados
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(fecha)
ORDER BY (fecha, id_estacion_inicio, tipo_membresia, es_electrica);

-- ------------------------------------------------------------
-- KPI PRECALCULADOS (uno por objetivo tactico)
-- ------------------------------------------------------------

-- El ETL de Airflow (cada 1 hora) inserta una fila por cada corrida;
-- nunca se calcula en el momento de la consulta. Insert-only: cada
-- fecha_calculo es una version historica del KPI, no se reemplaza.
CREATE TABLE IF NOT EXISTS urbanbike_tactica.kpi_resultados
(
    id_objetivo   String,                  -- codigo del objetivo tactico, ej. OBJ-T-01
    codigo_kpi    String,                  -- ej. KPI-UTILIZACION-FLOTA
    valor         Decimal(18, 4),
    fecha_calculo DateTime,
    departamento  LowCardinality(String)   -- operacion|mantenimiento|vigilancia|gerencia
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(fecha_calculo)
ORDER BY (departamento, codigo_kpi, fecha_calculo);
