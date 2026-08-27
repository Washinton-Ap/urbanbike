"""Envío de correo transaccional real vía SMTP (genérico -- funciona con
Gmail o Brevo, según lo que haya en .env). Best-effort: nunca lanza -- si
faltan credenciales o el servidor rechaza el envío, devuelve False y
quien llama decide qué hacer (ver app/routers/auth.py:registro_post /
solicitar_reset_post).

Dos correos automáticos reales: verificación de cuenta (registro) y
código de restablecimiento de contraseña -- comparten el mismo layout
visual (logo, header, pie) vía _layout_correo() y el mismo envío MIME
vía _enviar_correo(), solo cambia el contenido central y el asunto."""

from __future__ import annotations

import html
import logging
import smtplib
from datetime import date
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.config import settings

logger = logging.getLogger("urbanbike.email_client")

# Isotipo real (bicicletas formando una "U", sin texto) recortado del
# lockup real -- ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 16:
# "logo completo con texto" en correo = este isotipo + el wordmark
# "UrbanBike" armado con <span> de color (mismo patrón que
# componentes/factura.html y el sidebar de base.html), no un logo completo
# ya rasterizado -- así el texto queda nítido a cualquier tamaño y no hace
# falta mantener un segundo PNG solo para el correo. Un SVG inline no es
# confiable en correo (Gmail en Android y varios clientes más no lo
# renderizan dentro de HTML), así que el isotipo se manda como PNG
# incrustado como adjunto con Content-ID -- no como imagen externa por URL,
# que quedaría bloqueada por defecto en la mayoría de clientes.
_LOGO_PATH = Path(__file__).resolve().parent / "static" / "img" / "logo-urbanbike.png"
_LOGO_CID = "logo-urbanbike"


def _layout_correo(titulo: str, cuerpo_html: str) -> str:
    """Envoltorio HTML compartido por todos los correos reales del sistema:
    header con el logo incrustado (cid:) y borde azul, y pie con nombre del
    sistema/aviso de no-respuesta/derechos. `cuerpo_html` es el contenido
    específico de cada correo (saludo, código, avisos), ya con sus propios
    estilos inline -- misma paleta e identidad visual que main.css
    (--primary #1E86BD, --primary-light #D6EDF8, --text #0F172A,
    --text-muted #64748B) y misma tipografía que el resto del sistema
    (Sora / IBM Plex Sans, cargadas desde Google Fonts igual que en
    base.html). Todo con estilos inline y tabla como contenedor -- la
    mayoría de clientes de correo (Outlook incluido) ignora <style>
    externo y hojas de estilo con selectores, solo respetan `style=""`
    directo sobre cada elemento.

    `Content-Language` va tanto en el <meta> de acá como en la cabecera
    MIME real (ver _enviar_correo) porque Gmail sanea el HTML recibido y
    descarta el <html>/<head> originales antes de mostrarlo -- el
    <html lang="es"> de este documento nunca sobrevive a ese saneo, así
    que no alcanza por sí solo como señal de idioma para Gmail (sigue acá
    de todos modos: es gratis y sí lo respetan clientes que no reescriben
    el documento, como Outlook o Apple Mail)."""
    anio = date.today().year
    titulo_seguro = html.escape(titulo)
    return f"""\
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Language" content="es">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{titulo_seguro}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@700;800&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
</head>
<body style="margin:0;padding:0;background-color:#F8FAFC;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F8FAFC;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" style="width:480px;max-width:100%;background-color:#FFFFFF;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">

<tr><td style="padding:24px 32px;border-bottom:2px solid #1E86BD;">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:8px;"><img src="cid:{_LOGO_CID}" width="30" height="22" alt="" style="display:block;border:0;"></td>
<td style="font-family:'Sora',sans-serif;font-weight:800;font-size:20px;line-height:1;white-space:nowrap;">
<span style="color:#2A3143;">Urban</span><span style="color:#0B9FC3;">Bike</span>
</td>
</tr></table>
</td></tr>

<tr><td style="padding:32px;font-family:'IBM Plex Sans','Segoe UI',Arial,Helvetica,sans-serif;color:#0F172A;">
{cuerpo_html}
</td></tr>

<tr><td style="padding:20px 32px;background-color:#F8FAFC;border-top:1px solid #E2E8F0;font-family:'IBM Plex Sans','Segoe UI',Arial,Helvetica,sans-serif;">
<p style="margin:0 0 4px 0;font-size:12px;color:#64748B;">Sistema de Alquiler de Bicicletas UrbanBike</p>
<p style="margin:0 0 4px 0;font-size:12px;color:#64748B;">Este es un correo automático -- por favor no respondas a este mensaje.</p>
<p style="margin:0;font-size:12px;color:#94A3B8;">© {anio} UrbanBike. Todos los derechos reservados.</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>
"""


