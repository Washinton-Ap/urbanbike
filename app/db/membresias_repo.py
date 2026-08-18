"""Repositorio de membresia mensual del ciclista.

Fuente real: urbanbike_operativa.membresia_tarifa (precio vigente,
versionado igual que tarifas) y urbanbike_operativa.membresias
(historial real por ciclista, append-only -- ver docs/HOJA_DE_RUTA.md).

'member' deja de ser automatico para cualquier ciclista logueado: pasa
a depender de si su membresia esta activa hoy (esta_activa()). Sin
membresia activa, el ciclista sigue usando el sistema normalmente --
solo paga tarifa 'casual' en vez de 'member'. Nunca bloquea nada.

El pago se simula (sin pasarela real): activar()/procesar_vencidas_hoy()
insertan un pago real en la tabla real de pagos (concepto='membresia'),
usando metodos_pago (ya existia en el esquema, sin ningun consumidor
hasta hoy) como el 'medio de pago simulado' que decide si un cobro
automatico tiene o no con que cobrar.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from app.db import clickhouse as ch
from app.db import facturas_repo
from app.db import notificaciones_repo
from app.db.pocketbase import filter_literal, get_admin_client

DIAS_PERIODO = 30
VENTANA_REEMBOLSO_HORAS = 48
DIAS_AVISO_VENCIMIENTO = 3  # umbral del aviso anticipado (ver docs/HOJA_DE_RUTA.md sección 69)
SENTINELA = "00000000-0000-0000-0000-000000000000"


def _resolver_usuario_pocketbase(id_usuario_ch: str) -> tuple[str, str] | None:
    """El ciclista tiene dos ids distintos para la misma persona: el de
    ClickHouse (`urbanbike_operativa.usuarios.id`, el que usa todo este
    repo) y el de PocketBase (`users.id`, el que espera
    notificaciones_repo.notificar_usuario() -- es el que vive en
    request.session["user"]["id"]). Se resuelven por email, mismo
    criterio que resolver_id_usuario_por_email() en sentido inverso.
    Devuelve (id_pocketbase, nombre_completo) o None si no se pudo
    resolver (ej. usuario de seed sin cuenta real de PocketBase)."""
    fila = ch.query_one(
        "SELECT email, nombre, apellido FROM urbanbike_operativa.usuarios FINAL WHERE id = %(id)s",
        {"id": id_usuario_ch},
    )
    if not fila or not fila.get("email"):
        return None
    pb = get_admin_client()
    items = pb.list_records("users", filter=f'email = {filter_literal(fila["email"])}', per_page=1).get("items", [])
    if not items:
        return None
    nombre = f'{fila.get("nombre", "")} {fila.get("apellido", "")}'.strip() or fila["email"]
    return items[0]["id"], nombre


def resolver_id_usuario_por_email(email: str) -> str | None:
    """Busqueda de solo lectura (no crea) -- para chequeos de precio en
    el catalogo, donde no queremos escribir un usuario nuevo solo por
    mirar una pantalla. Mismo criterio de union por email que ya usa
    infracciones_repo.resolver_o_crear_usuario()."""
    if not email:
        return None
    fila = ch.query_one(
        "SELECT id FROM urbanbike_operativa.usuarios FINAL WHERE email = %(email)s",
        {"email": email},
    )
    return str(fila["id"]) if fila else None


def precio_vigente() -> float:
    fila = ch.query_one("""
        SELECT precio FROM urbanbike_operativa.membresia_tarifa FINAL
        WHERE estado = 'vigente' AND today() BETWEEN vigente_desde AND vigente_hasta
        ORDER BY vigente_desde DESC LIMIT 1
    """)
    return float(fila["precio"]) if fila else 0.0


def estado_actual(id_usuario: str) -> dict | None:
    """Fila mas reciente de membresias para este usuario, o None si
    nunca tuvo ninguna."""
    return ch.query_one("""
        SELECT id, estado, fecha_inicio, fecha_fin, precio, origen, fecha_registro
        FROM urbanbike_operativa.membresias
        WHERE id_usuario = %(id)s
        ORDER BY fecha_inicio DESC, fecha_registro DESC
        LIMIT 1
    """, {"id": id_usuario})


def obtener(id_membresia: str, id_usuario: str) -> dict | None:
    """Un periodo puntual por id, para la pantalla/PDF de comprobante --
    exige id_usuario para no depender solo de que el UUID sea dificil de
    adivinar (misma regla de propiedad que ya usan pago()/comprobante()
    para los pagos de alquiler). Incluye id_factura real (via el pago
    real vinculado) para el boton "Descargar factura" del comprobante."""
    return ch.query_one("""
        SELECT m.id AS id, m.id_usuario AS id_usuario, m.estado AS estado,
               m.fecha_inicio AS fecha_inicio, m.fecha_fin AS fecha_fin,
               m.precio AS precio, m.id_pago AS id_pago, m.origen AS origen,
               m.fecha_registro AS fecha_registro, p.id_factura AS id_factura
        FROM urbanbike_operativa.membresias m
        LEFT JOIN urbanbike_operativa.pagos p FINAL ON p.id = m.id_pago
        WHERE m.id = %(id)s AND m.id_usuario = %(id_usuario)s
        LIMIT 1
    """, {"id": id_membresia, "id_usuario": id_usuario})


def esta_activa(id_usuario: str) -> bool:
    fila = estado_actual(id_usuario)
    if not fila:
        return False
    return fila["estado"] == "activa" and fila["fecha_fin"] >= date.today()


def tipo_membresia_real(email: str) -> str:
    """'member' si el ciclista de este email tiene membresia activa hoy,
    'casual' en cualquier otro caso (nunca tuvo, la dejo vencer, o no se
    pudo resolver su usuario real) -- el reemplazo real del
    TIPO_MEMBRESIA = "member" fijo que asumia cualquier ciclista
    logueado."""
    id_usuario = resolver_id_usuario_por_email(email)
    if id_usuario and esta_activa(id_usuario):
        return "member"
    return "casual"


def _metodo_pago_valido(id_usuario: str) -> bool:
    """Metodo de pago simulado principal y activo -- decide si un cobro
    automatico 'tiene con que cobrar'. metodos_pago ya existia en el
    esquema sin ningun consumidor; esta es la primera vez que se usa
    de verdad."""
    fila = ch.query_one("""
        SELECT estado FROM urbanbike_operativa.metodos_pago FINAL
        WHERE id_usuario = %(id)s AND es_principal = 1
        ORDER BY version DESC LIMIT 1
    """, {"id": id_usuario})
    return bool(fila) and fila["estado"] == "activo"


def _asegurar_metodo_pago(
    id_usuario: str, *,
    ultimos4: str | None = None, marca_tarjeta: str | None = None,
    exp_mes: int | None = None, exp_anio: int | None = None,
) -> None:
    """Crea un metodo de pago simulado ya activo si el usuario no tiene
    ninguno -- nunca hay pasarela real (ver docs/HOJA_DE_RUTA.md), asi
    que nunca se guarda el numero completo, solo un token simulado y los
    ultimos4/marca/vencimiento, igual que cualquier pasarela real jamas
    expone el numero completo de vuelta. Si el wizard de la pantalla
    capturo esos datos (paso 1 del flujo de "pago" simulado), se guardan
    tal cual el ciclista los tipeo -- si no vinieron (ej. lo dispara
    procesar_vencidas_hoy() sin pantalla), cae al valor generico de
    siempre."""
    if _metodo_pago_valido(id_usuario):
        return
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.metodos_pago
            (id, id_usuario, tipo, token_tarjeta, marca_tarjeta, ultimos4,
             exp_mes, exp_anio, es_principal, estado)
        VALUES
            (%(id)s, %(id_usuario)s, 'tarjeta', %(token)s, %(marca)s, %(ultimos4)s,
             %(exp_mes)s, %(exp_anio)s, 1, 'activo')
    """, parameters={
        "id": str(uuid.uuid4()), "id_usuario": id_usuario,
        "token": f"sim_{uuid.uuid4().hex[:10]}",
        "marca": marca_tarjeta or "simulada",
        "ultimos4": ultimos4 or "0000",
        "exp_mes": exp_mes or 12,
        "exp_anio": exp_anio or 2099,
    })


