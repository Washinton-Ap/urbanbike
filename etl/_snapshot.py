"""Snapshot Parquet real de cada corrida del DAG de Airflow hacia
datos/{crudo,proceso,terminado} (ver docs/HOJA_DE_RUTA.md seccion 2 y
docs/datos_README.md). Cada llamada usa la fecha y hora exacta de esa
corrida en el nombre del archivo, para no pisar la corrida anterior."""

from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DATOS_DIR = Path(__file__).parent.parent / "datos"


def guardar_parquet(etapa: str, nombre: str, filas: list, columnas: list[str]) -> Path:
    """etapa: 'crudo'|'proceso'|'terminado'."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DATOS_DIR / etapa / f"{nombre}_{ts}.parquet"
    columnas_dict = {
        c: [None if fila[i] is None else str(fila[i]) for fila in filas]
        for i, c in enumerate(columnas)
    }
    tabla = (
        pa.table(columnas_dict)
        if filas
        else pa.table({c: pa.array([], type=pa.string()) for c in columnas})
    )
    pq.write_table(tabla, destino)
    print(f"  snapshot: datos/{etapa}/{destino.name} ({len(filas)} filas)")
    return destino
