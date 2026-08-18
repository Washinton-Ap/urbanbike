"""Repositorio de facturacion real (urbanbike_operativa.facturas +
factura_detalle).

IVA vigente en Ecuador: 15% (confirmado con Washington, sin cambios en
2026 -- ver docs/HOJA_DE_RUTA.md). El precio que el sistema ya cobra en
cualquier punto (pagos.monto, membresias.precio, alquileres.total) se
trata como precio final al consumidor, IVA YA INCLUIDO -- nunca se le
suma nada encima. subtotal/iva se calculan hacia atras a partir del
total real ya cobrado, para no cambiar ningun monto que el ciclista ya
vio o pago.

Cada factura de hoy es de 1 sola linea (un solo concepto por
transaccion real: una membresia, o un alquiler ya facturado) -- no hace
falta soportar facturas multi-linea todavia, ninguna transaccion real
del sistema genera mas de un cargo a la vez.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from app.db import clickhouse as ch

IVA_TASA = Decimal("0.15")
SERIE = "001-001"
SENTINELA = "00000000-0000-0000-0000-000000000000"


def _redondear(valor) -> float:
    return float(Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def desglosar_iva(total: float) -> tuple[float, float]:
    """(subtotal, iva) calculados hacia atras desde un total que YA
    incluye IVA -- ver nota del modulo. `total` nunca cambia; solo se
    reparte en sus dos componentes."""
    total_d = Decimal(str(total))
    subtotal_d = total_d / (Decimal("1") + IVA_TASA)
    iva_d = total_d - subtotal_d
    return _redondear(subtotal_d), _redondear(iva_d)


def siguiente_numero(serie: str = SERIE) -> str:
    """Correlativo real por serie -- mismo patron que
    alquileres_repo._siguiente_codigo() (MAX + 1 sobre la tabla real,
    nunca aleatorio)."""
    maximo = ch.scalar(
        "SELECT max(toUInt32OrZero(numero)) FROM urbanbike_operativa.facturas FINAL "
        "WHERE serie = %(serie)s",
        {"serie": serie},
    ) or 0
    return f"{maximo + 1:09d}"


def emitir(
    *, id_usuario: str, total: float, concepto: str,
    id_alquiler: str | None = None, fecha_emision: datetime | None = None,
) -> str:
    """Emite una factura real de 1 linea y su detalle. Retorna el id de
    la factura creada. `id_alquiler` usa el UUID sentinela cuando el
    cargo no es un alquiler (ej. membresia) -- mismo patron que ya usa
    `pagos.id_alquiler` en membresias_repo."""
    subtotal, iva = desglosar_iva(total)
    id_factura = str(uuid.uuid4())
    numero = siguiente_numero()
    fecha = fecha_emision or datetime.utcnow()

    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.facturas
            (id, serie, numero, id_alquiler, id_usuario, fecha_emision,
             subtotal, descuento, impuesto, total, estado)
        VALUES
            (%(id)s, %(serie)s, %(numero)s, %(id_alquiler)s, %(id_usuario)s, %(fecha)s,
             %(subtotal)s, 0, %(iva)s, %(total)s, 'emitida')
    """, parameters={
        "id": id_factura, "serie": SERIE, "numero": numero,
        "id_alquiler": id_alquiler or SENTINELA, "id_usuario": id_usuario, "fecha": fecha,
        "subtotal": subtotal, "iva": iva, "total": total,
    })

    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.factura_detalle
            (id, id_factura, linea, concepto, cantidad, precio_unitario, descuento, subtotal)
        VALUES
            (%(id)s, %(id_factura)s, 1, %(concepto)s, 1, %(precio_unitario)s, 0, %(subtotal)s)
    """, parameters={
        "id": str(uuid.uuid4()), "id_factura": id_factura, "concepto": concepto,
        "precio_unitario": subtotal, "subtotal": subtotal,
    })
    return id_factura


def obtener(id_factura: str, id_usuario: str) -> dict | None:
    """Encabezado real, exige id_usuario -- misma regla de propiedad
    que membresias_repo.obtener()."""
    return ch.query_one("""
        SELECT id, serie, numero, id_alquiler, id_usuario, fecha_emision,
               subtotal, descuento, impuesto, total, estado
        FROM urbanbike_operativa.facturas FINAL
        WHERE id = %(id)s AND id_usuario = %(id_usuario)s
    """, {"id": id_factura, "id_usuario": id_usuario})


def obtener_por_alquiler(id_alquiler: str, id_usuario: str) -> dict | None:
    return ch.query_one("""
        SELECT id, serie, numero, id_alquiler, id_usuario, fecha_emision,
               subtotal, descuento, impuesto, total, estado
        FROM urbanbike_operativa.facturas FINAL
        WHERE id_alquiler = %(id_alquiler)s AND id_usuario = %(id_usuario)s
    """, {"id_alquiler": id_alquiler, "id_usuario": id_usuario})


def detalle(id_factura: str) -> list[dict]:
    return ch.query("""
        SELECT linea, concepto, cantidad, precio_unitario, descuento, subtotal
        FROM urbanbike_operativa.factura_detalle FINAL
        WHERE id_factura = %(id)s
        ORDER BY linea
    """, {"id": id_factura})
