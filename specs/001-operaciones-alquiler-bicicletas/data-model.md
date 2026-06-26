# Data Model: Operaciones de Alquiler de Bicicletas (Documentación Brownfield)

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Research**: [research.md](./research.md)

> Este documento describe el modelo de datos de un sistema ya en producción. Los tres puntos que en
> una sesión previa habían quedado como `NEEDS VERIFICATION` (Reserva, Comprobante, Checklist de
> inspección/Alerta de retraso) fueron **confirmados contra el código fuente real**
> (`app/routers/ciclista.py` y `app/routers/empleado.py`) y se documentan abajo como hechos
> verificados, no como supuestos. El resto de los campos por colección que no fueron tocados por
> esta verificación (p. ej. detalle de `roles`, `estaciones`, `tarifas`, `cuentas_bancarias`,
> `auditoria`) siguen siendo inferencia razonable a partir de `spec.md` y deben confirmarse contra
> el código fuente antes de tratarse como definitivos.

## Resumen de almacenamiento

| Motor | Rol | Colecciones / Tablas |
|---|---|---|
| PocketBase | OLTP (transaccional) | `roles`, `users`, `bicicletas`, `estaciones`, `tarifas`, `viajes`, `ordenes_mant`, `pagos`, `cuentas_bancarias`, `auditoria` |
| ClickHouse | OLAP (analítico) | `fact_viajes` |

## Mapeo de entidades del spec a almacenamiento real

| Entidad (spec.md) | Colección/Tabla real | Estado del mapeo |
|---|---|---|
| Ciclista | `users` (rol Ciclista) | Confirmado |
| Empleado | `users` (rol Empleado de Operación / Mantenimiento / Vigilancia) | Confirmado |
| Rol | `roles` | Confirmado |
| Estación | `estaciones` | Confirmado |
| Bicicleta | `bicicletas` | Confirmado |
| Tarifa (por tipo de bicicleta) | `tarifas` | Confirmado |
| Viaje | `viajes` | Confirmado |
| Pago | `pagos` | Confirmado |
| Cuenta Bancaria (para transferencias) | `cuentas_bancarias` | Confirmado — no listada en `spec.md` como entidad propia; se documenta aquí porque existe en el sistema real |
| Auditoría de pagos | `auditoria` | Confirmado |
| Orden de Mantenimiento | `ordenes_mant` | Confirmado |
| Histórico de viajes (analítico) | `fact_viajes` (ClickHouse) | Confirmado |
| **Reserva** | **No existe como entidad ni estado separado.** Se materializa directamente como un registro de `viajes` con `estado="activo"` (ver detalle abajo) | **Confirmado** — contradice el modelo de `spec.md` (ver nota al final) |
| **Comprobante** | **No existe colección propia ni archivo persistido.** Campo `pagos.comprobante_numero` (`UB-YYYYMMDD-XXXX`), renderizado dinámicamente | **Confirmado** |
| **Checklist de Inspección** | **No se persiste.** Se evalúa al vuelo a partir de la constante `_CHECKLIST_ITEMS` (7 puntos, no 8) en `app/routers/empleado.py` | **Confirmado** — contradice `spec.md` FR-019/FR-020 (ver nota al final) |
| **Alerta de Retraso (120 min)** | **No se persiste como entidad.** Se calcula al vuelo comparando `viajes.fecha_inicio` contra la hora actual (`_LIMITE_ALERTA_MIN=120`). Solo persiste el booleano `viajes.alerta_atendida` | **Confirmado** |

## Detalle por colección (PocketBase)

### `roles`
- Campos esperados: identificador, nombre del rol.
- Valores: Administrador, Gerente, Ciclista, Empleado de Operación, Empleado de Mantenimiento,
  Empleado de Vigilancia.
- Soporta: FR-027 (validación de rol por endpoint).

### `users`
- Campos esperados: nombre, datos de contacto, identificación nacional, fecha de nacimiento,
  contraseña (hash), relación con `roles`, ciudad asociada.
- Soporta: FR-001, FR-002.
- **Confirmado**: no existe ningún campo persistido de "bloqueado"/estado de cuenta en `users`. El
  bloqueo por pago pendiente (FR-008) se calcula en tiempo de ejecución sobre `pagos`, no sobre
  `users` — ver sección "Bloqueo por pago pendiente (FR-008)" más abajo.