def _registrar_periodo(id_usuario: str, *, origen: str) -> str:
    """Cobro simulado real (INSERT en pagos, concepto='membresia') + una
    fila nueva en membresias con 1 periodo de vigencia. Compartida entre
    la activacion/renovacion manual del ciclista y la renovacion
    automatica de Airflow -- un solo camino real de cobro, no
    duplicado."""
    precio = precio_vigente()
    hoy = date.today()
    fin = hoy + timedelta(days=DIAS_PERIODO)

    id_factura = facturas_repo.emitir(
        id_usuario=id_usuario, total=precio, concepto="Membresía mensual",
    )

    id_pago = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.pagos
            (id, id_factura, id_alquiler, id_usuario, metodo, monto, estado, concepto)
        VALUES
            (%(id)s, %(id_factura)s, %(sentinela)s, %(id_usuario)s, 'automatico',
             %(monto)s, 'verificado', 'membresia')
    """, parameters={
        "id": id_pago, "id_factura": id_factura, "sentinela": SENTINELA,
        "id_usuario": id_usuario, "monto": precio,
    })

    id_membresia = str(uuid.uuid4())
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.membresias
            (id, id_usuario, fecha_inicio, fecha_fin, estado, precio, id_pago, origen)
        VALUES
            (%(id)s, %(id_usuario)s, %(inicio)s, %(fin)s, 'activa', %(precio)s, %(id_pago)s, %(origen)s)
    """, parameters={
        "id": id_membresia, "id_usuario": id_usuario, "inicio": hoy, "fin": fin,
        "precio": precio, "id_pago": id_pago, "origen": origen,
    })
    return id_membresia


