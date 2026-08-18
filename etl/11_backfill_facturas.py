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
from app.db import clickhouse as ch, facturas_repo  # noqa: E402


def main() -> None:
    alquileres = ch.query("""
        SELECT a.id AS id, a.codigo AS codigo, a.id_usuario AS id_usuario,
               a.total AS total, e.fecha AS fecha_facturacion
        FROM urbanbike_operativa.alquileres a FINAL
        JOIN urbanbike_operativa.alquiler_eventos e
            ON e.id_alquiler = a.id AND e.estado_destino = 'facturado'
        WHERE a.estado = 'facturado'
        ORDER BY e.fecha
    """)

    creadas = 0
    saltadas = 0
    for a in alquileres:
        id_alquiler = str(a["id"])
        id_usuario = str(a["id_usuario"])
        existente = facturas_repo.obtener_por_alquiler(id_alquiler, id_usuario)
        if existente:
            saltadas += 1
            continue
        facturas_repo.emitir(
            id_usuario=id_usuario, total=float(a["total"]),
            concepto=f"Alquiler de bicicleta {a['codigo']}",
            id_alquiler=id_alquiler, fecha_emision=a["fecha_facturacion"],
        )
        creadas += 1

    print(
        f"backfill de facturas: {len(alquileres)} alquileres 'facturado' revisados, "
        f"{creadas} facturas creadas, {saltadas} ya tenian factura (saltadas)"
    )


if __name__ == "__main__":
    main()
