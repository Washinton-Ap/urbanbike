"""
Configura PocketBase para el sistema UrbanBike Ecuador:
  1. Elimina estaciones antiguas y crea 8 estaciones reales de Ecuador
  2. Crea colección 'viajes' para gestión de alquileres
  3. Crea colección 'ordenes_mant' para mantenimiento
"""

import sys
import requests

PB = "http://localhost:8090"

r = requests.post(
    f"{PB}/api/collections/_superusers/auth-with-password",
    json={"identity": "admin@urbanbike.com", "password": "secret_pocketbase"},
)
if not r.ok:
    print(f"ERROR auth: {r.text}"); sys.exit(1)

token = r.json()["token"]
h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── 1. Reemplazar estaciones ────────────────────────────────────────────────
ECUADOR_STATIONS = [
    {"nombre": "Parque La Carolina",     "codigo": "EC-Q01", "capacidad": 20, "latitud": -0.1807, "longitud": -78.4866, "activa": True},
    {"nombre": "Plaza Grande",            "codigo": "EC-Q02", "capacidad": 15, "latitud": -0.2201, "longitud": -78.5123, "activa": True},
    {"nombre": "Parque El Ejido",         "codigo": "EC-Q03", "capacidad": 18, "latitud": -0.2075, "longitud": -78.5045, "activa": True},
    {"nombre": "Malecon 2000",            "codigo": "EC-G01", "capacidad": 25, "latitud": -2.1962, "longitud": -79.8862, "activa": True},
    {"nombre": "Parque Centenario",       "codigo": "EC-G02", "capacidad": 20, "latitud": -2.1900, "longitud": -79.8783, "activa": True},
    {"nombre": "Parque Calderon",         "codigo": "EC-C01", "capacidad": 15, "latitud": -2.8971, "longitud": -79.0044, "activa": True},
    {"nombre": "Parque Maldonado",        "codigo": "EC-R01", "capacidad": 12, "latitud": -1.6635, "longitud": -78.6540, "activa": True},
    {"nombre": "Parque Central Ambato",   "codigo": "EC-A01", "capacidad": 12, "latitud": -1.2490, "longitud": -78.6167, "activa": True},
]

# Eliminar estaciones existentes
existing = requests.get(f"{PB}/api/collections/estaciones/records?perPage=200", headers=h)
if existing.ok:
    for s in existing.json().get("items", []):
        requests.delete(f"{PB}/api/collections/estaciones/records/{s['id']}", headers=h)
    print(f"  Eliminadas {len(existing.json().get('items', []))} estaciones antiguas")

# Crear nuevas estaciones Ecuador
created = 0
for s in ECUADOR_STATIONS:
    r = requests.post(f"{PB}/api/collections/estaciones/records", headers=h, json=s)
    if r.ok:
        created += 1
        print(f"  CREADA: {s['nombre']} ({s['codigo']})")
    else:
        print(f"  ERROR creando {s['nombre']}: {r.status_code} {r.text[:120]}")

print(f"\n[OK] Estaciones Ecuador: {created}/{len(ECUADOR_STATIONS)}")


# ── 2. Crear colecciones ────────────────────────────────────────────────────
def get_collections():
    r = requests.get(f"{PB}/api/collections?perPage=200", headers=h)
    if r.ok:
        return {c["name"] for c in r.json().get("items", [])}
    return set()


def create_collection(name: str, fields: list) -> bool:
    payload = {"name": name, "type": "base", "fields": fields}
    r = requests.post(f"{PB}/api/collections", headers=h, json=payload)
    if r.ok:
        return True
    # Fallback: schema key (formato antiguo)
    payload2 = {"name": name, "type": "base", "schema": fields}
    r2 = requests.post(f"{PB}/api/collections", headers=h, json=payload2)
    if r2.ok:
        return True
    print(f"  ERROR: {r.status_code} {r.text[:200]}")
    return False


existing_cols = get_collections()

# Colección viajes
if "viajes" in existing_cols:
    print("\n[OK] Colección 'viajes' ya existe — omitida")
else:
    viajes_fields = [
        {"name": "ciclista_id",           "type": "text"},
        {"name": "ciclista_nombre",        "type": "text"},
        {"name": "bicicleta_id",           "type": "text"},
        {"name": "bicicleta_codigo",       "type": "text"},
        {"name": "estacion_inicio_id",     "type": "text"},
        {"name": "estacion_inicio_nombre", "type": "text"},
        {"name": "estacion_fin_id",        "type": "text"},
        {"name": "latitud_inicio",         "type": "number"},
        {"name": "longitud_inicio",        "type": "number"},
        {"name": "latitud_actual",         "type": "number"},
        {"name": "longitud_actual",        "type": "number"},
        {"name": "estado",                 "type": "select",
         "values": ["activo", "completado", "cancelado"], "maxSelect": 1},
        {"name": "fecha_inicio",           "type": "text"},
        {"name": "fecha_fin",              "type": "text"},
        {"name": "duracion_minutos",       "type": "number"},
    ]
    ok = create_collection("viajes", viajes_fields)
    print(f"\n{'[OK]' if ok else '[FAIL]'} Colección 'viajes' {'creada' if ok else 'no creada'}")

# Colección ordenes_mant
if "ordenes_mant" in existing_cols:
    print("[OK] Colección 'ordenes_mant' ya existe — omitida")
else:
    ordenes_fields = [
        {"name": "bicicleta_id",     "type": "text"},
        {"name": "bicicleta_codigo", "type": "text"},
        {"name": "tipo",             "type": "select",
         "values": ["preventivo", "correctivo", "urgente"], "maxSelect": 1},
        {"name": "descripcion",      "type": "text"},
        {"name": "estado",           "type": "select",
         "values": ["pendiente", "en_proceso", "completado"], "maxSelect": 1},
        {"name": "tecnico_nombre",   "type": "text"},
        {"name": "fecha_apertura",   "type": "text"},
        {"name": "fecha_cierre",     "type": "text"},
    ]
    ok = create_collection("ordenes_mant", ordenes_fields)
    print(f"{'[OK]' if ok else '[FAIL]'} Colección 'ordenes_mant' {'creada' if ok else 'no creada'}")


print("\nSetup Ecuador completado.")
