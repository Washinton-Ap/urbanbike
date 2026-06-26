# Research: Operaciones de Alquiler de Bicicletas (Documentación Brownfield)

**Fecha**: 2026-06-20
**Spec**: [spec.md](./spec.md)

> Este documento no es investigación previa a una decisión de diseño todavía no tomada. El
> sistema ya está construido y en producción; aquí se registran las decisiones técnicas **ya
> tomadas** por el equipo de UrbanBike S.A. Los tres puntos que en una sesión previa no pudieron
> confirmarse (Reserva, Comprobante, Checklist de inspección/Alerta de retraso) quedaron
> verificados contra el código fuente real (`app/routers/ciclista.py`, `app/routers/empleado.py`)
> y se documentan abajo como decisiones confirmadas, con el detalle completo en `data-model.md`.

## Decisiones confirmadas

### Backend y renderizado
- **Decision**: FastAPI (Python) como framework de backend; Jinja2 para renderizado server-side;
  CSS propio; Chart.js para gráficos; Leaflet.js para mapas interactivos.
- **Rationale**: Cumple el Principio II de la constitución (backend FastAPI + SSR, sin frameworks
  frontend pesados sin justificación). Chart.js y Leaflet.js son librerías de presentación cargadas
  dentro de páginas renderizadas en servidor, no frameworks SPA, por lo que no requieren
  justificación de complejidad adicional.
- **Alternatives considered**: N/A — decisión ya tomada e implementada; no aplica evaluar
  alternativas retroactivamente.

### Persistencia transaccional (OLTP)
- **Decision**: PocketBase con las colecciones `roles`, `users`, `bicicletas`, `estaciones`,
  `tarifas`, `viajes`, `ordenes_mant`, `pagos`, `cuentas_bancarias`, `auditoria`.
- **Rationale**: Cumple el Principio I de la constitución (PocketBase exclusivo para datos
  transaccionales).
- **Alternatives considered**: N/A — decisión ya tomada e implementada.

### Persistencia analítica (OLAP)
- **Decision**: ClickHouse con la tabla `fact_viajes` para reportes históricos.
- **Rationale**: Cumple el Principio I de la constitución (ClickHouse exclusivo para datos
  analíticos).
- **Alternatives considered**: N/A — decisión ya tomada e implementada.

### Seguridad por roles
- **Decision**: Middleware centralizado en `app/middleware/auth.py` que valida el rol del usuario
  autenticado antes de cada acción; routers separados por rol (`auth`, `admin`, `gerente`,
  `ciclista`, `empleado`, `roles`).
- **Rationale**: Cumple el Principio III de la constitución.
- **Alternatives considered**: N/A.

### Despliegue
- **Decision**: Contenedorización con Docker.
- **Rationale**: Cumple el Principio VII de la constitución.
- **Alternatives considered**: N/A.

### Reglas de negocio fijas
- **Decision**: El checklist de inspección de **7 puntos** (constante `_CHECKLIST_ITEMS`:
  frenos, llantas, cadena, luces, estructura, manubrio, sillín — CU-O13) y el umbral de alerta de
  120 minutos (constante `_LIMITE_ALERTA_MIN` — CU-O16) están implementados como reglas de negocio
  fijas en `app/routers/empleado.py`, sin panel de configuración para el usuario final.
- **Rationale**: Confirmado contra el código fuente real. El supuesto inicial de `spec.md` (8
  puntos, con "sistema de bloqueo" y "limpieza general") no coincidía con el código y fue
  corregido a 7 puntos.
- **Alternatives considered**: N/A.

### Reserva y Comprobante — mecanismo real (antes `NEEDS VERIFICATION`)
- **Decision**: No existe un estado "reservado" ni una colección `reservas`. `POST
  /ciclista/reservar` crea directamente un registro en `viajes` con `estado="activo"` y actualiza
  `bicicletas.estado="en_uso"` en la misma operación; reservar e iniciar el viaje son el mismo
  evento técnico, sin expiración por tiempo. El comprobante (CU-O10) tampoco se persiste como
  archivo: es el campo `pagos.comprobante_numero` (formato `UB-YYYYMMDD-XXXX`, generado por
  `_generar_comprobante`), renderizado dinámicamente en `GET /ciclista/comprobante/{pago_id}`.
- **Rationale**: Confirmado contra `app/routers/ciclista.py`. Resuelve la brecha que `spec.md`
  describía como una reserva con expiración de 15 minutos.
