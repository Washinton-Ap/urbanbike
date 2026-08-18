"""Consulta real de permisos por rol contra roles/permisos/rol_permisos
(ver docs/HOJA_DE_RUTA.md secciones 29/30) -- reemplaza, ruta por ruta,
la verificacion fija de ROLE_RULES en app/middleware/auth.py.

Tambien el acceso a rol_permisos para la pantalla de administracion
(seccion 41): otorgar/revocar son INSERT/DELETE reales sobre
rol_permisos (MergeTree simple, no ReplacingMergeTree) -- una fila
presente significa "otorgado", ausente significa "no otorgado", sin
version historica. Decision explicita de Washington al pedir esta
pantalla, distinta del criterio de "log de eventos, nunca se borra" con
el que se penso la tabla originalmente en la seccion 29 -- revocar aqui
de verdad borra la fila.
"""

from __future__ import annotations

from app.db import clickhouse as ch

UUID_SENTINELA = "00000000-0000-0000-0000-000000000000"

# Orden fijo de columnas para la matriz -- no alfabetico, alineado con como
# ya se presentan los roles en el resto de la app (ver ROLE_RULES).
ORDEN_ROLES = [
    "admin", "gerente", "empleado-operacion",
    "empleado-mantenimiento", "empleado-vigilancia", "ciclista",
]


def tiene_permiso(rol_slug: str, codigo: str, id_usuario: str | None = None) -> bool:
    """True si el usuario tiene el permiso (por codigo, ej.
    'bicicletas:crear') hoy. Sin rol o sin codigo, siempre False --
    nunca se asume acceso por defecto.

    Si se pasa id_usuario (id real de PocketBase users, ver seccion 42),
    primero se busca una excepcion explicita en usuario_permisos para
    ese usuario y ese permiso -- si existe, gana siempre, en cualquier
    direccion (otorga aunque el rol no lo de, o revoca aunque el rol si
    lo de). Sin excepcion (o sin id_usuario), cae al comportamiento de
    siempre: heredar de rol_permisos."""
    if not rol_slug or not codigo:
        return False

    if id_usuario:
        excepcion = ch.query_one(
            """
            SELECT up.estado AS estado
            FROM urbanbike_operativa.usuario_permisos up
            JOIN urbanbike_operativa.permisos p ON p.id = up.id_permiso
            WHERE up.id_usuario = %(usuario)s AND p.codigo = %(cod)s
            """,
            {"usuario": id_usuario, "cod": codigo},
        )
        if excepcion:
            return excepcion["estado"] == "otorgado"

    n = ch.scalar(
        """
        SELECT count() FROM urbanbike_operativa.rol_permisos rp
        JOIN urbanbike_operativa.roles r FINAL ON r.id = rp.id_rol
        JOIN urbanbike_operativa.permisos p FINAL ON p.id = rp.id_permiso
        WHERE r.slug = %(rol)s AND p.codigo = %(cod)s
        """,
        {"rol": rol_slug, "cod": codigo},
    )
    return bool(n)


def resolver_usuario_por_email(email: str) -> str:
    """id real de usuarios.id por email para otorgado_por -- sentinela si
    no existe. A diferencia de infracciones_repo.resolver_o_crear_usuario,
    aqui NO se crea el usuario si falta: es solo un dato de auditoria de
    quien tocó el botón, no una entidad de negocio que deba existir."""
    if not email:
        return UUID_SENTINELA
    filas = ch.query(
        "SELECT id FROM urbanbike_operativa.usuarios FINAL WHERE email = %(email)s",
        {"email": email},
    )
    return str(filas[0]["id"]) if filas else UUID_SENTINELA


def listar_matriz() -> dict:
    """Roles (orden fijo), permisos agrupados por recurso, y el conjunto
    real de asignaciones (id_rol, id_permiso) hoy en rol_permisos -- todo
    lo que necesita app/templates/admin/permisos.html para pintar la
    matriz. Los ids se normalizan a string aqui mismo -- clickhouse-connect
    devuelve columnas UUID como uuid.UUID, y comparar eso contra
    grant_set (tuplas de string) en la plantilla Jinja seria fragil."""
    roles = ch.query("SELECT id, slug, nombre FROM urbanbike_operativa.roles FINAL")
    for r in roles:
        r["id"] = str(r["id"])
    orden = {slug: i for i, slug in enumerate(ORDEN_ROLES)}
    roles.sort(key=lambda r: orden.get(r["slug"], 99))

    permisos = ch.query(
        "SELECT id, codigo, recurso, accion, descripcion FROM urbanbike_operativa.permisos FINAL "
        "ORDER BY recurso, accion"
    )
    grupos: dict[str, list] = {}
    for p in permisos:
        p["id"] = str(p["id"])
        grupos.setdefault(p["recurso"], []).append(p)

    grants = ch.query("SELECT id_rol, id_permiso FROM urbanbike_operativa.rol_permisos")
    grant_set = {(str(g["id_rol"]), str(g["id_permiso"])) for g in grants}

    return {"roles": roles, "grupos": grupos, "grant_set": grant_set}


