# Implementation Plan: Operaciones de Alquiler de Bicicletas (Nivel Operativo)
 
**Branch**: `001-operaciones-alquiler-bicicletas` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-operaciones-alquiler-bicicletas/spec.md`

> **⚠️ DOCUMENTACIÓN BROWNFIELD — NO ES UN DISEÑO A CONSTRUIR.**
> El sistema descrito en este plan ya está implementado y en funcionamiento. Este documento
> registra retroactivamente la arquitectura real existente que satisface `spec.md`, con fines de
> trazabilidad (Principios V y VI de la constitución del proyecto).

## Summary

Los 17 casos de uso operativos (CU-O01–CU-O17) de `spec.md` ya están cubiertos por un sistema en
producción: backend FastAPI con renderizado server-side Jinja2, persistencia híbrida PocketBase
(OLTP) + ClickHouse (OLAP), seguridad por rol mediante middleware centralizado, y despliegue
contenedorizado con Docker. Este plan documenta esa arquitectura real y mapea las entidades del
spec a las colecciones/tablas reales. Los tres puntos del modelo de datos que en una sesión previa
no pudieron confirmarse (Reserva, Comprobante, Checklist de inspección/Alerta de retraso) quedaron
verificados contra el código fuente real (`app/routers/ciclista.py`, `app/routers/empleado.py`) y
están documentados en detalle en `data-model.md`.

## Technical Context

**Language/Version**: Python 3.11+ (FastAPI)

**Primary Dependencies**: FastAPI, Jinja2 (renderizado server-side), cliente/SDK de PocketBase,
cliente de ClickHouse (p. ej. `clickhouse-connect` o `clickhouse-driver`), Chart.js (gráficos,
cargado como script en las plantillas), Leaflet.js (mapas interactivos, cargado como script en las
plantillas)

**Storage**: PocketBase (OLTP) — colecciones `roles`, `users`, `bicicletas`, `estaciones`,
`tarifas`, `viajes`, `ordenes_mant`, `pagos`, `cuentas_bancarias`, `auditoria`; ClickHouse (OLAP) —
tabla `fact_viajes`

**Testing**: No confirmado por el usuario como ya existente. Se documenta como recomendación
estándar para FastAPI: pytest + `fastapi.testclient.TestClient` (ver `research.md`)

**Target Platform**: Servidor Linux en contenedores Docker; acceso vía navegador web
(renderizado server-side) en las 5 ciudades de operación (Quito, Guayaquil, Cuenca, Riobamba,
Ambato)

**Project Type**: web-service (backend monolítico con renderizado server-side; sin frontend
separado/SPA)

**Performance Goals**: Los definidos en `spec.md` Success Criteria — disponibilidad de bicicletas
con ≥99% de precisión inmediatamente después de eventos de reserva/viaje (SC-002), costo de viaje
calculado y mostrado en ≤10s tras finalizar el viaje (SC-003), alerta de retraso entregada a
vigilancia en ≤1 minuto de superar 120 minutos (SC-008)

**Constraints**: Arquitectura híbrida obligatoria sin mezclar responsabilidades OLAP/OLTP
(Principio I); el checklist de inspección de 7 puntos (`_CHECKLIST_ITEMS` en
`app/routers/empleado.py`) y el umbral de alerta de 120 minutos (`_LIMITE_ALERTA_MIN`) son reglas
de negocio fijas en el backend, no configurables por el usuario final; todo endpoint valida el rol
del usuario autenticado antes de ejecutar su lógica (Principio III)

**Scale/Scope**: 5 ciudades, 6 roles, 17 casos de uso operativos (CU-O01–CU-O17) ya cubiertos por
el sistema en producción

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Evaluación | Evidencia |
|---|---|---|
| I. Arquitectura Híbrida de Datos | ✅ PASS | PocketBase concentra todo lo transaccional (10 colecciones listadas); ClickHouse se usa exclusivamente para `fact_viajes` (analítico/histórico). No se reporta mezcla de responsabilidades. |
| II. Backend FastAPI + SSR Jinja2 | ✅ PASS | FastAPI + Jinja2 confirmados. Chart.js y Leaflet.js son librerías de presentación cargadas dentro de páginas renderizadas en servidor, no frameworks SPA (React/Vue); no requieren justificación de complejidad adicional. |
| III. Seguridad por Roles | ✅ PASS | Middleware centralizado (`app/middleware/auth.py`) valida el rol antes de cada acción; routers separados por rol. |
| IV. Trazabilidad de Pagos | ✅ PASS | Colecciones `pagos`, `cuentas_bancarias` y `auditoria` soportan la trazabilidad exigida. El "Comprobante" (CU-O10) está confirmado: campo `comprobante_numero` (formato `UB-YYYYMMDD-XXXX`, generado por `_generar_comprobante`) dentro de `pagos`, renderizado dinámicamente en `GET /ciclista/comprobante/{pago_id}`; no existe archivo físico persistido. |
| V. Calidad ISO/IEC 25010 e ISO/IEC 29148 | ✅ PASS | El plan es trazable a `spec.md` y a casos de uso documentados. Los tres mapeos de entidades antes pendientes (Reserva, Comprobante, Checklist/Alerta de retraso) quedaron verificados contra `app/routers/ciclista.py` y `app/routers/empleado.py` y documentados en `data-model.md`. |
| VI. Diseño Orientado a Casos de Uso | ✅ PASS | Cada decisión documentada referencia su caso de uso (CU-O01–CU-O17) o su requisito funcional (FR-001–FR-027) en `spec.md`. |
| VII. Despliegue Contenedorizado con Docker | ✅ PASS | Confirmado por el usuario: el sistema ya corre en contenedores Docker. |

No se identifican violaciones que requieran justificación en Complexity Tracking. No quedan
puntos abiertos en la Constitution Check.

## Project Structure

### Documentation (this feature)

```text
specs/001-operaciones-alquiler-bicicletas/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   └── endpoints.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository del sistema en producción)