### `estaciones`
- Campos esperados: nombre, ciudad (Quito/Guayaquil/Cuenca/Riobamba/Ambato), coordenadas
  geográficas, capacidad de anclaje.
- Soporta: FR-003, FR-004 (mapa interactivo de disponibilidad vía Leaflet.js).

### `bicicletas` — confirmado

- Campo `estado` — campo `select` con exactamente **4 opciones**, confirmado directamente contra
  el esquema real de la colección en el panel de administración de PocketBase: `disponible`,
  `en_uso`, `mantenimiento`, `retirada`.
  - `POST /ciclista/reservar` → `estado="en_uso"` (inmediato, sin paso intermedio).
  - Fin de viaje (`POST /ciclista/finalizar`, `.../alquileres/{id}/completar`,
    `.../vigilancia/devolver/{id}`) → `estado="disponible"`.
  - Checklist reprobado en `POST /mantenimiento/inspeccion/registrar` → `estado="mantenimiento"`.
  - Checklist aprobado en el mismo endpoint → `estado="disponible"`.
  - `reservada` — **confirmado que NO existe** como valor del `select`: no hay paso de reserva
    separado del inicio del viaje (consistente con la sección "Reserva" abajo).
  - `retirada` — **confirmado que SÍ existe** como una de las 4 opciones del `select`, aunque no
    se observó su asignación en los flujos revisados de `ciclista.py`/`empleado.py`. Su disparador
    probable (no confirmado contra código, pero consistente con el esquema) es una acción manual
    desde `admin.py`/`gerente.py` para dar de baja una bicicleta de forma permanente (p. ej. robo,
    daño irreparable, fin de vida útil); esos routers están fuera del alcance operativo de
    `spec.md` (CU-O01–CU-O17).
- Campos esperados adicionales: tipo (estándar/eléctrica), estación actual.

### `tarifas`
- Campos esperados: tipo de bicicleta, tarifa por minuto/tramo, ciudad (si las tarifas varían por
  ciudad).
- Soporta: FR-010.

### `viajes` — confirmado
- Campo `estado` — valores confirmados: `activo`, `completado`, `cancelado`.
  - Creado directamente en `estado="activo"` por `POST /ciclista/reservar` (no existe un estado
    `reservado` previo; reservar e iniciar el viaje son el mismo evento técnico — ver sección
    "Reserva" abajo).
  - Pasa a `estado="completado"` vía `POST /ciclista/finalizar`, `.../empleado/operacion/alquileres/{id}/completar`
    o `.../empleado/vigilancia/devolver/{id}`.
  - Pasa a `estado="cancelado"` vía `.../empleado/operacion/alquileres/{id}/cancelar`.
- Campo `fecha_inicio` — usado por `GET /vigilancia/alertas` para calcular el retraso en tiempo de
  ejecución (umbral `_LIMITE_ALERTA_MIN=120`).
- Campo `alerta_atendida` (booleano) — único dato persistido de la alerta de retraso; se marca
  `true` vía `POST /vigilancia/alertas/{id}/atender`.
- Campos esperados adicionales: ciclista, bicicleta, estación de origen/destino, hora de fin,
  duración, costo calculado.
- Soporta: FR-007, FR-009, FR-010, FR-017, FR-023, FR-024, FR-025.

### `ordenes_mant` — confirmado

Coexisten dos vías de creación, ambas confirmadas contra `app/routers/empleado.py`:

1. **Manual** (`POST /mantenimiento/ordenes/crear`, función `mnt_ordenes_crear`): un empleado de
   mantenimiento registra la orden directamente, indicando `bicicleta_id`, `tipo`
   (`correctivo`/`preventivo`), `descripcion` y `tecnico_nombre`. No pasa por el checklist de
   inspección (CU-O12).
2. **Automática** (vía checklist reprobado en `POST /mantenimiento/inspeccion/registrar`): si al
   menos un punto del checklist falla, se crea una orden con `tipo="correctivo"` fijo y
   `descripcion` generada automáticamente listando las fallas detectadas. El checklist en sí **no
   se persiste** (ni en esta colección ni en otra); solo su resultado agregado queda reflejado en
   `descripcion` y en el cambio de `bicicletas.estado` (CU-O13).