def obtener_rol(id_rol: str) -> dict | None:
    filas = ch.query("SELECT id, slug, nombre FROM urbanbike_operativa.roles FINAL WHERE id = %(id)s", {"id": id_rol})
    return filas[0] if filas else None


def obtener_permiso(id_permiso: str) -> dict | None:
    filas = ch.query(
        "SELECT id, codigo, recurso, accion FROM urbanbike_operativa.permisos FINAL WHERE id = %(id)s",
        {"id": id_permiso},
    )
    return filas[0] if filas else None


def otorgar(id_rol: str, id_permiso: str, otorgado_por: str) -> None:
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.rol_permisos (id_rol, id_permiso, otorgado_por)
        VALUES (%(rol)s, %(permiso)s, %(por)s)
    """, parameters={"rol": id_rol, "permiso": id_permiso, "por": otorgado_por or UUID_SENTINELA})


def revocar(id_rol: str, id_permiso: str) -> None:
    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.rol_permisos DELETE WHERE id_rol = %(rol)s AND id_permiso = %(permiso)s",
        parameters={"rol": id_rol, "permiso": id_permiso},
        settings={"mutations_sync": 1},
    )


def toggle(id_rol: str, id_permiso: str, otorgado_por: str) -> bool:
    """Otorga si no existe, revoca si existe (INSERT/DELETE reales sobre
    rol_permisos). Devuelve el estado nuevo: True = otorgado, False =
    revocado."""
    existe = ch.scalar(
        "SELECT count() FROM urbanbike_operativa.rol_permisos WHERE id_rol = %(rol)s AND id_permiso = %(permiso)s",
        {"rol": id_rol, "permiso": id_permiso},
    )
    if existe:
        revocar(id_rol, id_permiso)
        return False
    otorgar(id_rol, id_permiso, otorgado_por)
    return True


# ── Excepciones por usuario individual (ver docs/HOJA_DE_RUTA.md sección 42) ──

def listar_permisos_usuario(id_usuario: str, rol_slug: str) -> dict[str, list]:
    """Los 38 permisos agrupados por recurso, cada uno con:
    heredado (bool, viene o no del rol), excepcion (None|'otorgado'|'revocado'),
    efectivo (bool, el resultado real que ya calcula tiene_permiso()) --
    todo lo que necesita la plantilla de detalle para decidir que boton
    mostrar por fila."""
    permisos = ch.query(
        "SELECT id, codigo, recurso, accion, descripcion FROM urbanbike_operativa.permisos FINAL "
        "ORDER BY recurso, accion"
    )
    for p in permisos:
        p["id"] = str(p["id"])

    heredados: set[str] = set()
    if rol_slug:
        filas = ch.query(
            """
            SELECT p.id AS id FROM urbanbike_operativa.rol_permisos rp
            JOIN urbanbike_operativa.roles r FINAL ON r.id = rp.id_rol
            JOIN urbanbike_operativa.permisos p FINAL ON p.id = rp.id_permiso
            WHERE r.slug = %(rol)s
            """,
            {"rol": rol_slug},
        )
        heredados = {str(f["id"]) for f in filas}

    excepciones = ch.query(
        "SELECT id_permiso, estado FROM urbanbike_operativa.usuario_permisos WHERE id_usuario = %(usuario)s",
        {"usuario": id_usuario},
    )
    excepcion_map = {str(e["id_permiso"]): e["estado"] for e in excepciones}

    grupos: dict[str, list] = {}
    for p in permisos:
        heredado = p["id"] in heredados
        excepcion = excepcion_map.get(p["id"])
        p["heredado"] = heredado
        p["excepcion"] = excepcion
        p["efectivo"] = (excepcion == "otorgado") if excepcion else heredado
        # accion que debe disparar el unico boton de esta fila -- calculada
        # aqui para que la plantilla no tenga que repetir esta logica
        if excepcion:
            p["accion_boton"] = "quitar"
        elif heredado:
            p["accion_boton"] = "revocar"
        else:
            p["accion_boton"] = "otorgar"
        grupos.setdefault(p["recurso"], []).append(p)

    return grupos


def set_excepcion_usuario(id_usuario: str, id_permiso: str, accion: str, otorgado_por: str) -> None:
    """accion: 'otorgar' | 'revocar' | 'quitar'. Siempre borra cualquier
    excepcion previa para ese (usuario, permiso) primero -- nunca UPDATE
    in place, mismo criterio que rol_permisos.toggle(). 'quitar' termina
    ahi (vuelve a heredar del rol); 'otorgar'/'revocar' insertan la fila
    nueva con el estado correspondiente."""
    if accion not in ("otorgar", "revocar", "quitar"):
        raise ValueError(f"accion invalida: {accion!r}")
    ch.get_client().command(
        "ALTER TABLE urbanbike_operativa.usuario_permisos DELETE WHERE id_usuario = %(usuario)s AND id_permiso = %(permiso)s",
        parameters={"usuario": id_usuario, "permiso": id_permiso},
        settings={"mutations_sync": 1},
    )
    if accion == "quitar":
        return
    estado = "otorgado" if accion == "otorgar" else "revocado"
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.usuario_permisos (id_usuario, id_permiso, estado, otorgado_por)
        VALUES (%(usuario)s, %(permiso)s, %(estado)s, %(por)s)
    """, parameters={
        "usuario": id_usuario, "permiso": id_permiso, "estado": estado,
        "por": otorgado_por or UUID_SENTINELA,
    })


