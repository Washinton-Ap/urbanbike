# Guía de uso por rol (punto 1.9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un apartado de ayuda dentro del sistema ("qué puedo hacer, cómo, qué no debo hacer") específico para cada uno de los 6 roles (Admin, Gerente, Ciclista, Empleado-Operación, Empleado-Mantenimiento, Empleado-Vigilancia), accesible desde un enlace nuevo en el sidebar.

**Architecture:** Una sola ruta compartida `GET /guia` en `app/main.py` (mismo patrón que `/dashboard`, `/perfil` y `/notificaciones`, que ya viven ahí sin prefijo de rol porque son comunes a cualquier usuario autenticado — no necesitan entrada nueva en `ROLE_RULES` de `app/middleware/auth.py`). El contenido (qué puedo hacer / cómo / qué no debo hacer) vive en un diccionario Python nuevo, `app/guia_contenido.py`, indexado por `rol_slug`, con enlaces reales a rutas que ya existen hoy (auditadas una por una en `app/routers/admin.py`, `gerente.py`, `ciclista.py`, `empleado.py`). Una sola plantilla `app/templates/guia.html` reutiliza las clases `.card`/`.card-header`/`.card-title`/`.badge-red` ya definidas en `app/static/css/main.css` (mismo patrón visual que `app/templates/institucional/mision_vision.html`). El enlace nuevo se agrega una sola vez en la sección compartida "Cuenta" de `app/templates/base.html` (junto a "Mi Perfil"), no en cada bloque de rol — evita repetir 6 veces el mismo `<a>` y no toca la campana de notificaciones ni ninguna otra sección del sidebar.

**Tech Stack:** FastAPI + Jinja2 (patrón ya usado en todo `app/`), sin JS ni CSS nuevos.

**Spec:** `docs/Plan_Mejoras_UrbanBike_V2.md` sección "PRIORIDAD 1", punto 1.9 (texto completo: *"Guía de uso por rol ('qué puedo hacer, cómo, qué no debo hacer'). Un apartado de ayuda dentro del sistema, específico para cada tipo de usuario, para reducir confusión y errores de uso — sobre todo mencionado para Operación, Mantenimiento y Vigilancia."*)

## Global Constraints

- Nombres de archivos, variables y contenido de UI en español (excepto `ride_id`, que no aplica aquí).
- Type hints en todo código Python nuevo.
- Colores/tipografía ya establecidos: `#1E86BD`, Sora (títulos) + IBM Plex Sans (cuerpo), sin Inter ni gradientes morados — se logra reutilizando `.card`/`var(--primary)`/`var(--text-muted)`, no CSS nuevo.
- No inventar funcionalidad que el sistema no tiene hoy: cada enlace de "qué puedo hacer" apunta a una ruta real, verificada por grep contra `app/routers/*.py` (ver lista completa en la sección "Rutas auditadas por rol" más abajo).
- El acceso de Gerente, Empleado-Operación, Empleado-Mantenimiento y Empleado-Vigilancia a Bicicletas/Estaciones/Tarifas/Promociones/Alquileres/Órdenes depende de permisos finos (`Depends(requiere_permiso(...))`), NO es automático por tener el rol — el contenido de la guía debe reflejar eso explícitamente, no prometer acceso incondicional.
- Servidor de verificación en el puerto **8015** exclusivamente (`python scripts/dev_reload.py 8015`), nunca 8002/8011/8012/8013/8014.
- Credenciales de prueba reales (de `docs/HOJA_DE_RUTA.md`, contraseña común `Urbanbike123!`): `admin@urbanbike.com`, `gerente@urbanbike.com`, `ciclista@urbanbike.com`, `empleado@urbanbike.com` (Operación), `empleado.mant@urbanbike.com` (Mantenimiento), `empleado.vig@urbanbike.com` (Vigilancia).

## Rutas auditadas por rol (fuente de verdad para el contenido de la guía)

