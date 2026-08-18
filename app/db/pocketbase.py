"""Cliente HTTP para operaciones CRUD contra PocketBase."""

from __future__ import annotations

import requests
from typing import Any

from app.config import settings


class PocketBaseError(Exception):
    def __init__(self, status: int, message: str, data: dict | None = None):
        self.status = status
        # Detalle real por campo (ej. {"email": {"code": "validation_not_unique",
        # "message": "Value must be unique."}}) -- PocketBase siempre pone el
        # mensaje genérico ("Failed to create record.") en el nivel superior,
        # nunca el motivo real, que vive solo en este dict. Sin capturarlo
        # acá, cualquier código que intente distinguir "correo duplicado" de
        # otro error revisando el mensaje de texto nunca lo va a encontrar
        # (ver docs/HOJA_DE_RUTA.md, bug real de registro).
        self.data = data or {}
        super().__init__(message)


def filter_literal(valor: str) -> str:
    """Escapa un valor para usarlo como literal string dentro de un
    `filter=` de PocketBase (su propio lenguaje de expresiones, no SQL).
    Verificado en vivo contra PocketBase real: escapa comillas dobles
    con backslash (`\\"`), NO duplicandolas como en SQL -- ver
    docs/HOJA_DE_RUTA.md, auditoria de seguridad. Antes varios repos
    interpolaban el valor crudo (`f'codigo = "{codigo}"'`), permitiendo
    romper el filtro con un `codigo` que contuviera comillas."""
    escapado = valor.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escapado}"'


class PocketBaseClient:
    """Wrapper delgado sobre la API REST de PocketBase."""

    def __init__(self, base_url: str = settings.pb_url):
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    # ── Auth ─────────────────────────────────────────────────────────────

    def set_token(self, token: str) -> None:
        self._session.headers["Authorization"] = f"Bearer {token}"

    def clear_token(self) -> None:
        self._session.headers.pop("Authorization", None)

    def auth_user(self, email: str, password: str) -> dict:
        """Autentica un usuario normal y devuelve {token, record}."""
        return self._post("/api/collections/users/auth-with-password",
                          {"identity": email, "password": password})

    def request_verification(self, collection: str, email: str) -> None:
        """Solicita a PocketBase el envío del correo de verificación de cuenta."""
        self._post(f"/api/collections/{collection}/request-verification", {"email": email})

    def auth_superuser(self) -> dict:
        return self._post(
            "/api/collections/_superusers/auth-with-password",
            {"identity": settings.pb_superuser_email,
             "password": settings.pb_superuser_password},
        )

    # ── Records ──────────────────────────────────────────────────────────

    def get_record(self, collection: str, record_id: str,
                   expand: str = "") -> dict:
        params = {"expand": expand} if expand else {}
        return self._get(f"/api/collections/{collection}/records/{record_id}",
                         params=params)

    def list_records(self, collection: str, *, filter: str = "",
                     sort: str = "", expand: str = "",
                     page: int = 1, per_page: int = 50) -> dict:
        params: dict[str, Any] = {"page": page, "perPage": per_page}
        if filter:   params["filter"] = filter
        if sort:     params["sort"]   = sort
        if expand:   params["expand"] = expand
        return self._get(f"/api/collections/{collection}/records", params=params)

    def create_record(self, collection: str, data: dict) -> dict:
        return self._post(f"/api/collections/{collection}/records", data)

    def update_record(self, collection: str, record_id: str, data: dict) -> dict:
        return self._patch(f"/api/collections/{collection}/records/{record_id}",
                           data)

    def update_record_with_file(self, collection: str, record_id: str,
                                 data: dict, files: dict) -> dict:
        # Anular el Content-Type fijo de la sesión para que requests genere el boundary multipart.
        headers = {"Content-Type": None}
        r = self._session.patch(
            f"{self.base_url}/api/collections/{collection}/records/{record_id}",
            data=data, files=files, headers=headers, timeout=15,
        )
        return self._handle(r)

    def delete_record(self, collection: str, record_id: str) -> None:
        self._delete(f"/api/collections/{collection}/records/{record_id}")

    # ── HTTP helpers ──────────────────────────────────────────────────────

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = self._session.get(self.base_url + path, params=params, timeout=10)
        return self._handle(r)

    def _post(self, path: str, data: dict) -> dict:
        r = self._session.post(self.base_url + path, json=data, timeout=10)
        return self._handle(r)

    def _patch(self, path: str, data: dict) -> dict:
        r = self._session.patch(self.base_url + path, json=data, timeout=10)
        return self._handle(r)

    def _delete(self, path: str) -> None:
        r = self._session.delete(self.base_url + path, timeout=10)
        if not r.ok:
            raise PocketBaseError(r.status_code, r.text)

    def _handle(self, r: requests.Response) -> dict:
        if not r.ok:
            if r.content:
                body = r.json()
                msg = body.get("message", r.text)
                data = body.get("data") or {}
            else:
                msg, data = r.text, {}
            raise PocketBaseError(r.status_code, msg, data)
        return r.json()


