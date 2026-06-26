<!--
Sync Impact Report
==================
Version change: TEMPLATE → 1.0.0 (initial ratification)

Modified principles: N/A (first ratification — all principles newly defined)

Added sections:
- Core Principles I–VII:
  I. Arquitectura Híbrida de Datos (NO NEGOCIABLE)
  II. Backend FastAPI con Renderizado Server-Side
  III. Seguridad por Roles (NO NEGOCIABLE)
  IV. Trazabilidad de Pagos (NO NEGOCIABLE)
  V. Calidad bajo ISO/IEC 25010 e ISO/IEC 29148
  VI. Diseño Orientado a Casos de Uso
  VII. Despliegue Contenedorizado con Docker
- Alcance Operativo y Roles del Sistema (Section 2)
- Flujo de Desarrollo y Puertas de Calidad (Section 3)
- Governance

Removed sections: none (template placeholders replaced)

Templates requiring updates:
- ✅ .specify/templates/plan-template.md — generic "Constitution Check" gate, no hardcoded
  principle names to update; resolves dynamically against this file.
- ✅ .specify/templates/spec-template.md — generic, no constitution-specific references.
- ✅ .specify/templates/tasks-template.md — generic, no constitution-specific references.
- ⚠ .specify/templates/checklist-template.md — not reviewed in depth; no action required
  unless a future amendment adds checklist-specific gates.