**Admin** (`app/routers/admin.py`, prefijo `/admin`, además accede a TODO lo de Gerente y de los 3 Empleado vía `ROLE_RULES`): `/admin/usuarios`, `/admin/bitacora`, `/admin/auditoria`, `/admin/permisos`, `/admin/permisos-usuario`, `/admin/reportes`, `/admin/respaldo`, `/admin/soporte`.

**Gerente** (`app/routers/gerente.py`, prefijo `/gerente`): `/gerente/dashboard`, `/gerente/analisis-citibike`, `/gerente/reportes`, `/gerente/reportes/pagos`, `/gerente/informe`, `/gerente/estrategico`, `/gerente/empleados` (crear/cambiar-rol/bloquear/reactivar), `/gerente/bicicletas`, `/gerente/estaciones`, `/gerente/tarifas`, `/gerente/promociones` (estas 4 últimas gated por `requiere_permiso`), `/institucional/mision-vision`.

**Ciclista** (`app/routers/ciclista.py`, prefijo `/ciclista`): `/ciclista/catalogo`, `/ciclista/alquilar` (incluye reserva individual y grupal 3+ con descuento), `/ciclista/viaje-activo`, `/ciclista/historial`, `/ciclista/pagos`, `/ciclista/membresia` (activar/cancelar/pagar), `/ciclista/promociones`, `/ciclista/infracciones`, `/ciclista/reportes`, `/ciclista/soporte`.

**Empleado-Operación** (`app/routers/empleado.py`, prefijo `/empleado/operacion`): `/empleado/operacion/dashboard`, `/empleado/operacion/inventario` (leer/crear/editar/eliminar gated por `requiere_permiso("bicicletas:*")`), `/empleado/operacion/alquileres` (gated por `requiere_permiso("alquileres:*")`), `/empleado/operacion/rebalanceo`, `/empleado/operacion/pagos` (cobrar presencial, confirmar efectivo, aprobar/rechazar transferencia), `/empleado/operacion/reportes`.

**Empleado-Mantenimiento** (prefijo `/empleado/mantenimiento`, más la excepción `INVENTARIO_PREFIX` que le da acceso de lectura a `/empleado/operacion/inventario`): `/empleado/mantenimiento/dashboard`, `/empleado/mantenimiento/ordenes` (gated por `requiere_permiso("ordenes_mantenimiento:*")`), `/empleado/mantenimiento/bicicletas`, `/empleado/mantenimiento/reportes`.

**Empleado-Vigilancia** (prefijo `/empleado/vigilancia`, más la misma excepción de inventario): `/empleado/vigilancia/dashboard`, `/empleado/vigilancia/seguimiento`, `/empleado/vigilancia/devoluciones` (checklist real de inspección), `/empleado/vigilancia/infracciones`, `/empleado/vigilancia/mantenimiento/cerrar` (certificar orden de mantenimiento), `/empleado/vigilancia/alertas`, `/empleado/vigilancia/soporte`, `/empleado/vigilancia/reportes`.

**Mecanismo de protección de `/guia`:** al no tener prefijo en `ROLE_RULES` (`app/middleware/auth.py`), queda accesible a cualquier usuario autenticado, exactamente igual que `/dashboard`, `/perfil` y `/notificaciones` — no requiere ninguna entrada nueva en `ROLE_RULES`.

---

### Task 1: Contenido de la guía por rol (`app/guia_contenido.py`)

**Files:**
- Create: `app/guia_contenido.py`

**Interfaces:**
- Produces: `GUIA: dict[str, dict]` — clave `rol_slug` (los 6 valores reales de `user["rol_slug"]`: `"admin"`, `"gerente"`, `"ciclista"`, `"empleado-operacion"`, `"empleado-mantenimiento"`, `"empleado-vigilancia"`). Cada valor es un `dict` con claves `titulo: str`, `resumen: str`, `puedo: list[dict]` (cada item `{"titulo": str, "descripcion": str, "enlace": str}`), `como: list[str]`, `no_debo: list[str]`.
- Consumido por: Task 2 (`app/main.py`, ruta `GET /guia`).

