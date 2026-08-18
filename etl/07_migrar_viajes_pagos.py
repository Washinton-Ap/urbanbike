"""
ETL paso 7: Migra los viajes y pagos reales de PocketBase (colecciones
"viajes" y "pagos") hacia urbanbike_operativa.alquileres y
urbanbike_operativa.alquiler_eventos.

Reglas de mapeo (confirmadas en la sesion del 29-jul-2026, ver
docs/HOJA_DE_RUTA.md seccion 6 y 8):

  El sistema viejo (PocketBase) solo tiene 3 estados de viaje
  (activo/completado/cancelado); el nuevo tiene 6. No se inventan pasos
  que no ocurrieron:
    - reservado y en_curso: ambos con fecha_inicio real (el sistema
      viejo nunca separo reserva de recogida).
    - devuelto: fecha_fin real, solo si viaje.estado == 'completado'.
    - facturado: fecha_confirmacion del pago (o fecha_pago si la
      primera esta vacia -- los pagos electronicos con tarjeta o
      transferencia se confirman al instante y no llenan
      fecha_confirmacion), solo si existe un pago de alquiler en
      estado 'pagado'.
    - inspeccionado y cerrado: NUNCA se generan para migrados, esos
      pasos no existian en el sistema viejo.
  - viaje.estado == 'cancelado' -> alquiler.estado='cancelado', un solo
    evento (reservado). No hay ninguno en los datos reales de hoy, pero
    el codigo lo soporta.
  - El pago tipo 'cargo_danos' (1 de 22) queda fuera de alcance: es un
    cargo de garantia/infraccion, no una tarifa de alquiler. No se
    migra hoy (pendiente, ver HOJA_DE_RUTA).

Resolucion de columnas sin correspondencia directa (decisiones
confirmadas con Washington el 29-jul-2026):
  - id_usuario: no existia fila en usuarios para el ciclista real
    (Adrian Guizado, PocketBase ciclista@urbanbike.com) ni para el
    empleado que confirma pagos en efectivo (Test Empleado,
    empleado@urbanbike.com). Se crean ambos usuarios si no existen
    (idempotente, buscando primero por email).
  - id_tarifa: pagos.tipo_bicicleta usa nomenclatura Citibike
    (classic_bike/electric_bike) y los precio_hora historicos no
    coinciden con la tarifa vigente hoy (los precios cambian con el
    tiempo). Se resuelve la categoria real desde
    bicicleta_codigo -> bicicletas.id_modelo -> categoria, se cruza con
    tipo_membresia del pago y modalidad='hora' (todos los pagos reales
    de hoy usan precio_hora) para ubicar el id_tarifa vigente de esa
    combinacion. subtotal/total usan el monto_total REAL del pago
    historico, no el precio de la tarifa de hoy.
  - Viajes sin ningun pago asociado (5 de 26): id_tarifa queda en
    UUID_SENTINELA (mismo patron que "sin estacion asignada" del ETL
    04) y subtotal/descuento/recargo/total en 0: no se inventa una
    membresia que no quedo registrada.
  - cantidad_contratada/minutos_contratados: el sistema viejo nunca
    distinguio "contratado" de "real", asi que se iguala
    minutos_contratados = minutos_reales y cantidad_contratada al
    numero de horas (redondeado hacia arriba, minimo 1).

es_prueba: el viaje 7j39ut1z9ztgan3 (UB-001, 2026-06-07 a 2026-06-22,
20457 minutos) fue confirmado por Washington como una prueba real de
desarrollo, no un alquiler real. Migra completo pero con es_prueba=1.
Todo KPI/informe que calcule duracion, ingresos o promedios debe
filtrar WHERE es_prueba = 0 para no distorsionar los numeros reales.

Idempotencia (agregado 06-ago-2026, ver docs/HOJA_DE_RUTA.md): la
auditoria previa a conectar este script a Airflow encontro que no tenia
ninguna guarda -- cada corrida reinsertaba TODOS los viajes de
PocketBase como alquileres nuevos, con UUID e id_alquiler distintos.
Se agrego alquileres.id_origen_pocketbase (= viajes.id de PocketBase)
como clave real de idempotencia: antes de migrar, el script carga los
id_origen_pocketbase ya presentes y salta cualquier viaje ya migrado.
Los 26 alquileres migrados el 30-jul-2026 se backfillearon con esta
columna a partir del rastro de texto libre que dejaban en
alquiler_eventos.observacion (mismo dato, ahora en columna real -- ver
seccion 17 de HOJA_DE_RUTA.md, resuelto).
"""

