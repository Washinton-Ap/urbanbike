"""
ETL paso 11 (unico, NO forma parte del DAG horario -- ver
docs/HOJA_DE_RUTA.md): backfill de facturas reales para los alquileres
historicos migrados en estado 'facturado'.

Alcance real, confirmado antes de escribir esto: 'facturado' no lo
dispara ningun codigo vivo de app/ hoy -- la unica via que lo produjo
fue etl/07_migrar_viajes_pagos.py, corrido una sola vez el 30-jul-2026
sobre datos historicos de PocketBase. Este backfill cubre SOLO esas
~18-19 filas ya existentes. No cubre alquileres nuevos -- para eso hace
falta resolver primero el puente pendiente de PocketBase->ClickHouse
para el flujo de reserva del ciclista (pendiente #14, seccion 6).

IVA: mismo criterio que facturas_repo (15%, calculado hacia atras sobre
alquileres.total ya real -- nunca se suma encima, el monto que el
ciclista ya vio/pago no cambia).

fecha_emision usa la fecha real del evento 'facturado' de cada
alquiler (alquiler_eventos.fecha), no "ahora" -- mismo dato que ya usa
_recibo_real() en ciclista.py para mostrar "fecha_facturacion".

Idempotente: salta cualquier alquiler que ya tenga una factura real
(facturas_repo.obtener_por_alquiler) -- correrlo dos veces no duplica
nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db import bicicletas_repo, clickhouse as ch, facturas_repo  # noqa: E402

# Hallazgo real (ronda de revision visual, Plan V3): el concepto original
# usaba `a.codigo` -- el codigo del ALQUILER (ej. "A-010486"), no el de la
# bicicleta -- en un texto que decia "bicicleta {codigo}", mostrando un
# identificador real pero equivocado, ademas de no traer nunca
# nombre/modelo ni tipo de bicicleta (confirmado en las 19 facturas reales
# ya emitidas: las 19 con el mismo patron). El propio esquema
# (01_operativa_schema.sql, comentario de factura_detalle.concepto) y el
# seed (02_operativa_seed.sql) ya mostraban el formato real esperado
# ("Alquiler por dia UB-014 Trek FX 3 Disc") -- nunca implementado aqui.
_ETIQUETA_MODALIDAD = {"hora": "por hora", "dia": "por día", "semana": "por semana"}


def _concepto_real(modalidad: str, id_bicicleta: str) -> str:
    etiqueta = _ETIQUETA_MODALIDAD.get(modalidad, modalidad)
    bici = bicicletas_repo.obtener(id_bicicleta)
    if not bici:
        # Bicicleta real ya no existe (borrada) -- no se inventa nada, se
        # deja constancia explicita en vez de repetir el bug de origen.
        return f"Alquiler {etiqueta} -- bicicleta no disponible"
    return f"Alquiler {etiqueta} {bici['codigo']} {bici['modelo']} ({bici['categoria']})"


def main() -> None:
    alquileres = ch.query("""
        SELECT a.id AS id, a.id_bicicleta AS id_bicicleta, a.modalidad AS modalidad,
               a.id_usuario AS id_usuario, a.total AS total, e.fecha AS fecha_facturacion
        FROM urbanbike_operativa.alquileres a FINAL
        JOIN urbanbike_operativa.alquiler_eventos e
            ON e.id_alquiler = a.id AND e.estado_destino = 'facturado'
        WHERE a.estado = 'facturado'
        ORDER BY e.fecha
    """)

    creadas = 0
    reparadas = 0
    saltadas = 0
    for a in alquileres:
        id_alquiler = str(a["id"])
        id_usuario = str(a["id_usuario"])
        concepto = _concepto_real(a["modalidad"], str(a["id_bicicleta"]))
        existente = facturas_repo.obtener_por_alquiler(id_alquiler, id_usuario)
        if existente:
            # Hallazgo real del revisor independiente (code-review, nivel
            # medium): sin este chequeo, correr el script una 2a vez
            # mutaba las 19 facturas ya reparadas otra vez, cada vez, aun
            # sin ningun cambio real en el texto -- contradecia la
            # idempotencia real que el docstring del modulo promete.
            # Ahora solo se compara y se muta si el concepto real
            # cambio de verdad.
            lineas = facturas_repo.detalle(existente["id"])
            if lineas and lineas[0]["concepto"] == concepto:
                saltadas += 1
                continue
            # Repara el texto real de una factura ya emitida (bug de
            # origen de esta misma migracion) -- no toca monto/estado,
            # solo el concepto de su unica linea de detalle. ALTER ...
            # UPDATE (no INSERT de "nueva version"): `concepto` no es
            # parte de ORDER BY (id_factura, linea), mismo criterio que
            # bicicletas_repo.actualizar().
            ch.get_client().command(
                "ALTER TABLE urbanbike_operativa.factura_detalle "
                "UPDATE concepto = %(concepto)s WHERE id_factura = %(id_factura)s",
                parameters={"concepto": concepto, "id_factura": existente["id"]},
                settings={"mutations_sync": 1},
            )
            reparadas += 1
            continue
        facturas_repo.emitir(
            id_usuario=id_usuario, total=float(a["total"]), concepto=concepto,
            id_alquiler=id_alquiler, fecha_emision=a["fecha_facturacion"],
        )
        creadas += 1

    print(
        f"backfill de facturas: {len(alquileres)} alquileres 'facturado' revisados, "
        f"{creadas} facturas creadas, {reparadas} con concepto reparado, "
        f"{saltadas} ya tenian el concepto real correcto (sin tocar)"
    )


if __name__ == "__main__":
    main()
