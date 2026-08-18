"""Chat interno de soporte (ver docs/Requerimientos_Mejoras_UrbanBike.md,
punto 12, Opción B -- ver docs/HOJA_DE_RUTA.md sección 68): un hilo por
ciclista, sin colección de "conversaciones" aparte -- el `ciclista_id` ya
identifica la conversación de punta a punta (todos los mensajes con ese
mismo `ciclista_id`, sin importar si los mandó el ciclista o el staff).

Colección PocketBase `mensajes_soporte` (creada por
etl/13_crear_coleccion_soporte.py). Sin infraestructura de tiempo real
nueva: los mensajes nuevos avisan por la campana de notificaciones real
ya existente (notificaciones_repo.notificar_usuario/notificar_rol, tipo
"mensaje_soporte"), y la conversación abierta se refresca con un sondeo
propio de 4s (mismo intervalo que ya usa sesion-tiempo-real.js).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db import notificaciones_repo
from app.db.pocketbase import filter_literal, get_admin_client

# El único rol de empleado que da soporte según el documento de
# requerimientos (punto 12: "El empleado de Vigilancia también brinda
# soporte a los ciclistas") -- Admin también puede responder (ve todo,
# mismo criterio que el resto del sistema), pero la difusión de rol es
# solo a Vigilancia, no a los 4 roles de empleado.
ROL_DESTINO_SOPORTE = "empleado-vigilancia"


def _pb():
    return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def listar_hilo(ciclista_id: str) -> list[dict]:
    """Todos los mensajes de una conversación, en orden cronológico
    (viejo -> nuevo, para pintar el hilo de arriba hacia abajo)."""
    if not ciclista_id:
        return []
    res = _pb().list_records(
        "mensajes_soporte",
        filter=f'ciclista_id = {filter_literal(ciclista_id)}',
        sort="fecha", per_page=200,
    )
    return res.get("items", [])


def enviar(*, ciclista_id: str, autor_id: str, autor_rol: str, autor_nombre: str, texto: str) -> dict:
    """Crea el mensaje y dispara la notificación real correspondiente:
    del ciclista hacia Vigilancia (difusión de rol, mismo patrón que
    'orden_asignada' en empleado.py), o de un miembro del staff hacia el
    ciclista puntual (aviso + correo, mismo patrón que el resto del
    sistema)."""
    texto = texto.strip()
    if not texto:
        raise ValueError("El mensaje no puede estar vacío.")
    if len(texto) > 2000:
        raise ValueError("El mensaje es demasiado largo (máximo 2000 caracteres).")

    pb = _pb()
    registro = pb.create_record("mensajes_soporte", {
        "ciclista_id":  ciclista_id,
        "autor_id":     autor_id,
        "autor_rol":    autor_rol,
        "autor_nombre": autor_nombre,
        "texto":        texto,
        "leido":        False,
        "fecha":        _ahora(),
    })

    resumen = texto if len(texto) <= 120 else texto[:117] + "..."
    if autor_rol == "ciclista":
        notificaciones_repo.notificar_rol(
            ROL_DESTINO_SOPORTE, tipo="mensaje_soporte",
            titulo="Nuevo mensaje de soporte",
            mensaje=f"{autor_nombre}: {resumen}",
            enlace=f"/empleado/vigilancia/soporte/{ciclista_id}",
        )
    else:
        notificaciones_repo.notificar_usuario(
            pb, ciclista_id, tipo="mensaje_soporte",
            titulo="Respuesta de soporte",
            mensaje=f"{autor_nombre}: {resumen}",
            enlace="/ciclista/soporte",
        )
    return registro


def marcar_leidos(ciclista_id: str, *, para_rol: str) -> int:
    """Marca leido=True los mensajes que le tocaba leer a `para_rol`:
    'ciclista' marca lo que mandó el staff; cualquier otro rol (llamado
    desde Vigilancia/Admin) marca lo que mandó el ciclista. Sin update
    masivo real en PocketBase -- mismo criterio uno-a-uno que
    notificaciones_repo.marcar_todas_leidas()."""
    hilo = listar_hilo(ciclista_id)
    if para_rol == "ciclista":
        pendientes = [m for m in hilo if m.get("autor_rol") != "ciclista" and not m.get("leido")]
    else:
        pendientes = [m for m in hilo if m.get("autor_rol") == "ciclista" and not m.get("leido")]
    pb = _pb()
    for m in pendientes:
        pb.update_record("mensajes_soporte", m["id"], {"leido": True})
    return len(pendientes)


def contar_no_leidos_ciclista(ciclista_id: str) -> int:
    """Mensajes del staff que este ciclista todavía no vio -- usado por
    su propia vista para saber si hay respuesta nueva."""
    if not ciclista_id:
        return 0
    hilo = listar_hilo(ciclista_id)
    return sum(1 for m in hilo if m.get("autor_rol") != "ciclista" and not m.get("leido"))


def listar_conversaciones() -> list[dict]:
    """Una fila por ciclista con conversación real, para el WorkPanel de
    Vigilancia/Admin: último mensaje + cuántos le faltan por leer al
    staff. Se trae todo el volumen real (bajo, mismo criterio que
    notificaciones_repo) y se agrupa en Python -- PocketBase no agrega
    del lado del servidor."""
    items = _pb().list_records("mensajes_soporte", sort="-fecha", per_page=500).get("items", [])
    por_ciclista: dict[str, dict] = {}
    for m in items:
        cid = m.get("ciclista_id", "")
        if not cid:
            continue
        conv = por_ciclista.setdefault(cid, {
            "ciclista_id": cid, "ciclista_nombre": "", "ultimo_texto": "",
            "ultima_fecha": "", "no_leidos": 0,
        })
        # `items` ya viene ordenado -fecha: el primer mensaje que se ve
        # por cada ciclista_id es el más reciente de esa conversación.
        if not conv["ultima_fecha"]:
            conv["ultimo_texto"] = m.get("texto", "")
            conv["ultima_fecha"] = m.get("fecha", "")
        if m.get("autor_rol") == "ciclista":
            if not conv["ciclista_nombre"]:
                conv["ciclista_nombre"] = m.get("autor_nombre", "")
            if not m.get("leido"):
                conv["no_leidos"] += 1
    conversaciones = list(por_ciclista.values())
    conversaciones.sort(key=lambda c: c["ultima_fecha"], reverse=True)
    return conversaciones