- [ ] **Step 1: Escribir `app/guia_contenido.py` completo**

```python
"""Contenido de la guía de uso por rol (punto 1.9 del Plan de Mejoras V2).

Cada entrada resume, para el rol_slug correspondiente, qué puede hacer hoy
ese rol en el sistema (con enlace real a la pantalla), cómo usar los flujos
más propensos a error, y qué no debe hacer -- auditado contra las rutas
reales de app/routers/*.py (ver docs/superpowers/plans/2026-08-20-guia-de-uso-por-rol.md,
sección "Rutas auditadas por rol"), no inventado. Los enlaces a Bicicletas/
Estaciones/Tarifas/Promociones/Alquileres/Órdenes se marcan como
"según tus permisos" porque dependen de requiere_permiso() -- no son
automáticos por tener el rol (ver app/middleware/permisos.py)."""

from __future__ import annotations

GUIA: dict[str, dict] = {
    "admin": {
        "titulo": "Guía de uso — Administrador",
        "resumen": (
            "Como Admin tienes acceso a todo el sistema: la gestión "
            "operativa de cada rol (Gerente, Operación, Mantenimiento, "
            "Vigilancia) y el panel de administración global."
        ),
        "puedo": [
            {"titulo": "Gestionar usuarios y sus roles", "descripcion": "Crear cuentas, cambiar rol, cerrar sesión de un usuario conectado o eliminar una cuenta.", "enlace": "/admin/usuarios"},
            {"titulo": "Revisar la bitácora del sistema", "descripcion": "Historial de acciones relevantes de todos los roles.", "enlace": "/admin/bitacora"},
            {"titulo": "Auditar cambios sensibles", "descripcion": "Permisos, tarifas, respaldos y otras acciones de alto impacto.", "enlace": "/admin/auditoria"},
            {"titulo": "Configurar Roles y Permisos", "descripcion": "El mapa de permisos finos que usan Gerente y los 3 roles de Empleado.", "enlace": "/admin/permisos"},
            {"titulo": "Otorgar excepciones por usuario", "descripcion": "Un permiso puntual para una persona, sin cambiarle el rol completo.", "enlace": "/admin/permisos-usuario"},
            {"titulo": "Exportar reportes y respaldos", "descripcion": "Reportes generales del sistema y respaldo de la base de datos.", "enlace": "/admin/reportes"},
            {"titulo": "Atender soporte de ciclistas", "descripcion": "Chat interno de soporte con cualquier ciclista.", "enlace": "/admin/soporte"},
            {"titulo": "Entrar a cualquier panel de rol", "descripcion": "Gerente y los 3 paneles de Empleado (Operación, Mantenimiento, Vigilancia), con las mismas pantallas que ese rol.", "enlace": "/gerente/dashboard"},
        ],
        "como": [
            "Antes de cambiarle el rol a alguien, revisa su Bitácora para no perder contexto de lo que hizo con el rol anterior.",
            "Usa \"Excepciones por Usuario\" solo para casos puntuales; para un cambio permanente de un rol completo, edita el rol en \"Roles y Permisos\".",
            "Antes de eliminar una cuenta, evalúa si \"Cerrar sesión\" (sin eliminarla) ya resuelve el problema real.",
        ],
        "no_debo": [
            "No otorgar permisos de eliminar (*:eliminar) sin confirmar que la persona entiende que esa acción no tiene deshacer real.",
            "No editar tarifas ni promociones activas sin avisar a Gerente, aunque el sistema no te lo impida.",
            "No usar tu acceso a paneles de Empleado para saltarte el flujo real (por ejemplo, confirmar un pago en efectivo sin haberlo cobrado de verdad).",
        ],
    },
    "gerente": {
        "titulo": "Guía de uso — Gerente",
        "resumen": (
            "Acceso de lectura a la analítica del negocio (ClickHouse) y "
            "gestión configurable de empleados, bicicletas, estaciones, "
            "tarifas y promociones, según los permisos que Admin te asigne."
        ),
        "puedo": [
            {"titulo": "Ver los KPIs generales", "descripcion": "Dashboard analítico con datos reales de ClickHouse.", "enlace": "/gerente/dashboard"},
            {"titulo": "Explorar el dataset académico Citibike", "descripcion": "Análisis de los 3.7M de viajes de Nueva York, octubre 2023.", "enlace": "/gerente/analisis-citibike"},
            {"titulo": "Generar reportes operativos y de pagos", "descripcion": "Exportables a Excel/PDF.", "enlace": "/gerente/reportes"},
            {"titulo": "Leer el Informe y el Informe Estratégico", "descripcion": "Resumen ejecutivo y de fondo, no solo el día a día.", "enlace": "/gerente/informe"},
            {"titulo": "Gestionar empleados", "descripcion": "Crear cuentas, cambiar de rol, bloquear o reactivar.", "enlace": "/gerente/empleados"},
            {"titulo": "Administrar Bicicletas, Estaciones, Tarifas y Promociones", "descripcion": "Solo si Admin te dio el permiso fino correspondiente.", "enlace": "/gerente/bicicletas"},
            {"titulo": "Leer la Misión y Visión institucional", "descripcion": "Apartado compartido con los 3 roles de Empleado.", "enlace": "/institucional/mision-vision"},
        ],
        "como": [
            "Si un enlace de Bicicletas/Estaciones/Tarifas/Promociones te da error de \"sin permisos\", es porque Admin no activó ese permiso fino para tu cuenta -- pídeselo, no es un error del sistema.",
            "Antes de bloquear a un empleado, evalúa si el problema es puntual (mejor una excepción de permiso vía Admin) o de verdad requiere el bloqueo completo.",
            "Usa el Informe Estratégico para decisiones de fondo; el dashboard de KPIs es para el seguimiento del día a día.",
        ],
        "no_debo": [
            "No cambiar el rol de un empleado sin avisarle -- pierde acceso a su panel actual de inmediato.",
            "No editar una tarifa vigente sin considerar los alquileres que ya se reservaron con el precio anterior.",
            "No asumir acceso total: tu rol depende de permisos finos, no es igual al de Admin.",
        ],
    },
    "ciclista": {
        "titulo": "Guía de uso — Ciclista",
        "resumen": "Para reservar bicicletas, pagar y llevar el control de tus viajes y tu membresía.",
        "puedo": [
            {"titulo": "Ver el catálogo de bicicletas", "descripcion": "Disponibilidad y precio por categoría (member vs. casual).", "enlace": "/ciclista/catalogo"},
            {"titulo": "Reservar una bicicleta", "descripcion": "Individual, o en grupo de 3+ con descuento automático.", "enlace": "/ciclista/alquilar"},
            {"titulo": "Seguir y finalizar tu viaje activo", "descripcion": "Confirmar el pago cuando termines.", "enlace": "/ciclista/viaje-activo"},
            {"titulo": "Revisar tu historial de viajes y pagos", "descripcion": "Con comprobantes descargables.", "enlace": "/ciclista/historial"},
            {"titulo": "Activar, pagar o cancelar tu membresía", "descripcion": "Precio con membresía activa es menor al de \"casual\".", "enlace": "/ciclista/membresia"},
            {"titulo": "Ver promociones vigentes", "descripcion": "Códigos de descuento aplicables.", "enlace": "/ciclista/promociones"},
            {"titulo": "Revisar tus infracciones", "descripcion": "Historial de incidencias registradas a tu cuenta.", "enlace": "/ciclista/infracciones"},
            {"titulo": "Escribir a soporte", "descripcion": "Chat interno si algo falla con tu viaje o tu pago.", "enlace": "/ciclista/soporte"},
        ],
        "como": [
            "Revisa el catálogo antes de reservar: el precio con membresía activa es menor al de \"casual\" para la misma bicicleta.",
            "Al reservar en grupo (3 o más bicicletas), el código de descuento del 15% se genera automático -- no hace falta pedirlo.",
            "Paga a tiempo: una membresía o un pago vencido puede bloquear tu cuenta hasta que regularices.",
        ],
        "no_debo": [
            "No exceder el tiempo de viaje reservado sin pagar la diferencia -- puede generar una infracción.",
            "No devolver la bicicleta en una estación distinta a la indicada sin confirmarlo primero -- queda \"pendiente de validación\" hasta que Vigilancia la revise.",
            "No ignorar una notificación de infracción: se acumulan y pueden bloquear tu cuenta.",
        ],
    },
    "empleado-operacion": {
        "titulo": "Guía de uso — Operación",
        "resumen": "Gestión del día a día de bicicletas, alquileres y cobros en tu estación.",
        "puedo": [
            {"titulo": "Ver el estado general del turno", "descripcion": "Resumen operativo del día.", "enlace": "/empleado/operacion/dashboard"},
            {"titulo": "Consultar y actualizar el inventario", "descripcion": "Crear/editar/eliminar bicicletas, según tus permisos.", "enlace": "/empleado/operacion/inventario"},
            {"titulo": "Gestionar alquileres", "descripcion": "Crear, cancelar y completar, según tus permisos.", "enlace": "/empleado/operacion/alquileres"},
            {"titulo": "Rebalancear bicicletas entre estaciones", "descripcion": "Trasladar unidades donde hacen falta.", "enlace": "/empleado/operacion/rebalanceo"},
            {"titulo": "Cobrar y confirmar pagos", "descripcion": "Presenciales, por transferencia (aprobar/rechazar) o en efectivo.", "enlace": "/empleado/operacion/pagos"},
            {"titulo": "Descargar reportes de tu operación", "descripcion": "Exportables a Excel/PDF.", "enlace": "/empleado/operacion/reportes"},
        ],
        "como": [
            "Antes de confirmar un pago en efectivo, verifica que el dinero ya está en tu poder -- esa acción queda registrada en bitácora.",
            "Si necesitas crear, editar o eliminar bicicletas o alquileres y no puedes, es un permiso fino que solo Admin/Gerente activan -- pídelo, no lo fuerces.",
            "Usa Rebalanceo cuando una estación está saturada o vacía, no como sustituto de una reserva normal.",
        ],
        "no_debo": [
            "No confirmar una transferencia sin revisar el comprobante real.",
            "No completar un alquiler que sigue con la bicicleta fuera de la estación.",
            "No editar el inventario de una bicicleta que está en curso de un viaje activo.",
        ],
    },
    "empleado-mantenimiento": {
        "titulo": "Guía de uso — Mantenimiento",
        "resumen": "Órdenes de trabajo y estado técnico de la flota.",
        "puedo": [
            {"titulo": "Ver el resumen de tu turno", "descripcion": "Órdenes pendientes y bicicletas por revisar.", "enlace": "/empleado/mantenimiento/dashboard"},
            {"titulo": "Crear, editar y cerrar órdenes de trabajo", "descripcion": "Según los permisos de ordenes_mantenimiento que tengas.", "enlace": "/empleado/mantenimiento/ordenes"},
            {"titulo": "Consultar el inventario de bicicletas", "descripcion": "Lectura siempre; escritura solo si tienes el permiso.", "enlace": "/empleado/mantenimiento/bicicletas"},
            {"titulo": "Descargar tus reportes de mantenimiento", "descripcion": "Exportables a Excel/PDF.", "enlace": "/empleado/mantenimiento/reportes"},
        ],
        "como": [
            "Cierra una orden de trabajo solo cuando la reparación está terminada de verdad -- Vigilancia certifica después con una inspección real antes de que la bicicleta vuelva a \"disponible\".",
            "Si una bicicleta necesita quedar fuera de servicio, cámbiale el estado en el inventario apenas la recibas, no al final del turno.",
            "Documenta en la orden qué se hizo, no solo que \"se resolvió\" -- ese texto es lo que Vigilancia revisa al certificar.",
        ],
        "no_debo": [
            "No cerrar una orden sin haber probado la reparación.",
            "No dejar una bicicleta marcada como \"disponible\" mientras sigue en tu taller.",
            "No editar el inventario de bicicletas de otra estación sin coordinarlo con Operación.",
        ],
    },
    "empleado-vigilancia": {
        "titulo": "Guía de uso — Vigilancia",
        "resumen": "Monitoreo en tiempo real, devoluciones, infracciones y certificación de mantenimiento.",
        "puedo": [
            {"titulo": "Ver el panorama en vivo de tu turno", "descripcion": "Viajes activos y alertas.", "enlace": "/empleado/vigilancia/dashboard"},
            {"titulo": "Consultar el inventario de bicicletas", "descripcion": "Acceso de lectura, igual que Mantenimiento.", "enlace": "/empleado/operacion/inventario"},
            {"titulo": "Dar seguimiento a los viajes activos", "descripcion": "Ubicación y tiempo transcurrido.", "enlace": "/empleado/vigilancia/seguimiento"},
            {"titulo": "Inspeccionar y registrar devoluciones", "descripcion": "Checklist real de la bicicleta (llantas, frenos, batería si aplica).", "enlace": "/empleado/vigilancia/devoluciones"},
            {"titulo": "Resolver infracciones reportadas", "descripcion": "Revisar y cerrar incidencias de ciclistas.", "enlace": "/empleado/vigilancia/infracciones"},
            {"titulo": "Certificar mantenimiento", "descripcion": "Segunda inspección antes de reactivar una bicicleta reparada.", "enlace": "/empleado/vigilancia/mantenimiento/cerrar"},
            {"titulo": "Atender alertas", "descripcion": "Viajes con algún problema detectado.", "enlace": "/empleado/vigilancia/alertas"},
            {"titulo": "Responder soporte de ciclistas", "descripcion": "Chat interno con cualquier ciclista.", "enlace": "/empleado/vigilancia/soporte"},
        ],
        "como": [
            "Al recibir una devolución, completa el checklist real antes de cerrarla -- de ahí sale una infracción si algo no está bien.",
            "No certifiques una orden de mantenimiento solo por la palabra de Mantenimiento -- la certificación existe justo para una segunda inspección real.",
            "Revisa Alertas con frecuencia: un viaje activo demasiado tiempo suele ser el primer síntoma de un problema.",
        ],
        "no_debo": [
            "No certificar una orden de mantenimiento sin inspeccionar la bicicleta en persona.",
            "No cerrar una devolución sin revisar el checklist completo.",
            "No resolver una infracción sin revisar el historial del ciclista involucrado.",
        ],
    },
}
```

