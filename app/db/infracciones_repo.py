"""Repositorio de acceso a infracciones reales de ciclistas.

Fuente real: urbanbike_operativa.infracciones en ClickHouse (0 filas
reales hasta hoy -- ORDER BY ya corregido en la sesion del 06-ago-2026,
seccion 19 de docs/HOJA_DE_RUTA.md, pero sin ningun escritor real hasta
esta sesion, Nivel 3 de la seccion 23).

Nace junto con el Nivel 3 del checklist de devolucion: hasta hoy, una
devolucion reprobada creaba la infraccion solo en la coleccion
`infracciones` de PocketBase, invisible para cualquier informe o KPI
real (S17 en db/03_informes_simples.sql ya la espera).

Cargo por danos (decision confirmada con Washington el 06-ago-2026,
sesion de la seccion 23): se guarda en `monto_multa`, el mismo INSERT de
la infraccion -- no como pago/garantia aparte. `monto_multa` no tenia
ningun escritor real en todo el codigo hasta hoy (confirmado con grep).

Fuera de alcance de este repositorio (documentado, no se toca aqui):
`empleado/vigilancia/infracciones.html` y el bloqueo de ciclista por
acumulacion de infracciones pendientes siguen leyendo/escribiendo
PocketBase (`resuelta`, `users.activo`) -- dos fuentes paralelas hasta
que esa pantalla se migre en una sesion aparte.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.db import clickhouse as ch

UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"
TIPOS_VALIDOS = ("dano_bicicleta",)


def resolver_o_crear_usuario(*, email: str, nombre_completo: str, rol: str) -> str:
    """id real de usuarios (busca por email, lo crea si no existe) --
    mismo patron que asegurar_inspector() en inspecciones_repo.py y
    asegurar_usuario() en etl/07_migrar_viajes_pagos.py. El ciclista de
    una devolucion real puede no estar migrado todavia (el ETL corre
    cada hora, la inspeccion pasa en vivo apenas se completa el viaje),
    asi que no alcanza con leer alquileres.id_usuario -- se resuelve por
    email, igual que el inspector."""
    if not email:
        return UUID_SENTINELA

    filas = ch.query(
        "SELECT id FROM urbanbike_operativa.usuarios FINAL WHERE email = %(email)s",
        {"email": email},
    )
    if filas:
        return str(filas[0]["id"])

    nombre, _, apellido = (nombre_completo or email).strip().partition(" ")
    nuevo_id = str(uuid.uuid4())
    ultimo = ch.scalar(
        "SELECT max(toUInt32OrZero(substring(codigo, 3))) FROM urbanbike_operativa.usuarios"
    ) or 0
    codigo = f"U-{ultimo + 1:04d}"
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.usuarios (id, codigo, nombre, apellido, email, rol, estado)
        VALUES (%(id)s, %(codigo)s, %(nombre)s, %(apellido)s, %(email)s, %(rol)s, 'activo')
    """, parameters={
        "id": nuevo_id, "codigo": codigo, "nombre": nombre or email,
        "apellido": apellido, "email": email, "rol": rol,
    })
    return nuevo_id


def crear(*, id_usuario: str, tipo: str, descripcion: str,
          id_alquiler: str = "", monto_multa: float = 0.0) -> str:
    nuevo_id = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.infracciones
            (id, id_usuario, id_alquiler, tipo, descripcion, monto_multa, fecha)
        VALUES
            (%(id)s, %(id_usuario)s, %(id_alquiler)s, %(tipo)s, %(descripcion)s,
             %(monto_multa)s, %(ahora)s)
    """, parameters={
        "id": nuevo_id, "id_usuario": id_usuario, "id_alquiler": id_alquiler,
        "tipo": tipo, "descripcion": descripcion, "monto_multa": monto_multa,
        "ahora": datetime.now(),
    })
    return nuevo_id