def activar(
    id_usuario: str, *,
    ultimos4: str | None = None, marca_tarjeta: str | None = None,
    exp_mes: int | None = None, exp_anio: int | None = None,
) -> str:
    """Activacion/renovacion manual desde /ciclista/membresia/pagar. Los
    datos de tarjeta son opcionales -- siguen sin ser necesarios para
    que el cobro simulado funcione (ver _asegurar_metodo_pago); solo
    existen para que el comprobante final se vea con datos reales del
    ciclista en vez del generico de siempre."""
    _asegurar_metodo_pago(
        id_usuario, ultimos4=ultimos4, marca_tarjeta=marca_tarjeta,
        exp_mes=exp_mes, exp_anio=exp_anio,
    )
    return _registrar_periodo(id_usuario, origen="compra")


def procesar_por_vencer_hoy(dias_aviso: int = DIAS_AVISO_VENCIMIENTO) -> dict:
    """Aviso anticipado real (ver docs/Requerimientos_Mejoras_UrbanBike.md
    y docs/HOJA_DE_RUTA.md sección 69): para cada membresía 'activa' cuya
    fecha_fin cae dentro de los próximos `dias_aviso` días (hoy incluido),
    genera una notificación real una sola vez por período -- se guarda
    contra duplicados buscando si ya existe un aviso de este tipo con el
    id de ESTA membresía en el enlace (no solo por usuario: un mismo
    ciclista tiene varios períodos a lo largo del tiempo, y correr esto
    cada hora durante 3 días no debe mandar 72 avisos del mismo período).

    Se corre como 5to paso del mismo DAG horario que ya procesa
    vencidas (ver etl/10_procesar_membresias.py) -- naturalmente
    idempotente por el chequeo de arriba, sin guarda de "ya corrí hoy"
    aparte, mismo criterio que procesar_vencidas_hoy()."""
    hoy = date.today()
    limite = hoy + timedelta(days=dias_aviso)
    filas = ch.query("""
        SELECT id, id_usuario, estado, fecha_fin, fecha_inicio, fecha_registro
        FROM urbanbike_operativa.membresias
        ORDER BY id_usuario, fecha_inicio DESC, fecha_registro DESC
    """)
    ultima_por_usuario: dict[str, dict] = {}
    for f in filas:
        uid = str(f["id_usuario"])
        if uid not in ultima_por_usuario:
            ultima_por_usuario[uid] = f

    por_vencer = [
        f for f in ultima_por_usuario.values()
        if f["estado"] == "activa" and hoy <= f["fecha_fin"] <= limite
    ]

    pb = get_admin_client()
    avisadas = 0
    sin_cuenta_real = 0
    for f in por_vencer:
        id_membresia = str(f["id"])
        ya_avisada = pb.list_records(
            "notificaciones",
            filter=f'tipo = "membresia_por_vencer" && enlace ~ {filter_literal(id_membresia)}',
            per_page=1,
        ).get("totalItems", 0)
        if ya_avisada:
            continue
        resuelto = _resolver_usuario_pocketbase(str(f["id_usuario"]))
        if not resuelto:
            sin_cuenta_real += 1
            continue
        pb_id, nombre = resuelto
        dias_restantes = (f["fecha_fin"] - hoy).days
        notificaciones_repo.notificar_usuario(
            pb, pb_id, tipo="membresia_por_vencer", titulo="Tu membresía está por vencer",
            mensaje=(
                f"Tu membresía vence el {f['fecha_fin'].strftime('%d/%m/%Y')} "
                f"({dias_restantes} día(s)). Renuévala desde Mi Membresía para no perder tus beneficios."
            ),
            enlace=f"/ciclista/membresia?aviso={id_membresia}",
        )
        avisadas += 1

    return {"revisadas": len(por_vencer), "avisadas": avisadas, "sin_cuenta_real": sin_cuenta_real}