- [ ] **Step 2: Verificar que el módulo importa sin errores**

Run: `cd "C:\Users\Washington Apunte\Desktop\urbanbike\.claude\worktrees\plan-mejoras-v2-p1-g3" && python -c "from app.guia_contenido import GUIA; assert set(GUIA) == {'admin','gerente','ciclista','empleado-operacion','empleado-mantenimiento','empleado-vigilancia'}; print('OK', len(GUIA))"`
Expected: `OK 6`

- [ ] **Step 3: Commit**

```bash
git add app/guia_contenido.py
git commit -m "feat: contenido de la guia de uso por rol (punto 1.9)"
```

---

### Task 2: Ruta compartida `GET /guia` + plantilla

**Files:**
- Modify: `app/main.py` (agregar ruta, junto a `/dashboard`/`/perfil`, después de la sección "Campana de notificaciones")
- Create: `app/templates/guia.html`

**Interfaces:**
- Consumes: `GUIA` de `app/guia_contenido.py` (Task 1).
- Produces: endpoint `GET /guia` (HTML), accesible a cualquier `request.state.user` autenticado, sin necesitar cambios en `ROLE_RULES`.

- [ ] **Step 1: Agregar el import y la ruta en `app/main.py`**

Agregar el import junto a los demás de `app/routers` (línea ~24, después de `institucional_router`):