def _caja_codigo(codigo_seguro: str) -> str:
    """Caja destacada del código de 6 dígitos, compartida por verificación
    y restablecimiento -- mismo diseño (fondo --primary-light, borde
    --primary, letra grande espaciada) ya probado y confirmado en Gmail."""
    return f"""\
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="background-color:#D6EDF8;border:1px solid #1E86BD;border-radius:8px;padding:20px;">
<span style="font-family:'IBM Plex Sans','Segoe UI',Arial,Helvetica,sans-serif;font-size:32px;font-weight:600;letter-spacing:10px;color:#1670A0;">{codigo_seguro}</span>
</td></tr>
</table>"""


def _pie_texto_plano() -> str:
    anio = date.today().year
    return (
        "--\n"
        "Sistema de Alquiler de Bicicletas UrbanBike\n"
        "Este es un correo automático, por favor no respondas a este mensaje.\n"
        f"© {anio} UrbanBike. Todos los derechos reservados.\n"
    )


def _html_codigo_verificacion(nombre: str, codigo: str) -> str:
    nombre_seguro = html.escape(nombre or "")
    codigo_seguro = html.escape(codigo or "")
    cuerpo = f"""\
<p style="margin:0 0 16px 0;font-size:17px;font-weight:600;">¡Hola {nombre_seguro}!</p>
<p style="margin:0 0 20px 0;font-size:15px;line-height:1.6;">
  Gracias por registrarte en UrbanBike. Ya casi estás listo para moverte por
  la ciudad: en cuanto verifiques tu correo vas a poder reservar bicicletas
  disponibles en cualquier estación, hacer seguimiento de tus viajes y pagos
  desde tu perfil, y aprovechar las promociones activas para ciclistas.
</p>
<p style="margin:0 0 24px 0;font-size:15px;line-height:1.6;">
  Para activar tu cuenta, ingresa este código de verificación:
</p>

{_caja_codigo(codigo_seguro)}

<p style="margin:24px 0 0 0;font-size:14px;line-height:1.6;color:#64748B;">
  El código vence en 15 minutos. Si no lo usas a tiempo, puedes pedir uno
  nuevo desde la misma pantalla de verificación.
</p>
<p style="margin:16px 0 0 0;font-size:14px;line-height:1.6;color:#64748B;">
  Si no creaste esta cuenta, puedes ignorar este correo -- no se activará
  nada sin ese código.
</p>

<p style="margin:32px 0 0 0;font-size:14px;color:#0F172A;">— Equipo UrbanBike</p>"""
    return _layout_correo("Verifica tu correo — UrbanBike", cuerpo)