import math
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import clickhouse_connect
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from app.db.pocketbase import get_admin_client  # noqa: E402
from _snapshot import guardar_parquet  # noqa: E402

load_dotenv()

DB = "urbanbike_operativa"
UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"
VIAJE_PRUEBA_DEV = "7j39ut1z9ztgan3"


def get_client():
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_HTTP_PORT", 8123)),
        username=os.getenv("CLICKHOUSE_USER", "default"),
        password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        database=DB,
    )


def parse_fecha(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)


def asegurar_usuario(client, *, email: str, nombre: str, apellido: str, rol: str) -> str:
    """Devuelve el id del usuario, creandolo si no existe (busca por email)."""
    existentes = client.query(
        "SELECT id FROM usuarios WHERE email = %(email)s", parameters={"email": email}
    ).result_rows
    if existentes:
        return str(existentes[0][0])

    nuevo_id = str(uuid.uuid4())
    ultimo_codigo = client.query(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM usuarios"
    ).result_rows[0][0] or 0
    codigo = f"U-{ultimo_codigo + 1:04d}"
    client.command(
        """
        INSERT INTO usuarios (id, codigo, nombre, apellido, email, rol, estado)
        VALUES (%(id)s, %(codigo)s, %(nombre)s, %(apellido)s, %(email)s, %(rol)s, 'activo')
        """,
        parameters={
            "id": nuevo_id, "codigo": codigo, "nombre": nombre,
            "apellido": apellido, "email": email, "rol": rol,
        },
    )
    print(f"  + usuario creado: {codigo} {nombre} {apellido} ({rol})")
    return nuevo_id