- N/A .specify/templates/commands/*.md — directory does not exist in this installation.
- ✅ CLAUDE.md — generic pointer to "current plan", no principle-specific text to update.

Follow-up TODOs: none. Ratification date set to the date of this command's execution since
no prior constitution existed (first adoption, not an amendment of a dated original).
-->

# Constitución de UrbanBike S.A.

UrbanBike S.A. es un sistema de alquiler de bicicletas urbano sostenible operado en
Ecuador (Quito, Guayaquil, Cuenca, Riobamba y Ambato). Esta constitución establece los
principios no negociables que rigen el diseño, la implementación y la operación del
sistema.

## Principios Fundamentales

### I. Arquitectura Híbrida de Datos (NO NEGOCIABLE)

ClickHouse DEBE ser el único almacén para datos analíticos (OLAP): histórico de viajes,
métricas de uso y reportes agregados. PocketBase DEBE ser el único almacén para datos
transaccionales (OLTP): usuarios, reservas, pagos y sesiones activas. Ninguna
funcionalidad puede escribir datos transaccionales en ClickHouse ni datos analíticos en
PocketBase; las responsabilidades de ambos motores NO se mezclan bajo ninguna
circunstancia.

**Razón fundamental**: ClickHouse está optimizado para consultas analíticas sobre grandes
volúmenes históricos, mientras que PocketBase ofrece consistencia transaccional para
operaciones críticas de negocio. Mezclar responsabilidades introduce acoplamiento,
degrada el rendimiento de ambos sistemas y complica la auditoría financiera.

### II. Backend FastAPI con Renderizado Server-Side

El backend DEBE implementarse en Python usando FastAPI. El renderizado de interfaces DEBE
realizarse server-side con Jinja2. NO DEBEN introducirse frameworks frontend pesados
(React, Vue, Angular u otros) salvo que exista una justificación documentada y aprobada
en la sección "Complexity Tracking" del `plan.md` de la funcionalidad correspondiente.

**Razón fundamental**: Mantener un stack server-side reduce la superficie de complejidad
operativa, facilita el mantenimiento por un equipo pequeño y evita la duplicación de
lógica de negocio entre cliente y servidor.

### III. Seguridad por Roles (NO NEGOCIABLE)

Todo endpoint DEBE validar el rol del usuario autenticado antes de ejecutar cualquier
lógica de negocio. Los roles reconocidos son: Administrador, Gerente, Ciclista, Empleado
de Operación, Empleado de Mantenimiento y Empleado de Vigilancia. Ninguna funcionalidad,
vista o endpoint puede exponerse sin verificación explícita del rol correspondiente; el
control de acceso NO DEBE delegarse únicamente al frontend.

**Razón fundamental**: El sistema atiende a múltiples tipos de actores con permisos
distintos sobre operaciones financieras y físicas (bicicletas, estaciones); omitir la
validación de rol habilita escalamiento de privilegios y accesos no autorizados.

### IV. Trazabilidad de Pagos (NO NEGOCIABLE)

Todo pago registrado (efectivo, tarjeta o transferencia) DEBE generar un comprobante y
quedar auditado. Ningún pago puede registrarse sin estar asociado a un viaje o una
reserva existente. Los registros de auditoría de pagos NO DEBEN ser editables ni
eliminables tras su creación.

**Razón fundamental**: La integridad financiera del sistema depende de poder reconstruir,
ante cualquier auditoría o reclamo, el origen y destino de cada transacción.

### V. Calidad bajo ISO/IEC 25010 e ISO/IEC 29148

Toda especificación de requisitos DEBE ser verificable, no ambigua y trazable a un caso
de uso documentado, conforme a ISO/IEC 29148. La calidad del producto DEBE evaluarse
según las características de ISO/IEC 25010 (funcionalidad, fiabilidad, usabilidad,
eficiencia de desempeño, seguridad, compatibilidad, mantenibilidad y portabilidad). Las
especificaciones que no puedan verificarse objetivamente DEBEN marcarse como `NEEDS
CLARIFICATION` antes de avanzar a planificación.

**Razón fundamental**: Estandarizar la calidad bajo normas internacionales reconocidas
permite auditorías externas y evita decisiones de diseño basadas en criterios subjetivos.

### VI. Diseño Orientado a Casos de Uso

Ninguna funcionalidad se implementa sin haber sido descrita primero como caso de uso,
identificando su nivel (operativo, táctico o estratégico), el actor responsable y el
objetivo de negocio que persigue. El `spec.md` de cada feature DEBE referenciar
explícitamente el caso de uso que la origina.

**Razón fundamental**: Anclar cada funcionalidad a un caso de uso evita el desarrollo
especulativo de características sin valor de negocio verificado y facilita la
trazabilidad entre requisitos y código.

### VII. Despliegue Contenedorizado con Docker

Todos los entornos (desarrollo, pruebas y producción) DEBEN ejecutarse mediante Docker y
Docker Compose. Las dependencias de ClickHouse, PocketBase y el backend FastAPI DEBEN
definirse como servicios contenedorizados versionados en el repositorio.

**Razón fundamental**: Garantiza reproducibilidad del entorno entre los equipos de
desarrollo y los despliegues en las distintas ciudades de operación, eliminando
inconsistencias de configuración.

## Alcance Operativo y Roles del Sistema

UrbanBike S.A. opera en las ciudades de Quito, Guayaquil, Cuenca, Riobamba y Ambato. Cada
ciudad puede tener estaciones, flotas de bicicletas y personal de operación,
mantenimiento y vigilancia propios, pero el sistema DEBE compartir el mismo modelo de
datos y la misma base de código entre ciudades; las diferencias entre ciudades se
modelan como datos (estaciones, tarifas, zonas), no como bifurcaciones de código.

Los seis roles del sistema (Administrador, Gerente, Ciclista, Empleado de Operación,
Empleado de Mantenimiento, Empleado de Vigilancia) DEBEN estar definidos como una
enumeración central reutilizada por todos los endpoints y vistas. Cualquier rol nuevo
requiere una enmienda de esta constitución (ver Gobernanza).

## Flujo de Desarrollo y Puertas de Calidad

El desarrollo de toda funcionalidad sigue el flujo Spec-Driven: `/speckit-specify` →
`/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` → `/speckit-analyze` →
`/speckit-implement`. La puerta "Constitution Check" del `plan.md` DEBE evaluarse
explícitamente contra los siete principios de esta constitución antes de iniciar la Fase
0 y debe re-verificarse tras el diseño de la Fase 1.

Toda revisión de código (humana o automatizada) DEBE confirmar: (a) que los endpoints
nuevos o modificados validan el rol correspondiente (Principio III), (b) que cualquier
flujo de pago genera comprobante y queda auditado (Principio IV), y (c) que no se
mezclan responsabilidades de ClickHouse y PocketBase (Principio I). Cualquier violación
detectada DEBE documentarse en la tabla "Complexity Tracking" del plan o corregirse antes
de la fusión del código.

## Gobernanza

Esta constitución prevalece sobre cualquier otra práctica, plantilla o preferencia
individual del equipo. Toda enmienda DEBE documentarse con: la razón del cambio, el
principio afectado y el nuevo número de versión, siguiendo versionado semántico:

- **MAYOR**: eliminación o redefinición incompatible de un principio existente (p. ej.,
  abandonar la arquitectura híbrida ClickHouse/PocketBase).
- **MENOR**: adición de un nuevo principio o expansión material de una guía existente.
- **PATCH**: aclaraciones de redacción, correcciones tipográficas o ajustes no
  semánticos.

Toda Pull Request o revisión DEBE verificar cumplimiento con los principios aquí
descritos antes de aprobarse. Las desviaciones DEBEN justificarse explícitamente en la
sección "Complexity Tracking" del `plan.md` correspondiente. Esta constitución se revisa
como mínimo en cada ejecución de `/speckit-plan`, mediante la puerta "Constitution
Check".

**Version**: 1.0.0 | **Ratified**: 2026-06-20 | **Last Amended**: 2026-06-20
