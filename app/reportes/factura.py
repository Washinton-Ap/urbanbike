"""Factura con marca UrbanBike (ver docs/Requerimientos_Mejoras_UrbanBike.md,
punto 11): reemplaza el comprobante genérico plano que usaban
ciclista.py:comprobante()/comprobante_pago_pdf() y
membresia_comprobante()/membresia_comprobante_pdf() -- mismo documento para
los dos orígenes (pago de viaje, membresía), solo cambian las líneas de
detalle que arma cada router.

Logo y paleta: reales (Washington los confirmó), ver `LOGO_PATH` y
`AZUL_PIZARRA`/`NAVY_TEXTO`/`CIAN_ACENTO` abajo -- independientes del azul
institucional #1E86BD de main.css (ese sigue siendo el color de acento del
resto de la UI; la factura usa la paleta propia del logo, no la del sitio).
El PNG (`app/static/img/logo-urbanbike.png`) es un recorte del isotipo
(bicicletas formando una "U") extraído de LOGO01.png con el fondo hecho
transparente -- el archivo "isotipo" que Washington compartió aparte es un
render de mockup (relieve 3D sobre metal cepillado) no apto para incrustar
en un documento, así que no se usó directamente.

Datos de la empresa (razón social/dirección/RUC/teléfono): ficticios pero
definitivos del proyecto, ver `EMPRESA_*` abajo y
docs/Requerimientos_Mejoras_UrbanBike.md, punto 15.

No es una factura con validez tributaria real (sin autorización del SRI) --
se lo aclara explícitamente en el pie, mismo criterio ya usado en
_factura_pdf() ("Simulación académica — RUC no aplica").
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings
from app.reportes.comun import GRID, MUTED
from app.reportes.pdf import _registrar_fuentes

# ── Paleta real de marca (logo, confirmada por Washington) ───────────────────
AZUL_PIZARRA = "3E5C74"  # bicicleta del logo + color principal (encabezado, líneas)
NAVY_TEXTO   = "2A3143"  # "Urban" del wordmark
CIAN_ACENTO  = "0B9FC3"  # "Bike" del wordmark + acento de totales/destacados
ALT_FACTURA  = "EAF0F4"  # tinte muy claro de AZUL_PIZARRA, para el rayado de filas

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "img" / "logo-urbanbike.png"

# ── Datos fiscales de la empresa (ficticios pero definitivos del proyecto,
#    ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 15: RUC calculado
#    con el algoritmo módulo 11 real de Ecuador, provincia 12 = Los Ríos) ──
EMPRESA_RAZON_SOCIAL = "UrbanBike S.A."
EMPRESA_DIRECCION = "Av. Walter Andrade y Séptima Etapa, Quevedo, Los Ríos, Ecuador"
EMPRESA_RUC = "1293456786001"
EMPRESA_TELEFONO = "05 275 0000"


@dataclass
class LineaFactura:
    descripcion: str
    cantidad: float
    precio_unitario: float
    importe: float


@dataclass
class DatosFactura:
    numero: str
    fecha_emision: str          # ya formateada, texto listo para mostrar
    fecha_vencimiento: str
    numero_pedido: str
    cliente_nombre: str
    cliente_cedula: str
    cliente_extra: str          # "Estación de retiro / devolución" (viaje) o período (membresía)
    metodo_pago: str
    lineas: list[LineaFactura] = field(default_factory=list)
    subtotal: float = 0.0
    iva: float = 0.0
    descuento: float = 0.0
    total: float = 0.0
    nota: str = ""              # ej. "MODO DEMOSTRACIÓN — pago simulado"


def _fmt_moneda(valor: float) -> str:
    """$-0.50 (el signo pegado al numero, no al simbolo) se ve como un error
    de imprenta -- el signo va siempre antes del simbolo: -$0.50."""
    return f"-${abs(valor):,.2f}" if valor < 0 else f"${valor:,.2f}"


def generar_factura_pdf(datos: DatosFactura, nombre_archivo: str) -> StreamingResponse:
    _registrar_fuentes()
    azul = colors.HexColor(f"#{AZUL_PIZARRA}")
    cian = colors.HexColor(f"#{CIAN_ACENTO}")
    alt = colors.HexColor(f"#{ALT_FACTURA}")
    muted = colors.HexColor(f"#{MUTED}")
    grid = colors.HexColor(f"#{GRID}")

    margen = 18 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=16 * mm, bottomMargin=16 * mm, leftMargin=margen, rightMargin=margen,
        title=f"Factura {datos.numero}",
    )
    ancho_disponible = A4[0] - 2 * margen

    estilo_empresa_nombre = ParagraphStyle(
        "empresa_nombre", fontName="Sora-Bold", fontSize=12, textColor=colors.HexColor("#0F172A"), leading=15,
    )
    estilo_empresa_dato = ParagraphStyle(
        "empresa_dato", fontName="IBMPlexSans", fontSize=8.5, textColor=muted, leading=12,
    )
    estilo_logo_nombre = ParagraphStyle(
        "logo_nombre", fontName="Sora-Bold", fontSize=15, leading=18, alignment=TA_RIGHT,
    )

    # ── Encabezado: datos de la empresa a la izquierda, logo a la derecha
    #    (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 11) ──────────
    bloque_empresa = [
        Paragraph(EMPRESA_RAZON_SOCIAL, estilo_empresa_nombre),
        Paragraph(EMPRESA_DIRECCION, estilo_empresa_dato),
        Paragraph(f"RUC: {EMPRESA_RUC} · Tel: {EMPRESA_TELEFONO}", estilo_empresa_dato),
    ]
    logo_alto = 26
    logo_ancho = logo_alto * (440 / 327)  # proporción real del PNG (440x327)
    bloque_logo = Table(
        [[
            Image(str(LOGO_PATH), width=logo_ancho, height=logo_alto),
            Paragraph(f'<font color="#{NAVY_TEXTO}">Urban</font><font color="#{CIAN_ACENTO}">Bike</font>', estilo_logo_nombre),
        ]],
        colWidths=[logo_ancho + 4, None],
    )
    bloque_logo.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    encabezado = Table(
        [[bloque_empresa, bloque_logo]],
        colWidths=[ancho_disponible * 0.6, ancho_disponible * 0.4],
    )
    encabezado.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -1), 1.6, azul),
    ]))

    elementos = [encabezado, Spacer(1, 14)]

    # ── Bloque de identificación (N° factura, fechas, N° pedido), alineado
    #    a la derecha -- ver punto 11, "como en el ejemplo 1" ─────────────
    estilo_id_etq = ParagraphStyle("id_etq", fontName="IBMPlexSans", fontSize=8.5, textColor=muted, alignment=TA_RIGHT)
    estilo_id_val = ParagraphStyle("id_val", fontName="IBMPlexSans-Bold", fontSize=9.5, textColor=colors.HexColor("#0F172A"), alignment=TA_RIGHT)
    filas_id = [
        ("Factura N°", datos.numero),
        ("Fecha de emisión", datos.fecha_emision),
        ("N° de pedido / viaje", datos.numero_pedido),
        ("Fecha de vencimiento", datos.fecha_vencimiento),
    ]
    tabla_id = Table(
        [[Paragraph(etq, estilo_id_etq), Paragraph(str(val), estilo_id_val)] for etq, val in filas_id],
        colWidths=[ancho_disponible * 0.35, ancho_disponible * 0.35],
        hAlign="RIGHT",
    )
    tabla_id.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elementos += [tabla_id, Spacer(1, 16)]

    # ── "Facturar a" ───────────────────────────────────────────────────────
    estilo_cliente_etq = ParagraphStyle("cliente_etq", fontName="IBMPlexSans-Bold", fontSize=9, textColor=azul, spaceAfter=3)
    estilo_cliente_val = ParagraphStyle("cliente_val", fontName="IBMPlexSans", fontSize=9.5, textColor=colors.HexColor("#0F172A"), leading=14)
    elementos += [
        Paragraph("Facturar a", estilo_cliente_etq),
        Paragraph(datos.cliente_nombre, estilo_cliente_val),
        Paragraph(f"Cédula/RUC: {datos.cliente_cedula or '—'}", estilo_cliente_val),
    ]
    if datos.cliente_extra:
        elementos.append(Paragraph(datos.cliente_extra, estilo_cliente_val))
    elementos.append(Spacer(1, 16))

    # ── Tabla de detalle: Cant. — Descripción — Precio unitario — Importe ──
    encabezados = ["Cant.", "Descripción", "Precio unitario", "Importe"]
    filas_detalle = [
        [f"{l.cantidad:g}", l.descripcion, _fmt_moneda(l.precio_unitario), _fmt_moneda(l.importe)]
        for l in datos.lineas
    ]
    tabla_detalle = Table(
        [encabezados] + filas_detalle,
        colWidths=[ancho_disponible * 0.1, ancho_disponible * 0.5, ancho_disponible * 0.2, ancho_disponible * 0.2],
        repeatRows=1,
    )
    estilo_detalle = [
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "IBMPlexSans-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "IBMPlexSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, grid),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (3, -1), "RIGHT"),
    ]
    for ri in range(1, len(filas_detalle) + 1):
        if ri % 2 == 0:
            estilo_detalle.append(("BACKGROUND", (0, ri), (-1, ri), alt))
    tabla_detalle.setStyle(TableStyle(estilo_detalle))
    elementos += [tabla_detalle, Spacer(1, 14)]

    # ── Totales: Subtotal, IVA, Descuento aplicado, TOTAL destacado ────────
    estilo_tot_etq = ParagraphStyle("tot_etq", fontName="IBMPlexSans", fontSize=9.5, textColor=muted, alignment=TA_RIGHT)
    estilo_tot_val = ParagraphStyle("tot_val", fontName="IBMPlexSans", fontSize=9.5, textColor=colors.HexColor("#0F172A"), alignment=TA_RIGHT)
    estilo_total_etq = ParagraphStyle("total_etq", fontName="Sora-Bold", fontSize=12, textColor=colors.HexColor("#0F172A"), alignment=TA_RIGHT)
    estilo_total_val = ParagraphStyle("total_val", fontName="Sora-Bold", fontSize=14, textColor=cian, alignment=TA_RIGHT)

    filas_totales = [[Paragraph("Subtotal", estilo_tot_etq), Paragraph(_fmt_moneda(datos.subtotal), estilo_tot_val)]]
    filas_totales.append([Paragraph("IVA (15%)", estilo_tot_etq), Paragraph(_fmt_moneda(datos.iva), estilo_tot_val)])
    if datos.descuento > 0:
        filas_totales.append([Paragraph("Descuento aplicado", estilo_tot_etq), Paragraph(_fmt_moneda(-datos.descuento), estilo_tot_val)])
    filas_totales.append([Paragraph("TOTAL", estilo_total_etq), Paragraph(_fmt_moneda(datos.total), estilo_total_val)])

    tabla_totales = Table(filas_totales, colWidths=[ancho_disponible * 0.75, ancho_disponible * 0.25], hAlign="RIGHT")
    estilo_totales = [
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, -1), (-1, -1), 1, cian),
        ("TOPPADDING", (0, -1), (-1, -1), 8),
    ]
    tabla_totales.setStyle(TableStyle(estilo_totales))
    elementos += [tabla_totales, Spacer(1, 24)]

    # ── Pie: condiciones de pago + contacto/soporte ────────────────────────
    estilo_pie = ParagraphStyle("pie", fontName="IBMPlexSans", fontSize=8, textColor=muted, leading=12)
    elementos.append(Paragraph(f"Condición de pago: {datos.metodo_pago}", estilo_pie))
    if datos.nota:
        elementos.append(Paragraph(datos.nota, estilo_pie))
    elementos.append(Spacer(1, 4))
    elementos.append(Paragraph(
        f"Soporte y contacto: {settings.support_email} — "
        "Documento generado electrónicamente con fines académicos, sin validez tributaria (sin autorización del SRI).",
        estilo_pie,
    ))

    doc.build(elementos)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