- **Alternatives considered**: N/A — comportamiento real verificado, no una decisión a evaluar.

### Checklist y Alerta de retraso — mecanismo real (antes `NEEDS VERIFICATION`)
- **Decision**: El checklist de 7 puntos se evalúa al vuelo en `POST
  /mantenimiento/inspeccion/registrar` y no se persiste; si reprueba, se crea una orden en
  `ordenes_mant` con `descripcion` en texto libre de las fallas. La alerta de retraso se calcula
  al vuelo en `GET /vigilancia/alertas` comparando `viajes.fecha_inicio` contra la hora actual; solo
  se persiste el booleano `viajes.alerta_atendida`, marcado vía `POST
  /vigilancia/alertas/{id}/atender`.
- **Rationale**: Confirmado contra `app/routers/empleado.py`.
- **Alternatives considered**: N/A — comportamiento real verificado, no una decisión a evaluar.

### Orden de Mantenimiento (CU-O12) — dos vías confirmadas
- **Decision**: `POST /mantenimiento/ordenes/crear` (función `mnt_ordenes_crear`) permite a un
  empleado de mantenimiento registrar una orden manualmente (`bicicleta_id`, `tipo`
  correctivo/preventivo, `descripcion`, `tecnico_nombre`), sin pasar por el checklist de
  inspección. Esta vía manual coexiste con la vía automática (checklist reprobado en `POST
  /mantenimiento/inspeccion/registrar`, que crea una orden con `tipo="correctivo"` fijo y
  `descripcion` autogenerada).
- **Rationale**: Confirmado contra `app/routers/empleado.py`. Resuelve la brecha que antes
  quedaba como `NEEDS VERIFICATION` sobre si CU-O12 tenía un flujo manual independiente.
- **Alternatives considered**: N/A — comportamiento real verificado, no una decisión a evaluar.

### Testing (recomendación, no confirmada como ya existente)
- **Decision**: pytest + `fastapi.testclient.TestClient` para pruebas de los routers FastAPI.
- **Rationale**: Es el stack de pruebas estándar recomendado por la documentación oficial de
  FastAPI para este tipo de aplicación; el usuario no indicó si ya existe una suite de pruebas en
  el repositorio real, ni se solicitó documentar testing en esta sesión.
- **Alternatives considered**: `unittest` puro — descartado como recomendación por mayor
  verbosidad sin beneficio adicional sobre pytest para este stack.

### Estados de `bicicletas` — confirmados contra el esquema real (antes `NEEDS VERIFICATION`)
- **Decision**: El campo `estado` de `bicicletas` es un `select` con exactamente 4 opciones,
  confirmado directamente contra el esquema real de la colección en el panel de administración de
  PocketBase: `disponible`, `en_uso`, `mantenimiento`, `retirada`. `reservada` **no** es una de las
  opciones (consistente con que no existe un paso de reserva separado del inicio de viaje).
  `retirada` sí existe, aunque su disparador no se observó en `ciclista.py`/`empleado.py`;
  probablemente se asigna desde `admin.py`/`gerente.py` para dar de baja una bicicleta de forma
  permanente (robo, daño irreparable, fin de vida útil) — fuera del alcance operativo de
  `spec.md`.
- **Rationale**: Confirmado directamente contra el esquema de PocketBase, no contra el código de
  los routers revisados.
- **Alternatives considered**: N/A — esquema real verificado, no una decisión a evaluar.

### Bloqueo por pago pendiente (FR-008) — mecanismo real (antes `NEEDS VERIFICATION`)
- **Decision**: No existe ningún campo persistido de "bloqueado" en `users`. El bloqueo se calcula
  en tiempo de ejecución en cada intento de reserva (`POST /ciclista/reservar`, función
  `reservar()`), mediante dos consultas a `pagos`: (1) existe algún pago del ciclista con
  `estado` en `"pendiente_efectivo"` o `"verificacion_pendiente"` → rechaza con "Tienes pagos
  pendientes..."; (2) más de 2 pagos del ciclista con `estado="rechazado"` → bloquea con "Tu
  cuenta ha sido bloqueada temporalmente por pagos rechazados...".
- **Rationale**: Confirmado contra `app/routers/ciclista.py`.
- **Alternatives considered**: N/A — comportamiento real verificado, no una decisión a evaluar.

## Puntos pendientes restantes

No quedan puntos `NEEDS VERIFICATION` abiertos en el conjunto de documentos de la especificación
001-operaciones-alquiler-bicicletas.