- Campos confirmados: `bicicleta_id`, `tipo` (`correctivo`/`preventivo`), `descripcion`,
  `tecnico_nombre`.
- Soporta: FR-018, FR-019, FR-020, FR-022.

### `pagos` — confirmado (parcial)
- Campo `comprobante_numero` (string) — confirmado: formato `UB-YYYYMMDD-XXXX`, generado por la
  función `_generar_comprobante`. No existe archivo PDF ni binario persistido; la vista
  `GET /ciclista/comprobante/{pago_id}` renderiza el comprobante dinámicamente en HTML a partir de
  este campo y los datos del viaje asociado, en cada solicitud.
- Campos esperados adicionales: viaje, monto, método (tarjeta/efectivo/transferencia), estado
  (pendiente/confirmado/rechazado/disputado), empleado que confirmó (si aplica), fecha de
  confirmación.
- Soporta: FR-011, FR-012, FR-013, FR-015, FR-016.

### `cuentas_bancarias`
- Campos esperados: datos de la cuenta receptora de transferencias, usados como referencia para
  validar comprobantes subidos por el ciclista (CU-O09).
- Soporta: FR-014.

### `auditoria`
- Campos esperados: referencia al pago/viaje afectado, acción registrada, usuario responsable,
  fecha/hora.
- Soporta: FR-016 (inmutabilidad de pagos mediante registros de ajuste vinculados, nunca edición
  directa del original).

## ClickHouse — `fact_viajes`

Tabla analítica derivada de `viajes`, usada para reportes históricos agregados (no transaccional).
Soporta el Principio I de la constitución. Los reportes que consumen esta tabla (p. ej. paneles de
Gerente/Administrador) están fuera del alcance operativo de `spec.md` (CU-O01–CU-O17 son todos de
nivel operativo).

## Transiciones de estado de Bicicleta (FR-021) — confirmado

```text
disponible --(POST /ciclista/reservar)--> en_uso
en_uso --(POST /ciclista/finalizar | .../alquileres/{id}/completar | .../vigilancia/devolver/{id})--> disponible
en_uso --(.../alquileres/{id}/cancelar, sobre el viaje)--> disponible
disponible --(checklist reprueba en POST /mantenimiento/inspeccion/registrar)--> mantenimiento
mantenimiento --(checklist aprueba en el mismo endpoint)--> disponible
mantenimiento --(checklist vuelve a reprobar)--> mantenimiento (permanece; nueva orden en ordenes_mant)
```

No existe un estado intermedio `reservada` (confirmado que no existe): reservar y comenzar el
viaje son el mismo evento técnico sobre `viajes` y `bicicletas`. El estado `retirada` **sí existe**
(confirmado contra el esquema real del campo `select` en PocketBase, una de sus 4 opciones), pero
su disparador no aparece en los flujos verificados de `ciclista.py`/`empleado.py`; probablemente se
asigna desde `admin.py`/`gerente.py` para dar de baja una bicicleta de forma permanente — fuera del
alcance operativo de `spec.md`.

## Entidades confirmadas contra código fuente

### Reserva (CU-O02) — confirmado, sin colección propia

No existe un estado "reservado" ni una colección `reservas`. `POST /ciclista/reservar` crea
directamente un registro en `viajes` con `estado="activo"` y, en la misma operación, actualiza
`bicicletas.estado="en_uso"`. Reservar e iniciar el viaje son el mismo evento técnico: no hay paso
intermedio ni expiración por tiempo. El viaje permanece en `estado="activo"` hasta que se finaliza
(`POST /ciclista/finalizar`, `.../empleado/operacion/alquileres/{id}/completar` o
`.../empleado/vigilancia/devolver/{id}` → `estado="completado"`; o
`.../empleado/operacion/alquileres/{id}/cancelar` → `estado="cancelado"`), momento en el que la
bicicleta vuelve a `estado="disponible"`.

### Comprobante (CU-O10) — confirmado, sin archivo persistido

