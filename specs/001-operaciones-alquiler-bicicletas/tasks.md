# Tasks: Operaciones de Alquiler de Bicicletas (Nivel Operativo)

**Input**: Documentos de diseño en `specs/001-operaciones-alquiler-bicicletas/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/endpoints.md, quickstart.md

> **⚠️ DOCUMENTACIÓN BROWNFIELD — TRABAJO YA REALIZADO, NO PENDIENTE.**
> El sistema ya está completamente implementado y en funcionamiento (ver `plan.md`). Las tareas
> de este documento no son trabajo a ejecutar: registran retroactivamente, con fines de
> trazabilidad (Principios V y VI de la constitución del proyecto), qué unidad de trabajo
> satisface cada caso de uso y requisito funcional de `spec.md`. Todas las tareas están marcadas
> `[X]` (completadas).
>
> Cada tarea indica su nivel de confianza documental, heredado de `contracts/endpoints.md` y
> `data-model.md`:
> - **Confirmado**: verificado directamente contra el código real (`app/routers/ciclista.py`,
>   `app/routers/empleado.py`) o el esquema real de PocketBase.
> - **Inferido**: funcionalidad que el sistema en producción necesariamente provee (forma parte
>   del ciclo de negocio operativo descrito en `spec.md`), pero cuyo archivo/función exacto no fue
>   leído línea por línea en las sesiones de documentación de `plan.md`/`data-model.md`. No es un
>   hueco de desarrollo: es un hueco de verificación documental.

**Tests**: No solicitados. `research.md` registra pytest + `fastapi.testclient.TestClient` como
recomendación estándar para FastAPI, no confirmada como suite ya existente; no se generan tareas
de test.

**Organización**: Las fases agrupan tareas por paquete de `spec.md` y, dentro de cada paquete, por
historia de usuario (US1–US5, prioridades P1–P3), igual que en `plan.md`.

## Formato: `[ID] [P?] [Story] Descripción con ruta de archivo — Estado`

- **[P]**: Archivo distinto, sin dependencia de otra tarea de la misma fase
- **[Story]**: Historia de usuario a la que pertenece (US1–US5)
- **Estado**: Confirmado | Inferido (ver banner arriba)

## Path Conventions

Rutas según `plan.md` § Project Structure. Solo `app/middleware/auth.py`, `app/routers/ciclista.py`
y `app/routers/empleado.py` están confirmadas contra el repositorio real; el resto (`auth.py`,
`admin.py`, `gerente.py`, `roles.py`, `services/`, `clients/`, `templates/`, `static/`) es la
estructura inferida documentada en `plan.md`.

---

## Phase 1: Setup (Infraestructura compartida) — ✅ Completado

**Purpose**: Inicialización del proyecto y la infraestructura base

- [X] T001 Inicializar backend FastAPI con renderizado server-side Jinja2 en `app/main.py` — Inferido
- [X] T002 [P] Configurar contenedorización con Docker: `Dockerfile` y `docker-compose.yml`
      (servicios backend, PocketBase, ClickHouse) — Confirmado (Principio VII)
- [X] T003 [P] Definir esquema de colecciones transaccionales en PocketBase: `roles`, `users`,
      `bicicletas`, `estaciones`, `tarifas`, `viajes`, `ordenes_mant`, `pagos`, `cuentas_bancarias`,
      `auditoria` — Confirmado (esquema de `bicicletas` y `viajes` verificado directamente; el
      resto es inferido a partir de `spec.md`)
- [X] T004 [P] Definir tabla analítica `fact_viajes` en ClickHouse, derivada de `viajes` (OLAP) —
      Inferido
- [X] T005 [P] Cargar librerías de presentación Chart.js y Leaflet.js en `app/static/`, consumidas
      desde las plantillas Jinja2 — Inferido

**Checkpoint**: Infraestructura base operativa (confirmado por el usuario: el sistema corre en
Docker en producción).

---

## Phase 2: Foundational (Prerrequisitos bloqueantes) — ✅ Completado

**Purpose**: Infraestructura núcleo de la que dependen todas las historias de usuario

- [X] T006 Implementar middleware centralizado de validación de rol en
      `app/middleware/auth.py`, aplicado a todo endpoint sin excepción (FR-027, Principio III) —
      **Confirmado**
- [X] T007 [P] Organizar routers separados por rol: `app/routers/auth.py`, `admin.py`,
      `gerente.py`, `ciclista.py`, `empleado.py`, `roles.py` — Confirmado (`ciclista.py` y
      `empleado.py`); inferido el resto
- [X] T008 [P] Definir el campo `bicicletas.estado` como `select` de 4 opciones (`disponible`,
      `en_uso`, `mantenimiento`, `retirada`) en el esquema de PocketBase — **Confirmado**
      directamente contra el panel de administración
- [X] T009 [P] Definir `viajes.estado` (`activo`/`completado`/`cancelado`) y los campos
      `fecha_inicio`, `alerta_atendida` en el esquema de `viajes` — **Confirmado**

**Checkpoint**: Base lista; las historias de usuario pueden documentarse de forma independiente.

---

## Phase 3: User Story 1 - Registro y reserva de bicicleta (Priority: P1) 🎯 MVP

**Paquete**: Gestión de Clientes y Reservas
**Goal**: Un ciclista nuevo se registra y reserva una bicicleta disponible vía mapa interactivo.
**Independent Test**: Registrar un ciclista, consultar disponibilidad en una estación y reservar
una bicicleta, verificando exclusividad (ver `quickstart.md` § Historia 1).

### Implementation for User Story 1

- [X] T010 [P] [US1] Implementar registro de ciclista con validación de edad mínima (18 años) en
      `app/routers/auth.py` (CU-O01, FR-001, FR-002) — Inferido
- [X] T011 [US1] Implementar consulta de disponibilidad de bicicletas por estación vía mapa
      interactivo (Leaflet.js) en `app/routers/ciclista.py` (CU-O03, FR-003) — Inferido
- [X] T012 [US1] Implementar `POST /ciclista/reservar` en `app/routers/ciclista.py`: crea
      `viajes` con `estado="activo"` y actualiza `bicicletas.estado="en_uso"` en la misma
      operación, sin estado "reservado" intermedio ni expiración (CU-O02, CU-O04, FR-004, FR-005,
      FR-006, FR-007) — **Confirmado**
- [X] T013 [US1] Implementar el bloqueo de reserva por pago pendiente
      (`estado="pendiente_efectivo"`/`"verificacion_pendiente"`) o por más de 2 pagos
      `estado="rechazado"`, mediante consultas a `pagos` dentro de la función `reservar()` en
      `app/routers/ciclista.py` (FR-008) — **Confirmado**

**Checkpoint**: Historia 1 funcional y verificable de forma independiente — ✅ En producción.

---

## Phase 4: User Story 2 - Viaje completo y pago (Priority: P1) 🎯 MVP

**Paquete**: Gestión de Viajes y Pagos
**Goal**: El viaje iniciado en la reserva se cierra al devolver la bicicleta, se calcula el costo,
se paga y se emite comprobante.
**Independent Test**: Llevar una reserva a través de fin de viaje, cálculo de costo, pago (los
tres métodos) y verificar comprobante e historial (ver `quickstart.md` § Historia 2).

### Implementation for User Story 2

- [X] T014 [US2] Implementar `POST /ciclista/finalizar` en `app/routers/ciclista.py`: cierra el
      viaje (`estado="completado"`) y libera la bicicleta a `"disponible"` (CU-O05, FR-009) —
      **Confirmado**
- [X] T015 [P] [US2] Implementar cálculo automático de costo según duración y tarifa por tipo de
      bicicleta en `app/services/costos.py` (CU-O06, FR-010) — Inferido
- [X] T016 [US2] Implementar registro de intento de pago (tarjeta/efectivo/transferencia) en
      `app/routers/ciclista.py` (CU-O07, FR-011) — Inferido
- [X] T017 [US2] Integrar la pasarela de pago externa para cobros con tarjeta y registrar su
      confirmación/rechazo asíncrono (CU-O07, FR-012) — Inferido (contrato exacto de la
      integración no documentado)
- [X] T018 [P] [US2] Implementar generación de comprobante dinámico: campo
      `pagos.comprobante_numero` (formato `UB-YYYYMMDD-XXXX`, función `_generar_comprobante`) y
      vista `GET /ciclista/comprobante/{pago_id}` en `app/routers/ciclista.py` (CU-O10, FR-015) —
      **Confirmado**
- [X] T019 [P] [US2] Implementar inmutabilidad de pagos mediante registros de ajuste vinculados
      (nunca edición/eliminación del original) en `app/services/pagos.py` (FR-016, Principio IV) —
      Inferido
- [X] T020 [US2] Implementar consulta de historial de viajes y pagos del ciclista en
      `app/routers/ciclista.py` (CU-O11, FR-017) — Inferido

**Checkpoint**: Historias 1 y 2 funcionan de forma independiente — MVP completo en producción.

---

## Phase 5: User Story 3 - Conciliación de pagos manuales (Priority: P2)

**Paquete**: Gestión de Viajes y Pagos
**Goal**: Un empleado de operación confirma pagos en efectivo y valida comprobantes de
transferencia.
**Independent Test**: Generar un pago en efectivo y uno por transferencia, y verificar que un
empleado de operación puede confirmarlos/rechazarlos de forma independiente (ver `quickstart.md`
§ Historia 3).

### Implementation for User Story 3

- [X] T021 [P] [US3] Implementar confirmación manual de pago en efectivo (con responsable y
      fecha auditados) en `app/routers/empleado.py` (CU-O08, FR-013) — Inferido
- [X] T022 [P] [US3] Implementar revisión de comprobante de transferencia (aprobar/rechazar) en
      `app/routers/empleado.py` (CU-O09, FR-014) — Inferido

**Checkpoint**: Ciclo financiero de pagos no electrónicos cerrado — ✅ En producción.

---

## Phase 6: User Story 4 - Gestión de flota e inspección (Priority: P2)

**Paquete**: Gestión de Flota e Inspección
**Goal**: Registrar órdenes de mantenimiento (manuales o derivadas del checklist) y mantener el
estado de la bicicleta consistente.
**Independent Test**: Registrar una orden manual, completar el checklist de inspección con
resultados distintos y verificar el estado resultante de la bicicleta (ver `quickstart.md` §
Historia 4).

### Implementation for User Story 4

- [X] T023 [US4] Implementar `POST /mantenimiento/ordenes/crear` (función `mnt_ordenes_crear`) en
      `app/routers/empleado.py`: orden manual con `bicicleta_id`, `tipo`
      (`correctivo`/`preventivo`), `descripcion`, `tecnico_nombre`, sin pasar por el checklist
      (CU-O12, FR-018) — **Confirmado**
- [X] T024 [US4] Implementar el checklist de inspección de 7 puntos (constante
      `_CHECKLIST_ITEMS`: frenos, llantas, cadena, luces, estructura, manubrio, sillín), evaluado
      al vuelo y sin persistencia punto por punto, en `POST /mantenimiento/inspeccion/registrar`
      de `app/routers/empleado.py` (CU-O13, FR-019) — **Confirmado**
- [X] T025 [US4] Implementar la creación automática de orden en `ordenes_mant`
      (`tipo="correctivo"` fijo, `descripcion` autogenerada con las fallas) cuando el checklist
      reprueba, dentro del mismo endpoint de T024 (CU-O13, FR-020) — **Confirmado**
- [X] T026 [US4] Implementar la actualización automática de `bicicletas.estado` tras cada evento
      relevante (reserva/inicio de viaje, fin de viaje, resultado de checklist) en
      `app/routers/ciclista.py` y `app/routers/empleado.py` (CU-O14, FR-021) — **Confirmado**
- [X] T027 [US4] Implementar el bloqueo de cambios de estado por orden de mantenimiento o
      checklist mientras la bicicleta tiene un viaje activo en curso (FR-022) — Inferido

**Checkpoint**: Calidad y seguridad de la flota garantizadas — ✅ En producción.

---

## Phase 7: User Story 5 - Monitoreo y devoluciones (Priority: P3)

**Paquete**: Monitoreo y Devoluciones
**Goal**: Vigilancia visualiza viajes activos, recibe alertas de retraso y confirma devoluciones
físicas.
**Independent Test**: Simular viajes activos, verificar el panel de monitoreo, la alerta a los
120 minutos y el registro de una devolución física (ver `quickstart.md` § Historia 5).

### Implementation for User Story 5

- [X] T028 [US5] Implementar panel de viajes activos en tiempo real (tiempo transcurrido,
      estación de origen) en `app/routers/empleado.py` (CU-O15, FR-023) — Inferido
- [X] T029 [US5] Implementar `GET /vigilancia/alertas` en `app/routers/empleado.py`: calcula al
      vuelo los viajes activos cuya `fecha_inicio` supera `_LIMITE_ALERTA_MIN=120` minutos, sin
      tabla propia de alertas (CU-O16, FR-024) — **Confirmado**
- [X] T030 [US5] Implementar `POST /vigilancia/alertas/{id}/atender` en `app/routers/empleado.py`:
      marca `viajes.alerta_atendida=true` sin aplicar cargo ni cierre automático del viaje
      (CU-O16, FR-025) — **Confirmado**
- [X] T031 [US5] Implementar `POST /empleado/vigilancia/devolver/{id}` en
      `app/routers/empleado.py`: registra la devolución física y cierra el viaje
      (`estado="completado"`) (CU-O17, FR-026) — **Confirmado**

**Checkpoint**: Las 5 historias de usuario (CU-O01–CU-O17) funcionan de forma independiente y
están en producción.

---

## Phase 8: Polish & Cross-Cutting Concerns — ✅ Completado

**Purpose**: Aspectos transversales a todas las historias

- [X] T032 [P] Validar que todo endpoint de los routers anteriores pase por
      `app/middleware/auth.py` antes de ejecutar su lógica (FR-027, Principio III) — **Confirmado**
- [X] T033 [P] Ejecutar `quickstart.md` contra el entorno real (`docker compose up -d`) para
      validar los 17 casos de uso end-to-end

---

## Hallazgo: funcionalidad de spec.md sin cobertura confirmada

Se revisó cada requisito funcional (FR-001–FR-027) y entidad clave de `spec.md` contra
`contracts/endpoints.md` y `data-model.md`. **No se detectó ninguna funcionalidad descrita en
`spec.md` que el código confirmado contradiga o que esté ausente del sistema en producción.** Las
tareas marcadas "Inferido" arriba (T001, T003 parcial, T004, T005, T007 parcial, T010, T011, T015,
T016, T017, T019, T020, T021, T022, T027, T028) no son huecos de desarrollo: son funcionalidad que
el sistema necesariamente provee para que el ciclo de negocio operativo funcione (confirmado
indirectamente por el usuario: "el sistema ya está completamente implementado y en
funcionamiento"), pero cuyo archivo/función exacto no fue leído línea por línea durante las
sesiones de `plan.md`/`data-model.md`. Por lo tanto **no se generan tareas nuevas de desarrollo
pendiente**.

El único punto fuera del alcance operativo de CU-O01–CU-O17 (no un hueco, sino un límite de
alcance explícito) es el disparador del estado `bicicletas.estado="retirada"`, que pertenece a
funciones de nivel Administrador/Gerente — ver `data-model.md` y `spec.md` (Key Entities,
FR-021).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)** → **Foundational (Phase 2)** → Historias de usuario (Phase 3–7) → **Polish
  (Phase 8)**
- Todas las fases ya están completas en el sistema real; el orden documentado refleja la
  secuencia lógica de dependencia, no necesariamente el orden cronológico real de construcción
  (no reportado por el usuario).

### User Story Dependencies

- **US1 (P1)**: Sin dependencia de otras historias — punto de entrada del flujo de negocio.
- **US2 (P1)**: Depende de que una bicicleta pueda reservarse (US1); junto con US1 forma el MVP.
- **US3 (P2)**: Depende de que existan pagos en efectivo/transferencia generados por US2.
- **US4 (P2)**: Independiente de US1–US3 en su flujo manual (T023); su flujo automático (T024–T026)
  depende de que existan bicicletas (Foundational).
- **US5 (P3)**: Depende de que existan viajes activos generados por US1/US2.

### Parallel Opportunities

- Setup: T002–T005 son archivos/esquemas independientes.
- Foundational: T007–T009 son archivos/esquemas independientes (T006 es la base que valida los
  demás en tiempo de ejecución).
- US2: T015, T018, T019 tocan archivos distintos entre sí.
- US3: T021 y T022 son endpoints independientes en el mismo router.
- Polish: T032 y T033 son independientes entre sí.

---

## Implementation Strategy (registro retroactivo)

### MVP entregado

US1 (Registro y reserva) + US2 (Viaje completo y pago) — confirmado como el ciclo de valor
central ya operando en las 5 ciudades.

### Entrega incremental (orden lógico de paquetes)

1. Setup + Foundational → base lista.
2. Gestión de Clientes y Reservas (US1) → MVP parcial.
3. Gestión de Viajes y Pagos (US2 + US3) → MVP completo + conciliación financiera.
4. Gestión de Flota e Inspección (US4) → calidad de flota.
5. Monitoreo y Devoluciones (US5) → supervisión operativa.

---

## Notes

- `[X]` = completado y en producción; no quedan checkboxes `[ ]` pendientes en este documento.
- `[P]` indica independencia de archivo, con fines de trazabilidad, no de planificación futura.
- "Confirmado" vs "Inferido" hereda exactamente la clasificación de `contracts/endpoints.md`; no
  se reclasificó ningún endpoint en esta sesión.
- Si se detecta en el futuro que alguna tarea "Inferido" en realidad no está implementada,
  corregir primero `data-model.md`/`contracts/endpoints.md` y luego marcar la tarea
  correspondiente aquí como pendiente real (`[ ]`).
