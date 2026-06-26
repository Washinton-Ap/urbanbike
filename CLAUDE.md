# UrbanBike — Contexto del Proyecto

Sistema web de alquiler de bicicletas con análisis de datos de Citibike NYC.

## Dataset
- 4 CSV de Citibike, ~3.7 millones de viajes, Nueva York, octubre 2023
- Columnas: `ride_id`, `rideable_type`, `started_at`, `ended_at`,
  `start_station_name`, `start_station_id`, `end_station_name`, `end_station_id`,
  `start_lat`, `start_lng`, `end_lat`, `end_lng`, `member_casual`
- Los `station_id` son VARCHAR (algunos tienen formato "190 Morgan")

## Arquitectura de Bases de Datos

### ClickHouse (puerto 8123) — Capa Analítica (OLAP)
- Motor de columnas para consultas de KPIs sobre 3.7M filas
- Tablas: `fact_viajes`, `dim_estaciones`, `dim_tipos_bicicleta`,
  `dim_membresia`, `dim_tiempo`
- Database: `urbanbike`
- Los Parquet se montan en `/var/lib/clickhouse/user_files/parquet/`

### PocketBase (puerto 8090) — Capa Operativa (OLTP)
- Auth, sesiones, permisos, CRUD en tiempo real
- Gestiona usuarios, roles, bicicletas operativas, reportes de mantenimiento

## Flujo ETL
```
data/raw/*.csv
  → etl/01_extract_to_parquet.py  (DuckDB + PyArrow)
  → data/parquet/*.parquet
  → etl/02_load_clickhouse.py     (clickhouse-connect)
  → ClickHouse urbanbike.*
```

## Roles del Sistema
| Rol                    | Acceso principal                                  |
|------------------------|---------------------------------------------------|
| Admin                  | Todo (usuarios, configuración, sistema)           |
| Gerente                | Dashboard KPIs ClickHouse (solo lectura analítica)|
| Ciclista               | Reservas, historial personal, perfil              |
| Empleado-Operación     | Estado de bicicletas, asignaciones de estación    |
| Empleado-Mantenimiento | Reportes de mantenimiento, incidencias            |
| Empleado-Vigilancia    | Monitoreo en tiempo real de estaciones            |

## Stack Tecnológico
- **Backend**: Python 3.11+, FastAPI, Jinja2
- **ETL**: DuckDB, PyArrow, clickhouse-connect
- **Bases de datos**: ClickHouse 24.8, PocketBase 0.39.0
- **Infraestructura**: Docker Compose
- **Variables de entorno**: python-dotenv, `.env` (no commitear)

## Diseño UI
- **Color primario**: `#1E86BD` (azul urbano)
- **Tema**: claro / oscuro (CSS custom properties)
- **Tipografía**: Sora (títulos), IBM Plex Sans (cuerpo)
- **NO usar**: Inter, gradientes morados, estilos Bootstrap por defecto
- **Estilo**: Minimalista, limpio, sin decoraciones superfluas

## Estructura de Carpetas
```
urbanbike/
├── data/
│   ├── raw/          ← CSVs originales (ignorados en git)
│   └── parquet/      ← Parquets generados (ignorados en git)
├── etl/
│   ├── sql/          ← DDL de ClickHouse
│   ├── 01_extract_to_parquet.py
│   ├── 02_load_clickhouse.py
│   └── requirements.txt
├── pocketbase/
│   └── Dockerfile
├── app/
│   ├── routers/      ← FastAPI routers por rol
│   ├── templates/    ← Jinja2 HTML
│   └── static/       ← CSS, JS, imágenes
├── docs/
├── docker-compose.yml
├── .env              ← No commitear
├── .env.example
└── CLAUDE.md
```

## Convenciones de Código
- Nombres de tablas y columnas en **español** (excepto `ride_id` que viene del CSV)
- Nombres de archivos Python en formato `NN_descripcion.py` (numerados)
- SQL en mayúsculas para palabras reservadas
- Variables de entorno siempre desde `.env`, nunca hardcodeadas
- Type hints en todo código Python nuevo

## Comandos Frecuentes
```bash
# Levantar infraestructura
docker compose up -d

# ETL completo
cd etl
pip install -r requirements.txt
python 01_extract_to_parquet.py
python 02_load_clickhouse.py

# Iniciar app FastAPI (pendiente de implementar)
uvicorn app.main:app --reload
```

## Especificación SDD (Spec-Driven Development)

Este proyecto cuenta con una especificación formal generada con GitHub Spec Kit:

- Constitución del proyecto: `.specify/memory/constitution.md`
- Especificación operativa (17 casos de uso, 27 requisitos funcionales): `specs/001-operaciones-alquiler-bicicletas/spec.md`
- Plan de implementación verificado: `specs/001-operaciones-alquiler-bicicletas/plan.md`
- Modelo de datos confirmado contra código real: `specs/001-operaciones-alquiler-bicicletas/data-model.md`