Campo `comprobante_numero` (string) dentro del registro de `pagos`, con formato
`UB-YYYYMMDD-XXXX`, generado por la función `_generar_comprobante`. No se guarda ningún archivo
PDF físico. La vista HTML de comprobante (`GET /ciclista/comprobante/{pago_id}`) se renderiza
dinámicamente a partir de ese campo más los datos del viaje asociado, en cada solicitud.

### Checklist de Inspección (CU-O13) — confirmado, 7 puntos, no persistido

El checklist tiene **7 puntos reales** (constante `_CHECKLIST_ITEMS` en `app/routers/empleado.py`):
frenos, llantas, cadena, luces, estructura, manubrio, sillín — **no 8** como asumió la
especificación inicial (`spec.md` FR-019/FR-020/SC-007/Assumptions listan 8, incluyendo "sistema
de bloqueo" y "limpieza general", que no existen en el código real).

El checklist se evalúa al vuelo en `POST /mantenimiento/inspeccion/registrar` y **no se persiste**
en ninguna colección:
- Si todos los puntos pasan → solo se actualiza `bicicletas.estado="disponible"`.
- Si al menos uno falla → se crea una nueva orden en `ordenes_mant` con `descripcion` en texto
  libre listando las fallas, y la bicicleta pasa a `bicicletas.estado="mantenimiento"`.

### Bloqueo por pago pendiente (FR-008) — confirmado, sin campo en `users`

No existe ningún campo persistido de "bloqueado" en `users`. El bloqueo se calcula en tiempo de
ejecución en cada intento de reserva (`POST /ciclista/reservar`, confirmado contra
`app/routers/ciclista.py`, función `reservar()`) mediante dos consultas directas a `pagos`:

1. **Pago pendiente**: se consulta si existe algún registro en `pagos` con `ciclista_id` igual al
   usuario actual y `estado` igual a `"pendiente_efectivo"` o `"verificacion_pendiente"`. Si existe
   al menos uno, se rechaza la reserva con el mensaje "Tienes pagos pendientes. Regula tu situación
   antes de hacer una nueva reserva."
2. **Rechazos repetidos**: se cuentan los registros en `pagos` del ciclista con `estado="rechazado"`.
   Si son más de 2, se bloquea con el mensaje "Tu cuenta ha sido bloqueada temporalmente por pagos
   rechazados. Contacta a soporte."

### Orden de Mantenimiento (CU-O12) — confirmado, dos vías de creación

`POST /mantenimiento/ordenes/crear` (función `mnt_ordenes_crear`) permite que un empleado de
mantenimiento registre una orden directamente sobre `ordenes_mant`, indicando `bicicleta_id`,
`tipo` (`correctivo`/`preventivo`), `descripcion` y `tecnico_nombre`, sin pasar por el checklist de
inspección. Esta vía manual coexiste con la vía automática descrita en "Checklist de Inspección"
abajo (checklist reprobado → orden con `tipo="correctivo"` fijo y `descripcion` autogenerada).

### Alerta de Retraso (CU-O16) — confirmado, calculada en tiempo de ejecución

No tiene tabla propia. Se calcula en tiempo de ejecución en `GET /vigilancia/alertas` comparando
el campo `viajes.fecha_inicio` de cada viaje activo contra la hora actual, usando la constante
`_LIMITE_ALERTA_MIN=120`. Lo único que se persiste es el campo booleano `viajes.alerta_atendida`,
marcado `true` vía `POST /vigilancia/alertas/{id}/atender`.

## Estado de sincronización con el resto de la documentación

`spec.md`, `research.md`, `contracts/endpoints.md` y `quickstart.md` fueron actualizados para
reflejar los hechos confirmados arriba (sin estado "reservado" con expiración, checklist de 7
puntos, comprobante sin archivo persistido, alerta de retraso calculada en tiempo de ejecución,
CU-O12 con dos vías de creación confirmadas, los 4 estados reales de `bicicletas` —`disponible`,
`en_uso`, `mantenimiento`, `retirada`— y el bloqueo por pago pendiente/rechazos repetidos
calculado en tiempo de ejecución sobre `pagos`, sin campo persistido en `users`).

No quedan puntos `NEEDS VERIFICATION` abiertos en el conjunto de documentos de la especificación
001-operaciones-alquiler-bicicletas.