def _html_codigo_restablecimiento(nombre: str, codigo: str) -> str:
    nombre_seguro = html.escape(nombre or "")
    codigo_seguro = html.escape(codigo or "")
    cuerpo = f"""\
<p style="margin:0 0 16px 0;font-size:17px;font-weight:600;">¡Hola {nombre_seguro}!</p>
<p style="margin:0 0 24px 0;font-size:15px;line-height:1.6;">
  Recibimos una solicitud para restablecer la contraseña de tu cuenta en
  UrbanBike. Usa este código para crear una contraseña nueva:
</p>

{_caja_codigo(codigo_seguro)}

<p style="margin:24px 0 0 0;font-size:14px;line-height:1.6;color:#64748B;">
  El código vence en 15 minutos. Si no lo usas a tiempo, puedes pedir uno
  nuevo desde la misma pantalla de restablecimiento.
</p>
<p style="margin:16px 0 0 0;font-size:14px;line-height:1.6;color:#64748B;">
  Si no fuiste tú quien lo solicitó, puedes ignorar este correo -- tu
  contraseña actual sigue funcionando sin cambios.
</p>

<p style="margin:32px 0 0 0;font-size:14px;color:#0F172A;">— Equipo UrbanBike</p>"""
    return _layout_correo("Restablece tu contraseña — UrbanBike", cuerpo)


def _enviar_correo(destinatario: str, asunto: str, texto_plano: str, html_body: str) -> bool:
    """Construye el MIME (multipart/related: texto+html alternativos más el
    logo incrustado como adjunto inline -- RFC 2387, estructura estándar
    para HTML con imagen cid:) y lo manda por SMTP. Compartido por todos
    los correos reales del sistema."""
    if not settings.smtp_user or not settings.smtp_app_password or not settings.smtp_from_email:
        return False

    msg = MIMEMultipart("related")
    msg["Subject"] = asunto
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = destinatario
    # Cabecera MIME real (RFC 3282), no solo el <html lang="es"> del cuerpo
    # -- ver el docstring de _layout_correo sobre por qué hacía falta esta
    # señal aparte para que Gmail no ofreciera traducir el correo.
    msg["Content-Language"] = "es"

    alternativa = MIMEMultipart("alternative")
    alternativa.attach(MIMEText(texto_plano, "plain", "utf-8"))
    parte_html = MIMEText(html_body, "html", "utf-8")
    parte_html["Content-Language"] = "es"
    alternativa.attach(parte_html)
    msg.attach(alternativa)

    try:
        logo_bytes = _LOGO_PATH.read_bytes()
        logo = MIMEImage(logo_bytes, _subtype="png")
        logo.add_header("Content-ID", f"<{_LOGO_CID}>")
        logo.add_header("Content-Disposition", "inline", filename="logo-urbanbike.png")
        msg.attach(logo)
    except OSError as e:
        # Best-effort igual que el resto de la función: si el logo no está
        # disponible por algún motivo, se manda el correo sin imagen antes
        # que no mandarlo -- el código real sigue siendo lo único
        # indispensable acá.
        logger.error("No se pudo adjuntar el logo del correo (%s): %s", _LOGO_PATH, e)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_app_password)
            server.send_message(msg)
        # Log de exito real, no solo de fallo (ver docs/HOJA_DE_RUTA.md,
        # seccion 109): desde que enviar_notificacion() se dispara en un
        # hilo en segundo plano (notificaciones_repo.notificar_usuario), el
        # handler que la llamo ya termino y no puede saber si el correo de
        # verdad salio -- este log es la unica traza real que queda.
        logger.info("Correo enviado a %s: %s", destinatario, asunto)
        return True
    except Exception as e:
        # Un True acá solo significa que el relay ACEPTÓ el mensaje (250 OK),
        # no que lo haya entregado -- Brevo puede aceptar en el handshake SMTP
        # y rechazarlo después de forma asíncrona (ej. remitente no verificado),
        # visible solo en su panel (Transactional > Logs), nunca como excepción
        # acá (ver docs/HOJA_DE_RUTA.md). Esta excepción cubre el otro caso real
        # -- fallos que sí ocurren en el propio handshake SMTP (credenciales,
        # timeout, host caído) -- y antes se perdía en silencio sin dejar rastro.
        logger.error("Envio de correo a %s fallo: %s", destinatario, e)
        return False


