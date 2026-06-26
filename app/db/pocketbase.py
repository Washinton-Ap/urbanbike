"""Cliente HTTP para operaciones CRUD contra PocketBase."""

from __future__ import annotations

import requests
from typing import Any

from app.config import settings


class PocketBaseError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


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
            msg = r.json().get("message", r.text) if r.content else r.text
            raise PocketBaseError(r.status_code, msg)
        return r.json()


# Singleton que usa el token del superusuario para operaciones internas
_admin_client: PocketBaseClient | None = None


def get_admin_client() -> PocketBaseClient:
    global _admin_client
    if _admin_client is None:
        _admin_client = PocketBaseClient()
        data = _admin_client.auth_superuser()
        _admin_client.set_token(data["token"])
    return _admin_client


def get_user_client(token: str) -> PocketBaseClient:
    """Devuelve un cliente con el token de sesión del usuario."""
    client = PocketBaseClient()
    client.set_token(token)
    return client


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