```python
from app.guia_contenido import GUIA
```

Agregar la ruta al final de `app/main.py`, después del bloque de `/notificaciones` (después de la función `notificaciones_marcar_todas`, línea ~315):

```python
# ── Guía de uso por rol (punto 1.9) -- mismo patrón que /dashboard y
# /perfil de arriba: ruta compartida sin prefijo de rol, el contenido
# varía según user["rol_slug"] (ver app/guia_contenido.py) ────────────────

@app.get("/guia", response_class=HTMLResponse)
def guia(request: Request):
    user = request.state.user
    rol = user.get("rol_slug", "")
    contenido = GUIA.get(rol)
    return templates.TemplateResponse(request, "guia.html", {
        "user": user, "title": "Guía de uso",
        "contenido": contenido,
    })
```

- [ ] **Step 2: Escribir `app/templates/guia.html`**

```html
{% extends "base.html" %}
{% block title %}Guía de uso{% endblock %}
{% block page_title %}Guía de uso{% endblock %}
{% block back_url %}{% endblock %}

{% block content %}

{% if not contenido %}
<div class="card">
  <p style="color:var(--text-muted);margin:0;">
    Todavía no hay una guía específica para tu rol. Escribe a soporte si crees que esto es un error.
  </p>
</div>
{% else %}

<div class="card" style="border-top:3px solid var(--primary);margin-bottom:18px;">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">
    <div style="width:40px;height:40px;border-radius:10px;background:var(--primary-light);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
    </div>
    <span style="font-family:'Sora',sans-serif;font-weight:700;font-size:1.1rem;color:var(--text);">{{ contenido.titulo }}</span>
  </div>
  <p style="color:var(--text-muted);line-height:1.7;font-size:0.92rem;margin:0;">{{ contenido.resumen }}</p>
</div>

<div class="card" style="margin-bottom:18px;">
  <div class="card-header"><span class="card-title">Qué puedo hacer</span></div>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;padding:0 20px 20px;">
    {% for item in contenido.puedo %}
    <a href="{{ item.enlace }}" style="text-decoration:none;color:inherit;display:block;padding:14px;border:1px solid var(--border);border-radius:var(--radius);transition:border-color var(--transition);">
      <div style="font-family:'Sora',sans-serif;font-weight:700;font-size:0.9rem;color:var(--text);margin-bottom:4px;">{{ item.titulo }}</div>
      <div style="font-size:0.82rem;color:var(--text-muted);line-height:1.5;">{{ item.descripcion }}</div>
    </a>
    {% endfor %}
  </div>
</div>

<div class="card" style="margin-bottom:18px;">
  <div class="card-header"><span class="card-title">Cómo hacerlo bien</span></div>
  <ul style="margin:0;padding:0 20px 16px 38px;color:var(--text-muted);font-size:0.88rem;line-height:1.8;">
    {% for tip in contenido.como %}
    <li>{{ tip }}</li>
    {% endfor %}
  </ul>
</div>

<div class="card">
  <div class="card-header"><span class="card-title">Qué no debo hacer</span></div>
  <div style="padding:0 20px 20px;display:flex;flex-direction:column;gap:8px;">
    {% for aviso in contenido.no_debo %}
    <div class="badge badge-red" style="display:block;white-space:normal;text-align:left;line-height:1.5;padding:10px 12px;">{{ aviso }}</div>
    {% endfor %}
  </div>
</div>

{% endif %}

{% endblock %}
```

