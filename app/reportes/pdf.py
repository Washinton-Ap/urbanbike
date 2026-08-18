"""Generación de PDF real con reportlab: membrete UrbanBike (logo + nombre
en Sora Bold, mismo diseño que componentes/membrete.html) y tabla con
encabezado azul y filas alternadas (mismo esquema que el Excel, ver
comun.py). Las tipografías reales (Sora, IBM Plex Sans) se registran desde
app/static/fonts/ — reportlab no trae esas fuentes integradas.
"""

import io
from pathlib import Path

from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Circle, Drawing
from reportlab.graphics.shapes import Path as FormaPath

from app.reportes.comun import ALT, BLUE, GRID, MUTED, ColumnaReporte, ReporteVacioError, formatear_valor

_FUENTES_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
_fuentes_registradas = False


def _registrar_fuentes() -> None:
    """Registra Sora Bold e IBM Plex Sans (regular/bold) una sola vez por proceso."""
    global _fuentes_registradas
    if _fuentes_registradas:
        return
    pdfmetrics.registerFont(TTFont("Sora-Bold", str(_FUENTES_DIR / "Sora-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("IBMPlexSans", str(_FUENTES_DIR / "IBMPlexSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("IBMPlexSans-Bold", str(_FUENTES_DIR / "IBMPlexSans-Bold.ttf")))
    _fuentes_registradas = True


def _logo_bicicleta() -> Drawing:
    """Redibuja el logo de componentes/membrete.html con formas de reportlab
    (reportlab no puede incrustar el SVG/HTML directamente: mismo diseño
    visual, código distinto por herramienta)."""
    azul = colors.HexColor(f"#{BLUE}")
    escala = 34 / 28  # el SVG original usa un viewBox de 28x28

    def x(v: float) -> float:
        return v * escala

    def y(v: float) -> float:
        return 34 - v * escala  # el SVG crece hacia abajo; reportlab, hacia arriba

    d = Drawing(34, 34)
    d.add(Circle(x(7), y(20), 5 * escala, strokeColor=azul, strokeWidth=2.2, fillColor=None))
    d.add(Circle(x(21), y(20), 5 * escala, strokeColor=azul, strokeWidth=2.2, fillColor=None))

    marco = FormaPath(strokeColor=azul, strokeWidth=2.2, fillColor=None, strokeLineJoin=1, strokeLineCap=1)
    marco.moveTo(x(7), y(20))
    marco.lineTo(x(12), y(8))
    marco.lineTo(x(18), y(14))
    marco.lineTo(x(21), y(20))
    d.add(marco)

    d.add(Circle(x(14), y(6), 2 * escala, strokeColor=None, fillColor=azul))
    return d


def generar_pdf_reporte(
    *,
    titulo: str,
    subtitulo: str,
    columnas: list[ColumnaReporte],
    filas: list[list],
    nombre_archivo: str,
    fila_total: list | None = None,
    horizontal: bool = True,
) -> StreamingResponse:
    """Genera un .pdf con membrete UrbanBike + tabla, usando las mismas
    columnas/filas/fila_total que `generar_excel_reporte` (ver excel.py).
    Los valores se formatean a texto con `formatear_valor` según
    `columna.formato` (en el Excel el número real se guarda con
    number_format; el PDF solo puede mostrar texto).
    """
    if not filas:
        raise ReporteVacioError("No hay datos para exportar.")

    _registrar_fuentes()

    azul = colors.HexColor(f"#{BLUE}")
    alt = colors.HexColor(f"#{ALT}")
    muted = colors.HexColor(f"#{MUTED}")
    grid = colors.HexColor(f"#{GRID}")

    pagesize = landscape(A4) if horizontal else A4
    margen = 16 * mm
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=margen, rightMargin=margen,
        title=titulo,
    )

    nombre_style = ParagraphStyle("membrete_nombre", fontName="Sora-Bold", fontSize=16, textColor=azul, leading=20, alignment=TA_LEFT)
    sub_style = ParagraphStyle("membrete_sub", fontName="IBMPlexSans", fontSize=9, textColor=muted, leading=12, alignment=TA_LEFT)

    membrete = Table(
        [[_logo_bicicleta(), [Paragraph(f"UrbanBike — {titulo}", nombre_style), Paragraph(subtitulo, sub_style)]]],
        colWidths=[40, None],
    )
    membrete.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LINEBELOW", (0, 0), (-1, -1), 1.4, azul),
    ]))

    elementos = [membrete, Spacer(1, 14)]

    encabezados = [columna.titulo for columna in columnas]
    filas_texto = [
        [formatear_valor(valor, columna.formato) for columna, valor in zip(columnas, fila)]
        for fila in filas
    ]
    datos = [encabezados] + filas_texto
    if fila_total is not None:
        datos.append([
            formatear_valor(valor, columna.formato) if valor is not None else ""
            for columna, valor in zip(columnas, fila_total)
        ])

    ancho_disponible = pagesize[0] - 2 * margen
    pesos = [columna.ancho for columna in columnas]
    suma_pesos = sum(pesos) or 1
    anchos = [ancho_disponible * (peso / suma_pesos) for peso in pesos]

    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "IBMPlexSans-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "IBMPlexSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, grid),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    alineacion_pdf = {"left": "LEFT", "right": "RIGHT", "center": "CENTER"}
    for i, columna in enumerate(columnas):
        estilo.append(("ALIGN", (i, 0), (i, -1), alineacion_pdf[columna.alineacion_efectiva()]))
    for ri in range(1, len(filas) + 1):
        if ri % 2 == 0:
            estilo.append(("BACKGROUND", (0, ri), (-1, ri), alt))
    if fila_total is not None:
        ultima = len(datos) - 1
        estilo.append(("FONTNAME", (0, ultima), (-1, ultima), "IBMPlexSans-Bold"))
        estilo.append(("TEXTCOLOR", (0, ultima), (-1, ultima), azul))
        estilo.append(("LINEABOVE", (0, ultima), (-1, ultima), 0.8, azul))
    tabla.setStyle(TableStyle(estilo))

    elementos.append(tabla)
    doc.build(elementos)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
