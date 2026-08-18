"""DAG: ETL real de UrbanBike cada 1 hora.

Orquesta en secuencia los scripts que hasta el 06-ago-2026 se corrian a
mano (ver docs/HOJA_DE_RUTA.md punto 13, seccion 6), mas el paso de
membresias agregado el 11-ago-2026 (diseno de membresias aprobado):

  1. 07_migrar_viajes_pagos.py  -> urbanbike_operativa (alquileres/eventos)
  2. 08_calcular_tactica.py     -> urbanbike_tactica (dimensiones + fact_viajes + KPI)
  3. 09_calcular_estrategica.py -> urbanbike_estrategica (consolidados mensuales)
  4. 10_procesar_membresias.py  -> renueva o vence membresias, cobro simulado real

Cada script, ademas de escribir en ClickHouse, deja un archivo Parquet
real en datos/{crudo,proceso,terminado} identificado con la fecha y
hora exacta de esa corrida (ver etl/_snapshot.py y docs/datos_README.md).

Idempotencia verificada el 06-ago-2026 antes de programar este DAG
(correr cada script dos veces seguidas no duplica ni recalcula de mas,
ver docs/HOJA_DE_RUTA.md): los tres scripts originales se corrigieron
para esto antes de conectarlos aqui, requisito explicito antes de
programar ejecucion cada hora sin supervision. El paso 10 es
idempotente por diseno desde el dia uno (ver su propio docstring): una
membresia procesada deja de cumplir la condicion "activa y vencida", asi
que correrlo cada hora en vez de estrictamente una vez al dia no
duplica ni re-cobra nada.
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/opt/airflow/project"

default_args = {
    "owner": "urbanbike",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="urbanbike_etl_hourly",
    description="Migra viajes/pagos y recalcula KPI tactico/estrategico cada hora",
    default_args=default_args,
    start_date=datetime(2026, 8, 6),
    schedule_interval=timedelta(hours=1),
    catchup=False,
    max_active_runs=1,
    tags=["urbanbike", "etl"],
) as dag:

    migrar_viajes_pagos = BashOperator(
        task_id="migrar_viajes_pagos",
        bash_command=f"cd {PROJECT_DIR}/etl && python 07_migrar_viajes_pagos.py",
    )

    calcular_tactica = BashOperator(
        task_id="calcular_tactica",
        bash_command=f"cd {PROJECT_DIR}/etl && python 08_calcular_tactica.py",
    )

    calcular_estrategica = BashOperator(
        task_id="calcular_estrategica",
        bash_command=f"cd {PROJECT_DIR}/etl && python 09_calcular_estrategica.py",
    )

    procesar_membresias = BashOperator(
        task_id="procesar_membresias",
        bash_command=f"cd {PROJECT_DIR}/etl && python 10_procesar_membresias.py",
    )

    migrar_viajes_pagos >> calcular_tactica >> calcular_estrategica >> procesar_membresias
