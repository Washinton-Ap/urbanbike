"""Templates Jinja2 compartido con filtros personalizados."""

from pathlib import Path
from fastapi.templating import Jinja2Templates

from app.config import settings

_BASE = Path(__file__).parent / "templates"


def avatar_url(user) -> str:
    """URL del archivo de avatar del usuario en PocketBase, o cadena vacía si no tiene."""
    if not user:
        return ""
    nombre = user.get("avatar", "") if isinstance(user, dict) else ""
    if not nombre:
        return ""
    uid = user.get("id", "") if isinstance(user, dict) else ""
    return f"{settings.pb_url}/api/files/users/{uid}/{nombre}"


def file_url(collection: str, record_id: str, filename: str, thumb: str = "") -> str:
    """URL de un archivo subido a una colección de PocketBase, o cadena vacía si no hay nombre."""
    if not filename or not record_id:
        return ""
    url = f"{settings.pb_url}/api/files/{collection}/{record_id}/{filename}"
    if thumb:
        url += f"?thumb={thumb}"
    return url


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
templates.env.globals["avatar_url"] = avatar_url
templates.env.globals["file_url"] = file_url
