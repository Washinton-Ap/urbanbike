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
