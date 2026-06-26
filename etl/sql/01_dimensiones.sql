-- Base de datos principal
CREATE DATABASE IF NOT EXISTS urbanbike;

-- Tipos de bicicleta
CREATE TABLE IF NOT EXISTS urbanbike.dim_tipos_bicicleta
(
    id_tipo     UInt8,
    nombre      String,
    descripcion String
)
ENGINE = MergeTree()
ORDER BY id_tipo;

-- Estaciones con coordenadas promedio
CREATE TABLE IF NOT EXISTS urbanbike.dim_estaciones
(
    id_estacion     String,
    nombre_estacion String,
    latitud         Float64,
    longitud        Float64
)
ENGINE = MergeTree()
ORDER BY id_estacion;

-- Tipo de membresía del usuario
CREATE TABLE IF NOT EXISTS urbanbike.dim_membresia
(
    id_membresia UInt8,
    tipo         String   -- 'member' | 'casual'
)
ENGINE = MergeTree()
ORDER BY id_membresia;

-- Dimensión tiempo (granularidad diaria)
CREATE TABLE IF NOT EXISTS urbanbike.dim_tiempo
(
    fecha       Date,
    anio        UInt16,
    mes         UInt8,
    dia         UInt8,
    dia_semana  UInt8,   -- 1=Lunes, 7=Domingo
    nombre_dia  String,
    nombre_mes  String,
    es_fin_semana UInt8
)
ENGINE = MergeTree()
ORDER BY fecha;