> Rutas confirmadas explícitamente contra el código fuente real: `app/middleware/auth.py`,
> `app/routers/ciclista.py` y `app/routers/empleado.py` (con sus endpoints, constantes y
> funciones internas — ver `data-model.md`). El resto de esta estructura (routers `auth`, `admin`,
> `gerente`, `roles`; carpetas `templates/`, `static/`, `services/`, `clients/`) sigue siendo una
> inferencia razonable a partir de los componentes descritos; **no fue verificada contra el
> repositorio de código real**. Se recomienda confirmarla si difiere de la estructura real.

```text
app/
├── main.py                  # Punto de entrada FastAPI
├── middleware/
│   └── auth.py               # Validación de rol por endpoint (Principio III) — CONFIRMADO
├── routers/
│   ├── auth.py                # Registro/login (CU-O01)
│   ├── admin.py                # Funciones de nivel Administrador (fuera de alcance de spec 001)
│   ├── gerente.py              # Funciones de nivel Gerente (fuera de alcance de spec 001)
│   ├── ciclista.py             # Reservas, viajes, pagos, historial (CU-O02–CU-O11)
│   ├── empleado.py             # Operación, mantenimiento, vigilancia (CU-O08–CU-O09, CU-O12–CU-O17)
│   └── roles.py                # Soporte de roles para los demás routers
├── templates/                # Plantillas Jinja2 (SSR)
├── static/                   # CSS propio, Chart.js, Leaflet.js
├── services/                 # Lógica de negocio (cálculo de costo, checklist, alertas)
└── clients/                   # Clientes de PocketBase y ClickHouse

docker/ (o raíz del repo)
├── Dockerfile
└── docker-compose.yml        # Servicios: backend, PocketBase, ClickHouse
```

**Structure Decision**: Documentación retroactiva de un único servicio web monolítico (`app/`) con
renderizado server-side; no aplica la opción de frontend/backend separados ni de app móvil. La
estructura interna de `routers/`, `templates/`, `static/`, `services/` y `clients/` es inferida y
debe confirmarse contra el repositorio real.

## Complexity Tracking

> No se identificaron violaciones de la Constitution Check que requieran justificación.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| _Ninguna_ | — | — |