def main():
    pb = get_admin_client()
    ch = get_client()

    viajes = pb.list_records("viajes", sort="fecha_inicio", per_page=200).get("items", [])
    pagos_todos = pb.list_records("pagos", per_page=200).get("items", [])
    estaciones_pb = pb.list_records("estaciones", per_page=200).get("items", [])
    print(f"PocketBase: {len(viajes)} viajes, {len(pagos_todos)} pagos, {len(estaciones_pb)} estaciones")

    ya_migrados = {r[0] for r in ch.query(
        "SELECT id_origen_pocketbase FROM alquileres FINAL WHERE id_origen_pocketbase != ''"
    ).result_rows}
    if ya_migrados:
        print(f"  {len(ya_migrados)} viaje(s) ya migrados antes, se saltan (idempotencia)")

    pagos_alquiler = [p for p in pagos_todos if p.get("tipo") != "cargo_danos"]
    descartados = len(pagos_todos) - len(pagos_alquiler)
    if descartados:
        print(f"  {descartados} pago(s) tipo cargo_danos fuera de alcance (no se migran hoy)")

    pago_por_viaje = {}
    for p in pagos_alquiler:
        pago_por_viaje.setdefault(p.get("viaje_id"), []).append(p)

    id2nombre_estacion_pb = {e["id"]: e["nombre"] for e in estaciones_pb}

    # ── Lookups en ClickHouse operativa ─────────────────────────────────
    bicicletas = {r["codigo"]: (r["id"], r["id_modelo"]) for r in ch.query(
        "SELECT codigo, id, id_modelo FROM bicicletas FINAL").named_results()}
    modelo_a_categoria = {r["id"]: r["id_categoria"] for r in ch.query(
        "SELECT id, id_categoria FROM modelos_bicicleta FINAL").named_results()}
    categoria_nombre = {r["id"]: r["nombre"] for r in ch.query(
        "SELECT id, nombre FROM categorias FINAL").named_results()}
    estaciones = {r["nombre"]: r["id"] for r in ch.query(
        "SELECT nombre, id FROM estaciones FINAL").named_results()}
    tarifas = {(r["categoria"], r["tipo_membresia"], r["modalidad"]): r["id"] for r in ch.query("""
        SELECT t.id AS id, c.nombre AS categoria, t.tipo_membresia AS tipo_membresia, t.modalidad AS modalidad
        FROM tarifas t FINAL JOIN categorias c FINAL ON c.id = t.id_categoria
        WHERE t.estado = 'vigente'
    """).named_results()}

    # ── Usuarios que no existian ─────────────────────────────────────────
    id_ciclista = asegurar_usuario(
        ch, email="ciclista@urbanbike.com", nombre="Adrian", apellido="Guizado", rol="ciclista")
    id_empleado_operacion = asegurar_usuario(
        ch, email="empleado@urbanbike.com", nombre="Test", apellido="Empleado", rol="operacion")

    siguiente_codigo = 1 + (ch.query(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM alquileres"
    ).result_rows[0][0] or 0)

    resumen_estados = {}
    ejemplos = []

    saltados = 0
    for v in viajes:
        if v["id"] in ya_migrados:
            saltados += 1
            continue

        codigo_bici = v.get("bicicleta_codigo", "")
        if codigo_bici not in bicicletas:
            print(f"  ! viaje {v['id']}: bicicleta_codigo {codigo_bici!r} no existe en bicicletas, se omite")
            continue
        id_bicicleta, id_modelo = bicicletas[codigo_bici]
        categoria = categoria_nombre.get(modelo_a_categoria.get(id_modelo, ""), "")

        nombre_ini = v.get("estacion_inicio_nombre", "")
        nombre_fin = id2nombre_estacion_pb.get(v.get("estacion_fin_id", ""), "")
        id_estacion_inicio = estaciones.get(nombre_ini)
        id_estacion_fin = estaciones.get(nombre_fin, "")
        if id_estacion_inicio is None:
            print(f"  ! viaje {v['id']}: estacion de inicio {nombre_ini!r} no resuelve, se omite")
            continue

        pagos_v = pago_por_viaje.get(v["id"], [])
        pago = pagos_v[0] if pagos_v else None

        modalidad = "hora"
        minutos_reales = int(v.get("duracion_minutos", 0))
        cantidad_contratada = max(1, math.ceil(minutos_reales / 60))

        if pago:
            tipo_membresia = pago.get("tipo_membresia") or "casual"
            id_tarifa = tarifas.get((categoria, tipo_membresia, modalidad), UUID_SENTINELA)
            monto = float(pago.get("monto_total") or 0)
        else:
            id_tarifa = UUID_SENTINELA
            monto = 0.0

        fecha_inicio = parse_fecha(v["fecha_inicio"])
        fecha_fin = parse_fecha(v["fecha_fin"]) if v.get("fecha_fin") else fecha_inicio

        if v["estado"] == "cancelado":
            estado_final = "cancelado"
        elif v["estado"] == "completado":
            estado_final = "facturado" if (pago and pago["estado"] == "pagado") else "devuelto"
        else:  # 'activo': no hay ninguno en los datos de hoy, se deja en_curso por consistencia
            estado_final = "en_curso"

        id_alquiler = str(uuid.uuid4())
        codigo = f"A-{siguiente_codigo:06d}"
        siguiente_codigo += 1
        es_prueba = 1 if v["id"] == VIAJE_PRUEBA_DEV else 0

        ch.command("""
            INSERT INTO alquileres
                (id, codigo, id_usuario, id_bicicleta, id_tarifa, id_estacion_inicio,
                 id_estacion_fin, modalidad, cantidad_contratada, minutos_contratados,
                 fecha_reserva, fecha_inicio, fecha_fin, minutos_reales, estado,
                 subtotal, descuento, recargo, total, es_prueba, id_origen_pocketbase)
            VALUES
                (%(id)s, %(codigo)s, %(id_usuario)s, %(id_bicicleta)s, %(id_tarifa)s,
                 %(id_estacion_inicio)s, %(id_estacion_fin)s, %(modalidad)s,
                 %(cantidad_contratada)s, %(minutos_contratados)s, %(fecha_reserva)s,
                 %(fecha_inicio)s, %(fecha_fin)s, %(minutos_reales)s, %(estado)s,
                 %(subtotal)s, 0, 0, %(total)s, %(es_prueba)s, %(id_origen_pocketbase)s)
        """, parameters={
            "id": id_alquiler, "codigo": codigo, "id_usuario": id_ciclista,
            "id_bicicleta": id_bicicleta, "id_tarifa": id_tarifa,
            "id_estacion_inicio": id_estacion_inicio, "id_estacion_fin": id_estacion_fin,
            "modalidad": modalidad, "cantidad_contratada": cantidad_contratada,
            "minutos_contratados": minutos_reales, "fecha_reserva": fecha_inicio,
            "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
            "minutos_reales": minutos_reales, "estado": estado_final,
            "subtotal": monto, "total": monto, "es_prueba": es_prueba,
            "id_origen_pocketbase": v["id"],
        })

        eventos = [(1, "", "reservado", fecha_inicio, id_ciclista, "ciclista",
                    f"Migrado de PocketBase (viaje {v['id']})")]
        if estado_final != "cancelado":
            eventos.append((2, "reservado", "en_curso", fecha_inicio, id_ciclista, "ciclista",
                             f"Recogida en {nombre_ini} (migrado)"))
        if estado_final in ("devuelto", "facturado"):
            eventos.append((3, "en_curso", "devuelto", fecha_fin, id_ciclista, "ciclista",
                             f"Devolucion en {nombre_fin or '(sin registro)'} (migrado)"))
        if estado_final == "facturado":
            fecha_conf_raw = pago.get("fecha_confirmacion") or pago.get("fecha_pago")
            fecha_conf = parse_fecha(fecha_conf_raw) if fecha_conf_raw else fecha_fin
            if pago.get("confirmado_por_empleado_id"):
                actor, rol_actor = id_empleado_operacion, "operacion"
            else:
                actor, rol_actor = id_ciclista, "ciclista"
            eventos.append((4, "devuelto", "facturado", fecha_conf, actor, rol_actor,
                             f"Pago {pago.get('metodo_pago', '')} confirmado (migrado, pago {pago['id']})"))

        for secuencia, origen, destino, fecha, actor, rol_actor, obs in eventos:
            ch.command("""
                INSERT INTO alquiler_eventos
                    (id_alquiler, secuencia, estado_origen, estado_destino, fecha,
                     id_actor, rol_actor, observacion)
                VALUES
                    (%(id_alquiler)s, %(secuencia)s, %(origen)s, %(destino)s, %(fecha)s,
                     %(actor)s, %(rol_actor)s, %(obs)s)
            """, parameters={
                "id_alquiler": id_alquiler, "secuencia": secuencia, "origen": origen,
                "destino": destino, "fecha": fecha, "actor": actor,
                "rol_actor": rol_actor, "obs": obs,
            })

        resumen_estados[estado_final] = resumen_estados.get(estado_final, 0) + 1
        if len(ejemplos) < 3:
            ejemplos.append((codigo, v["id"], estado_final))

    print(f"\n{saltados} viaje(s) ya migrados, saltados en esta corrida (idempotencia)")
    print("Alquileres migrados por estado final:")
    for estado, n in sorted(resumen_estados.items()):
        print(f"  {estado}: {n}")
    print("\nEjemplos para revisar la linea de tiempo:", ejemplos)

    # datos/crudo: lo que llego de PocketBase esta corrida, sin transformar
    # (ver docs/datos_README.md) -- todos los viajes leidos, migrados o no.
    guardar_parquet(
        "crudo", "07_migrar_viajes_pagos", [
            (v["id"], v.get("bicicleta_codigo", ""), v.get("estacion_inicio_nombre", ""),
             v.get("estacion_fin_id", ""), v.get("fecha_inicio", ""), v.get("fecha_fin", ""),
             v.get("duracion_minutos", 0), v["estado"])
            for v in viajes
        ],
        ["viaje_id", "bicicleta_codigo", "estacion_inicio_nombre", "estacion_fin_id",
         "fecha_inicio", "fecha_fin", "duracion_minutos", "estado"],
    )


if __name__ == "__main__":
    main()
