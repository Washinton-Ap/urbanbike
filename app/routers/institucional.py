"""Apartado institucional (Misión/Visión), ver
docs/Requerimientos_Mejoras_UrbanBike.md, punto 8: visible para Gerente y
para los 3 roles de Empleado -- ninguno de esos 4 roles comparte un mismo
prefijo de URL en app/middleware/auth.py (ROLE_RULES), así que esta ruta
vive bajo su propio prefijo "/institucional" con una entrada dedicada en
ROLE_RULES, en vez de duplicarse dentro de gerente.py y empleado.py."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

router = APIRouter(prefix="/institucional", tags=["institucional"])

# Texto PLACEHOLDER a propósito (ver docs/Requerimientos_Mejoras_UrbanBike.md,
# punto 8 -- el documento no trae la redacción oficial, mismo criterio que
# los datos fiscales del punto 15: dejar un texto definitivo del proyecto,
# fácil de reemplazar el día que Washington tenga la redacción real).
MISION = (
    "Facilitar la movilidad urbana sostenible ofreciendo un sistema de "
    "alquiler de bicicletas accesible, confiable y tecnológicamente moderno, "
    "que reduzca la dependencia del transporte motorizado y mejore la "
    "calidad de vida en las ciudades donde operamos."
)
VISION = (
    "Ser la red de bicicletas compartidas de referencia en Ecuador, "
    "reconocida por la calidad de su flota, la solidez de su operación y su "
    "aporte real a ciudades más limpias, saludables y conectadas."
)
VALORES = [
    ("Sostenibilidad", "Cada viaje en bicicleta es un viaje menos en vehículo motorizado."),
    ("Confiabilidad", "Bicicletas en buen estado y un servicio que responde cuando algo falla."),
    ("Accesibilidad", "Tarifas claras y un sistema simple de usar, para cualquier ciclista."),
    ("Mejora continua", "Datos reales de uso para decidir dónde y cómo crecer."),
]


@router.get("/mision-vision", response_class=HTMLResponse)
async def mision_vision(request: Request):
    user = getattr(request.state, "user", None)
    return templates.TemplateResponse(request, "institucional/mision_vision.html", {
        "user": user, "title": "Misión y Visión",
        "mision": MISION, "vision": VISION, "valores": VALORES,
    })
