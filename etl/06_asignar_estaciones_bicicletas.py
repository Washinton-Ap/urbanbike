"""
ETL paso 6: Asigna bicicletas.id_estacion para las 11 bicicletas reales,
enlazandolas por coincidencia EXACTA de nombre contra
urbanbike_operativa.estaciones (ya migrada con las 9 reales en el paso 5).

Comparacion ya verificada en docs/comparacion_estaciones.md: las 11
coinciden exacto, no hace falta normalizar ni adivinar.

ReplacingMergeTree no tiene UPDATE: se reinserta la fila completa con el
mismo id y una version mas nueva, cambiando solo id_estacion.
"""

import os
import sys
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

load_dotenv()

DB = "urbanbike_operativa"


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=DB,
    )


def main():
    client = get_client()
    pb = get_admin_client()

    estacion_id_por_nombre = {
        r["nombre"]: r["id"] for r in
        client.query("SELECT id, nombre FROM estaciones FINAL").named_results()
    }

    bicis_pb = {b["codigo"]: b for b in
                pb.list_records("bicicletas", per_page=200).get("items", [])}

    bicis_ch = list(client.query("""
        SELECT id, codigo, id_modelo, id_estacion, numero_serie, estado,
               fecha_adquisicion, km_acumulados, minutos_uso,
               fecha_ultimo_mantenimiento, observacion
        FROM bicicletas FINAL
        WHERE codigo LIKE 'UB-0%'
    """).named_results())

    actualizadas = 0
    for b in bicis_ch:
        codigo = b["codigo"]
        nombre_estacion = bicis_pb.get(codigo, {}).get("estacion", "")
        id_estacion = estacion_id_por_nombre.get(nombre_estacion)
        if not id_estacion:
            print(f"  ! sin coincidencia para {codigo} ({nombre_estacion!r}), se omite")
            continue

        client.command("""
            INSERT INTO bicicletas
                (id, codigo, id_modelo, id_estacion, numero_serie, estado,
                 fecha_adquisicion, km_acumulados, minutos_uso,
                 fecha_ultimo_mantenimiento, observacion)
            VALUES
                (%(id)s, %(codigo)s, %(id_modelo)s, %(id_estacion)s, %(numero_serie)s,
                 %(estado)s, %(fecha_adquisicion)s, %(km_acumulados)s, %(minutos_uso)s,
                 %(fecha_ultimo_mantenimiento)s, %(observacion)s)
        """, parameters={
            "id": b["id"], "codigo": b["codigo"], "id_modelo": b["id_modelo"],
            "id_estacion": id_estacion, "numero_serie": b["numero_serie"],
            "estado": b["estado"], "fecha_adquisicion": b["fecha_adquisicion"],
            "km_acumulados": b["km_acumulados"], "minutos_uso": b["minutos_uso"],
            "fecha_ultimo_mantenimiento": b["fecha_ultimo_mantenimiento"],
            "observacion": b["observacion"],
        })
        print(f"  + {codigo} -> {nombre_estacion}")
        actualizadas += 1

    print(f"\n{actualizadas} bicicletas actualizadas")


if __name__ == "__main__":
    main()
