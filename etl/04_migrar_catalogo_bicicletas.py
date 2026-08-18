"""
ETL paso 4: Migra el catalogo real de bicicletas (docs/plantilla_bicicletas_completa.csv,
completado a mano a partir del inventario de PocketBase) hacia
urbanbike_operativa.{marcas,categorias,modelos_bicicleta,bicicletas}.

No toca viajes, pagos, ni ninguna otra tabla. No borra filas de prueba
existentes en estas cuatro tablas: solo agrega marcas/modelos que falten y
hace upsert (insert; no habia filas previas) de las 11 bicicletas reales.

id_estacion se deja en el UUID cero (sentinela de "sin estacion asignada
todavia"): la columna "estacion" del CSV es texto libre de PocketBase, no
un id real de urbanbike_operativa.estaciones, así que ese cruce se resuelve
en otra sesión.
"""

import csv
import os
import uuid
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

load_dotenv()

CSV_PATH = Path(__file__).parent.parent / "docs" / "plantilla_bicicletas_completa.csv"
DB = "urbanbike_operativa"
UUID_SIN_ESTACION = "00000000-0000-0000-0000-000000000000"
ANIO_MODELOS_NUEVOS = 2025  # el CSV no trae año; ver sesión de migración (2026-07-29)


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=DB,
    )


