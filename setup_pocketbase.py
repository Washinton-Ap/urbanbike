"""Aprovisiona colecciones y campos de PocketBase para UrbanBike.

Se conecta como superusuario y crea la colección `infracciones` (si no
existe) y agrega los campos faltantes en `users`, `viajes`,
`ordenes_mant` y `pagos`. Es idempotente: los campos/colecciones que ya
existen se detectan y no se vuelven a crear.
"""

import sys

import requests

PB_URL = "http://localhost:8090"
ADMIN_EMAIL = "admin@urbanbike.com"
ADMIN_PASSWORD = "secret_pocketbase"

# PocketBase 0.39 reemplazó /api/admins/auth-with-password por el
# endpoint de la colección interna _superusers.
AUTH_ENDPOINT = f"{PB_URL}/api/collections/_superusers/auth-with-password"
COLLECTIONS_ENDPOINT = f"{PB_URL}/api/collections"

INFRACCIONES_FIELDS = [
    ("ciclista_id", "text"),
    ("tipo", "text"),
    ("descripcion", "text"),
    ("bicicleta_id", "text"),
    ("bicicleta_codigo", "text"),
    ("resuelta", "bool"),
    ("resolucion", "text"),
    ("fecha", "text"),
    ("fecha_resolucion", "text"),
    ("resuelta_por", "text"),
    ("notificada_por", "text"),
]

USERS_FIELDS = [
    ("activo", "bool"),
]

VIAJES_FIELDS = [
    ("es_presencial", "bool"),
    ("ciclista_contacto", "text"),
]

ORDENES_MANT_FIELDS = [
    ("notificada_por", "text"),
    ("origen", "text"),
    ("certificada_por", "text"),
    ("observaciones_cierre", "text"),
    ("observaciones", "text"),
    ("fecha_inicio_trabajo", "text"),
]

PAGOS_FIELDS = [
    ("es_presencial", "bool"),
    ("empleado_id", "text"),
]

# (nombre_coleccion, campos, se_crea_si_no_existe)
TAREAS = [
    ("infracciones", INFRACCIONES_FIELDS, True),
    ("users", USERS_FIELDS, False),
    ("viajes", VIAJES_FIELDS, False),
    ("ordenes_mant", ORDENES_MANT_FIELDS, False),
    ("pagos", PAGOS_FIELDS, False),
]


def autenticar() -> str:
    resp = requests.post(
        AUTH_ENDPOINT,
        json={"identity": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def obtener_colecciones(token: str) -> dict:
    resp = requests.get(
        COLLECTIONS_ENDPOINT,
        params={"perPage": 200},
        headers={"Authorization": token},
        timeout=10,
    )
    resp.raise_for_status()
    return {c["name"]: c for c in resp.json()["items"]}


def crear_coleccion(token: str, nombre: str, campos: list) -> dict:
    payload = {
        "name": nombre,
        "type": "base",
        "fields": [{"name": n, "type": t} for n, t in campos],
    }
    resp = requests.post(
        COLLECTIONS_ENDPOINT,
        json=payload,
        headers={"Authorization": token},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def agregar_campos_faltantes(token: str, coleccion: dict, campos: list):
    """Agrega a `coleccion` los campos de `campos` que aún no existan.

    Devuelve (agregados, ya_existentes).
    """
    existentes = {f["name"] for f in coleccion["fields"]}
    nuevos = []
    agregados = []
    ya_existentes = []

    for nombre, tipo in campos:
        if nombre in existentes:
            ya_existentes.append(nombre)
            continue
        nuevos.append({"name": nombre, "type": tipo})
        agregados.append(nombre)

    if not nuevos:
        return agregados, ya_existentes

    payload_campos = coleccion["fields"] + nuevos
    resp = requests.patch(
        f"{COLLECTIONS_ENDPOINT}/{coleccion['id']}",
        json={"fields": payload_campos},
        headers={"Authorization": token},
        timeout=10,
    )
    resp.raise_for_status()
    return agregados, ya_existentes


def main():
    resumen = {
        "colecciones_creadas": [],
        "colecciones_existentes": [],
        "campos_agregados": [],
        "campos_ya_existentes": [],
        "errores": [],
    }

    print(f"Conectando a PocketBase en {PB_URL} ...")
    try:
        token = autenticar()
    except Exception as e:
        print(f"ERROR FATAL: no se pudo autenticar como superusuario: {e}")
        sys.exit(1)
    print("Autenticacion exitosa.\n")

    try:
        colecciones = obtener_colecciones(token)
    except Exception as e:
        print(f"ERROR FATAL: no se pudo obtener la lista de colecciones: {e}")
        sys.exit(1)

    for nombre, campos, se_puede_crear in TAREAS:
        try:
            if nombre not in colecciones:
                if not se_puede_crear:
                    msg = f"La coleccion '{nombre}' no existe y esta tarea no crea colecciones nuevas"
                    print(f"[ERROR] {msg}")
                    resumen["errores"].append(msg)
                    continue
                print(f"Creando coleccion '{nombre}' ...")
                colecciones[nombre] = crear_coleccion(token, nombre, campos)
                resumen["colecciones_creadas"].append(nombre)
                print(f"  -> coleccion '{nombre}' creada")
            else:
                resumen["colecciones_existentes"].append(nombre)
                print(f"La coleccion '{nombre}' ya existia, verificando campos ...")

            agregados, ya_existentes = agregar_campos_faltantes(
                token, colecciones[nombre], campos
            )
            for campo in agregados:
                print(f"  + campo agregado: {nombre}.{campo}")
                resumen["campos_agregados"].append(f"{nombre}.{campo}")
            for campo in ya_existentes:
                resumen["campos_ya_existentes"].append(f"{nombre}.{campo}")

        except requests.HTTPError as e:
            detalle = e.response.text if e.response is not None else str(e)
            msg = f"{nombre}: {detalle}"
            print(f"[ERROR] {msg}")
            resumen["errores"].append(msg)
        except Exception as e:
            msg = f"{nombre}: {e}"
            print(f"[ERROR] {msg}")
            resumen["errores"].append(msg)

    imprimir_resumen(resumen)


def imprimir_resumen(resumen: dict):
    print("\n" + "=" * 60)
    print("RESUMEN")
    print("=" * 60)

    print(f"\nColecciones creadas ({len(resumen['colecciones_creadas'])}):")
    for c in resumen["colecciones_creadas"]:
        print(f"  - {c}")

    print(f"\nColecciones ya existentes ({len(resumen['colecciones_existentes'])}):")
    for c in resumen["colecciones_existentes"]:
        print(f"  - {c}")

    print(f"\nCampos agregados ({len(resumen['campos_agregados'])}):")
    for c in resumen["campos_agregados"]:
        print(f"  - {c}")

    print(f"\nCampos que ya existian ({len(resumen['campos_ya_existentes'])}):")
    for c in resumen["campos_ya_existentes"]:
        print(f"  - {c}")

    print(f"\nErrores ({len(resumen['errores'])}):")
    if not resumen["errores"]:
        print("  (ninguno)")
    for e in resumen["errores"]:
        print(f"  - {e}")

    print()
    if resumen["errores"]:
        print("Finalizado con errores.")
        sys.exit(1)
    print("Finalizado sin errores.")


if __name__ == "__main__":
    main()