- [ ] **Step 3: Levantar el servidor de verificación en el puerto 8015**

Run (en background, desde el worktree): `python scripts/dev_reload.py 8015`

- [ ] **Step 4: Verificación real vía HTTP con sesión de `admin@urbanbike.com`**

Usar `requests.Session()` en Python (o `curl -c`/`-b` con cookie jar) contra `http://localhost:8015`:
1. `POST /auth/login` con `email=admin@urbanbike.com`, `password=Urbanbike123!` -- confirmar redirect 302 a `/dashboard` (login correcto).
2. `GET /guia` con la misma sesión -- confirmar `200` y que el HTML contiene `"Guía de uso — Administrador"` y al menos un enlace `href="/admin/usuarios"`.

Expected: ambos pasos devuelven lo esperado, sin excepción ni 500.

- [ ] **Step 5: Commit**

```bash
git add app/main.py app/templates/guia.html
git commit -m "feat: ruta y plantilla compartidas para la guia de uso por rol"
```

---

### Task 3: Enlace "Guía de uso" en el sidebar compartido

**Files:**
- Modify: `app/templates/base.html:372-379` (sección `<!-- Perfil (todos los roles) -->`, dentro de `{% if user %}`)

**Interfaces:**
- Consumes: ruta `/guia` (Task 2).
- No produce interfaz nueva -- es el punto de entrada visible.

