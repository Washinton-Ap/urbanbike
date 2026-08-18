# Imagen de Airflow extendida con las dependencias del ETL real
# (etl/07_migrar_viajes_pagos.py, 08_calcular_tactica.py,
# 09_calcular_estrategica.py) para poder ejecutarlos como tareas del DAG
# en vez de a mano. Ver docker-compose.yml (servicios airflow-*).
FROM apache/airflow:2.10.4-python3.11

# --constraint: archivo oficial que publica el propio proyecto Airflow
# para esta version exacta (2.10.4) + Python 3.11 (ver
# docs/HOJA_DE_RUTA.md). Sin esto, "pip install" resuelve
# duckdb/pyarrow/clickhouse-connect libremente y puede elegir una version
# que choque con lo que Airflow ya fija internamente (pydantic,
# SQLAlchemy, etc.) sin ningun aviso -- --constraint no fuerza una
# version en paquetes que Airflow no usa (duckdb, clickhouse-connect),
# solo evita que el resolvedor de pip se salga del rango que Airflow ya
# valido para los paquetes que sí comparte (ej. pyarrow, requests).
ARG AIRFLOW_VERSION=2.10.4
ARG PYTHON_VERSION=3.11
ARG CONSTRAINT_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt

COPY etl/requirements.txt /tmp/etl-requirements.txt
RUN pip install --no-cache-dir --constraint "${CONSTRAINT_URL}" -r /tmp/etl-requirements.txt requests