def resumen_por_accion(id_usuario: str, rol_slug: str) -> dict[str, dict]:
    """Para cada una de las 4 acciones (leer/crear/actualizar/eliminar):
    cuántos recursos reales la tienen definida (total) y en cuántos el
    usuario la tiene efectiva hoy (efectivos), más el estado agregado
    ('todos'|'parcial'|'ninguno') que decide que boton mostrar el
    indicador. Reutiliza listar_permisos_usuario() -- no vuelve a
    calcular heredado/efectivo por su cuenta, cero consultas nuevas mas
    alla de las que esa funcion ya hace (ver docs/HOJA_DE_RUTA.md
    sección 43)."""
    grupos = listar_permisos_usuario(id_usuario, rol_slug)
    conteo = {a: {"total": 0, "efectivos": 0} for a in ("leer", "crear", "actualizar", "eliminar")}
    for lista in grupos.values():
        for p in lista:
            if p["accion"] in conteo:
                conteo[p["accion"]]["total"] += 1
                if p["efectivo"]:
                    conteo[p["accion"]]["efectivos"] += 1
    for datos in conteo.values():
        if datos["efectivos"] == 0:
            datos["estado"] = "ninguno"
        elif datos["efectivos"] == datos["total"]:
            datos["estado"] = "todos"
        else:
            datos["estado"] = "parcial"
    return conteo


def set_excepcion_masiva(id_usuario: str, rol_slug: str, accion: str, otorgar: bool, otorgado_por: str) -> int:
    """Accion masiva real sobre los 4 indicadores (ver
    docs/HOJA_DE_RUTA.md sección 44): otorgar=True crea una excepción
    'otorgado' en CADA recurso donde el usuario todavía no tiene esa
    acción efectiva hoy (ni por rol ni por excepción previa);
    otorgar=False crea una excepción 'revocado' en CADA recurso donde
    sí la tiene hoy (por rol o por una excepción 'otorgado' previa).
    Reutiliza set_excepcion_usuario() fila por fila -- mismo INSERT/DELETE
    real de siempre, no una fila genérica ni una tabla nueva. Devuelve
    cuántos recursos se tocaron de verdad (0 si ya estaba en el estado
    pedido en todos)."""
    grupos = listar_permisos_usuario(id_usuario, rol_slug)
    tocados = 0
    for lista in grupos.values():
        for p in lista:
            if p["accion"] != accion:
                continue
            if otorgar and not p["efectivo"]:
                set_excepcion_usuario(id_usuario, p["id"], "otorgar", otorgado_por)
                tocados += 1
            elif not otorgar and p["efectivo"]:
                set_excepcion_usuario(id_usuario, p["id"], "revocar", otorgado_por)
                tocados += 1
    return tocados