- [ ] **Step 1: Editar `app/templates/base.html`**

Reemplazar el bloque actual (líneas 372-379):

```html
      <!-- Perfil (todos los roles) -->
      {% if user %}
        <div class="sidebar-section">Cuenta</div>
        <a class="nav-item {% if '/perfil' in p %}active{% endif %}" href="/perfil">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Mi Perfil
        </a>
      {% endif %}
```

por (agrega el enlace de Guía de uso, mismo bloque, sin tocar nada más del archivo):

```html
      <!-- Perfil y Guía de uso (todos los roles) -->
      {% if user %}
        <div class="sidebar-section">Cuenta</div>
        <a class="nav-item {% if '/perfil' in p %}active{% endif %}" href="/perfil">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          Mi Perfil
        </a>
        <a class="nav-item {% if p == '/guia' %}active{% endif %}" href="/guia">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          Guía de uso
        </a>
      {% endif %}
```

- [ ] **Step 2: Verificación real con los 6 roles de prueba**

Con el servidor del puerto 8015 corriendo, para cada una de las 6 cuentas (`admin@urbanbike.com`, `gerente@urbanbike.com`, `ciclista@urbanbike.com`, `empleado@urbanbike.com`, `empleado.mant@urbanbike.com`, `empleado.vig@urbanbike.com`, todas con password `Urbanbike123!`):
1. Login real (`POST /auth/login`).
2. `GET` de su dashboard real (ej. `/gerente/dashboard`) -- confirmar que el HTML de respuesta contiene `href="/guia"` y el texto `Guía de uso` en el sidebar.
3. `GET /guia` -- confirmar `200` y que el `<h1>`/título coincide con el rol logueado (ej. Vigilancia ve "Guía de uso — Vigilancia", no la de otro rol).
4. Confirmar que el resto del sidebar de ese rol sigue intacto (mismos enlaces que antes, ningún `nav-item` roto ni duplicado) -- comparar contra la lista de enlaces por rol documentada arriba en "Rutas auditadas por rol".

Expected: los 6 roles ven el enlace, cada uno cae en su propio contenido, y ningún otro enlace del sidebar cambió.

- [ ] **Step 3: Commit**

```bash
git add app/templates/base.html
git commit -m "feat: enlace Guia de uso en el sidebar compartido de todos los roles"
```

---

### Task 4: Revisión final de rama

- [ ] **Step 1: Invocar al revisor independiente** (skill `superpowers:requesting-code-review` / agente `code-review`) sobre el diff completo de la rama `worktree-plan-mejoras-v2-p1-g3` contra `main`, con foco en: contenido de la guía fiel a las rutas reales (sin funcionalidad inventada), que `/guia` no quede accesible sin sesión, que el nuevo `<a>` en `base.html` no rompa el nav existente de ningún rol, y estilo consistente con el resto del sistema (sin Inter, sin gradientes morados).
- [ ] **Step 2: Si el revisor pide cambios, aplicarlos y volver a pedir revisión** antes de reportar la tarea como cerrada.
- [ ] **Step 3: Reportar a "main" vía SendMessage** con el commit final, la evidencia de los 6 logins reales, y el veredicto del revisor -- sin marcar la tarea completa si falta cualquiera de las dos cosas.
