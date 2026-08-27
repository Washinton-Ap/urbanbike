"""Templates Jinja2 compartido con filtros personalizados."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import jinja2
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.config import settings
from app.middleware.csrf import get_csrf_token

_BASE = Path(__file__).parent / "templates"


def pb_public_base(request=None) -> str:
    """Base URL de PocketBase tal como debe verla el navegador: usa el
    host por el que llegó la petición (Host header, vía request.url), no
    el host interno de PB_URL (127.0.0.1 en dev, o el nombre del
    contenedor Docker en compose) -- ese host solo tiene sentido para
    llamadas servidor-a-servidor (ver app/db/pocketbase.py), y rompe las
    imágenes/archivos cuando se accede desde fuera de la máquina (ej. vía
    túnel cloudflared), porque 127.0.0.1 en el navegador del visitante
    apunta a su propio equipo. Mantiene el puerto real de PocketBase
    (settings.pb_url).

    Si PB_PUBLIC_URL está definida (ver app/config.py), se usa tal cual y
    se ignora todo lo demás -- necesario cuando el túnel de pruebas solo
    expone el puerto de FastAPI y no el de PocketBase, caso en el que no
    existe ningún host derivable de la request que sirva."""
    if settings.pb_public_url:
        return settings.pb_public_url.rstrip("/")
    pb = urlsplit(settings.pb_url)
    if request is None:
        return f"{pb.scheme}://{pb.netloc}"
    host = request.url.hostname or pb.hostname
    netloc = f"{host}:{pb.port}" if pb.port else host
    return f"{request.url.scheme}://{netloc}"


def avatar_url(user, request=None) -> str:
    """URL del archivo de avatar del usuario en PocketBase, o cadena vacía si no tiene.
    `request` es opcional a propósito: además de llamarse desde las plantillas
    (donde `_avatar_url_jinja` lo inyecta solo desde el contexto de render),
    se llama directo desde routers/repos sin acceso a la request -- ahí cae
    al fallback de pb_public_base() (PB_PUBLIC_URL o settings.pb_url)."""
    if not user:
        return ""
    nombre = user.get("avatar", "") if isinstance(user, dict) else ""
    if not nombre:
        return ""
    uid = user.get("id", "") if isinstance(user, dict) else ""
    base = pb_public_base(request)
    return f"{base}/api/files/users/{uid}/{nombre}"


@jinja2.pass_context
def _avatar_url_jinja(context, user) -> str:
    return avatar_url(user, context.get("request"))


_DASHBOARD_POR_ROL = {
    "admin":                   "/dashboard",
    "gerente":                 "/gerente/dashboard",
    "ciclista":                "/ciclista/dashboard",
    "empleado-operacion":      "/empleado/operacion/dashboard",
    "empleado-mantenimiento":  "/empleado/mantenimiento/dashboard",
    "empleado-vigilancia":     "/empleado/vigilancia/dashboard",
}


def dashboard_url(user) -> str:
    """Dashboard de inicio del rol actual (destino del logo y del boton volver por defecto)."""
    if not user or not isinstance(user, dict):
        return "/"
    return _DASHBOARD_POR_ROL.get(user.get("rol_slug", ""), "/dashboard")


def file_url(collection: str, record_id: str, filename: str, thumb: str = "", request=None) -> str:
    """URL de un archivo subido a una colección de PocketBase, o cadena vacía si no hay nombre.
    `request` opcional -- mismo motivo que en avatar_url(): se llama tanto
    desde plantillas (contexto inyectado por `_file_url_jinja`) como directo
    desde routers/bicicletas_repo.py sin request a mano."""
    if not filename or not record_id:
        return ""
    base = pb_public_base(request)
    url = f"{base}/api/files/{collection}/{record_id}/{filename}"
    if thumb:
        url += f"?thumb={thumb}"
    return url


@jinja2.pass_context
def _file_url_jinja(context, collection: str, record_id: str, filename: str, thumb: str = "") -> str:
    return file_url(collection, record_id, filename, thumb, context.get("request"))


def jsonseguro(valor) -> Markup:
    """Reemplazo de `| safe` para insertar un JSON ya serializado
    (json.dumps en el router) dentro de un <script> inline. json.dumps()
    no escapa '</', asi que un valor de origen editable por un rol
    interno (ej. nombre de estacion con '</script><script>...') podia
    romper el bloque script e inyectar JS arbitrario -- XSS almacenado,
    ver docs/HOJA_DE_RUTA.md, auditoria de seguridad. Escapa <, > y &
    (equivalente a lo que hace Flask/Jinja en su filtro `tojson`)."""
    texto = "null" if valor is None else str(valor)
    texto = texto.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return Markup(texto)


def _tojson(valor) -> Markup:
    """Serializa a JSON seguro para insertar dentro de un <script> inline --
    Jinja2Templates (a diferencia de Flask) no trae un filtro `tojson` por
    defecto. Mismo escape de '<', '>' y '&' que jsonseguro() (evita que un
    valor con '</script>' rompa el bloque), pero haciendo el json.dumps()
    acá mismo -- jsonseguro() espera un string ya serializado.

    `default=str` porque algunas filas de ClickHouse (ej. catalogo_bicicletas,
    campo exclusiva_hasta) traen un `date`/`datetime` real -- necesario para
    poder usar .strftime() del lado servidor en otras plantillas (ver
    componentes/tarjeta_bicicleta.html), pero json.dumps() no lo serializa
    por defecto. str(date) da 'YYYY-MM-DD', suficiente para el uso en JS."""
    texto = json.dumps(valor, default=str)
    texto = texto.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return Markup(texto)


def _fmt_moneda(valor) -> str:
    """$-0.50 (el signo pegado al numero) se ve como un error de imprenta --
    el signo va antes del simbolo: -$0.50. Usado por componentes/factura.html
    (mismo criterio que app/reportes/factura.py:_fmt_moneda, version PDF)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return "$0.00"
    return f"-${abs(numero):,.2f}" if numero < 0 else f"${numero:,.2f}"


def _fmt_num(value) -> str:
    """Formatea un número con separadores de miles: 3708271 → 3,708,271."""
    if value is None:
        return "—"
    try:
        return f"{int(float(value)):,}"
    except (ValueError, TypeError):
        return str(value)


templates = Jinja2Templates(directory=str(_BASE))
templates.env.filters["num"] = _fmt_num
templates.env.filters["moneda"] = _fmt_moneda
templates.env.filters["jsonseguro"] = jsonseguro
templates.env.filters["tojson"] = _tojson
templates.env.globals["avatar_url"] = _avatar_url_jinja
templates.env.globals["file_url"] = _file_url_jinja
templates.env.globals["dashboard_url"] = dashboard_url
templates.env.globals["csrf_token"] = get_csrf_token