# Singleton que usa el token del superusuario para operaciones internas
_admin_client: PocketBaseClient | None = None


def get_admin_client() -> PocketBaseClient:
    """Bug real encontrado y corregido (ver docs/HOJA_DE_RUTA.md): antes se
    asignaba a `_admin_client` (global) ANTES de autenticar -- si
    `auth_superuser()` fallaba (ej. PocketBase caído en el momento exacto
    de la primera llamada), el objeto ya asignado, sin token válido, se
    quedaba cacheado para siempre (`is None` ya daba False), y cada
    llamada posterior en todo el proceso volvía a fallar en silencio
    (401), sin reintentar nunca la autenticación real. Ahora solo se
    asigna a la global si `auth_superuser()` termina bien -- una falla
    deja `_admin_client` en `None`, así que la próxima llamada reintenta
    de cero."""
    global _admin_client
    if _admin_client is None:
        cliente = PocketBaseClient()
        data = cliente.auth_superuser()
        cliente.set_token(data["token"])
        _admin_client = cliente
    return _admin_client


def get_user_client(token: str) -> PocketBaseClient:
    """Devuelve un cliente con el token de sesión del usuario."""
    client = PocketBaseClient()
    client.set_token(token)
    return client


def primer_email_por_rol(rol_slug: str) -> str | None:
    """Email real del primer usuario activo con este rol (por fecha de
    creación) -- usado por la pantalla de bloqueo para decirle a un
    empleado bloqueado a qué gerente escribir, o a un gerente bloqueado
    a qué admin escribir. None si no hay ninguno real. Verificado en
    vivo: PocketBase soporta filtrar por el slug de una relación
    (rol.slug), no hace falta resolver el id del rol antes."""
    try:
        res = get_admin_client().list_records(
            "users",
            filter=f'rol.slug = {filter_literal(rol_slug)} && activo = true',
            sort="created", per_page=1,
        )
        items = res.get("items", [])
        return items[0].get("email") if items else None
    except Exception:
        return None


def rol_id_por_slug(slug: str) -> str | None:
    """Id real de la colección `roles` para un slug (ej. 'ciclista') --
    usado por el registro público para asignar el rol sin dejar que el
    cliente lo elija (ver app/routers/auth.py:registro_post)."""
    try:
        res = get_admin_client().list_records(
            "roles", filter=f'slug = {filter_literal(slug)}', per_page=1,
        )
        items = res.get("items", [])
        return items[0]["id"] if items else None
    except Exception:
        return None


def registrar_auditoria(token: str, usuario_id: str, nombre: str, email: str,
                         accion: str, modulo: str, detalle: str, request,
                         usuario_rol: str = "") -> None:
    """Registra una entrada en la colección 'auditoria'. Nunca lanza excepciones."""
    from datetime import datetime, timezone

    try:
        ip_cliente = request.client.host if request and request.client else ""
        admin = get_admin_client()
        admin.create_record("auditoria", {
            "usuario_id":     usuario_id,
            "usuario_nombre": nombre,
            "usuario_email":  email,
            "usuario_rol":    usuario_rol,
            "accion":         accion,
            "modulo":         modulo,
            "detalle":        detalle,
            "ip_cliente":     ip_cliente,
            "fecha":          datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    except Exception:
        pass
