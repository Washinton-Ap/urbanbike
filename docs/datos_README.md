# Carpeta `datos/`

Etapas del pipeline ETL de Airflow (corre cada 1 hora, ver
`docs/HOJA_DE_RUTA.md`). Los archivos Parquet no se versionan en git, solo
la estructura de carpetas (`.gitkeep`).

## `crudo/`
Extraído directo de la fuente, sin transformar. Es la copia fiel de lo que
llegó (CSV de Citibike o eventos operativos de `urbanbike_operativa`),
convertido a Parquet pero sin limpiar ni tipar.

## `proceso/`
Datos en transformación: limpieza, tipado, cálculo de dimensiones y de los
KPI que luego se guardan precalculados. Es el área de trabajo intermedia
del DAG, no un destino final.

## `terminado/`
Lo que el ETL ya validó y está listo para cargar hacia ClickHouse
(`urbanbike_tactica` y `urbanbike_estrategica`). Es la única etapa que se
conserva de forma permanente una vez que la carga a ClickHouse fue
exitosa.
