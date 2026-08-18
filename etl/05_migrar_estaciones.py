"""
ETL paso 5: Migra las 9 estaciones reales de PocketBase (coleccion
"estaciones", ya confirmada como la fuente de verdad frente a
"estaciones_op") hacia urbanbike_operativa.estaciones en ClickHouse.

Las 2 filas de prueba que ya existian en esa tabla (Estacion Central,
Malecon, ids 44444444-...0001/0002) no se tocan: esto solo agrega las 9
reales con ids nuevos. "direccion" no existe en PocketBase -> se inserta
vacia, no se inventa.
"""

import os
import sys
import uuid
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
    pb = get_admin_client()
    estaciones_pb = pb.list_records("estaciones", filter="activa = true",
                                     sort="nombre", per_page=50).get("items", [])
    print(f"PocketBase: {len(estaciones_pb)} estaciones reales")

    client = get_client()
    existentes = {r["nombre"] for r in client.query(
        "SELECT nombre FROM estaciones FINAL").named_results()}

    insertadas = 0
    for e in estaciones_pb:
        nombre = e.get("nombre", "")
        if nombre in existentes:
            print(f"  = ya existe, se omite: {nombre}")
            continue
        client.command("""
            INSERT INTO estaciones
                (id, codigo, nombre, direccion, latitud, longitud, capacidad, activa)
            VALUES
                (%(id)s, %(codigo)s, %(nombre)s, '', %(latitud)s, %(longitud)s,
                 %(capacidad)s, %(activa)s)
        """, parameters={
            "id": str(uuid.uuid4()),
            "codigo": e.get("codigo", ""),
            "nombre": nombre,
            "latitud": float(e.get("latitud") or 0),
            "longitud": float(e.get("longitud") or 0),
            "capacidad": int(e.get("capacidad") or 0),
            "activa": 1 if e.get("activa") else 0,
        })
        insertadas += 1
        print(f"  + insertada: {nombre}")

    print(f"\n{insertadas} estaciones nuevas insertadas")


if __name__ == "__main__":
    main()