def leer_csv() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    filas = leer_csv()
    print(f"CSV leído: {len(filas)} bicicletas")
    client = get_client()

    # ── 1. Marcas ────────────────────────────────────────────────────────
    marcas_existentes = {r["nombre"]: r["id"] for r in client.query(
        "SELECT id, nombre FROM marcas").named_results()}
    marcas_csv = sorted({f["marca"] for f in filas})
    nuevas_marcas = [m for m in marcas_csv if m not in marcas_existentes]

    for nombre in nuevas_marcas:
        nuevo_id = str(uuid.uuid4())
        client.command(
            "INSERT INTO marcas (id, nombre) VALUES (%(id)s, %(nombre)s)",
            parameters={"id": nuevo_id, "nombre": nombre},
        )
        marcas_existentes[nombre] = nuevo_id
    print(f"Marcas nuevas insertadas: {nuevas_marcas or '(ninguna)'}")

    # ── 2. Categorias ────────────────────────────────────────────────────
    categorias_existentes = {r["nombre"]: r["id"] for r in client.query(
        "SELECT id, nombre FROM categorias").named_results()}
    categorias_csv = sorted({f["categoria"] for f in filas})
    nuevas_categorias = [c for c in categorias_csv if c not in categorias_existentes]
    # Se espera que sea vacío (Premium/Electrica/Estandar ya existen);
    # si aparece una nueva categoría en el CSV, se inserta con es_premium=0
    # por defecto y debe revisarse a mano.
    for nombre in nuevas_categorias:
        nuevo_id = str(uuid.uuid4())
        client.command(
            "INSERT INTO categorias (id, nombre) VALUES (%(id)s, %(nombre)s)",
            parameters={"id": nuevo_id, "nombre": nombre},
        )
        categorias_existentes[nombre] = nuevo_id
    print(f"Categorías nuevas insertadas: {nuevas_categorias or '(ninguna)'}")

    # ── 3. Modelos ───────────────────────────────────────────────────────
    modelos_existentes = list(client.query("""
        SELECT m.id AS id, ma.nombre AS marca, c.nombre AS categoria,
               m.nombre AS nombre, m.enfoque AS enfoque, m.marchas AS marchas,
               m.tipo_frenos AS tipo_frenos, m.material_cuadro AS material_cuadro,
               m.suspension AS suspension, m.rodado AS rodado, m.peso_kg AS peso_kg,
               m.es_electrica AS es_electrica, m.autonomia_km AS autonomia_km
        FROM modelos_bicicleta m
        JOIN marcas ma ON ma.id = m.id_marca
        JOIN categorias c ON c.id = m.id_categoria
    """).named_results())

    def specs_csv(f: dict) -> tuple:
        return (
            f["enfoque"], int(f["marchas"]), f["tipo_frenos"], f["material_cuadro"],
            f["suspension"], int(f["rodado"]), round(float(f["peso_kg"]), 2),
            int(f["es_electrica"]), int(f["autonomia_km"]),
        )

    def specs_existente(m: dict) -> tuple:
        return (
            m["enfoque"], int(m["marchas"]), m["tipo_frenos"], m["material_cuadro"],
            m["suspension"], int(m["rodado"]), round(float(m["peso_kg"]), 2),
            int(m["es_electrica"]), int(m["autonomia_km"]),
        )

    # combinaciones únicas marca+modelo+categoria+specs del CSV
    vistos: dict[tuple, str] = {}   # (marca, modelo, categoria) -> id_modelo resuelto
    for f in filas:
        clave = (f["marca"], f["modelo"], f["categoria"])
        if clave in vistos:
            continue

        candidato = next(
            (m for m in modelos_existentes
             if m["marca"] == f["marca"] and m["categoria"] == f["categoria"]
             and m["nombre"] == f"{f['marca']} {f['modelo']}"),
            None,
        )

        if candidato and specs_existente(candidato) == specs_csv(f):
            # Coincide exacto: reutilizar id existente, sin insertar nada.
            vistos[clave] = candidato["id"]
            print(f"  = modelo ya existe (idéntico): {clave[0]} {clave[1]}")
            continue

        if candidato:
            # Coincide en identidad pero difieren specs (caso Scott Sub Cross
            # 40: peso 13.80 de prueba vs 13.5 real) -> se actualiza el mismo
            # id_modelo con los datos reales del CSV (decisión confirmada).
            client.command("""
                INSERT INTO modelos_bicicleta
                    (id, id_marca, id_categoria, nombre, anio, enfoque, marchas,
                     tipo_frenos, material_cuadro, suspension, rodado, peso_kg,
                     es_electrica, autonomia_km)
                VALUES
                    (%(id)s, %(id_marca)s, %(id_categoria)s, %(nombre)s, %(anio)s,
                     %(enfoque)s, %(marchas)s, %(tipo_frenos)s, %(material_cuadro)s,
                     %(suspension)s, %(rodado)s, %(peso_kg)s, %(es_electrica)s,
                     %(autonomia_km)s)
            """, parameters={
                "id": candidato["id"],
                "id_marca": marcas_existentes[f["marca"]],
                "id_categoria": categorias_existentes[f["categoria"]],
                "nombre": f"{f['marca']} {f['modelo']}",
                "anio": ANIO_MODELOS_NUEVOS,
                "enfoque": f["enfoque"], "marchas": int(f["marchas"]),
                "tipo_frenos": f["tipo_frenos"], "material_cuadro": f["material_cuadro"],
                "suspension": f["suspension"], "rodado": int(f["rodado"]),
                "peso_kg": float(f["peso_kg"]), "es_electrica": int(f["es_electrica"]),
                "autonomia_km": int(f["autonomia_km"]),
            })
            vistos[clave] = candidato["id"]
            print(f"  ~ modelo actualizado (specs reales distintas): {clave[0]} {clave[1]}")
            continue

        # Modelo nuevo
        nuevo_id = str(uuid.uuid4())
        client.command("""
            INSERT INTO modelos_bicicleta
                (id, id_marca, id_categoria, nombre, anio, enfoque, marchas,
                 tipo_frenos, material_cuadro, suspension, rodado, peso_kg,
                 es_electrica, autonomia_km)
            VALUES
                (%(id)s, %(id_marca)s, %(id_categoria)s, %(nombre)s, %(anio)s,
                 %(enfoque)s, %(marchas)s, %(tipo_frenos)s, %(material_cuadro)s,
                 %(suspension)s, %(rodado)s, %(peso_kg)s, %(es_electrica)s,
                 %(autonomia_km)s)
        """, parameters={
            "id": nuevo_id,
            "id_marca": marcas_existentes[f["marca"]],
            "id_categoria": categorias_existentes[f["categoria"]],
            "nombre": f"{f['marca']} {f['modelo']}",
            "anio": ANIO_MODELOS_NUEVOS,
            "enfoque": f["enfoque"], "marchas": int(f["marchas"]),
            "tipo_frenos": f["tipo_frenos"], "material_cuadro": f["material_cuadro"],
            "suspension": f["suspension"], "rodado": int(f["rodado"]),
            "peso_kg": float(f["peso_kg"]), "es_electrica": int(f["es_electrica"]),
            "autonomia_km": int(f["autonomia_km"]),
        })
        vistos[clave] = nuevo_id
        print(f"  + modelo nuevo: {clave[0]} {clave[1]}")

    # ── 4. Bicicletas ────────────────────────────────────────────────────
    for f in filas:
        clave = (f["marca"], f["modelo"], f["categoria"])
        id_modelo = vistos[clave]
        client.command("""
            INSERT INTO bicicletas
                (id, codigo, id_modelo, id_estacion, numero_serie, estado,
                 fecha_adquisicion, observacion)
            VALUES
                (%(id)s, %(codigo)s, %(id_modelo)s, %(id_estacion)s, %(numero_serie)s,
                 %(estado)s, %(fecha_adquisicion)s, %(observacion)s)
        """, parameters={
            "id": str(uuid.uuid4()),
            "codigo": f["codigo"],
            "id_modelo": id_modelo,
            "id_estacion": UUID_SIN_ESTACION,
            "numero_serie": "",
            "estado": f["estado"],
            "fecha_adquisicion": "1970-01-01",
            "observacion": f.get("notas", "") or "",
        })
    print(f"Bicicletas insertadas: {len(filas)}")


if __name__ == "__main__":
    main()
