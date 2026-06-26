# Contracts: Endpoints (Documentación Brownfield)

**Spec**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md)

> Los endpoints marcados **Confirmado** abajo fueron verificados contra el código fuente real
> (`app/routers/ciclista.py`, `app/routers/empleado.py`) e incluyen ruta y verbo HTTP exactos. El
> resto sigue siendo **inferido** a partir de los routers reportados por el usuario (`auth`,
> `admin`, `gerente`, `roles`) y de los requisitos funcionales de `spec.md`, y debe confirmarse y
> corregirse contra `app/routers/*.py` antes de usar este documento como contrato definitivo.

Todos los endpoints, sin excepción, DEBEN pasar por el middleware de `app/middleware/auth.py` que
valida el rol del usuario autenticado antes de ejecutar la acción (FR-027, Principio III de la
constitución).

## Router `auth` — sin rol previo (acceso público)

| Endpoint (inferido) | Caso de uso / Requisito |
|---|---|
| Registro de ciclista | CU-O01, FR-001, FR-002 |
| Inicio de sesión | (soporte transversal, no tiene CU propio en spec 001) |
| Cierre de sesión | (soporte transversal, no tiene CU propio en spec 001) |

## Router `ciclista` — rol requerido: Ciclista

| Endpoint | Estado | Caso de uso / Requisito |
|---|---|---|
| `POST /ciclista/reservar` — crea `viajes` en `estado="activo"` y pone `bicicletas.estado="en_uso"` en la misma operación (sin estado "reservado" intermedio) | **Confirmado** | CU-O02, CU-O04, FR-004, FR-005, FR-006, FR-007 |
| `POST /ciclista/finalizar` — cierra el viaje (`estado="completado"`) y libera la bicicleta a "disponible" | **Confirmado** | CU-O05, FR-009, FR-010 |
| `GET /ciclista/comprobante/{pago_id}` — renderiza dinámicamente el comprobante a partir de `pagos.comprobante_numero`; no hay archivo persistido | **Confirmado** | CU-O10, FR-015 |
| Consultar disponibilidad de bicicletas por estación (mapa interactivo) | Inferido | CU-O03, FR-003 |
| Pagar el viaje (tarjeta / efectivo / transferencia) | Inferido | CU-O07, FR-011, FR-012 |
| Subir comprobante de transferencia | Inferido | CU-O09 (lado ciclista), FR-014 |
| Consultar historial de viajes y pagos | Inferido | CU-O11, FR-017 |

## Router `empleado` — rol requerido según acción

| Endpoint | Estado | Rol requerido | Caso de uso / Requisito |
|---|---|---|---|
| `POST /mantenimiento/inspeccion/registrar` — evalúa el checklist de 7 puntos (`_CHECKLIST_ITEMS`) al vuelo; si reprueba, crea orden en `ordenes_mant` con `descripcion`; si aprueba, pone `bicicletas.estado="disponible"` | **Confirmado** | Empleado de Mantenimiento | CU-O13, CU-O14, FR-019, FR-020 |
| `GET /vigilancia/alertas` — calcula al vuelo los viajes activos que superan `_LIMITE_ALERTA_MIN=120` min comparando `viajes.fecha_inicio` | **Confirmado** | Empleado de Vigilancia | CU-O15, CU-O16, FR-023, FR-024, FR-025 |
| `POST /vigilancia/alertas/{id}/atender` — marca `viajes.alerta_atendida=true` | **Confirmado** | Empleado de Vigilancia | CU-O16, FR-025 |
| `POST /empleado/operacion/alquileres/{id}/completar` — cierra el viaje (`estado="completado"`) | **Confirmado** | Empleado de Operación | CU-O05, CU-O17 |
| `POST /empleado/operacion/alquileres/{id}/cancelar` — cancela el viaje (`estado="cancelado"`) | **Confirmado** | Empleado de Operación | CU-O05 |
| `POST /empleado/vigilancia/devolver/{id}` — cierra el viaje (`estado="completado"`) | **Confirmado** | Empleado de Vigilancia | CU-O17, FR-026 |
| `POST /mantenimiento/ordenes/crear` (función `mnt_ordenes_crear`) — crea orden manual en `ordenes_mant` (`bicicleta_id`, `tipo` correctivo/preventivo, `descripcion`, `tecnico_nombre`), sin checklist | **Confirmado** | Empleado de Mantenimiento | CU-O12, FR-018 |
| Confirmar pago en efectivo | Inferido | Empleado de Operación | CU-O08, FR-013 |
| Revisar comprobante de transferencia (aprobar/rechazar) | Inferido | Empleado de Operación | CU-O09, FR-014 |
| Ver panel de viajes activos | Inferido | Empleado de Vigilancia | CU-O15, FR-023 |

## Routers `admin`, `gerente`, `roles`

Existen en el sistema real pero sus endpoints **no están en el alcance de `spec.md` (001)**, que
cubre únicamente el nivel operativo (CU-O01–CU-O17). Quedan fuera de este contrato hasta que se
documente la especificación correspondiente al nivel táctico/estratégico (Principio VI de la
constitución: ninguna funcionalidad se documenta sin un caso de uso asociado).

## Actores externos / automáticos

- **Pasarela de Pago** (sistema externo): recibe la solicitud de cobro con tarjeta desde el
  endpoint de pago del router `ciclista` y devuelve confirmación o rechazo de forma asíncrona
  (CU-O07, FR-012). El contrato exacto de esta integración (formato de payload, callback/webhook)
  no fue proporcionado y queda fuera de alcance de esta sesión.
- **Sistema** (actor automático): no expone un endpoint propio; sus acciones (cálculo de costo,
  actualización de estado de bicicleta) ocurren como efecto secundario de los endpoints anteriores
  (CU-O06, CU-O14, FR-010, FR-021).
