"""
ETL paso 3: Configura colecciones de PocketBase vía API REST.
Crea: roles, estaciones_op, bicicletas, tarifas, viajes_activos
Actualiza: users (agrega campo rol)
Siembra: roles, usuarios de prueba por cada rol
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

BASE = os.getenv("PB_URL", "http://localhost:8090")
EMAIL = os.getenv("PB_SUPERUSER_EMAIL")
PASSWORD = os.getenv("PB_SUPERUSER_PASSWORD")


# ── Helpers ─────────────────────────────────────────────────────────────────

def auth() -> str:
    r = requests.post(f"{BASE}/api/collections/_superusers/auth-with-password",
                      json={"identity": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["token"]
    print(f"  Auth OK como superusuario")
    return token


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def get_collection(token: str, name: str) -> dict | None:
    r = requests.get(f"{BASE}/api/collections/{name}", headers=headers(token))
    return r.json() if r.ok else None


def create_or_skip(token: str, payload: dict) -> dict | None:
    name = payload["name"]
    existing = get_collection(token, name)
    if existing:
        print(f"  [{name}] ya existe — omitiendo")
        return existing
    r = requests.post(f"{BASE}/api/collections", headers=headers(token), json=payload)
    if not r.ok:
        print(f"  ERROR creando [{name}]: {r.text}")
        return None
    print(f"  [{name}] creada OK")
    return r.json()


def seed_record(token: str, collection: str, data: dict, unique_field: str) -> dict | None:
    """Crea un registro solo si no existe ya (compara por unique_field)."""
    val = data[unique_field]
    r = requests.get(f"{BASE}/api/collections/{collection}/records",
                     params={"filter": f'{unique_field}="{val}"'},
                     headers=headers(token))
    if r.ok and r.json().get("totalItems", 0) > 0:
        return r.json()["items"][0]
    r = requests.post(f"{BASE}/api/collections/{collection}/records",
                      headers=headers(token), json=data)
    if not r.ok:
        print(f"    ERROR sembrando {collection}/{val}: {r.text}")
        return None
    return r.json()


# ── Definiciones de colecciones ──────────────────────────────────────────────

ROLES_FIELDS = [
    {"name": "nombre",      "type": "text",   "required": True},
    {"name": "slug",        "type": "text",   "required": True},
    {"name": "descripcion", "type": "text",   "required": False},
]

ESTACIONES_OP_FIELDS = [
    {"name": "nombre",        "type": "text",   "required": True},
    {"name": "id_clickhouse", "type": "text",   "required": False},
    {"name": "latitud",       "type": "number", "required": False},
    {"name": "longitud",      "type": "number", "required": False},
    {"name": "capacidad",     "type": "number", "required": False},
    {"name": "activa",        "type": "bool",   "required": False},
]

BICICLETAS_FIELDS = [
    {"name": "codigo",      "type": "text",   "required": True},
    {"name": "tipo",        "type": "select", "required": True,  "maxSelect": 1, "values": ["classic_bike", "electric_bike"]},
    {"name": "estado",      "type": "select", "required": True,  "maxSelect": 1, "values": ["disponible", "en_uso", "mantenimiento", "retirada"]},
    {"name": "bateria_pct", "type": "number", "required": False, "min": 0, "max": 100},
    {"name": "notas",       "type": "text",   "required": False},
]

TARIFAS_FIELDS = [
    {"name": "nombre",            "type": "text",   "required": True},
    {"name": "tipo_usuario",      "type": "select", "required": True, "maxSelect": 1, "values": ["member", "casual"]},
    {"name": "precio_base",       "type": "number", "required": False},
    {"name": "precio_por_minuto", "type": "number", "required": False},
    {"name": "activa",            "type": "bool",   "required": False},
]

VIAJES_ACTIVOS_FIELDS = [
    {"name": "started_at",  "type": "autodate", "required": False, "onCreate": True, "onUpdate": False},
    {"name": "lat_inicio",  "type": "number",   "required": False},
    {"name": "lng_inicio",  "type": "number",   "required": False},
]


def make_collection(name: str, fields: list, view_rule: str = "") -> dict:
    return {
        "name":       name,
        "type":       "base",
        "fields":     fields,
        "listRule":   view_rule,
        "viewRule":   view_rule,
        "createRule": "",
        "updateRule": "",
        "deleteRule": None,
    }


# ── Actualizar users con campo rol ────────────────────────────────────────────

def add_rol_to_users(token: str, roles_collection_id: str) -> None:
    col = get_collection(token, "users")
    if not col:
        print("  ERROR: no se encontró la colección users")
        return

    fields = col.get("fields", [])
    if any(f["name"] == "rol" for f in fields):
        print("  [users.rol] ya existe — omitiendo")
        return

    fields.append({
        "name":         "rol",
        "type":         "relation",
        "required":     False,
        "collectionId": roles_collection_id,
        "cascadeDelete":False,
        "maxSelect":    1,
    })

    r = requests.patch(f"{BASE}/api/collections/users",
                       headers=headers(token),
                       json={"fields": fields})
    if r.ok:
        print("  [users.rol] campo de relación agregado OK")
    else:
        print(f"  ERROR actualizando users: {r.text}")


# ── Relaciones con FK ─────────────────────────────────────────────────────────

def add_fk_fields(token: str, bicicletas_id: str, estaciones_id: str) -> None:
    """Agrega campos de relación a bicicletas y viajes_activos."""

    # bicicletas → estaciones_op
    col = get_collection(token, "bicicletas")
    fields = col.get("fields", [])
    if not any(f["name"] == "estacion" for f in fields):
        fields.append({
            "name": "estacion", "type": "relation", "required": False,
            "collectionId": estaciones_id, "cascadeDelete": False, "maxSelect": 1,
        })
        r = requests.patch(f"{BASE}/api/collections/bicicletas",
                           headers=headers(token), json={"fields": fields})
        print("  [bicicletas.estacion] FK agregada" if r.ok else f"  ERROR: {r.text}")

    # viajes_activos → users, bicicletas, estaciones_op
    col = get_collection(token, "viajes_activos")
    fields = col.get("fields", [])
    existing = {f["name"] for f in fields}
    additions = [
        {"name": "usuario",         "type": "relation", "required": True, "collectionId": "_pb_users_auth_", "cascadeDelete": False, "maxSelect": 1},
        {"name": "bicicleta",       "type": "relation", "required": True, "collectionId": bicicletas_id,     "cascadeDelete": False, "maxSelect": 1},
        {"name": "estacion_inicio", "type": "relation", "required": True, "collectionId": estaciones_id,     "cascadeDelete": False, "maxSelect": 1},
    ]
    new_fields = fields + [f for f in additions if f["name"] not in existing]
    if len(new_fields) > len(fields):
        r = requests.patch(f"{BASE}/api/collections/viajes_activos",
                           headers=headers(token), json={"fields": new_fields})
        print("  [viajes_activos] FKs agregadas" if r.ok else f"  ERROR: {r.text}")


# ── Datos iniciales ───────────────────────────────────────────────────────────

ROLES_DATA = [
    {"nombre": "Administrador",          "slug": "admin",                  "descripcion": "Acceso total al sistema"},
    {"nombre": "Gerente",                "slug": "gerente",                "descripcion": "Dashboard analítico de KPIs"},
    {"nombre": "Ciclista",               "slug": "ciclista",               "descripcion": "Reservas y perfil personal"},
    {"nombre": "Empleado Operación",     "slug": "empleado-operacion",     "descripcion": "Estado de bicicletas y estaciones"},
    {"nombre": "Empleado Mantenimiento", "slug": "empleado-mantenimiento", "descripcion": "Reportes de mantenimiento"},
    {"nombre": "Empleado Vigilancia",    "slug": "empleado-vigilancia",    "descripcion": "Monitoreo en tiempo real"},
]

TARIFAS_DATA = [
    {"nombre": "Miembro estándar",  "tipo_usuario": "member", "precio_base": 0.0,  "precio_por_minuto": 0.16, "activa": True},
    {"nombre": "Casual estándar",   "tipo_usuario": "casual", "precio_base": 1.50, "precio_por_minuto": 0.26, "activa": True},
    {"nombre": "Casual ebike",      "tipo_usuario": "casual", "precio_base": 1.50, "precio_por_minuto": 0.36, "activa": True},
]


def seed_test_users(token: str, roles_map: dict) -> None:
    """Crea un usuario de prueba por cada rol en la colección users."""
    test_users = [
        {"email": "admin@urbanbike.com",    "rol_slug": "admin"},
        {"email": "gerente@urbanbike.com",  "rol_slug": "gerente"},
        {"email": "ciclista@urbanbike.com", "rol_slug": "ciclista"},
        {"email": "operacion@urbanbike.com","rol_slug": "empleado-operacion"},
        {"email": "mant@urbanbike.com",     "rol_slug": "empleado-mantenimiento"},
        {"email": "vigil@urbanbike.com",    "rol_slug": "empleado-vigilancia"},
    ]
    for u in test_users:
        rol_id = roles_map.get(u["rol_slug"])
        data = {
            "email":           u["email"],
            "password":        "Urbanbike123!",
            "passwordConfirm": "Urbanbike123!",
            "name":            u["email"].split("@")[0].capitalize(),
            "rol":             rol_id,
            "emailVisibility": True,
        }
        r = requests.get(f"{BASE}/api/collections/users/records",
                         params={"filter": f'email="{u["email"]}"'},
                         headers=headers(token))
        if r.ok and r.json().get("totalItems", 0) > 0:
            print(f"    usuario {u['email']} ya existe")
            continue
        r = requests.post(f"{BASE}/api/collections/users/records",
                          headers=headers(token), json=data)
        if r.ok:
            print(f"    usuario {u['email']} creado OK")
        else:
            print(f"    ERROR {u['email']}: {r.text}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("Autenticando con PocketBase...")
    token = auth()

    print("\nCreando colecciones...")
    roles_col       = create_or_skip(token, make_collection("roles",         ROLES_FIELDS,         view_rule=""))
    estaciones_col  = create_or_skip(token, make_collection("estaciones_op", ESTACIONES_OP_FIELDS, view_rule=""))
    bicicletas_col  = create_or_skip(token, make_collection("bicicletas",    BICICLETAS_FIELDS,    view_rule=""))
    _               = create_or_skip(token, make_collection("tarifas",       TARIFAS_FIELDS,       view_rule=""))
    _               = create_or_skip(token, make_collection("viajes_activos",VIAJES_ACTIVOS_FIELDS,view_rule=""))

    if not roles_col or not estaciones_col or not bicicletas_col:
        print("\nERROR: Alguna colección no pudo crearse. Abortando.")
        sys.exit(1)

    print("\nAgregando campo rol a users...")
    add_rol_to_users(token, roles_col["id"])

    print("\nAgregando FKs de relación...")
    add_fk_fields(token, bicicletas_col["id"], estaciones_col["id"])

    print("\nSembrando roles...")
    roles_map = {}
    for r_data in ROLES_DATA:
        rec = seed_record(token, "roles", r_data, "slug")
        if rec:
            roles_map[r_data["slug"]] = rec["id"]
            print(f"    rol '{r_data['slug']}' OK")

    print("\nSembrando tarifas...")
    for t_data in TARIFAS_DATA:
        seed_record(token, "tarifas", t_data, "nombre")
        print(f"    tarifa '{t_data['nombre']}' OK")

    print("\nCreando usuarios de prueba (password: Urbanbike123!)...")
    seed_test_users(token, roles_map)

    print("\nSetup de PocketBase completado.")
    print("Usuarios de prueba creados:")
    print("  admin@urbanbike.com / Urbanbike123!")
    print("  gerente@urbanbike.com / Urbanbike123!")
    print("  ciclista@urbanbike.com / Urbanbike123!")


if __name__ == "__main__":
    main()
