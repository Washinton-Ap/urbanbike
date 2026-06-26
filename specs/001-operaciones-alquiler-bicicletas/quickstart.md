# Quickstart: Validación de Operaciones de Alquiler de Bicicletas (Brownfield)

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Data Model**:
[data-model.md](./data-model.md) | **Contracts**: [contracts/endpoints.md](./contracts/endpoints.md)

> Esta guía no es un "primer arranque" de un proyecto nuevo: el sistema ya está en producción. Su
> propósito es permitir validar, contra el sistema real, que el comportamiento descrito en
> `spec.md` (CU-O01–CU-O17) efectivamente ocurre. Los puntos que antes estaban `NEEDS
> VERIFICATION` (Reserva, Comprobante, Checklist/Alerta de retraso) ya fueron confirmados contra
> el código fuente — ver `data-model.md`. Quedan abiertos los puntos listados en la sección final.

## Prerrequisitos

- Docker y Docker Compose instalados (Principio VII de la constitución).
- Acceso al repositorio de código real de UrbanBike S.A. (no incluido en este directorio de
  documentación de Spec Kit).
- Credenciales de prueba para al menos un usuario de cada rol: Ciclista, Empleado de Operación,
  Empleado de Mantenimiento, Empleado de Vigilancia.
- Acceso al panel de administración de PocketBase y a una consola de ClickHouse, para inspeccionar
  directamente los esquemas reales (usado, por ejemplo, para confirmar los 4 estados reales de
  `bicicletas` — ver sección final).

## Levantar el entorno

```bash
docker compose up -d
```

Verificar que los tres servicios (backend FastAPI, PocketBase, ClickHouse) estén activos antes de
continuar.

## Escenarios de validación (trazables a `spec.md`)

Cada escenario referencia directamente los Acceptance Scenarios de `spec.md`. El objetivo es
confirmar que el sistema real produce el resultado esperado, no medir cobertura de pruebas
automatizadas.

### Historia 1 — Registro y reserva (P1)

1. Registrar un ciclista nuevo con datos válidos → debe quedar con cuenta activa (CU-O01).
2. Consultar el mapa interactivo de una estación con bicicletas disponibles → debe reflejar el
   inventario real en tiempo real (CU-O03).
3. Reservar una bicicleta disponible → debe pasar a "en uso" de inmediato (mismo evento técnico
   que iniciar el viaje, sin estado "reservado" intermedio); un segundo intento de reserva sobre
   la misma bicicleta debe rechazarse (CU-O02, `POST /ciclista/reservar`).

### Historia 2 — Viaje completo y pago (P1)

1. Verificar que reservar la bicicleta (paso anterior) ya registró la hora de inicio del viaje —
   no existe un paso de "iniciar viaje" separado (CU-O02, CU-O04).
2. Finalizar el viaje devolviendo la bicicleta → debe registrar hora de fin y calcular el costo
   automáticamente (CU-O05, CU-O06).
3. Pagar con cada uno de los tres métodos (tarjeta, efectivo, transferencia) en corridas separadas
   → debe generarse un comprobante imprimible en cada caso (CU-O07, CU-O10).
4. Consultar el historial del ciclista → debe listar los viajes y pagos anteriores (CU-O11).
5. Con un pago pendiente sin confirmar, intentar iniciar un nuevo viaje → debe bloquearse
   (FR-008).

### Historia 3 — Conciliación de pagos manuales (P2)

1. Como Empleado de Operación, confirmar un pago en efectivo pendiente → debe quedar auditado con
   responsable y fecha (CU-O08).
2. Revisar un comprobante de transferencia subido por un ciclista → aprobar uno y rechazar otro,
   verificando que el rechazado permanece pendiente para corrección (CU-O09).

### Historia 4 — Gestión de flota e inspección (P2)

1. Registrar una orden de mantenimiento manual (`POST /mantenimiento/ordenes/crear`) sobre una
   bicicleta, indicando tipo (correctivo/preventivo), descripción y técnico → debe pasar a estado
   "mantenimiento" y desaparecer de la disponibilidad (CU-O12).
2. Completar el checklist de 7 puntos (`POST /mantenimiento/inspeccion/registrar`) con todos
   aprobados → la bicicleta debe volver a "disponible" (CU-O13, CU-O14).
3. Repetir con al menos un punto reprobado → debe crearse una orden en `ordenes_mant` con la
   descripción de las fallas y la bicicleta debe permanecer en "mantenimiento" (CU-O13, CU-O14).

### Historia 5 — Monitoreo y devoluciones (P3)

1. Con un viaje activo, abrir el panel de vigilancia → debe listarse con su tiempo transcurrido
   (CU-O15).
2. Simular un viaje activo por más de 120 minutos → debe generarse una alerta dirigida a
   vigilancia, y el viaje debe permanecer activo sin cargo ni cierre automático (CU-O16, FR-025).
3. Confirmar la devolución física de una bicicleta → debe registrarse como cierre del ciclo de
   viaje (CU-O17).

## Cierre de los puntos `NEEDS VERIFICATION` de esta especificación

Todos los puntos que estuvieron abiertos sobre el modelo de datos de esta especificación quedaron
confirmados contra el código fuente real o el esquema de PocketBase: Reserva, Comprobante,
Checklist de inspección, Alerta de retraso, CU-O12 (orden de mantenimiento manual vs. automática),
los 4 estados reales de `bicicletas` (`disponible`, `en_uso`, `mantenimiento`, `retirada`;
`reservada` confirmado que no existe) y el bloqueo por pago pendiente/rechazos repetidos (FR-008),
que se calcula en tiempo de ejecución sobre `pagos` y no tiene campo persistido en `users`. Ver
`data-model.md` para el detalle completo.

No quedan puntos `NEEDS VERIFICATION` abiertos en el conjunto de documentos de la especificación
001-operaciones-alquiler-bicicletas.