def enviar_codigo_verificacion(destinatario: str, nombre: str, codigo: str) -> bool:
    texto_plano = (
        f"¡Hola {nombre}!\n\n"
        "Gracias por registrarte en UrbanBike. Ya casi estás listo para moverte "
        "por la ciudad: en cuanto verifiques tu correo vas a poder reservar "
        "bicicletas disponibles en cualquier estación, hacer seguimiento de tus "
        "viajes y pagos desde tu perfil, y aprovechar las promociones activas "
        "para ciclistas.\n\n"
        "Para activar tu cuenta, ingresa este código de verificación:\n\n"
        f"  {codigo}\n\n"
        "El código vence en 15 minutos. Si no lo usas a tiempo, puedes pedir "
        "uno nuevo desde la misma pantalla de verificación.\n\n"
        "Si no creaste esta cuenta, puedes ignorar este correo -- no se "
        "activará nada sin ese código.\n\n"
        "— Equipo UrbanBike\n\n"
        f"{_pie_texto_plano()}"
    )
    return _enviar_correo(
        destinatario, "Verifica tu correo — UrbanBike",
        texto_plano, _html_codigo_verificacion(nombre, codigo),
    )


def _html_notificacion(nombre: str, titulo: str, mensaje: str) -> str:
    nombre_seguro = html.escape(nombre or "")
    titulo_seguro = html.escape(titulo or "")
    mensaje_seguro = html.escape(mensaje or "")
    cuerpo = f"""\
<p style="margin:0 0 16px 0;font-size:17px;font-weight:600;">¡Hola {nombre_seguro}!</p>
<p style="margin:0 0 8px 0;font-size:16px;font-weight:600;color:#1670A0;">{titulo_seguro}</p>
<p style="margin:0 0 24px 0;font-size:15px;line-height:1.6;">{mensaje_seguro}</p>
<p style="margin:32px 0 0 0;font-size:14px;color:#0F172A;">— Equipo UrbanBike</p>"""
    return _layout_correo(f"{titulo} — UrbanBike", cuerpo)


def enviar_notificacion(destinatario: str, nombre: str, titulo: str, mensaje: str) -> bool:
    """Correo generico para los avisos reales del flujo de alquiler/devolucion
    (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 11.1: falla detectada,
    pago aprobado, penalizacion aplicada) -- mismo layout/envio que los 2
    correos de auth, solo cambia titulo/mensaje. Llamado siempre junto con
    notificaciones_repo.crear() (la campana), nunca solo -- ver
    app/routers/ciclista.py / app/routers/empleado.py."""
    texto_plano = (
        f"¡Hola {nombre}!\n\n"
        f"{titulo}\n\n"
        f"{mensaje}\n\n"
        "— Equipo UrbanBike\n\n"
        f"{_pie_texto_plano()}"
    )
    return _enviar_correo(
        destinatario, f"{titulo} — UrbanBike",
        texto_plano, _html_notificacion(nombre, titulo, mensaje),
    )


def enviar_codigo_restablecimiento(destinatario: str, nombre: str, codigo: str) -> bool:
    texto_plano = (
        f"¡Hola {nombre}!\n\n"
        "Recibimos una solicitud para restablecer la contraseña de tu cuenta "
        "en UrbanBike. Usa este código para crear una contraseña nueva:\n\n"
        f"  {codigo}\n\n"
        "El código vence en 15 minutos. Si no lo usas a tiempo, puedes pedir "
        "uno nuevo desde la misma pantalla de restablecimiento.\n\n"
        "Si no fuiste tú quien lo solicitó, puedes ignorar este correo -- tu "
        "contraseña actual sigue funcionando sin cambios.\n\n"
        "— Equipo UrbanBike\n\n"
        f"{_pie_texto_plano()}"
    )
    return _enviar_correo(
        destinatario, "Restablece tu contraseña — UrbanBike",
        texto_plano, _html_codigo_restablecimiento(nombre, codigo),
    )
