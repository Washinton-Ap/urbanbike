"""Chat interno de soporte (ver docs/Requerimientos_Mejoras_UrbanBike.md,
punto 12, Opción B; expandido para el punto 2.4 de
docs/Plan_Mejoras_UrbanBike_V2.md -- ver docs/HOJA_DE_RUTA.md secciones
68 y 85). Un ciclista puede tener varias conversaciones reales, cada una
identificada por `conversacion_id` (no por `ciclista_id`, que ahora solo
queda denormalizado): una por cada vez que elige un agente de Vigilancia
y un motivo distintos al iniciar un chat nuevo.

Colección PocketBase `mensajes_soporte` (creada por
etl/13_crear_coleccion_soporte.py, ampliada por
etl/21_agregar_adjunto_soporte.py). Sin infraestructura de tiempo real
nueva: los mensajes nuevos avisan por la campana de notificaciones real
ya existente, y la conversación abierta se refresca con el mismo sondeo
de 4s de siempre (app/static/js/chat-soporte.js).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.db import notificaciones_repo
from app.db.pocketbase import filter_literal, get_admin_client

MOTIVOS_VALIDOS = ("infraccion", "consulta_general", "otro")
MOTIVO_LABEL = {"infraccion": "Infracción", "consulta_general": "Consulta general", "otro": "Otro"}

# Tipo MIME real -> limite de tamano real en bytes. Imagen/PDF comparten
# el mismo limite que ya usa comprobante_imagen (empleado.py); video no
# tiene precedente en el proyecto, limite propuesto y confirmado con
# Washington (punto 2.4).
MIME_ADJUNTOS_PERMITIDOS: dict[str, int] = {
    "image/jpeg": 5 * 1024 * 1024, "image/png": 5 * 1024 * 1024, "image/gif": 5 * 1024 * 1024,
    "application/pdf": 5 * 1024 * 1024,
    "video/mp4": 20 * 1024 * 1024, "video/quicktime": 20 * 1024 * 1024, "video/webm": 20 * 1024 * 1024,
}


def _pb():
    return get_admin_client()


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nuevo_conversacion_id() -> str:
    return str(uuid.uuid4())


def validar_adjunto(content_type: str | None, size: int | None) -> None:
    """Lanza ValueError con un mensaje real si el tipo/tamaño no es
    válido. `content_type`/`size` vienen de un UploadFile ya leído por el
    router -- este módulo no depende de FastAPI."""
    limite = MIME_ADJUNTOS_PERMITIDOS.get(content_type or "")
    if limite is None:
        raise ValueError(
            "Tipo de archivo no permitido. Se aceptan imágenes (JPG/PNG/GIF), "
            "PDF o video (MP4/MOV/WEBM)."
        )
    if size and size > limite:
        raise ValueError(f"El archivo supera el límite de {limite // (1024 * 1024)} MB para este tipo.")


def listar_agentes_vigilancia_activos() -> list[dict]:
    """[{id, nombre}] de empleados de Vigilancia activos -- fuente real
    para el selector de "Iniciar chat" del ciclista. Nunca incluye Admin
    ni otros roles (ver auditoría del punto 2.4)."""
    try:
        items = _pb().list_records(
            "users", expand="rol", filter="activo = true", per_page=200,
        ).get("items", [])
    except Exception:
        return []
    agentes = []
    for u in items:
        slug = (u.get("expand") or {}).get("rol", {}).get("slug", "")
        if slug == "empleado-vigilancia":
            agentes.append({"id": u["id"], "nombre": u.get("name") or u.get("email", "")})
    agentes.sort(key=lambda a: a["nombre"])
    return agentes


def obtener_conversacion(conversacion_id: str) -> dict:
    """agente_id/agente_nombre/motivo/ciclista_id reales de una
    conversación ya iniciada -- se leen del primer mensaje real (todos
    los mensajes de un mismo hilo los llevan denormalizados igual, pero
    el primero es el que los originó)."""
    if not conversacion_id:
        return {}
    primero = _pb().list_records(
        "mensajes_soporte", filter=f'conversacion_id = {filter_literal(conversacion_id)}',
        sort="fecha", per_page=1,
    ).get("items", [])
    return primero[0] if primero else {}


def listar_hilo(conversacion_id: str, *, incluir_eliminados: bool = False) -> list[dict]:
    """Mensajes de UNA conversación, en orden cronológico. Por defecto
    oculta los marcados `eliminado` (vista normal de ciclista/Vigilancia)
    -- `incluir_eliminados=True` es solo para la vista de supervisión de
    Admin, que ve todo aunque Vigilancia haya borrado la conversación."""
    if not conversacion_id:
        return []
    res = _pb().list_records(
        "mensajes_soporte",
        filter=f'conversacion_id = {filter_literal(conversacion_id)}',
        sort="fecha", per_page=500,
    )
    items = res.get("items", [])
    if not incluir_eliminados:
        items = [m for m in items if not m.get("eliminado")]
    return items


def _crear_mensaje(*, conversacion_id: str, ciclista_id: str, autor_id: str, autor_rol: str,
                    autor_nombre: str, agente_id: str, agente_nombre: str, motivo: str,
                    texto: str, archivo: tuple[str, bytes, str] | None) -> dict:
    pb = _pb()
    registro = pb.create_record("mensajes_soporte", {
        "conversacion_id": conversacion_id,
        "ciclista_id":  ciclista_id,
        "autor_id":     autor_id,
        "autor_rol":    autor_rol,
        "autor_nombre": autor_nombre,
        "agente_id":    agente_id,
        "agente_nombre": agente_nombre,
        "motivo":       motivo,
        "texto":        texto,
        "leido":        False,
        "eliminado":    False,
        "fecha":        _ahora(),
    })
    if archivo:
        nombre, contenido, content_type = archivo
        registro = pb.update_record_with_file(
            "mensajes_soporte", registro["id"], {}, {"adjunto": (nombre, contenido, content_type)},
        )
    return registro


def iniciar_conversacion(*, ciclista_id: str, ciclista_nombre: str, agente_id: str,
                          agente_nombre: str, motivo: str, texto: str = "",
                          archivo: tuple[str, bytes, str] | None = None) -> dict:
    """Crea una conversación real nueva (conversacion_id nuevo) con su
    primer mensaje. Notifica al agente elegido puntualmente -- nunca una
    difusión a todo el rol, esa era la razón de ser del punto 2.4."""
    if motivo not in MOTIVOS_VALIDOS:
        raise ValueError("Elige un motivo válido para iniciar el chat.")
    if not agente_id:
        raise ValueError("Elige un agente de Vigilancia para iniciar el chat.")
    texto = (texto or "").strip()
    if len(texto) > 2000:
        raise ValueError("El mensaje es demasiado largo (máximo 2000 caracteres).")
    if not texto and not archivo:
        raise ValueError("Escribe un mensaje o adjunta un archivo.")

    conversacion_id = nuevo_conversacion_id()
    registro = _crear_mensaje(
        conversacion_id=conversacion_id, ciclista_id=ciclista_id,
        autor_id=ciclista_id, autor_rol="ciclista", autor_nombre=ciclista_nombre,
        agente_id=agente_id, agente_nombre=agente_nombre, motivo=motivo,
        texto=texto, archivo=archivo,
    )

    resumen = texto if texto else "(envió un archivo adjunto)"
    resumen = resumen if len(resumen) <= 120 else resumen[:117] + "..."
    notificaciones_repo.notificar_usuario(
        _pb(), agente_id, tipo="mensaje_soporte",
        titulo=f"Nuevo chat de soporte — {MOTIVO_LABEL.get(motivo, motivo)}",
        mensaje=f"{ciclista_nombre}: {resumen}",
        enlace=f"/empleado/vigilancia/soporte/{conversacion_id}",
    )
    return registro


def enviar(*, conversacion_id: str, autor_id: str, autor_rol: str, autor_nombre: str,
           texto: str = "", archivo: tuple[str, bytes, str] | None = None) -> dict:
    """Responde en una conversación ya iniciada. Reutiliza el
    agente_id/motivo/ciclista_id reales de esa conversación (leídos de su
    primer mensaje) -- quien llama nunca los vuelve a pasar, así no
    pueden desalinearse entre mensajes del mismo hilo."""
    meta = obtener_conversacion(conversacion_id)
    if not meta:
        raise ValueError("Esa conversación no existe.")

    texto = (texto or "").strip()
    if len(texto) > 2000:
        raise ValueError("El mensaje es demasiado largo (máximo 2000 caracteres).")
    if not texto and not archivo:
        raise ValueError("Escribe un mensaje o adjunta un archivo.")

    registro = _crear_mensaje(
        conversacion_id=conversacion_id, ciclista_id=meta.get("ciclista_id", ""),
        autor_id=autor_id, autor_rol=autor_rol, autor_nombre=autor_nombre,
        agente_id=meta.get("agente_id", ""), agente_nombre=meta.get("agente_nombre", ""),
        motivo=meta.get("motivo", "otro"), texto=texto, archivo=archivo,
    )

    resumen = texto if texto else "(envió un archivo adjunto)"
    resumen = resumen if len(resumen) <= 120 else resumen[:117] + "..."
    pb = _pb()
    if autor_rol == "ciclista":
        # Notifica al agente puntual de ESTA conversacion -- nunca una
        # difusion de rol, ver auditoria del punto 2.4. Si la
        # conversacion es una de las 13 migradas del modelo viejo
        # (sin agente_id real, ver etl/21), esto no notifica a nadie
        # puntual -- notificar_usuario("") ya es un no-op seguro.
        notificaciones_repo.notificar_usuario(
            pb, meta.get("agente_id", ""), tipo="mensaje_soporte",
            titulo="Nuevo mensaje de soporte",
            mensaje=f"{autor_nombre}: {resumen}",
            enlace=f"/empleado/vigilancia/soporte/{conversacion_id}",
        )
    else:
        notificaciones_repo.notificar_usuario(
            pb, meta.get("ciclista_id", ""), tipo="mensaje_soporte",
            titulo="Respuesta de soporte",
            mensaje=f"{autor_nombre}: {resumen}",
            enlace=f"/ciclista/soporte/{conversacion_id}",
        )
    return registro


def marcar_leidos(conversacion_id: str, *, para_rol: str) -> int:
    """Marca leido=True los mensajes que le tocaba leer a `para_rol`:
    'ciclista' marca lo que mandó el staff; cualquier otro rol marca lo
    que mandó el ciclista. Sin update masivo real en PocketBase -- mismo
    criterio uno-a-uno que notificaciones_repo.marcar_todas_leidas()."""
    hilo = listar_hilo(conversacion_id)
    if para_rol == "ciclista":
        pendientes = [m for m in hilo if m.get("autor_rol") != "ciclista" and not m.get("leido")]
    else:
        pendientes = [m for m in hilo if m.get("autor_rol") == "ciclista" and not m.get("leido")]
    pb = _pb()
    for m in pendientes:
        pb.update_record("mensajes_soporte", m["id"], {"leido": True})
    return len(pendientes)


def eliminar_mensaje(mensaje_id: str, *, actor_id: str, puede_moderar: bool = False) -> tuple[bool, str]:
    """Soft-delete de UN mensaje: nunca DELETE real (puede ser evidencia de
    un reclamo o de una promesa hecha por el staff, mismo criterio que la
    bitácora/ordenes_repo.eliminar()).

    Por defecto (`puede_moderar=False`) solo el autor real de ese mensaje
    puede borrarlo -- ni el ciclista puede borrar lo que mandó el staff, ni
    al revés. `puede_moderar=True` (Vigilancia/Admin, ver punto 32 del Plan
    V3 -- moderación real de mensajes ajenos inapropiados, antes solo
    existía el borrado de la conversación completa) permite ocultar
    CUALQUIER mensaje de la conversación, no solo los propios -- mismo
    mecanismo de soft-delete, sin distinción en el dato guardado más allá
    de `eliminado_por` (que ya deja constancia real de quién lo hizo)."""
    try:
        m = _pb().get_record("mensajes_soporte", mensaje_id)
    except Exception:
        return False, "Mensaje no encontrado."
    if not puede_moderar and m.get("autor_id") != actor_id:
        return False, "Solo puedes borrar tus propios mensajes."
    if m.get("eliminado"):
        return True, ""
    _pb().update_record("mensajes_soporte", mensaje_id, {
        "eliminado": True, "eliminado_por": actor_id, "eliminado_en": _ahora(),
    })
    return True, ""


def eliminar_conversacion(conversacion_id: str, *, actor_id: str) -> int:
    """Soft-delete de TODA una conversación -- reservado a Vigilancia/
    Admin por la propia restricción de rutas (/empleado/vigilancia/*,
    /admin/*), nunca expuesto bajo /ciclista/. Devuelve cuántos mensajes
    reales se marcaron (idempotente: los ya borrados no se tocan)."""
    mensajes = listar_hilo(conversacion_id, incluir_eliminados=True)
    pb = _pb()
    tocados = 0
    for m in mensajes:
        if m.get("eliminado"):
            continue
        pb.update_record("mensajes_soporte", m["id"], {
            "eliminado": True, "eliminado_por": actor_id, "eliminado_en": _ahora(),
        })
        tocados += 1
    return tocados


def _agrupar_por_conversacion(items: list[dict], *, incluir_eliminadas: bool,
                               no_leidos_para: str = "staff") -> list[dict]:
    """Agrupa mensajes ya traídos (orden -fecha) en filas de conversación
    -- mismo criterio de agregación en Python que ya usaba
    listar_conversaciones() antes de esta ampliación, ahora por
    conversacion_id en vez de ciclista_id. `no_leidos_para` decide de
    quién es el punto de vista del contador: "staff" cuenta lo que el
    ciclista mandó y el staff no vio (lista de Vigilancia/Admin);
    "ciclista" cuenta lo que el staff respondió y el ciclista no vio
    (lista propia del ciclista) -- mismo criterio que marcar_leidos()."""
    por_conv: dict[str, dict] = {}
    for m in items:
        cid = m.get("conversacion_id", "")
        if not cid:
            continue
        conv = por_conv.setdefault(cid, {
            "conversacion_id": cid, "ciclista_id": m.get("ciclista_id", ""),
            "ciclista_nombre": "", "agente_id": m.get("agente_id", ""),
            "agente_nombre": m.get("agente_nombre", ""), "motivo": m.get("motivo", "otro"),
            "ultimo_texto": "", "ultima_fecha": "", "no_leidos": 0,
            "eliminada": True,
        })
        if not m.get("eliminado"):
            conv["eliminada"] = False
        if not conv["ultima_fecha"] and (incluir_eliminadas or not m.get("eliminado")):
            conv["ultimo_texto"] = m.get("texto") or ("(archivo adjunto)" if m.get("adjunto") else "")
            conv["ultima_fecha"] = m.get("fecha", "")
        if m.get("autor_rol") == "ciclista" and not conv["ciclista_nombre"]:
            conv["ciclista_nombre"] = m.get("autor_nombre", "")
        es_del_ciclista = m.get("autor_rol") == "ciclista"
        cuenta = es_del_ciclista if no_leidos_para == "staff" else not es_del_ciclista
        if cuenta and not m.get("leido") and not m.get("eliminado"):
            conv["no_leidos"] += 1
    conversaciones = [c for c in por_conv.values() if incluir_eliminadas or not c["eliminada"]]
    conversaciones.sort(key=lambda c: c["ultima_fecha"], reverse=True)
    return conversaciones


def listar_conversaciones(*, incluir_eliminadas: bool = False) -> list[dict]:
    """Una fila por conversación real, para el WorkPanel de Vigilancia
    (activas únicamente) o de Admin (`incluir_eliminadas=True`: ve
    también las que Vigilancia borró completas, ver punto 2.4)."""
    items = _pb().list_records("mensajes_soporte", sort="-fecha", per_page=500).get("items", [])
    return _agrupar_por_conversacion(items, incluir_eliminadas=incluir_eliminadas)


def listar_conversaciones_de_ciclista(ciclista_id: str) -> list[dict]:
    """Las conversaciones reales de UN ciclista (para su propia lista de
    "Soporte" -- puede tener varias, una por agente/motivo elegido)."""
    if not ciclista_id:
        return []
    items = _pb().list_records(
        "mensajes_soporte", filter=f'ciclista_id = {filter_literal(ciclista_id)}',
        sort="-fecha", per_page=500,
    ).get("items", [])
    return _agrupar_por_conversacion(items, incluir_eliminadas=False, no_leidos_para="ciclista")


def contar_no_leidos_ciclista(ciclista_id: str) -> int:
    """Mensajes del staff que este ciclista todavía no vio, sumados
    entre TODAS sus conversaciones activas -- usado por su propia vista
    para saber si hay respuesta nueva."""
    return sum(c["no_leidos"] for c in listar_conversaciones_de_ciclista(ciclista_id))