def procesar_vencidas_hoy() -> dict:
    """Tarea real diaria (ver etl/10_procesar_membresias.py, cuarto paso
    del DAG horario): para cada ciclista cuya membresia mas reciente
    esta 'activa' pero ya vencio, intenta renovar cobrando su metodo de
    pago simulado principal; si no tiene uno activo, la marca 'vencida'
    sin cobrar nada -- nunca fuerza la renovacion.

    Idempotente de verdad: en cuanto se procesa a un usuario, su fila
    mas reciente deja de cumplir 'activa y vencida' (o pasa a
    'vencida' sin mas vencimiento pendiente, o se renueva con
    fecha_fin en el futuro) -- una segunda corrida el mismo dia no
    vuelve a tocarlo. Tabla chica: se trae completa y se reduce en
    Python, mismo criterio que promociones_repo.activas_hoy()."""
    hoy = date.today()
    filas = ch.query("""
        SELECT id_usuario, estado, fecha_fin, fecha_inicio, fecha_registro
        FROM urbanbike_operativa.membresias
        ORDER BY id_usuario, fecha_inicio DESC, fecha_registro DESC
    """)
    ultima_por_usuario: dict[str, dict] = {}
    for f in filas:
        uid = str(f["id_usuario"])
        if uid not in ultima_por_usuario:
            ultima_por_usuario[uid] = f

    vencidas = [
        (uid, f) for uid, f in ultima_por_usuario.items()
        if f["estado"] == "activa" and f["fecha_fin"] < hoy
    ]

    pb = get_admin_client()
    renovadas = 0
    marcadas_vencidas = 0
    for uid, _ in vencidas:
        if _metodo_pago_valido(uid):
            _registrar_periodo(uid, origen="renovacion_automatica")
            renovadas += 1
        else:
            ch.get_client().command("""
                INSERT INTO urbanbike_operativa.membresias
                    (id, id_usuario, fecha_inicio, fecha_fin, estado, precio, id_pago, origen)
                VALUES
                    (%(id)s, %(id_usuario)s, %(hoy)s, %(hoy)s, 'vencida', 0, %(sentinela)s, 'renovacion_fallida')
            """, parameters={
                "id": str(uuid.uuid4()), "id_usuario": uid, "hoy": hoy, "sentinela": SENTINELA,
            })
            marcadas_vencidas += 1
            # Notificación real de vencimiento (ver docs/HOJA_DE_RUTA.md
            # sección 69) -- solo cuando de verdad queda 'vencida' (sin
            # método de pago para renovar); una renovación automática
            # exitosa no es un evento negativo que amerite avisar.
            resuelto = _resolver_usuario_pocketbase(uid)
            if resuelto:
                pb_id, nombre = resuelto
                notificaciones_repo.notificar_usuario(
                    pb, pb_id, tipo="membresia_vencida", titulo="Tu membresía venció",
                    mensaje="Tu membresía venció y no se pudo renovar automáticamente "
                            "(sin método de pago activo). Renuévala desde Mi Membresía.",
                    enlace="/ciclista/membresia",
                )

    return {"revisadas": len(vencidas), "renovadas": renovadas, "marcadas_vencidas": marcadas_vencidas}


