"""Definiciones compartidas entre exportación a Excel (openpyxl) y PDF
(reportlab): colores institucionales, especificación de columnas y
formato de valores. Ver excel.py y pdf.py.
"""

from dataclasses import dataclass


class ReporteVacioError(Exception):
    """Se lanza cuando no hay filas que exportar -- ver
    generar_excel_reporte()/generar_pdf_reporte(). Capturada centralmente
    en app/main.py para redirigir con un flash en vez de generar un
    archivo en blanco (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 5)."""


BLUE = "1E86BD"
WHITE = "FFFFFF"
ALT = "D6EDF8"
MUTED = "64748B"
GRID = "E2E8F0"

ALINEACION_POR_DEFECTO = {
    "texto": "left",
    "entero": "right",
    "decimal1": "right",
    "decimal2": "right",
    "moneda": "right",
}


@dataclass
class ColumnaReporte:
    titulo: str
    ancho: int = 18
    formato: str = "texto"        # texto | entero | decimal1 | decimal2 | moneda
    alineacion: str | None = None  # left | right | center — None usa el default de `formato`

    def alineacion_efectiva(self) -> str:
        return self.alineacion or ALINEACION_POR_DEFECTO.get(self.formato, "left")


def formatear_valor(valor, formato: str) -> str:
    """Convierte un valor crudo a texto legible según el formato de columna.

    Usado por el PDF (las celdas de una tabla reportlab son texto plano).
    El Excel no lo necesita: guarda el número real y aplica number_format.
    """
    if valor is None or valor == "":
        return "" if valor is None else str(valor)
    if formato == "entero":
        return f"{int(valor):,}"
    if formato == "decimal1":
        return f"{float(valor):.1f}"
    if formato == "decimal2":
        return f"{float(valor):.2f}"
    if formato == "moneda":
        return f"${float(valor):,.2f}"
    return str(valor)
