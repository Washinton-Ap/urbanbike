-- Tabla de hechos principal: 3.7M viajes de Citibike NYC, octubre 2023
CREATE TABLE IF NOT EXISTS urbanbike.fact_viajes
(
    ride_id             String,
    id_tipo_bicicleta   UInt8,
    fecha_inicio        DateTime,
    fecha_fin           DateTime,
    id_estacion_inicio  String,
    id_estacion_fin     String,
    lat_inicio          Float64,
    lng_inicio          Float64,
    lat_fin             Float64,
    lng_fin             Float64,
    id_membresia        UInt8,
    duracion_min        Float32,
    distancia_km        Float32
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(fecha_inicio)
ORDER BY (fecha_inicio, id_estacion_inicio)
SETTINGS index_granularity = 8192;