def cancelar(id_usuario: str) -> dict:
    """Cancelacion real desde /ciclista/membresia. El beneficio se quita
    de inmediato: se INSERTa una fila nueva en membresias con
    estado='cancelada' (append-only, nunca un UPDATE -- mismo patron
    que ya usa procesar_vencidas_hoy() para 'vencida') para que
    esta_activa() deje de ver el periodo pagado como vigente en la
    siguiente lectura, sin esperar a que termine fecha_fin.

    Reembolso real (INSERT en pagos, monto negativo,
    concepto='reembolso_membresia') solo si el cobro de ESTE periodo
    (fecha_registro de la fila 'activa' vigente) fue hace
    VENTANA_REEMBOLSO_HORAS o menos. Fuera de esa ventana, se cancela
    sin reembolsar nada -- mismo `precio=0` que ya usa
    'renovacion_fallida' para la fila de cancelacion en si (no es un
    cobro nuevo; el cobro real, si lo hay, vive en pagos)."""
    actual = estado_actual(id_usuario)
    if not actual or actual["estado"] != "activa" or actual["fecha_fin"] < date.today():
        return {"ok": False, "motivo": "No tienes una membresía activa para cancelar."}

    ahora = datetime.now(timezone.utc)
    fecha_cobro = actual["fecha_registro"]
    if fecha_cobro.tzinfo is None:
        fecha_cobro = fecha_cobro.replace(tzinfo=timezone.utc)
    horas_desde_cobro = (ahora - fecha_cobro).total_seconds() / 3600
    reembolsado = horas_desde_cobro <= VENTANA_REEMBOLSO_HORAS

    id_pago_evento = SENTINELA
    if reembolsado:
        id_pago_evento = str(uuid.uuid4())
        ch.get_client().command("""
            INSERT INTO urbanbike_operativa.pagos
                (id, id_factura, id_alquiler, id_usuario, metodo, monto, estado, concepto)
            VALUES
                (%(id)s, %(sentinela)s, %(sentinela)s, %(id_usuario)s, 'automatico',
                 %(monto)s, 'verificado', 'reembolso_membresia')
        """, parameters={
            "id": id_pago_evento, "sentinela": SENTINELA,
            "id_usuario": id_usuario, "monto": -float(actual["precio"]),
        })

    hoy = date.today()
    ch.get_client().command("""
        INSERT INTO urbanbike_operativa.membresias
            (id, id_usuario, fecha_inicio, fecha_fin, estado, precio, id_pago, origen)
        VALUES
            (%(id)s, %(id_usuario)s, %(hoy)s, %(hoy)s, 'cancelada', 0, %(id_pago)s, 'cancelacion')
    """, parameters={
        "id": str(uuid.uuid4()), "id_usuario": id_usuario, "hoy": hoy, "id_pago": id_pago_evento,
    })

    return {
        "ok": True, "reembolsado": reembolsado,
        "monto_reembolsado": float(actual["precio"]) if reembolsado else 0.0,
        "horas_desde_cobro": round(horas_desde_cobro, 1),
    }
