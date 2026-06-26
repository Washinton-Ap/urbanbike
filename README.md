# UrbanBike

Sistema web de alquiler de bicicletas con análisis de datos de Citibike NYC (3.7M viajes, octubre 2023).

## Requisitos previos

- Docker Desktop instalado y corriendo
- Python 3.11 o superior
- Git

## Instrucciones paso a paso

### 1. Clonar y configurar variables de entorno

```bash
git clone <url-del-repo>
cd urbanbike
cp .env.example .env
# Editar .env con tus contraseñas
```

### 2. Colocar los CSV

Copia los 4 archivos CSV de Citibike dentro de `data/raw/`:

```
data/raw/
├── 202310-citibike-tripdata_1.csv
├── 202310-citibike-tripdata_2.csv
├── 202310-citibike-tripdata_3.csv
└── 202310-citibike-tripdata_4.csv
```

### 3. Levantar Docker (ClickHouse + PocketBase)

```bash
docker compose up -d
```

Verifica que los contenedores estén sanos:

```bash
docker compose ps
```

Espera a que ambos servicios aparezcan como `healthy` (puede tomar ~30 segundos).

### 4. Instalar dependencias del ETL

```bash
cd etl
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

### 5. Ejecutar el ETL

**Paso 1** — Convertir CSV a Parquet (puede tardar 3-5 minutos):

```bash
python 01_extract_to_parquet.py
```

**Paso 2** — Cargar Parquet en ClickHouse:

```bash
python 02_load_clickhouse.py
```

### 6. Verificar la carga

Abre el navegador en `http://localhost:8123/play` y ejecuta:

```sql
SELECT COUNT() FROM urbanbike.fact_viajes;
-- Esperado: ~3.7 millones de filas
```

PocketBase admin estará disponible en `http://localhost:8090/_/`.

### 7. Iniciar la aplicación web

*(Próximamente)*

```bash
cd ..
uvicorn app.main:app --reload
```

## Arquitectura

```
CSV  →  DuckDB  →  Parquet  →  ClickHouse (KPIs del Gerente)
                              PocketBase  (Auth + CRUD operativo)
                              FastAPI + Jinja2 (Frontend web)
```

## Roles disponibles

| Rol                    | Descripción                               |
|------------------------|-------------------------------------------|
| Admin                  | Gestión total del sistema                 |
| Gerente                | Dashboard analítico de KPIs               |
| Ciclista               | Reservas y perfil personal                |
| Empleado-Operación     | Estado de bicicletas y estaciones         |
| Empleado-Mantenimiento | Reportes de mantenimiento                 |
| Empleado-Vigilancia    | Monitoreo en tiempo real                  |
