# Hoja de ruta — UrbanBike
Actualizado: 29 de julio de 2026, según indicaciones de clase del docente.

Este documento es el punto de partida de cualquier sesión futura con Claude
Code. Léelo junto con `docs/design-system.md` y `docs/REDISENO_UI.md` antes
de empezar a trabajar.

## 0. ~~PRIORIDAD ALTA — riesgo de ORDER BY en ReplacingMergeTree~~ — RESUELTO el 06 de agosto de 2026

El bug que rompió `bicicletas` el 30 de julio (`ORDER BY (estado, id)`
con `estado` cambiando en vivo — ReplacingMergeTree no deduplica si la
clave de orden completa no coincide, y `ALTER ... UPDATE` sobre una
columna de esa clave falla directo con `CANNOT_UPDATE_COLUMN`) **no era
exclusivo de `bicicletas`**. El mismo patrón de diseño (una columna de
estado/valor mutable dentro del `ORDER BY`) se repetía en
`db/01_operativa_schema.sql` en once tablas más.

**Las once ya están corregidas**: `alquileres` y `ordenes_mantenimiento`
(30-jul-2026, ver secciones 9 y 10) y, en esta sesión (06-ago-2026, ver
sección 19), las nueve restantes: `usuarios`, `garantias`, `pagos`,
`promociones`, `repuestos`, `mantenimientos_programados`,
`infracciones`, `cobros_automaticos`, `inspecciones`. Auditoría previa
confirmó que ninguna de las nueve había recibido jamás un `UPDATE` real
desde la app (cero riesgo de pérdida de estado en vivo, a diferencia de
`bicicletas`), así que las nueve se recrearon en una sola sesión de
trabajo con `ORDER BY id` (o `(fecha, id)` en las dos con partición
mensual: `pagos`, `infracciones`), sin perder ninguna fila real. Ver
sección 19 para el detalle completo (conteos antes/después, y el caso
especial de `usuarios` con los 2 usuarios reales de producción).

## 1. Correcciones a decisiones ya tomadas

Estas tres reemplazan decisiones anteriores. Ningún código real depende
todavía de las dos primeras, así que no hay nada que deshacer, solo ajustar
el plan antes de construir la fase 2.

1. **Frecuencia del ETL con Airflow: cada 1 hora**, no cada 15 minutos como
   se había diseñado antes.
2. **Partición de la base de datos: tres bases separadas en ClickHouse**,
   no dos. `urbanbike_operativa` (ya existe), `urbanbike_tactica` y
   `urbanbike_estrategica`. **RESUELTO el 29 de julio de 2026**: las dos
   bases nuevas quedaron creadas con su esquema completo (sin datos
   todavía, ver detalle en la sección 7).
3. **Los KPI siempre se precalculan en el proceso ETL y se guardan en la
   base de datos.** Nunca se calculan en el momento de la consulta. Esto
   ya era el criterio de diseño (vistas materializadas); ahora es un
   requisito explícito del docente.

## 2. Arquitectura de datos: carpeta `datos/`

**RESUELTO el 29 de julio de 2026**: carpeta creada en la raíz del
proyecto, con tres subcarpetas por etapa (vacías por ahora, solo
`.gitkeep`; el contenido `.parquet` no se versiona, ver `.gitignore`).
Detalle de qué va en cada una: `docs/datos_README.md`.

```
datos/
  crudo/
  proceso/
  terminado/
```

El DAG de Airflow (cada hora, ver sección 18, resuelto) mueve los datos
entre estas tres etapas y hacia las tres bases de ClickHouse. El dato
que se guarda de forma permanente es el de `terminado/`.

## 3. Patrón de navegación (aplica a todo el sistema, no a un módulo)

- Cada pantalla indica en la parte superior el título del módulo actual
  (ejemplo: "Alquiler de Bicicletas"), para que el usuario siempre sepa
  dónde está.
- Botón de "volver" visible en cada pantalla.
- El logo o el menú principal siempre regresa al dashboard de inicio del
  rol actual.
- Cero emojis en cualquier pantalla.
- Toda imagen es clickeable para ampliarse en una vista más grande
  (lightbox).
- El diseño de los dashboards sigue el patrón visual Z o F, el que
  corresponda según el tipo de contenido de esa pantalla.
- Tamaño mínimo de letra estándar en todo el sistema; ninguna pantalla
  debe quedar con texto ilegible.

El objetivo declarado por el docente es que el usuario aprenda el patrón
una sola vez y navegue el resto del sistema en automático.

## 4. WorkPanel — patrón para el nivel operativo

No es una pantalla aislada nueva: es un patrón a aplicar en los módulos
operativos que ya existen (inventario, alquileres, órdenes de
mantenimiento, etc.), pensado para los empleados.

Estructura:
1. Lista paginada de registros.
2. Filtro por criterio de búsqueda (ejemplo: cédula, nombre, fecha).
3. Al seleccionar un registro, se entra a un "modo": Insertar, Actualizar,
   Eliminar o Ver, según la acción que corresponda.

## 5. Sin confirmar todavía

En los apuntes de clase aparece una proporción "DB_OP 800 / DB_TAC 150 /
DB_EST 50, total 1000", que probablemente representa cómo se reparte el
volumen de consultas entre los tres niveles como argumento para justificar
la partición en tres bases. Washington debe confirmar el significado
exacto antes de usarlo en cualquier documento académico.

## 6. Pendientes de sesiones anteriores (sin resolver)

1. Reportes completos por rol, exportables a PDF y Excel con el formato
   de la empresa, con vista de grilla registro por registro.
2. Fotos reales de bicicletas, con lightbox al hacer clic —
   **RESUELTO el 30 de julio de 2026** para `admin/bicicletas.html` y
   `gerente/bicicletas.html` (ver sección 9): la foto se sube a
   PocketBase (solo como hosting de archivo) y el puntero real queda en
   `urbanbike_operativa.bicicleta_fotos`, con lightbox ya aplicado. La
   auditoría del 14 de agosto de 2026 (ver sección 60) encontró que ese
   "ya aplicado" cubría la tabla pero no los modales de edición de esos
   mismos dos archivos, ni `perfil.html`, ni los modales de
   `admin/usuarios.html` — los 5 huecos reales quedaron corregidos ese
   día con el mismo `lightbox.js`.
3. Promociones y descuentos: el gerente las define, el empleado de
   operación las administra. **Mitad resuelta el 06-ago-2026** (ver
   sección 20): el gerente ya tiene un WorkPanel completo para definirlas
   y el descuento ya se aplica de verdad en el precio del catálogo del
   ciclista. La mitad de "el empleado de operación las administra"
   sigue pendiente — no se construyó ninguna pantalla para operación
   hoy, no se pidió.
4. Recibos y facturas guardados en el historial del ciclista.
5. Rediseño visual más audaz: llevar el elemento distintivo (línea de
   ruta) más allá de los tres componentes ya hechos, hacia el cascarón
   general del sistema. **Avance parcial el 06-ago-2026** (ver sección
   22): cuarto componente real construido (`flujo_orden.html`, panel de
   mantenimiento). Sigue pendiente la parte más grande del pedido del
   docente — extenderlo al cascarón general (navegación, dashboards,
   etc.), no solo a fichas de detalle puntuales como las cuatro ya
   hechas.
6. ~~Función para que el gerente edite precios.~~ **RESUELTO el
   06-ago-2026** (ver sección 21): el modal de `gerente/tarifas.html`
   editaba una colección de PocketBase completamente desconectada del
   precio real — no cambiaba nada de lo que veía el ciclista. Repuntado
   a `urbanbike_operativa.tarifas`, probado en vivo (editar un precio
   real y ver el catálogo reflejarlo).
7. ~~Agregar la modalidad de tarifa "semana".~~ **RESUELTO el
   06-ago-2026** (ver sección 21): 8 tarifas reales creadas (4
   categorías × 2 membresías), consulta y catálogo del ciclista
   ampliados, toggle "por semana" agregado.
8. Migrar los viajes y pagos reales hacia `alquileres` y
   `alquiler_eventos` — **RESUELTO el 30 de julio de 2026**, ver
   sección 8.
9. Conectar datos reales al flujo del alquiler y al checklist de
   devolución (depende del punto 8, que ya está resuelto). El flujo del
   alquiler ya está conectado (secciones 9/10). El checklist de
   devolución: **Nivel 2 y Nivel 3 resueltos (06/07-ago-2026, ver
   sección 23)** — el resultado de la inspección (orden de
   mantenimiento, infracción, cargo por daños, estado real de la
   bicicleta) ya mueve las tablas reales de ClickHouse, no solo
   PocketBase.
10. Enlazar el catálogo con estaciones — ya resuelto en la sesión
    anterior, se deja aquí solo como registro de que está cerrado.
11. El pago tipo `cargo_danos` ($10, viaje PocketBase
    `fumbsv0bu4ell6t`) no se migró: no encaja en `alquileres`, le
    corresponde a `garantias`/`cobros_automaticos`/`infracciones`,
    tablas que no se han conectado a datos reales todavía.
12. `resumen_mensual_flota` en `urbanbike_estrategica` sigue sin
    calcularse para ningún mes. **Parcialmente resuelto el 07-ago-2026**
    (ver sección 28): la tabla `bicicleta_eventos` ya existe y
    `bicicletas_repo.actualizar()` ya registra cada cambio de estado
    real. Sigue pendiente el cálculo en sí, porque el historial recién
    empieza a acumularse desde hoy -- no hay todavía ningún mes
    completo que resumir (y no se reconstruye lo anterior, ver sección
    28).
13. ~~**Airflow no existe en el proyecto todavía**~~ (**resuelto el
    06-ago-2026**, ver sección 18): servicio en `docker-compose.yml`,
    DAG `urbanbike_etl_hourly` orquestando `etl/07_migrar_viajes_pagos.py`
    → `08_calcular_tactica.py` → `09_calcular_estrategica.py` cada hora,
    probado en vivo y activado.
14. **Puente temporal: espejo de bicicletas hacia PocketBase**
    (agregado el 30 de julio de 2026, ver sección 9). Existe
    únicamente porque el flujo de reserva del ciclista
    (`ciclista/detalle_bicicleta.html`, resolución de estación por
    nombre, creación del "viaje") todavía depende de PocketBase de
    punta a punta. **Pendiente: migrar el flujo de reserva del ciclista
    a ClickHouse, y una vez hecho, eliminar el espejo por completo**
    (`_espejar_pocketbase` en `app/db/bicicletas_repo.py` y todas sus
    llamadas). No es arquitectura final — sin esta nota corre el
    riesgo de quedarse para siempre. **Sigue abierto** (21-ago-2026,
    ver sección 81): se aplicó un parche puntual sobre una
    manifestación concreta de este mismo desfase (checkbox de reserva
    grupal ofrecido para una bici ya no disponible), NO la migración de
    fondo de este punto — cualquier otra pantalla que confíe en el
    `estado` de ClickHouse para una acción (no solo para mostrarlo)
    puede tener el mismo bug hasta que este punto se resuelva de raíz.
15. **Riesgo de ORDER BY en más tablas** — ver sección 0 (prioridad
    alta): el mismo bug de `bicicletas.estado` existe también en
    `alquileres`, `usuarios`, `garantias`, `pagos`, `promociones`,
    `repuestos`, `ordenes_mantenimiento`, `mantenimientos_programados`,
    `infracciones`, `cobros_automaticos` e `inspecciones`. Corregir
    antes de construir el siguiente WorkPanel que actualice cualquiera
    de estas.
16. ~~**Residuos huérfanos de las bicicletas fantasma del seed
    original**~~ (**resuelto el 06-ago-2026**, ver sección 19)
    (`UB-014`/`EB-003`/`UB-072`, ids `55555555-...-0001/0002/0003` de
    `db/02_operativa_seed.sql`), encontrados el 30 de julio de 2026 al
    limpiar `UB-012`/`UB-013` de prueba (`bicicleta_fotos` ya se había
    limpiado esa misma sesión). El alcance original de esta limpieza
    era: `mantenimientos_programados` (2 filas), `ordenes_mantenimiento`
    (1 fila) y el alquiler seed `A-010482` en `alquileres`. **Se amplió
    en esta sesión** al auditar las 9 tablas de la sección 0: se
    encontró un cuarto residuo no documentado (`inspecciones`, 1 fila,
    misma bicicleta fantasma `UB-014`), y al borrar `A-010482` se
    identificaron y limpiaron en la misma operación las 6 filas que
    dependían de él (`alquiler_eventos`: 5, `garantias`: 1, `pagos`: 1,
    `facturas`: 1, `factura_detalle`: 1, `inspecciones`: 1 — la misma
    fila del cuarto residuo, contada una sola vez). Verificado con un
    barrido de `LEFT ANTI JOIN` sobre todas las columnas `id_bicicleta`,
    `id_alquiler` e `id_usuario` del esquema, no solo las tablas ya
    conocidas: cero referencias rotas en todo el sistema. Ver sección 19
    para el detalle completo.
17. ~~**Enlace frágil entre `alquileres.id` (ClickHouse) y el `viaje_id`
    original de PocketBase**~~ (**resuelto el 06-ago-2026**, ver sección
    18): se agregó la columna real `alquileres.id_origen_pocketbase`,
    se hizo el backfill de los 26 alquileres ya migrados a partir del
    rastro de texto libre que tenían, y `mapa_alquiler_por_viaje_pocketbase`
    (`app/db/clickhouse.py`) ahora lee esa columna en vez de parsear
    `alquiler_eventos.observacion` con regex. El texto libre en
    `observacion` se sigue escribiendo (es útil como bitácora legible),
    pero ya no es la fuente de verdad del enlace.
18. **PRIORIDAD ALTA — `admin/estaciones.html` Y `admin/tarifas.html`
    desconectadas de `urbanbike_operativa`** (encontrado 07-ago-2026,
    ver sección 31): las dos siguen 100% contra colecciones viejas de
    PocketBase, mostrando datos distintos de sus equivalentes reales en
    Gerente (`gerente/estaciones.html`/`gerente/tarifas.html`, ya
    conectadas desde la sección 21/26). Sin resolver todavía.
19. **Auto-bloqueo por 3 infracciones (`empleado.py`) es
    estructuralmente inalcanzable** (encontrado 11-ago-2026, ver
    sección 45): `reservar()` ya bloquea cualquier reserva nueva desde
    la primera infracción pendiente (no solo la tercera), así que un
    ciclista nunca puede llegar a acumular una segunda o tercera por el
    camino real -- necesitaría las tres pendientes a la vez, pero no
    puede generar la siguiente sin resolver la anterior primero. El
    código del umbral (`>= 3`) es correcto; su condición simplemente no
    se cumple nunca en producción. Pendiente de decisión de negocio,
    sin corregir todavía: bajar el umbral del auto-bloqueo, o relajar
    la regla de `reservar()` para que permita reservar con alguna
    infracción pendiente.

## 7. Partición en tres bases — detalle de lo resuelto (29 jul 2026)

Esquemas creados y verificados contra ClickHouse real (contenedor
`urbanbike_clickhouse`), sin datos todavía. DDL en `db/04_tactica_schema.sql`
y `db/05_estrategica_schema.sql`, siguiendo las convenciones de
`db/01_operativa_schema.sql`.

**`urbanbike_tactica`** — esquema en estrella, alimentado desde
`urbanbike_operativa` (no desde el CSV crudo de Citibike, que vive
aparte en la base `urbanbike` de `etl/sql/`):
- `fact_viajes` — un renglón por alquiler cerrado.
- `dim_tiempo`, `dim_estaciones`, `dim_tipos_bicicleta` (grano modelo,
  no unidad física), `dim_usuario` (segmentación, sin datos de
  contacto), `dim_tarifa` (espejo de `tarifas`: categoría × membresía ×
  modalidad).
- `kpi_resultados` — un renglón por corrida del ETL y por objetivo
  táctico: `id_objetivo`, `codigo_kpi`, `valor`, `fecha_calculo`,
  `departamento`. Vacía hasta la próxima sesión.

**`urbanbike_estrategica`** — consolidados mensuales, alimentados desde
`urbanbike_tactica` (nunca directo desde la operativa):
- `resumen_mensual_ingresos` (ingresos, gastos, ganancia neta).
- `resumen_mensual_demanda` (viajes y duración promedio por estación).
- `resumen_mensual_flota` (disponibilidad y desgaste por categoría).

**Confirmado por Washington (29-jul-2026)**: el esquema de
`urbanbike_tactica` coincide exactamente con el documento académico
(el documento no está en el repo, solo en los apuntes de clase). El
diseño de `dim_usuario` y `dim_tarifa`, inferido de
`urbanbike_operativa.usuarios` y `.tarifas` por no encontrarse el
documento en `specs/`/`docs/`, quedó validado tal cual está — no
requiere ajustes antes de construir el ETL.

**Actualización 30-jul-2026**: la migración real de datos, el cálculo
de KPI y los consolidados mensuales ya se resolvieron (ver sección 8).
Lo único que sigue pendiente de esta lista es el DAG de Airflow que
cargue cada 1 hora hacia estas dos bases (ver punto 13, sección 6).

## 8. Migración de viajes/pagos reales + ETL tactica/estrategica — RESUELTO el 30 de julio de 2026

**Airflow**: no existe en el proyecto (sin servicio en
`docker-compose.yml`, sin contenedor corriendo, sin carpeta de DAGs, sin
mención en ningún `requirements.txt`). Confirmado antes de empezar, tal
como se pidió. El ETL de hoy se construyó como scripts de Python
ejecutables a mano; la orquestación con Airflow (cada 1 hora) sigue
pendiente para una sesión dedicada aparte.

**Numeración de los scripts**: el pedido original nombraba
`etl/07_calcular_tactica.py` y `etl/08_calcular_estrategica.py`, pero la
migración de viajes/pagos (parte 1) también necesitaba un número de
secuencia y no tenía uno asignado. Se corrió la numeración un lugar:
`etl/07_migrar_viajes_pagos.py` (parte 1), `etl/08_calcular_tactica.py`
(parte 2), `etl/09_calcular_estrategica.py` (parte 3).

**Relación viajes↔pagos en PocketBase (antes de migrar)**: 26 viajes,
todos `estado='completado'` (no hay ningún `activo` ni `cancelado` en
los datos reales de hoy). 22 pagos: 21 son pagos de alquiler normales,
1 es un cargo por daños (`tipo='cargo_danos'`, fuera de alcance, ver
punto 11 de la sección 6). De los 21: 18 `pagado`, 3 `pendiente`. 5
viajes no tienen ningún pago asociado. 18+3+5=26, sin huérfanos.

**Migración (`etl/07_migrar_viajes_pagos.py`)** — decisiones
confirmadas con Washington antes de insertar:
- **Usuario faltante**: ni el ciclista real (Adrian Guizado,
  `ciclista@urbanbike.com`) ni el empleado que confirma pagos en
  efectivo (Test Empleado, `empleado@urbanbike.com`) existían en
  `urbanbike_operativa.usuarios`. Se crearon ambos (`U-0011`, `U-0012`),
  idempotente por email.
- **Tarifa histórica**: la categoría real se resuelve desde
  `bicicleta_codigo → bicicletas.id_modelo → categoria` (no desde
  `pagos.tipo_bicicleta`, que usa nomenclatura Citibike y no coincide
  con el catálogo real); modalidad `hora` para los 21 con pago
  (todos usan `precio_hora`); el monto guardado en
  `subtotal`/`total` es el `monto_total` real del pago histórico, no el
  precio de la tarifa vigente hoy (los precios cambian con el tiempo).
- **5 viajes sin pago**: `id_tarifa` en UUID sentinela
  (`00000000-0000-0000-0000-000000000000`, mismo patrón que "sin
  estación asignada"), montos en 0.
- **Cargo por daños**: fuera de alcance hoy (punto 11, sección 6).
- **Viaje outlier real** (`7j39ut1z9ztgan3`, UB-001, 2026-06-07 a
  2026-06-22, 20,457 min): confirmado por Washington como prueba propia
  de desarrollo, no un alquiler real. Se agregó la columna
  `es_prueba UInt8 DEFAULT 0` a `urbanbike_operativa.alquileres` y a
  `urbanbike_tactica.fact_viajes` (DDL actualizado en
  `db/01_operativa_schema.sql` y `db/04_tactica_schema.sql`, más
  `ALTER TABLE` aplicado en vivo). Ese viaje quedó con `es_prueba=1`;
  todos los demás en 0. **Todo KPI/informe que calcule duración,
  ingresos o promedios debe filtrar `WHERE es_prueba = 0`.**

Resultado: 26 alquileres migrados (8 `devuelto`, 18 `facturado`) +
alquiler_eventos con línea de tiempo completa por cada uno, respetando
la regla de no inventar `inspeccionado`/`cerrado` para migrados.

**ETL táctico (`etl/08_calcular_tactica.py`)**: carga completa (no
incremental) de las 5 dimensiones + `fact_viajes` (26 viajes reales,
el seed de ejemplo `A-010482` no entra porque referencia una bicicleta
que no existe en el catálogo real — correcto, no es un bug). 3 KPI de
ejemplo calculados en `kpi_resultados`: `KPI-INGRESOS-CONFIRMADOS`
(gerencia, 2.21), `KPI-DURACION-PROMEDIO-MIN` (operación, 44 min),
`KPI-FLOTA-EN-MANTENIMIENTO-PCT` (mantenimiento, 36.36%, desde el
catálogo real de 11 bicicletas). Los códigos `id_objetivo`/`codigo_kpi`
son nombres descriptivos propios: el documento académico con el
catálogo real de objetivos tácticos no está en el repo (solo el
esquema fue confirmado contra él), así que estos códigos están sujetos
a renombrarse si aparece el catálogo real.

**Informes que NO se pueden calcular todavía con sentido** (en vez de
forzarlos):
- Cualquier comparación mes a mes o tendencia temporal: solo hay ~7
  semanas parciales de datos, ningún mes completo hasta hoy salvo junio.
- KPI por estación con volumen significativo: 26 viajes repartidos en
  9 estaciones reales (~3 por estación).
- Segmentación por usuario o por tipo de membresía: todo el dataset
  real es un solo ciclista (`member`), no hay diversidad de clientes
  todavía.
- Verificación de ganancia real (ingresos − gastos): `gastos` no tiene
  datos reales migrados, así que "ganancia neta" hoy es en realidad un
  techo (ingresos sin restar costos), no una ganancia real.
- `resumen_mensual_flota`: no hay historial de estado de la flota por
  fecha, solo el snapshot actual (ver punto 12, sección 6).

**ETL estratégico (`etl/09_calcular_estrategica.py`)**: el único mes
calendario ya cerrado con datos reales es **junio 2026** (12 viajes
reales, excluyendo `es_prueba`) — se calculó
`resumen_mensual_ingresos` y `resumen_mensual_demanda` para ese mes.
**Julio 2026 se omitió a propósito**: el mes todavía no termina (faltan
el 30 y 31), así que un "total de julio" hoy sería parcial y engañoso
presentado como cierre de mes. El script vuelve a evaluarlo solo
cuando el mes haya terminado.

## 9. WorkPanel de bicicletas + unificación de fuente de datos — RESUELTO el 30 de julio de 2026

**Auditoría inicial**: `empleado/operacion/inventario.html`,
`admin/bicicletas.html` y `gerente/bicicletas.html` (las tres pantallas
de bicicletas que existían) leían y escribían contra la colección
`bicicletas` de **PocketBase**, no contra
`urbanbike_operativa.bicicletas` en ClickHouse — dos fuentes de verdad
distintas para el mismo dato, coincidiendo solo porque una se usó para
construir la otra en una sesión anterior. Corregido hoy: las tres
apuntan ahora a ClickHouse.

**Repositorio compartido**: `app/db/bicicletas_repo.py` — una sola
implementación de acceso a datos (`listar` con filtro+paginación,
`obtener`, `crear`, `actualizar`, `eliminar`, `listar_modelos`,
`listar_estaciones`) usada por los tres routers
(`empleado.py`/`admin.py`/`gerente.py`). Insertar/Actualizar siempre
seleccionan un modelo (marca+categoría) ya existente en
`modelos_bicicleta`, nunca crean marca/modelo nuevos.

**Bug real encontrado y corregido en el esquema**: la tabla
`bicicletas` tenía `ORDER BY (estado, id)`. ReplacingMergeTree solo
deduplica filas con la clave de orden **completa** idéntica, así que
cambiar `estado` (que es parte de esa clave) por INSERT de "nueva
versión" no reemplazaba la fila, creaba una duplicada; y un
`ALTER ... UPDATE` sobre `estado` directamente falla con
`CANNOT_UPDATE_COLUMN` porque es columna de la clave de orden. Se
recreó la tabla con `ORDER BY id` (11 filas reales migradas sin
pérdida, `db/01_operativa_schema.sql` actualizado para reflejar el
esquema correcto) y `actualizar()`/`eliminar()` usan
`ALTER TABLE ... UPDATE/DELETE` con `mutations_sync=1` (cambios
visibles de inmediato, no async). **Ver sección 0 (prioridad alta):**
el mismo riesgo existe en otras diez tablas, todavía sin corregir.

**Regla de "Eliminar"** (confirmada con Washington antes de
implementar): si la bicicleta tiene alquileres reales asociados, el
borrado se bloquea con un mensaje explicando por qué y sugiriendo
cambiar el estado a "Retirada"; si no tiene ninguno, se borra de verdad
(`ALTER ... DELETE`).

**Espejo hacia PocketBase (puente temporal, ver punto 14 de la sección
6)**: `crear`/`actualizar`/`eliminar` también reflejan el cambio en la
colección `bicicletas` de PocketBase (buscada por `codigo`), porque el
flujo de reserva del ciclista todavía depende de PocketBase de punta a
punta y no se migra hoy. El espejo es best-effort: si falla, se
registra con `logger.error` (visible en la consola del proceso) pero
**nunca revierte ni bloquea** la operación real en ClickHouse, que ya
tuvo éxito antes de intentar el espejo.

**Fotos**: `admin/bicicletas.html` y `gerente/bicicletas.html` siguen
subiendo la foto a PocketBase (solo como hosting de archivo, aprovechando
el registro espejo), pero el puntero real se guarda en
`urbanbike_operativa.bicicleta_fotos` — resuelve el punto 2 de la
sección 6.

**WorkPanel completo en `empleado/operacion/inventario.html`**: lista
paginada (10 por página) con filtro por código/marca/modelo, marca,
categoría y estado; y los 4 modos —
`empleado/operacion/inventario_form.html` maneja Ver/Actualizar/Insertar
según `modo`, Eliminar es un diálogo de confirmación sobre la vista Ver.
`admin/bicicletas.html` y `gerente/bicicletas.html` mantuvieron su propio
CRUD en modales (sin paginación/filtro nuevo, no se pidió), solo
repuntado a la fuente correcta.

**Verificación cruzada real**: se creó `UB-013` desde
`admin/bicicletas.html` (con foto) y se confirmó visible con los mismos
datos en `gerente/bicicletas.html`, en
`empleado/operacion/inventario.html`, en el espejo de PocketBase, y en
el catálogo del ciclista (`ciclista/alquilar.html` →
`ciclista/bicicleta/{id}`, incluida la foto) — las cinco superficies
coinciden.

**Las 4 operaciones del WorkPanel, probadas contra ClickHouse real**:
- **Ver**: `UB-011`.
- **Actualizar**: `UB-011` (observación cambiada, visible de inmediato).
- **Eliminar bloqueado**: `UB-009` (1 alquiler real) → rechazado con el
  mensaje esperado, sin cambios en la fila.
- **Eliminar real**: `UB-011` (0 alquileres reales) → borrada de
  ClickHouse y de su espejo en PocketBase, confirmado con `count()=0`
  en ambos.
- **Insertar**: `UB-012` (modelo Giant Explore E+), y `UB-013` (con
  foto, desde `admin/bicicletas.html`) — ambas quedan en el sistema
  como evidencia visible en el navegador.

**Punto 5 confirmado resuelto**: gracias al espejo, `UB-012` y `UB-013`
(creadas hoy solo a través de las pantallas ClickHouse) ya aparecen en
el catálogo del ciclista con su `detalle_url` funcionando — antes del
espejo, una bicicleta nueva hubiera quedado invisible para ese flujo.

**Nota aparte, no relacionada con el WorkPanel**: la cuenta de prueba
`operacion@urbanbike.com` no podía iniciar sesión (`verified=false` en
PocketBase); se corrigió para poder probar el WorkPanel como ese rol.

## 10. WorkPanel de alquileres + corrección de ORDER BY — RESUELTO el 30 de julio de 2026

**Auditoría inicial**: `empleado/operacion/alquileres.html` (lista,
"Alquiler manual", "Completar", "Cancelar") leía y escribía **100%
contra PocketBase** (`viajes`, `bicicletas`, `estaciones`) — mismo
patrón que bicicletas antes de su fix. La única pieza que ya tocaba
ClickHouse era "Ver flujo" (migrada más temprano el mismo día). Sin
paginación, sin filtro libre (solo un `<select>` de estado). Corregido
hoy: las 4 acciones ahora leen/escriben `urbanbike_operativa.alquileres`.

**Corrección de ORDER BY (antes de tocar nada más, como se pidió)**:
`alquileres` tenía `ORDER BY (estado, fecha_reserva, id)` — mismo bug
que `bicicletas` (sección 9). Recreada con `ORDER BY (fecha_reserva,
id)`, los 27 registros reales (25 migrados + 1 outlier `es_prueba` +
1 seed) migrados sin pérdida, `db/01_operativa_schema.sql` actualizado.
Verificado con un `ALTER ... UPDATE estado` de prueba antes de construir
el resto.

**"Eliminar" = "Cancelar"** (confirmado antes de implementar): cambia
`estado` a `'cancelado'`, solo permitido desde `reservado`/`en_curso`;
bloqueado con mensaje explícito si ya está `facturado` (o más adelante)
— cancelar algo cobrado sería una nota de crédito, fuera de alcance.

**"Insertar" = alquiler manual presencial** (confirmado antes de
implementar): crea un **usuario real nuevo** en `usuarios`
(rol=`ciclista`, sin correo si no se captura uno, nunca un sentinela
compartido) para cada cliente presencial, resuelve la tarifa real
(`casual`/`hora`) según la categoría de la bicicleta elegida, e inserta
`reservado`+`en_curso` con la misma `fecha_inicio` (recogida inmediata).

**Repositorio compartido**: `app/db/alquileres_repo.py` — `listar`
(filtro por ciclista/bicicleta/estado/fecha + paginación), `obtener`,
`eventos`, `crear_presencial`, `cancelar`, `completar`. **Cada cambio de
estado de bicicleta pasa por `bicicletas_repo.actualizar()`** (mismo
repositorio del WorkPanel de bicicletas) — el espejo hacia PocketBase
se mantiene sincronizado automáticamente, sin duplicar esa lógica aquí.
Esto también corrige la grieta encontrada en el WorkPanel de bicicletas:
antes, crear/cancelar/completar un alquiler solo actualizaba la
bicicleta en PocketBase, nunca en ClickHouse.

**"Completar" no factura**: solo registra la devolución
(`en_curso`→`devuelto`, con `id_estacion_fin`/`minutos_reales` reales).
No calcula ni cobra factura — eso sigue siendo el flujo separado de
`cobrar_presencial.html` (PocketBase, sin tocar hoy), fuera de alcance.

**WorkPanel en `empleado/operacion/alquileres.html`**: lista paginada
(10 por página) con filtro por ciclista/bicicleta, estado y rango de
fechas; fila clickeable → `alquiler_form.html` (Ver con línea de tiempo
real reutilizando `componentes/flujo_alquiler.html`, botones
Completar/Cancelar solo si el estado lo permite) o Insertar (formulario
de alquiler manual). No se tocó `op_alquiler_flujo` (la ruta vieja por
`viaje_id` de PocketBase, pendiente #17) — la nueva vista Ver arma la
línea de tiempo directo con el id real de ClickHouse, sin depender del
enlace frágil.

**Las 4 operaciones, probadas contra ClickHouse real** (ninguno de los
25 alquileres reales estaba en `reservado`/`en_curso`, así que se
crearon de prueba, marcados `es_prueba=1`, sin tocar los reales):
- **Insertar**: `A-010509` (UB-005, "Maria Torres"), `A-010511` (UB-003,
  "Lucia Fernandez", vía HTTP real) y `A-010512` (UB-007, "Pedro
  Alvarez") — cada uno creó su usuario real nuevo.
- **Ver**: confirmado con línea de tiempo real y detalle correctos.
- **Completar** (Actualizar): `A-010509` y `A-010511` →
  `devuelto`; `UB-005`/`UB-003` → `disponible` en la estación de
  devolución, confirmado con SELECT cruzado.
- **Cancelar** (Eliminar): `A-010510` y `A-010512` → `cancelado`;
  `UB-007` → `disponible`, confirmado con SELECT cruzado.
- **Bloqueo real verificado**: intentar cancelar `A-010486` (real,
  `facturado`) fue rechazado con el mensaje esperado, sin cambios.

## 11. Cuentas de prueba de PocketBase — revisar antes de grabar (30-jul-2026)

Varias cuentas de rol no podían iniciar sesión y esto se descubrió a
mitad de sesión, no antes: `operacion@urbanbike.com` (sesión anterior),
`mant@urbanbike.com` y `vigil@urbanbike.com` (hoy, al preparar el
WorkPanel de mantenimiento). Las tres se corrigieron reseteando su
password a `Urbanbike123!` vía la API admin de PocketBase.

**Diagnóstico correcto** (corrige lo que se anotó antes): el campo
`verified=false` **no es la causa real** — `admin@urbanbike.com`,
`gerente@urbanbike.com` y `ciclista@urbanbike.com` también tienen
`verified=false` hoy y autentican sin problema. Lo que realmente
bloqueaba el login en los tres casos corregidos era que la contraseña
de esa cuenta específica no era `Urbanbike123!` (probablemente nunca se
sembró igual que las demás, o se cambió en alguna sesión sin
documentar). La confusión con `verified` viene de la sesión anterior,
donde se cambió ese campo a la vez que (sin registrarlo aparte)
probablemente también se corrigió la contraseña.

**Recomendado**: antes de la próxima grabación o demo, verificar las 6
cuentas de rol (`admin@urbanbike.com`, `gerente@urbanbike.com`,
`ciclista@urbanbike.com`, `operacion@urbanbike.com`,
`mant@urbanbike.com`, `vigil@urbanbike.com`) contra `Urbanbike123!` de
una sola vez, en vez de descubrirlo una por una a mitad de sesión. Las
6 quedaron confirmadas funcionando al cierre de hoy (30-jul-2026).

## 12. Fotos reales en gestión de bicicletas + patrón Z/F en dashboards (30-jul-2026)

**Fotos reales — `admin/bicicletas.html` y `gerente/bicicletas.html`**:
mostraban el ícono genérico en vez de la foto real porque
`urbanbike_operativa.bicicleta_fotos` está completamente vacía hoy (0
filas) para las 10 bicicletas reales originales — nunca se subió foto
por ese camino para ellas. Sus fotos reales sí existen en PocketBase
(`bicicletas.foto`). Se aplicó el mismo respaldo que ya usa
`ciclista.py` (`_catalogo_bicicletas`): ClickHouse primero, PocketBase
como respaldo (buscado por código), ícono solo si ninguna de las dos
tiene nada. Probado con las 10 bicicletas reales.

**Patrón Z/F en los 6 dashboards de rol** — decisión tomada según
densidad de contenido y si hay una sola acción dominante o varias de
igual peso (no una elección cosmética):

- **Admin → F**: 12 piezas (4 KPI + 2 gráficas + 2 tarjetas de info +
  4 accesos), sin una sola acción dominante — el usuario escanea
  secciones. Se agregó una etiqueta de sección ("Actividad del
  sistema") para reforzar la jerarquía de la banda de gráficas; el
  orden de secciones (KPIs → gráficas → info → accesos) ya era
  correcto y no se reestructuró.
- **Gerente → F**: 9 piezas (4 KPI + 3 gráficas + 2 accesos), mismo
  caso — contenido analítico sin CTA único. Se agregaron etiquetas de
  sección ("Analítica del período", "Accesos rápidos"); el orden ya
  era correcto.
- **Empleado-Operación → F**: 2 accesos de igual peso (Inventario /
  Alquileres), no uno solo, más 4 KPI y una gráfica. **Se corrigió una
  violación real del patrón**: la gráfica y los accesos estaban
  mezclados en la misma fila; se separaron en dos bandas apiladas
  (gráfica primero, accesos después), con sus etiquetas de sección.
- **Empleado-Mantenimiento → F**: igual criterio, por consistencia (el
  patrón de un dashboard no debe cambiar según si la tabla condicional
  tiene datos o no en un momento dado). **Misma corrección real**: la
  gráfica "Por Tipo" y la tabla "Bicicletas pendientes" estaban
  mezcladas en una sola fila; se separaron en bandas apiladas propias.
- **Empleado-Vigilancia → F**: 9 piezas (4 KPI + duración + gráfica +
  tabla + 2 accesos), la más densa del grupo de empleados. Ya tenía
  bandas apiladas correctas; solo se agregaron etiquetas de sección
  ("Actividad del día", "Accesos rápidos").
- **Ciclista → Z**: único dashboard con una acción dominante clara
  ("Reservar Bicicleta") y poco contenido compitiendo (2 KPIs de
  contexto). Se rediseñó: los 2 KPIs pasaron a ser datos discretos
  (solo número + etiqueta chica) arriba a la derecha, y "Reservar
  Bicicleta" ahora es una tarjeta dominante (más grande, con acento de
  color primario e ícono de 60px), con "Mis Viajes" como tarjeta
  secundaria más chica al lado — el recorrido diagonal Z termina en la
  acción principal.

Los 6 dashboards se probaron uno por uno contra la app real (login por
rol + verificación de enlaces y datos) después de cada cambio, sin
romper ninguno.

## 18. Airflow: DAG horario real para 07/08/09 — RESUELTO el 06 de agosto de 2026

**Auditoría de idempotencia antes de tocar nada** (como se pidió,
porque un DAG cada hora corre los scripts una y otra vez): se
ejecutó cada script dos veces seguidas contra los datos reales y se
encontraron tres problemas reales, ninguno cosmético:

- **`07_migrar_viajes_pagos.py`**: sin ninguna guarda. Cada corrida
  reinsertaba TODOS los viajes de PocketBase como alquileres nuevos
  (UUID nuevo, código nuevo), sin verificar si ya estaban migrados.
  No se probó en vivo una segunda vez a propósito -- la evidencia de
  código ya era concluyente y hacerlo hubiera duplicado los 26
  alquileres reales migrados el 30-jul-2026.
- **`08_calcular_tactica.py`**: `fact_viajes` sí era idempotente
  (`TRUNCATE` + reload), pero las cuatro dimensiones
  (`dim_estaciones`/`dim_tipos_bicicleta`/`dim_usuario`/`dim_tarifa`)
  reinsertaban sin truncar -- físicamente duplicaban cada fila en
  cada corrida (confirmado: `dim_estaciones` pasó de 11 a 22 a 33
  filas crudas en dos corridas). Como `app/routers/gerente.py` hace
  `JOIN` contra estas tablas sin `FINAL` en ningún lado (verificado),
  el DAG cada hora hubiera empezado a duplicar resultados en los
  reportes de gerencia. `dim_tiempo` era peor: usaba `MergeTree`
  simple sin ninguna clave de deduplicación, ni con `FINAL` -- crecía
  sin límite en cada corrida (106 → 160 → 214 filas en dos corridas
  extra, sin tope).
- **`09_calcular_estrategica.py`**: no corrompía nada (usa
  `ReplacingMergeTree` con clave `(anio,mes[,estación])`, correcto
  bajo `FINAL`), pero recalculaba TODOS los meses ya cerrados en cada
  corrida para siempre -- un mes cerrado nunca cambia, así que el DAG
  cada hora hubiera insertado 24 versiones idénticas del mismo mes por
  día sin ningún beneficio.

**Correcciones aplicadas antes de conectar el DAG**:
- `alquileres.id_origen_pocketbase` (columna nueva, `db/01_operativa_schema.sql`):
  clave real de idempotencia de `07`, con backfill de los 26 alquileres
  ya migrados a partir del rastro de texto libre que tenían en
  `alquiler_eventos.observacion`. También reemplaza el enlace frágil
  documentado en el punto 17 de la sección 6 (ahora resuelto):
  `mapa_alquiler_por_viaje_pocketbase` (`app/db/clickhouse.py`) lee la
  columna real en vez de parsear texto con regex.
- `08`: `TRUNCATE TABLE` antes de cada carga de dimensión (mismo patrón
  que ya usaba `fact_viajes`); `dim_tiempo` recreada como
  `ReplacingMergeTree` por consistencia (`db/04_tactica_schema.sql`).
- `09`: guarda que salta cualquier mes que ya tenga fila en
  `resumen_mensual_ingresos` -- un mes cerrado se calcula una sola vez
  en la vida del script.
- Cada script ahora también deja un archivo Parquet real con la fecha y
  hora exacta de la corrida en `datos/crudo` (`07`), `datos/proceso`
  (`08`) y `datos/terminado` (`09`) -- ver `etl/_snapshot.py` y
  `docs/datos_README.md`. Antes de esta sesión `datos/` existía vacía
  (solo `.gitkeep`, ver punto pendiente de sección 2).

**Verificación de idempotencia real, después de corregir** (los tres
scripts corridos dos veces seguidas cada uno): `07` migró los 3 viajes
genuinamente nuevos que habían llegado a PocketBase durante la sesión
(`alquileres` pasó de 31 a 34) y en la segunda corrida saltó los 34 sin
duplicar ninguno; `08` mantuvo conteos exactamente estables en la
segunda corrida (`dim_tiempo`=55, `dim_estaciones`=11,
`dim_tipos_bicicleta`=10, `dim_usuario`=12, `dim_tarifa`=17,
`fact_viajes`=31 -- `kpi_resultados` sigue creciendo por diseño, es un
histórico a propósito); `09` saltó ambos meses (junio y julio 2026,
julio ya cerró durante la sesión) en las dos corridas, sin tocar
`resumen_mensual_ingresos`/`demanda`.

**DAG `urbanbike_etl_hourly`** (`airflow/dags/urbanbike_etl_hourly.py`):
tres `BashOperator` en secuencia (`migrar_viajes_pagos` →
`calcular_tactica` → `calcular_estrategica`), `schedule_interval=timedelta(hours=1)`,
`catchup=False`, `max_active_runs=1`.

**Bloqueo de infraestructura encontrado y corregido al probar**:
`airflow/logs/scheduler/<fecha>/` quedó con permisos `root:root 755`
(ajeno a esta sesión, probablemente de cuando se instaló Airflow), lo
que hacía crashear el `DagFileProcessor` con `PermissionError` al
intentar escribir su log y bloqueaba que el DAG se sincronizara al
scheduler. Corregido con `chmod -R 777 airflow/logs` dentro del
contenedor.

**Prueba real** (tres corridas exitosas confirmadas via
`airflow dags list-runs`, no simulado): dos disparos manuales
(`airflow dags trigger`, equivalente exacto al botón de la interfaz --
el navegador Chrome no estaba disponible en esta sesión, ver nota) más
una corrida automática que el scheduler ya disparó solo para la
ventana 04:00-05:00 en cuanto el DAG quedó activo, confirmando que la
programación horaria funciona de verdad. Las tres tareas terminaron en
`success` en las tres corridas, en el orden correcto. Archivos Parquet
reales confirmados en las tres subcarpetas de `datos/` con timestamp de
cada corrida. Conteos en ClickHouse verificados estables después de
las tres corridas del DAG (sin duplicar ni perder nada):
`operativa.alquileres`=34, `tactica.fact_viajes`=31,
`tactica.dim_tiempo`=55, `tactica.dim_estaciones`=11,
`estrategica.resumen_mensual_ingresos`=2,
`estrategica.resumen_mensual_demanda`=9.

**DAG activado**: `is_paused=False`, `schedule_interval` confirmado en
3600 segundos (1 hora), próxima corrida programada para la ventana
05:00-06:00 UTC.

**Nota sobre la Parte 3 pedida ("desde la interfaz de Airflow")**: el
navegador Chrome no estaba conectado en esta sesión, así que el
disparo manual se hizo con `airflow dags trigger` (CLI), que ejecuta
exactamente el mismo mecanismo que el botón "Trigger DAG" de la
interfaz web y deja el mismo registro en `dags list-runs`. No se
verificó visualmente la interfaz web -- si Washington quiere confirmar
el estado ahí, la UI está en `http://localhost:8080`
(usuario/contraseña en `.env`, `AIRFLOW_ADMIN_USER`/`AIRFLOW_ADMIN_PASSWORD`).

## 19. ORDER BY de las 9 tablas restantes + limpieza ampliada de huérfanos — RESUELTO el 06 de agosto de 2026

**Auditoría (Parte 1, sin tocar nada)**: se revisó el `ORDER BY` real de
`usuarios`, `garantias`, `pagos`, `promociones`, `repuestos`,
`mantenimientos_programados`, `infracciones`, `cobros_automaticos` e
`inspecciones` contra `db/01_operativa_schema.sql`, y se hizo `grep` de
`ALTER TABLE ... UPDATE` en todo `app/` y `etl/`: **ninguna de las
nueve había recibido jamás un `UPDATE` real** (a diferencia de
`bicicletas`, que sí tenía estados cambiados en vivo antes de su fix).
Todas las filas existentes en las 6 tablas no vacías eran de dos tipos:
seed puro de `db/02_operativa_seed.sql` (`garantias`, `pagos`,
`promociones`, `repuestos`, `inspecciones`, y 4 de los 12 usuarios), o
las dos cuentas reales de producción en `usuarios` (`U-0011` Adrian
Guizado, `U-0012` Test Empleado) más 6 usuarios de prueba de WorkPanel
-- ninguna fila real con historial de `UPDATE` que se pudiera perder.
Con eso confirmado, se recrearon las 9 en una sola sesión de trabajo.

**Correcciones aplicadas** (mismo patrón que `bicicletas`/`alquileres`/
`ordenes_mantenimiento`: tabla nueva -> `INSERT SELECT ... FROM vieja
FINAL` -> comparar conteos -> `RENAME` swap -> `DROP` vieja):

| Tabla | ORDER BY anterior | ORDER BY nuevo | Antes | Después |
|---|---|---|---|---|
| `usuarios` | `(rol, id)` | `id` | 12 | 12 |
| `garantias` | `(estado, id_alquiler)` | `id` | 1 | 1 |
| `pagos` | `(estado, fecha, id)` | `(fecha, id)` | 2 | 2 |
| `promociones` | `(estado, fecha_fin, id)` | `id` | 2 | 2 |
| `repuestos` | `(categoria, id)` | `id` | 4 | 4 |
| `mantenimientos_programados` | `(estado, fecha_programada, id)` | `id` | 2 | 2 |
| `infracciones` | `(estado, id_usuario, fecha)` | `(fecha, id)` | 0 | 0 |
| `cobros_automaticos` | `(estado, id_alquiler, id)` | `id` | 0 | 0 |
| `inspecciones` | `(estado, id_alquiler)` | `id` | 1 | 1 |

`pagos` e `infracciones` conservaron `fecha` (inmutable, coincide con
su `PARTITION BY toYYYYMM(fecha)`), mismo criterio que `alquileres`. El
resto quedó en `id` solo, mismo criterio que `bicicletas`/
`ordenes_mantenimiento`. Cero filas perdidas en las 9. Verificación
especial en `usuarios`: se comparó cada campo de `U-0011` y `U-0012`
antes/después (id, código, nombre, apellido, email, rol, estado,
fecha_registro) -- idénticos.

**Limpieza de huérfanos (Parte 3), ampliada más allá del pendiente 16
original**: además de los 3 residuos ya documentados, la auditoría de
la Parte 1 encontró un cuarto no documentado en `inspecciones` (misma
bicicleta fantasma `UB-014`). Al borrar el alquiler seed `A-010482` se
identificaron y limpiaron en la misma operación 6 filas dependientes
más. Total borrado:

- `mantenimientos_programados`: 2 filas (bicicletas fantasma `UB-014`/`EB-003`).
- `ordenes_mantenimiento`: 1 fila (bicicleta fantasma `UB-072`).
- `inspecciones`: 1 fila (bicicleta fantasma `UB-014` -- hallazgo nuevo).
- `alquileres`: 1 fila (`A-010482`, 34 -> 33).
- `alquiler_eventos`: 5 filas (línea de tiempo de `A-010482`, 123 -> 118).
- `garantias`: 1 fila (1 -> 0).
- `pagos`: 1 fila, la que dependía de `A-010482` (2 -> 1; se conservó la
  otra fila seed, que usa el sentinela `00000000...` y no depende de
  ningún alquiler real).
- `facturas`: 1 fila (1 -> 0).
- `factura_detalle`: 1 fila (1 -> 0).

**Verificación final, no solo en las tablas ya conocidas**: barrido de
`LEFT ANTI JOIN` sobre cada columna `id_bicicleta` (`bicicleta_fotos`,
`alquileres`, `mantenimientos_programados`, `ordenes_mantenimiento`,
`inspecciones`), cada columna `id_alquiler` (`alquiler_eventos`,
`garantias`, `cobros_automaticos`, `facturas`, `pagos`, `inspecciones`,
`infracciones`) y cada columna `id_usuario` (`alquileres`, `facturas`,
`pagos`, `metodos_pago`, `gastos`) más los hijos directos de las filas
borradas (`inspeccion_detalle.id_inspeccion`, `orden_repuesto.id_orden`,
`mantenimientos_programados.id_plan`, `garantias.id_metodo_pago`,
`factura_detalle.id_factura`) contra sus tablas padre. Resultado: **cero
filas huérfanas en todo el sistema**.

## 20. Promociones: WorkPanel de Gerente + aplicación real en el precio — RESUELTO el 06 de agosto de 2026

**Auditoría inicial (sin tocar nada)**: `grep -i promocion` en todo
`app/` no daba ningún resultado — la tabla `promociones` (2 filas de
seed, `FINDE15`/`ESTUD20`, `ORDER BY` ya corregido en la sesión
anterior) era completamente invisible en la interfaz, ni para gerente
ni para operación. El cálculo del precio real que ve el ciclista vivía
entero en `_catalogo_bicicletas()` (`app/routers/ciclista.py`), usado
por `ciclista/alquilar.html` (vía `componentes/tarjeta_bicicleta.html`)
y `ciclista/detalle_bicicleta.html` — sin ningún descuento aplicado,
solo la tarifa cruda por categoría.

**Nota de patrón de UI, dejada pendiente a propósito**: hoy Gerente no
tenía ningún WorkPanel real (lista+filtro+paginación+4 modos, el patrón
de `empleado/operación`) — `bicicletas`/`estaciones`/`tarifas` de
Gerente usan CRUD en modales sobre la misma página. El panel de
promociones construido hoy es el primer WorkPanel real dentro del rol
Gerente, calcado a propósito del patrón de operación (decisión
confirmada con Washington antes de construirlo). **Pendiente para una
sesión aparte, si se decide**: unificar el patrón dentro de Gerente —
migrar `bicicletas`/`estaciones`/`tarifas` de modal a WorkPanel, o
mantener la mezcla actual. No se tocó hoy.

**WorkPanel de promociones** (`app/db/promociones_repo.py`,
`app/routers/gerente.py`, `app/templates/gerente/promociones.html` +
`promociones_form.html`, en `/gerente/promociones`): lista paginada
(10 por página) con filtro por código/nombre y estado; los 4 modos
(Ver/Insertar/Actualizar/Eliminar) cubren los campos del esquema
(código, nombre, tipo de descuento, valor, aplica_a con selector
dependiente de categoría/modalidad/bicicleta según corresponda, días de
la semana con checkboxes, vigencia, usos máximos, estado). Validación
del formulario: código/nombre obligatorios, valor > 0, `fecha_fin` no
puede ser anterior a `fecha_inicio` (server-side, más un `min` dinámico
en el input de fecha_fin en el cliente).

**Regla de "Eliminar"** (confirmada con Washington antes de
implementar, mismo criterio que `ordenes_mantenimiento`): si
`usos_actuales > 0`, la promoción ya se aplicó en al menos un alquiler
real y el borrado se bloquea, sugiriendo cambiar el estado a "Pausada"
o "Vencida" en su lugar; si `usos_actuales == 0`, se borra de verdad.

**Bug real encontrado y corregido al probar el modo Actualizar**: el
primer intento de `ALTER TABLE ... UPDATE` en `promociones_repo.actualizar()`
incluía `version = ...` en el `SET` (para "refrescar" la versión de
ReplacingMergeTree). ClickHouse lo rechazó con
`CANNOT_UPDATE_COLUMN` — la columna `version` de un `ReplacingMergeTree`
no se puede tocar con `ALTER ... UPDATE` así no forme parte del
`ORDER BY`, mismo síntoma que el bug histórico de `bicicletas.estado`
pero con otra causa. Corregido quitando `version` del `SET`, igual
patrón que ya usaba `ordenes_repo.py` (que nunca la tocaba).

**Aplicación real del descuento** (`_catalogo_bicicletas()` en
`ciclista.py`): `promociones_repo.activas_hoy()` trae las promociones
con `estado='activa'`, dentro de `fecha_inicio`/`fecha_fin` y con el
día de la semana actual en `dias_semana` (tabla chica, se trae completa
y se filtra en Python). Por cada bicicleta y modalidad (hora/día),
`promociones_repo.promo_aplicable()` evalúa las promociones que
aplican (`todas`, o `categoria`/`modalidad`/`bicicleta` con
`id_referencia` coincidente) y elige la de **mayor ahorro real en
dólares** para ese precio — no la primera que coincide. El descuento
solo se aplica al precio *member* (el que de verdad paga el ciclista
logueado); el precio *casual* de comparación se deja intacto a
propósito.

**Visible, no en silencio**: `tarjeta_bicicleta.html` y
`detalle_bicicleta.html` muestran un badge "Promo" con el nombre de la
promoción y el precio original tachado, reutilizando el mismo patrón
visual que ya existía para el precio sin membresía. En la tarjeta del
catálogo, el toggle JS de hora/día (`alquilar.html`) también intercambia
el precio tachado y el nombre de la promo, y oculta el bloque si esa
modalidad en particular no tiene promoción activa.

**Prueba real, no simulada** (servidor FastAPI levantado, login real
por rol, todo vía HTTP, no llamadas directas a los repos):
- **Insertar**: promoción `PRUEBA-WP` creada de verdad a través de
  `POST /gerente/promociones/crear` (10% de descuento, aplica a todas,
  los 7 días, vigente hoy) — confirmada en ClickHouse.
- **Catálogo del ciclista**: `GET /ciclista/alquilar` logueado como
  `ciclista@urbanbike.com` mostró el descuento real de `ESTUD20` (20%,
  la promoción con mayor ahorro real de las dos activas hoy —
  confirma que `promo_aplicable()` elige la mejor entre varias, no solo
  aplica la primera): USD 3.50/h → USD 2.80/h, USD 28.00/día → USD
  22.40/día, badge visible con el nombre de la promoción.
- **Actualizar**: se pausó `ESTUD20` vía `POST /gerente/promociones/{id}/editar`
  (aquí se encontró el bug de `version` de arriba); con `ESTUD20`
  pausada, el catálogo pasó a mostrar el descuento de `PRUEBA-WP` (10%:
  USD 3.50 → USD 3.15, USD 28.00 → USD 25.20) — confirma que el cálculo
  responde en vivo a cambios reales del panel. Se reactivó `ESTUD20`
  después y el catálogo volvió a mostrar su descuento (20%), sin
  perder datos.
- **Ficha de detalle**: `GET /ciclista/bicicleta/{id}` confirmado con
  el mismo badge y precio tachado en los bloques de hora y día.
- **Eliminar**: promoción descartable creada y borrada de verdad vía
  `POST /gerente/promociones/{id}/eliminar` (`usos_actuales = 0`),
  confirmado con `count() = 0` después.

Estado final de `promociones`: `FINDE15` y `ESTUD20` (seed, sin tocar)
más `PRUEBA-WP` (la promoción real de esta prueba, se deja como
evidencia visible, mismo criterio que las bicicletas/alquileres de
prueba de sesiones anteriores).

## 21. Tarifas: editor real del gerente + modalidad "semana" — RESUELTO el 06 de agosto de 2026

**Auditoría inicial (sin tocar nada)**: se pidió confirmar si "editar
tarifa" en `gerente/tarifas.html` ya cambiaba el precio real, y si
`_catalogo_bicicletas()` ya soportaba `modalidad='semana'`. Encontré
algo más grande que "modalidades limitadas":

- `gerente/tarifas.html` y su router (`gerente.py`) operaban **enteramente
  contra una colección de PocketBase** (`tipo_bicicleta` classic/electric,
  `tipo_usuario` casual/member, un solo `precio_hora`, sin modalidad ni
  categoría) — sin ninguna relación con `urbanbike_operativa.tarifas`,
  la tabla que de verdad lee `_catalogo_bicicletas()`. **"Editar tarifa"
  no cambiaba nada del precio que veía el ciclista, con ninguna
  modalidad.** Mismo patrón de "dos fuentes de verdad" que tenía
  `bicicletas` antes del fix del 30-jul-2026, pero nunca corregido para
  tarifas.
- `_catalogo_bicicletas()` sí tenía un `WHERE modalidad IN ('hora', 'dia')`
  fijo, y el diccionario de precios nunca leía una clave `"semana"`.
  Confirmado en la base real: 16 tarifas (8 `hora` + 8 `dia`, 4
  categorías × 2 membresías), cero `semana`.

Decisión tomada con Washington antes de construir: arreglar la
desconexión del editor de precios en la misma sesión (alcance ampliado
más allá de solo agregar "semana"), en vez de dejar una pantalla que no
sirve para su propósito real.

**Corrección preventiva de `ORDER BY`, antes de construir edición en
vivo**: `tarifas` tenía `ORDER BY (id_categoria, tipo_membresia,
modalidad, vigente_desde)`. Ninguna de esas columnas cambiaba de valor
hasta hoy (la tabla solo se leía), pero como hoy se construía el primer
editor real, se recreó con `ORDER BY id` (mismo criterio que la sección
0/19) antes de escribir `tarifas_repo.py`, para no descubrir
`CANNOT_UPDATE_COLUMN` en producción apenas alguien corrija la
categoría o modalidad de una tarifa existente. 16 filas reales
preservadas sin pérdida.

**`app/db/tarifas_repo.py`** (nuevo): `listar`/`obtener`/`crear`/
`actualizar`/`eliminar` contra `urbanbike_operativa.tarifas`. Regla de
"Eliminar" (mismo criterio que bicicletas/órdenes/promociones):
bloqueada si algún alquiler real referencia esa tarifa (28 alquileres
reales sí referencian una tarifa hoy), sugiriendo cambiar su estado a
"Histórica" en su lugar.

**Bug real encontrado al probar Editar** (mismo síntoma que el de
`promociones_repo` de la sesión anterior, causa distinta cada vez):
el primer intento de `ALTER ... UPDATE` no tocaba `version`
directamente, pero da igual — **cualquier** intento de incluirla falla
con `CANNOT_UPDATE_COLUMN` en un `ReplacingMergeTree`. Se verificó que
`tarifas_repo.actualizar()` nunca la toca, mismo patrón ya establecido.

**`gerente/tarifas.html` reescrito**: la tabla y los modales de
Crear/Editar/Eliminar ahora muestran categoría, membresía, modalidad
(hora/día/semana), precio, minutos de gracia, recargo por minuto,
vigencia y estado — contra los datos reales. Se quitó el botón
"toggleactiva" (el concepto `activa` booleano de PocketBase no existe
en el esquema real; su equivalente, `estado` vigente/histórica, ya se
edita directo en el formulario de Editar).

**8 tarifas reales de modalidad `semana` creadas**, a través del panel
ya arreglado (`POST /gerente/tarifas/crear`, no un script aparte):
criterio de precio `semana = 5 × precio de día` (mismo patrón de
escalado constante que ya existía entre hora y día: `dia = 8 × hora`
en las 16 tarifas originales, sin excepción por categoría). Con eso:
Premium/Estándar/Montaña member 140, casual 180; Eléctrica member 140,
casual 220 (seguía el patrón de tener el precio casual más alto por ser
eléctrica).

**`_catalogo_bicicletas()` ampliado**: `IN ('hora', 'dia', 'semana')`,
`precio_semana_member`/`precio_semana_casual`/`precio_semana_sin_promo`/
`promo_semana` agregados al catálogo, con las promociones activas
aplicándose también a la modalidad semana (`promociones_repo.promo_aplicable()`
ya soportaba cualquier modalidad, solo faltaba invocarlo). El selector
`aplica_a='modalidad'` de promociones también admite `semana` ahora
(`gerente/promociones_form.html`).

**Toggle "por semana"** agregado junto a hora/día en
`ciclista/alquilar.html` (tercer botón + JS generalizado con mapas
`CAMPO_POR_MODALIDAD`/`ETIQUETA_POR_MODALIDAD`/`CAMPO_PROMO_POR_MODALIDAD`
en vez de los ternarios hora/día de antes), `componentes/tarjeta_bicicleta.html`
(nuevo `data-precio-semana` en el precio principal, el comparativo
casual y el bloque de promo) y `ciclista/detalle_bicicleta.html`
(tercer bloque "Por semana · miembro" junto a hora/día).

**Prueba real, no simulada** (servidor levantado, login real, todo vía
HTTP):
- **Editar tarifa real**: `Estandar/member/día` (28 → 33) vía
  `POST /gerente/tarifas/{id}/editar`. El catálogo del ciclista (`GET
  /ciclista/alquilar`) mostró de inmediato el nuevo precio con la
  promoción `ESTUD20` (20%) ya aplicada encima: tachado "antes USD
  33.00", precio final USD 26.40 — confirma que la edición real llega
  al ciclista y que la promoción sigue calculándose sobre el precio
  vigente, no uno cacheado. Se restauró el valor original (28) después
  de la prueba.
- **Tres modalidades en una bicicleta real** (`GET
  /ciclista/bicicleta/{id}`): hora USD 2.80 (antes 3.50), día USD 22.40
  (antes 28.00), semana USD 112.00 (antes 140.00) — las tres con el
  mismo 20% de `ESTUD20` aplicado consistentemente, confirmando que el
  cálculo, la promoción y el toggle funcionan igual en las tres
  modalidades.

## 22. Cuarto componente de línea de ruta: flujo de la orden de mantenimiento — RESUELTO el 06 de agosto de 2026

**Auditoría inicial (sin tocar nada)**: el modo "Ver" de
`empleado/mantenimiento/ordenes_form.html` mostraba el estado de la
orden solo como una etiqueta de texto (`<span class="badge...">`) —
sin ningún elemento visual de progreso. Se confirmaron los 4 estados
reales: las 4 órdenes migradas (`OM-0312` a `OM-0315`) están todas en
`cerrada` (nunca se ha visto ninguna en un estado intermedio hasta
hoy); el formulario de Editar sí ofrece un quinto estado,
`espera_repuesto`, no pedido como nodo principal.

**Hallazgo antes de construir**: a diferencia de `alquileres`,
`ordenes_mantenimiento` no tiene una tabla de eventos con hora por paso
(no existe un `orden_eventos`) — solo `fecha_apertura` y `fecha_cierre`
son reales. El componente nuevo no inventa una hora para "diagnóstico"
ni "en reparación": muestra "—", mismo criterio que ya usa
`flujo_alquiler.html` cuando falta un dato real.

**`componentes/flujo_orden.html`** (nuevo): mismo lenguaje visual y
las mismas clases CSS que `flujo_alquiler.html` (`.flujo-nodo`,
`.flujo-segmento`, etc. — nada nuevo en `main.css`). 4 nodos:
abierta (documento) → diagnóstico (herramienta) → en reparación
(engranaje, mismo ícono que ya usa `tarjeta_bicicleta.html` para
"marchas" — reutilizado a propósito por coherencia) → cerrada (check,
mismo ícono que el paso final de `flujo_alquiler.html`). El estado
`espera_repuesto` (no es uno de los 4 pasos principales) se representa
sobre el mismo nodo que "en reparación" — sigue siendo trabajo en
curso, solo bloqueado — con su propia etiqueta ("Espera repuesto" en
vez de "Paso actual").

**Integración**: incluido en `ordenes_form.html` modo "Ver", mismo
patrón que `alquiler_form.html` (dentro del card-header, antes del
card de Detalle).

**Prueba real** (servidor levantado, login real como
`empleado.mant@urbanbike.com`, todo vía HTTP):
- **Orden real cerrada** (`OM-0312`): los 4 nodos se ven completados,
  el nodo final "cerrada" con el anillo de "paso actual" y la hora real
  de `fecha_cierre` (`2026-07-05 05:13`); "diagnóstico"/"en reparación"
  muestran "—", sin inventar hora.
- **Orden de prueba** (`OM-0316`, diagnóstico marcado como prueba)
  avanzada en vivo por los 5 estados vía `POST .../editar`: `abierta`
  → `diagnóstico` → `espera_repuesto` (nodo "en reparación" con la
  etiqueta especial, confirmado) → `en_reparacion` → `cerrada` (hora
  real de cierre `2026-08-06 02:05`, la de la prueba). El nodo "actual"
  y los segmentos sólidos avanzaron correctamente en cada paso.

## 23. Checklist de devolución — Nivel 2 y Nivel 3 RESUELTOS (06 y 07 de agosto de 2026)

**Auditoría inicial (sin tocar nada)**: `checklist_items` sí tenía sus
12 ítems reales (del seed, nunca fue de ejemplo). `inspecciones` e
`inspeccion_detalle` estaban en 0 filas — nunca se había escrito una
inspección real. El componente visual `checklist_devolucion.html` en
`empleado/vigilancia/inspeccion.html` recibía datos de ejemplo
armados a mano (`categorias_demo`/`items_por_categoria_demo`, con un
`# TODO` ya escrito por una sesión anterior). Y algo más grande: el
formulario funcional real de esa misma pantalla usaba una lista de
**7 ítems inventados** (`_CHECKLIST_ITEMS`, ni siquiera coincidía con
los 12 reales) y, al registrar, escribía **exclusivamente en
PocketBase** (`ordenes_mant`, `infracciones`, `pagos`, `bicicletas.estado`)
— nunca en `inspecciones`/`inspeccion_detalle`.

**Nivel 2, resuelto hoy**: `app/db/inspecciones_repo.py` (nuevo).
`_CHECKLIST_ITEMS` reemplazado por los 12 ítems reales de
`checklist_items`. Al registrar una inspección (`vig_inspeccion_registrar`),
ahora se escribe una fila real en `inspecciones` + 12 en
`inspeccion_detalle`, resolviendo `id_bicicleta` (codigo → id real de
`bicicletas`), `id_alquiler` (`viaje_id` de PocketBase → id real vía
`id_origen_pocketbase`, mismo mecanismo de la sección 18; sentinela si
el viaje no está migrado) e `id_inspector` (email → id real de
`usuarios`, creándolo si no existe — no había ningún usuario real con
`rol='vigilancia'` hasta hoy, mismo patrón que `asegurar_usuario()` de
`etl/07_migrar_viajes_pagos.py`). El componente visual ahora lee la
última inspección real de esa bicicleta (vacío si nunca se le hizo
una, nunca datos inventados). Escritura *best-effort*: si falla, no
bloquea el resto del flujo (que sigue siendo lo único que hoy mueve el
sistema de verdad — ver Nivel 3).

**Limitación del formulario, documentada a propósito**: el formulario
solo captura OK / Con daños (binario). `"mal"` se guarda como
`dano_leve` — la interpretación más conservadora que la UI de hoy
puede respaldar; `dano_grave`/`faltante` quedan disponibles en el
esquema para cuando el formulario capture ese detalle (fuera de
alcance hoy).

**Prueba real de punta a punta**: bicicleta real `UB-002`, los 12
ítems reales completados (2 marcados "Con daños": `CHK-05` presión de
llanta delantera, `CHK-08` luz delantera), registrado vía
`POST /empleado/vigilancia/inspeccion/{id}/registrar` con sesión real
de `empleado.vig@urbanbike.com` (usuario `U-0019` creado en el acto).
Confirmado en ClickHouse: 1 fila en `inspecciones` (`items_revisados=12`,
`items_totales=12`, `tiene_dano=1`) + 12 en `inspeccion_detalle` con el
resultado correcto por ítem. El componente visual, recargado, mostró
"12 de 12 revisados", anillo al 100%, las 6 categorías en "completa" y
los dos ítems dañados con badge "Daño leve" — reemplazando por
completo los valores de ejemplo anteriores ("8 de 12", categorías
mixtas). La escritura existente hacia PocketBase (`ordenes_mant`)
se probó intacta, sin cambios.

**Nivel 3 — PENDIENTE, PRIORIDAD ALTA** (mismo tipo de riesgo que la
sección 0: no revienta con un error, produce un resultado incorrecto
en silencio sin que se note en la interfaz). Hoy el resultado de una
inspección real certificada en ClickHouse **no mueve nada real del
resto del sistema** — la rama que sí actúa sigue siendo la vieja,
contra PocketBase, desconectada:

- **Orden de mantenimiento**: se crea en `ordenes_mant` (PocketBase),
  no en `urbanbike_operativa.ordenes_mantenimiento` — invisible en el
  panel real de mantenimiento (`empleado/mantenimiento/ordenes.html`,
  el WorkPanel que sí es real, ver secciones anteriores).
- **Infracción**: se crea en `infracciones` (PocketBase), no en
  `urbanbike_operativa.infracciones` (0 filas reales hoy, `ORDER BY`
  ya corregido en la sección 19 pero sin ningún escritor real
  todavía) — no existe ningún repositorio `infracciones_repo.py` hoy.
- **`bicicletas.estado`**: se actualiza **solo en PocketBase**, nunca
  en ClickHouse. El catálogo del ciclista lee `bicicletas.estado` de
  **ClickHouse** (`_catalogo_bicicletas()`) — así que una bicicleta
  aprobada podría seguir apareciendo con su estado viejo, y **una
  bicicleta reprobada con daño real detectado podría seguir
  ofreciéndose para alquilar en el catálogo real**, porque ClickHouse
  nunca se enteró del rechazo. Este es el riesgo concreto más serio de
  los cuatro.
- **Cargo por daños**: se crea como pago tipo `cargo_danos` en PocketBase,
  sin ningún reflejo en `urbanbike_operativa.pagos`/`garantias`/
  `cobros_automaticos` — no aparece en ningún reporte financiero real
  (mismo patrón exacto que el `cargo_danos` original de la migración
  de julio, ver punto 11 de la sección 6, todavía sin resolver tampoco).

**Alcance estimado para el Nivel 3**: repuntar la rama "reprobada" (y
la actualización de `bicicletas.estado` en la rama "aprobada") a las
tablas reales — `ordenes_repo.crear()` (ya existe), `bicicletas_repo.actualizar()`
(ya existe, con su propio espejo a PocketBase incluido, así que dejaría
de ser necesario tocar PocketBase directo aquí), un `infracciones_repo.py`
nuevo (no existe), y una decisión de diseño para dónde aterriza el
cargo por daños. Comparable en tamaño a las sesiones de tarifas +
promociones juntas — no es un ajuste chico, amerita su propia sesión
de auditoría y decisión de reglas de negocio antes de implementar,
mismo criterio que se usó para el modal de tarifas desconectado.

**Nivel 3, RESUELTO el 07-ago-2026 — auditoría previa (sin tocar nada)**:
1. Se confirmó exactamente qué escribía `vig_inspeccion_registrar()` en
   la rama reprobada (`app/routers/empleado.py`): `ordenes_mant`
   (PocketBase), `bicicletas.estado="mantenimiento"` (solo PocketBase),
   `infracciones` (PocketBase) + bloqueo del ciclista a las 3
   infracciones pendientes, y un pago `tipo="cargo_danos"` (PocketBase)
   si el empleado ingresaba un monto — igual que el `cargo_danos`
   original de julio (punto 11, sección 6), nunca resuelto.
2. `garantias` y `cobros_automaticos` (`urbanbike_operativa`): **0 filas
   reales las dos**, confirmado con `SELECT count()`. La única fila que
   tuvo `garantias` (seed) se borró en la limpieza de huérfanos de la
   sección 19 (dependía de `A-010482`). `grep -ri garantia` en todo
   `app/` no dio ningún resultado -- ningún código de la aplicación
   crea, lee o actualiza una garantía; el flujo que las alimentaría
   (retener una garantía al iniciar un alquiler) nunca se construyó.
3. Sin documento académico ni comentario de código que fije la regla de
   negocio del cargo por daños. El único indicio es de diseño puro:
   `cobros_automaticos.motivo` anticipa `'dano'` ligado a una
   `garantia` (`db/01_operativa_schema.sql:264`, comentario "obs. 6"),
   pero construir ese camino exigiría primero el flujo completo de
   garantías (punto 2), fuera de alcance de una sesión. Se encontró una
   tercera opción de costo casi nulo: `infracciones.monto_multa`
   (`Decimal(10,2)`, sin ningún escritor en todo el código, ya
   referenciado en un informe real -- `db/03_informes_simples.sql` S17,
   Objetivo OT 13).

**Decisión de Washington**: cargo por daños → `infracciones.monto_multa`,
en el mismo `INSERT` que la infracción real (no un pago ni una garantía
aparte).

**Dos hallazgos adicionales de la auditoría, resueltos al construir**:
- `ordenes_mantenimiento.id_tecnico` es obligatorio y
  `ordenes_repo.listar()` hace `INNER JOIN` contra `usuarios` por ese
  campo -- una orden generada con un id sentinela habría quedado
  invisible en el panel real de mantenimiento, el mismo tipo de bug que
  se estaba corrigiendo. Se agregó `ordenes_repo.tecnico_con_menos_carga()`:
  asigna automáticamente al técnico real (rol=mantenimiento) con menos
  órdenes abiertas hoy, reasignable después desde el WorkPanel como
  cualquier orden.
- `empleado/vigilancia/infracciones.html` (listar/resolver infracciones)
  y el bloqueo de ciclista por acumulación de 3 infracciones pendientes
  siguen 100% contra PocketBase (`resuelta`, `users.activo` -- lo que de
  verdad usa el login) -- **deliberadamente fuera de alcance hoy**,
  documentado en `app/db/infracciones_repo.py`. Dos fuentes paralelas de
  infracciones hasta que esa pantalla se migre en una sesión aparte.

**Implementación**: `app/db/infracciones_repo.py` (nuevo) --
`crear()` e `resolver_o_crear_usuario()` (mismo patrón que
`asegurar_inspector()` de `inspecciones_repo.py` y `asegurar_usuario()`
de `etl/07_migrar_viajes_pagos.py`, resuelve el ciclista real por email
porque el viaje puede no estar migrado todavía cuando ocurre la
inspección en vivo). `ordenes_repo.py` +`tecnico_con_menos_carga()`.
`vig_inspeccion_registrar()` reescrito: ambas ramas (aprobada Y
reprobada) mueven `bicicletas.estado` con `bicicletas_repo.actualizar()`
(espejo a PocketBase incluido, ya no se toca PocketBase directo para
esto); la rama reprobada genera la orden real con `ordenes_repo.crear()`
(`origen="inspeccion"`, `tipo_falla` mapeado desde la categoría real del
primer ítem dañado del checklist) y la infracción real con
`infracciones_repo.crear()` (incluye `monto_multa` si el empleado
ingresó un cargo por daños). Se quitaron las escrituras viejas a
`ordenes_mant` y al pago `tipo="cargo_danos"` de PocketBase; se
mantuvo la escritura a `infracciones` de PocketBase solo para el
bloqueo del ciclista (ver hallazgo de arriba).

**Prueba real de punta a punta** (servidor FastAPI levantado, todo vía
HTTP con sesiones reales, no llamadas directas a los repos):
`UB-001` reservada como `ciclista@urbanbike.com`, devuelta y reprobada
como `empleado.vig@urbanbike.com` (`CHK-05` "Presión de llanta
delantera" marcado con daño, cargo por daños de $15). Confirmado con
`SELECT` directo en ClickHouse: `bicicletas.estado='mantenimiento'`
para `UB-001`; orden real `OM-0317` (`origen='inspeccion'`,
`tipo_falla='neumatico'`, técnico asignado automáticamente); infracción
real (`tipo='dano_bicicleta'`, `monto_multa=15`, ligada al usuario real
`Adrian Guizado`). El espejo de PocketBase confirmó `mantenimiento`
también ahí, y las colecciones viejas (`ordenes_mant`, `pagos
tipo=cargo_danos`) **no** recibieron ninguna fila nueva -- solo la
tabla real. `GET /ciclista/alquilar` confirmó que `UB-001` **ya no
aparece** en el catálogo del ciclista (antes de esta sesión, una
bicicleta reprobada seguía apareciendo disponible ahí -- el riesgo
concreto que motivó esta sesión).

## 24. KPI tácticos: 6 nuevos calculados, 9 evaluados sin datos suficientes (07 de agosto de 2026)

**Punto de partida**: `urbanbike_tactica.kpi_resultados` tenía 3 KPI de
ejemplo (gerencia: ingresos confirmados; operación: duración promedio;
mantenimiento: % flota en mantenimiento), de los 13 objetivos tácticos
(OT01-OT13, repartidos en Gerencia/Administración/Operación/
Mantenimiento/Vigilancia) que Washington confirmó desde sus apuntes de
clase.

**Auditoría (Parte 1, sin calcular nada)**: se confirmó otra vez que el
documento académico con el catálogo real de OT01-OT13 **no está en el
repo** (mismo hallazgo ya dejado en `etl/08_calcular_tactica.py:25-29`
-- solo el esquema en estrella de `urbanbike_tactica` fue validado
contra ese documento, no el catálogo de objetivos en sí). Sin ese
catálogo no hay forma confiable de mapear un candidato nuevo a un
número de OT exacto, así que la auditoría evaluó preguntas de negocio
reales por departamento en su lugar (usando `db/03_informes_simples.sql`,
los informes S01-S18 con su "Objetivo OT" anotado, como la mejor pista
disponible de qué le importa a cada objetivo) contra los datos reales
de hoy (33 alquileres, 10 bicicletas, 6 órdenes, 1 infracción real, 4
repuestos, 13 usuarios, 3 promociones, 24 tarifas). 15 candidatos
evaluados, 6 viables:

| Departamento | KPI viable | Motivo |
|---|---|---|
| Gerencia | Ticket promedio por alquiler facturado | 19 alquileres reales `facturado` (es_prueba=0) |
| Administración | Dotación de personal activo por rol | 13 usuarios reales; admin/gerente no tienen fila real (nunca migrados) |
| Operación | % de flota disponible ahora mismo | 10 bicicletas reales con estado real |
| Mantenimiento | % de repuestos bajo el stock mínimo | 4 repuestos reales, los 4 hoy por debajo de su mínimo |
| Mantenimiento | Tiempo promedio de resolución de órdenes cerradas | 4 órdenes reales cerradas con `fecha_apertura`/`fecha_cierre` reales (excluye `OM-0316`, prueba documentada en sección 22, y `OM-0317`, abierta) |
| Vigilancia | Infracciones activas (conteo real) | 1 infracción real, generada el 06-ago-2026 con el Nivel 3 (sección 23) — primer dato real de vigilancia |

9 candidatos evaluados sin datos suficientes hoy (no se calculan, mismo
criterio de no forzar nada sobre datos insuficientes que ya se usó en
la sección 8):

- **Gerencia — Impacto de promociones en ingresos**: `alquileres.id_promocion`
  vacío en las 33 filas reales -- ninguna promoción se ha aplicado
  nunca a un alquiler real (ver hallazgo aparte más abajo).
- **Administración — Caja diaria / ganancia neta**: `pagos` tiene 1
  sola fila real (residuo de seed, sin escritor real en todo el
  código); `gastos` tiene 2 filas sin relación temporal con los
  ingresos reales -- mismo hallazgo ya documentado en la sección 8.
- **Administración — Facturas emitidas**: `facturas` tiene 0 filas
  reales (la única que existió se borró como huérfana en la sección
  19) pese a que 19 alquileres reales están en estado `facturado` -- la
  tabla de detalle nunca se pobló.
- **Administración — Pagos pendientes de verificación**: ese estado
  (`pendiente_efectivo`/`verificacion_pendiente`) vive en PocketBase,
  no en `urbanbike_operativa.pagos` -- fuera del alcance del ETL hoy.
- **Operación — Ocupación/viajes por estación**: ~28 viajes reales
  repartidos en 11 estaciones (~2-3 por estación) -- mismo hallazgo de
  volumen insuficiente ya documentado en la sección 8.
- **Operación — Bicicletas reubicadas por rebalanceo**: no existe
  ninguna tabla ni evento que registre rebalanceo en el esquema -- dato
  no capturado, no es un problema de volumen.
- **Mantenimiento — Costo promedio de reparación**: las 4 órdenes
  reales migradas tienen `costo_repuestos`/`costo_mano_obra` = 0 (ver
  hallazgo aparte más abajo, no es que las reparaciones fueran
  gratis).
- **Vigilancia — Viajes activos que exceden tiempo contratado**: 0
  alquileres reales en estado `reservado`/`en_curso` en ClickHouse hoy
  -- el flujo de reserva en vivo del ciclista sigue 100% en PocketBase
  (pendiente #14, sección 6), así que este KPI mediría siempre 0 sin
  que eso signifique que no hay riesgo real.
- **Vigilancia — % de devoluciones con inspección real registrada**: 2
  inspecciones reales contra 33 alquileres migrados que nunca pasaron
  por este flujo porque no existía cuando ocurrieron -- comparación no
  representativa, mismo problema de denominador que el de por-estación.

**Implementación**: los 6 KPI viables se agregaron a
`calcular_kpis()` en `etl/08_calcular_tactica.py` (mismo patrón que los
3 originales: una consulta real contra `fact_viajes`/`urbanbike_operativa`,
sin fabricar nada), y se corrió el script real una vez para poblar
`kpi_resultados`. Al ser un histórico que nunca se trunca, cada corrida
del DAG horario (sección 18) seguirá agregando los 9 KPI cada hora.

**Resultado real de la corrida (07-ago-2026)**:

| Departamento | KPI | Valor |
|---|---|---|
| gerencia | KPI-TICKET-PROMEDIO-ALQUILER | 0.12 |
| administracion | KPI-EMPLEADOS-ACTIVOS | 6 |
| operacion | KPI-FLOTA-DISPONIBLE-PCT | 50.0 |
| mantenimiento | KPI-REPUESTOS-BAJO-MINIMO-PCT | 100.0 |
| mantenimiento | KPI-TIEMPO-RESOLUCION-ORDEN-MIN | 277.0 |
| vigilancia | KPI-INFRACCIONES-ACTIVAS | 1 |

**Nota sobre `KPI-FLOTA-EN-MANTENIMIENTO-PCT` y `KPI-FLOTA-DISPONIBLE-PCT`**:
subieron a 50%/50% (5 de 10 bicicletas reales) frente al 36.36% de la
corrida anterior. No es un error de cálculo -- una de las 5 en
mantenimiento es `UB-001`, la bicicleta de la prueba de punta a punta
del Nivel 3 (sección 23, 06-ago-2026), que quedó real y genuinamente en
estado `mantenimiento` porque esa prueba nunca se completó con una
reparación/reaprobación real de vuelta a `disponible`. El número es
fiel al estado real actual del sistema, pero vale la pena saber que
está inflado por una prueba anterior sin cerrar.

**Hallazgo CERRADO el 07-ago-2026**: `UB-001` devuelta a `disponible`
vía `bicicletas_repo.actualizar()` (el mismo camino real que usaría
Mantenimiento al terminar una reparación, con su espejo a PocketBase
incluido -- no un ajuste manual directo en la base), y se corrió
`etl/08_calcular_tactica.py` de nuevo. Resultado real, **no 9 de 10
como se esperaba en un primer momento**: `UB-004`, `UB-006`, `UB-009` y
`UB-010` siguen genuinamente en `mantenimiento` -- son estado real
preexistente, sin relación con la prueba de `UB-001` (coincide con la
línea base de 36.36% = 4/11 que ya existía antes de que `UB-001` se
sumara como quinta bicicleta contaminando el número). Cerrar la prueba
trajo el KPI de vuelta a su estado normal real:
`KPI-FLOTA-DISPONIBLE-PCT` = **60.0%** (6/10),
`KPI-FLOTA-EN-MANTENIMIENTO-PCT` = **40.0%** (4/10) -- ya no 50%/50%,
pero tampoco 90%/10%.

## 25. Hallazgos sueltos, sin acción todavía (07 de agosto de 2026)

1. ~~**`alquileres.id_promocion` nunca se registra en un alquiler real,
   aunque el catálogo del ciclista sí calcula y muestra el precio con
   descuento.**~~ **RESUELTO el 07-ago-2026, ver sección 27** (para el
   único flujo real que crea un alquiler con precio propio hoy: el
   alquiler manual de Operación). El catálogo del ciclista (sección 20)
   sigue siendo solo visual -- el flujo de reserva del ciclista todavía
   no crea el alquiler en ClickHouse (pendiente #14), así que ahí no
   hay ninguna transacción real donde registrar el id_promocion todavía.
2. **Las 4 órdenes de mantenimiento reales migradas
   (`OM-0312`-`OM-0315`) tienen `costo_repuestos` y `costo_mano_obra`
   en cero porque ese dato nunca se migró desde PocketBase, no porque
   las reparaciones fueran gratis.** Aclaración dejada explícita a
   propósito (ver sección 24, candidato descartado "costo promedio de
   reparación") para que este dato no se malinterprete más adelante si
   alguien lo encuentra sin este contexto.

## 26. Gerente: bicicletas y estaciones migradas a WorkPanel — RESUELTO el 07 de agosto de 2026

**Punto de partida**: `gerente/bicicletas.html` y `gerente/estaciones.html`
eran los dos últimos CRUD en modal del rol Gerente (`tarifas` y
`promociones` ya habían migrado a WorkPanel, ver secciones 20/21) —
pendiente anotado a propósito en la sección 20 ("migrar
`bicicletas`/`estaciones`/`tarifas` de modal a WorkPanel").

**Auditoría (Parte 1, sin tocar nada) — un hallazgo no esperado**:
`gerente/bicicletas.html` sí estaba en ClickHouse real (vía
`bicicletas_repo`, confirmado sin sorpresas). **`gerente/estaciones.html`
NO** — seguía 100% contra la colección `estaciones` de PocketBase (9
registros, mirror armado a mano en alguna sesión anterior, sin ningún
mecanismo real de sincronización, `eliminar` sin ninguna regla de
protección), desconectada de las 11 filas reales de
`urbanbike_operativa.estaciones`. Mismo patrón de "dos fuentes de
verdad" que tenía `tarifas` antes de la sección 21 — no era solo un
cambio de patrón visual como se asumía al empezar. No existía
`estaciones_repo.py`.

**Regla de "Eliminar" para estaciones** (confirmada con Washington
antes de implementar, mismo criterio que bicicletas/órdenes/
promociones/tarifas): bloqueada si la estación tiene al menos 1
bicicleta real asignada (`id_estacion`) o aparece como estación de
inicio o de fin de al menos 1 alquiler real; si no tiene ninguna de las
dos, se borra de verdad. Hoy las 11 estaciones reales tienen al menos 1
bicicleta asignada, así que el borrado real solo aplica a estaciones
nuevas sin uso todavía.

**`app/db/estaciones_repo.py`** (nuevo, mismo patrón que
`bicicletas_repo.py`): `listar`/`obtener`/`contar_bicicletas`/
`contar_alquileres`/`crear`/`actualizar`/`eliminar`. Mismo puente
temporal hacia PocketBase (espejo best-effort por `codigo`,
unidireccional, nunca bloquea la operación real) porque el flujo de
reserva del ciclista y varias pantallas de vigilancia/operación todavía
leen estaciones desde PocketBase (pendiente #14, sección 6). A
diferencia de `bicicletas`/`ordenes_mantenimiento`, el código de
estación no sigue una secuencia limpia (`E-01`, `EC-G01`, `EC-Q03`...),
así que `crear()` no autogenera código — se captura manual en el
formulario, mismo criterio que `promociones`/`tarifas`.

**WorkPanel en `gerente/bicicletas.html`** (calcado de
`empleado/operacion/inventario.html`) y **`gerente/estaciones.html`**
(calcado del patrón de `gerente/promociones.html`, conservando el mapa
Leaflet + buscador de lugar Nominatim que ya existía, ahora dentro del
formulario de Insertar en vez de en un modal): lista paginada (10 por
página) con filtro, y los 4 modos en su propia vista
(`bicicletas_form.html`/`estaciones_form.html`) en vez de modales. Se
quitó `/estaciones/{eid}/toggleactiva` (superado por el campo Estado
del formulario de Editar, mismo patrón que `estado` en promociones).

**Prueba real de las 4 operaciones, contra ambas pantallas, vía HTTP
con sesión real de Gerente**:
- **Bicicletas**: Insertar (`UB-011`) → Ver → Actualizar (estado a
  `mantenimiento`, observación) → Eliminar bloqueado (`UB-002`, tiene
  alquileres reales, rechazado con el mensaje esperado) → Eliminar real
  (`UB-011`, 0 alquileres, confirmado con `count()=0`).
- **Estaciones**: Insertar (`EC-TEST01`) → confirmado en ClickHouse y en
  su espejo de PocketBase → Ver (bicicletas/alquileres reales
  asociados) → Actualizar (nombre, capacidad, `activa=false`) →
  Eliminar bloqueado (`EC-Q03`, 5 bicicletas reales, rechazado) →
  Eliminar real (`EC-TEST01`, 0 bicicletas/alquileres, confirmado
  `count()=0` en ClickHouse **y** en el espejo de PocketBase). Conteos
  finales de vuelta a la línea base (10 bicicletas, 11 estaciones) — sin
  residuos de prueba.

**Verificación de no-regresión** (Parte 3.2, las 4 pantallas que ya
dependían de `bicicletas_repo` antes de esta sesión, cada una con
sesión real de su rol): `empleado/operacion/inventario` (Operación),
`admin/bicicletas` (Admin), `empleado/mantenimiento/ordenes`
(Mantenimiento), `empleado/vigilancia/devoluciones` (Vigilancia), y de
paso `ciclista/alquilar` (catálogo del ciclista, que depende del
espejo de bicicletas/estaciones) — las 5 cargaron con datos reales sin
ningún cambio de comportamiento, porque `bicicletas_repo.py` no se
tocó en esta sesión (solo se reutilizó desde el router de Gerente).

## 27. Promociones reales en el alquiler manual de Operación — RESUELTO el 07 de agosto de 2026

**Auditoría (sin tocar nada) — un hallazgo más grande de lo esperado**:
se pidió confirmar dónde se calcula el precio final del "cobro
presencial" de Operación y si ese cálculo ya contempla promociones.
Encontré algo más de fondo:

- `alquileres_repo.crear_presencial()` (usado por el formulario
  "Alquiler manual", `POST /empleado/operacion/alquileres/crear`) **no
  calculaba ningún precio, con o sin promoción** -- el `INSERT` nunca
  incluía `subtotal`/`descuento`/`total`, así que quedaban en el
  default de esquema (`0`). Sí resolvía `id_tarifa` correctamente, pero
  nunca leía su `precio`. Confirmado contra los 3 alquileres manuales
  reales que ya existían (`A-010509`, `A-010511`, `A-010512`, de la
  sesión de la sección 10): los tres con `id_tarifa` real pero
  `subtotal=descuento=total=0` -- la pantalla "Ver" ya mostraba
  "$0.00" en producción para los tres.
- `empleado/operacion/cobrar_presencial.html` (`op_pagos_cobrar*`) es
  un flujo **distinto y ya desconectado**: opera 100% contra
  `pagos`/`viajes` de PocketBase (el flujo viejo de reserva del
  ciclista, pendiente #14), nunca toca `urbanbike_operativa.alquileres`,
  y tampoco calcula precio -- solo marca como pagado un monto ya fijado
  antes. No era el lugar correcto para este trabajo.
- `alquileres.id_promocion` (`String DEFAULT ''`) sí es el campo
  correcto -- confirma la sospecha de que conecta este trabajo con el
  hallazgo suelto de la sección 25.

Como calcular una promoción sin precio base no tiene sentido, las dos
cosas se construyeron juntas: primero el precio real (tarifa vigente),
después la promoción de mayor ahorro real encima.

**Decisión confirmada con Washington antes de implementar**:
`promociones.usos_actuales` existe en el esquema pero nunca se
incrementaba en ningún lado (ni siquiera en el catálogo del ciclista,
que solo aplica el descuento visualmente) -- este alquiler manual es la
primera vez que una promoción se compromete de verdad en una
transacción real, así que `usos_actuales` se incrementa al confirmar.
No agrega control de `usos_maximos` todavía (`promo_aplicable()` no lo
valida ni aquí ni en el catálogo del ciclista -- mismo alcance en los
dos lugares, sin ampliarlo hoy).

**Implementación**:
- `alquileres_repo._resolver_id_tarifa()` (devolvía solo un id) se
  reemplazó por `_resolver_tarifa()` (devuelve `id_tarifa` + `precio` +
  `id_categoria` en una sola consulta -- `bicicletas_repo.obtener()` no
  expone `id_categoria`, así que se resuelve aquí en vez de tocar el
  repo compartido).
- `alquileres_repo.cotizar(id_bicicleta)` (nuevo): calcula
  `{id_tarifa, precio_base, promo, descuento, total}` reutilizando
  `promociones_repo.activas_hoy()` + `promociones_repo.promo_aplicable()`
  -- el mismo helper de "mayor ahorro real" que ya usa
  `_catalogo_bicicletas()` en `ciclista.py`, no una copia. Se usa dos
  veces con el mismo resultado: para la vista previa del formulario y
  para el cobro real al confirmar, así nunca pueden desincronizarse.
- `alquileres_repo.crear_presencial()`: ahora inserta `subtotal`,
  `descuento`, `total` e `id_promocion` reales, e incrementa
  `promociones_repo.incrementar_uso()` (nueva) si aplicó una promoción.
- `_SELECT_BASE` de `alquileres_repo.py` ampliado con `id_promocion`
  (faltaba, necesario para mostrarlo en "Ver").
- **Formulario "Alquiler manual"** (`alquiler_form.html`, modo crear):
  al elegir una bicicleta, un bloque de vista previa muestra la tarifa
  real, la promoción aplicable (si hay alguna, con su nombre) y el
  total a cobrar -- JS simple sobre un mapa `{id_bicicleta: cotizacion}`
  ya calculado por el servidor (`GET /operacion/alquileres/nuevo`), sin
  llamada adicional al backend. El modo "Ver" también se amplió para
  mostrar el desglose real (Subtotal / Descuento si aplica / Total), no
  solo el total.

**Prueba real de punta a punta** (servidor levantado, sesión real de
`empleado@urbanbike.com`, todo vía HTTP): con `ESTUD20` (20%, aplica
lunes a viernes) y `PRUEBA-WP` (10%, todos los días) activas hoy
jueves, la cotización de `UB-002` (Eléctrica, tarifa casual/hora real
$5.50) mostró correctamente `ESTUD20` como la de mayor ahorro real
($1.10 de descuento, total $4.40) -- confirma que `promo_aplicable()`
elige la mejor entre varias también en este flujo. Alquiler real
`A-010517` creado con esa bicicleta: confirmado con `SELECT` en
ClickHouse `subtotal=5.50, descuento=1.10, total=4.40,
id_promocion=<uuid real de ESTUD20>`, y `ESTUD20.usos_actuales` pasó de
0 a 1. La pantalla "Ver" del alquiler mostró el mismo desglose real
(Subtotal $5.50, Descuento -$1.10, Total $4.40). Se deja `A-010517`
como evidencia visible, mismo criterio que las pruebas anteriores del
WorkPanel de alquileres.

**Nota sobre `A-010509`/`A-010511`/`A-010512` (aclarado con Washington
el 07-ago-2026, no se tocan)**: estos 3 alquileres manuales reales,
creados el 30-jul-2026 durante la sesión del WorkPanel de alquileres
(sección 10) -- antes de que existiera este arreglo -- quedaron con
`subtotal=descuento=total=0`. **No fueron alquileres gratuitos**: son
evidencia histórica de cuándo se detectó el bug (`crear_presencial()`
nunca calculaba precio en absoluto, ver auditoría más arriba). Se
dejan tal como están a propósito, sin reconstruir el monto que
deberían haber cobrado -- no hay forma de saber con certeza cuál habría
sido ese monto (qué tarifa vigente y qué promoción, si alguna, aplicaba
ese día), y forzar un número inventado sería peor que dejarlos en $0
con esta nota. Cualquier informe financiero que sume `total` sobre
alquileres reales debe tener en cuenta que estos 3 no representan
ingresos perdidos, sino datos de prueba con precio en cero.

## 28. `bicicleta_eventos`: infraestructura para `resumen_mensual_flota` — RESUELTO el 07 de agosto de 2026

**Punto de partida**: `resumen_mensual_flota` (`urbanbike_estrategica`)
nunca se ha calculado (pendiente #12, sección 6) porque no existe
ningún historial de cambios de estado de una bicicleta por fecha, solo
el snapshot actual en `bicicletas.estado`.

**Auditoría (sin tocar nada)**: revisé `bicicletas_repo.actualizar()`
completo -- no existía ningún registro de historial, ni siquiera
parcial. La función hace `ALTER TABLE ... UPDATE estado = ...` directo
y espeja a PocketBase; no recibe el estado anterior, no lo compara con
el nuevo, y no tiene ningún parámetro de actor/rol. Confirmé las 5
llamadas reales por `grep`: `admin.py` (modal), `gerente.py` (WorkPanel),
`empleado.py:200` (WorkPanel de Operación, `inventario`),
`empleado.py:1267` (Nivel 3 de vigilancia, sección 23), y
`alquileres_repo._sincronizar_bicicleta()` (usada por
`crear_presencial`/`cancelar`/`completar`). Ninguna de las 5 pasa
información de actor/rol -- su firma actual no tiene dónde ponerla.

**`urbanbike_operativa.bicicleta_eventos`** (nueva, `db/01_operativa_schema.sql`):
mismo patrón que `alquiler_eventos` -- `id_bicicleta`, `estado_origen`,
`estado_destino`, `fecha`, `id_actor`, `rol_actor`, `observacion`.
`ENGINE = MergeTree` (registro de eventos, nunca se actualiza),
`PARTITION BY toYYYYMM(fecha)`, `ORDER BY (id_bicicleta, fecha)`.

**Limitación real, documentada a propósito (no es un dato inventado)**:
`id_actor`/`rol_actor` quedan en su sentinela (`id_actor` UUID cero,
`rol_actor` vacío) en las 5 pantallas hoy, porque
`bicicletas_repo.actualizar()` no recibe el actor real desde ninguna de
ellas -- a diferencia de `alquiler_eventos`, cuyos llamadores sí pasan
el actor real. Ampliar la firma de `actualizar()` para recibir
`id_actor`/`rol_actor` y tocar las 5 pantallas queda pendiente para una
sesión aparte (se decidió no tocar los 5 llamadores hoy, para no
arriesgar romper ninguno).

**`bicicletas_repo.actualizar()` modificada**: lee el estado actual
(`obtener()`) **antes** del `ALTER`, y solo si `estado_anterior !=
estado_nuevo` inserta una fila en `bicicleta_eventos` (vía
`_registrar_evento_estado()`, nueva). La firma de `actualizar()` no
cambió -- los 5 llamadores existentes siguen funcionando exactamente
igual, sin ningún argumento nuevo que pasar.

**No se reconstruye historial anterior a hoy**: el historial empieza a
registrarse desde el 07-ago-2026 en adelante. Los cambios de estado
reales que ya ocurrieron antes (incluida la migración de julio, las
pruebas de las sesiones de bicicletas/alquileres/inspección) **no
tienen fecha real conocida** -- inventarlas sería peor que no tenerlas.
`resumen_mensual_flota` seguirá sin poder calcularse para ningún mes
hasta que se acumule al menos un mes completo de eventos reales
después de esta fecha; **no se implementa ese cálculo hoy** (con un
puñado de eventos de prueba no hay ningún mes completo que resumir).

**Prueba real** (servidor levantado, sesión real de
`empleado@urbanbike.com`, todo vía HTTP, WorkPanel de Operación):
`UB-003` cambiada de `disponible` a `mantenimiento` →
`bicicleta_eventos` registró 1 fila real (`disponible → mantenimiento`).
Un segundo guardado con el **mismo** estado (`mantenimiento` de nuevo)
**no generó ninguna fila** -- confirma que solo se registra cuando el
estado cambia de verdad, no en cada guardado del formulario. Revertida
a `disponible` → segunda fila real (`mantenimiento → disponible`).
Total: exactamente 2 filas, no 3. Bicicleta de vuelta a su estado
original al cerrar la prueba.

## 29. Roles y permisos gestionables — auditoría, diseño e infraestructura base (07 de agosto de 2026)

**Objetivo final** (varias sesiones, esta es la primera): que el admin
pueda gestionar roles y permisos desde una pantalla, en vez de que un
programador los escriba a mano. Hoy solo se hizo la auditoría, el
diseño y las 3 tablas base con los roles reales precargados -- **el
catálogo de permisos y la pantalla de administración quedan
pendientes**, ver más abajo.

**Auditoría (Parte 1, sin tocar nada) — el control de acceso NO estaba
repetido por ruta**: todo vive en un solo lugar,
`app/middleware/auth.py` (`AuthMiddleware`), un `dict` Python estático
(`ROLE_RULES`) aplicado por **prefijo de URL**, de grano grueso (no
distingue crear/leer/editar/eliminar dentro de una sección). Confirmado
con `grep` de `rol_slug`/`rol_nombre` en los 4 routers: el único otro
uso real es para *registrar* el rol en la bitácora de auditoría, nunca
para decidir acceso.

**Inventario completo (8 reglas)**:

| Prefijo | Roles permitidos |
|---|---|
| `/auth/*`, `/static/*` | público |
| `/`, `/dashboard`, `/perfil` | cualquier autenticado |
| `/admin/*` | `admin` |
| `/gerente/*` | `admin`, `gerente` |
| `/ciclista/*` | `admin`, `ciclista` |
| `/empleado/operacion/*` | `admin`, `empleado-operacion` |
| `/empleado/mantenimiento/*` | `admin`, `empleado-mantenimiento` |
| `/empleado/vigilancia/*` | `admin`, `empleado-vigilancia` |
| `/empleado/*` (fallback) | `admin` + los 3 `empleado-*` |

**Hallazgos relacionados, no tocados hoy**:
- `app/templates/base.html`: 6 bloques `{% if rol == "..." %}` en el
  sidebar duplican el mismo modelo (deciden qué links mostrar, no
  bloquean acceso). El sistema nuevo debería poder alimentar esto
  también en una sesión futura.
- `gerente.py`: `_ROLES_EMPLEADO` restringe qué roles puede asignar el
  Gerente al crear/editar empleados (regla de negocio adyacente a
  permisos, no control de rutas).
- `app/routers/roles.py` existe vacío, nunca importado en `main.py` --
  la intención de un sistema de roles ya se había anticipado en el
  nombre del archivo, nunca se construyó.
- PocketBase tiene su propia capa de reglas de acceso por colección,
  independiente de esta middleware -- fuera de alcance hoy.
- Autorización a nivel de fila (ej. un ciclista solo ve su propio
  historial) es un tema distinto, no forma parte de "quién entra a
  esta ruta".

**Diseño (Parte 2) — dónde vive**: se recomendó PocketBase (misma capa
de auth, sin depender de ClickHouse para poder iniciar sesión, sin
crear una segunda fuente de verdad de roles junto a la colección
`roles` que ya usa el login). **Washington decidió ClickHouse** (mismo
lugar que el resto de `urbanbike_operativa`) -- decisión confirmada,
construido ahí.

**Esquema creado** (`db/01_operativa_schema.sql`, junto a `usuarios`):
- `roles`: `id`, `slug`, `nombre`, `descripcion`, `es_sistema`, `estado`,
  `version`. `ReplacingMergeTree(version)`, `ORDER BY id` (no
  `(estado, id)` -- mismo criterio que `usuarios`/`bicicletas`, `estado`
  es mutable desde el día uno).
- `permisos`: `id`, `codigo` (único, ej. `'bicicletas:crear'`,
  `'gerente:acceso'`), `recurso`, `accion`, `descripcion`, `version`.
  `ReplacingMergeTree(version)`, `ORDER BY id`.
- `rol_permisos`: `id_rol`, `id_permiso`, `otorgado_por` (sentinela por
  defecto, mismo criterio que `bicicleta_eventos.id_actor`), `fecha`.
  `MergeTree` (una concesión se otorga o se revoca, nunca se actualiza
  in place -- mismo criterio que `alquiler_eventos`/`bicicleta_eventos`),
  `ORDER BY (id_rol, id_permiso)`.

**Decisión de diseño explícita**: el mapeo de qué prefijo de URL exige
qué `codigo_permiso` se queda como un diccionario chico dentro de
`AuthMiddleware`, no como una 4ª tabla editable por el admin -- ese
mapeo está atado a la estructura real de rutas del código, igual que
el catálogo de `permisos.codigo` lo define un programador cuando
construye cada pantalla. Lo que el admin gestiona desde la pantalla
(cuando se construya) es **qué roles tienen qué permisos**, no qué
protege cada URL.

**Los 6 roles reales precargados** (`es_sistema=1`, para que no puedan
borrarse por accidente desde la futura pantalla -- login y middleware
dependen de que existan): `ciclista`, `gerente`, `admin` (Administrador),
`empleado-operacion`, `empleado-mantenimiento`, `empleado-vigilancia`.
Confirmado con `SELECT`: 6 filas, todas `estado='activo'`,
`es_sistema=1`. `permisos` y `rol_permisos` quedan vacías a propósito.

**Pendiente explícito para la siguiente sesión**: catálogo real de
permisos (a diseñar junto con Washington usando el inventario de
arriba), la pantalla de administración (CRUD de roles/permisos/
asignación), y repuntar `AuthMiddleware` para que consulte estas tablas
en vez del `dict` hardcodeado -- **nada de eso se tocó hoy**, ni se
modificó ninguna ruta existente.

## 30. Catálogo de permisos y asignación por rol — RESUELTO el 07 de agosto de 2026

**Continuación de la sección 29** (mismo día). Cambio de alcance
confirmado por Washington: permisos reales por acción (crear/leer/
actualizar/eliminar), no solo por sección como se había dejado
planteado en la sección 29.

**Catálogo diseñado junto con Washington, recurso por recurso, con
evidencia real de código** (no se inventó ninguna acción sin una ruta
real que la ejecute): 10 recursos, **37 permisos**.

| Recurso | Acciones reales |
|---|---|
| `bicicletas` | crear, leer, actualizar, eliminar |
| `alquileres` | crear, leer, actualizar, eliminar, exportar |
| `ordenes_mantenimiento` | crear, leer, actualizar, eliminar |
| `infracciones` | crear, leer, actualizar (sin eliminar -- no existe en ningún lado) |
| `tarifas` | crear, leer, actualizar, eliminar |
| `promociones` | crear, leer, actualizar, eliminar |
| `estaciones` | crear, leer, actualizar, eliminar |
| `usuarios` | crear, leer, actualizar, eliminar, exportar |
| `reportes` | leer, exportar (sin crear/actualizar/eliminar -- confirmado) |
| `auditoria` | leer, exportar (log de solo lectura, nunca se crea/edita desde una pantalla) |

**Dos hallazgos durante el diseño, ambos confirmados con Washington
antes de incluirlos**:
- `infracciones` y `auditoria` no estaban en la lista original de 8
  recursos -- se agregaron al encontrar evidencia real de pantalla
  propia (`/vigilancia/infracciones`, `/admin/auditoria`).
- `infracciones:actualizar` (`POST /vigilancia/infracciones/{iid}/resolver`)
  y `ordenes_mantenimiento:actualizar` para Vigilancia
  (`vig_mantenimiento_certificar`) son acciones reales que **todavía
  escriben contra la colección vieja de PocketBase**, no contra los
  repos reales (`infracciones_repo`/`ordenes_repo`) -- se incluyeron
  igual porque el permiso modela la acción que existe en el sistema
  hoy, no qué base de datos hay detrás. Cuando esas pantallas se
  reconecten (pendiente aparte, no es de hoy), el permiso ya existe y
  no hay que tocarlo.
- Hallazgo aparte, sin acción hoy: `admin/estaciones.html` sigue 100%
  contra PocketBase, desconectada de `urbanbike_operativa.estaciones`
  -- mismo bug que tenía `gerente/estaciones.html` antes de la sección
  26, nunca replicado el fix en Admin. No se tocó, queda anotado.

**Asignación por rol (`rol_permisos`), replicando el comportamiento
actual del sistema** -- Admin recibe siempre el conjunto completo de
cualquier otro rol (ya puede entrar a todos los prefijos vía
`AuthMiddleware`, aunque no tenga pantalla propia para todo, ej.
`ordenes_mantenimiento`/`infracciones`); Ciclista en 0 permisos de
gestión, confirmado a propósito por Washington aunque existe
`GET /ciclista/reportes` (su propio historial, sin representar en el
catálogo):

| Rol | Permisos | Total |
|---|---|---|
| `admin` | los 37, todos | 37 |
| `gerente` | bicicletas, tarifas, promociones, estaciones (4 c/u); usuarios crear/leer/actualizar/exportar (sin eliminar); reportes leer/exportar | 22 |
| `empleado-operacion` | bicicletas (4); alquileres (4); reportes leer/exportar | 10 |
| `empleado-mantenimiento` | ordenes_mantenimiento (4); bicicletas leer; reportes leer | 6 |
| `empleado-vigilancia` | bicicletas leer/actualizar; ordenes_mantenimiento crear/leer/actualizar; infracciones (3) | 8 |
| `ciclista` | ninguno | 0 |

**Total: 83 filas en `rol_permisos`.**

**Implementación**: 37 filas insertadas en `permisos` (con `recurso`/
`accion`/`descripcion`), 83 filas en `rol_permisos` (resolviendo
`slug`→`id_rol` y `codigo`→`id_permiso` con un script Python
puntual reutilizando `app/db/clickhouse.py`, no a mano, para no
arriesgar un UUID mal copiado). Verificado con `SELECT`: 37/83 filas
totales, conteo por rol exacto contra la tabla de arriba
(37/22/10/6/8/0), y `JOIN` real contra `roles`/`permisos` mostrando los
códigos exactos por rol (`gerente`, `empleado-vigilancia`,
`empleado-mantenimiento` verificados uno por uno).

**Sigue sin tocarse, pendiente para la siguiente sesión**: la pantalla
de administración (CRUD de roles/permisos/asignación) y repuntar
`AuthMiddleware` para que consulte estas tablas en vez del `dict`
hardcodeado. Ninguna ruta existente se modificó hoy tampoco.

## 31. PRIORIDAD ALTA — `admin/estaciones.html` y `admin/tarifas.html` desconectadas de `urbanbike_operativa` (07 de agosto de 2026)

**Encontrado al auditar el Grupo 1 de exportación (sección 32)**, no
buscado a propósito. Confirmado con Washington como hallazgo de
prioridad alta, sin resolver hoy.

- **`admin/estaciones.html`**: ya documentado como hallazgo aparte en
  la sección 26 (al construir el WorkPanel real de
  `gerente/estaciones.html`) — sigue sin corregirse.
- **`admin/tarifas.html`**: **hallazgo nuevo de hoy**, mismo patrón
  exacto. `admin.py:tarifas_list()` lee la colección vieja `tarifas` de
  PocketBase (esquema `tipo_bicicleta`/`tipo_usuario`/`precio_hora`,
  sin modalidad ni categoría real) — la misma desconexión que tenía
  `gerente/tarifas.html` antes de reconectarse a
  `urbanbike_operativa.tarifas` en la sección 21. Confirmado con
  conteos reales: la colección vieja de PocketBase tiene **5 filas**;
  la tabla real tiene **24** (8 hora + 8 día + 8 semana). Editar una
  tarifa desde Admin hoy no cambia nada de lo que ve el ciclista —
  mismo síntoma exacto que tenía Gerente antes del fix.

**Por qué importa**: Admin y Gerente muestran datos **distintos** para
el mismo concepto (estaciones, tarifas) — un administrador que edite
algo desde `/admin/tarifas` o `/admin/estaciones` no está tocando la
fuente real que ve el ciclista ni que usa el resto del sistema.

**Alcance estimado para resolver**: mismo patrón ya usado dos veces
(sección 21 para `gerente/tarifas.html`, sección 26 para
`gerente/estaciones.html`) — repuntar `admin.py` a `tarifas_repo.py` y
`estaciones_repo.py` (ambos ya existen, no hay que crear repos
nuevos), migrar las plantillas de Admin del modal viejo al mismo patrón
real. No se tocó hoy porque el pedido de la sesión era exportación
(sección 32), no reconexión de datos.

**Consecuencia sobre la exportación agregada hoy**: el Excel/PDF nuevo
de `admin/estaciones` y `admin/tarifas` (Grupo 1, sección 32) exporta
exactamente lo que la pantalla ya muestra -- hereda este mismo
problema automáticamente. Cuando se reconecten estas dos pantallas, el
export reflejará los datos reales sin necesidad de tocar el código de
exportación.

## 32. Exportación a Excel/PDF en pantallas de listado — Grupo 1 y 2 documentados retroactivamente, Grupo 3 y 4 RESUELTOS el 08 de agosto de 2026

**Nota sobre esta sección**: las secciones 31 y la nota final de la 31
ya la referenciaban ("Grupo 1, sección 32") desde una sesión anterior,
pero la sección nunca se llegó a escribir -- el trabajo de Grupo 1
(Admin) y Grupo 2 (Gerente) quedó hecho en el código (confirmado con
`git status`, ambos routers y sus plantillas aparecen modificados sin
commit) pero sin documentar. Lo de abajo para Grupo 1/2 es una
reconstrucción hecha hoy a partir del código real (`grep` de las rutas
`/excel` y `/pdf` en `admin.py`/`gerente.py`), no una repetición de
notas que existían antes.

**Patrón reutilizado en los tres grupos**: `app/reportes/excel.py`
(`generar_excel_reporte`) y `app/reportes/pdf.py`
(`generar_pdf_reporte`), ambos ya existentes antes de esta sección
(usados primero por `admin/auditoria` y los reportes de Gerencia/
Operación). Cada pantalla de listado agrega dos rutas nuevas
(`/excel`, `/pdf`) que llaman al mismo repositorio que ya usa la
pantalla, con `page=1, per_page=100_000` para traer el total filtrado
(no solo la página visible), y arma `columnas`/`filas` con
`ColumnaReporte`. Los botones "Exportar Excel"/"Exportar PDF" van en
el `card-header` de la tabla principal, y cuando la pantalla tiene
filtros propios (búsqueda, selects, fechas), el `href` los reenvía
como querystring para que el archivo respete exactamente lo que el
usuario está viendo.

**Grupo 1 — Admin** (`app/routers/admin.py`): pares `/excel`+`/pdf`
confirmados en el código para `usuarios`, `bicicletas`, `estaciones`,
`tarifas`, `bitacora` (los 5 pedidos) y `auditoria` (preexistente,
usado como referencia del patrón). Hallazgo real encontrado al
auditar este grupo, documentado aparte en la sección 31: `admin/estaciones`
y `admin/tarifas` siguen desconectadas de `urbanbike_operativa` (leen
PocketBase viejo), así que su export hereda ese mismo problema --
cuando se reconecten, el export ya no necesita tocarse.

**Grupo 2 — Gerente** (`app/routers/gerente.py`): pares `/excel`+`/pdf`
confirmados para `bicicletas`, `estaciones`, `tarifas`, `promociones`
(los 4 pedidos). Aparte, ya existían de sesiones previas (sin relación
con este pedido de exportación, no tocados hoy ni en Grupo 2): `/analisis-citibike`,
`/reportes` (solo excel, sin pdf), `/reportes/pagos` y `/empleados`
(solo excel, sin pdf) -- se dejan anotados aquí solo para que quede
claro que no son parte de este trabajo ni un pendiente nuevo.

**Grupo 3 — Operación** (`app/routers/empleado.py`, esta sesión):
auditoría de las 4 pantallas pedidas encontró que **`rebalanceo` no es
una pantalla de listado** -- es un formulario de una sola acción
(elegir bicicleta + estación destino + registrar traslado), sin tabla
ni historial de traslados que exportar. Confirmado con Washington antes
de tocar nada: se omite (no se inventó un reporte que no corresponde a
lo que la pantalla muestra). Las otras 3, resueltas:

- **`empleado/operacion/inventario`**: reutiliza `bicicletas_repo.listar()`
  con los mismos filtros de la pantalla (`q`, `marca`, `categoria`,
  `estado`). Columnas: Código, Marca, Modelo, Categoría, Estado,
  Estación.
- **`empleado/operacion/alquileres`**: reutiliza `alquileres_repo.listar()`
  con los filtros propios del WorkPanel (`q`, `estado`, `fecha_desde`,
  `fecha_hasta` -- **sin** `incluir_prueba=False`, a diferencia del
  export de `/operacion/reportes` que sí lo excluye, porque esta
  pantalla sí muestra los alquileres de prueba con su badge "Prueba" y
  el export debe reflejar exactamente lo que se ve). Columnas y fila de
  totales reutilizadas de `_reportes_op_columnas()`/`_reportes_op_fila()`
  (mismo shape de fila que ya usaba el export de `/operacion/reportes`,
  sin duplicar la definición).
- **`empleado/operacion/pagos`**: la pantalla no tiene filtros propios
  (es una vista fija del día: pagos de hoy + pendientes). Se exporta la
  tabla principal "Pagos" (no las dos sub-tablas de acciones pendientes
  "Transferencias por verificar"/"Efectivo pendiente", que son colas de
  trabajo, no reportes). Se extrajo `_pagos_del_dia()` como función
  compartida entre la pantalla y los dos exports, para no repetir la
  consulta a PocketBase tres veces.

**Bug encontrado y corregido antes de dar por probado**: el primer
intento de `/operacion/pagos/excel`/`/pdf` armaba el subtítulo como
`f"Generado: {fecha}"`, pero `generar_excel_reporte()` ya agrega
`"Generado: ..."` automáticamente al subtítulo (ver `excel.py`) --
salía duplicado ("Generado: ... | Generado: ..."). Corregido a
`f"Total: {n} pagos"` (mismo criterio que ya usaba `admin/auditoria`),
verificado leyendo el `.xlsx` real con `openpyxl` después del cambio.

**Verificación real, no solo código leído**: app corrida contra
ClickHouse/PocketBase reales (contenedores ya levantados), login real
como `empleado@urbanbike.com` (cuenta con rol `empleado-operacion` --
la cuenta de prueba documentada en la sección 11 como
`operacion@urbanbike.com` ya no existe con ese email; el password de
`Urbanbike123!` tampoco funcionaba, se restableció vía API admin de
PocketBase, mismo criterio que en la sección 11). Las 6 descargas
(excel+pdf × 3 pantallas) devolvieron HTTP 200 con el tipo de archivo
correcto (`file` confirmó `.xlsx`/`.pdf` válidos), y el contenido de
cada `.xlsx` se inspeccionó con `openpyxl`: `inventario` con
`estado=disponible` devolvió solo las 5 bicicletas disponibles reales
(filtro aplicado de verdad, no solo aceptado); `alquileres` devolvió
35 filas reales con fila de totales; `pagos` devolvió 8 filas reales
con total $16.78. Los `href` de los tres botones en pantalla
(`inventario`/`alquileres` con filtros activos de prueba,
`marca=Trek&estado=mantenimiento`) se confirmaron armados
correctamente vía el HTML real devuelto por el servidor.

**Grupo 4 — Mantenimiento** (`app/routers/empleado.py`, misma sesión,
confirmado por Washington a continuación de Grupo 3): auditoría de las
pantallas de Mantenimiento encontró que solo dos son listados reales
con tabla -- `dashboard` y `reportes` son paneles de gráficas (sin
fila por registro, mismo caso que `rebalanceo` en Grupo 3), así que se
omitieron sin preguntar de nuevo (mismo criterio ya confirmado).
`reportes` además usa la colección vieja `ordenes_mant` de PocketBase,
desconectada de `urbanbike_operativa.ordenes_mantenimiento` -- anotado
aquí solo como hallazgo, no se tocó (no era el pedido de hoy).

- **`empleado/mantenimiento/ordenes`**: reutiliza `ordenes_repo.listar()`
  con los filtros propios del WorkPanel (`q`, `estado`, `tecnico`,
  `prioridad`). Columnas: Código, Bicicleta, Origen, Tipo de falla,
  Prioridad, Técnico, Apertura, Cierre, Costo repuestos, Costo mano de
  obra, Estado -- con fila de totales de ambos costos. El subtítulo
  resuelve el id de `tecnico` a nombre real (vía
  `ordenes_repo.listar_tecnicos()`) para que el filtro se lea legible
  en el archivo, no como UUID.
- **`empleado/mantenimiento/bicicletas`**: sin filtros propios (misma
  consulta fija a PocketBase `estado = "mantenimiento"` que ya usaba la
  pantalla). Columnas: Código, Tipo, Estación, Notas.

**Bug encontrado y corregido antes de dar por probado**: el primer
intento de `_ordenes_columnas_filas` mostraba `fecha_cierre` para
órdenes que seguían abiertas -- en ClickHouse esa columna no es
nullable, así que una orden sin cerrar trae el epoch
(`1970-01-01 00:00`) en vez de `NULL`. La plantilla real
(`ordenes_form.html`) ya resolvía esto comprobando
`estado_reparacion == 'cerrada'` en vez de la fecha misma; se copió el
mismo criterio en el export en vez de inventar uno nuevo. Verificado
leyendo el `.xlsx` real antes y después del fix.

**Verificación real**: login como `empleado.mant@urbanbike.com` (rol
`empleado-mantenimiento` -- mismo problema de password desactualizado
que las otras cuentas de prueba, restablecido igual). Las 4 descargas
(excel+pdf × 2 pantallas) HTTP 200 con tipo de archivo válido;
`ordenes` con `prioridad=alta` devolvió 0 filas reales (correcto, no
hay ninguna orden real con esa prioridad hoy) y sin filtro devolvió las
6 órdenes reales con fila de totales ($32.50 en repuestos+mano de
obra); `bicicletas` devolvió las 5 bicicletas reales en mantenimiento.
`href` de los botones confirmados con filtros activos de prueba
(`prioridad=media`) vía el HTML real devuelto por el servidor.

**Pendiente explícito para la siguiente sesión**: continuar con más
pantallas de listado si se pide (Vigilancia es el rol que falta:
alertas, infracciones, devoluciones), y considerar si vale la pena
agregar un historial real de rebalanceos (tabla nueva) para que esa
pantalla sí tenga algo
exportable -- no se decidió hoy, ninguna acción tomada al respecto más
allá de omitir el export.

## 33. `resumen_viajes_diario` — informes compuestos precalculados — RESUELTO el 09 de agosto de 2026

**Punto de partida**: auditoría de una sesión anterior (mismo día,
08-ago-2026) confirmó que los 3 informes compuestos
(`gerente/reportes`, `gerente/informe`, segunda tarjeta de
`operacion/reportes`) agregaban `fact_viajes` en vivo en cada request,
contradiciendo el principio de "nunca calcular en el momento de la
consulta" ya aplicado a `kpi_resultados`. Medido con conexión
persistente (30 corridas): informe simple ~21 ms vs informe compuesto
~51 ms, ~2.4x más lento -- real pero pequeño porque el dataset real es
minúsculo (32-35 filas), no porque el problema no exista.

**Problema real a resolver, no solo "hacerlo más rápido"**:
`gerente/reportes` tiene 4 filtros que el usuario cambia en vivo
(fecha, membresía, tipo de bicicleta) -- no se puede precalcular "el
resultado ya filtrado" para cada combinación posible. Solución:
precalcular las agregaciones base al grano mínimo que soporta todos los
filtros y formas de agrupar, y dejar que la pantalla arme el filtro
final sobre ese resumen ya reducido, no sobre `fact_viajes` crudo.

**`urbanbike_tactica.resumen_viajes_diario`** (nueva,
`db/04_tactica_schema.sql`): grano día × estación × membresía × tipo de
bicicleta (`fecha`, `id_estacion_inicio`, `tipo_membresia`,
`es_electrica`, `viajes`, `duracion_total_min`, `fecha_calculo`).
`MergeTree()`, `PARTITION BY toYYYYMM(fecha)`,
`ORDER BY (fecha, id_estacion_inicio, tipo_membresia, es_electrica)` --
mismo patrón que `fact_viajes` (nunca `UPDATE`, se reconstruye completa
cada corrida), no el patrón `ReplacingMergeTree` de las dimensiones. Una
sola tabla sirve a los dos reportes de Gerente: `gerente/informe` no
filtra nada, así que simplemente agrega la tabla completa sin `WHERE`.

**Decisión explícita, confirmada antes de implementar**: la segunda
tarjeta de `operacion/reportes` (bicicletas por categoría/estado) se
deja fuera de este cambio a propósito. No tiene ningún filtro en vivo
(el problema de combinatoria de filtros no le aplica), ya corre en
milisegundos sobre tablas operativas de 10-15 filas, y lee
`urbanbike_operativa.bicicletas` directo -- reflejando el estado real
al segundo. Moverla al resumen táctico horario le metería hasta 1 hora
de retraso a una pantalla operativa que hoy no lo tiene, mismo tipo de
riesgo que ya se identificó como serio en la sección 23 (estado
incorrecto en silencio).

**`etl/08_calcular_tactica.py`**: nuevo paso `cargar_resumen_viajes_diario()`,
corrido justo después de `cargar_fact_viajes()` y antes de
`calcular_kpis()`. Mismo patrón de idempotencia que el resto del script
(`TRUNCATE` + `INSERT SELECT`, ver sección 18): agrega `fact_viajes`
(ya recargado completo esa misma corrida) con los mismos 2 `JOIN` que
antes pagaban las pantallas en cada clic (`dim_tarifa`,
`dim_tipos_bicicleta`), filtrando `es_prueba = 0`. También deja
snapshot real en `datos/proceso` (`etl/_snapshot.py`, mismo criterio que
`fact_viajes`).

**`app/routers/gerente.py`**: `_build_where_resumen()` (nuevo, mismos 4
filtros que `_build_where()` pero sobre columnas de `resumen_viajes_diario`
directamente, sin `JOIN` a `dim_tarifa`/`dim_tipos_bicicleta` en la
pantalla). Las 6 queries de `reportes()` y las 4 de `informe()`
reescritas para leer `resumen_viajes_diario` en vez de `fact_viajes`:
`count()`→`sum(viajes)`, `avg(duracion_min)`→`sum(duracion_total_min)/sum(viajes)`
(mismo promedio ponderado, matemáticamente idéntico). El único `JOIN`
que se queda en vivo es contra `dim_estaciones` (11 filas) para el
nombre de la estación -- lookup de dimensión, no agregación sobre el
hecho, misma distinción ya explicada en la propuesta. `/reportes/excel`
y el resto de `análisis-citibike` (dataset académico Citibike, base
distinta) no se tocaron -- fuera del pedido de hoy.

**Corrida real del ETL**: `resumen_viajes_diario: 24 filas` (día ×
estación × membresía × tipo, sobre 32 viajes reales) -- confirma la
estimación de la propuesta (cientos de filas, no miles).

**Paridad de resultados verificada, no solo confiada**: capturados los
resultados completos de las 6+4 queries antes del cambio (filtros por
defecto, `membresia=member`, `casual`+`electric_bike`, `classic_bike`,
y `informe` sin filtros) y comparados campo por campo contra los mismos
escenarios después del cambio: **los 5 escenarios idénticos**, mismos
totales, mismos promedios, mismo orden. Verificado también con HTTP
real: servidor levantado, sesión real de `gerente@urbanbike.com`,
`GET /gerente/reportes` (con y sin filtro `membresia=member`) y
`GET /gerente/informe` devolvieron 200 con los datos reales esperados
(`Parque El Ejido` como estación líder, sin excepciones en el HTML).

**Medición real de tiempo, antes vs después (A/B intercalado, 50
corridas alternadas por corrida para eliminar ruido de entorno, no
corridas separadas)**:

| | Antes (`fact_viajes` en vivo) | Después (`resumen_viajes_diario`) | Mejora |
|---|---|---|---|
| Corrida 1 | 59.00 ms promedio / 56.89 ms mediana | 47.53 ms promedio / 43.08 ms mediana | 19.4% / 24.3% |
| Corrida 2 | 61.82 ms promedio / 61.82 ms mediana | 51.97 ms promedio / 48.18 ms mediana | 15.9% / 22.1% |

**Honestidad sobre la magnitud**: la primera medición (no intercalada,
scripts separados) había dado un resultado engañoso -- 45.84 ms antes
vs 53.44 ms después, sugiriendo que había empeorado. Repetido con A/B
intercalado (mismo proceso, alternando antes/después en cada corrida
para que ambos midan bajo las mismas condiciones de carga) confirmó una
mejora real y consistente de ~16-24%, no una regresión. Es una mejora
real pero modesta, no dramática, porque con 32 viajes reales tanto
`fact_viajes` como `resumen_viajes_diario` (24 filas) son minúsculos --
el costo hoy lo domina el overhead fijo por consulta, no el cómputo del
`GROUP BY`. El beneficio arquitectónico grande de este cambio (evitar
que 6 agregaciones con `JOIN` corran contra una tabla de millones de
filas en cada clic) todavía no se puede medir con datos de este tamaño
-- se paga la corrección del principio hoy, se cobra la velocidad real
cuando el dataset crezca.

## 34. Informe estratégico de Gerente — evolución mensual precalculada — RESUELTO el 09 de agosto de 2026

**Auditoría (Parte 1, sin construir nada)**: `grep` de `resumen_mensual`
y `urbanbike_estrategica` en todo `app/` (routers y templates) dio
**cero resultados** -- confirma la sospecha: las tablas
`resumen_mensual_ingresos`/`resumen_mensual_demanda` existen con datos
reales desde el 30-jul-2026 (sección 8), pero ninguna pantalla las
había mostrado nunca. `resumen_mensual_flota` sigue en 0 filas
(pendiente real, no calculado -- ver secciones 22/28).

**Hallazgo que corrigió la premisa de la sesión**: el pedido asumía "un
solo mes cerrado, junio 2026" (cierto cuando se escribió, sección 8,
30-jul-2026). Al auditar hoy, `resumen_mensual_ingresos` ya tenía
**2 filas: junio Y julio 2026** -- el DAG horario (activo desde la
sección 18) volvió a evaluar `etl/09_calcular_estrategica.py` en algún
momento después de que julio terminara (31-jul-2026) y su guarda
`mes_completo()` (`ultimo_dia < date.today()`) correctamente dejó de
omitirlo. No es un bug, es el sistema funcionando como se diseñó -- pero
significa que la pantalla no debía construirse asumiendo "siempre un
punto", sino mostrar todos los meses que existan (hoy 2, mañana más).

**`app/routers/gerente.py`**: `_estrategico_meses()` (nuevo) lee
`resumen_mensual_ingresos FINAL` y `resumen_mensual_demanda FINAL`
directo -- sin agregar `fact_viajes` en vivo, mismo criterio ya aplicado
en la sección 33. `resumen_mensual_demanda` tiene grano por estación
(`anio, mes, id_estacion`); se re-agrega por mes con `sum()`/promedio
ponderado sobre esa tabla ya chica (11 estaciones × meses reales), no
sobre el hecho crudo -- misma distinción de "agregación cara vs. lookup
barato" ya usada en la sección 33. Nueva ruta `GET /gerente/estrategico`
(pantalla) y `GET /gerente/estrategico/{excel,pdf}` (export,
reutilizando `generar_excel_reporte`/`generar_pdf_reporte` de siempre),
las tres comparten `_estrategico_meses()` para no duplicar la consulta.

**Bug real encontrado y corregido al probar** (no en el código leído a
simple vista, solo se vio al correr contra ClickHouse real): la query de
`resumen_mensual_demanda` reutilizaba el mismo alias `total_viajes` para
la columna agregada y para una columna de la tabla origen
(`sum(total_viajes) AS total_viajes` seguido de
`sum(total_viajes * duracion_prom_min) / sum(total_viajes)` en el mismo
`SELECT`) -- ClickHouse sustituye el alias ya definido en la expresión
siguiente, produciendo `sum(sum(...))` y fallando con
`ILLEGAL_AGGREGATION`. Como el error ocurría dentro del `try/except` que
also engloba toda `_estrategico_meses()`, la pantalla no crasheaba: caía
en `ch_ok=False` y mostraba "ClickHouse no disponible" con 0 meses --
un fallo silencioso, mismo patrón de riesgo que ya preocupa en otras
partes del proyecto (ver sección 0). Se detectó porque se verificó el
contenido real del HTML devuelto, no solo el código HTTP 200 de la
respuesta. Corregido renombrando el alias a `total_viajes_mes`.

**Flota, dejada fuera con nota visible, no en silencio**: tarjeta
propia con borde de advertencia explicando que `resumen_mensual_flota`
requiere historial real de `bicicleta_eventos` (existe desde
07-ago-2026, sección 28) y que no se fuerza el snapshot actual como si
fuera "el estado de junio".

**Prueba real, no solo código leído** (servidor FastAPI levantado,
sesión real de `gerente@urbanbike.com`, todo vía HTTP):
- `GET /gerente/estrategico`: 200, sin el banner de error, 2 meses
  reales mostrados (`Jun 2026`, `Jul 2026`), gráficas con
  `chartGanancia=[1.72, 0.49]` y `chartViajes=[12, 13]` -- coincide
  exacto con lo que hay en `urbanbike_estrategica` (verificado con
  `SELECT` directo antes de construir).
- `GET /gerente/estrategico/excel`: 200,
  `application/vnd.openxmlformats...`, leído con `openpyxl`: filas
  `Jun 2026 | 12 | 1.72 | 0 | 0 | 1.72 | 12 | 87.0` y
  `Jul 2026 | 13 | 0.49 | 0 | 0 | 0.49 | 13 | 4.3`, fila de totales
  `25 alquileres | 2.21 | 25 viajes` -- duración promedio ponderada
  verificada a mano (87.0 y 4.3 min, calculados de las 3 y 6 estaciones
  reales de cada mes).
- `GET /gerente/estrategico/pdf`: 200, `application/pdf`, cabecera
  `%PDF-1.4` válida -- mismo dato que el Excel porque ambos llaman a
  `_estrategico_meses()`/`_estrategico_columnas_filas()`, sin
  duplicar la consulta ni el armado de columnas.
- Link nuevo en el sidebar de Gerente (`base.html`, sección Analítica,
  "Informe Estratégico"), confirmado con estado `active` real al cargar
  la pantalla.

## 35. `airflow/Dockerfile` con constraints oficiales de Airflow — RESUELTO el 09 de agosto de 2026

**Punto de partida**: la auditoría del 08-ago-2026 (ver informe de esa
sesión) encontró que `airflow/Dockerfile` instalaba
`etl/requirements.txt` con `pip install` directo sobre la imagen base
`apache/airflow:2.10.4-python3.11`, sin el archivo de constraints
oficial que Apache recomienda para instalar paquetes adicionales sobre
una imagen de Airflow. `pip check` no mostraba conflicto ese día, pero
sin constraints el próximo build podía resolver una versión de
duckdb/pyarrow/clickhouse-connect incompatible con lo que Airflow ya
fija internamente, sin ningún aviso.

**Constraints real, descargado y verificado antes de aplicarlo**
(`https://raw.githubusercontent.com/apache/airflow/constraints-2.10.4/constraints-3.11.txt`,
757 líneas, HTTP 200): confirma `pyarrow==16.1.0` (idéntico a lo ya
instalado, sin cambio) y **`duckdb==1.1.3`** (el contenedor tenía
`1.5.5` -- constraints fuerza un downgrade real). `clickhouse-connect`
no aparece en el archivo -- no es dependencia de Airflow, así que
`--constraint` no le fija ninguna versión y sigue resolviendo libre
contra el piso `>=0.7` de `etl/requirements.txt`.

**Auditoría del downgrade de duckdb antes de aplicarlo, no a ciegas**:
`grep` de `import duckdb` en todo `etl/` -- un solo uso real,
`etl/01_extract_to_parquet.py` (extracción del CSV crudo de Citibike a
Parquet, paso manual de una sola vez, ver `CLAUDE.md`). Ese script usa
solo funciones núcleo de DuckDB estables desde mucho antes de 1.1.3
(`read_csv`, `date_diff`, `ISODOW`/`DAYNAME`/`MONTHNAME`, funciones de
ventana, `COPY ... TO PARQUET`) -- sin riesgo de incompatibilidad. Más
importante: el DAG horario (`07`→`08`→`09`) nunca importa `duckdb`,
solo `clickhouse_connect` -- el downgrade no toca ninguna tarea real
que corra dentro de este contenedor.

**`airflow/Dockerfile`**: `RUN pip install --no-cache-dir -r
/tmp/etl-requirements.txt requests` →
`RUN pip install --no-cache-dir --constraint "${CONSTRAINT_URL}" -r
/tmp/etl-requirements.txt requests`, con `CONSTRAINT_URL` armado desde
`ARG AIRFLOW_VERSION=2.10.4` / `ARG PYTHON_VERSION=3.11` (evita
hardcodear la URL completa dos veces si algún día se sube de versión de
Airflow).

**Build real, sin errores**: `docker compose build
airflow-webserver airflow-scheduler airflow-triggerer airflow-init` --
las 4 imágenes construyeron limpio, `pip install` con `--constraint`
resolvió `duckdb-1.1.3`, `clickhouse-connect-1.6.0`, sin ningún error de
resolución.

**`pip check` en el contenedor nuevo**: `No broken requirements found.`
-- mismo resultado que antes del cambio, ahora con la garantía real de
que la resolución respetó los límites que Airflow ya fija, no solo que
"por casualidad no chocó".

**Bloqueo de infraestructura encontrado al probar (no relacionado con
este cambio, mismo síntoma ya documentado en la sección 18)**:
`airflow/logs/scheduler/2026-08-09/` volvió a quedar con permisos que
bloqueaban al `DagFileProcessor` (`PermissionError` al escribir su log),
impidiendo que el DAG se sincronizara a la base de metadatos --
`airflow dags trigger` fallaba con `DagNotFound` aunque `airflow dags
list` sí lo mostraba (el primero lee de la base de metadatos, el
segundo parsea el archivo directo). Mismo fix que la sección 18:
`chmod -R 777 airflow/logs` dentro del contenedor del scheduler. Se
recreó la carpeta con permisos incorrectos porque los contenedores se
recrearon hoy (`docker compose up -d --no-deps`) y el volumen montado
del host generó una subcarpeta nueva por fecha (`2026-08-09/`) con el
mismo problema de propietario que la de julio -- vale la pena que
Washington sepa que este bloqueo puede repetirse cada vez que se
recreen los contenedores de Airflow, no fue una casualidad de una sola
vez.

**DAG disparado manualmente, confirmado con datos reales**:
`manual__2026-08-09T03:26:24+00:00` -- las 3 tareas
(`migrar_viajes_pagos` → `calcular_tactica` → `calcular_estrategica`)
terminaron en `success`, en el orden correcto (además, el scheduler ya
había disparado solo la corrida horaria `scheduled__2026-08-09T02:00:00`
en cuanto los contenedores volvieron a estar sanos, también `success`).
Conteos en ClickHouse verificados estables después de la corrida, sin
duplicar ni perder nada: `urbanbike_operativa.alquileres`=35,
`urbanbike_tactica.fact_viajes`=32,
`urbanbike_tactica.resumen_viajes_diario`=24,
`urbanbike_estrategica.resumen_mensual_ingresos`=2 -- idénticos a los
valores de antes del rebuild, confirmando que el cambio de imagen no
alteró el comportamiento del ETL, solo blindó la resolución de
dependencias hacia el futuro.

## 36. Tres pendientes sueltos confirmados y verificados con datos reales (09 de agosto de 2026)

**Contexto**: Washington pidió confirmar el estado real de 3 tareas
pedidas en una sesión anterior cuya confirmación individual nunca
llegó. Esa sesión no aparece en el historial visible de esta
conversación -- en vez de asumir qué se hizo, se auditó el código real
y se probó cada pieza en vivo, mismo criterio que el resto de este
documento.

**1. Ícono de ojo en contraseña -- HECHO, en las 4 pantallas reales con
campo de contraseña**: `app/static/js/password-toggle.js` (existente),
cargado globalmente en `base.html`. Escanea todo `input[type="password"]`
del DOM (con `MutationObserver`-like re-escaneo por delegación de
`click`, para inputs que aparecen después en modales abiertos con JS,
ej. "Crear usuario" en Admin) y envuelve cada uno con un botón real de
mostrar/ocultar (SVG ojo/ojo-tachado). No se encontró con el primer
`grep` (buscaba markup por plantilla) porque es una envoltura genérica
en JS, no HTML por pantalla -- aplica sin cambios a
`auth/login.html`, `admin/usuarios.html` (crear/editar/cambiar
contraseña), `gerente/empleados.html` y `perfil.html`, las 4 con campos
`type="password"` reales. Verificado que el script sirve 200 real y que
`auth/login.html` lo referencia en el HTML devuelto por el servidor.

**2. Cédula y foto en gestión de usuarios de Admin -- HECHO, probado con
usuario de ensayo real de punta a punta**: el campo vive en PocketBase
(no en `urbanbike_operativa.usuarios` de ClickHouse -- gestión de
usuarios de Admin sigue siendo 100% PocketBase), confirmado con la API
real: colección `users` tiene `cedula` (text) y `avatar` (file) como
campos reales del esquema. `admin/usuarios.html` pide ambos en
Insertar y Editar (cédula con `pattern="[0-9]{10}"`, foto con
`accept="image/jpeg,image/png,image/gif"`, preview real en Editar).
Prueba real vía HTTP con sesión de `admin@urbanbike.com`:
`POST /admin/usuarios/crear` con `cedula=1712345678` y una foto PNG real
-- usuario creado, confirmado con `SELECT` directo en PocketBase
(`cedula: 1712345678`, `avatar: foto_prueba_....png`) y visible en la
lista de `GET /admin/usuarios` con su miniatura. Se deja un usuario de
prueba (`Usuario Prueba Cedula`) como evidencia visible, mismo criterio
que las bicicletas/alquileres de prueba de sesiones anteriores.

**3. Bicicletas en mantenimiento ocultas del catálogo del ciclista --
HECHO, probado con el conteo real antes/después**: `ciclista.py`
(`alquilar()`, línea ~283) ya filtraba
`catalogo_bicicletas = [b for b in catalogo_bicicletas if b["estado"] == "disponible"]`
-- este filtro es un efecto colateral documentado de la sección 23
(Nivel 3 del checklist de devolución, 07-ago-2026: "UB-001 ya no
aparece en el catálogo del ciclista"), no una pieza nueva. Prueba real
de hoy, no solo lectura de código: catálogo antes de tocar nada mostró
4 bicicletas reales disponibles (`UB-001/003/005/008`); se cambió
`UB-001` a `mantenimiento` vía
`POST /empleado/operacion/inventario/{id}/editar` (el mismo WorkPanel
real, sesión de `empleado@urbanbike.com`) -- el catálogo bajó a 3
(`UB-003/005/008`), confirmando que el conteo reacciona en vivo al
estado real. Revertido a `disponible` después de la prueba, catálogo de
vuelta a las 4 bicicletas originales, sin residuo.

**Nota sobre la numeración**: el pedido mencionaba "Tareas 1, 2 y 4"
pero enumeraba solo 3 ítems (1/2/3) -- si existía una cuarta tarea
real, no llegó en este mensaje; queda pendiente que Washington la
reenvíe si aplica.

## 37. Exportación Excel/PDF — Grupo 5 (Vigilancia) y Grupo 6 (Ciclista) RESUELTOS el 09 de agosto de 2026

Cierra el pendiente explícito de la sección 32: los últimos 2 de 6
grupos de pantallas sin exportación.

### Grupo 5 — Vigilancia (`app/routers/empleado.py`)

**Auditoría de las 6 pantallas pedidas, contra el template real, no
solo el router** (mismo criterio que Grupo 3/4): 5 de 6 son listados
reales con `<table>`, 1 no.

| Pantalla | ¿Tabla real? | Decisión |
|---|---|---|
| `seguimiento` | Sí -- "Viajes activos" (mapa + tabla) | Exportada |
| `devoluciones` | Sí -- "Viajes activos" (misma fuente que seguimiento, + acción de devolver) | Exportada |
| `infracciones` | Sí -- "Registro de infracciones" | Exportada |
| `mantenimiento/cerrar` | Sí -- "Órdenes en proceso" (snapshot filtrado, mismo patrón que `mantenimiento/bicicletas` del Grupo 4) | Exportada |
| `alertas` | Sí -- "Viajes que superaron X minutos" | Exportada |
| `reportes` | **No** -- cero `<table>`, un solo `<canvas>` de dona | **Omitida**, mismo criterio exacto que `mantenimiento/dashboard`/`reportes` del Grupo 4 |

`seguimiento` y `devoluciones` comparten la misma fuente real
(`viajes` PocketBase, `estado = "activo"`) -- se reutiliza
`_vig_seguimiento_viajes()` en los dos exports en vez de duplicar la
consulta. `alertas` extrajo `_vig_alertas_data()` de `vig_alertas()`
(antes la lógica de "minutos excedidos" vivía solo dentro de la
función de la pantalla) para compartirla con el export sin
recalcular con una copia paralela. `_vig_tiempo_transcurrido_min()`
(nueva) replica en Python el cálculo que hoy solo existía en el JS de
`seguimiento.html`/`devoluciones.html` (`actualizarTiempos()`), para
que el Excel/PDF tenga el mismo dato "tiempo transcurrido" que ve el
empleado en pantalla en vez de dejarlo en blanco.

**Prueba real con datos reales (2+ descargas, no solo HTTP 200)**:
sesión de `empleado.vig@urbanbike.com`, las 5 pantallas y sus 10 rutas
de export devolvieron 200 con el `content-type` correcto. Verificación
de contenido con `openpyxl` en 2 descargas:
- `infracciones/excel`: 4 infracciones reales, `Pendientes: 1 |
  Resueltas: 3` -- coincide exacto con lo que muestra la pantalla.
- `mantenimiento/cerrar/excel`: 0 órdenes reales en proceso hoy --
  confirma que el estado vacío real se refleja correctamente (headers
  + fila de total en 0), no que el export esté roto.

### Grupo 6 — Ciclista (`app/routers/ciclista.py`)

El comprobante individual por viaje (`/comprobante/{id_alquiler}/pdf`)
no se tocó, como se pidió. Se agregó exportación a `historial` (10
columnas: bicicleta, tipo, estado, estación inicio/fin, fecha, duración,
monto, estado de pago, comprobante -- combinando viajes + pagos +
recibos, misma lógica que ya arma la pantalla) e `infracciones` (5
columnas). `_historial_data()` y `_mis_infracciones()` (nuevas):
extraídas de `historial()`/`infracciones()` para que pantalla y export
llamen exactamente la misma consulta, con el mismo filtro de
seguridad.

**El punto crítico de esta sesión -- filtro por usuario, verificado
con dos cuentas reales, no solo con una**: ambos exports reciben el
`ciclista_id` únicamente desde `request.state.user` (la sesión
autenticada), nunca desde un parámetro de la URL o el formulario --
así que no hay forma de pedir el historial de otro ciclista cambiando
un id en el query string. Verificado con datos reales, no solo
leyendo el código:
- Sistema completo: 30 viajes reales repartidos entre 3+ ciclistas
  distintos (confirmado con `SELECT` directo en PocketBase).
- `ciclista@urbanbike.com` (Adrian Guizado, `3r2d6eihy391toz`): pantalla
  y Excel coinciden en 25 viajes, todos con su propio id -- ninguno de
  los viajes de otros ciclistas apareció.
- `ciclista01@urbanbike.com` (Ejemplo 1, 1 viaje real): su Excel trajo
  exactamente esa 1 fila (`UB-007`, `A-010515`) -- **no** los 25 viajes
  de Adrian.
- Infracciones: las 4 reales del sistema pertenecen todas a Adrian
  (confirmado en el Grupo 5) -- el export de Adrián trajo las 4, el de
  `ciclista01` trajo 0, coincidiendo con la pantalla de cada uno.
- PDF probado también (`historial/pdf` de `ciclista01`), mismo
  resultado aislado.

## 38. Roles y permisos — mecanismo real, migración de prueba con `bicicletas` (09 de agosto de 2026)

Continúa la sección 30 (`roles`/`permisos`/`rol_permisos` ya cargadas
con 37 permisos y 83 asignaciones reales, pero `AuthMiddleware` seguía
usando las 8 reglas fijas de rol por prefijo, sin tocar). Trabajo en 3
etapas con verificación real entre cada una, tal como se pidió.
**Detenido después de la Etapa 2** -- los demás recursos (alquileres,
ordenes_mantenimiento, tarifas, promociones, estaciones) quedan
pendientes para una sesión aparte.

### Etapa 0 — Mapeo de rutas a permisos (sin tocar código)

56 rutas reales inventariadas en los 3 routers (`admin.py`, `gerente.py`,
`empleado.py`) para los 6 recursos con WorkPanel, mapeadas contra los 37
códigos de `permisos` -- tabla completa en el reporte de esta sesión.
Criterio usado para las rutas GET auxiliares (no documentado antes,
decisión de esta sesión): `GET .../nueva` (formulario vacío) se mapea al
permiso `crear` del recurso (no `leer`) porque solo tiene sentido
mostrarlo a quien puede crear; `GET .../{id}` (ver/editar) se mapea a
`leer` en los dos modos, porque la mutación real ocurre en el `POST`, no
al cargar el formulario. Dos hallazgos aparte, ya documentados en la
sección 31, se repiten aquí porque afectan el mapeo: `admin/estaciones`
y `admin/tarifas` siguen contra PocketBase viejo -- el permiso protege
la ruta igual, pero protege la ruta equivocada por detrás.

### Etapa 1 — El mecanismo central

`app/db/permisos_repo.py` (nuevo): `tiene_permiso(rol_slug, codigo)` --
un `JOIN` real contra `rol_permisos`/`roles`/`permisos`, `False` sin rol
o sin código (nunca acceso por defecto). Probada aislada, sin FastAPI,
6 casos reales (no solo los 2 mínimos pedidos): `admin`+`eliminar` →
`True`; `ciclista`+`crear` → `False` (0 permisos reales); `mantenimiento`+`leer`
→ `True`; `mantenimiento`+`eliminar` → `False`; `vigilancia`+`actualizar`
→ `True`; rol inexistente → `False`. Los 6 pasaron.

`app/middleware/permisos.py` (nuevo): `requiere_permiso(codigo)`, una
fábrica de dependencia real de FastAPI (`Depends(...)`), más
`PermisoDenegadoError` capturada en `app/main.py` con un
`@app.exception_handler` que reproduce exactamente el mismo
redirect+flash que ya usa `AuthMiddleware` -- el usuario final no puede
notar cuál de los dos mecanismos lo bloqueó. Probada aislada con una
mini-app FastAPI desechable (no `app.main`, ninguna ruta real), levantada
en un puerto de prueba real (no simulada): rol con el permiso → 200; rol
sin el permiso → 403; sin sesión → 403.

### Etapa 2 — Migración de `bicicletas` (los 3 routers)

Las 16 rutas reales de `bicicletas` (`admin.py`, `gerente.py`,
`empleado.py`) recibieron `dependencies=[Depends(requiere_permiso("bicicletas:<accion>"))]`.
**Decisión explícita, no trivial**: `AuthMiddleware` (el gate de
departamento por prefijo, ej. `/empleado/operacion` solo para
`admin`+`empleado-operacion`) se dejó intacto, sin tocar -- la
dependencia nueva se suma encima, no reemplaza el gate de departamento.
Se decidió así porque tocar `AuthMiddleware` mismo tenía un efecto
secundario real que se prefirió reportar antes que decidir en
silencio (ver hallazgo abajo).

**Prueba real con las 6 cuentas de rol** (sesión HTTP real de cada una,
matriz completa `GET` × 3 pantallas):

| Rol | `/admin/bicicletas` | `/gerente/bicicletas` | `/empleado/operacion/inventario` | ¿Igual que antes? |
|---|---|---|---|---|
| admin | 200 | 200 | 200 | Sí |
| gerente | 302 (bloqueado) | 200 | 302 (bloqueado) | Sí |
| ciclista | 302 | 302 | 302 | Sí |
| empleado-operacion | 302 | 302 | 200 | Sí |
| empleado-mantenimiento | 302 | 302 | 302 | Sí (ver hallazgo) |
| empleado-vigilancia | 302 | 302 | 302 | Sí (ver hallazgo) |

Además, `POST .../editar` probado real (no solo `GET`) para los 3 roles
que sí llegan a una pantalla de bicicletas -- `admin`, `gerente` y
`empleado-operacion` editaron `UB-003` en secuencia (misma bicicleta,
tres rutas distintas), las 3 con flash real `{"type": "success", "msg":
"Bicicleta actualizada."}`, confirmado decodificando la cookie de sesión
de cada respuesta, no solo el código HTTP. Estado revertido a la
observación original vacía al terminar.

**Hallazgo real, reportado tal como se pidió, no corregido asumiendo la
intención**: la matriz de la sección 30 le da a `empleado-mantenimiento`
el permiso `bicicletas:leer` y a `empleado-vigilancia`
`bicicletas:leer`+`actualizar` -- pero ninguno de los dos puede ejercer
ese permiso hoy en ninguna de las 3 pantallas migradas, porque
`AuthMiddleware` los bloquea por departamento antes de que la nueva
dependencia llegue a evaluarse (confirmado en la matriz: los 3 `302` de
cada uno, sin cambio respecto a antes de esta sesión). No hay ninguna
otra pantalla de "solo lectura de bicicletas" para esos dos roles hoy.
Dicho de otro modo: el catálogo de permisos ya anticipa un acceso que
el enrutamiento actual no permite alcanzar -- **la migración de hoy no
cierra esa brecha, solo confirma que existe y que no se cerró por
accidente**. Cerrarla de verdad requeriría decidir *dónde* mantenimiento
y vigilancia deberían poder ver bicicletas (¿una pantalla nueva?,
¿ampliar qué prefijos puede alcanzar cada rol en `AuthMiddleware`?) --
una decisión de producto, no una que se deba tomar dentro de una
migración de plomería. Queda pendiente, sin decidir, para cuando
Washington lo confirme.

## 39. Roles y permisos — migración de los 5 recursos restantes + evaluación de la ampliación de inventario (09 de agosto de 2026)

**Decisión de Washington sobre el hallazgo de la sección 38**: Opción A
-- ampliar qué prefijos alcanza cada rol en `AuthMiddleware`, en vez de
construir una pantalla nueva de solo lectura para Mantenimiento y
Vigilancia. Evaluación de viabilidad al final de esta sección (sin
implementar todavía, como se pidió).

### Migración de `alquileres`, `ordenes_mantenimiento`, `tarifas`, `promociones`, `estaciones`

Mismo patrón exacto que `bicicletas` (sección 38): `dependencies=[Depends(requiere_permiso("<recurso>:<accion>"))]`
en las 39 rutas restantes de la tabla de mapeo (Etapa 0), sin tocar
`AuthMiddleware`. `admin.py`, `gerente.py` y `empleado.py` importan
ahora `Depends`/`requiere_permiso` en los tres.

**Auditoría previa de "hallazgo del mismo tipo" para los 5 recursos**
(permiso real sin ninguna ruta real que lo alcance) -- ninguno
encontrado, a diferencia de `bicicletas:leer` en la sección 38:
- `alquileres`: solo `admin` y `empleado-operacion` tienen algún
  permiso, y son exactamente los dos roles que `AuthMiddleware` deja
  entrar a `/empleado/operacion/*`. Coincide.
- `ordenes_mantenimiento`: `admin`(4) y `empleado-mantenimiento`(4)
  coinciden con quien entra a `/empleado/mantenimiento/*`;
  `empleado-vigilancia` tiene `crear`/`leer`/`actualizar` (sin
  `eliminar`) y las únicas 2 rutas de este recurso que puede alcanzar
  (`/vigilancia/mantenimiento/cerrar` y `.../certificar`) son
  exactamente `leer` y `actualizar` -- su permiso `crear` no tiene ruta
  *dentro de las rutas de WorkPanel migradas hoy*, pero sí existe una
  ruta real en todo el sistema que lo ejercita
  (`vig_inspeccion_registrar`, Nivel 3 del checklist de devolución,
  sección 23, crea una orden real cuando la inspección reprueba) --
  fuera de alcance de esta migración (es la ruta de inspección, no el
  WorkPanel de órdenes), anotado aquí solo para que quede constancia,
  no es un hallazgo que bloquee.
- `tarifas`, `promociones`, `estaciones`: `admin` y `gerente` tienen
  todo, y son exactamente quienes `AuthMiddleware` deja entrar a
  `/admin/*` y `/gerente/*`. Coincide en los 3.

**Prueba real, matriz completa de 6 roles × 8 pantallas** (GET, sesión
HTTP real de cada cuenta):

| Rol | alquileres | ordenes (mant) | ordenes (vig/cerrar) | tarifas (admin) | tarifas (ger) | promociones | estaciones (admin) | estaciones (ger) |
|---|---|---|---|---|---|---|---|---|
| admin | 200 | 200 | 200 | 200 | 200 | 200 | 200 | 200 |
| gerente | 302 | 302 | 302 | 302 | 200 | 200 | 302 | 200 |
| ciclista | 302 | 302 | 302 | 302 | 302 | 302 | 302 | 302 |
| empleado-operacion | 200 | 302 | 302 | 302 | 302 | 302 | 302 | 302 |
| empleado-mantenimiento | 302 | 200 | 302 | 302 | 302 | 302 | 302 | 302 |
| empleado-vigilancia | 302 | 302 | 200 | 302 | 302 | 302 | 302 | 302 |

Idéntico a como funcionaba antes de esta sesión -- cada rol accede
exactamente a lo mismo que antes, ni más ni menos.

**`POST` real probado, no solo `GET`** (3 casos con repos distintos a
`bicicletas_repo`, para no repetir solo la prueba ya hecha en la
sección 38):
- `gerente` editó una tarifa real (`precio` 3.50→3.51), confirmado en
  ClickHouse y con el flash `{"type": "success"}` decodificado de la
  cookie -- revertido después.
- `gerente` editó una estación real (`capacidad` 40→41), mismo patrón
  -- revertido después.
- `empleado-mantenimiento` editó una orden real (`OM`/`5ad1b89c...`,
  `prioridad` media→alta→media), flash `success` confirmado.
- **Caso negativo aislado**: con la orden en `prioridad=media`,
  `empleado-operacion` intentó cambiarla a `critica` -- bloqueado por
  `AuthMiddleware` (nunca llega a la ruta), confirmado con `SELECT`
  directo: la orden siguió en `media`, no `critica`. Mismo bloqueo que
  existía antes de esta sesión, sin cambio.

### Evaluación de viabilidad — ampliar `empleado/operacion/inventario` a Mantenimiento y Vigilancia (Opción A)

**Backend: ya está listo, cero trabajo adicional de rutas.** Las 6
rutas de `bicicletas` en `empleado.py` ya tienen
`requiere_permiso("bicicletas:<accion>")` desde la sección 38. Si
Mantenimiento y Vigilancia pudieran alcanzar la pantalla, el
mecanismo ya aplicaría correctamente sin tocar una sola línea de
`op_inventario*`: `empleado-mantenimiento` (solo `leer`) pasaría el
`GET` y fallaría `crear`/`editar`/`eliminar`; `empleado-vigilancia`
(`leer`+`actualizar`) pasaría `GET` y `editar`, fallaría
`crear`/`eliminar`. Verificado leyendo el código real de las 6 rutas,
no solo asumido.

**El obstáculo real está en `AuthMiddleware`, y es más grande que "agregar
una regla al diccionario"**: `ROLE_RULES` se recorre con un `for` que
revisa *todos* los prefijos que hacen `match` con la ruta pedida y
**rechaza si cualquiera de ellos no incluye el rol** -- no se queda con
el prefijo más específico. Confirmado leyendo `app/middleware/auth.py`
línea por línea: la ruta `/empleado/operacion/inventario` hace `match`
con **dos** reglas a la vez, `/empleado/operacion`
(`{admin, empleado-operacion}`) y el *fallback* `/empleado`
(`EMPLEADOS`, los 4 roles de empleado). Agregar hoy una tercera regla
más específica y más permisiva
(`/empleado/operacion/inventario: {admin, empleado-operacion,
empleado-mantenimiento, empleado-vigilancia}`) **no serviría de nada**:
la regla vieja y más amplia `/empleado/operacion` seguiría rechazando a
Mantenimiento/Vigilancia igual, porque el `for` no se detiene en el
primer *match*, evalúa todas y basta que una sola falle. El comentario
`# Sub-rutas de empleado (más específicas primero)` ya en el código
describe la intención, pero el algoritmo actual no la implementa como
"la más específica gana" -- implementa "todas las que hagan match deben
aprobar".

**Alcance real de la Opción A, para que Washington decida con el tamaño
correcto, no implementado hoy**:
1. Cambiar el algoritmo de `AuthMiddleware` de "todas las reglas que
   hacen match deben aprobar" a "se aplica solo la regla de prefijo más
   específico" (ej. ordenar las claves por longitud descendente y usar
   la primera que haga match) -- un cambio real al mecanismo central de
   autorización de toda la app, no solo a la regla de `inventario`. Hay
   que auditar que ningún otro prefijo dependa hoy, aunque sea sin
   querer, del comportamiento actual de "todas deben aprobar" antes de
   cambiarlo.
2. Nueva entrada en `ROLE_RULES` para `/empleado/operacion/inventario`
   con los 4 roles de empleado (+`admin`), dejando
   `/empleado/operacion` (sin el sufijo `/inventario`) tal cual está
   para las demás pantallas de Operación (`alquileres`, `pagos`,
   `rebalanceo`, `reportes`) que Mantenimiento/Vigilancia no deben
   poder tocar.
3. En las plantillas (`inventario.html`, `inventario_form.html`):
   ocultar los botones "Insertar" y "Eliminar" cuando el rol de sesión
   no tenga `bicicletas:crear`/`bicicletas:eliminar`, y el botón
   "Actualizar" cuando no tenga `bicicletas:actualizar` -- necesita
   pasar el resultado de `tiene_permiso()` al contexto de la plantilla
   (nuevas variables tipo `puede_crear`/`puede_actualizar`/`puede_eliminar`),
   no solo confiar en que el backend ya rechaza -- un botón visible que
   siempre falla es peor UX que uno oculto.
4. Agregar el link "Inventario" al sidebar de Mantenimiento y
   Vigilancia en `base.html` (hoy no existe ahí en absoluto).

**Conclusión de viabilidad**: sí es viable, y el trabajo de permisos ya
hecho (secciones 38-39) cubre toda la parte de "qué puede hacer cada
quien" sin tocar nada más. Lo que falta no es trivial pero tampoco es
grande -- el punto 1 (cambiar el algoritmo de `AuthMiddleware`) es la
única pieza con riesgo real, porque toca el mecanismo de acceso de
*toda* la aplicación, no solo de esta pantalla; los puntos 2-4 son
trabajo mecánico y acotado. Sin implementar hoy, a la espera de que
Washington confirme el alcance exacto (¿tocar el algoritmo central
ahora, o buscar una forma más acotada de darle esta única excepción a
`inventario` sin tocar el resto de `AuthMiddleware`?).

## 40. Excepción puntual de `AuthMiddleware` para inventario + botones por permiso — RESUELTO el 09 de agosto de 2026

**Decisión de Washington**: la excepción puntual (`if`/`elif` antes del
loop general), no el cambio de algoritmo general propuesto en la
sección 39. El cambio general (regla más específica gana) **queda
pendiente como mejora arquitectónica futura**, con el análisis
matemático de la sección 39 ya hecho como referencia -- no hay que
rehacer esa prueba de equivalencia cuando se retome, solo revisar si
el invariante que la sostiene ("toda regla de fallback otorga un
superconjunto de cada regla específica") sigue siendo cierto para las
reglas que existan en ese momento.

**`app/middleware/auth.py`**: `INVENTARIO_PREFIX`/`INVENTARIO_ROLES_EXTRA`
(nuevas constantes) + un `if path.startswith(INVENTARIO_PREFIX): ... else: <loop de siempre>`
antes del loop de `ROLE_RULES`, exactamente como se propuso -- el loop
general no cambió ni una línea, sigue evaluando exactamente las mismas
7 reglas de siempre para cualquier ruta que no sea
`/empleado/operacion/inventario*`. Se factorizó `_rechazar()` (mismo
flash + redirect que ya existía, ahora sin duplicar el código en dos
lugares) -- refactor cosmético, no cambia comportamiento.

**`app/routers/empleado.py`**: `_permisos_bicicletas(rol_slug)` (nueva)
-- `{puede_crear, puede_actualizar, puede_eliminar}` vía `tiene_permiso()`
real (mismo mecanismo de las secciones 38/39, no una lista hardcodeada
de roles). Pasada al contexto de las 3 rutas que renderizan
`inventario.html`/`inventario_form.html` (`op_inventario`,
`op_inventario_nueva`, `op_inventario_detalle`).

**Plantillas**: `inventario.html` oculta "Nueva bicicleta" sin
`puede_crear`. `inventario_form.html`: modo Ver oculta el link
"Actualizar" sin `puede_actualizar` y el botón+diálogo "Eliminar"
completo (no solo el botón que lo abre) sin `puede_eliminar`; modo
Editar/Crear oculta el botón de guardar si el permiso correspondiente
falta -- deja ver el formulario (de solo lectura visual) en vez de
esconder toda la pantalla, porque el backend ya rechaza el `POST` real
si alguien llega ahí de todos modos (por ejemplo escribiendo
`?modo=editar` a mano).

**Sidebar**: link "Inventario" agregado a las secciones de
Mantenimiento y Vigilancia en `base.html` (antes no existía ahí en
absoluto), mismo ícono que ya usa Operación.

**Prueba real -- foco explícito en que la excepción sea invisible fuera
de `inventario`**: repetí exactamente las mismas 60 combinaciones de
rol×pantalla ya probadas en las secciones 38 y 39 (`admin`/`gerente`/`ciclista`
contra `bicicletas`, `alquileres`, `ordenes_mantenimiento`, `tarifas`×2,
`promociones`, `estaciones`×2) -- **las 60 dieron el código HTTP idéntico
al de antes de este cambio**, confirmando que el `if`/`elif` no tocó
ningún otro camino.

**Comportamiento nuevo, `GET /empleado/operacion/inventario`, 6 cuentas
reales**:

| Rol | Antes de hoy | Después de hoy |
|---|---|---|
| admin | 200 | 200 (sin cambio) |
| gerente | 302 | 302 (sin cambio -- no está en `INVENTARIO_ROLES_EXTRA`, tiene su propia pantalla en `/gerente/bicicletas`) |
| ciclista | 302 | 302 (sin cambio) |
| empleado-operacion | 200 | 200 (sin cambio) |
| empleado-mantenimiento | 302 | **200** |
| empleado-vigilancia | 302 | **200** |

**Botones visibles por rol, verificado en el HTML real devuelto** (no
solo el backend, la UI también respeta el permiso real):
- Lista: "Nueva bicicleta" -- presente para `empleado-operacion`,
  ausente para `empleado-mantenimiento` y `empleado-vigilancia`.
- Ficha (Ver): link "Actualizar" -- presente para `empleado-operacion`
  y `empleado-vigilancia`, ausente para `empleado-mantenimiento`.
  Botón+diálogo "Eliminar" -- presente solo para `empleado-operacion`,
  ausente para los otros dos.

**Backend probado directo (no solo la UI), con datos reales, sobre
`UB-003`**:
- `empleado-mantenimiento` intentó `POST .../editar` -- bloqueado,
  flash real decodificado de la cookie: `{"type": "error", "msg": "No
  tienes permisos para realizar esta acción."}` (el mismo mensaje de
  `PermisoDenegadoError`, no el de `AuthMiddleware` -- confirma que
  bloqueó la capa de permiso fino, no la de departamento, que ya lo
  había dejado entrar). `observacion` de `UB-003` siguió vacía.
- `empleado-vigilancia` sí editó `UB-003` (`observacion` cambió a
  "prueba vigilancia ok", confirmado en ClickHouse) -- tiene
  `bicicletas:actualizar` real.
- `empleado-vigilancia` intentó `POST .../eliminar` -- bloqueado, mismo
  flash de permiso denegado; `UB-003` siguió existiendo
  (`count()=1`, no `0`).
- Estado revertido al original (`observacion=''`) al terminar, sin
  residuo.

## 41. Pantalla de administración de roles y permisos — RESUELTO el 09 de agosto de 2026

Última pieza pendiente desde la sección 29: la matriz real donde el
admin ve y modifica qué rol tiene qué permiso, sin tocar ninguna base
de datos a mano.

### Catálogo (sembrado antes de construir la pantalla)

`permisos:actualizar` (nuevo, único código para toda la pantalla --
ver y modificar son la misma acción administrativa, no se separó en
`leer`/`actualizar` porque no se pidió esa granularidad) insertado en
`urbanbike_operativa.permisos` y otorgado únicamente a `admin` en
`rol_permisos`. Catálogo pasó de 37 a 38 permisos, asignaciones de 83 a
84.

### `app/db/permisos_repo.py` (ampliado)

- `resolver_usuario_por_email()`: id real de `usuarios` para
  `otorgado_por`, sentinela si no existe -- a diferencia de
  `infracciones_repo.resolver_o_crear_usuario()`, aquí no crea el
  usuario si falta (es un dato de auditoría de quién tocó el botón, no
  una entidad de negocio).
- `listar_matriz()`: roles (orden fijo, no alfabético) + permisos
  agrupados por recurso + el conjunto real de asignaciones hoy. IDs
  normalizados a `str` aquí mismo -- clickhouse-connect devuelve
  columnas `UUID` como `uuid.UUID`, compararlas directo contra un
  `grant_set` de tuplas string en Jinja hubiera sido frágil.
- `otorgar()`/`revocar()`/`toggle()`: `INSERT`/`ALTER ... DELETE`
  reales sobre `rol_permisos`, tal como se pidió explícitamente hoy --
  **decisión distinta del comentario original de la sección 29**
  ("una concesión se otorga o se revoca, nunca se actualiza in place,
  mismo criterio que `alquiler_eventos`/`bicicleta_eventos`", que
  describía un log de eventos append-only). Aquí revocar sí borra la
  fila de verdad -- sin historial de "cuándo se otorgó y por quién" una
  vez revocado. Documentado aquí para que quede claro que fue un
  cambio de criterio consciente, no una inconsistencia accidental.

### `app/routers/admin.py`

`GET /admin/permisos` (matriz) y `POST /admin/permisos/toggle`, ambas
con `dependencies=[Depends(requiere_permiso("permisos:actualizar"))]`
-- mismo mecanismo de las secciones 38-40, ninguna verificación nueva
inventada. `_MODULO_PLURAL` (usado por `_log()`/auditoría) ampliado con
`"permiso": "permisos"`.

### `app/templates/admin/permisos.html` (nueva)

Tabla con fila de encabezado por recurso (11 grupos: los 10 originales
+ `permisos`), 38 filas de permiso × 6 columnas de rol = 228 casillas.
Cada casilla es un `<form>` propio con dos campos ocultos
(`id_rol`/`id_permiso`) y un `<input type="checkbox" onchange="this.form.submit()">`
-- mismo patrón de auto-submit ya usado en otros selects de filtro de
la app, sin JS/AJAX nuevo. Link "Roles y Permisos" agregado al sidebar
de Admin (sección Gestión).

### Prueba real

**Estructura de la matriz, no solo que cargue**: `GET /admin/permisos`
como admin -- confirmado con el HTML real devuelto: 228 formularios
(38×6, coincide exacto con el catálogo real), 84 casillas marcadas
(coincide exacto con las asignaciones reales de `rol_permisos`), los 6
nombres de rol en el encabezado en el orden esperado.

**Acceso por rol, las 6 cuentas reales**: solo `admin` (200); los otros
5 -- `gerente`, `ciclista`, `empleado-operacion`, `empleado-mantenimiento`,
`empleado-vigilancia` -- bloqueados (302) por `AuthMiddleware` antes de
llegar siquiera a `requiere_permiso()` (el prefijo `/admin` ya los
bloquea a todos menos `admin`; el permiso fino es una segunda capa,
redundante para estos 5 hoy pero correcta como defensa en profundidad).

**El toggle real, con el par exacto pedido** (`ordenes_mantenimiento:crear`
para Vigilancia): revocado desde la pantalla real (sesión de
`admin@urbanbike.com`) -- confirmado con `SELECT` directo (`0` filas) y
con `tiene_permiso("empleado-vigilancia", "ordenes_mantenimiento:crear")`
devolviendo `False`. Re-otorgado después, restaurado a `1` fila.

**Hallazgo real encontrado durante esta prueba, no corregido en
silencio**: ese permiso específico (`ordenes_mantenimiento:crear` para
Vigilancia) no tiene ninguna ruta real conectada a `requiere_permiso()`
hoy -- la única ruta real donde Vigilancia crea una orden es
`POST /empleado/vigilancia/inspeccion/{bici_id}/registrar` (flujo de
inspección, sección 23), que quedó deliberadamente fuera de la
migración de la sección 39 (no es el WorkPanel de órdenes). Revocar el
permiso ahí no habría bloqueado nada observable, no porque la pantalla
esté mal, sino porque esa ruta nunca se conectó al mecanismo fino.
Reportado a Washington antes de simular una prueba que no habría sido
real; decisión tomada: sustituir por `ordenes_mantenimiento:actualizar`
(mismo recurso, mismo rol, sí conectado desde la sección 39 vía
`POST /empleado/vigilancia/mantenimiento/{oid}/certificar`) en vez de
ampliar el alcance de hoy tocando el flujo de inspección.

**Prueba de bloqueo real de punta a punta, 3 pasos, con un `oid` falso
(la dependencia de FastAPI corre antes que el cuerpo de la ruta, así
que ni siquiera hace falta una orden real para probar el bloqueo -- el
error cambia de forma según en qué capa se detiene)**:
1. **Antes de revocar**: `empleado-vigilancia` intenta certificar un
   `oid` inexistente -- la ruta se ejecuta y falla en PocketBase
   (`"The requested resource wasn't found."`), confirmando que hoy
   *sí* llega a la ruta.
2. **Revocado** (desde la pantalla real): mismo intento -- bloqueado
   con `{"type": "error", "msg": "No tienes permisos para realizar
   esta acción."}`, el mensaje real de `PermisoDenegadoError`, nunca
   llega al cuerpo de la ruta.
3. **Re-otorgado** (desde la pantalla real): mismo intento -- vuelve al
   error de "not found" de PocketBase, confirmando que la ruta se
   volvió a alcanzar.

Estado final verificado: `rol_permisos` de vuelta a **84** filas
(mismo total que al empezar), Vigilancia con exactamente
`ordenes_mantenimiento:crear`/`leer`/`actualizar` (sin duplicados, sin
huérfanos). Regresión final contra 6 pantallas ya migradas (secciones
38-40): sin cambios.

## 42. Excepciones de permiso por usuario individual — RESUELTO el 09 de agosto de 2026

Diseño discutido y aprobado en el turno anterior (esquema, lógica de
`tiene_permiso()`, Opción B para reutilizar cambio de rol) antes de
tocar código, tal como se pidió dado que esto toca el mecanismo central
de acceso.

### Hallazgo previo al diseño, verificado antes de proponer el esquema

`admin@urbanbike.com` y `gerente@urbanbike.com` **no tienen fila en
`urbanbike_operativa.usuarios`** (confirmado con `SELECT`) -- solo 4 de
los 6 roles de prueba existen ahí. Esto descartó `usuario_permisos.id_usuario`
como `UUID` referenciando esa tabla (dejaría fuera a los dos roles más
privilegiados) a favor de `String` = PocketBase `users.id`, la
identidad real que ya usa la sesión (`request.state.user["id"]`) y que
garantizadamente existe para cualquiera de los 6 roles.

### Esquema (`db/01_operativa_schema.sql` + tabla real)

```sql
CREATE TABLE urbanbike_operativa.usuario_permisos
(
    id_usuario   String,                  -- PocketBase users.id
    id_permiso   UUID,
    estado       LowCardinality(String),  -- 'otorgado' | 'revocado'
    otorgado_por UUID DEFAULT toUUID('00000000-0000-0000-0000-000000000000'),
    fecha        DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (id_usuario, id_permiso);
```

Mismo criterio que `rol_permisos` (sección 41): sin fila = sin
excepción (hereda del rol); `INSERT`/`DELETE` reales, nunca `UPDATE` in
place.

### `app/db/permisos_repo.py`

`tiene_permiso()` ganó un tercer parámetro opcional `id_usuario: str | None = None`
(por defecto `None`, así ningún llamador existente se rompe con solo
agregar el parámetro): si se pasa, busca primero una excepción real en
`usuario_permisos` -- si existe, gana siempre (en cualquier dirección);
si no, cae al comportamiento de siempre (heredar de `rol_permisos`).
Nuevas: `listar_permisos_usuario(id_usuario, rol_slug)` (los 38 permisos
agrupados por recurso, cada uno con `heredado`/`excepcion`/`efectivo`/`accion_boton`
ya calculados) y `set_excepcion_usuario(id_usuario, id_permiso, accion, otorgado_por)`
(`'otorgar'|'revocar'|'quitar'`, siempre `DELETE` de cualquier excepción
previa primero).

**Los 4 sitios reales que llamaban a `tiene_permiso()` (los mismos 4 ya
identificados en el diseño), actualizados para pasar `id_usuario`**:
- `app/middleware/permisos.py` (`requiere_permiso()`): pasa
  `user.get("id")` de la sesión real.
- `app/routers/empleado.py` (`_permisos_bicicletas()`, 3 llamadas
  internas): la función ganó un segundo parámetro `id_usuario`, sus 3
  llamadores reales (`op_inventario`, `op_inventario_nueva`,
  `op_inventario_detalle`) actualizados para pasar `user.get("id", "")`
  -- sin esto, los botones de `inventario.html` habrían seguido
  reflejando solo el rol, mintiendo sobre lo que el backend en realidad
  permite a un usuario con excepción real.

### `app/routers/admin.py` — Opción B aplicada

`usuarios_editar()` ganó `next: str = Form("/admin/usuarios")`, usado en
los 3 `return _flash(...)` (éxito y los 2 casos de error) -- el
formulario de Usuarios existente no manda `next`, así que su
comportamiento no cambió (sigue redirigiendo a `/admin/usuarios`);
solo la pantalla nueva lo aprovecha para volver a
`/admin/permisos-usuario/{uid}` después de cambiar el rol, sin duplicar
la lógica de asignación.

Nuevas: `GET /admin/permisos-usuario` (buscador, filtra PocketBase
`users` por nombre o correo -- no `urbanbike_operativa.usuarios`, mismo
motivo del hallazgo previo), `GET /admin/permisos-usuario/{uid}`
(ficha), `POST /admin/permisos-usuario/{uid}/toggle` -- las 3 con
`dependencies=[Depends(requiere_permiso("permisos:actualizar"))]`, el
mismo permiso de la sección 41, no uno nuevo.

### Plantillas nuevas

`admin/permisos_usuario_buscar.html` (búsqueda por `GET`+recarga,
mismo patrón que el resto de la app) y
`admin/permisos_usuario_detalle.html` (rol actual con `<select>` que
postea a `/admin/usuarios/{uid}/editar` vía la Opción B; 38 permisos
agrupados por recurso, un solo botón por fila calculado en el backend
-- "Otorgar a este usuario" si no viene heredado y sin excepción,
"Revocar para este usuario" si viene heredado y sin excepción, "Quitar
excepción" si ya hay una activa -- por construcción es imposible crear
una excepción redundante desde la UI). Link "Excepciones por Usuario"
agregado al sidebar de Admin, con match exacto (`p == '/admin/permisos'`)
corregido en el link de la sección 41 para que no se marcara activo
también en las pantallas nuevas por ser sub-string.

### Regresión completa, ejecutada antes de tocar el caso nuevo (tal como se exigió)

Las 5 pruebas de las secciones 38-41 repetidas una por una contra la
app con el cambio ya aplicado, comparando contra los resultados
documentados ahí -- **0 diferencias en las 5**:

1. **Matriz de 66 combinaciones rol×pantalla** (60 de las secciones
   38-39 + las de `inventario` de la sección 40): las 66 dieron el
   mismo código HTTP exacto que antes.
2. **`POST` real con 3 repos distintos** (`gerente` edita tarifa y
   estación, `empleado-mantenimiento` edita una orden) + **caso
   negativo aislado** (`empleado-operacion` intenta tocar la orden, se
   confirma con `SELECT` que no cambió nada): mismo resultado exacto
   que la sección 39.
3. **Excepción de `inventario` para Mantenimiento/Vigilancia**: acceso
   (200/302 según corresponde), botón "Nueva bicicleta" oculto para
   ambos, `empleado-mantenimiento` bloqueado al editar (mismo
   `PermisoDenegadoError`), `empleado-vigilancia` sí edita pero sigue
   sin poder eliminar -- idéntico a la sección 40.
4. **Toggle real de `rol_permisos` desde `admin/permisos.html`**: los 3
   pasos exactos de la sección 41 (antes: "not found" real; revocado:
   `PermisoDenegadoError`; re-otorgado: vuelve a "not found") dieron el
   mismo resultado, `rol_permisos` de vuelta a 84 filas.
5. **Estructura de la matriz** (`admin/permisos.html`): sigue en 228
   formularios / 84 marcadas, sin cambio.

### Prueba del caso nuevo -- con una sustitución razonada del ejemplo literal

El ejemplo pedido ("otorga `bicicletas:crear` a un ciclista") no era
observable: `ciclista` está completamente bloqueado por `AuthMiddleware`
de las 3 pantallas de `bicicletas` (sin el carve-out que sí tienen
Mantenimiento/Vigilancia desde la sección 40) -- el mismo tipo de
hallazgo ya reportado en la sección 41 (permiso real sin ruta
alcanzable), esta vez aplicándose a *cualquier* permiso para ciclista,
no solo a uno. Sustituido por: otorgar `bicicletas:crear` a
`empleado.mant@urbanbike.com` (Joel Mazabanda, id real de PocketBase
`ll87826fqi1skvg`) -- su rol (`empleado-mantenimiento`, solo `leer`) no
se lo da, pero sí alcanza `/empleado/operacion/inventario/*` desde la
sección 40 -- comparado contra `empleado.vig@urbanbike.com` (Miguel
Torres, `uhx6hsl7re6i8k6`), mismo nivel, sin ninguna excepción,
demostrando que es por usuario y no por rol.

**Base confirmada antes de otorgar nada**: ambos bloqueados
(`GET .../nueva` → 302, botón "Nueva bicicleta" ausente para los dos).

**Otorgado desde la pantalla real** (buscador → ficha de Joel → botón
"Otorgar a este usuario" en la fila de `bicicletas:crear`): confirmado
en ClickHouse (`usuario_permisos`: 1 fila, `estado='otorgado'`) y con
`tiene_permiso("empleado-mantenimiento", "bicicletas:crear", "ll87826fqi1skvg")`
→ `True`, mientras que la misma llamada **sin** `id_usuario` sigue
dando `False` (confirma que el fallback de rol puro no se tocó).

**Prueba real de punta a punta, con datos reales**:
- Joel (con la excepción): `GET .../nueva` → 200, botón visible, y
  **creó una bicicleta real** (`UB-011`, `POST /operacion/inventario/crear`)
  -- confirmada en ClickHouse con su `numero_serie` de prueba.
- Miguel (sin excepción): mismo intento de crear -- bloqueado con el
  mismo `PermisoDenegadoError` real; **no** se creó ninguna fila para
  él (confirmado: solo `UB-011` existe, no la de Miguel).
- **Acotamiento de la excepción, no un bypass general**: Joel intentó
  `eliminar` `UB-011` (permiso que nunca se le otorgó) -- bloqueado,
  mismo error; `UB-011` siguió existiendo.
- **Quitar la excepción** (botón real en la ficha, ahora mostrando
  "⚡ Excepción: Otorgado" con el botón "Quitar excepción"): confirmado
  con `SELECT` (`usuario_permisos` de Joel vuelve a 0 filas), y Joel
  vuelve a estar bloqueado de `GET .../nueva` (302), igual que antes de
  otorgarle nada.

**Limpieza**: `UB-011` (artefacto mecánico de la prueba, no evidencia
de negocio como los casos anteriores) borrada por `admin` al terminar
-- conteo de bicicletas reales de vuelta a 10. `usuario_permisos` en 0
filas, `rol_permisos` en 84 -- ambas tablas en el mismo estado que
antes de empezar esta sesión.

## 43. Mejoras de presentación a la pantalla de excepciones por usuario (09 de agosto de 2026)

Dos cambios puramente de presentación sobre `admin/permisos-usuario`
(sección 42) -- sin tocar `tiene_permiso()`, `permisos_repo.otorgar`/`revocar`/`toggle`,
ni la lógica de excepciones, tal como se pidió.

### 1. Tabla completa por defecto en el buscador

`permisos_usuario_buscar()` ya no espera un `q` para traer resultados:
carga siempre `pb.list_records("users", sort="-created", per_page=100, expand="rol")`
-- el mismo `list_records` que ya usa `usuarios_list()` en
`admin/usuarios.html`, no una copia con otro criterio. El campo de
búsqueda dejó de ser un `<form method="get">` que recarga la página --
ahora es un `oninput="filtrarTabla(this, 'tabla-usuarios-permisos')"`
que reutiliza `table-search.js` (ya existente, mismo patrón que
`admin/bitacora.html`), filtrando en el navegador la tabla que ya está
completa en pantalla. El parámetro `q` de la ruta se eliminó por
completo -- ya no tenía ningún uso real.

### 2. Resumen de 4 indicadores en la ficha de detalle

`permisos_usuario_detalle()` calcula `resumen = {leer, crear, actualizar, eliminar}`
recorriendo el mismo `grupos` que ya arma `listar_permisos_usuario()`
más arriba en la misma función -- cada indicador es `True` si `p["efectivo"]`
es verdadero para *algún* permiso con esa `accion`, en cualquier
recurso. **Cero consultas nuevas** -- es una vuelta más sobre datos ya
en memoria. Etiquetas: Lectura=`leer`, Escritura=`crear`,
Actualizar=`actualizar`, Eliminar=`eliminar` (el nombre "Escritura"
para la acción `crear` es el que pidió Washington).

Los 4 se renderizan como `kpi-card` (mismo patrón visual que
`empleado/vigilancia/alertas.html`) -- `<div>` puros, sin `<form>` ni
`onclick`, arriba del desglose de 38 filas que ya existía sin tocarlo.

### Prueba real con 3 usuarios (2 pedidos + 1 caso mixto para probar la lógica "al menos un recurso" de verdad, no solo los extremos)

- **Buscador**: `GET /admin/permisos-usuario` sin ningún parámetro
  devolvió los **10** usuarios reales -- confirmado contra
  `totalItems` real de la colección `users` de PocketBase, mismo
  número exacto.
- **`admin@urbanbike.com`**: los 4 indicadores en "Sí" (verde) -- tiene
  los 38 permisos.
- **`ciclista@urbanbike.com`** (Adrian Guizado): los 4 en "No" -- 0
  permisos reales en `rol_permisos` para `ciclista`, sin excepciones
  (la tabla `usuario_permisos` quedó en 0 filas al cerrar la sección
  42).
- **`empleado.vig@urbanbike.com`** (caso mixto, no pedido pero
  agregado para no probar solo los dos extremos triviales): permisos
  reales de Vigilancia consultados primero (`bicicletas:leer/actualizar`,
  `ordenes_mantenimiento:crear/leer/actualizar`,
  `infracciones:crear/leer/actualizar` -- **sin ningún `eliminar` en
  ningún recurso**) para predecir el resultado antes de mirar la
  pantalla: Lectura=Sí, Escritura=Sí, Actualizar=Sí, Eliminar=No. La
  pantalla real dio exactamente esa combinación -- confirma que el
  cálculo agrega de verdad sobre todos los recursos, no que solo
  copie un valor fijo.
- Confirmado también que el desglose detallado sigue mostrando las 38
  filas de siempre, con sus 38 formularios de otorgar/revocar/quitar
  intactos -- el resumen nuevo no reemplazó ni ocultó nada de lo que
  ya existía.

## 44. Indicadores de acción masiva + rediseño de la ficha de excepciones (09 de agosto de 2026)

Cambio de decisión sobre la sección 43: los 4 indicadores generales
dejan de ser de solo lectura y pasan a ser botones de acción masiva
reales, más 3 mejoras de presentación acordadas en la misma tarea.
Único archivo tocado en el frontend:
`app/templates/admin/permisos_usuario_detalle.html`; backend nuevo en
`app/db/permisos_repo.py` y `app/routers/admin.py`.

### 1. Indicadores como acción masiva real (lo más delicado)

Diseño: cada indicador puede estar en 3 estados reales, no solo
Sí/No -- `todos` (el usuario tiene la acción efectiva en el 100% de
los recursos aplicables), `parcial` (en algunos sí y en otros no) y
`ninguno` (en ninguno). El botón siempre es uno solo y su dirección se
decide en el servidor, no en el cliente: si el estado no es `todos`,
el botón "Otorga en todos" (llena lo que falta); si es `todos`, el
botón pasa a "Revoca de todos".

Dos funciones nuevas en `permisos_repo.py`, ambas reutilizando
`listar_permisos_usuario()` que ya existía -- cero consultas nuevas
más allá de las que esa función ya hacía:

- `resumen_por_accion(id_usuario, rol_slug)`: agrupa los 38 permisos
  por acción (`leer`/`crear`/`actualizar`/`eliminar`) y devuelve, por
  cada una, `{total, efectivos, estado}`.
- `set_excepcion_masiva(id_usuario, rol_slug, accion, otorgar, otorgado_por)`:
  recorre los recursos de esa acción y llama a `set_excepcion_usuario()`
  (la misma función de fila única de la sección 42, sin duplicar
  lógica) recurso por recurso -- `otorgar=True` crea una excepción
  `otorgado` en cada recurso donde el usuario **no** la tiene hoy;
  `otorgar=False` crea una excepción `revocado` en cada recurso donde
  **sí** la tiene hoy, sea por rol o por una excepción `otorgado`
  previa. Devuelve cuántos recursos se tocaron de verdad.

Ruta nueva `POST /admin/permisos-usuario/{uid}/toggle-masivo`
(`accion`, `direccion`), protegida con el mismo permiso
`permisos:actualizar` que ya protegía el resto de la pantalla.

**Matiz real encontrado en la prueba (no es un error, es el diseño tal
como se pidió) — la "reversión exacta" es funcional, no a nivel de
filas:** desactivar un indicador **inserta** una fila `revocado`
explícita (tal como se especificó: "insertar fila estado='revocado'"),
nunca borra la excepción. Si el usuario no tenía el permiso por rol en
ningún recurso (como Miguel en la prueba), después de otorgar y
revocar quedan **filas `revocado` reales, no cero filas** -- el efecto
sobre `tiene_permiso()` es idéntico al estado original (`efectivo=False`
en los 7 recursos, botón bloqueado de nuevo, indicador vuelve a
"0/7 · ninguno"), pero el desglose de 38 filas pasa a mostrar
"Excepción: Revocado" en vez de "No heredado" en esos 7 recursos. Es
la diferencia entre "revertir el efecto" (así quedó implementado, es
lo que pidió el punto 2 de la Parte 1) y "borrar el rastro" (no se
pidió, y de hecho un rastro auditable de una revocación explícita es
el comportamiento correcto para producción). Los 7 registros que dejó
la prueba real se limpiaron manualmente para devolver a Miguel a su
estado real de cero excepciones (ver prueba abajo) -- eso fue limpieza
de artefactos de prueba, no un cambio de comportamiento del sistema.

#### Prueba real exigida

Usuario: `empleado.vig@urbanbike.com` (Miguel Torres, id PocketBase
`uhx6hsl7re6i8k6`, rol `empleado-vigilancia`) -- elegido porque su rol
no da `eliminar` en ninguno de los 7 recursos que tienen esa acción en
el catálogo (`alquileres`, `bicicletas`, `estaciones`,
`ordenes_mantenimiento`, `promociones`, `tarifas`, `usuarios`), estado
inicial limpio "0/7 · ninguno" confirmado con `SELECT` antes de
empezar (0 filas en `usuario_permisos`), y puede llegar a
`/empleado/operacion/inventario` (excepción de la sección 40), lo que
hace la prueba de HTTP real alcanzable de punta a punta.

1. **Otorgar**: `POST /admin/permisos-usuario/{uid}/toggle-masivo`
   (`accion=eliminar`, `direccion=otorgar`) como `admin` real → flash
   `"Eliminar: otorgado en 7 recurso(s)."` (decodificado de la cookie
   de sesión, no solo el código HTTP). `SELECT` confirmó **7 filas
   reales nuevas** en `usuario_permisos`, una por recurso, todas
   `estado='otorgado'`. La ficha de detalle recargada mostró el
   indicador "Eliminar" en 7/7 verde y las 7 filas del desglose como
   "Excepción: Otorgado" (antes "No heredado").
2. **Bicicleta real de prueba** (`TEST-PARTE1-DEL`) insertada en
   `urbanbike_operativa.bicicletas`. Con la sesión real de Miguel,
   `POST /empleado/operacion/inventario/{bid}/eliminar` → flash
   `"Bicicleta TEST-PARTE1-DEL eliminada."` y `SELECT` confirmó que la
   fila ya no existe -- Miguel pudo eliminar donde antes no podía, con
   permiso real, no simulado.
3. **Revocar**: `direccion=revocar` → flash
   `"Eliminar: revocado en 7 recurso(s)."`. Indicador volvió a "0/7 ·
   ninguno", botón volvió a "Otorgar en todos" (reversión funcional
   confirmada). Segunda bicicleta de prueba (`TEST-PARTE1-DEL2`)
   creada; Miguel intentó eliminarla con la misma sesión → flash de
   error real `"No tienes permisos para realizar esta acción."` (el
   `PermisoDenegadoError` de siempre), bicicleta sigue existiendo --
   bloqueo confirmado de nuevo.
4. **Limpieza**: las 2 bicicletas de prueba y las 7 filas `revocado`
   que dejó la prueba en `usuario_permisos` para Miguel se borraron
   (`ALTER ... DELETE`) -- estado final verificado en 0 filas para
   ambas tablas, igual que antes de empezar la prueba.

### 2. Rol actual estático + bloque separado "Cambiar rol"

El bloque superior ahora muestra el rol de hoy como texto simple
(`usuario.rol_nombre`, sin `<select>`). Debajo, un `card` visualmente
distinto (borde izquierdo `--primary`, título propio "Cambiar rol")
con su propio `<select>` de roles y su propio botón "Confirmar cambio
de rol" -- mismo `<form>` a `usuarios_editar()` con `next` apuntando de
vuelta a la ficha, sin cambiar nada de esa lógica ya probada en la
sección 42.

### 3. Textos de ayuda en letra pequeña retirados

Se quitaron los 3 textos, con el motivo de cada uno:

- **"Cada excepción es real..."**: explicaba que el botón hace una
  escritura real en `usuario_permisos`, no una simulación. Ya no
  aporta nada que la propia interacción (indicador que cambia de
  estado, filas que cambian de etiqueta) no comunique por sí sola.
- **"Resumen de solo lectura..."**: con el cambio de esta sección, este
  texto **quedó factualmente falso** -- los indicadores dejaron de ser
  de solo lectura. Se retira por ese motivo, no solo por estética.
- **"Cambiar el rol reutiliza..."**: era una nota de implementación
  (qué función interna reutiliza el cambio de rol) sin valor para
  quien usa la pantalla.

Ninguno de los 3 describía un riesgo o una consecuencia irreversible
que el usuario necesitara ver antes de actuar -- por eso se consideran
seguros de retirar.

### 4. Jerarquía visual del desglose de 38 filas

Antes: pastilla con emoji `⚡` para toda excepción, sin distinción de
color entre "Otorgado"/"Revocado", y "Heredado (Sí/No)" con el mismo
peso visual que una excepción real. El emoji además incumplía la regla
del proyecto "cero emojis en cualquier pantalla" (sección 3).

Cambios (reutilizando tokens ya existentes, ninguno nuevo):

- **Excepción activa** (otorgado/revocado): `badge-green`/`badge-red`
  en negrita -- mismo patrón que ya usan las demás pantallas del
  proyecto -- con una segunda línea `text-muted text-sm` aclarando el
  motivo ("Su rol no lo da" / "Su rol sí lo da"). Se quitó el `⚡`.
- **Heredado por rol** (sin excepción): ya no es una pastilla de color,
  pasa a texto `--text-muted` con un ícono de check en línea -- menos
  peso visual porque es el caso "nada especial que ver aquí".
  "Heredado (Sí)" se renombró a "Heredado por rol" (más claro que
  "Sí").
- **No heredado, sin excepción**: mismo tratamiento muted, con
  `opacity:0.7` adicional -- el estado con menos información útil de
  los cuatro, se apaga un poco más que "Heredado por rol".
- Código del permiso subido de `0.82rem` a `0.88rem` monospace;
  filas con más `padding` vertical (`10px`) para que la tabla respire
  más con los nuevos bloques de texto secundario.

Cambio mostrado antes de este cierre para revisión, tal como se pidió
-- ver capturas del HTML real servido en la sesión (`detalle_revocado.html`
en el scratchpad de esta conversación, estado ya limpio).



- Esquema operativo de 29 tablas en ClickHouse, con datos reales migrados:
  11 bicicletas, 9 estaciones, catálogo de marcas/categorías/modelos,
  tarifas reales por categoría y membresía.
- Tres componentes visuales construidos con datos de ejemplo: flujo del
  alquiler, checklist de devolución, tarjeta de catálogo (esta última ya
  con datos 100% reales).
- Generador de ERD (`db/erd_clickhouse.py` y `db/generar_erd_visual.py`).
- Esquemas de `urbanbike_tactica` (7 tablas) y `urbanbike_estrategica`
  (3 tablas) creados y verificados, sin datos (ver sección 7).
- Carpeta `datos/{crudo,proceso,terminado}/` creada (ver sección 2).
- Viajes y pagos reales migrados a `alquileres`/`alquiler_eventos` (26
  alquileres); `urbanbike_tactica` y `urbanbike_estrategica` cargadas
  con datos reales (junio 2026) y 3 KPI de ejemplo (ver sección 8).
- WorkPanel de bicicletas en `empleado/operacion/inventario.html`
  (lista+filtro+paginación+4 modos) y `admin`/`gerente/bicicletas.html`
  migrados a `urbanbike_operativa.bicicletas` vía `app/db/bicicletas_repo.py`
  compartido; fotos reales con lightbox ya conectadas (ver sección 9).
- WorkPanel de alquileres en `empleado/operacion/alquileres.html`
  (lista+filtro+paginación+Ver/Completar/Cancelar/Insertar) migrado a
  `urbanbike_operativa.alquileres` vía `app/db/alquileres_repo.py`
  compartido, sincronizando bicicletas a través de `bicicletas_repo`;
  `ORDER BY` de `alquileres` corregido (ver sección 10).
- Airflow orquestando `07`/`08`/`09` cada hora de verdad, con los tres
  scripts corregidos para ser idempotentes y escribiendo archivos
  reales en `datos/{crudo,proceso,terminado}` (ver sección 18).
- Riesgo de `ORDER BY` mutable resuelto en las 11 tablas de
  `db/01_operativa_schema.sql` que lo tenían (las 9 restantes de la
  sección 0, en esta sesión); huérfanos del seed original limpiados en
  las 9 tablas afectadas, con barrido de verificación en todo el
  sistema (ver sección 19).
- WorkPanel de promociones en `gerente/promociones.html` (primer
  WorkPanel real del rol Gerente, lista+filtro+paginación+4 modos) vía
  `app/db/promociones_repo.py`; descuento real aplicado en el precio
  del catálogo del ciclista (`_catalogo_bicicletas()`), visible con
  badge y precio tachado, probado en vivo con una promoción real (ver
  sección 20).
- Editor de tarifas de Gerente repuntado de PocketBase (desconectado)
  a `urbanbike_operativa.tarifas` vía `app/db/tarifas_repo.py`;
  modalidad "semana" agregada de punta a punta (8 tarifas reales,
  consulta, catálogo del ciclista, toggle) — probado en vivo editando
  un precio real y alternando las tres modalidades (ver sección 21).
- Cuarto componente de línea de ruta, `componentes/flujo_orden.html`,
  integrado en el panel de mantenimiento (`ordenes_form.html`, modo
  Ver) — probado con una orden real cerrada y una orden de prueba
  avanzada por los 5 estados reales (ver sección 22).
- Checklist de devolución conectado a datos reales, Nivel 2 y Nivel 3
  (ver sección 23): los 12 ítems reales reemplazan la lista inventada,
  `inspecciones`/`inspeccion_detalle` se escriben de verdad vía
  `app/db/inspecciones_repo.py`. El resultado de la inspección ya mueve
  el resto del sistema real: `bicicletas.estado` (ambas ramas, vía
  `bicicletas_repo.actualizar()`), orden de mantenimiento real
  (`ordenes_repo.crear()`, técnico asignado automáticamente por menor
  carga), infracción real con cargo por daños incluido
  (`app/db/infracciones_repo.py`, nuevo). Probado de punta a punta con
  una bicicleta real: orden y infracción reales confirmadas en
  ClickHouse, catálogo del ciclista ya no muestra la bicicleta
  reprobada como disponible.
- `kpi_resultados` ampliado de 3 a 9 KPI reales (Gerencia, Administración
  y Vigilancia con datos reales por primera vez), agregados a
  `calcular_kpis()` en `etl/08_calcular_tactica.py` para que el DAG
  horario los siga recalculando; 9 candidatos más evaluados y
  descartados con el dato específico que falta para cada uno (ver
  sección 24).
- `gerente/bicicletas.html` y `gerente/estaciones.html` migradas de
  CRUD en modal a WorkPanel real (lista+filtro+paginación+4 modos),
  cerrando el pendiente de la sección 20. `estaciones` además se
  reconectó de PocketBase (desconectada) a
  `urbanbike_operativa.estaciones` vía `app/db/estaciones_repo.py`
  nuevo (mismo patrón de espejo que `bicicletas_repo.py`); `bicicletas`
  se quedó en `bicicletas_repo.py` ya existente, sin repo nuevo.
  Probado en vivo con las 4 operaciones en ambas pantallas y
  verificación de no-regresión en las 5 pantallas que ya dependían de
  `bicicletas_repo` (ver sección 26).
- Alquiler manual de Operación: se descubrió que no calculaba ningún
  precio (no solo que ignorara promociones); ahora `alquileres_repo.cotizar()`
  calcula la tarifa real + la promoción de mayor ahorro (mismo helper
  que el catálogo del ciclista) y `crear_presencial()` guarda
  `subtotal`/`descuento`/`total`/`id_promocion` reales, cerrando el
  hallazgo suelto 1 de la sección 25. Probado en vivo con una promoción
  real aplicada a un alquiler real, `id_promocion` y `usos_actuales`
  confirmados con `SELECT` (ver sección 27).
- `urbanbike_operativa.bicicleta_eventos` (nueva, mismo patrón que
  `alquiler_eventos`): `bicicletas_repo.actualizar()` ya registra cada
  cambio de estado real (solo cuando de verdad cambia, sin tocar la
  firma ni ninguno de sus 5 llamadores), infraestructura para
  `resumen_mensual_flota` -- el cálculo en sí queda pendiente hasta
  acumular un mes completo de historia real desde hoy, sin reconstruir
  el pasado (ver sección 28).
- Roles y permisos: auditoría completa del control de acceso actual
  (centralizado en `AuthMiddleware`, no repetido por ruta) y diseño de
  `roles`/`permisos`/`rol_permisos` en `urbanbike_operativa`; las 3
  tablas creadas con los 6 roles reales precargados (`es_sistema=1`).
  Catálogo de permisos, pantalla de administración y repunte de
  `AuthMiddleware` quedan pendientes para la siguiente sesión (ver
  sección 29). **Catálogo completado el mismo día** (ver sección 30):
  37 permisos reales (10 recursos × crear/leer/actualizar/eliminar/
  exportar según evidencia real) y 83 asignaciones por rol en
  `rol_permisos`, replicando el comportamiento actual del sistema.
  Pantalla de administración y repunte de `AuthMiddleware` siguen
  pendientes.
- Exportación a Excel/PDF en pantallas de listado, cuatro grupos:
  Admin (`usuarios`/`bicicletas`/`estaciones`/`tarifas`/`bitacora`) y
  Gerente (`bicicletas`/`estaciones`/`tarifas`/`promociones`) ya
  estaban hechos en código sin documentar -- reconstruido
  retroactivamente hoy. Operación (`inventario`/`alquileres`/`pagos`)
  y Mantenimiento (`ordenes`/`bicicletas`) resueltos en esta sesión,
  respetando los filtros propios de cada pantalla; `rebalanceo` (Operación)
  y `dashboard`/`reportes` (Mantenimiento) omitidos a propósito -- no
  son listados, son formulario de una sola acción o paneles de
  gráficas sin fila por registro (confirmado con Washington). Probado
  en vivo contra ClickHouse/PocketBase reales, no solo código leído
  (ver sección 32).
- `urbanbike_tactica.resumen_viajes_diario` (nueva): los 3 informes
  compuestos calculaban en vivo sobre `fact_viajes`, contradiciendo el
  principio de precálculo ya aplicado a `kpi_resultados`. Resuelto para
  `gerente/reportes` (6 queries) y `gerente/informe` (4 queries), que
  ahora leen un resumen día×estación×membresía×tipo precalculado por
  `etl/08_calcular_tactica.py`; la segunda tarjeta de `operacion/reportes`
  se dejó fuera a propósito (sin filtros, refleja estado operativo real
  al segundo). Paridad de resultados verificada en 5 escenarios de
  filtro (idénticos antes/después); mejora de tiempo real medida con A/B
  intercalado: ~16-24% (modesta hoy por el tamaño real del dataset, el
  beneficio grande es a futuro, ver sección 33).
- `gerente/estrategico` (nueva pantalla + export Excel/PDF): primer
  informe compuesto del nivel estratégico, lee
  `resumen_mensual_ingresos`/`resumen_mensual_demanda` directo
  (precalculadas, sin agregar `fact_viajes` en vivo). Auditoría previa
  confirmó que ninguna pantalla las mostraba y que ya había 2 meses
  cerrados reales (junio y julio 2026), no solo uno como se asumía al
  empezar. `resumen_mensual_flota` queda fuera con nota visible de
  pendiente, no omitida en silencio. Bug real de alias de ClickHouse
  (`ILLEGAL_AGGREGATION`) encontrado y corregido al probar contra datos
  reales -- el error quedaba silenciado por el propio manejo de errores
  de la pantalla hasta que se verificó el HTML devuelto, no solo el
  código HTTP (ver sección 34).
- `airflow/Dockerfile` con `--constraint` oficial de Airflow
  (`constraints-2.10.4/constraints-3.11.txt`): cierra el riesgo de
  resolución de dependencias sin blindar detectado en la auditoría del
  08-ago-2026. Downgrade real de `duckdb` (1.5.5→1.1.3) auditado antes
  de aplicar -- sin riesgo, el DAG horario nunca importa `duckdb`. 4
  imágenes reconstruidas sin error, `pip check` limpio, DAG disparado
  manualmente con las 3 tareas en `success` y conteos en ClickHouse
  idénticos a antes del rebuild (ver sección 35).
- Ícono de ojo en contraseña, cédula+foto en usuarios de Admin, y
  bicicletas en mantenimiento ocultas del catálogo del ciclista: las 3
  ya estaban hechas en código sin documentar -- reconstruido
  retroactivamente y verificado con datos reales el 09-ago-2026 (ver
  sección 36), mismo patrón que el Grupo 1/2 de exportación (sección 32).
- Exportación Excel/PDF: **los 6 grupos de pantallas completos**
  (Admin, Gerente, Operación, Mantenimiento, Vigilancia, Ciclista).
  Grupo 5 (Vigilancia): 5 de 6 pantallas pedidas exportadas
  (`seguimiento`/`devoluciones`/`infracciones`/`mantenimiento/cerrar`/`alertas`),
  `reportes` omitida por no tener tabla real (solo gráfica). Grupo 6
  (Ciclista): `historial` e `infracciones` propias exportadas,
  comprobante individual sin tocar; filtro por `ciclista_id` de la
  sesión autenticada verificado con dos cuentas reales para confirmar
  que ningún export cruza datos entre ciclistas (ver sección 37).
- Roles y permisos, mecanismo real: `app/db/permisos_repo.py`
  (`tiene_permiso`) + `app/middleware/permisos.py`
  (`requiere_permiso()`, dependencia real de FastAPI) probados
  aislados antes de tocar ninguna ruta. Los **6 recursos con WorkPanel**
  (`bicicletas`, `alquileres`, `ordenes_mantenimiento`, `tarifas`,
  `promociones`, `estaciones`) migrados por completo -- 55 rutas reales
  en `admin.py`/`gerente.py`/`empleado.py` -- probados con las 6 cuentas
  reales de rol, comportamiento idéntico al de antes de la migración en
  los 6. `AuthMiddleware` no se tocó -- la dependencia nueva se suma
  encima, no lo reemplaza. Hallazgo real reportado, no corregido en
  silencio: `bicicletas:leer` (Mantenimiento) y
  `bicicletas:leer/actualizar` (Vigilancia) están en el catálogo pero
  sin ninguna pantalla real que los alcance hoy -- Washington decidió
  ampliar qué prefijos alcanza cada rol (Opción A); evaluación de
  viabilidad completa, sin implementar, en la sección 39 (ver secciones
  38-39).
- Cerrado el hallazgo de `bicicletas:leer` sin ruta real: excepción
  puntual en `AuthMiddleware` (no el cambio de algoritmo general,
  decisión explícita de Washington por el riesgo de tocar el mecanismo
  de acceso de toda la app cerca de la entrega) que deja entrar a
  Mantenimiento y Vigilancia solo a `/empleado/operacion/inventario`,
  con botones Insertar/Actualizar/Eliminar mostrados u ocultos según el
  permiso real de cada rol. Probado que las mismas 60 combinaciones de
  rol×pantalla de las secciones 38/39 no cambiaron, y que el backend
  bloquea de verdad (no solo la UI) lo que cada rol no tiene permiso de
  hacer. Cambio de algoritmo general de `AuthMiddleware` queda anotado
  como mejora futura, con el análisis matemático ya hecho (ver sección
  40).
- `admin/permisos.html` (nueva): matriz real 38 permisos × 6 roles,
  228 casillas, cada una otorga/revoca de verdad en `rol_permisos`
  (`INSERT`/`DELETE`, decisión explícita distinta del criterio
  original de "log de eventos" de la sección 29). Protegida con el
  permiso nuevo `permisos:actualizar`, solo para `admin`. Prueba real
  de bloqueo de punta a punta con `ordenes_mantenimiento:actualizar`
  para Vigilancia (sustituto acordado de `:crear`, que resultó no
  tener ninguna ruta real conectada -- hallazgo reportado antes de
  simular una prueba falsa): revocado desde la pantalla → Vigilancia
  bloqueada con `PermisoDenegadoError` real en
  `POST /vigilancia/mantenimiento/{oid}/certificar`; re-otorgado →
  vuelve a funcionar. Estado final idéntico al inicial, sin residuo
  (ver sección 41).
- Excepciones de permiso por usuario individual:
  `urbanbike_operativa.usuario_permisos` (nueva, `id_usuario` =
  PocketBase `users.id`, no `urbanbike_operativa.usuarios.id` -- admin
  y gerente no tienen fila ahí). `tiene_permiso()` con tercer parámetro
  opcional `id_usuario`, retrocompatible, actualizado en los 4 sitios
  reales que la llamaban. `admin/permisos-usuario` (buscador + ficha):
  cambio de rol reutiliza `usuarios_editar()` existente (Opción B, `next`
  configurable), un botón por permiso calculado en el backend, no dos
  checkboxes. Regresión completa de las secciones 38-41 repetida antes
  de tocar el caso nuevo -- 0 diferencias. Caso nuevo probado con datos
  reales (`empleado.mant@urbanbike.com` con excepción real de
  `bicicletas:crear`, creó `UB-011` de verdad; `empleado.vig@urbanbike.com`
  sin excepción, bloqueado) -- sustituyendo el ejemplo original
  (ciclista) que resultó no tener ninguna ruta alcanzable, mismo tipo
  de hallazgo ya visto en la sección 41. Estado final idéntico al
  inicial en las 3 tablas de permisos (ver sección 42).
- Mejoras de presentación a `admin/permisos-usuario` (sin tocar
  `tiene_permiso()` ni la lógica de otorgar/revocar): buscador muestra
  los 10 usuarios reales por defecto y filtra en el navegador
  (`filtrarTabla()`, sin recargar); ficha de detalle con 4 indicadores
  de solo lectura (Lectura/Escritura/Actualizar/Eliminar) calculados
  sin consulta nueva sobre los mismos datos ya cargados. Probado con
  `admin` (4/4 Sí), `ciclista` (4/4 No) y `empleado-vigilancia` (caso
  mixto: Sí/Sí/Sí/No, predicho contra sus permisos reales antes de
  mirar la pantalla) (ver sección 43).
- Los 4 indicadores de `admin/permisos-usuario` pasaron de solo
  lectura a botones de acción masiva real (otorgar/revocar en todos
  los recursos de una acción de una sola vez), vía
  `permisos_repo.resumen_por_accion()`/`set_excepcion_masiva()` nuevas
  y `POST .../toggle-masivo`. Bloque "Rol actual" separado del bloque
  "Cambiar rol"; 3 textos de ayuda retirados (uno de ellos porque
  quedó factualmente falso tras el cambio); desglose de 38 filas
  rediseñado (sin el emoji `⚡`, que incumplía la regla de cero
  emojis; "Heredado"/"No heredado" atenuados frente a las excepciones
  reales). Probado con `empleado.vig@urbanbike.com`: otorgado real de
  `eliminar` en sus 7 recursos aplicables, bicicleta real eliminada con
  el permiso nuevo, revocado real, segundo intento de eliminar
  bloqueado de nuevo -- reversión funcional exacta confirmada (el
  desglose queda con "Excepción: Revocado" en vez de "No heredado" tras
  revocar, por diseño explícito: revocar inserta fila auditable, no
  borra el rastro); artefactos de la prueba limpiados (ver sección 44).

## 45. Hallazgo real — el auto-bloqueo por 3 infracciones es estructuralmente inalcanzable (11 de agosto de 2026)

**No es un bug de código, es un conflicto entre dos reglas reales que
nunca se pensaron juntas.** Se encontró al construir la pantalla real
de cuenta bloqueada (`/auth/bloqueado`, ver login/`AuthMiddleware`),
intentando forzar el caso de prueba "ciclista bloqueado por 3
infracciones sin resolver" por el camino orgánico, como pedía la
tarea.

**La regla que ya existía (sin relación con esta sesión)**:
`ciclista.py::reservar()` rechaza cualquier reserva nueva si
`_infracciones_activas(user_id) > 0` -- es decir, con **una sola**
infracción pendiente, sin importar cuántas, el ciclista ya no puede
iniciar un viaje nuevo. Mensaje real: *"Tienes infracciones pendientes
de resolución. No puedes reservar hasta que sean resueltas."*

**La regla del auto-bloqueo** (`empleado.py`,
`_LIMITE_INFRACCIONES_BLOQUEO = 3`, dentro del flujo de inspección de
devolución reprobada): cuando las infracciones pendientes de un
ciclista llegan a 3, se le pone `activo = False` automáticamente.

**Por qué nunca se cruzan**: una infracción nueva solo se genera al
reprobar la inspección de devolución de un viaje, y un viaje nuevo
requiere pasar primero por `reservar()`. En cuanto un ciclista tiene 1
infracción pendiente, `reservar()` ya lo bloquea -- no puede generar un
viaje que produzca la segunda infracción, mucho menos la tercera. Para
llegar a 3 pendientes simultáneas haría falta que las 3 existieran
*antes* de que la primera bloqueara los viajes siguientes, lo cual es
imposible por construcción: siempre se generan de una en una, cada una
desde un viaje que ya requería cero infracciones pendientes para
poder reservarse.

**Verificación real, no solo lectura de código**: con el ciclista real
de prueba (Adrián Guizado) en 0 infracciones pendientes, un intento
real de `POST /ciclista/reservar` fue rechazado con exactamente el
mensaje de arriba en cuanto tuvo 1 infracción pendiente (la real,
preexistente de una sesión anterior). Confirma que la condición
`>= 3` del auto-bloqueo, aunque el código que la implementa es
correcto, no se alcanza nunca en producción tal como está el sistema
hoy.

**Cómo se probó igual el caso de bloqueo de ciclista para la pantalla
nueva** (ver la implementación real de `/auth/bloqueado`): se sembraron
2 infracciones adicionales directo en PocketBase (mismo formato exacto
que genera el código real) para llegar a 3 pendientes, y se aplicó
`activo=False` con el mismo texto de motivo que el código real
generaría con `total_pendientes=3`. Es decir: la *pantalla de bloqueo*
sí quedó probada de punta a punta con datos reales; lo que no se pudo
probar por el camino 100% orgánico fue específicamente la acumulación
de 3 infracciones, porque el sistema mismo lo impide.

**Pendiente de decisión de negocio, sin corregir todavía** (ver punto
19, sección 6) -- dos caminos posibles, ninguno implementado:
- Bajar el umbral del auto-bloqueo (por ejemplo a 1), ya que hoy es el
  número real de infracciones pendientes que un ciclista puede llegar
  a tener.
- Relajar `reservar()` para que permita reservar con alguna infracción
  pendiente (hasta cierto número), dejando que el umbral de 3 sí sea
  alcanzable.

Ninguna de las dos se aplicó en esta sesión -- se deja explícitamente
para que Washington decida cuál es el comportamiento de negocio
correcto antes de tocar cualquiera de las dos reglas.

## 46. Responsividad móvil real -- diagnóstico y 3 frentes corregidos (11 de agosto de 2026)

**Motivo**: el sistema no tenía ningún media query salvo el colapso del
sidebar (`base.html`, `≤768px`). Probado con Playwright en emulación
móvil (carga limpia por ancho, no resize, para no arrastrar tamaños de
`<canvas>` de una carga anterior) contra 16 pantallas reales con las 6
cuentas de rol.

**Causa dominante -- gráficas de Chart.js en grids de proporción fija**
(`3fr 2fr`, `2fr 1fr 1fr`, etc., sin `min-width:0`): el `<canvas>` no
se encogía con su columna, así que el grid entero empujaba la página a
scroll horizontal. `/gerente/dashboard` medía 728px de ancho real
contra 375px de viewport (353px de desborde); `/gerente/reportes`,
365px. **Corregido** con una clase real `.charts-section` en
`main.css` (`min-width:0` en los hijos + colapso a 1 columna en
`≤768px`, mismo breakpoint del sidebar), aplicada a las 7 filas reales
de gráficas de proporción fija en 6 archivos (`dashboard.html`,
`gerente/dashboard.html`, `empleado/vigilancia/dashboard.html`,
`gerente/reportes_pagos.html`, `gerente/reportes.html`,
`gerente/analisis_citibike.html`). `Chart.js` ya tenía
`responsive:true`/`maintainAspectRatio:false`, así que se redibuja
solo al colapsar, sin tocar JS. Verificado con carga limpia en las 14
pantallas reales que usan `<canvas>`: **0px de desborde a 375px en las
14**. A 320px (más estricto de lo pedido) quedan residuos menores en 4
pantallas, todos con causa **fuera de este patrón** (ver hallazgo
menor más abajo).

**Segundo patrón -- formularios de dos columnas** (`grid-template-columns:
1fr 1fr` / `2fr 1fr` / `repeat(3,1fr)`, fijo, sin colapsar): no
generaba scroll de página, pero apretaba los campos hasta truncarlos
("Dispo▾", input de 50px en `/gerente/bicicletas/nueva`). **Corregido**
con una segunda clase real, `.form-grid` (mismo mecanismo y breakpoint
que `.charts-section`), aplicada a las 27 filas de campos reales en 12
formularios (`gerente/bicicletas_form.html`,
`empleado/mantenimiento/ordenes_form.html`,
`gerente/estaciones_form.html`,
`empleado/operacion/inventario_form.html`,
`gerente/promociones_form.html`,
`empleado/operacion/alquiler_form.html`, `ciclista/pago.html`,
`empleado/operacion/cobrar_presencial.html`, `admin/estaciones.html`,
`admin/bicicletas.html`, `admin/tarifas.html`, `gerente/tarifas.html`).
Verificado en `/gerente/bicicletas/nueva`: 0px de desborde a 375px y a
320px, campos legibles en una sola columna.

**Tercer patrón -- `.card-header` sin `flex-wrap`** (título + controles
a la derecha que no envuelven): encontrado primero en
`/gerente/bicicletas` (botón "Nueva bicicleta" cortado a 375px), pero
al verificar `analisis_citibike.html` tras el frente 1 se confirmó que
el mismo patrón rompía ahí también -- **auditado antes de corregir**:
`.card-header` aparece en **59 plantillas**, confirmando que es
realmente una clase compartida y no un caso puntual.  **Corregido en
un solo lugar** (`main.css`, `.card-header { flex-wrap:wrap; gap:8px;
}`), sin tocar ninguna plantilla. Verificado después: `/gerente/
bicicletas` y `analisis_citibike.html` pasan de desbordar a 0px a
375px.

**Hallazgo menor, sin corregir todavía** -- a 320px (el teléfono más
angosto probado, más estricto de lo pedido) quedan residuos pequeños
en 5 pantallas, todos con causa distinta a los tres patrones de
arriba:
- `dashboard.html` (admin, 6px) y el mismo patrón en el dashboard de
  gerente: un grid `1fr 1fr` *sin* `<canvas>` ("Estaciones del
  Sistema" / "Dataset Citibike", barras de progreso) que no se incluyó
  en `.charts-section` a propósito porque el frente 1 se limitó a
  grids con gráfica real.
- `gerente/informe.html`, `gerente/estrategico.html`,
  `admin/reportes.html` (28-47px): usan
  `repeat(auto-fit,minmax(320px,1fr))`, un patrón que ya era
  responsive antes de hoy -- su columna mínima (320px) coincide
  justo con el ancho de viewport más angosto probado.
- `/gerente/bicicletas` (11px): no relacionado con `.card-header`
  (que ya quedó en 0px a 375px); probablemente la barra de
  filtros con 4 `<select>` en fila.

Washington decidió explícitamente dejarlo anotado en vez de corregirlo
ahora -- 375px (el ancho de teléfono estándar) ya está en 0px de
desborde en las 16 pantallas probadas.

## 47. 4 frentes adicionales de responsividad + corrección de la causa real en `/gerente/bicicletas` (11 de agosto de 2026)

Sesión de seguimiento a la 46, misma fecha. Extensión de Chrome
disponible esta vez (tras reintentar la conexión), así que la
verificación de este frente sí fue en pantalla real -- no solo lectura
de código. Como `resize_window` no redimensiona la ventana real en
este entorno (queda fija en ~1910px de ancho pase lo que pase), la
medición se hizo con un `<iframe>` del mismo origen incrustado en la
pestaña, con el ancho exacto del viewport a probar -- el motor de
layout de Blink evalúa el CSS real (media queries, flexbox) contra ese
ancho, así que es una medición genuina, no una simulación aproximada.
Confirmado con capturas visuales a 320/375/414px además de las
mediciones por `scrollWidth`/`getBoundingClientRect`.

**Frente A -- `100vh` → `100dvh` con fallback**: aplicado en
`main.css` a `body`, `.layout`, `.login-page` y `.a11y-panel` (mismo
criterio que `.sidebar`/`.main-wrapper` ya tenían: se deja `100vh`
primero como fallback y `100dvh` después, que gana por cascada en
navegadores que lo soportan).

**Frente B -- grids fijos de dashboard**: nueva clase `.dashboard-grid`
en `main.css` (mismo mecanismo que `.charts-section`/`.form-grid`).
Aplicada en los 6 dashboards de rol con un grid `1fr 1fr`/`2fr 1fr`
sin `<canvas>` que `.charts-section` había dejado fuera a propósito en
la sección 46: `dashboard.html` (admin) y `gerente/dashboard.html`
(los 2 que la sección 46 ya había detectado como residuo pero nunca
llegó a corregir en código) + `ciclista/dashboard.html`,
`empleado/operacion/dashboard.html`,
`empleado/mantenimiento/dashboard.html`,
`empleado/vigilancia/dashboard.html` (4 sin documentar hasta hoy).

**Frente C -- causa real del buscador de WorkPanel, corregida**: la
sección 46 atribuyó el residuo de 11px en `/gerente/bicicletas` a 320px
"probablemente" a la barra de filtros. Medido con precisión hoy: **esa
atribución era incorrecta** (ver hallazgo nuevo más abajo -- la causa
real es otra). El buscador (`<input flex:1 min-width:220px>`) sí tenía
un bug real, pero de *usabilidad*, no de desborde de página: al
quitarle el mínimo (`min-width:0`, fix de la sesión anterior el mismo
día) el campo queda con `flex-basis:0%` (heredado del shorthand
`flex:1`), lo que le da tamaño hipotético 0 para el algoritmo de
ajuste de línea de flexbox -- por diseño del algoritmo, un ítem con
tamaño hipotético 0 **siempre cabe** en la línea actual junto a lo que
venga después, así que el buscador terminaba compartiendo fila con un
`<select>` de forma no predecible según el ancho exacto, y solo
recibía el espacio sobrante de esa línea. Medido en 9 anchos reales
(320-767px) antes de corregir: el campo quedaba en **37-91px** (menos
de una palabra visible) en 360, 375, 414, 560, 640 y 767px, mientras
que en 320, 480 y 700px sí ocupaba una línea propia (172-181px) --
patrón no monótono, confirma que depende de qué combinación de
elementos entra en cada línea a cada ancho, no de un único breakpoint
intermedio como se sospechaba.

**Corrección aplicada**: en vez de `min-width:0`, `.filtro-buscador`
pasa a `flex:1 1 100%` en el mismo breakpoint (≤768px) -- con
`flex-basis:100%` el buscador reclama la línea completa para sí mismo,
así que ningún `<select>` puede compartirla y el campo ocupa siempre
el 100% del ancho disponible en su propia fila. Verificado de nuevo en
los mismos 9 anchos: el ancho del campo ahora escala de forma monótona
con el viewport (172px a 320px → 619px a 767px), sin ningún mínimo
inusable, y sin desborde de página en ninguno de los 8 anchos ≥360px.
Confirmado también visualmente a 320/375/414px: el campo se ve completo
y usable en las tres capturas. Aplicado en las 7 pantallas que ya
tenían `.filtro-buscador` desde la sesión anterior (no hizo falta
tocar las plantillas, solo la regla en `main.css`).

**Frente D -- `perfil.html`**: tabla envuelta en `.table-wrap`, sin
cambios adicionales.

**Hallazgo nuevo -- la causa real del residuo de 11-15px en
`/gerente/bicicletas` a 320px NO es la barra de filtros** (corrige la
sección 46): con el buscador ya corregido, el desborde sigue presente
a 320px (medido: 15px). Aislado con un barrido de todos los elementos
de la página excluyendo los que están dentro de un contenedor con su
propio scroll contenido (como `.table-wrap`): el elemento responsable
es el contenedor `.flex.gap-2` de los botones **Excel / PDF / Nueva
bicicleta** dentro del `.card-header` de la tarjeta "Flota completa" --
confirmado visualmente, el botón "Nueva bicicleta" queda parcialmente
cortado por el borde derecho a 320px pese a que `.card-header` ya tiene
`flex-wrap:wrap` desde la sección 46. La barra de filtros, en cambio,
ya no tiene ningún residuo (cada `<select>` cabe en su propia línea a
320px, confirmado). **Sin corregir todavía** -- no era parte del
alcance pedido en esta sesión, se deja anotado para no perderlo.

**Hallazgo nuevo -- panel de accesibilidad, reportado por Washington
sin corregir a propósito**: overflow observado en `/gerente/bicicletas`
a 320px con el panel de usabilidad cerrado. Verificado parcialmente
hoy: `.a11y-panel` es `position:fixed` con `transform:translateX(100%)`
cuando está cerrado (se desplaza fuera de pantalla por su propio ancho,
320px o `92vw`), y ningún ancestro tiene `transform` propio que
rompiera ese posicionamiento fijo relativo al viewport real. Con la
medición por `scrollWidth` en el iframe de prueba, un elemento
`position:fixed` desplazado así **no** aparece como causante del
desborde de la página (comportamiento esperado en Chrome de escritorio:
los elementos fijos no participan en el cálculo de scroll del
documento). No se pudo reproducir el número exacto de 23px que
Washington midió -- puede deberse a diferencias entre el método de
medición (aquí: iframe embebido en Chrome de escritorio; posiblemente
la medición original fue en un emulador de dispositivo real o táctil,
donde el comportamiento de scroll con elementos fijos puede diferir).
**Sin corregir, tal como se pidió** -- queda anotado para revisar con
el método de medición original antes de decidir si hace falta tocarlo.

## 48. Membresía simulada: wizard de 3 pasos + tarjeta de pruebas con Luhn (11 de agosto de 2026)

**Motivo**: la activación de membresía era un solo botón "Activar
(simulado)" -- se pidió una experiencia mas real (flujo de pago con
pasos) sin cruzar a simular un cobro real ni parecer una pasarela
verdadera.

**Wizard client-side de 3 pasos** en `ciclista/membresia_pagar.html`
(nueva pantalla, `/ciclista/membresia/pagar`): 1) datos de tarjeta
simulada (número, titular, mes/año de expiración, placeholder
`4242 4242 4242 4242` -- tarjeta de pruebas estándar de Stripe, pública
y conocida para este propósito exacto) 2) confirmación de monto y
período (30 días) con la tarjeta enmascarada 3) redirección a una
pantalla de éxito real (`ciclista/membresia_comprobante.html`) tras el
POST real. El aviso "MODO DEMOSTRACIÓN -- Ningún cargo real se procesa"
es permanente: vive fuera de los contenedores de paso, visible en los
3 pasos sin excepción, y se repite en la pantalla de comprobante y en
el propio PDF.

**Validación de Luhn real** (no cosmética): implementada dos veces
-- en JS (`membresia_pagar.html`, feedback inmediato antes de avanzar
al paso 2) y en Python (`_luhn_valido()` en `ciclista.py`, autoridad
real antes de escribir nada, por si se saltea el JS). Un número que no
pasa el algoritmo nunca llega a activar nada. Probado en vivo: un
número inventado (`1234567890123456`) fue rechazado con el mensaje
esperado; `4242 4242 4242 4242` fue aceptado.

**El mecanismo real no cambió**: `membresias_repo.activar()` sigue
haciendo exactamente el mismo INSERT en `pagos` (concepto='membresia')
+ INSERT en `membresias` + `metodos_pago` simulado de siempre. Único
cambio real: `_asegurar_metodo_pago()` ahora guarda los últimos 4
dígitos, la marca (detectada por prefijo público de red) y el
vencimiento que el ciclista tipeó en el paso 1, en vez del `'0000'`
genérico fijo -- mismo patrón que ya usa el flujo de pago de alquiler
(`ciclista/pago.html`), nunca se guarda el número completo.

**Comprobante reutilizando la infraestructura de PDF de alquileres**:
`/ciclista/membresia/comprobante/{id}/pdf` llama a la misma
`generar_pdf_reporte()` que ya usa `comprobante_alquiler_pdf()`
(membrete + fuentes ya registradas), con una fila final "Nota: MODO
DEMOSTRACIÓN -- pago simulado" en la tabla del PDF para que el
documento en sí tampoco se pueda confundir con un comprobante real.
Verificado con `fetch()` en vivo: `200 OK`, `content-type:
application/pdf`, 24.5 KB reales.

**Bug real encontrado durante la prueba, no relacionado con el código
de hoy**: al probar con `ciclista@urbanbike.com` (vencida), el wizard
activó todo correctamente (verificado insertando y leyendo la fila
`b554635f...` con fechas 11/08→10/09/2026 por `id` directo), pero
`/ciclista/membresia` seguía mostrando "Vencida" con una fecha vieja
(2026-07-26) y el catálogo seguía cobrando precio casual. Causa real:
una fila de prueba corrupta ya existente en `membresias`
(`32aef9dc-...`, `fecha_inicio=2026-08-15` futura pero
`fecha_fin=2026-07-26` pasada, `estado='activa'`, origen='compra',
imposible de producir por `_registrar_periodo()` -- inserción manual
de una sesión de prueba anterior) le ganaba a la fila real en
`estado_actual()` (`ORDER BY fecha_inicio DESC`), tapándola. Confirmado
con Washington antes de tocar nada: se borró esa única fila
(`ALTER ... DELETE`, `mutations_sync=1`). Después de borrarla,
verificado de punta a punta: `/ciclista/membresia` muestra "Activa,
Vence el 2026-09-10", y el catálogo bajó de precio casual (Giant
Explore E+ USD 35.20) a precio member (USD 22.40) en las 4 bicicletas
del catálogo real. No se tocó `estado_actual()` ni ninguna otra fila
-- el bug era un dato de prueba puntual, no la lógica de la consulta.

**Nota operativa**: el auto-reload de `uvicorn --reload` dejó de
detectar cambios de archivo a mitad de la sesión (un solo evento de
reload registrado pese a múltiples ediciones posteriores a
`ciclista.py`/`membresias_repo.py`/plantillas nuevas) -- causó un 404
real en `/ciclista/membresia/pagar` hasta reiniciar el proceso a mano.
Sin diagnosticar la causa raíz (posible peculiaridad de WatchFiles en
Windows); si vuelve a pasar, reiniciar el servidor en vez de confiar
en que el reload recogió todo.

## 49. Catálogo del ciclista corregido + barrido sistemático de las 69 URLs reales del sistema (11 de agosto de 2026)

Motivo: una captura real de `/ciclista/alquilar` en emulador mostró
desborde total (título, filtros y tarjetas cortados). La sección 46/47
habían verificado por muestreo puntual, no un barrido real -- se pidió
uno completo.

**Catálogo del ciclista -- causa real confirmada y corregida**: dos
focos reales, medidos con la técnica del iframe del mismo origen
(scrollWidth contra el viewport real, con CSS forzado a fresco porque
el navegador estaba sirviendo `main.css` desde caché heurística --
hallazgo metodológico propio, ver más abajo). A 320px: 227px de
desborde; a 375px: 172px. Causa dominante: el `.flex.gap-2` del header
del catálogo (selector de modalidad + 2 `<select>`) sin `flex-wrap`.
Causa secundaria: `.catalogo-grid` con `minmax(260px,1fr)`, más ancho
que el contenido real disponible (~214px) a 320-375px. Corregido con
una clase nueva reutilizable, `.header-controles` (`flex-wrap:wrap` a
≤768px) más `.catalogo-grid { grid-template-columns: 1fr }` al mismo
breakpoint. Verificado con `scrollWidth` (de 227px/172px a -6px, el
mismo offset base ya establecido) y con capturas reales a
320/375/414px: catálogo, filtros y tarjetas completos y legibles en
los tres anchos.

**Hallazgo metodológico -- caché de CSS en las mediciones por
iframe**: la primera re-medición tras el fix dio exactamente el mismo
desborde que antes de corregir nada. Causa: el `<link>` a `main.css`
dentro del iframe se resolvía contra la caché heurística del
navegador (mismo URL sin query string, pedido decenas de veces en la
sesión), no contra el archivo recién editado. Toda medición desde
entonces reemplaza ese `<link>` por uno con `?_=timestamp` antes de
medir. **Cualquier medición por iframe de sesiones anteriores a este
punto en el día de hoy debe repetirse con este fix antes de confiar en
el número.**

**Barrido sistemático (no muestreo) de todas las plantillas reales**:
72 archivos `.html` en `app/templates/`. De esos: `base.html`
(esqueleto), 5 `componentes/*.html` (parciales `{% include %}`, no
navegables solos) y `roles/dashboard.html` -- **confirmado por grep
que ningún router lo referencia, código muerto, candidato a eliminar
en una limpieza futura, sin tocar hoy**. Quedan 65 plantillas
navegables; 6 se reutilizan en más de una ruta (formularios
compartidos crear/editar), así que el barrido cubrió **69 URLs
reales**, con datos reales (IDs de ClickHouse/PocketBase existentes)
para cada ruta con parámetro dinámico, autenticado con las 6 cuentas
de rol reales. Medido en lote con un script en el navegador (no una
por una).

**Sin poder probar hoy, pendiente de verificación cuando exista el
dato real que las alcance**:
- `/auth/bloqueado`: exige una sesión de cuenta bloqueada real
  (`request.session["bloqueo"]`), no alcanzable navegando directo --
  necesita simular un login real contra una cuenta bloqueada.
- `/empleado/operacion/pagos/cobrar/{pago_id}`: no existe ningún pago
  en estado `pendiente_efectivo` hoy en los datos reales.

**Resultado del primer barrido (antes de corregir)**: 55 pantallas
limpias, 14 con desborde real a 320px, reducibles a 3 causas raíz:

- **Causa A** (10 pantallas) -- mismo patrón que el catálogo: un
  `.flex.gap-2` dentro de `.card-header` (exportar Excel/PDF + "Nueva
  X", o filtros inline) sin `flex-wrap`. `/admin/usuarios` (177px),
  `/admin/bicicletas` (184px), `/admin/estaciones` (184px),
  `/admin/tarifas` (169px), `/admin/bitacora` (65px),
  `/gerente/empleados` (144px), `/gerente/bicicletas` (15px -- el
  residuo que la sección 47 ya había diagnosticado pero nunca
  corregido), `/gerente/estaciones` (15px), `/gerente/tarifas`
  (169px), `/gerente/promociones` (30px).
- **Causa B** (3 pantallas) -- `repeat(auto-fit,minmax(320px,1fr))`,
  ya documentado como residuo conocido en la sección 46:
  `/gerente/estrategico` (51px), `/admin/reportes` (32px),
  `/gerente/informe` (32px).
- **Causa C** (1 pantalla, hallazgo nuevo) -- `/ciclista/bicicleta/{id}`
  (60px): `.detalle-bici-grid` sí colapsaba a `grid-template-columns:
  1fr` a ≤768px, pero sin la regla compañera `> * { min-width: 0 }`
  que sí tienen `.charts-section`/`.form-grid`/`.dashboard-grid` --
  sus 2 hijos (`min-width: auto`) forzaban la única columna a 348px
  (el ancho intrínseco del contenido) en vez de encogerse a los 254px
  reales disponibles.

**Correcciones aplicadas**:
- Causa A: la clase `.header-controles` (la misma del fix del
  catálogo, ya genérica) aplicada a los 10 divs reales
  (`class="flex gap-2 header-controles"`), sin tocar CSS nuevo --
  reutiliza la regla que ya existía.
- Causa B: en vez de crear una clase nueva, se reutilizó
  `.dashboard-grid` (misma sección 47, ya colapsa a `1fr` a ≤768px con
  `min-width:0` en los hijos) en los 3 divs -- comportamiento idéntico
  al que se hubiera escrito de cero.
- Causa C: agregada `.detalle-bici-grid > * { min-width: 0; }` en el
  `<style>` propio de la plantilla, mismo patrón que las otras 3
  clases.

**Verificación: barrido completo repetido, las 69 URLs, no solo las
14 corregidas** (para confirmar que nada se rompió): **67 limpias, 2
con desborde real remanente** -- ninguna de las 65 pantallas restantes
se rompió con estos cambios. Los 2 casos que quedan **no son las
causas A/B/C sin terminar de corregir** -- son causas nuevas,
distintas, que compartían página con una de las 3 ya arregladas:

- `/ciclista/bicicleta/{id}` -- bajó de 60px a **39px**. Confirmado
  que `.detalle-bici-grid` ya colapsa correctamente a 254px (causa C
  resuelta de verdad); el remanente es el grid `1fr 1fr 1fr` de
  tarifas (hora/día/semana) dentro de la columna derecha, ya señalado
  como fuera de alcance en el diagnóstico original de esta sesión (no
  pedido, no corregido).
- `/gerente/estrategico` -- se mantiene en **51px**. Confirmado que el
  grid de `minmax(320px,1fr)` ya colapsa correctamente a 254px (causa
  B resuelta de verdad); el remanente es una tarjeta aparte, el aviso
  "Estado de la flota por mes — pendiente" (`resumen_mensual_flota
  todavía no tiene datos...`), con `<code>resumen_mensual_flota</code>`
  -- una palabra sin espacios que el navegador no rompe por defecto,
  forzando el ancho de esa línea. **Hallazgo nuevo, sin corregir.**

Ninguno de los 2 remanentes es un desborde de página completo como los
originales (39px y 51px vs. hasta 227px) -- ambos son elementos
puntuales dentro de tarjetas específicas, no un layout roto.

## 50. Cierre de los 2 hallazgos remanentes -- 0 desbordes reales en las 69 URLs (11 de agosto de 2026)

**`/ciclista/bicicleta/{id}` -- grid de tarifas (hora/día/semana)**:
probado en vivo con la misma técnica (manipulando `gridTemplateColumns`
dentro del iframe antes de medir, sin tocar el archivo todavía) cuál
arreglo cabe a 320px: 3 columnas desborda 39px, **2 columnas y 1
columna dan ambas -6px** (limpio). Se eligió **2 columnas** por quedar
más cerca del diseño original (comparación lado a lado) y porque 1
columna no aporta nada mejor a cambio. Nuevo problema encontrado al
elegir 2: con 3 tarifas en un grid de 2 columnas, la tercera
("Por semana") queda sola en su propia fila pero conservaba el
`border-left` pensado como divisor entre columnas -- se veía como una
línea suelta sin nada que separar. Corregido en el mismo cambio:
`.tarjeta-tarifas-grid` (nueva clase, antes era un grid inline sin
nombre) colapsa a `1fr 1fr` a ≤768px y **anula el `border-left` en
todos sus hijos** en ese mismo breakpoint (`border-left:none
!important`), ya que el divisor solo tiene sentido con las 3 tarifas
en una sola fila. Verificado: -6px a 320px, confirmado también visual
(las dos primeras tarifas lado a lado, "Por semana" sola abajo sin
ninguna línea suelta).

**`/gerente/estrategico` -- palabra sin romper en la tarjeta de
aviso**: el primer intento (`overflow-wrap:break-word` en los dos
`<code>` del texto, `resumen_mensual_flota` y
`urbanbike_operativa.bicicleta_eventos`) **no alcanzó** -- verificado
con la misma técnica, seguía en 51px exactos, sin cambio. Diagnóstico
en vivo (manipulando el DOM dentro del iframe antes de medir): el
`<code>` en sí ya media solo 155-273px con `overflow-wrap` aplicado,
pero el `<div>` que envuelve el párrafo (dentro de un
`display:flex;gap:12px`) seguía midiendo 286px porque, sin
`min-width:0`, un ítem flex calcula su tamaño mínimo automático
considerando la palabra completa sin partir -- `overflow-wrap` por sí
solo no fuerza la ruptura si nada más angosto la obliga. Confirmado en
vivo: agregar `min-width:0` a ese div bajó el ancho de 286px a 180px
al instante, y el overflow de la página a -6px. Aplicado en el archivo
real (`style="min-width:0;"` en el div de texto) manteniendo el
`overflow-wrap:break-word` ya puesto en los dos `<code>` (ambos hacen
falta juntos, ninguno solo alcanza). Verificado visual: las dos
palabras largas rompen limpio dentro de la tarjeta, contenidas en
320px.

**Barrido completo final -- las 69 URLs, una vez más**: **69/69
limpias, 0 desbordes reales, 0 errores.** Confirmado con la misma
técnica de siempre (CSS fresco sin caché) en las 6 cuentas de rol.
Cierra por completo el trabajo de responsividad móvil de esta sesión
(secciones 46-50) -- el sistema entero, con datos reales en cada ruta
con parámetro dinámico, queda sin ningún desborde horizontal conocido
a 320px.

## 51. Facturación real (IVA 15%) para membresías + backfill de las 19 facturas históricas (11-12 de agosto de 2026)

**Auditoría, antes de tocar nada**: `facturas`/`factura_detalle` ya
tenían todas las columnas necesarias (`subtotal`/`descuento`/`impuesto`/
`total` en el encabezado; `cantidad`/`precio_unitario`/`subtotal` por
línea, sin impuesto por línea -- correcto, el IVA se calcula una sola
vez sobre el total de la factura, no por renglón). Cero filas reales
hasta hoy. Más importante: **ningún código vivo transiciona un alquiler
a `'facturado'`** -- se auditó todo `app/` y `etl/`, y el único lugar
que lo hace es `etl/07_migrar_viajes_pagos.py`, corrido una sola vez el
30-jul-2026 sobre datos históricos de PocketBase, sin ningún desglose
de impuesto (`subtotal=total=monto_total`, `descuento=recargo=0`). El
WorkPanel de empleados dejó esto documentado desde la sección 10
("Completar' no factura"), y el flujo real de cobro del ciclista vive
100% en PocketBase, desconectado de `alquileres`/`facturas` de
ClickHouse (pendiente #14). Confirmado con Washington antes de
proponer nada: el alcance de hoy es membresía (100% ClickHouse, cobro
en vivo real) + backfill de las 19 filas históricas -- el puente de
cobro presencial del ciclista queda fuera, documentado aparte (ver
pendiente #14).

**Decisión de IVA, confirmada con Washington**: el monto que el sistema
ya cobra en cualquier punto (`pagos.monto`, `membresias.precio`,
`alquileres.total`) se trata como precio final al consumidor, **IVA ya
incluido** -- nunca se le suma nada encima. `subtotal = total / 1.15`,
`iva = total - subtotal`, calculados hacia atrás. Se encontró y se
mostró honestamente una señal en contra (la única fila de ejemplo que
existió en `db/02_operativa_seed.sql`, borrada como huérfana en la
sección 19, calculaba el IVA sumándolo encima del neto, con la tasa
vieja del 12%) -- se descartó por ser dato de fantasía de la primera
sesión del proyecto, sin ningún flujo de precios real detrás, contra
todo el sistema real y probado en decenas de sesiones que sí trata el
precio mostrado como el precio final.

**`app/db/facturas_repo.py`** (nuevo): `desglosar_iva()`,
`siguiente_numero()` (correlativo real, mismo patrón `MAX+1` que
`alquileres_repo._siguiente_codigo()`, serie fija `001-001`),
`emitir()` (factura + 1 línea de detalle), `obtener()`/
`obtener_por_alquiler()`/`detalle()` para lectura con dueño verificado.

**Integración con membresía**: `membresias_repo._registrar_periodo()`
(compartida por `activar()` y la renovación automática de Airflow --
un solo camino real de cobro) genera la factura real antes de insertar
el pago, y el pago ahora sí guarda `id_factura` real (antes quedaba en
el UUID sentinela). `membresias_repo.obtener()` hace `LEFT JOIN` con
`pagos` para exponer `id_factura` a la pantalla de comprobante.

**PDF de factura** (`ciclista.py`, `_factura_pdf()`): compartido entre
origen membresía y origen alquiler (misma tabla real, mismo documento)
-- encabezado "Simulación académica — RUC no aplica", tabla
Concepto/Cantidad/Precio Unit./Subtotal, filas de Subtotal/IVA (15%)/
TOTAL reutilizando `generar_pdf_reporte()` sin escribir PDF nuevo
(mismo patrón que ya usan `fila_total` en los reportes de historial).
Ruta genérica `/ciclista/factura/{id_factura}/pdf`. Botón "Descargar
factura" agregado en `membresia_comprobante.html` junto al comprobante
ya existente -- con `flex-wrap` agregado a ese header, para no repetir
el mismo bug de las secciones 46-50 con un botón más en la fila.

**Backfill (`etl/11_backfill_facturas.py`, nuevo)**: recorre los
alquileres reales en `estado='facturado'`, usa la fecha real del
evento `'facturado'` (`alquiler_eventos.fecha`, no "ahora") como
`fecha_emision`, e idempotente (salta cualquier alquiler que ya tenga
factura). Corrido dos veces: primera corrida, **19 alquileres
revisados, 19 facturas creadas**; segunda corrida, **19 revisadas, 0
creadas, 19 saltadas** -- confirma idempotencia real. `historial.html`
y `_historial_data()` actualizados: el enlace "Comprobante" (antes
apuntando al PDF viejo de 2 columnas sin IVA) ahora resuelve
`id_factura` real vía `LEFT JOIN` con `facturas` y descarga la factura
nueva con desglose.

**Hallazgo de infraestructura real, no menor**: los reinicios de
`uvicorn` de esta sesión (y probablemente de sesiones anteriores)
**nunca mataron el proceso viejo de verdad**. `taskkill //F //PID
<pid>` vía git-bash reportaba "no se encontró el proceso" para el
mismo PID que `netstat`/`Get-NetTCPConnection` seguían mostrando como
dueño del puerto 8000 -- probablemente la conversión de rutas de MSYS
mangling el flag `//PID`. Esto quedó sin detectar durante las secciones
46-50 porque CSS y plantillas Jinja se leen frescos del disco en cada
request (no necesitan reinicio); recién se hizo evidente hoy con un
cambio de código Python real (`facturas_repo.emitir()` nunca se
ejecutaba, `pagos.id_factura` seguía en el sentinela pese a que el
archivo en disco ya tenía el cambio correcto). Diagnosticado con
`Get-Process`/`Get-NetTCPConnection` de PowerShell, resuelto con
`Stop-Process -Force` desde PowerShell (no desde git-bash) sobre el PID
real (`Get-Process` sí lo encontró, aunque el que colgaba el puerto
aparentaba ser un PID fantasma). **Recomendación para sesiones
futuras**: reiniciar el servidor con PowerShell (`Stop-Process`/
`Start-Process`), no con `taskkill` desde git-bash, y verificar el
reinicio con una prueba de comportamiento real (no solo el código de
estado HTTP), no solo confiar en que el puerto respondió.

**Verificación real (Parte 3)**:
- Membresía: activada en vivo para Adrian Guizado (`ciclista@urbanbike.com`,
  tarjeta de pruebas `4242 4242 4242 4242`). Factura real
  `001-001-000000020`: subtotal `$21.73`, IVA (15%) `$3.26`, total
  `$24.99` -- verificado con `round(total/1.15,2)`/`round(total-total/1.15,2)`
  directo en ClickHouse, coincide exacto con lo que muestra el PDF.
  Correlativo continúa correctamente después de las 19 del backfill.
- Historial: confirmado con capturas reales que los viajes `Pagado` de
  Adrian ahora muestran "Descargar factura" en vez del comprobante
  viejo; descargada la factura `001-001-000000018` (alquiler
  `A-010506`), PDF real de 24.4 KB, `fecha_emision` real
  (2026-07-09 20:48, no la fecha de hoy), concepto "Alquiler de
  bicicleta A-010506", subtotal `$0.22` + IVA `$0.03` = total `$0.25`
  exacto.
- `19 alquileres 'facturado' revisados, 0 descuadres` (`subtotal +
  impuesto = total` verificado con `countIf` sobre las 19 filas reales
  en ClickHouse).

## 52. Cancelación real de membresía, con reembolso condicionado a 48h (12 de agosto de 2026)

**`membresias_repo.cancelar(id_usuario)`** (nuevo): mismo patrón
append-only de siempre -- nunca un `UPDATE`, inserta una fila nueva con
`estado='cancelada'` (mismo criterio que ya usa `procesar_vencidas_hoy()`
para `'vencida'`: `fecha_inicio=fecha_fin=hoy`, `precio=0`, el cobro
real si lo hay vive en `pagos`, no en esta fila). `esta_activa()` deja
de ver el período pagado como vigente en la siguiente lectura, sin
esperar a que termine `fecha_fin` -- el beneficio se quita de
inmediato.

**Ventana de reembolso**: `VENTANA_REEMBOLSO_HORAS = 48`, comparado
contra `fecha_registro` real de la fila `'activa'` vigente (el cobro
real de ESE período, no la fecha de hoy). Dentro de la ventana: INSERT
real en `pagos` con `monto` **negativo** y `concepto='reembolso_membresia'`
(mismo criterio contable que cualquier libro mayor: un reembolso
negativo se neta solo en cualquier `SUM(monto)` futuro, sin casos
especiales). Fuera de la ventana: `id_pago` de la fila de cancelación
queda en el UUID sentinela, sin ningún INSERT en `pagos`.

**Ruta y pantalla**: `POST /ciclista/membresia/cancelar` (con
`onsubmit="return confirm(...)"`, mismo patrón ya usado en
`empleado/operacion/pagos.html` para acciones reales). Botón "Cancelar
membresía" en `membresia.html`, visible solo si `activa`. De paso se
agregó una rama `estado='cancelada'` al badge de estado -- antes caía
en la rama genérica de "Vencida" (el estado interno ya era correcto,
`esta_activa()` ya daba `False`, pero el texto confundía cancelación
con vencimiento natural).

**Verificación real, caso dentro de 48h**: activada una membresía real
(factura `001-001-000000020`, `$24.99`), cancelada ~27 minutos después
por el endpoint real. Confirmado en ClickHouse: pago de reembolso real
`monto=-24.99`, `concepto='reembolso_membresia'`, `estado='verificado'`.
Catálogo verificado con captura real: vuelve a precio casual (`USD
28.80`/`35.20`) de inmediato, sin esperar nada.

**Verificación real, caso fuera de 48h -- con un hallazgo real en el
camino**: no existe ningún camino en vivo para "esperar 49 horas", así
que se activó una membresía real y se le retrasó `fecha_registro` por
SQL para simular el paso del tiempo (confirmado con Washington antes
de tocar la BD). Primer intento con `ALTER ... UPDATE` falló:
`CANNOT_UPDATE_COLUMN` -- `fecha_registro` es parte del `ORDER BY` de
`membresias`, mismo tipo de restricción ya documentado varias veces en
este proyecto (sección 0). Corregido con el patrón ya establecido
(`DELETE` + `INSERT` idéntico con la fecha correcta desde el inicio,
nunca una mutación in-place).

Al hacerlo apareció un problema más de fondo: la cuenta de prueba de
Adrian tenía **13 filas de membresía acumuladas de sesiones de prueba
anteriores** (activaciones y renovaciones automáticas de prueba, todas
con `fecha_inicio` de hoy o ayer), y `estado_actual()` ordena por
`(fecha_inicio DESC, fecha_registro DESC)` -- cualquiera de esas 13
seguía ganando el orden sobre la fila de prueba retrasada, sin importar
cuánto se retrasara. Confirmado con Washington antes de borrar nada:
se limpiaron las 13 filas viejas de `membresias` + sus 14 `pagos`
asociados (13 de renovaciones/activaciones de prueba sin factura real,
más una que sí tenía factura real ligada -- `001-001-000000020`,
borrada también junto con su `factura_detalle`; ya estaba verificada y
reportada en la sección 51, no se perdía evidencia real). Con la
cuenta limpia, se repitió la activación + el `DELETE`+`INSERT`
retrasado (`fecha_registro` 49h antes de "ahora") y se canceló por el
endpoint real. Confirmado en ClickHouse: fila de cancelación con
`id_pago` en el UUID sentinela (sin reembolso), **cero** filas nuevas
en `pagos` con `concepto='reembolso_membresia'`. Confirmado visual: el
badge pasa a "Cancelada" (gris) de inmediato.

**Nota para sesiones futuras**: la cuenta de prueba de Adrian
(`ciclista@urbanbike.com`) acumula artefactos de cada sesión de prueba
de membresía -- vale la pena revisar periódicamente si conviene
limpiarla antes de que vuelva a interferir con una prueba real, en vez
de descubrirlo a mitad de una prueba como hoy.

## 53. Contraste de `--primary-light` en modo oscuro + banner de viaje activo en el dashboard (12 de agosto de 2026)

**Contraste en modo oscuro -- corregido con un solo token, sin tocar
plantillas**: `--primary-light` vivía solo en `:root` (`#D6EDF8`,
pensado para modo claro) y nunca se redefinía dentro de
`[data-theme="dark"]` normal (solo en la variante combinada
`dark`+`alto-contraste`). Agregada `--primary-light: #14304A` dentro de
`[data-theme="dark"]` -- calculado con la fórmula de luminancia
relativa de WCAG: >10:1 de contraste contra `var(--text)` (casi
blanco, `#E2E8F0`), >5:1 contra `var(--text-muted)`, ~3.3:1 contra
`var(--primary)` (suficiente para texto grande/negrita como los
precios de 1.6rem, aunque no para las insignias pequeñas que también
usan `--primary` sobre este fondo -- esas ya eran legibles antes del
fix, porque `--primary` no cambia entre temas, así que no eran parte
del bug real). Al ser una variable compartida, la corrección alcanza
de una sola vez la tarjeta "Reservar Bicicleta"
(`ciclista/dashboard.html`) y la tarjeta "Tarifas"
(`ciclista/detalle_bicicleta.html`) sin tocar ningún template --
ambas usan `background:var(--primary-light)` inline. `roles/dashboard.html`
(mismo patrón, archivo huérfano ya confirmado) no se tocó, tal como se
pidió.

Verificado visual en las 2 pantallas: modo oscuro con texto claramente
legible en ambas tarjetas (antes casi blanco sobre azul pálido, ahora
blanco sobre azul marino oscuro); modo claro sin ningún cambio visible
(`[data-theme="light"]` nunca tuvo su propio override, sigue leyendo
el valor de `:root` tal cual siempre lo hizo).

**Banner de viaje activo en el dashboard**: `ciclista/dashboard.html`
ya recibía `viaje_activo` del router (`/ciclista/dashboard` ya lo
calculaba) pero nunca lo usaba en ningún lugar del template -- dato
plomeado, nunca renderizado. Agregada una tarjeta clickeable
(`card-clickeable`) condicional (`{% if viaje_activo %}`) entre el
saludo y las tarjetas normales, con acento verde (`#10B981`, mismo
color que "Completado"/"disponibles" en el resto del sistema),
bicicleta + estación real, y enlace directo a `/ciclista/viaje-activo`.
Sin viaje activo, el `{% if %}` no renderiza nada -- el dashboard queda
idéntico al de siempre, sin ningún hueco ni banner vacío.

**Verificación real**: Adrian (`ciclista@urbanbike.com`) tiene una
infracción real pendiente (sección 23, todavía relevante para la
decisión de negocio pendiente #19 de la sección 6) que bloquea
`/ciclista/reservar` por diseño -- confirmado antes de tocar nada, y
**no se resolvió** esa infracción solo para destrabar esta prueba (es
evidencia real de un hallazgo todavía abierto). En su lugar, se creó
un viaje de prueba directo en PocketBase (mismos campos exactos que
insertaría `/reservar`, sin pasar por esa regla de negocio ajena a lo
que se estaba probando hoy). Confirmado con captura real: el banner
"Tienes un viaje en curso" aparece con los datos reales (`UB-001 ·
desde Parque La Carolina`), el enlace lleva a `/ciclista/viaje-activo`
real (detalle, mapa, cronómetro, formulario de devolución). Viaje de
prueba borrado al terminar (no "cerrado" por el flujo real, que
hubiera generado un pago ficticio sin viaje real detrás) -- confirmado
que el dashboard vuelve exactamente al estado sin banner.

## 54. Estado `pendiente_validacion` -- devolución autoreportada por el ciclista, con validación física de Vigilancia (12 de agosto de 2026)

**Contexto (pendiente #14, sección 6)**: el flujo real de alquiler del
ciclista sigue viviendo en PocketBase de punta a punta. Hasta hoy,
`/ciclista/finalizar` congelaba todo de una vez -- calculaba duración y
monto con la hora en que el ciclista *decía* haber dejado la bici,
creaba el pago ahí mismo, y liberaba la bicicleta -- sin que ningún
empleado hubiera confirmado la entrega física real. Un ciclista podía
reportar la devolución sin dejar la bicicleta, o dejarla en un sitio
no autorizado, y el sistema ya lo daba todo por cerrado.

**Diseño implementado**: nuevo estado intermedio `pendiente_validacion`
entre `activo` y `completado`. `/ciclista/finalizar` ya no calcula
nada -- solo mueve el viaje a `pendiente_validacion` con la
`estacion_fin_id` reportada, deja la bicicleta en `en_uso` (sigue sin
estar disponible para nadie más, pero tampoco se asume entregada) y no
crea ningún pago. El monto que le corresponderá pagar sigue una
fórmula en vivo (`costoEnVivo`, ver abajo) que aumenta cada segundo
mientras el viaje espera validación -- exactamente como una
penalización por el tiempo que la bicicleta pasa fuera del sistema sin
confirmación física.

**Estado del esquema real**: se agregó `pendiente_validacion` al campo
`select` `viajes.estado` en PocketBase vía PATCH a
`/api/collections/{id}` (no basta con usarlo desde el código -- los
campos `select` de PocketBase tienen una lista fija de valores
válidos). Confirmado por API: `['activo', 'completado', 'cancelado',
'pendiente_validacion']`.

**Fórmula de costo en vivo, compartida en un solo archivo**: extraída
a `/static/js/costo-en-vivo.js` (`segundosTranscurridos`,
`costoEnVivo`, `formatearDuracion`), cargado globalmente desde
`base.html`. Antes solo vivía inline en
`ciclista/viaje_activo.html`; ahora la usan también las filas de
`empleado/vigilancia/devoluciones.html` -- un solo lugar calcula el
número, nunca se duplica la fórmula ni puede quedar desincronizada
entre lo que ve el ciclista y lo que ve Vigilancia.

**Validación real de Vigilancia**: `vig_devolver` ahora sirve para los
dos orígenes reales -- `activo` (recepción en persona, pide estación
por formulario, como siempre) y `pendiente_validacion` (la estación ya
la reportó el ciclista, no hace falta pedirla de nuevo). La duración y
el monto se calculan siempre con la hora REAL del momento en que
Vigilancia confirma, nunca con la hora en que el ciclista reportó --
así el tiempo de espera hasta la validación también cuenta como parte
del cobro real, que es justamente el propósito de la penalización.
Recién en ese momento se crea el pago real (idempotente: si por
cualquier motivo ya existe uno para ese viaje, no duplica) y la
bicicleta pasa a `mantenimiento` (retenida para inspección, nunca
antes).

**Hallazgo de seguridad corregido de paso**: la pantalla de inspección
posterior (`vig_inspeccion` / `vig_inspeccion_registrar`) leía
`ciclista_id`/`bici_id`/`pago_id` de `request.session["devolucion_ctx"]`,
una clave que solo escribía `vig_devolver`. Si Vigilancia llegaba a la
pantalla de inspección por cualquier otro camino (navegando directo
por URL con el `bici_id`, un enlace guardado, refrescar tras perder la
sesión), `ctx` quedaba vacío y el bloque entero de infracción real +
cargo por daños se saltaba **en silencio** -- la bicicleta igual
quedaba en mantenimiento y la inspección se registraba, pero el
ciclista responsable de un daño real nunca recibía la infracción ni el
cargo. Corregido eliminando `devolucion_ctx` por completo: nuevo
helper `_viaje_para_inspeccion(pb, bici_id)` busca siempre el viaje
`completado` más reciente de esa bicicleta directo en PocketBase, sin
importar cómo se llegó a la pantalla. `ciclista_id`, `ciclista_nombre`
y `duracion_minutos` salen de esa fila real; `tiene_pago_pendiente` se
resuelve consultando `pagos` por `viaje_id`. Los templates
`inspeccion.html` (`ctx.*` → `viaje.*` / `tiene_pago_pendiente`
directo) y `devoluciones.html` se actualizaron acorde.

**Visibilidad para Vigilancia**: hasta hoy no existía ninguna forma de
que Vigilancia supiera que había una devolución pendiente de validar --
ni un contador, ni una alerta. Agregados dos indicadores reales, ambos
alimentados por el mismo conteo (`viajes` con
`estado = "pendiente_validacion"`, vía PocketBase, no ClickHouse,
porque el estado vive ahí): una sección completa "Pendientes de
validación" en `devoluciones.html` (arriba de "Viajes activos", con
badge de conteo, foto, monto en vivo por fila y botón "Validar
devolución" con `confirm()`), y un banner clickeable en
`vigilancia/dashboard.html` (visible solo si el conteo es > 0, enlaza
a `/empleado/vigilancia/devoluciones`).

**Prueba real de punta a punta** (12 de agosto de 2026, contra la app
corriendo en `127.0.0.1:8000`, PocketBase y ClickHouse reales,
verificado con requests HTTP autenticados como usuario real -- no
mocks):

1. **Ciclista reserva y devuelve** (`wacho@urbanbike.com` sobre
   `UB-001`, sin infracciones/pagos pendientes que bloquearan la
   reserva -- `ciclista@urbanbike.com` sí las tenía, de pruebas
   anteriores, así que se usó la otra cuenta de prueba real):
   `POST /ciclista/reservar` → viaje creado `activo`.
   `POST /ciclista/finalizar` → viaje movido a `pendiente_validacion`,
   pantalla del ciclista muestra el badge "Pendiente de validación" y
   el formulario de devolución desaparece. Confirmado en PocketBase:
   **cero pagos** creados para ese `viaje_id` en este punto.
2. **El monto sube mientras espera**: `devoluciones.html` (como
   Vigilancia) muestra la fila en la sección "Pendientes de
   validación" con `data-inicio`/`data-precio-hora` reales
   (`precio_hora = 4.5`); calculado con la misma fórmula
   (`costoEnVivo`) en dos lecturas separadas por 20s reales, el costo
   pasa de $0 a >$0 de forma monotónica creciente con el tiempo real
   transcurrido -- la fórmula es la misma que corre client-side cada
   segundo en el navegador.
3. **Vigilancia valida** (`empleado.vig@urbanbike.com`, esperando ~35s
   reales adicionales desde que el ciclista reportó):
   `POST /empleado/vigilancia/devolver/{viaje_id}` sin reenviar
   estación. Confirmado en PocketBase: `viaje.estado = "completado"`,
   `viaje.duracion_minutos = 2` (duración real hasta el instante de la
   validación, no hasta que el ciclista reportó -- la espera sí contó),
   `viaje.estacion_fin_id` igual al que reportó el ciclista.
   `bicicleta.estado = "mantenimiento"`. Exactamente **1 pago** creado
   con `monto_total = duracion_minutos/60 * precio_hora = $0.15`,
   coincidiendo con la duración congelada del viaje.
4. **Hallazgo de seguridad, probado específicamente**: nueva sesión de
   Vigilancia que nunca pasó por `vig_devolver` navega **directo por
   URL** a `/empleado/vigilancia/inspeccion/UB-001` (bici_id). La
   pantalla muestra correctamente "Wacho IA" y "2 min" (datos reales
   del viaje, no de sesión vacía). Se reprueba con una falla
   (`CHK-01`, "Freno delantero") y un cargo por daños de $25.00.
   Confirmado: se creó exactamente **1 infracción nueva** en
   PocketBase con `ciclista_id = wjdmqjyr3i8ceym` (el ciclista real del
   viaje, Wacho -- no vacío, no el de otra prueba anterior), y en
   ClickHouse (`urbanbike_operativa.infracciones`) el registro
   correspondiente con `monto_multa = 25` y la descripción exacta de
   la prueba. Antes de esta corrección, este mismo camino (URL directa)
   habría dejado `ctx` vacío y saltado todo este bloque en silencio --
   bicicleta igual retenida, pero sin infracción ni cargo real al
   ciclista responsable.

**No resuelto/fuera de alcance de hoy**: la migración completa del
flujo del ciclista de PocketBase a ClickHouse sigue pendiente (mismo
pendiente #14 de la sección 6) -- esta tarea solo cierra el hueco de
validación física dentro del sistema actual, no cambia dónde vive el
dato.

## 55. Registro público de ciclistas con contraseña propia + verificación real por correo (12 de agosto de 2026)

**Contexto y cambio de diseño real durante la sesión**: la primera
versión de esta tarea (auditada y diseñada, pero nunca completada del
todo -- se quedó esperando credenciales SMTP reales) usaba la cédula
como contraseña inicial, entregada por correo, con un aviso persistente
(`contrasena_default`) hasta que el usuario la cambiara. Antes de
terminarla, Washington cambió el diseño: el usuario elige su propia
contraseña al registrarse, y el correo pasa a servir para **verificar
que la dirección es real** (código de 6 dígitos), no para entregar
credenciales. Todo rastro del diseño anterior se eliminó del código y
del esquema real de PocketBase (`contrasena_default` -- campo borrado
de la colección `users`, no solo dejado de usar; el correo de
"bienvenida con tu cédula" reemplazado por completo).

**Auditoría real antes de escribir código**:
- **SMTP seguía sin configurar** -- ni Gmail ni Brevo, `.env` no tenía
  ninguna variable `SMTP_*` (la sesión anterior nunca llegó a recibir
  las credenciales). `app/config.py`/`app/email_client.py` ya existían
  con soporte genérico (funcionan igual con cualquier proveedor SMTP
  real, solo cambian los valores en `.env`).
- **Hallazgo bloqueante encontrado antes de activar nada**: los 10
  usuarios reales que ya existían en PocketBase (admin, gerente, los 3
  roles de empleado, y los 4 ciclistas/cuentas de prueba) tenían los
  10 `verified = false` -- el campo existe en el esquema desde que
  PocketBase crea una colección `auth`, pero nunca se había usado para
  nada real. Activar el bloqueo de login por `verified=false` tal cual
  habría dejado fuera a todo el sistema, admin incluido.

**Lo que se construyó**:
1. **Esquema real de PocketBase**: se quitó `contrasena_default` de
   `users` (PATCH real a `/api/collections/{id}`, no solo dejarlo sin
   usar) y se agregaron `codigo_verificacion` (texto, 6 dígitos) y
   `codigo_verificacion_expira` (fecha). `createRule` de `users` se
   mantuvo en superusuario únicamente (cerrado en la sesión anterior,
   sigue correcto -- la única puerta de alta real sigue siendo el
   backend de FastAPI).
2. **Backfill real de las 10 cuentas preexistentes**: `verified = true`
   aplicado directo por API admin a las 10, una por una, confirmado
   antes de tocar el login. Ninguna cuenta que ya tenía acceso lo
   perdió -- el bloqueo aplica solo hacia adelante.
3. **`/auth/registro`** (`app/routers/auth.py`): nombre, apellido,
   correo, cédula, contraseña + confirmar (mínimo 8 caracteres,
   validación de coincidencia). Cédula duplicada rechazada con consulta
   real (`filter=cedula=...`); correo duplicado lo rechaza el índice
   único real de PocketBase, traducido a un mensaje legible. `rol` se
   resuelve del lado del servidor vía `rol_id_por_slug("ciclista")`
   (nuevo helper en `app/db/pocketbase.py`) -- el formulario nunca
   puede elegir otro rol, mismo candado ya diseñado en la sesión
   anterior. La cuenta se crea con `verified=False` y un código real de
   6 dígitos (`secrets.randbelow`, no `random`) con expiración de 15
   minutos, enviado por correo real (`enviar_codigo_verificacion`,
   `app/email_client.py`, reemplaza a `enviar_correo_bienvenida`).
4. **`/auth/verificar`** (GET + POST) **y `/auth/verificar/reenviar`**:
   pantalla real donde se ingresa el código. Comparación con
   `secrets.compare_digest` (no `==`, mismo criterio que ya usa el
   CSRF real del sistema). Código incorrecto o vencido -> error con
   mensaje claro y botón "Reenviar código" (genera uno nuevo, invalida
   el anterior). Correcto y vigente -> `verified=True`, limpia
   `codigo_verificacion`/`codigo_verificacion_expira`, redirige a login
   con éxito. El correo objetivo viaja en sesión
   (`verificar_email`), nunca en el formulario, para que no se pueda
   verificar la cuenta de otra persona con solo saber su correo.
5. **Bloqueo real en `/auth/login`**: si `record.get("verified")` es
   `false` tras una contraseña correcta, no se crea sesión -- se guarda
   `verificar_email` y redirige directo a `/auth/verificar` con un
   flash claro ("Verifica tu correo antes de iniciar sesión..."),
   reutilizando el mismo reenvío en vez de dejar al usuario en un
   callejón sin salida.
6. **Cuentas creadas por Admin/Gerente, corregidas de paso**:
   `admin/usuarios.html` (`usuarios_crear`) y
   `gerente/empleados.html` (`empleados_crear`) ya creaban cuentas
   reales sin pasar por el registro público -- sin `verified=True`
   explícito, el nuevo bloqueo las habría dejado fuera del sistema la
   primera vez que alguien intentara entrar. Corregido en el mismo
   cambio (no hallazgo aparte): ambas rutas ahora crean con
   `verified=True` directo, sin correo de verificación de por medio
   (acto de por sí verificado, es un alta manual de un rol de
   confianza). De paso se quitó la llamada muerta a
   `pb.request_verification()` en ambas rutas -- dependía del SMTP
   propio de PocketBase (deshabilitado, confirmado en la auditoría de
   la sesión anterior) y no se integraba con ningún flujo de
   verificación real que la app implementara.

**Prueba real de punta a punta** (12 de agosto de 2026, contra la app
corriendo en `127.0.0.1:8000`, PocketBase y Brevo reales, sin mocks):

1. Registro con correo real (`washingtonapunte123@gmail.com`) y
   contraseña propia. Confirmado en PocketBase: cuenta creada con
   `rol=ciclista` (id real, nunca elegible desde el formulario),
   `verified=False`, código real de 6 dígitos con expiración guardados.
2. Correo real enviado por Brevo (confirmado por la respuesta SMTP
   exitosa del envío real, sin mocks).
3. Login con la cuenta sin verificar **antes** de ingresar el código:
   bloqueado -- no crea sesión, redirige a `/auth/verificar` con el
   mensaje "Verifica tu correo antes de iniciar sesión...".
4. Código incorrecto (`000000`) rechazado con mensaje claro. Botón
   "Reenviar código" probado: genera un código nuevo real, distinto al
   anterior (confirmado comparando ambos directo en PocketBase).
5. Verificación con el código real vigente: `verified=True`, campos de
   código limpiados, redirige a login con "Correo verificado. Ya puedes
   iniciar sesión."
6. Login exitoso tras verificar: llega al dashboard real de ciclista.
7. Regresión confirmada en las dos direcciones: una cuenta preexistente
   con el backfill (`wacho@urbanbike.com`) sigue entrando normal sin
   pedir verificación; una cuenta nueva creada por Admin
   (`admin/usuarios/crear`) tampoco queda bloqueada por verificación
   (sí quedó bloqueada por `activo` -- **hallazgo aparte, no de esta
   tarea**: `usuarios_crear()` nunca seteó `activo=True` explícito, ver
   pendiente nuevo abajo).

**Hallazgo nuevo, no pedido, hallado al probar (pendiente, no
corregido hoy)**: `admin/usuarios/crear` no fija `activo=True` en el
payload -- una cuenta creada desde Admin cae en el valor por defecto
del campo (`false`), y termina en `/auth/bloqueado` igual que una
cuenta desactivada a propósito. Preexistente a esta tarea (no lo causó
el bloqueo de `verified`), pero lo dejó en evidencia la prueba real de
hoy. No corregido porque no fue pedido.

**Cuentas de prueba dejadas como evidencia real** (mismo criterio que
el resto del sistema, ver sección 53): `washingtonapunte123@gmail.com`
(ciclista, verificado de punta a punta con el código real) y
`prueba.admin.verified@urbanbike.com` (creada por Admin, evidencia del
hallazgo de `activo` sin fijar). **La segunda se eliminó en la sección
56**, una vez corregido el hallazgo -- ya no reflejaba el
comportamiento real del sistema, quedar como residuo habría sido
confuso (bug fantasma que ya no existe).

## 56. Tamaño de fuente en las pantallas standalone de auth + `activo=True` faltante en Admin (12 de agosto de 2026)

**Aclaración de partida**: Washington pidió revisar "la sección 44
(donde se subió el tamaño de letra general del sistema)" -- leída
completa, la sección 44 es sobre indicadores de acción masiva de
permisos, sin ninguna relación con tipografía. Tampoco existe en todo
`docs/HOJA_DE_RUTA.md` ninguna sección que documente una subida general
de tamaño de fuente. Reportado antes de tocar nada, tal como se pidió,
en vez de construir sobre una premisa que no era real.

**Causa real, confirmada en el código (no una clase con tamaño fijo,
como se sospechaba)**: `login.html` usa exactamente las mismas clases
compartidas (`.form-input` a `0.9375rem`, `.form-label` a `0.8125rem`)
que el resto del sistema, sobre el mismo `html { font-size: 16px }` de
`main.css` -- no hay ningún valor propio hardcodeado. La causa real es
que el sistema **sí** tiene un mecanismo real de tamaño de letra: el
panel de accesibilidad (`app/static/js/usabilidad.js`, botones
Normal/A+/A++) aplica `data-font-size="grande|extra"` sobre `<html>` y
lo persiste en `localStorage`. `base.html` carga ese script en todas
las pantallas internas -- pero `auth/login.html`, `auth/registro.html`,
`auth/verificar.html` y `auth/bloqueado.html` son plantillas standalone
(no extienden `base.html`) que nunca lo cargaban. Cualquier preferencia
de tamaño ya elegida en el resto del sistema quedaba guardada en
`localStorage` pero jamás se aplicaba en estas 4 pantallas.

**Segundo hallazgo, encontrado al diseñar el fix (no alcanzaba con solo
agregar el `<script>`)**: `usabilidad.js` tenía un `return` temprano
(`if (!toggleBtn || !panel) return;`) que cortaba *toda* la
inicialización -- incluida la que aplica el tamaño guardado -- si no
encontraba el panel de accesibilidad en el DOM, que solo existe en
`base.html`. Corregido separando las dos responsabilidades: aplicar las
preferencias guardadas (`cargarEstadoInicial()`) ahora corre siempre en
`DOMContentLoaded`, independiente de que exista el panel; solo el
cableado de los controles del panel (abrir/cerrar, botones, checkboxes)
sigue detrás del `return`, que es lo único que de verdad depende de que
el panel exista. Efecto colateral correcto, no alcance ampliado sin
pedirlo: las 4 pantallas standalone ahora también heredan contraste
alto, marcador de línea y guía de enfoque si el usuario los tenía
activados, mismo mecanismo, mismo bug.

**Fix aplicado**: `<script src="/static/js/usabilidad.js"></script>`
agregado a las 4 plantillas standalone de `auth/`. Ningún valor de
`rem`/`px` inventado -- el tamaño que se ve ahora en login es
exactamente el mismo que ya usa el resto del sistema para el nivel de
accesibilidad que el usuario tenga elegido.

**Prueba real (navegador real, Chrome vía MCP)**: con
`localStorage` limpio (nivel "Normal", 16px), captura de
`/auth/login` sin cambios visibles frente al estado anterior --
correcto, ese caso nunca estuvo roto. Con
`localStorage.setItem('ub-font-size', 'extra')` + recarga: capturas
reales de `/auth/login` y `/auth/registro` mostrando el texto
notablemente más grande, formulario completo y centrado, sin
scroll horizontal. Confirmado también por JS en la página:
`document.documentElement.getAttribute('data-font-size') === 'extra'`,
`getComputedStyle(html).fontSize === '20px'` (antes 16px),
`getComputedStyle('.form-input').fontSize === '18.75px'` (escala
proporcional real vía `rem`, no un valor absoluto nuevo), y
`document.documentElement.scrollWidth === document.documentElement.clientWidth`
(sin desborde horizontal). `localStorage` restaurado a su estado
original (sin la clave) al terminar la prueba.

**Segunda tarea -- `activo=True` faltante en `admin/usuarios/crear`**
(hallazgo dejado documentado en la sección 55, corregido hoy):
`usuarios_crear()` en `app/routers/admin.py` ya fijaba `verified=True`
pero nunca `activo` -- una cuenta creada por Admin caía en el valor por
defecto de PocketBase (`false`) y terminaba en `/auth/bloqueado` igual
que una cuenta desactivada a propósito. Corregido agregando
`"activo": True` al mismo payload, mismo criterio ya usado para
`verified`. Auditadas las otras dos rutas reales que crean cuentas
(`grep` de `create_record("users"` en todo `app/`, exhaustivo, solo 2
resultados): `gerente.py:empleados_crear()` ya tenía `activo=True`
desde la sesión anterior, y `auth.py:registro_post()` (registro
público) también -- no hacía falta tocar ninguna de las dos.

**Prueba real**: cuenta nueva creada vía
`POST /admin/usuarios/crear` (`prueba.activo.fix@urbanbike.com`) con
sesión real de `admin@urbanbike.com`. Confirmado directo en PocketBase:
`activo=True` y `verified=True` en el registro real, sin intervención
manual. Login inmediato con esa cuenta, misma sesión de prueba:
`POST /auth/login` devuelve `200` con redirect a `/dashboard` --
**nunca pasa por `/auth/bloqueado` ni por `/auth/verificar`**. La
cuenta de prueba obsoleta de la sección 55
(`prueba.admin.verified@urbanbike.com`, creada antes del fix, con
`activo=False` real) se eliminó -- ya no representaba el comportamiento
actual del sistema, dejarla habría sido evidencia de un bug que ya no
existe.

## 57. El fix de la sección 56 no alcanzaba: el tamaño por defecto seguía chico para un usuario nuevo (12 de agosto de 2026)

**Pregunta real de Washington antes de cerrar la sección 56**: ¿qué
tamaño ve alguien que entra a `/auth/login` por primera vez, sin
ninguna preferencia guardada en `localStorage`? El fix anterior solo
arreglaba la herencia de una preferencia *ya elegida* en otra pantalla
-- no tocaba el tamaño por defecto en sí.

**Confirmado con evidencia real antes de tocar nada** (Chrome real,
`localStorage` limpiado a mano, sesión cerrada para no heredar nada):
`data-font-size` nulo, raíz en `16px`, `.form-input` en `15px`,
`.form-label` en `13px` -- exactamente igual que siempre. La sospecha
de Washington era correcta: el fix de la sección 56 nunca subió el
tamaño por defecto, solo dejó de bloquear una preferencia previa que la
mayoría de usuarios nuevos, por definición, todavía no tiene.

**Fix real**: en vez de inventar un valor nuevo, se reutilizó el nivel
"grande" que ya existe en `main.css`
(`html[data-font-size="grande"] { font-size: 18px; }`, mismo mecanismo
del panel de accesibilidad) como **default explícito** de
`auth/login.html` y `auth/registro.html` -- `data-font-size="grande"`
agregado directo al `<html>` de esas dos plantillas (mismo criterio
pedido: "no un valor inventado aparte").

**Conflicto real encontrado al implementarlo**: `usabilidad.js`
(después del fix de la sección 56) forzaba
`applyFontSize(localStorage.getItem(...) || "normal")` en cada carga
-- con `localStorage` vacío, esto pisaba el `data-font-size="grande"`
recién declarado y lo devolvía a `"normal"` de inmediato, apenas
corría el script. Corregido separando los dos casos reales:
- **Hay preferencia guardada** (el usuario ya la eligió en algún lado,
  aunque sea "Normal" explícito): se aplica siempre, gana sobre
  cualquier default de la página.
- **No hay preferencia guardada** (primera visita real a todo el
  sistema): se respeta el `data-font-size` que la plantilla ya trae, y
  **a propósito no se escribe nada en `localStorage`** -- si se
  persistiera, la primera visita a login dejaría "grande" como
  preferencia real del usuario para *todo* el sistema (dashboard
  incluido) sin que lo haya elegido nunca, más alcance del que se
  pidió (solo login/registro).

**Prueba real** (Chrome real, sin mocks):
1. `localStorage` limpio + sesión cerrada + recarga de `/auth/login`:
   `data-font-size="grande"`, raíz `18px` (antes `16px`), `.form-input`
   `16.875px` (antes `15px`), `.form-label` `14.625px` (antes `13px`),
   **`localStorage.getItem('ub-font-size') === null`** (el default no
   se filtró como preferencia real). Captura visual confirma el texto
   notablemente más grande, formulario completo, sin desborde.
   `/auth/registro` confirmado igual.
2. Con `localStorage.setItem('ub-font-size', 'extra')` + recarga:
   `data-font-size="extra"`, raíz `20px` -- la preferencia explícita
   del usuario sigue ganando por encima del default de la página, no
   se queda atascado en "grande".
3. Con `localStorage.setItem('ub-font-size', 'normal')` + recarga:
   `data-font-size` nulo, raíz `16px` -- un "Normal" explícito también
   se respeta, no se fuerza "grande" contra la voluntad real del
   usuario.

`localStorage` restaurado a vacío al terminar la prueba, mismo criterio
de limpieza que el resto de las pruebas reales de esta sesión.

## 58. Monto de ahorro explícito junto al precio con descuento (12 de agosto de 2026)

**Auditoría (sin tocar nada, tal como se pidió)**: `_catalogo_bicicletas()`
(`app/routers/ciclista.py`, ver sección 20) ya calculaba, para las 3
modalidades (hora/día/semana), `precio_X_member` (final),
`precio_X_sin_promo` (original, `None` si no hay promo) y `promo_X`
(`{codigo, nombre}` o `None`). Lo único que faltaba era la resta en sí
-- ni Python ni las plantillas calculaban el monto real ahorrado en
ningún lado.

**Cambios**:
- `_catalogo_bicicletas()`: 3 campos nuevos,
  `ahorro_hora`/`ahorro_dia`/`ahorro_semana` = `round(precio_base -
  precio_member, 2)`, presentes **solo** cuando la promo
  correspondiente existe (mismo criterio ya usado para
  `precio_X_sin_promo` -- nunca "Ahorras $0").
- `componentes/tarjeta_bicicleta.html` (catálogo): nueva línea
  "Ahorras USD X.XX con {promo}" dentro del mismo bloque de promo ya
  existente (mismo `{% if %}` que ya lo ocultaba por completo si no
  hay ninguna promo en las 3 modalidades). Nuevos
  `data-ahorro-hora/dia/semana` para que el toggle de modalidad
  (`alquilar.html`) actualice el texto en vivo sin recargar, igual
  patrón que ya usaba para el precio tachado. CSS: el bloque de promo
  pasa de una fila a dos (`flex-direction: column`), con la línea de
  ahorro en verde (`#10B981`) y negrita para que resalte como
  incentivo real, no como texto secundario.
- `detalle_bicicleta.html`: misma línea agregada a los 3 bloques
  estáticos de modalidad (hora/día/semana se muestran juntos, sin JS).

**Prueba real** (vía HTTP autenticado + Chrome real, sin mocks, con
`ESTUD20` activa hoy -- miércoles, dentro de sus días de semana
lun-vie -- 20% de descuento, la de mayor ahorro entre las 3 promos
reales vigentes):
- Catálogo (`GET /ciclista/alquilar`): confirmado matemáticamente para
  la primera bici con promo -- hora `USD 5.50 → 4.40`, "Ahorras USD
  1.10"; día `USD 44.00 → 35.20`, "Ahorras USD 8.80"; semana `USD
  220.00 → 176.00`, "Ahorras USD 44.00" -- exactos, 20% en las 3.
- Toggle de modalidad real en Chrome (clic real en "Por hora" y "Por
  semana", sin recargar): las 3 tarjetas del catálogo actualizaron el
  texto de ahorro en vivo, matemáticamente correcto en cada caso
  (verificado leyendo el DOM real después de cada clic, no solo el
  HTML inicial). Sin desborde horizontal en ningún estado
  (`scrollWidth === clientWidth`).
- Ficha de detalle (`GET /ciclista/bicicleta/{id}`): las 3 modalidades
  confirmadas con `precio_member + ahorro == precio_sin_promo` exacto
  (hora `4.40+1.10=5.50`, día `35.20+8.80=44.00`, semana
  `176.00+44.00=220.00`).
- **Caso "sin promo" no se pudo probar con datos reales hoy** -- las 3
  promociones vigentes (`ESTUD20`, `FINDE15`, `PRUEBA-WP`, ver sección
  20) aplican todas a `aplica_a=todas`, así que hoy no existe ninguna
  bicicleta/modalidad real sin descuento para demostrarlo en vivo sin
  pausar una promoción real solo para la prueba (no se hizo, por no
  interrumpir el sistema real). Verificado por construcción en su
  lugar: `ahorro_X` es `None` salvo que `promo_X` exista, el
  `{% if %}` que envuelve todo el bloque exige al menos una promo
  entre las 3 modalidades, y el toggle de JS oculta el bloque completo
  (`display:none`) para cualquier modalidad sin promo -- mismo
  mecanismo ya probado y en producción desde la sección 20 para el
  precio tachado, ahora comparte el gate con la línea de ahorro.

## 59. Bug real de registro -- "No se pudo completar el registro" ocultaba la causa real (12 de agosto de 2026)

**Reproducido con datos nuevos reales**, no el correo ya usado en
pruebas anteriores. El primer intento con datos completamente nuevos
funcionó sin problema -- el bug **no** es "cualquier registro nuevo
falla". Antes de asumir nada, se inspeccionaron los logs reales del
servidor y se probó `pb.create_record()` directo contra PocketBase
(mismo cliente que usa la app) con varias variantes realistas (nombres
con tilde/ñ, cédulas con cero inicial) -- todas funcionaron también.

**Causa real, encontrada probando el caso más común que un usuario real
puede repetir sin querer: registrarse dos veces con el mismo correo**
(ya tenía cuenta, lo olvidó, o reintentó tras un error de red).
Capturado el JSON crudo que devuelve PocketBase para ese caso exacto:

```json
{"data": {"email": {"code": "validation_not_unique", "message": "Value must be unique."}},
 "message": "Failed to create record.", "status": 400}
```

`PocketBaseClient._handle()` (`app/db/pocketbase.py`) solo capturaba el
campo superior `message` (**siempre** el genérico "Failed to create
record.", para *cualquier* fallo de validación, no solo duplicados) y
descartaba por completo `data`, que es donde vive el motivo real por
campo. `registro_post()` (`app/routers/auth.py`) intentaba distinguir
"correo duplicado" con `if "email" in msg.lower()` contra ese mismo
mensaje genérico -- una condición que **nunca podía ser cierta**,
porque la palabra "email" jamás aparece en "Failed to create record.".
El resultado: el caso más común y más útil de explicarle al usuario
(correo ya registrado) siempre caía en el mensaje genérico
"No se pudo completar el registro. Verifica los datos e intenta de
nuevo." -- técnicamente cierto pero inútil, exactamente la sensación de
"algo se rompió" que reportó Washington.

**Corrección**: `PocketBaseError` ganó un tercer atributo `data: dict`
(retrocompatible -- valor por defecto `{}`, los otros 3 sitios reales
que ya atrapan esta excepción en el código no necesitaron cambios).
`_handle()` ahora captura `body.get("data")` además de `message`.
`registro_post()` revisa `"email" in e.data`/`"cedula" in e.data`
(el detalle real por campo) en vez de adivinar por texto -- mensaje
específico y correcto para correo duplicado, uno nuevo para cédula con
problema de validación real de PocketBase (defensa en profundidad,
aunque el duplicado de cédula ya se revisa antes con una consulta
propia), y el genérico solo para lo que de verdad no se puede
identificar.

**Prueba real de punta a punta, 3 partes**:
1. **Reproducción exacta del bug** (antes del fix, con el JSON crudo de
   arriba como evidencia): registrar dos veces el mismo correo real vía
   HTTP mostraba el mensaje genérico incorrecto.
2. **Confirmado el fix**: mismo escenario exacto (registro real +
   segundo intento con el mismo correo) vía HTTP contra el servidor ya
   corregido -- mensaje ahora exacto: "Ya existe una cuenta registrada
   con ese correo."
3. **Dos registros nuevos distintos, de punta a punta, para confirmar
   que no fue casualidad**: dos cuentas reales
   (`washingtonapunte123+regfix1@gmail.com`,
   `...+regfix2@gmail.com`) -- cada una con su propio código real de 6
   dígitos generado y enviado por Brevo (confirmado por la rama de
   éxito real del flash, no la de "no pudimos enviarte el correo"),
   verificación con el código real (`verified=True` confirmado en
   PocketBase) y login exitoso hasta `/ciclista/dashboard`. Las dos
   quedan como evidencia real.

## 60. Auditoría de lightbox en fotos reales: 5 huecos sin ampliar en `perfil.html` y 4 modales, `historial.html` confirmado como excepción intencional (14 de agosto de 2026)

**Punto de partida**: el avatar del sidebar (`base.html`) ya tenía el
lightbox funcionando; la foto de perfil en `/perfil` no se ampliaba al
hacer clic. Antes de corregir solo ese caso, se pidió un barrido de
**todas** las imágenes reales del sistema (catálogo, ficha de
bicicleta, WorkPanels con fotos, comprobantes y perfil) para no dejar
otro hueco escondido.

**Método**: `grep` de `<img` sobre `app/templates/**/*.html` (16
archivos con al menos una `<img>` real, logo excluido) y revisión de
cada resultado para confirmar si traía `data-lightbox`/`data-full` --
los dos atributos que `lightbox.js` (`app/static/js/lightbox.js`)
detecta por delegación de eventos en `document`, sin necesidad de
volver a "escanear" el DOM cuando la imagen se inserta después vía JS.

**5 huecos reales encontrados** (imagen real del sistema, mostrada al
usuario, sin los atributos):
1. `app/templates/perfil.html:29` -- foto de perfil propia, el caso
   reportado que disparó la auditoría.
2. `app/templates/admin/bicicletas.html:194` -- preview de "foto
   actual" dentro del modal de editar bicicleta, generado por JS
   (`openEdit()`). La fila de la tabla (línea 37) sí tenía lightbox
   desde el 30 de julio (sección 9); este preview del mismo archivo se
   quedó fuera en aquel momento.
3. `app/templates/gerente/bicicletas_form.html:132` -- preview "Foto
   actual" en el formulario de editar bicicleta (server-rendered, no
   JS). Mismo patrón que el punto anterior, en el otro archivo que la
   sección 9 marcó como resuelto.
4. `app/templates/admin/usuarios.html:290` -- preview del avatar
   actual en el modal de editar usuario, generado por JS
   (`openEdit()`).
5. `app/templates/admin/usuarios.html:304` -- avatar mostrado en el
   modal "Ver perfil" de un usuario, generado por JS (`openPerfil()`).

En los 4 casos generados por JS (2, 4 y 5 más el propio `openEdit` de
usuarios), el patrón real era el mismo: la tabla ya tenía lightbox en
su miniatura, pero el HTML se reconstruye con un string JS aparte
para el modal de edición/detalle, y ese string nunca recibió los
atributos cuando se aplicó el lightbox original.

**Todo lo demás ya tenía lightbox correcto** y no se tocó: tabla de
`admin/bicicletas.html` y `gerente/bicicletas.html`, catálogo
(`ciclista/alquilar.html`, `componentes/tarjeta_bicicleta.html`),
ficha de bicicleta (`ciclista/detalle_bicicleta.html`), avatar del
sidebar (`base.html`), tabla de usuarios y empleados
(`admin/usuarios.html` fila, `gerente/empleados.html`), órdenes de
mantenimiento (`empleado/mantenimiento/ordenes.html`),
inspección/devoluciones de vigilancia
(`empleado/vigilancia/inspeccion.html`,
`empleado/vigilancia/devoluciones.html`), comprobante de pago
(`empleado/operacion/pagos.html`) e inventario
(`empleado/operacion/inventario.html`).

**Excepción intencional, no pendiente**: `ciclista/historial.html`
(líneas 54 y 184) usa su propio modal (`abrirModalBici()` /
`#biciModal`, con `#modalImg`, título, badge de tipo y texto
descriptivo persuasivo) en vez de `lightbox.js`. No es el mismo hueco
que los 5 anteriores -- ahí la imagen sí se amplía al hacer clic, solo
que con un mecanismo propio y más rico (información de la bicicleta
alrededor de la foto, no solo la foto). Convertirlo a `lightbox.js`
implicaría perder ese contenido adicional o duplicar UI, así que se
dejó explícitamente sin tocar. Si en el futuro se decide unificarlo,
es un rediseño de esa pantalla, no un fix de lightbox faltante.

**Corrección**: se agregaron `data-lightbox` y `data-full` en los 5
puntos reales, reutilizando exactamente `lightbox.js` -- sin
mecanismo nuevo, sin duplicar código. En los 3 generados por JS se
agregó `cursor:zoom-in` al string igual que ya tenían sus
contrapartes de tabla; en `gerente/bicicletas_form.html` se igualó al
patrón ya usado en la miniatura de la línea 26 del mismo archivo.

**Prueba real** (servidor `uvicorn` real levantado, login real como
`admin@urbanbike.com` vía Chrome, sesión cerrada y servidor detenido
al terminar):
1. `/perfil`: clic real en la foto de perfil -- se abrió el overlay
   de `lightbox.js` con la imagen ampliada y botón de cerrar.
   Confirmado visualmente.
2. `admin/usuarios`: clic real en "Ver perfil" del usuario Heiner
   Zambrano (con foto real, no iniciales) -- el modal abrió con su
   avatar; clic en el avatar disparó el lightbox real
   (`#lightbox-overlay` con clase `open` y `<img class="lightbox-img">`
   apuntando a la URL real de PocketBase
   `.../api/files/users/nnovna8cedlcwdl/hinerimg_yjvrw198dz.jpg`).
   Confirmado leyendo el DOM real después del clic y visualmente por
   captura.
3. Los otros 3 puntos (`admin/bicicletas.html`,
   `gerente/bicicletas_form.html`, modal de editar usuario) comparten
   el mismo componente (`data-lightbox` + delegación de eventos en
   `document`) ya verificado en vivo en los dos casos anteriores --
   no se probaron uno por uno en el navegador porque es el mismo
   mecanismo, no lógica distinta por pantalla.

## 61. Correo de verificación: logo real embebido, pie de correo, contenido más cálido, y por qué Gmail lo marcaba como "detectado en inglés" (14 de agosto de 2026)

**Punto de partida**: el correo HTML ya llegaba de verdad (confirmado con
captura real de Washington en una sesión anterior), pero con 3 problemas
reales: el logo era solo texto estilizado ("UrbanBike" en Sora, sin la
bicicleta), no tenía pie de correo, y Gmail mostraba el aviso "Este
mensaje está escrito en inglés" con opción de traducir, pese a que todo
el contenido es español.

**Auditoría pedida antes de tocar nada:**

1. **Por qué Gmail detectaba inglés** -- revisados los 3 sospechosos
   reales: `<html lang="es">` ya estaba declarado (sección anterior);
   charset UTF-8 correcto en ambas partes MIME (`text/plain` y
   `text/html`, confirmado inspeccionando los bytes crudos del mensaje --
   ambas partes en `base64` limpio, sin mojibake); el `Subject` también
   correcto, codificado por Python vía RFC 2047
   (`=?utf-8?q?Verifica_tu_correo_=E2=80=94_UrbanBike?=`). Ningún
   síntoma de corrupción de encoding.

   **Causa real encontrada**: faltaba la cabecera MIME real
   `Content-Language` (RFC 3282) a nivel de mensaje. El `<html lang="es">`
   del cuerpo, por sí solo, no alcanza como señal para Gmail -- Gmail
   sanea el HTML recibido antes de mostrarlo (descarta `<html>`/`<head>`
   originales y reinyecta solo el `<body>` saneado dentro de su propia
   página, cuyo `<html>` real es el de la interfaz de Gmail, no el del
   correo), así que ese atributo nunca sobrevive hasta el clasificador de
   idioma. La cabecera `Content-Language` a nivel de transporte sí
   sobrevive al saneo -- es la señal recomendada por los principales ESP
   (Mailchimp, SendGrid, Postmark) exactamente para este síntoma. Se deja
   documentado con honestidad: el clasificador de Gmail no es público, así
   que esto es la corrección correcta y mejor fundamentada disponible, no
   una garantía absoluta -- de ahí que la prueba real (más abajo) sea la
   que de verdad confirma si funcionó.

2. **Logo real en PNG** -- confirmado por `find`/`grep` que no existía
   ningún logo raster en `app/static/` (solo el SVG inline, duplicado en
   `componentes/membrete.html` y redibujado con formas de `reportlab` en
   `app/reportes/pdf.py::_logo_bicicleta`, mismo diseño, código distinto
   por motor de render). Generado `app/static/img/logo-email.png` con
   Pillow, redibujando a mano las mismas coordenadas exactas del viewBox
   28x28 del SVG original (círculos, trazo del marco con extremos
   redondeados simulados, círculo relleno de la "cabeza") + wordmark
   "UrbanBike" en `Sora-Bold.ttf` (ya existente en `app/static/fonts/`),
   mismo azul `#1E86BD` que `BLUE` en `app/reportes/comun.py`. Revisado
   visualmente antes de usarlo: bicicleta + wordmark nítidos, sin
   artefactos, proporciones consistentes con el resto del sistema.

**Cambios en `app/email_client.py`:**

- Estructura MIME cambiada de `multipart/alternative` (texto + html) a
  `multipart/related` conteniendo un `multipart/alternative` (texto +
  html) más el PNG del logo como adjunto `inline` con
  `Content-ID: <logo-urbanbike>` -- estructura estándar (RFC 2387) para
  incrustar una imagen sin depender de una URL externa, que quedaría
  bloqueada por defecto en la mayoría de clientes. El HTML referencia
  `src="cid:logo-urbanbike"`. Adjuntar el logo es best-effort (mismo
  criterio que el resto del archivo): si el PNG no se puede leer, se
  loggea y el correo se manda igual sin imagen, nunca se cae el envío
  completo por eso.
- `Content-Language: es` agregado como cabecera real del mensaje y de la
  parte `text/html`, más `<meta http-equiv="Content-Language" content="es">`
  en el `<head>` (redundante para clientes que no reescriben el
  documento, como Outlook o Apple Mail).
- Pie de correo real (antes no existía): "Sistema de Alquiler de
  Bicicletas UrbanBike", aviso de correo automático sin respuesta, y
  "© {año actual} UrbanBike. Todos los derechos reservados." -- sin
  inventar dirección física ni enlaces a redes sociales que no existen,
  tal como se pidió. Año calculado con `date.today().year`, no
  hardcodeado.
- Saludo y contenido más cálidos: "¡Hola {nombre}!" en vez de "Hola
  {nombre},", y un párrafo nuevo de bienvenida explicando qué podrá
  hacer el usuario una vez verificada la cuenta (reservar bicicletas,
  seguimiento de viajes y pagos, promociones). Toda la información
  técnica que ya estaba bien (vigencia de 15 min, aviso de seguridad si
  no fue el usuario, firma "Equipo UrbanBike") se mantuvo sin cambios de
  fondo. El texto plano (respaldo real de la parte HTML) recibió el
  mismo tono y el mismo pie, para no dejarlo desactualizado frente al
  HTML.
- **Alcance del punto 4 (aplicar la mejora a otros correos)**: auditado
  con `grep` de `smtplib`/`MIMEMultipart`/`send_message` en todo `app/`
  -- `enviar_codigo_verificacion` es el único correo automático real del
  sistema, usado solo desde `registro_post()` en `app/routers/auth.py`.
  No había otro correo al que aplicarle el rediseño.

**Prueba real**: reenviado un código real (`482013`) a
`washingtonapunte123@gmail.com` vía `enviar_codigo_verificacion()`
directo (mismo cliente SMTP que usa la app) -- `True`, aceptado por el
relay de Brevo sin excepciones en el handshake. Queda pendiente la
confirmación de Washington con una captura nueva mostrando: logo como
imagen real (no solo texto), pie de correo visible, y sin el aviso de
"detectado en inglés" de Gmail.

## 62. Cinco pendientes reales sobre registro/perfil: cédula invisible, duplicados (ya estaban), teléfono nuevo, iniciales del avatar, y contacto de soporte en bloqueo (14 de agosto de 2026)

**PARTE A -- cédula de Doris Paz invisible en `/perfil`.** Confirmado
primero contra PocketBase real (no se asumió nada): el registro de
`dorispaz2026@gmail.com` sí tenía `cedula: "1251050044"` guardada -- el
bug no estaba en el registro, estaba en la lectura/exhibición. Causa
real: `login()` (`app/routers/auth.py`) arma el diccionario `user` que
se guarda en `request.session["user"]` (y de ahí a
`request.state.user` vía `AuthMiddleware`, sin transformación) con una
lista fija de campos -- `id/email/name/pb_token/rol_id/rol_slug/
rol_nombre/avatar` -- que nunca incluyó `cedula`. `/perfil` lee
`user.cedula` de esa sesión, no de PocketBase directo, así que
mostraba "—" aunque el dato real existiera. `perfil_post()` sí
actualizaba `user["cedula"]` en sesión al guardar un cambio -- por
eso el bug no aparecía para cualquiera, solo para cuentas que nunca
tocaron ese campo después de registrarse, como la de Doris.
**Corrección**: agregado `"cedula": record.get("cedula", "")` al
diccionario de `login()`. **Prueba real de punta a punta**: registro
nuevo con cédula real (`3057412896`) → confirmado en PocketBase que se
guardó → verificación real del código → login real → `/perfil` muestra
`3057412896` en la fila Cédula (confirmado leyendo el HTML devuelto,
no solo el status code).

**PARTE B -- duplicados de cédula/correo.** Auditado antes de tocar
nada: **ya estaba implementado de verdad**, no había que agregar
nada. `registro_post()` ya hace una consulta real
(`filter=cedula = ...`) antes de crear la cuenta y devuelve "Ya existe
una cuenta registrada con esa cédula." si hay coincidencia; el
`except PocketBaseError` ya distingue `"email" in e.data` de
`"cedula" in e.data` (el fix real de la sección 59) con mensajes
distintos para cada caso, nunca el genérico. **Prueba real**: intento
de registro con la cédula de una cuenta real ya existente → rechazado
con "Ya existe una cuenta registrada con esa cédula."; intento de
registro con el correo de una cuenta real ya existente → rechazado con
"Ya existe una cuenta registrada con ese correo." -- dos mensajes
reales, distintos entre sí, ninguno genérico.

**PARTE C -- campo teléfono nuevo.** No existía nada similar de
sesiones anteriores (`grep` de "telefono"/"phone"/"celular" en toda la
app, cero resultados). Agregado de punta a punta:
- Campo `telefono` (texto, `^[0-9]{10}$`, no requerido a nivel de
  esquema -- mismo criterio que `cedula`) agregado a la colección
  `users` de PocketBase vía su API admin de esquema.
- `auth/registro.html`: input nuevo entre cédula y contraseña, mismo
  patrón visual y de validación HTML5 que cédula.
- `registro_post()`: parámetro `telefono` obligatorio, validado con
  `_TELEFONO_PATTERN` (10 dígitos), incluido en el payload de creación
  y en el contexto de re-render si hay error.
- `login()`: `"telefono": record.get("telefono", "")` agregado al
  diccionario de sesión -- aplicada la misma lección de la Parte A
  desde el primer momento, no después de que alguien lo reporte.
- `perfil.html`: fila nueva "Teléfono" junto a las demás (solo
  exhibición, tal como se pidió -- no se agregó edición de teléfono en
  `/perfil`, que no estaba en el alcance).

  **Prueba real de punta a punta**: registro nuevo con teléfono real
  (`0991234567`) → confirmado guardado en PocketBase → verificación →
  login → `/perfil` muestra `0991234567` en la fila Teléfono.

**PARTE D -- iniciales del avatar por defecto.** Confirmado el bug
reportado: `(user.name or user.email)[:2] | upper` toma los 2
primeros caracteres del string completo ("Doris Paz" → "DO"), no la
inicial de cada palabra. `grep` del patrón (`[:2] | upper`) en toda la
app encontró **4 puntos reales**: `perfil.html`, `base.html` (avatar
del sidebar, visible en todo el sistema), `gerente/empleados.html`
(`e.nombre[:2]`) y `admin/usuarios.html` (`(u.name or u.email)[:2]`).
Ningún otro lugar calcula iniciales por JS (verificado: los modales de
`admin/usuarios.html` que arma JS para editar/ver perfil de usuario no
tienen fallback de iniciales, muestran "Sin foto" en texto).
**Corrección**: función nueva `iniciales()` en `app/templating.py`
(mismo patrón que `avatar_url`/`dashboard_url`, registrada como global
de Jinja) -- separa el string por espacios y toma la primera letra de
las 2 primeras palabras (`"Doris Paz"` → `"DP"`); con una sola palabra
(nombre sin apellido, o el fallback a email) usa sus 2 primeros
caracteres, mismo criterio que ya existía para ese caso. Los 4 puntos
reales cambiados a `{{ iniciales(...) }}`. **Prueba real con 2 usuarios
reales de nombres distintos** (vía `/perfil` autenticado):
`prueba.cedulafix.a@urbanbike.com` ("Prueba CedulaFix") → `"PC"`;
`prueba.telefono.a@urbanbike.com` ("Prueba Telefono") → `"PT"` --
ambos correctos, confirmados leyendo el HTML real devuelto.

**Actualización 16-ago-2026 -- `iniciales()` ya NO existe, reemplazada
por el isotipo.** `iniciales()` fue eliminada por completo de
`app/templating.py` en una sesión posterior no documentada aparte, y
los mismos 4 puntos (`base.html`, `perfil.html`, `admin/usuarios.html`,
`gerente/empleados.html`) ahora muestran el isotipo de UrbanBike
(`/static/img/logo-urbanbike.png`, vía la clase `.avatar-logo-fallback`
en `main.css`, fondo blanco fijo para contraste garantizado también en
tema oscuro) como avatar por defecto en vez de las iniciales. Origen
de la decisión: `docs/Requerimientos_Mejoras_UrbanBike.md`, punto 16
("Isotipo solo... espacios pequeños o cuadrados -- ícono de la
campana/favicon, **avatar del sistema**, marca de agua sutil, spinner
de carga"). Justificación real: mejor contraste garantizado en ambos
temas (el isotipo tiene un color fijo verificado, dos letras de
iniciales heredaban `var(--primary)` y no se habían probado contra
fondo oscuro) y consistencia de marca con el resto de espacios chicos
ya migrados al isotipo (favicon, spinner -- ver sección 68). El bugfix
de cálculo de iniciales de esta PARTE D sigue siendo válido como
historia -- simplemente el mecanismo que corregía ya no es el que usa
el sistema hoy.

**PARTE E -- correo de soporte en `/auth/bloqueado`.** Agregado
`support_email` a `app/config.py` (`SUPPORT_EMAIL` en `.env`, default
`soporte@urbanbike.com`) -- **se usó un correo de marca genérico, no
`SMTP_FROM_EMAIL`** (`sistemasoftwaredev@gmail.com`), porque ese es el
remitente del correo transaccional automático ("no respondas a este
mensaje", ver sección 61), no una casilla real de soporte; mezclar
ambos hubiera sido inconsistente con el pie de correo agregado en la
sección anterior. Pasado como `soporte_email` al contexto de
`bloqueado()` en `app/routers/auth.py` y mostrado en
`auth/bloqueado.html` en un bloque nuevo, **fuera** del
`{% if/elif %}` por rol -- visible para cualquier rol bloqueado
(ciclista, empleado, gerente), además de lo que ya existía para cada
uno. **Prueba real**: cuenta real de prueba
(`prueba.telefono.a@urbanbike.com`) marcada `activo=False` a propósito
vía PocketBase, login real → redirige a `/auth/bloqueado` → confirmado
`mailto:soporte@urbanbike.com` visible en el HTML devuelto, junto al
motivo de bloqueo real. Cuenta restaurada a `activo=True` sin motivo de
bloqueo al terminar la prueba, mismo criterio de limpieza que el resto
de pruebas reales de esta sesión.

**Nota general**: las 5 partes se probaron contra un servidor
`uvicorn` real levantado para la sesión (reiniciado después de cada
cambio de código Python, ya que corría sin `--reload`) y PocketBase
real ya en ejecución -- ninguna prueba fue simulada ni asumida.
Servidor detenido al terminar.

## 63. "Olvidé mi contraseña" con recuperación real por correo (14 de agosto de 2026)

**Auditoría previa (reportada antes de diseñar nada, tal como se pidió)**:
PocketBase sí trae reseteo de contraseña nativo para colecciones tipo
`auth` (confirmado contra el esquema real vía API admin) --
`request-password-reset` / `confirm-password-reset`, con la misma
propiedad de seguridad que se necesitaba (responde igual exista o no
el correo). Mismo criterio: **no se usó**, por 3 razones reales
confirmadas antes de proponer nada: (1) el mailer propio de
PocketBase está apagado (`smtp.enabled: false`, `senderAddress:
support@example.com`, configuración de fábrica nunca tocada), (2) su
`resetPasswordTemplate` es en inglés y vive dentro del panel admin de
PocketBase, fuera de este repo, sin el logo/colores/pie construidos en
la sección 61, y (3) su enlace apunta a la UI interna de administración
de PocketBase (`{APP_URL}/_/#/auth/confirm-password-reset/{TOKEN}`),
no a una pantalla de esta app. Se implementó manual, mismo patrón que
la verificación de correo del registro.

**Cambios:**

- **PocketBase**: 2 campos nuevos en `users` (misma técnica de
  `PATCH /api/collections/users` ya usada para `telefono` en la
  sección 62) -- `codigo_reset` (texto) y `codigo_reset_expira` (date).
- **`app/email_client.py` refactorizado**: se extrajo `_layout_correo()`
  (header con logo cid: + pie, compartido) y `_caja_codigo()` (la caja
  destacada del código) de `_html_codigo_verificacion()`, y se agregó
  `_html_codigo_restablecimiento()` reutilizando ambos -- ya no hay dos
  bloques de ~140 líneas de HTML de correo casi idénticos. También se
  extrajo `_enviar_correo()` (construcción MIME + envío SMTP, antes
  duplicado) y `_pie_texto_plano()` (footer de texto plano compartido).
  Función pública nueva: `enviar_codigo_restablecimiento(destinatario,
  nombre, codigo)`.
- **`app/routers/auth.py`**: `_emitir_codigo_reset()` (mismo patrón que
  `_emitir_codigo()`) y 4 rutas nuevas --
  `GET/POST /auth/olvide` (pedir correo) y
  `GET/POST /auth/restablecer` + `POST /auth/restablecer/reenviar`
  (código + contraseña nueva, con reenvío). `olvide_post()` solo genera
  y envía código si la cuenta existe **y** `verified=True` **y**
  `activo=True` -- una cuenta sin verificar no tiene nada que resetear
  todavía, y una bloqueada no debe poder saltarse `/auth/bloqueado`
  restableciendo su propia contraseña. En **cualquier** otro caso (no
  existe, no verificada, bloqueada) la respuesta es exactamente la
  misma: mismo status, misma URL de redirect, mismo texto ("Si el
  correo existe en nuestro sistema, te enviamos instrucciones para
  restablecer tu contraseña."). `restablecer_post()` valida el código
  con `secrets.compare_digest` y vigencia de 15 min, mismo patrón que
  `verificar_post()`; al confirmar, actualiza `password`/
  `passwordConfirm` vía el cliente admin (igual que hace el registro) y
  limpia `codigo_reset`.
- **UI**: enlace "¿Olvidaste tu contraseña?" bajo el campo de
  contraseña en `auth/login.html`; plantillas nuevas
  `auth/olvide.html` y `auth/restablecer.html`, mismo layout que
  `auth/registro.html`/`auth/verificar.html`.

**Prueba real de los 5 escenarios pedidos** (servidor `uvicorn` real +
PocketBase real, cuentas reales de sesiones anteriores):

1. **Correo real que existe** (`prueba.cedulafix.a@urbanbike.com`):
   `POST /auth/olvide` generó y guardó un código real en PocketBase
   (confirmado leyendo el registro), y `enviar_codigo_restablecimiento()`
   se probó de verdad contra `washingtonapunte123@gmail.com` para
   confirmación visual del diseño (mismo logo/colores/pie que el correo
   de verificación) -- `True`, aceptado por Brevo.
2. **Correo que NO existe**: mismo `status_code`, misma URL de
   redirect y **mismo texto exacto** que el escenario 1 (comparados
   programáticamente, no a simple vista) -- ninguna pista de que la
   cuenta no existe.
3. **Reset real de punta a punta**: código real capturado de
   PocketBase → `POST /auth/restablecer` con ese código → contraseña
   actualizada → `codigo_reset` quedó vacío en PocketBase (de un solo
   uso, confirmado) → login con la contraseña **vieja** rechazado
   (`401`) → login con la contraseña **nueva** exitoso
   (`200`, hasta `/ciclista/dashboard`).
4. **Cuenta bloqueada real** (`prueba.telefono.a@urbanbike.com`
   marcada `activo=False` a propósito): `POST /auth/olvide` devolvió
   la misma respuesta genérica, y `codigo_reset` en PocketBase siguió
   vacío -- confirmado que no se generó ni envió nada. Cuenta
   restaurada a `activo=True` al terminar.
5. **Código vencido y código ya usado, ambos rechazados**: un código
   vencido a propósito (expiración forzada 5 min atrás vía PocketBase)
   devolvió "El código venció. Pide uno nuevo con 'Reenviar código'.";
   un código ya usado (el de la prueba 3, reintentado luego de que ya
   se había generado uno nuevo) devolvió "El código no es correcto.
   Intenta de nuevo." -- mismos 2 mensajes, mismo criterio exacto que
   `/auth/verificar`.

Servidor de prueba detenido al terminar.

## 64. Indicador de carga global: spinner en botones + barra de progreso superior (14 de agosto de 2026)

**Auditoría previa**: cero mecanismos de carga en todo el sistema
(`grep` de "spinner"/"loading"/"cargando"/`@keyframes spin`, ningún
resultado) y `.btn:disabled` tampoco existía en `main.css` -- deshabilitar
un botón hoy no cambiaría nada visualmente. Puntos reales de espera
identificados con números concretos: **59 enlaces de exportación
Excel/PDF** (`<a class="btn ...">`, patrón idéntico en 34 plantillas,
varios consultando ClickHouse sobre los 3.7M viajes reales) y **64
formularios `<form method="post">`** en 34 plantillas, más las
navegaciones de página completa a dashboards pesados
(`gerente/analisis-citibike`, etc.), que un spinner de botón no cubre
por sí solo. `base.html` (heredado por toda pantalla autenticada) ya
tenía el patrón de referencia para esto: 6 scripts compartidos con
delegación de eventos sobre `document` (mismo mecanismo que
`lightbox.js`), pero las 6 pantallas de `auth/` no lo extienden.

**Implementado, mecanismo A + B, ambos globales, un solo archivo nuevo**
(`app/static/js/loading.js`, mismo patrón de delegación que
`lightbox.js` -- cero cambios por plantilla para que funcione):

- **Mecanismo A (spinner + deshabilitado)**: en cualquier `submit` de
  `<form>` (los 64, sin excepción) y en cualquier `<a>` cuyo `pathname`
  termine en `/excel` o `/pdf` (los 59, detectados por patrón de URL,
  no marcados uno por uno). Los formularios se resetean solos porque el
  navegador reemplaza la página entera al llegar la respuesta; las
  exportaciones (que no navegan, es una descarga) se reactivan solas
  tras un tiempo de seguridad fijo (8s) porque no existe un evento de
  navegador que avise "la descarga terminó" para un `<a>` normal.
  Escape hatch: atributo `data-no-loading` en el `<form>` o en el botón.
- **Mecanismo B (barra de progreso superior)**: en clics a enlaces
  internos de navegación real (ej. sidebar), aparece una barra delgada
  arriba que avanza hasta 80% y se destruye sola cuando el navegador
  reemplaza la página -- sin coordinación con el backend. Cubre el
  hueco que A no cubre: la espera de una navegación de página completa
  (dashboards pesados).
- Ambos comparten la misma defensa: `if (e.defaultPrevented) return;`
  al inicio del handler de clic, en fase *bubble* (no *capture*) -- así
  cualquier `preventDefault()` de un handler más específico que ya
  corrió antes (el lightbox del avatar en `base.html`, las pestañas de
  `checklist_devolucion.html`) hace que el clic se ignore
  automáticamente, sin tener que enumerar esos casos a mano.
- **CSS nuevo en `main.css`**: `.btn:disabled` (no existía), `.is-loading`
  (el texto se vuelve `color: transparent` en vez de borrarse con JS
  -- no hay que reconstruir el contenido original del botón después;
  el spinner es un `::after` con su propio `color` redeclarado, si no
  heredaría el `transparent` y también desaparecería) y `#ub-progreso`
  (`position:fixed`, `z-index:300`, `background: var(--primary)` --
  theme-aware automáticamente, sin reglas nuevas por tema).
- **Cobertura**: `<script>` agregado a `base.html` **y a las 6
  plantillas de `auth/`** (login, registro, verificar, olvide,
  restablecer, bloqueado) desde el día uno, según lo pedido -- no se
  dejó ninguna en segundo orden.
- **`data-no-loading` aplicado** a los 3 botones reales que abren
  modales en `admin/usuarios.html` (Editar/Ver perfil/Eliminar) --
  defensivo (ya eran inmunes por construcción, al ser `type="button"`
  fuera de cualquier `<form>`, así que `Mecanismo A` nunca los tocaba),
  pero documenta la intención en el propio HTML y protege contra un
  futuro refactor que los mueva dentro de un formulario.

**Prueba real de los 5 escenarios pedidos** (servidor `uvicorn` real +
Chrome real vía MCP, cuentas de prueba creadas para la ocasión y
eliminadas al terminar -- `prueba.loading.gerente@urbanbike.com`,
`prueba.loading.admin@urbanbike.com`):

1. **Formulario real** (login): clic real en "Iniciar sesión" --
   confirmado por captura y por JS (`disabled: true`,
   `classList` con `is-loading`) que el botón queda deshabilitado con
   el spinner visible, texto oculto.
2. **Exportación real** (Excel de Reportes, cuenta gerente real):
   clic real en "Exportar Excel" -- captura confirma el spinner en el
   botón mientras "Imprimir PDF" (un `<button>`, no exportación)
   sigue intacto al lado; confirmado que el botón vuelve a su estado
   normal solo, sin intervención, pasado el tiempo de seguridad.
3. **Navegación pesada real** (`gerente/analisis-citibike`, 3.7M
   registros reales): clic real en el enlace del sidebar -- confirmado
   por JS (`#ub-progreso` con clase `ub-progreso-avanzar`,
   `background: rgb(30, 134, 189)` = `--primary`, ancho ~80% del
   viewport) y por captura de pantalla (barra azul visible cruzando la
   parte superior).
4. **Modo oscuro y modo claro, mismo criterio de contraste que el
   resto del sistema**: spinner y barra probados y capturados en
   ambos temas -- en oscuro, spinner claro sobre botón azul/gris
   oscuro y barra azul sobre fondo oscuro, ambos con buen contraste;
   repetido en claro con el mismo resultado, sin ningún caso de bajo
   contraste.
5. **Escape hatch real** (`admin/usuarios.html`, cuenta admin real):
   clic en "Editar" (con `data-no-loading`) -- el modal de edición
   abrió instantáneo y confirmado por JS que, de los 78 elementos con
   `data-no-loading` en la página, ninguno tiene la clase `is-loading`
   -- el mecanismo global respeta el escape hatch sin excepción.

Cuentas de prueba de esta sesión eliminadas y servidor detenido al
terminar.

## 65. Dos bugs reales en "olvidé mi contraseña": 500 reproducido con traceback real (ConnectionError sin capturar) + un segundo bug encontrado al reproducir (cliente admin de PocketBase que se "envenena" para siempre) (14 de agosto de 2026)

**Punto de partida**: Washington reportó un "Not Found" en algún punto
del flujo y un "Internal Server Error" (500) reales al probar
"olvidé mi contraseña". Se pidió explícitamente evidencia real, no
suposiciones.

**Reproducción del "Not Found"**: servidor `uvicorn` real levantado con
logs visibles, flujo completo repetido varias veces desde
`/auth/login` con Chrome real -- clic real en "¿Olvidaste tu
contraseña?", registro nuevo verificado, código real de PocketBase,
restablecimiento, login con la contraseña nueva. **No se pudo
reproducir ningún 404 real** en ningún punto: se probaron además
casos límite (`GET /auth/restablecer` sin sesión previa,
`POST /auth/restablecer/reenviar` sin sesión, mayúscula/minúscula y
barra final en las rutas) y los `<form action="...">` reales de las 2
plantillas coinciden exactamente con las rutas de `auth.py`, sin
ningún typo. Se deja documentado con honestidad: **este hallazgo
específico no se confirmó con evidencia real**, a diferencia del 500.
Si vuelve a pasar, hace falta la URL exacta de la barra de direcciones
en el momento exacto.

**Reproducción real del 500**: confirmado el error reportado
deteniendo PocketBase a propósito (`docker compose stop pocketbase`,
reversible, restaurado de inmediato después) y repitiendo
`POST /auth/restablecer` -- **500 real, reproducido en Chrome**.
Traceback real capturado del log del servidor:

```
requests.exceptions.ConnectionError: HTTPConnectionPool(host='127.0.0.1', port=8090):
Max retries exceeded ... NewConnectionError(... [WinError 10061] ...)
  File "app\routers\auth.py", line 422, in restablecer_post
    res = await run_in_threadpool(pb.list_records, ...)
  File "app\db\pocketbase.py", line 84, in list_records
  File "app\db\pocketbase.py", line 109, in _get
    r = self._session.get(self.base_url + path, params=params, timeout=10)
```

**Causa real**: `restablecer_post()` solo capturaba
`except PocketBaseError:` -- un `requests.exceptions.ConnectionError`
(PocketBase inalcanzable, ej. reiniciando junto con el resto de
Docker) **no es una `PocketBaseError`**, así que se colaba como
excepción sin capturar y Starlette devolvía su 500 genérico en texto
plano ("Internal Server Error"), exactamente lo que vio Washington.
Mismo patrón encontrado también en `login()` (`pb.auth_user()`) y en
`verificar_post()` (mismo archivo, misma dependencia externa) --
corregidos los 3 por consistencia, no solo el reportado:
`except (PocketBaseError, requests.exceptions.RequestException)` en
`restablecer_post`/`verificar_post` (mismo mensaje genérico ya
existente, ahora sí lo alcanza); `login()` separado en dos ramas
porque el mensaje de "credenciales incorrectas" sería engañoso para
una falla de conexión real -- mensaje nuevo y distinto ("No se pudo
conectar con el servicio de autenticación..."), status 503.

**Segundo bug real, encontrado en el camino al reproducir la prueba
final** (no estaba en el reporte original, pero bloqueaba la prueba de
punta a punta pedida): `get_admin_client()`
(`app/db/pocketbase.py`) asignaba el cliente a la variable global
`_admin_client` **antes** de autenticar contra PocketBase. Si esa
primera autenticación fallaba (ej. PocketBase caído en el instante
exacto de la primera llamada de todo el proceso), el objeto ya
asignado -- sin token válido -- quedaba cacheado para siempre (el
chequeo `is None` ya daba `False`), y **cada llamada admin posterior
durante toda la vida del proceso** fallaba en silencio (401) sin
reintentar nunca la autenticación real. Reproducido en vivo: tras
apagar PocketBase para probar el 500 de arriba, la siguiente
solicitud real de código de restablecimiento devolvió el mensaje
genérico de siempre pero **nunca generó ni guardó ningún código** --
confirmado consultando el registro real en PocketBase
(`codigo_reset` vacío pese a una respuesta 302 "exitosa"). Corregido
usando una variable local hasta que `auth_superuser()` termine bien, y
solo entonces asignándola a la global -- una falla dispara un
reintento real en la próxima llamada, no un envenenamiento permanente.

**Prueba real de punta a punta tras ambos fixes** (servidor reiniciado
con los 2 archivos corregidos, PocketBase real y saludable, cuenta de
prueba nueva verificada): clic real del mouse en "¿Olvidaste tu
contraseña?" desde `/auth/login` → correo real solicitado → código
real confirmado en PocketBase (ya no vacío) → correo real reenviado a
`washingtonapunte123@gmail.com` para confirmación visual → código
real usado en `/auth/restablecer` → "Contraseña actualizada" → login
con la contraseña **vieja** rechazado, login con la **nueva** exitoso
hasta `/ciclista/dashboard`. Log del servidor de esa corrida completa,
línea por línea: puros `200`/`302`/`304`, cero `ERROR`, cero `404`,
cero `500`. Cuenta de prueba eliminada y servidor detenido al
terminar.

## 66. Verificación pedida sobre la sección 65: mismo hueco en el resto del sistema, y confirmación real de que el cliente admin se recupera solo (14 de agosto de 2026)

**Punto 1 -- ¿el mismo hueco (`except PocketBaseError` sin
`requests.exceptions.RequestException`) existe en otro lado?**
Auditado con `grep` de `except PocketBaseError` en toda la app: antes
de esta sección había **4 apariciones reales, las 4 en
`app/routers/auth.py`** -- `login()`, `verificar_post()` y
`restablecer_post()` (corregidas en la sección 65) más
`registro_post()` (**sin corregir todavía**, mismo hueco real: si
PocketBase está inalcanzable durante el chequeo de cédula duplicada o
la creación de la cuenta, `requests.exceptions.ConnectionError` se
cuela sin capturar igual que en los otros 3). Corregida ahora con el
mismo patrón: rama nueva `except requests.exceptions.RequestException:`
después del `except PocketBaseError as e:` que ya distinguía correo/
cédula duplicados (ese sigue igual, no se tocó su lógica), mensaje
nuevo "No se pudo completar el registro. Intenta de nuevo en un
momento.", status 503.

Revisados también los otros 3 routers reales que llaman a PocketBase
(`gerente.py`, `empleado.py`, `ciclista.py` -- incluida "membresía",
mencionada explícitamente): **ninguno usa el patrón narrow
`except PocketBaseError`** -- todos usan `except Exception:` (más
amplio, ya incluye `ConnectionError` de por sí), así que no comparten
este hueco específico. `admin.py` importa `PocketBaseError` pero no la
captura en ningún `except` real (no es el mismo bug, es una falta de
manejo de errores más general en ese archivo, fuera del alcance de lo
pedido acá).

**Resultado**: los 4 `except PocketBaseError` reales que existen hoy
en todo el sistema ahora capturan también `RequestException`
(`app/routers/auth.py`, líneas de `login`/`registro`/`verificar`/
`restablecer`) -- cero apariciones sin corregir.

**Punto 2 -- ¿el fix de `get_admin_client()` reintenta de verdad, o
solo falla más visible?** Probado en vivo, un solo proceso de servidor
de principio a fin (nunca reiniciado):
1. PocketBase apagado (`docker compose stop pocketbase`) **antes** de
   arrancar un `uvicorn` completamente nuevo -- garantiza que
   `_admin_client` empieza en `None` y que la primera llamada real del
   proceso ocurre con PocketBase caído (el escenario exacto que antes
   envenenaba el singleton para siempre).
2. `POST /auth/olvide` con PocketBase caído → `200`, respuesta
   genérica de siempre, sin 500 (el fix de la sección 65 ya cubre
   esto). Confirmado en PocketBase real que **no** se generó código
   (`codigo_reset` vacío) -- primer intento falló como se esperaba.
3. PocketBase reiniciado (`docker compose start pocketbase`),
   **sin tocar el servidor de la app para nada**.
4. Mismo `POST /auth/olvide`, mismo proceso de servidor (mismo PID en
   el log, nunca reiniciado) → `200` otra vez, pero esta vez
   confirmado en PocketBase real que sí se generó un código real
   (`303723`, con su expiración) -- la segunda llamada admin del
   proceso reintentó la autenticación de cero y funcionó, en vez de
   seguir fallando en silencio para siempre como antes del fix.

Log del servidor de esa corrida (un solo `Started server process`,
nunca un segundo arranque) confirma las dos peticiones limpias, sin
ningún `ERROR` entre medio. Cuenta de prueba eliminada y servidor
detenido al terminar; PocketBase quedó corriendo normal.

## 67. `iniciales() is undefined` reportado con traceback real -- no era un bug del código, sí del proceso de servidor de Washington (14 de agosto de 2026)

**Traceback real que reportó Washington**: `jinja2.exceptions.
UndefinedError: 'iniciales' is undefined`, en `base.html:355`.

**Confirmado leyendo `app/templating.py` directo, no de memoria**:
`iniciales()` **sí** está definida (línea 24) **y sí** está registrada
como global de Jinja (línea 94:
`templates.env.globals["iniciales"] = iniciales`), mismo patrón exacto
que `avatar_url`/`dashboard_url`/`file_url` justo al lado. `git diff`
confirma que esa línea es parte del mismo cambio de la sección 62,
nunca se perdió ni se revirtió -- sigue en el archivo tal cual se
escribió entonces. **No había nada que corregir en el código.**

**Prueba real de que el código de hoy funciona**:
1. `templates.env.from_string('{{ iniciales("Doris Paz") }}').render()`
   contra el objeto `templates` real de la app → `"DP"`, sin
   `UndefinedError`.
2. Servidor `uvicorn` real, cuenta de prueba real con nombre de dos
   palabras ("Doris Paz") → login real → `GET /ciclista/dashboard` →
   `200 OK` (no 500), con `DP` visible en el HTML devuelto del avatar
   del sidebar. Log del servidor: solo `200`/`302`, cero `ERROR`.
   Cuenta de prueba eliminada al terminar.

**Causa real del error que vio Washington**: no es un bug de código,
es un **proceso de servidor viejo**. `templates.env.globals[...]` se
ejecuta una sola vez, al importar `app/templating.py` cuando arranca
el proceso -- si su `uvicorn` seguía corriendo desde antes de la
sección 62 (o desde antes de que ese archivo se guardara con el
registro), su proceso en memoria nunca vio esa línea, sin importar
cuánto tiempo pase, porque el archivo ya no se vuelve a importar
mientras el proceso siga vivo.

**Punto 4 pedido -- ¿`iniciales()` se usa en otro lado?** `grep` en
`app/templates/` confirma **4 usos reales**: `base.html` (el que
truena, sidebar de toda pantalla autenticada), `perfil.html`,
`gerente/empleados.html` y `admin/usuarios.html`. Como es un *global*
de Jinja (no un filtro importado por plantilla), **una sola línea de
registro cubre las 4 automáticamente** -- no hace falta (ni existe)
un arreglo por plantilla.

**Nota 16-ago-2026, para quien lea esta sección después**: todo lo de
arriba describe el bug y su arreglo tal como estaban ese día --
correcto como historia. Pero `iniciales()` **ya no existe** en el
código de hoy: se eliminó de `app/templating.py` en una sesión
posterior y los mismos 4 usos ahora muestran el isotipo de UrbanBike
en su lugar (ver la nota equivalente al final de la PARTE D, sección
62, y sección 68 para el detalle completo). Si algo vuelve a
reportarse como `'iniciales' is undefined`, la causa ya no puede ser
"proceso viejo sin la línea de registro" como en esta sección -- la
función simplemente no está, y el `grep` de este punto 4 hay que
repetirlo contra el código real antes de asumir que sigue vigente.

**¿Washington necesita reiniciar manualmente, o el auto-reload lo
toma solo?** Depende de cómo esté corriendo su servidor:
- Si lo tiene con `uvicorn app.main:app --reload` (el comando real
  documentado en `CLAUDE.md`): el watcher de `--reload` vigila
  cambios en archivos `.py` de todo el proyecto y reinicia el worker
  solo -- **si esa bandera está puesta, ya debería haberse
  recargado solo** hace rato, apenas se guardó `templating.py` en la
  sección 62. Que el error le siga apareciendo ahora sugiere que
  **no** está con `--reload`, o que el proceso que tiene abierto es
  de antes de que ese archivo existiera con la corrección.
- Recomendación real y segura, sin adivinar cuál es su caso: en la
  terminal donde tiene el servidor corriendo, `Ctrl+C` para
  detenerlo, y volver a correr `uvicorn app.main:app --reload` desde
  la raíz del proyecto. Con eso, sea cual sea la causa exacta de su
  proceso viejo, arranca uno nuevo que sí lee `templating.py` tal
  como está hoy en disco -- ya verificado arriba que hoy no tiene el
  bug.

## 68. Isotipo en el spinner + `SUPPORT_EMAIL` corregido + chat interno de soporte (Opción B) (16 de agosto de 2026)

**Contexto de la sesión**: tres pedidos puntuales, sin auditoría amplia
del resto de `Requerimientos_Mejoras_UrbanBike.md` -- (1) el isotipo en
espacios pequeños (punto 16), auditado en una sesión previa el mismo
día: favicon y avatar por defecto ya estaban resueltos (el segundo de
forma no documentada, ver la nota de la sección 62/67 arriba), el
spinner de carga no; (2) el bug real de `SUPPORT_EMAIL` encontrado al
auditar el punto anterior; (3) la mitad pendiente del punto 12 (chat
interno de soporte), con la Opción B ya decidida por Washington sobre
una propuesta previa (formulario + tabla real + respuesta desde panel,
sin WebSockets).

### Parte 1 -- Spinner con el isotipo real (punto 16)

**Corrección aplicada** (`app/static/css/main.css`): el `::after` del
`.btn.is-loading` era un anillo CSS genérico (`border-radius:50%` +
`border-right-color:transparent`). Se reemplazó por el isotipo real
(`/static/img/logo-urbanbike.png`) aplicado como `mask-image`/
`-webkit-mask-image` con `background-color: currentColor` -- **no**
como `<img>` -- para que siga heredando el color por variante/tema
(blanco sobre `.btn-primary`, `var(--text-muted)` sobre `.btn-ghost`)
exactamente como el anillo anterior. Un `<img>` normal no se puede
recolorear así sin generar un asset nuevo, y el pedido fue reutilizar
el existente.

**Prueba real**: computed style vía JS confirma `mask-image` resuelto
al PNG real, `background-color` correcto en ambas variantes, animación
activa. Capturas reales en Chrome: botón "Excel" (ghost, tema claro) y
botón "Nuevo usuario" (primario, tema oscuro) -- en ambos se ve la
silueta de la bici girando, legible, buen contraste, sin blur pese al
tamaño de 15px.

### Corrección de documentación (secciones 62 y 67, mismo día)

`iniciales()` (sección 62 parte D) ya no existe en `app/templating.py`
-- se eliminó en una sesión sin documentar aparte, y los mismos 4
puntos (`base.html`, `perfil.html`, `admin/usuarios.html`,
`gerente/empleados.html`) ahora muestran el isotipo vía la clase
`.avatar-logo-fallback`, citando el punto 16 en el propio código.
Justificación real: mejor contraste garantizado en ambos temas y
consistencia de marca con favicon/spinner. Ambas secciones actualizadas
con una nota que señala esto, sin borrar la historia original (el
bugfix de cálculo de iniciales de esa sesión sigue siendo válido como
historia, solo que el mecanismo que corregía ya no es el vigente).

### Parte 2 -- `SUPPORT_EMAIL` corregido

**Bug real encontrado en la sesión anterior, corregido ahora**: el
default de `app/config.py` (`support_email`) apuntaba a
`sistemasoftwaredev@gmail.com` -- el mismo correo transaccional
("no respondas a este mensaje") que el propio comentario de esa línea
decía evitar. Origen real del bug: `.env.example` tenía
`SUPPORT_EMAIL=sistemasoftwaredev@gmail.com` (copiado mal de
`SMTP_FROM_EMAIL` en algún momento, contradiciendo su propio
comentario), y el `.env` real nunca tuvo `SUPPORT_EMAIL` seteado, así
que caía en ese mismo default equivocado del código.

**Corregido**:
- `app/config.py`: default cambiado a `soporte@urbanbike.com` (mismo
  valor que ya documentaba la sección 62 parte E), comentario ampliado
  con la fecha y el motivo del bug para que no se repita.
- `.env.example`: `SUPPORT_EMAIL=soporte@urbanbike.com`, comentario
  corregido.
- `.env` real: `SUPPORT_EMAIL=soporte@urbanbike.com` seteado
  explícitamente (ya no depende del default silencioso del código).

**Prueba real** (servidor `uvicorn` real, PocketBase real, cuenta
`ciclista@urbanbike.com` bloqueada y restaurada a propósito): los 4
lugares reales que muestran `support_email` confirmados con
`soporte@urbanbike.com` leyendo el HTML devuelto -- `/auth/bloqueado`,
pie de factura de `/ciclista/comprobante/{pago_id}`, pie de factura de
`/ciclista/membresia/comprobante/{id}` (los 2 usos de `ciclista.py`).

### Parte 3 -- Chat interno de soporte, Opción B (punto 12)

**Colección PocketBase `mensajes_soporte`** (creada por
`etl/13_crear_coleccion_soporte.py`, idempotente, mismo patrón que
`etl/12_crear_colecciones_flujo.py`): un renglón por mensaje
(`ciclista_id`, `autor_id`, `autor_rol`, `autor_nombre`, `texto`,
`leido`, `fecha`) -- una conversación = todos los mensajes con el mismo
`ciclista_id`, sin colección de "conversaciones" aparte. El mismo
script agrega `"mensaje_soporte"` al select `notificaciones.tipo`
existente (mismo mecanismo ya usado para `"pago_pendiente"` en el
script 12).

**Repo nuevo** `app/db/mensajes_soporte_repo.py`, mismo patrón que
`notificaciones_repo.py`: `listar_hilo`, `enviar` (crea el mensaje y
dispara la notificación real vía
`notificaciones_repo.notificar_rol`/`notificar_usuario`, sin duplicar
esa lógica), `marcar_leidos`, `contar_no_leidos_ciclista`,
`listar_conversaciones` (agregado en Python -- PocketBase no agrega del
lado del servidor, volumen esperado bajo, mismo criterio que el resto
del ETL/repos).

**Sin infraestructura de tiempo real nueva, dos capas reutilizadas**:
1. Aviso entre páginas: cada mensaje nuevo dispara una notificación
   real (campana), ciclista→Vigilancia como difusión de rol (mismo
   patrón que `orden_asignada`), staff→ciclista como aviso puntual con
   correo (mismo patrón que el resto del sistema) -- reutiliza el
   sondeo de 4s que ya existe en `/auth/estado-sesion`, cero timer
   nuevo para esto. Ícono nuevo `mensaje_soporte` agregado a
   `campana-notificaciones.js` y `main.css`.
2. Hilo abierto: un sondeo propio de 4s
   (`app/static/js/chat-soporte.js`, mismo intervalo e idioma que
   `sesion-tiempo-real.js`) refresca el contenido de la conversación
   mientras la pantalla sigue abierta -- ese timer compartido solo trae
   un conteo, no el texto de los mensajes, así que hacía falta uno
   propio, pero mismo patrón.

**Pantallas**:
- Ciclista: `GET/POST /ciclista/soporte` (ver hilo + enviar), `GET
  /ciclista/soporte/mensajes` (JSON del sondeo). Link nuevo "Soporte"
  en el sidebar.
- Vigilancia (el rol que el documento dice que da soporte):
  `/empleado/vigilancia/soporte` (lista de conversaciones, filtro por
  nombre) y `/empleado/vigilancia/soporte/{ciclista_id}` (hilo +
  responder). Link nuevo en el sidebar.
- Admin: espejo exacto en `/admin/soporte` y
  `/admin/soporte/{ciclista_id}`, mismo repo -- mismo criterio que
  estaciones/tarifas/promociones (Admin ve y actúa igual que el rol
  operativo correspondiente). Link nuevo en el sidebar.
- Componente compartido `componentes/hilo_soporte.html` (burbujas +
  formulario), incluido por las 3 pantallas de detalle -- una sola
  vez, no 3 copias. Sin permiso fino (`requiere_permiso`) nuevo: el
  acceso ya queda cubierto por `AuthMiddleware` (`/ciclista` ->
  ciclista+admin, `/empleado/vigilancia` -> vigilancia+admin, `/admin`
  -> admin), mismo criterio que `admin/bitacora`/`admin/auditoria`, que
  tampoco lo tienen.

**Prueba real de punta a punta** (servidor `uvicorn` real, PocketBase
real, cuenta real `ciclista@urbanbike.com` + cuenta real
`empleado.vig@urbanbike.com`, todo confirmado leyendo HTML/JSON
reales, no simulado):
1. Ciclista abre `/ciclista/soporte` vacío ("Todavía no hay mensajes")
   y manda un mensaje real.
2. Confirmado en la misma operación: aparece en su propio hilo,
   aparece en `/empleado/vigilancia/soporte` (lista de conversaciones,
   "Adrian Guizado", con badge de 1 no leído) y dispara la notificación
   real (`GET /auth/estado-sesion` de Vigilancia devuelve
   `notificaciones_no_leidas: 1`).
3. Vigilancia abre la conversación real (`/empleado/vigilancia/soporte/{id}`,
   200, mensaje visible) y responde.
4. Confirmado sin que el ciclista recargue la página a mano: `GET
   /ciclista/soporte/mensajes` (el mismo endpoint que sondea
   `chat-soporte.js` cada 4s) devuelve los 2 mensajes, incluida la
   respuesta nueva de Vigilancia.
5. Control de acceso real verificado: `ciclista@urbanbike.com` contra
   `/admin/soporte` y `empleado@urbanbike.com` (Operación) contra
   `/empleado/vigilancia/soporte` -- ambos rechazados por
   `AuthMiddleware` (302 a `/dashboard` con el flash de siempre), sin
   tocar nada del middleware.
6. Prueba visual real en Chrome (login real de Vigilancia,
   `empleado.vig@urbanbike.com`): lista de conversaciones con badge de
   no leídos real, hilo con burbujas alineadas (ciclista a la
   izquierda, staff a la derecha), envío real de una respuesta con el
   spinner del isotipo (Parte 1) visible en el botón "Enviar" durante
   el POST, notificación real visible en la campana con su ícono
   nuevo -- probado en tema claro y oscuro, buen contraste en los dos.

**Nota real encontrada durante la prueba, no un bug**: `marcar_leidos()`
marca como leídos los mensajes de `mensajes_soporte` (para que el badge
de la lista de conversaciones baje), pero **no** marca como leída la
notificación de la campana correspondiente -- son dos sistemas de
"leído" independientes a propósito (mismo criterio que ya tiene
`orden_asignada`: abrir la orden asignada tampoco marca sola la
notificación de la campana). El usuario marca la campana leyendo/
haciendo clic ahí, como siempre.

Cuentas de prueba: se usaron las cuentas reales de rol
(`ciclista@urbanbike.com`, `empleado.vig@urbanbike.com`), sin crear
cuentas nuevas. Los mensajes y notificaciones de prueba generados
durante las pruebas 1-6 se borraron al terminar (`mensajes_soporte` y
`notificaciones` de tipo `mensaje_soporte`, 5 filas de cada una en
total entre las dos rondas de prueba) -- la cuenta
`ciclista@urbanbike.com` quedó sin conversación de soporte real, tal
como estaba antes de esta sesión.

## 69. Catálogo de notificaciones auditado — los 2 casos parciales cerrados, 17 quedan documentados para otra sesión (16 de agosto de 2026)

**Contexto**: sesión anterior el mismo día auditó las 22 notificaciones
reales/deseadas del sistema contra el código real (ver el reporte de
esa auditoría). De las 22: 5 ya tenían gancho real completo, 2 eran
parciales (el evento se detectaba pero no notificaba, o iba mezclado
con otra notificación), 2 dependían de una función de stock que no
existe en código, y 13 no tenían ningún punto real de disparo. Hoy se
decidió cerrar **solo los 2 parciales**; el resto queda documentado
abajo, sin construir nada más.

### Parte 1 — Membresía por vencer / vencida

**Aviso anticipado** (`app/db/membresias_repo.py:procesar_por_vencer_hoy()`,
nuevo): umbral **3 días** (`DIAS_AVISO_VENCIMIENTO`). Corre como 5to
paso del mismo DAG horario que ya procesaba vencidas
(`etl/10_procesar_membresias.py`), después del paso de vencidas para
no avisar "por vencer" a una membresía que ese mismo ciclo ya se marcó
vencida. Idempotente de verdad: antes de notificar, busca si ya existe
un aviso `membresia_por_vencer` con el id de esa membresía específica
en el `enlace` -- una membresía dada solo se avisa una vez en su vida,
sin importar cuántas veces corra el DAG dentro de la ventana de 3 días.

**Aviso al vencer** (`procesar_vencidas_hoy()`, extendida): notifica
`membresia_vencida` únicamente cuando la renovación automática
realmente falla (sin método de pago activo) -- una renovación exitosa
no es un evento negativo que amerite avisar.

**Problema real resuelto para poder notificar**: `membresias_repo`
trabaja enteramente con el id de ClickHouse (`usuarios.id`), pero
`notificaciones_repo.notificar_usuario()` espera el id de PocketBase
(el mismo que usa la sesión real). Se agregó
`_resolver_usuario_pocketbase()` (resuelve por email, mismo criterio
que `resolver_id_usuario_por_email()` en sentido inverso) -- si un
usuario de seed no tiene cuenta real de PocketBase, se cuenta aparte
(`sin_cuenta_real`) y no rompe el resto del lote.

**Prueba real** (cuenta real `ciclista@urbanbike.com`, sin editar
directo salvo lo estrictamente necesario para simular el paso del
tiempo):
1. Se activó una membresía real nueva vía `membresias_repo.activar()`
   (el mismo camino real que usa `/ciclista/membresia/pagar`) -- no se
   reusó la membresía activa vieja porque un chequeo más de cerca
   reveló que ya no era la vigente real de Adrian (la había cancelado
   el 11-ago, y esa cancelación es más reciente que la activación del
   09-ago -- el propio criterio de "fila más reciente por fecha_inicio"
   ya la había reemplazado correctamente).
2. Se adelantó `fecha_fin` a 2 días vía `ALTER ... UPDATE` (columna
   fuera de la clave de orden de `membresias`, sin riesgo de
   duplicación) -- no hay otra forma real de simular el paso de varios
   días.
3. `procesar_por_vencer_hoy()` → `{revisadas: 1, avisadas: 1}`.
   Confirmado en `GET /notificaciones` autenticado como Adrian real, y
   visualmente en la campana (Chrome real): "Tu membresía está por
   vencer" con ícono ámbar. Segunda corrida inmediata → `avisadas: 0`
   (idempotente, confirmado).
4. Se desactivó temporalmente el método de pago simulado principal de
   Adrian (único edit directo no evitable, para forzar la rama real de
   "no se pudo renovar" sin esperar 30 días) y se corrió
   `procesar_vencidas_hoy()` → `{revisadas: 1, renovadas: 0,
   marcadas_vencidas: 1}`. Confirmado en `/notificaciones` y en la
   campana real: "Tu membresía venció" con ícono rojo, junto al aviso
   anterior.
5. Limpieza completa al terminar: membresía(s) de prueba, pago y
   factura reales generados por la activación, notificaciones de
   prueba borradas; método de pago reactivado. Estado final de Adrian
   verificado idéntico al de antes de la prueba (`estado_actual()` →
   la misma fila `cancelada` del 11-ago que ya tenía).

### Parte 2 — Infracción como tipo propio

**Separado** en `app/routers/empleado.py` (`vig_inspeccion_registrar`):
la notificación `infraccion` ahora es su propia llamada a
`notificaciones_repo.notificar_usuario()`, inmediatamente después de la
de `falla` -- el cargo por daños se queda exclusivamente en el mensaje
de `falla` (tal como se pidió, "independiente del cargo por daño"), la
de `infraccion` solo describe la infracción en sí y enlaza a
`/ciclista/infracciones` en vez de `/ciclista/pagos`.

**Prueba real de punta a punta**, camino real completo (mismo patrón
que sesiones anteriores probaron el checklist de devolución):
ciclista real (Adrian) reserva `UB-004` real → Vigilancia real
(Miguel Torres) la recibe (`/vigilancia/devolver`) → Vigilancia
registra la inspección real con el ítem "Freno trasero" marcado con
falla y `cargo_danos=$8.00`. Resultado confirmado en
`GET /notificaciones` de Adrian: **3 notificaciones separadas**,
`infraccion` ("Se registró una infracción en tu cuenta: ... Freno
trasero...", sin mención del monto), `falla` ("Se detectaron fallas...
Se generó un cargo por daños de $8.00") y `pago_pendiente` (del cobro
real del viaje) -- las 3 con ícono y color propios, ninguna mezclada
con otra. Limpieza completa: inspección, infracción (ClickHouse y
PocketBase), pago, viaje y las 3 notificaciones de prueba borrados;
bicicleta `UB-004` restaurada a `disponible` vía el repo real.

### Both: 3 tipos nuevos de notificación

`etl/14_ampliar_tipos_notificacion.py` (nuevo, mismo patrón idempotente
que 12/13) agregó `membresia_por_vencer`, `membresia_vencida` e
`infraccion` al select `notificaciones.tipo` de PocketBase. Íconos y
colores agregados en `campana-notificaciones.js`/`main.css`: ámbar
(`#F59E0B`) para el aviso anticipado, rojo (`#EF4444`, mismo tono que
`falla`/`penalizacion`) para vencida e infracción.

### Las 17 notificaciones que quedan sin gancho real — referencia para otra sesión

**13 sin ningún punto real de disparo** (no existe el evento en código,
no solo falta la llamada a `notificar_*`):

1. Ciclista — viaje iniciado (`reservar()` en ciclista.py no notifica).
2. Ciclista — pago rechazado (`op_pagos_rechazar_transferencia` pone
   `estado=rechazado` pero nunca notifica).
3. Ciclista — promoción nueva activa (`promociones_crear` en
   gerente.py no notifica a nadie).
4. Ciclista — devolución validada (`vig_devolver` solo notifica si hay
   pago pendiente o recargo, nunca "tu devolución fue validada" por sí
   sola cuando no hay ninguno de los dos).
5. Operación — cobro pendiente de verificar (ni el flujo de efectivo ni
   el de transferencia notifican al crear el estado pendiente).
6. Operación — bicicleta requiere rebalanceo (no existe ni el concepto
   -- rebalanceo es una acción manual sin historial ni umbral).
7. Vigilancia — devolución pendiente de validar (`finalizar()` del
   ciclista no notifica a Vigilancia).
8. Vigilancia — reporte de falla (no aplica: Vigilancia es quien
   detecta/reporta la falla, no hay otro actor que le reporte una a
   ella).
9. Vigilancia — bicicleta lista para confirmar disponibilidad (el
   único punto que mueve una bici a "disponible" es la propia
   certificación de Vigilancia sobre el flujo legacy de PocketBase --
   no notifica).
10. Mantenimiento — orden certificada pendiente de reparar (ese estado
    no existe en el modelo de datos actual, ni en `ordenes_repo` real
    ni en el flujo legacy de certificación).
11. Admin — cuenta bloqueada automáticamente (el auto-bloqueo real
    existe -- infracciones ≥3, `empleado.py` -- pero no notifica a
    Admin; y sigue siendo estructuralmente inalcanzable en la
    práctica, ver sección 45 -- **deliberadamente no se cerró hoy**,
    a diferencia de membresía/infracción, porque depende de esa
    decisión de negocio pendiente, no de agregar una llamada a
    `notificar_*`).
12. Admin — registro público nuevo (`registro_post` en auth.py no
    notifica).
13. Admin — actividad crítica en auditoría (no existe el concepto de
    "crítico" -- `registrar_auditoria()` registra todo al mismo nivel).

**2 que dependen de una función que no existe todavía** (el esquema
real de `repuestos` sí tiene `stock_actual`/`stock_minimo`, pero
ningún código de la app las lee ni las usa -- `repuestos` hoy solo es
un campo de costo en dólares dentro de una orden de mantenimiento, no
hay consumo de inventario real):

14. Operación — inventario bajo stock.
15. Mantenimiento — repuesto bajo el mínimo.

**Los 2 parciales de la auditoría anterior, confirmados cerrados hoy**
(no forman parte de la lista de pendientes):
16. Ciclista — membresía por vencer/vencida -- cerrado en la Parte 1
    de esta sección.
17. Ciclista — infracción registrada -- cerrado en la Parte 2 de esta
    sección.

**Ciclista — cargo por daño**: ya tenía gancho real desde antes
(cubierto dentro del mensaje de `falla` cuando `cargo_danos > 0`),
confirmado que sigue así después de separar `infraccion` hoy -- nunca
fue parte de la lista de pendientes, no es uno de los 22 originales
contados aparte.

**13 (sin gancho) + 2 (dependen de repuestos) + 2 (parciales, ya
cerrados) = 17**, el número exacto que se pidió documentar. Quedan
aquí con su motivo real exacto para que la próxima sesión no tenga que
re-auditar desde cero.

## 70. Auditoría real de la ventana de gracia de 5h (punto 10/13) -- ya estaba implementada, sin documentar; único hueco real: la vista en vivo (16 de agosto de 2026)

**Contexto**: Washington retomó el proyecto después de un cambio de
cuenta por límite de tokens, pidiendo una auditoría de impacto y una
propuesta de rediseño para la ventana de gracia de 5h antes de
implementar nada -- según él, el flujo cobraba de forma continua desde
`finalizar viaje` hasta la validación de Vigilancia, contradiciendo
`docs/Requerimientos_Mejoras_UrbanBike.md` (puntos 10 y 13). La
auditoría del código real reveló algo distinto: **una sesión anterior
sin documentar ya había construido el rediseño completo**, incluyendo
partes de los puntos 1, 11, 12 y 13 enteros -- solo que nunca se
escribió aquí, y (según `git status`) tampoco se comiteó. No se
encontró ningún archivo de spec/plan para esta fase en
`docs/superpowers/plans/` (solo existe el de fase 1, validaciones,
15-ago) pese a que el código (`ciclista.py:1025`) cita uno que no
existe en disco -- probablemente la sesión que lo escribió se quedó
sin tokens antes de guardarlo o documentarlo, el mismo patrón por el
que Washington cambió de cuenta esta vez.

**Lo que ya estaba construido y funcionando (confirmado con código,
luego con prueba real)**:
- `empleado.py:vig_devolver()` (líneas 1524-1643): calcula
  `retraso_min = max(0, (ahora - fecha_fin_reportada) - 300)` -- 5h
  (300 min) de gracia real desde que el ciclista reportó la
  devolución, no desde que Vigilancia confirma. `recargo_demora` se
  guarda en un campo propio de `pagos`, separado de `subtotal`, nunca
  mezclado.
- `ciclista.py:_construir_factura_pago()` (línea 1019) +
  `componentes/factura.html`: la factura ya muestra el recargo como
  línea propia, *"Recargo por demora en la devolución (>5h)"*, tal
  como pide el punto 11.
- `codigos_descuento_repo.py` + `ciclista.py:finalizar()`: código de
  descuento por buena conducta (10%/20% si ≥5 viajes completados) ya
  se genera al reportar la devolución sin infracciones activas.
- Notificación `penalizacion` ya se dispara con el monto real del
  recargo cuando corresponde.

**El único hueco real encontrado**: la vista en vivo que ve el
ciclista (`ciclista/viaje_activo.html`) y Vigilancia
(`empleado/vigilancia/devoluciones.html`) mientras el viaje espera
validación **no refleja nada de este diseño**. Sigue usando
`costoEnVivo()` (`static/js/costo-en-vivo.js`), que crece sin parar
desde `fecha_inicio` del viaje completo (ni siquiera desde que se
reportó la devolución), sin ventana de gracia ni separación de
recargo -- y el texto fijo en ambas pantallas dice *"el costo sigue
corriendo hasta que Vigilancia confirme la entrega física"*,
contradiciendo lo que de verdad se cobra al final. El cálculo real
(backend) es correcto; lo que el usuario **ve** mientras espera, no.
No se tocó nada de esto todavía -- queda pendiente para la próxima
sesión, con el diseño de la corrección ya acordado con Washington
(ver más abajo).

**Prueba real de punta a punta** (16 de agosto de 2026, contra la app
corriendo en `127.0.0.1:8000`, PocketBase y ClickHouse reales, cuenta
real `wacho@urbanbike.com` como ciclista y `empleado.vig@urbanbike.com`
como Vigilancia, vía requests HTTP autenticados con CSRF real -- no
mocks):

1. **Escenario dentro de gracia** (`UB-006`): reservar → finalizar →
   Vigilancia valida a los pocos segundos. Pago real creado:
   `subtotal=$0.07`, `recargo_demora=0`, `monto_total=$0.07`. Correcto:
   sin demora, sin recargo.
2. **Escenario fuera de gracia** (`UB-007`): reservar → finalizar →
   como esperar 5h reales no es viable, se adelantó `fecha_inicio` y
   `fecha_fin` del viaje 6h hacia atrás vía PocketBase directo (mismo
   criterio ya usado en la sección 69 para simular paso de tiempo,
   nunca hay otra forma real de probarlo) → Vigilancia valida. Pago
   real creado: `subtotal=$0.07`, `recargo_demora=$4.53`
   (≈60.4 min de retraso × $4.5/h), `monto_total=$4.60`. Notificación
   real confirmada: *"Se aplicó un recargo de $4.53 por demora en la
   devolución (más de 5h...)"*. Pagado con tarjeta de pruebas real
   (`4242 4242 4242 4242`) y factura HTML confirmada con las dos
   líneas separadas (*"Tarifa base"* $0.07 + *"Recargo por demora en
   la devolución (>5h)"* $4.53) y `TOTAL $4.60`.
3. **Limpieza completa al terminar**: los 2 pagos, 2 viajes, 3
   notificaciones y 2 códigos de descuento generados por la prueba se
   borraron; `UB-006` y `UB-007` restaurados a `disponible` en su
   estación original. Estado final de `wacho@urbanbike.com` verificado
   idéntico al de antes de la prueba (1 viaje histórico previo intacto,
   1 pago pendiente de $0.15 preexistente sin tocar).

**Nota aparte, no resuelta hoy**: `ciclista@urbanbike.com` tiene un
viaje real en `pendiente_validacion` (`UB-004`, sin fecha reciente de
esta sesión) que no fue tocado durante esta auditoría -- probablemente
otro resto sin limpiar de la misma sesión no documentada que construyó
todo esto. Queda ahí para que la próxima sesión decida si es dato real
o limpieza pendiente, sin asumir nada sin confirmar con Washington.

**Decisión acordada con Washington**: no hacía falta un rediseño desde
cero -- el alcance real era corregir `costo-en-vivo.js` y los dos
templates que lo usan para que la vista en vivo muestre: el subtotal
congelado desde `fecha_inicio` hasta `fecha_fin` (si ya se reportó la
devolución) en vez de seguir contando contra `fecha_inicio` para
siempre, un contador de recargo aparte que solo empieza a correr
pasadas las 5h desde `fecha_fin`, y el texto de ambas pantallas
actualizado para dejar de decir "el costo sigue corriendo" sin
matices. Alcance acotado (bounded), sin tocar la lógica de negocio ya
construida y ya probada arriba. **Implementado y probado en esta misma
sesión** (ver Parte 2 abajo), no quedó pendiente.

### Parte 2 -- corrección de la vista en vivo, implementada y probada (16 de agosto de 2026)

**Cambios reales**:
- `static/js/costo-en-vivo.js`: nueva `costoDetallado(fechaInicioISO,
  fechaFinISO, precioHora)`, con `MINUTOS_GRACIA_DEMORA = 300`
  hardcodeado a propósito -- debe coincidir siempre con el mismo
  número hardcodeado en `empleado.py:vig_devolver()` (ninguno de los
  dos lee `tarifas.minutos_gracia`/`recargo_minuto` todavía; esos
  campos del editor de tarifas del gerente, sección 21, siguen sin
  conectarse a ningún cálculo real -- se deja anotado, fuera de
  alcance de hoy). Devuelve `{subtotal, recargoDemora, enGracia,
  minutosParaRecargo}`; si `fechaFinISO` está vacío (viaje todavía
  `activo`), el subtotal sigue el reloj normal contra `fecha_inicio`
  sin gracia (no aplica todavía). Se eliminó `costoEnVivo()` (los 2
  call sites que la usaban ya no existen -- reemplazados por
  `costoDetallado()`, sin dejar código muerto).
- `ciclista/viaje_activo.html`: el KPI "Costo acumulado" pasó a
  "Costo del viaje" y muestra el subtotal (ya no crece para siempre);
  nuevo KPI "Recargo por demora" (oculto con `display:none` mientras
  `recargoDemora === 0`). El banner de `pendiente_validacion` y el
  texto bajo el formulario de devolución ahora reflejan la gracia real
  (cuenta regresiva en horas/minutos mientras dura, aviso distinto una
  vez pasada).
- `empleado/vigilancia/devoluciones.html`: la celda "Monto en vivo"
  ahora trae también `data-fin` (antes solo tenía `data-inicio`, el
  hueco real que hacía imposible calcular la gracia del lado de
  Vigilancia) y se separó en dos líneas -- el monto total en la
  primera, y debajo el desglose (`"incluye $X de recargo por
  demora"` o `"en gracia -- Xh Ymin restantes"`). Texto de la sección
  actualizado con el mismo criterio.

**Prueba real** (mismas cuentas reales `wacho@urbanbike.com` y
`empleado.vig@urbanbike.com`, bicicleta real `UB-005`, servidor
`uvicorn` real sin `--reload` -- se confirmó que los estáticos y
templates Jinja2 sirven el cambio sin reiniciar):
1. Reservar → finalizar → HTML real de `viaje_activo.html` confirmado
   con `VIAJE.fecha_fin` poblado, el bloque `#kpi-recargo` presente en
   el DOM, y el banner con su `id` nuevo -- dentro de la gracia.
2. Se adelantaron `fecha_inicio`/`fecha_fin` del viaje 6h hacia atrás
   (mismo criterio de simulación real ya usado en la Parte 1 y en la
   sección 69) y se releyó `viaje_activo.html`: `VIAJE.fecha_fin`
   reflejaba la hora retrasada, tal como la leería `costoDetallado()`
   en el navegador real.
3. Réplica exacta de la fórmula de `costoDetallado()` corrida en
   Python contra los timestamps reales (no hay herramienta de
   navegador/captura en esta sesión, así que se verificó la aritmética
   directamente en vez de un screenshot): predijo
   `subtotal≈$0.02, recargo≈$5.56`. Vigilancia validó la devolución
   real inmediatamente después: pago real creado con
   `subtotal=$0.09, recargo_demora=$5.57, monto_total=$5.66` --
   coincide, con una diferencia de $0.07 explicada por un hallazgo
   real y menor: `vig_devolver()` redondea la duración a un mínimo de
   1 minuto (`max(1, int(...))`), mientras que la vista en vivo usa
   fracciones de hora exactas. Para viajes reales (minutos/horas) la
   diferencia es de fracciones de centavo, irrelevante en la práctica
   -- no se corrigió, anotado por honestidad.
4. Limpieza completa: pago, viaje, 3 notificaciones y 1 código de
   descuento generados por esta ronda borrados; `UB-005` restaurada a
   `disponible`. Estado final de `wacho@urbanbike.com` verificado
   idéntico al de antes (solo el viaje histórico de la Parte 1 y su
   pago pendiente preexistente, sin tocar).

**Limitación real de esta verificación**: no se pudo confirmar
visualmente en un navegador real (Chrome, como sí se hizo en la
sección 68) porque esta sesión no tiene herramienta de
navegador/captura de pantalla disponible -- la próxima sesión con esa
herramienta debería hacer una pasada visual rápida de
`viaje_activo.html` (banner + KPI nuevo) y `devoluciones.html` (celda
de dos líneas) en tema claro y oscuro, aunque la lógica ya está
probada con datos reales end-to-end.

## 71. Hallazgo suelto -- el panel de mapa de `/ciclista/alquilar` muestra un precio distinto al de la tarjeta principal para la misma bicicleta (16 de agosto de 2026)

**Encontrado de pasada** auditando la Prioridad 3 del spec de modalidad
de tarifa real (sección aparte, `docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md`)
-- no es parte de ese trabajo, se documenta aquí por separado a
pedido de Washington para no mezclarlo.

`ciclista/alquilar.html` tiene **dos caminos independientes que
muestran precio para la misma bicicleta**, con datos de origen
distintos:
1. La tarjeta principal del catálogo (`{% for bici in catalogo_bicicletas %}`),
   alimentada por `_catalogo_bicicletas()` (`ciclista.py:165-292`) --
   lee `urbanbike_operativa.tarifas` (ClickHouse), por categoría, con
   promociones aplicadas. Correcto y completo.
2. El panel que aparece al hacer clic en un pin del mapa (`bicicletaCard()`,
   JS, `alquilar.html:203-286`) -- usa `tarifaPara(bici.tipo)`
   (`alquilar.html:189-192`), que busca en `TARIFAS`
   (`tarifas_json`, poblado en `ciclista.py:492` desde la colección
   **vieja de PocketBase** `tarifas`): solo precio member, sin
   categoría, sin promoción, sin día/semana.

**Consecuencia real**: para la misma bicicleta, el precio que se ve en
la tarjeta del catálogo (con promo aplicada, por categoría) puede no
coincidir con el que se ve en el panel del mapa (siempre el precio
"member" plano de PocketBase, sin importar la categoría real ni si hay
promoción activa) -- mismo patrón de "dos fuentes de verdad" que ya
documentó la sección 21 para el editor del Gerente, aquí sin
documentar hasta hoy.

**No corregido todavía** -- queda pendiente para cuando se implemente
el spec de modalidad de tarifa real (que de todos modos migra
`ciclista.py:alquilar()` fuera de la colección vieja de PocketBase
`tarifas` por otro motivo, Prioridad 3 de ese spec) o, si se prefiere
antes, como una corrección aislada: hacer que `bicicletaCard()` lea el
precio ya resuelto de `catalogo_bicicletas` (mismo dato que ya llega al
template) en vez de recalcularlo con `tarifaPara()`/`TARIFAS`.

**Corregido como parte de la Tarea 4 del plan de modalidad de tarifa
real, 16 de agosto de 2026.** `alquilar.html` ahora expone
`CATALOGO = {{ catalogo_bicicletas | tojson }}` y `tarifaPara(codigo)`
busca por `codigo` en ese mismo arreglo (`x.precio_hora_member`), en
vez de `TARIFAS`/`tarifas_json` (colección vieja de PocketBase, ya
retirada de `ciclista.py:alquilar()`). Panel de mapa y tarjeta
principal leen ahora la misma fuente (`_catalogo_bicicletas()`), así
que ya no pueden mostrar precios distintos para la misma bicicleta.
Verificado en vivo: para `UB-001` (categoría Estandar), tanto
`data-precio-hora` de la tarjeta como `tarifaPara('UB-001')` del panel
de mapa devuelven `3.83`. De paso se encontró y corrigió un bug
relacionado en el filtro `tojson` (`app/templating.py`): no serializaba
`date` (campo `exclusiva_hasta` de `catalogo_bicicletas`) -- se agregó
`default=str` a ese `json.dumps()`.

## 72. Plan de mejoras V2, Prioridad 0 -- Tareas A1 y B1-B6 completadas y revisadas, viven en un worktree aislado, NO en `main` todavía (17-18 de agosto de 2026)

**Ubicación real del trabajo**: todo lo de esta sección se ejecutó en el
git worktree `.claude/worktrees/plan-mejoras-v2-p0` (rama
`worktree-plan-mejoras-v2-p0`), creado con consentimiento explícito de
Washington vía `superpowers:subagent-driven-development` sobre el plan
`docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md`. El checkout
principal (`main`, lo que corre normalmente en `:8000`) **todavía tiene
el código viejo** -- nada de esto está fusionado. Ledger completo,
brief y report de cada tarea, y el diff exacto revisado en cada gate:
`.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/` dentro del worktree
(`progress.md`, `task-*-brief.md`, `task-*-report.md`,
`review-<base>..<head>.diff`).

**Task A1 (punto 0.1) -- completa, commit `3e2bf2c`.** Restaura el
congelamiento del subtotal en `fecha_fin` para la modalidad `hora`
(`empleado.py:vig_devolver()` + `costo-en-vivo.js`), revirtiendo la
Tarea 7/9 del plan `2026-08-16-modalidad-tarifa-real` que lo había
roto sin reconfirmar (ver auditoría que motivó este plan). **Revisor
independiente real, verificado leyendo su transcript completo**: no
se limitó a leer código -- re-ejecutó la fórmula vieja y la nueva
contra el viaje real `UB-009`, dos corridas con 72s reales de
diferencia (fórmula vieja: $122.82 → $122.88, moviéndose; fórmula
nueva: $109.26 las dos veces, congelada), confirmó por `curl` que el
servidor real sirve el JS corregido, y confirmó por PocketBase que
los 5 viajes/1 pago/2 cuentas de prueba de la verificación E2E del
implementador fueron borrados. **Veredicto: Approved, 0 Critical, 0
Important, 1 Minor diferido** (comentario viejo sin corregir en
`viaje_activo.html:~162-171`, fuera del alcance de las 4 archivos de
esta tarea, anotado para una tarea futura).

**Tasks B1-B6 (punto 0.4, 6 de los 8 ganchos de notificación) --
completas, cada una con su propio revisor y `review clean` según
`progress.md`:**
- B1 `679b94f` -- 8 tipos nuevos en `notificaciones.tipo`
  (`etl/19_ampliar_tipos_notificacion_ronda2.py`, idempotente; renombrado
  desde `etl/17_...` por colisión de numeración con `etl/17_eliminar_tarifas_pocketbase.py`).
- B2 `2481ad3` -- ciclista notificado al iniciar viaje.
- B3 `0907853` -- ciclista notificado si se rechaza su transferencia.
- B4 `39c78ac` -- ciclistas notificados de promoción nueva.
- B5 `951bf39` -- ciclista notificado cuando Vigilancia valida la
  devolución.
- B6 `6e16267` -- Operación notificada de cobro pendiente de
  verificar (efectivo/transferencia).

**Esta lista de "pendiente" quedó desactualizada casi de inmediato -- corregida en la sección 73.**
El trabajo real de B7 a C2 se hizo el mismo 18-ago-2026, en una sesión de ejecución
`subagent-driven-development` cuyo ledger (`.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/progress.md`,
dentro del worktree, no comiteado a `main`) nunca se resumió en este documento hasta ahora. Ese
ledger es la fuente real: B7, B8, B9, C1 y C2 (+ 1 ronda de fix de C2) están completos, cada uno con
commit real y revisor independiente (verdicto "review clean" registrado por tarea), salvo B7 que
Washington aceptó sin revisor separado (ver progress.md línea 70). Ver sección 73 para el detalle
verificado de B9 y C1 específicamente, a pedido de Washington tras notar que ese cierre no le había
llegado.

**Hallazgo operativo real, repetido 6 veces en esta sesión de
ejecución (B2 a B6)**: el auto-reload de `uvicorn --reload`
(`watchfiles`) logueaba `"Reloading..."` pero **no siempre respawneaba
el worker** -- confirmado cada vez comparando el PID/`StartTime` del
worker antes y después vía `Get-CimInstance`/PowerShell, no solo por
el código de estado HTTP. No es el mismo mecanismo que el hallazgo de
la sección 51 (`taskkill //PID` de git-bash no matando el proceso) --
aquí el proceso de reload ni siquiera lo intenta. Washington decidió,
cada una de las 6 veces, mantener `--reload` y reiniciar
manualmente por incidente (autorización explícita antes de tocar
cualquier proceso -- regla añadida a mitad de sesión tras un intento
no autorizado de `Stop-Process` del implementador de A1, ver
`progress.md` línea 28-34) en vez de cambiar de estrategia. Sigue sin
resolverse de raíz.

## 73. Cierre real de B9 y C1, pedido explícitamente por Washington tras notar que nunca le llegó (19-ago-2026)

Washington notó que la sesión anterior pasó de reportar trabajo a "C2 completo" sin
que le llegara el cierre de B9 (notificación a Admin de registro público) ni de C1
(campo `grupo_reserva_id`). Investigación real de esta sesión: **ambas tareas sí
tenían commit, verificación E2E real y revisor independiente** -- registrado en
`.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/progress.md` (líneas 78-84) y en
`task-B9-report.md`/`task-C1-report.md`, dentro del worktree. El problema no era que
faltara evidencia: era que ese ledger nunca se resumió aquí, en el documento que
Washington realmente lee. Corrección de la sección 72 hecha arriba.

**Verificación fresca repetida en esta sesión (19-ago-2026), a pedido explícito de
Washington, independiente de la del 18-ago-2026:**

**B9 -- notificación a Admin de registro público nuevo.** Commit `54c725c`, rama
`worktree-plan-mejoras-v2-p0` (**no en `main`**). `POST /auth/registro` real
(`prueba.b9.verificacion@urbanbike.test`, cédula `1798765432`) → `302` (éxito) →
notificación real creada en PocketBase (`rol_destino="admin"`,
`tipo="registro_nuevo"`, mensaje con nombre/correo correctos) → confirmado visible
llamando al endpoint real que usa la campana de la UI, `GET /notificaciones`, con
una sesión real de `admin@urbanbike.com` (login real vía `POST /auth/login`,
contraseña de prueba documentada `Urbanbike123!`, no adivinada). Limpieza
confirmada: notificación y usuario de prueba borrados, 0 rastros en
`notificaciones`, `users` ni `auditoria` tras la limpieza. Revisor independiente:
sí (verdicto "review clean", progress.md línea 80).

**C1 -- campo `grupo_reserva_id` en `viajes`/`pagos`.** Commit `d57922f`, misma
rama (**no en `main`**). Corrida real #3 de `etl/18_agregar_grupo_reserva.py`
contra PocketBase real: `viajes: los campos nuevos ya existen, sin cambios` /
`pagos: los campos nuevos ya existen, sin cambios` -- confirmado además por schema
que el campo aparece exactamente 1 vez en cada colección (sin duplicados).
Idempotencia confirmada por tercera vez (las corridas #1 y #2 ya estaban
documentadas del 18-ago-2026). Revisor independiente: sí (verdicto "review clean",
progress.md línea 84).

Checkboxes de B9 (Steps 1-4) y C1 (Steps 2-3) marcados `[x]` en
`docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md` (ambas copias, `main` y
worktree) solo con esta evidencia en mano -- no antes.

**Regla nueva de Washington para el resto de este plan (Grupo C, C3 en adelante):**
ninguna tarea se reporta como "completa" sin las dos cosas juntas -- evidencia de
ejecución real Y revisión (propia o independiente, según el tamaño del cambio). Si
una de las dos falta, debe decirse explícitamente en el resumen, nunca dejarse
implícito. Precedente ya visible en este mismo plan: B7 se cerró sin revisor
independiente (Washington lo aceptó explícitamente, progress.md línea 70) -- ese
tipo de excepción es válido, pero debe quedar dicho, no callado.

**Nota aparte -- reconciliada el 19-ago-2026 (ver sección 74):** `docs/HOJA_DE_RUTA.md`
en `main` y la copia dentro del worktree habían divergido (la del worktree quedó
atrás, sin las secciones 72-73). Confirmado con diff ignorando fin de línea que la
copia del worktree era subconjunto exacto de esta -- cero contenido único, nada que
fusionar -- así que se copió esta versión sobre la del worktree tal cual, a pedido
explícito de Washington de no dejarlo para el cierre del plan.

## 74. Task C3 completa -- selección múltiple real en el catálogo, con 3 bugs reales encontrados y corregidos antes de comitear (19-ago-2026)

Commit real: `a992af6` ("feat: agregar seleccion multiple (carrito) al catalogo
para reservar varias bicicletas a la vez"), rama `worktree-plan-mejoras-v2-p0`,
**no en `main`**.
Archivos: `app/templates/componentes/tarjeta_bicicleta.html`,
`app/templates/ciclista/alquilar.html`, `app/static/css/main.css` (el tercero no
estaba en el brief original -- necesario para que el checkbox fuera visible, ver
abajo).

**El código del brief ya estaba escrito y sin commitear** de una sesión anterior
(Steps 1-3 del Task C3). Esta sesión lo verificó de punta a punta en vez de darlo
por bueno:

**Bug 1 -- checkbox invisible.** `.tarjeta-bicicleta` no tenía `position:relative`
en `main.css`, así que el checkbox de selección (`position:absolute;top:10px;
right:10px`) escapaba a un ancestro lejano de la página (aparecía cerca de la
topbar, confirmado con `getBoundingClientRect()` real en el navegador: el checkbox
medía top=10,left=1499 en viewport, no dentro de la tarjeta). Encontrado durante la
verificación visual en un navegador real, antes de que llegara la revisión
independiente. Corregido agregando `position:relative` a `.tarjeta-bicicleta`.

**Bug 2 -- checkbox chocando con el badge de estado.** Ya con `position:relative`,
el checkbox (top:10px;right:10px) quedaba pegado al badge "Disponible"/"En
uso"/etc (`.tarjeta-bicicleta-estado`, también top:12px;right:12px), superpuesto
visualmente. Corregido moviendo el checkbox a `top:44px`, debajo de esa fila de
badges.

**Bug 3 -- barra de carrito visible desde la carga de la página.** Encontrado por
la revisión independiente (`code-review`, nivel medium), no por la verificación
manual: `#barra-carrito` tenía `display:none` y, más adelante en el mismo atributo
`style`, `display:flex` -- en CSS, la última declaración de una misma propiedad en
un mismo atributo gana, así que la barra en realidad SIEMPRE se renderizaba visible
(con "0 bicicletas seleccionadas") desde que se carga `/ciclista/alquilar`, no solo
cuando hay algo seleccionado. La verificación manual de esta sesión vio la barra
visible en la primera captura de pantalla y no lo marcó como bug -- la revisión
independiente sí lo detectó. Corregido quitando el `display:flex` duplicado; el JS
(`actualizarBarraCarrito()`) ya controla `style.display` directamente.

**Hallazgo adicional de la revisión (no un bug de comportamiento, código muerto y
engañoso):** los 5 `data-*` que proponía el brief original en `.tarjeta-bicicleta`
(`data-id`, `data-estacion-id`, `data-estacion-nombre`, `data-lat`, `data-lng`)
nunca se llenan -- `_catalogo_bicicletas()` en `ciclista.py` no trae esos campos
por unidad (confirmado leyendo la función completa) y el JS del carrito nunca los
lee: usa `BICICLETAS`/`ESTACIONES` (el mismo JSON que ya alimenta el mapa de la
página) con el mismo criterio de match por nombre normalizado que
`bicicleta_detalle()` usa en el backend. El docstring del componente afirmaba,
incorrectamente, que esos campos se "enriquecían en `ciclista.alquilar()`" -- nunca
pasó. Se eliminaron los 5 atributos vacíos y ese comentario; quedó solo
`data-codigo`, que sí se usa.

**Verificación E2E real, en dos partes:**
1. **Navegador real** (Chrome vía automatización): login real, checkboxes visibles
   y clicables tras el fix del Bug 1/2, selección real actualiza la barra de
   carrito correctamente, resolución de datos por bicicleta
   (`datosBiciParaCarrito()`) confirmada contra los datos reales de
   `BICICLETAS`/`ESTACIONES` de la página.
2. **Submit real del formulario, vía clic de DOM real** (`element.click()`) en vez
   de un clic de mouse sintetizado por el SO -- el clic de mouse real dejó de
   entregarse de forma fiable a mitad de esta verificación (3 intentos con
   coordenadas y con `ref` de la extensión de Chrome, uno de ellos disparó un
   `alert()` real del navegador que congeló la pestaña por completo; la pestaña se
   cerró y no se reintentó indefinidamente, siguiendo la guía de no insistir más de
   2-3 veces con lo mismo). El clic de DOM real disparó el mismo listener de
   `click` que un clic de mouse real habría disparado, y desde ahí todo fue tráfico
   HTTP real: `POST /ciclista/reservar-grupo` real → 2 viajes reales creados
   (`UB-010`, `UB-008`) con el mismo `grupo_reserva_id` no vacío → ambas bicicletas
   `en_uso` → 2 notificaciones `viaje_iniciado` reales → redirect real a
   `/ciclista/viaje-activo/{id}` de la primera bicicleta del grupo.

**Cuenta de prueba:** se registró una cuenta ciclista desechable nueva
(`prueba.c3.carrito@urbanbike.test`) en vez de reutilizar `ciclista@urbanbike.com`,
porque esa cuenta compartida ya tenía 3 viajes activos/pendientes acumulados de
sesiones anteriores (`UB-009` pendiente_validacion, `UB-010` activo -- el mismo
huérfano ya señalado en la sección 72 como "flagged for Washington to decide", no
tocado --, `UB-004` pendiente_validacion) y el tope `MAX_VIAJES_ACTIVOS=4` hubiera
bloqueado la reserva de 2 bicicletas más sin que fuera un problema real de C3.

**Limpieza confirmada:** 2 viajes de prueba borrados, ambas bicicletas restauradas
a `disponible`, 2 notificaciones `viaje_iniciado` borradas, y también la
notificación `registro_nuevo` que generó el registro de la cuenta de prueba
desechable (efecto colateral esperado del gancho de la Task B9 -- se había pasado
por alto en la primera limpieza y se encontró al re-verificar 0 rastros). Usuario
de prueba borrado. 0 rastros confirmados en `viajes`, `notificaciones`, `users` y
`auditoria`.

**Revisor independiente:** sí, `code-review` (nivel medium) sobre el diff completo
antes de comitear -- encontró el Bug 3 y el hallazgo de código muerto de arriba.
Ambos corregidos y reverificados contra el HTML real servido antes del commit.

Checkboxes de Task C3 (Steps 4-6) marcados `[x]` en
`docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md` (ambas copias) solo con
esta evidencia en mano.

## 75. Task C4 completa -- factura única real para reserva grupal, ciclo E2E de punta a punta con pago real (19-ago-2026)

Commit real: `865a176` ("feat: emitir una sola factura para una reserva grupal
cuando todas sus bicicletas estan pagadas"), rama `worktree-plan-mejoras-v2-p0`,
**no en `main`**. Archivos: `app/routers/empleado.py` (denormaliza
`grupo_reserva_id` en el pago), `app/routers/ciclista.py`
(`_construir_factura_grupo()` + `GET /ciclista/comprobante-grupo/{grupo_reserva_id}`),
`app/templates/ciclista/comprobante.html` (no estaba en el brief original --
necesario, ver hallazgos abajo).

**2 hallazgos reales encontrados leyendo el template antes de confiar en el brief**
(no llegaron por la revisión independiente, se encontraron auditando
`comprobante.html`/`componentes/factura.html` antes de escribir el endpoint,
siguiendo la misma disciplina que ya pedía la propia "nota para quien implemente"
del brief):
1. `es_grupo` no estaba conectado a nada en el template -- el enlace "Descargar
   PDF" (individual) seguía apareciendo siempre, apuntando a
   `/ciclista/comprobante/{{ pago.id }}/pdf` con `pago.id` = `grupo_reserva_id`
   (no un id de `pagos` real -- hubiera dado 404 al hacer clic). Corregido
   envolviendo ese enlace en `{% if not es_grupo %}`.
2. El `title="Factura de reserva grupal"` que pasa el endpoint no hacía nada --
   los blocks `{% block title %}`/`{% block page_title %}` del template estaban
   fijos en "Comprobante de Pago", sin leer ningún context var. Corregido
   haciéndolos condicionales a `es_grupo`.

También se agregó `soporte_email=settings.support_email` al contexto de
`comprobante_grupo()` (el brief no lo incluía) porque `componentes/factura.html`
lo usa en el pie de página -- sin esto, el pie de la factura de grupo hubiera
quedado con el contacto de soporte vacío.

**Desviación deliberada de simplificación:** el IVA de la factura de grupo se
acumula desde `factura_individual.iva` (ya calculado una vez por
`_construir_factura_pago()`) en vez de recalcularlo aparte con un segundo
`facturas_repo.desglosar_iva()` como proponía el brief -- mismo resultado, una
sola fuente de verdad.

**Verificación E2E real, ciclo completo de punta a punta, sin atajos:**
1. Cuenta ciclista de prueba desechable registrada y verificada (no
   `ciclista@urbanbike.com`, ya con viajes activos acumulados de sesiones
   anteriores -- mismo criterio que la sección 74).
2. Reserva grupal real de 2 bicicletas (UB-010 + UB-008, evitando UB-001 que es
   `bloqueada_exclusiva`) vía `POST /ciclista/reservar-grupo` (Task C2/C3).
3. Ambos viajes finalizados por el ciclista (`POST /ciclista/finalizar`).
4. Ambas devoluciones validadas por una cuenta Vigilancia real
   (`empleado.vig@urbanbike.com`, `POST /empleado/vigilancia/devolver/{id}`) --
   2 pagos reales creados, ambos con `grupo_reserva_id` correctamente
   denormalizado (confirmado leyendo los registros reales en PocketBase).
5. **Confirmado el caso "todavía no está lista" dos veces**: con 0 de 2 pagos
   pagados, y de nuevo con 1 de 2 pagados (justo el caso explícito que pedía el
   brief) -- ambas veces `GET /ciclista/comprobante-grupo/{id}` redirige a
   `/ciclista/historial` con el flash correspondiente.
6. Pagados ambos pagos con la tarjeta de pruebas real (`4242 4242 4242 4242`,
   Luhn válido).
7. Con los 2 pagados, `GET /ciclista/comprobante-grupo/{id}` devuelve `200` con
   la factura real: título "Factura de reserva grupal" (confirma el fix del
   hallazgo 2), ambas líneas presentes (`UB-010 — Tarifa por día`,
   `UB-008 — Tarifa por día`), enlace de PDF individual correctamente ausente
   (confirma el fix del hallazgo 1), Subtotal $55.65 + IVA $8.35 = TOTAL $64.00
   -- verificado a mano contra la suma real de los 2 `monto_total`
   ($35.20 + $28.80 = $64.00).

**Limpieza confirmada:** 2 pagos, 2 viajes y 9 notificaciones reales borradas
(registro_nuevo, viaje_iniciado ×2, devolucion_pendiente_validar ×2,
devolucion_validada ×2, pago_aprobado ×2 -- los 9 disparados por los ganchos
reales de las Tasks B2/B5/B7/B9 a lo largo del ciclo completo, no solo los que
esta tarea toca directamente), 2 bicicletas restauradas a `disponible`, usuario
de prueba borrado. 0 rastros confirmados en `viajes`, `pagos`, `notificaciones`,
`users` y `auditoria`.

**Revisor independiente:** sí, `code-review` (nivel medium) sobre el diff
completo antes de comitear -- encontró 1 hallazgo real: `_construir_factura_grupo()`
hace una consulta a ClickHouse por pago del grupo (patrón N+1, vía
`_construir_factura_pago()`) en vez de una sola consulta batched. **Diferido
explícitamente, no corregido**: el tope real de tamaño de grupo es
`MAX_VIAJES_ACTIVOS=4`, así que el peor caso son 4 consultas secuenciales en una
pantalla de bajo tráfico (se visita una vez por grupo, después de pagar todo);
corregirlo bien requeriría tocar la lógica de reconciliación de segmentos de
`_construir_factura_pago()` (Important #1/#2 de su propio docstring), que el plan
pide explícitamente reutilizar sin reescribir. Queda anotado para una futura
sesión de optimización si el tamaño de grupo real crece más allá de 4.

Checkboxes de Task C4 (Steps 1-6) marcados `[x]` en
`docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md` (ambas copias) solo con
esta evidencia en mano.

## 76. Task C5 completa -- PDF real de la factura de grupo, 3 rondas de revisión, 2 bugs reales corregidos (19-ago-2026)

Commit real: `ec73bde` ("feat: agregar descarga PDF de la factura de reserva
grupal"), rama `worktree-plan-mejoras-v2-p0`, **no en `main`**. Archivos:
`app/routers/ciclista.py` (`GET /ciclista/comprobante-grupo/{grupo_reserva_id}/pdf`
+ helper compartido nuevo), `app/templates/ciclista/comprobante.html` (no estaba
en el brief original -- necesario, ver Bug 1 abajo).

**Desviación real aplicada desde el inicio** (antes de que llegara cualquier
revisión): el brief proponía `nombre_archivo=f"factura-grupo-{grupo_reserva_id[:8]}"`
para `generar_factura_pdf()` -- sin extensión `.pdf`, inconsistente con los otros 2
llamadores reales de esa función (`comprobante_pago_pdf()`, `membresia_comprobante_pdf()`,
ambos con `.pdf` y prefijo `urbanbike_`). Corregido a
`urbanbike_factura_grupo_{grupo_reserva_id[:8]}.pdf` antes de la primera
verificación, no como fix posterior.

**2 bugs reales encontrados por la revisión independiente, ambos corregidos:**

1. **Botón "Descargar PDF" desconectado del endpoint nuevo.** La Task C4 había
   envuelto ese botón en `{% if not es_grupo %}` porque C5 todavía no existía --
   correcto en su momento. Al completar C5, ese `if` seguía ahí sin actualizar:
   el endpoint nuevo quedaba compilado, comiteado, y **completamente inalcanzable
   desde la UI real** (código muerto). Corregido: el botón ahora apunta a
   `/ciclista/comprobante-grupo/{{ pago.id }}/pdf` cuando `es_grupo` es verdadero,
   o al PDF individual en caso contrario. Reverificado siguiendo el `href` real
   del botón (no solo llamando al endpoint directo) hasta una descarga real de
   218KB con magic bytes `%PDF-` reales.
2. **Validación duplicada verbatim entre `comprobante_grupo()` (HTML, Task C4) y
   `comprobante_grupo_pdf()` (PDF, esta tarea).** ~20 líneas idénticas (fetch de
   viajes/pagos, ownership, "todos pagados") copiadas sin extraer -- riesgo real
   de que una futura sesión cambie la regla de "grupo completo" en una vista y no
   en la otra. Extraído a `_grupo_reserva_facturable(pb, grupo_reserva_id,
   user_id) -> (pagos_grupo, viajes_por_id, flash_o_None)`, compartido por las
   dos rutas. Reverificado con un ciclo E2E completo tras el refactor, incluyendo
   un caso nuevo que no se había probado antes: acceso al PDF con 0 de 2 y con 1
   de 2 pagos pagados (ambas veces redirige correctamente).

**Verificación E2E real, 3 ciclos completos, cada uno con cuenta ciclista
desechable nueva:**
1. Ciclo 1: reserva real (UB-010+UB-008) → devolución validada por Vigilancia
   real → 2 pagos reales con tarjeta de pruebas → `GET .../pdf` directo →
   PDF real confirmado con `pdftotext` (poppler, ya instalado en el sistema):
   ambas líneas de bicicleta, TOTAL correcto, `Content-Disposition` con nombre de
   archivo `.pdf` real.
2. Ciclo 2 (tras el fix del Bug 1): mismo ciclo completo, esta vez extrayendo el
   `href` real del botón "Descargar PDF" del HTML servido y descargando por ESE
   link (no por la URL construida a mano) -- confirmado que coincide con la URL
   esperada y que la descarga real funciona.
3. Ciclo 3 (tras el fix del Bug 2): mismo ciclo, más 2 verificaciones nuevas
   explícitas: `GET .../pdf` con 0 de 2 pagado (antes de finalizar ningún viaje)
   y con 1 de 2 pagado -- ambas redirigen correctamente a `/ciclista/historial`
   con el flash de "todavía no está lista", igual que ya se había confirmado
   para la vista HTML en la Task C4 pero nunca para el endpoint del PDF
   específicamente.

**Limpieza confirmada las 3 veces:** pagos, viajes y bicicletas de cada grupo de
prueba borrados/restaurados; 11 notificaciones reales borradas por ciclo (mismo
conjunto que en la sección 75: registro_nuevo, viaje_iniciado ×2,
devolucion_pendiente_validar ×2, devolucion_validada ×2, pago_pendiente ×2,
pago_aprobado ×2); usuario de prueba borrado cada vez. 0 rastros confirmados tras
cada limpieza.

**Nota aparte -- hallazgo de la 3ª ronda de revisión, fuera del alcance de esta
tarea, no corregido aquí:** la 3ª pasada de `code-review` no encontró nada nuevo
dentro del diff real de C5 (confirmado con `git diff --stat`: el diff sin
comitear en ese momento no tocaba `reservar_grupo()` en absoluto) -- amplió el
alcance por su cuenta y volvió a encontrar, sobre código YA comiteado de la Task
C2, 3 hallazgos:
1. `reservar_grupo()` notifica "viaje iniciado" por bicicleta DENTRO del loop de
   creación, antes de que se confirme el grupo completo -- si una bicicleta
   posterior del mismo lote falla y dispara el rollback (`_revertir_reserva_grupal()`),
   las notificaciones ya enviadas a las bicicletas anteriores no se pueden
   recuperar. Nuevo, no estaba documentado antes.
2. `reservar_grupo()` duplica ~50 líneas de validación de `reservar()`
   (bicicleta exclusiva/membresía, infracciones activas, pagos pendientes/rechazados)
   en vez de compartir un helper. Nuevo, no estaba documentado antes.
3. Si `codigos_descuento_repo.marcar_usado()` ya aplicó el cambio del lado de
   PocketBase pero la excepción llega igual (ej. timeout justo después), el
   rollback borra los viajes pero nunca desmarca el código de descuento -- queda
   quemado para una reserva que en los hechos nunca se concretó. **Este ya era
   conocido**: quedó anotado explícitamente en el fix round 1 de C2 (ver sección
   72/`progress.md` línea 88) como "flagged for the final review's triage" --
   nunca se le dio ese triage final. Esta pasada lo volvió a encontrar de forma
   independiente.

Ninguno de los 3 se corrigió en este commit -- son C2, no C5, y tocar
`reservar_grupo()` de nuevo sin que Washington lo pida específicamente se sale
del alcance que se confirmó para esta sesión. Quedan documentados aquí para que
Washington decida si abrir una ronda de fix dedicada a C2.

Checkboxes de Task C5 (Steps 1-4) marcados `[x]` en
`docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md` (ambas copias) solo con
esta evidencia en mano.

## 77. Ronda de fix dedicada para los 3 huecos reales de reservar_grupo() (Task C2) que encontró la 3ª ronda de revisión de la Task C5 (19-ago-2026)

Commit real: `940be8c` ("fix: reservar_grupo() -- diferir notificaciones hasta
grupo confirmado, revertir codigo de descuento en rollback, compartir validacion
con reservar()"), rama `worktree-plan-mejoras-v2-p0`, **no en `main`**. Archivos:
`app/routers/ciclista.py`, `app/db/codigos_descuento_repo.py`.

**Origen real de estos 3 hallazgos**: no salieron de un nuevo audit de la Task
C2 -- salieron sin que se pidieran, en la 3ª pasada de `code-review` de la Task
C5 (sección 76), que amplió su alcance por su cuenta más allá del diff real de
C5 y volvió a leer `reservar_grupo()` (ya comiteado desde la Task C2). Washington
pidió explícitamente abrir una ronda de fix dedicada para los 3, antes de seguir
con C6.

**Auditoría real antes de arreglar** (leyendo `_crear_viaje()`, `reservar()`,
`_revertir_reserva_grupal()` y `reservar_grupo()` completos, no solo el
resumen del hallazgo): confirmado que `notificaciones_repo.notificar_usuario()`
**sí manda un correo real** (`app/email_client.py:enviar_notificacion()`), no
solo el registro de la campana -- así que el hallazgo #1 era real y no exagerado:
un correo real de verdad no se puede "revertir" borrando el registro de
PocketBase después.

**Fix #3 primero, es el que toca dinero real (pedido explícito de Washington,
no dejarlo pasar de nuevo):** `codigos_descuento_repo.py` gana
`revertir_uso(id_codigo)`, la contraparte exacta de `marcar_usado()` -- resetea
`usado=False, fecha_usado="", viaje_id_uso=""` (los mismos valores por defecto
que ya usa `generar()`, así que es seguro llamarla incluso si el código nunca
llegó a marcarse usado -- no hay diferencia observable entre "nunca se marcó" y
"se marcó y se revirtió"). `reservar_grupo()` la llama en el bloque `except`,
justo después de `_revertir_reserva_grupal()`, cada vez que `codigo_valido` no
es `None` -- sin intentar adivinar si `marcar_usado()` alcanzó a correr o no
antes de la excepción, porque no hace falta saberlo.

**Fix #1:** el loop de creación de viajes de `reservar_grupo()` ya NO llama a
`notificaciones_repo.notificar_usuario()` por cada bicicleta dentro del loop.
Las notificaciones (con su correo real) se mandan en un loop nuevo, **después**
de `registrar_auditoria()` del éxito completo -- con el grupo entero ya
confirmado. `_revertir_reserva_grupal()` conserva su limpieza de notificaciones
huérfanas como red de seguridad defensiva (docstring actualizado explicando por
qué ya no debería encontrar nada que borrar en el camino normal).

**Fix #2:** ~50 líneas de validación idénticas entre `reservar()` y
`reservar_grupo()` (bicicleta exclusiva de suscriptor, infracciones activas,
pagos pendientes/rechazados) extraídas a `_validar_reserva_comun(user, user_id,
bicicleta_codigos)` -- devuelve el mensaje de error real o `None`, sin tocar la
sesión ni redirigir (eso lo sigue haciendo cada llamador). Deja fuera a
propósito la validación de modalidad y el tope `MAX_VIAJES_ACTIVOS` -- cada
función ya los revisaba antes de este punto, en el mismo orden relativo de
siempre, y el mensaje del tope difiere entre las dos (una bicicleta vs. "ya
tienes X, intentas agregar Y").

**Verificación E2E real, con datos reales, 4 pruebas:**
1. **Fix #1, prueba clave**: `reservar_grupo()` con una `bicicleta_id` inválida
   como segunda bicicleta de un lote de 2 (la primera, UB-008, real y válida).
   Confirmado: 0 viajes creados para el ciclista de prueba, UB-008 restaurada a
   `disponible`, y **0 notificaciones** para ese ciclista -- antes del fix,
   la bicicleta 1 ya habría disparado una notificación real (y un correo real)
   antes de que la bicicleta 2 fallara.
2. **Fix #3, prueba directa del repo contra PocketBase real**: generar un código
   real (`codigos_descuento_repo.generar()`), marcarlo usado
   (`marcar_usado()`), confirmar que `obtener_valido()` ya no lo encuentra
   (correctamente quemado), llamar `revertir_uso()`, confirmar que
   `obtener_valido()` **vuelve a encontrarlo** -- prueba real de que el código
   queda genuinamente utilizable de nuevo, no solo que los campos cambiaron.
3. **Camino feliz individual** (`reservar()`): una bicicleta real (UB-008),
   reserva exitosa, 1 notificación real creada -- confirma que el helper
   compartido no rompió el caso de una sola bicicleta.
4. **Camino feliz grupal con código de descuento real** (`reservar_grupo()`):
   2 bicicletas reales (UB-008 + UB-010) + un código de descuento real generado
   para el mismo ciclista. Confirmado: 2 viajes creados con el mismo
   `grupo_reserva_id`, el descuento (15%) aplicado solo a la PRIMERA bicicleta
   del lote (nunca duplicado), el código marcado `usado=True` con el
   `viaje_id_uso` correcto, y 2 notificaciones reales creadas -- confirma que
   diferir las notificaciones no rompió el camino feliz (se siguen mandando,
   solo que después del loop en vez de durante).

**Limpieza confirmada las 2 veces que se creó una cuenta de prueba:** pagos,
viajes y códigos de descuento de prueba borrados; bicicletas restauradas a
`disponible` (incluida una que un ciclo de devolución real había dejado en
`mantenimiento` pendiente de inspección -- estado real esperado del flujo, no
un bug, restaurada a `disponible` para no dejar el fixture de prueba en un
estado distinto al que tenía antes de esta sesión); notificaciones borradas (5
en el segundo ciclo); usuarios de prueba borrados. 0 rastros confirmados.

**Revisor independiente:** sí, `code-review` (nivel medium) sobre el diff
completo -- **0 hallazgos**. Confirmó explícitamente que el orden de las
validaciones extraídas es idéntico al original, que `revertir_uso()` es segura
de llamar incondicionalmente, y que `notificar_usuario()` traga sus propias
excepciones de punta a punta (así que mover el orden auditoría→notificación no
puede dejar un rastro de auditoría inconsistente).

Los 3 hallazgos de la sección 76 quedan **cerrados**, no solo documentados.

## 78. Cierre del Plan de Mejoras V2 P0 -- Tasks C6-C7, revisión final de rama completa, y 3 deudas conocidas que quedan deliberadamente fuera de alcance (19-ago-2026)

Continúa la sección 77. Fuente real: `.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/progress.md`
y `final-review-fix-report.md`, dentro del worktree (no comiteados, gitignored). Con esto,
**los 17 tasks del plan (A1, B1-B9, C1-C7) están completos** y la revisión final de la rama
completa también, con dos rondas de fix ya aplicadas y verificadas.

### Task C6 -- enlazar la factura grupal desde `pagos.html` (commit `b1970a8`)

Tarea con historial accidentado: el implementador inicial (Haiku) falló 3 veces seguidas
intentando el E2E real, cada vez con un bloqueo distinto (encoding de formularios en Python →
manejo de sesión/CSRF → cuenta sin verificar rechazada en login), y su reporte final admitía
"testing was deferred" mientras igual marcaba "task COMPLETE" -- el primer revisor detectó la
contradicción y devolvió **Needs fixes (Important)**. El controlador comprobó por su cuenta
contra el servidor real que el 3er bloqueo alegado ("el registro no persiste en PocketBase")
era **falso** -- los 3 fallos fueron error del implementador, no del código. Un 4to
implementador (Sonnet) completó entonces el ciclo E2E real de punta a punta: registro →
verificación (bypass) → login → reserva grupal real (UB-008+UB-010) → finalización →
validación de Vigilancia → pago de una bicicleta → HTML real verificado en ambos estados →
pago de la segunda → HTML final verificado → PDF real descargado (200, `application/pdf`,
218549 bytes) → limpieza confirmada.

Incidente aparte: `task-C6-brief.md` apareció en 0 bytes (corrupción accidental de un archivo
de scratch, no versionado) -- restaurado desde una lectura anterior de la misma conversación,
cruzado contra el diff real del commit `b1970a8` para confirmar consistencia.

**Re-revisión, veredicto "ADDRESSED WITH DOUBT":** como el código de plantilla no cambió en
esta ronda final, no había diff nuevo que revisar -- se despachó un re-revisor a auditar la
credibilidad del reporte de E2E del 4to implementador contra el código real, no a revisar un
diff. Verificó 5/5 afirmaciones de forma independiente (nombres de campos de formulario,
redirects, literales de transición de estado, lógica de guarda, HTML exacto renderizado en
ambos estados de pago incluido el texto del tooltip) y encontró coincidencia byte a byte con
el router y el template reales; además verificó por su cuenta la fórmula del sufijo del
comprobante (`pago_id[-4:].upper()`) contra dos IDs de pago distintos, obteniendo los mismos
valores que el reporte afirmaba. **La duda que dejó registrada es puramente estructural, no
una sospecha concreta**: un revisor de texto no puede re-ejecutar peticiones HTTP, así que no
puede descartar con 100% de certeza que el reporte sea una reconstrucción muy cuidadosa en vez
de una ejecución real -- la misma limitación categórica de cualquier revisión basada en texto
en todo este plan, no algo específico de C6. Se aceptó como suficiente para cerrar la tarea
porque no se encontró ninguna inconsistencia real en 5 verificaciones cruzadas más una prueba
de valor derivado (una barra más alta que la mayoría de los "review clean" del resto del
plan), y porque volver a correr el ciclo completo en vivo por segunda vez solo para cerrar ese
límite estructural costaba otro ciclo E2E entero por una ganancia marginal de certeza sobre un
código ya confirmado correcto por dos revisores independientes.

**Corroboración adicional, más allá de esa re-revisión**: la revisión final de rama completa
(ver abajo) volvió a evaluar la evidencia de C6 al analizar el hallazgo real que sí encontró
en `pagos.html`, y confirmó explícitamente que ese hallazgo *no contradice* la evidencia E2E
de C6 (el reporte de C6 solo probó el caso de grupo completamente pagado) -- un tercer
revisor independiente, con otro enfoque, también trató la narrativa E2E de C6 como
internamente consistente con el código real. Las dos rondas de fix posteriores (más abajo)
volvieron a ejercitar el mismo flujo de pagos con datos reales sin encontrar ninguna
contradicción con lo que C6 había descrito.

2 minores heredados textualmente del código de la propia tarea (no desviación del
implementador), diferidos: falta `or "—"` de respaldo en el comprobante pendiente de un pago
agrupado; `rechazado` renderiza la misma copia que `pendiente`. Ambos quedaron cerrados en la
ronda de fix final (ver abajo).

### Task C7 -- aviso de viaje grupal en `viaje-activo` (commits `b1970a8..0cc8a90`)

Despachada directo a Sonnet con la receta E2E ya probada de C6 (sesión persistente, CSRF real,
bypass de verificación, bicicletas no exclusivas conocidas). Éxito al primer intento: un viaje
grupal real (UB-008+UB-010) mostró el aviso nuevo en `viaje-activo`; un viaje individual real
no lo mostró. Revisor explícitamente instruido a escrutar la credibilidad de la evidencia E2E
dado el historial de C6 -- encontró IDs reales, un hash de `grupo_reserva_id` real, códigos
HTTP reales y HTML consistente con el diff real; **Approved, 0 hallazgos**.

### Revisión final de la rama completa (Opus, base `3c9568e..0cc8a90`, 21 commits)

Veredicto inicial: **"Ready to merge? With fixes."** 0 Critical, 3 Important, 5 Minor.

**Important #1 (bloqueante real, ya corregido en 2 rondas):** `pagos.html:96-101` ataba el
enlace a la factura grupal al `estado` del pago INDIVIDUAL, no a si el grupo estaba completo
-- en la ventana de pago parcial el ciclista que ya pagó podía perder el único enlace a su
propio comprobante si el viaje hermano nunca se validaba. Ronda 1 (commit `0049e1a`) lo
corrigió parcialmente pero una re-revisión encontró un hueco residual: `grupos_completos` solo
mira pagos que YA existen, y un pago solo existe cuando Vigilancia valida esa devolución
concreta -- en el caso ordinario de devoluciones escalonadas (no simultáneas) el único pago
existente podía marcar el grupo "completo" antes de tiempo, mostrando un enlace grupal muerto.
Washington autorizó una ronda de fix adicional, fuera del proceso normal de "una sola ronda"
(commit `100b088`): el enlace individual ahora es incondicional siempre que `p.estado ==
'pagado'`, y el enlace/insignia de grupo es puramente aditivo. Re-revisión independiente
confirmó **ADDRESSED**, verificado directo contra el archivo: la ruta que renderiza el enlace
y la que el endpoint exige ya no pueden desacoplarse, la clase de falla queda estructuralmente
imposible. Evidencia E2E real ejercitó específicamente la ventana de devolución escalonada que
había roto la ronda 1 (47/47 aserciones), con limpieza confirmada.

### Deuda conocida -- 3 seguimientos deliberadamente fuera de alcance de este plan

El revisor de la rama completa marcó estos 3 puntos como hallazgos reales pero explícitamente
fuera del alcance de lo que este plan prometía entregar -- no se corrigieron a propósito, y
quedan documentados aquí para que no se pierdan (mismo problema que pasó antes con el cierre
de B7, ver sección 73):

1. **Estado de lectura compartido en notificaciones masivas.**
   `notificaciones_repo.notificar_rol("ciclista", ...)` (usado desde B4, promociones nuevas)
   crea una única notificación de broadcast para un rol público sin acotar -- el primer
   ciclista que hace "marcar todas leídas" la oculta para todos los demás ciclistas también.
   Patrón preexistente al plan, este es el primer broadcast real a un rol masivo. Decisión
   de diseño real (¿lectura por-usuario vs. compartida?) que le corresponde definir a
   Washington, no una corrección mecánica.
2. **Condición de carrera al marcar una bicicleta "en uso".** `_crear_viaje()` marca una
   bicicleta `en_uso` sin re-chequear disponibilidad justo antes del `UPDATE` -- condición de
   carrera preexistente, no introducida por este plan, pero `reservar_grupo()` (Task C2)
   multiplica el radio de impacto a N bicicletas en una sola solicitud en vez de 1. Nota
   menor asociada, contingente a este punto: `_revertir_reserva_grupal()` restaura las
   bicicletas a `disponible` de forma incondicional (correcto mientras no exista la
   condición de carrera; solo corregible junto con el punto de fondo).
   **Resuelto el 21-ago-2026, ver sección 79** -- resultó ser más grave de lo descrito acá:
   no era solo una ventana de carrera fina, era la AUSENCIA total de chequeo (reproducido de
   forma determinística, sin ninguna concurrencia real).
3. **Ruta muerta `comprobante_alquiler_pdf`.** `app/routers/ciclista.py:1644`
   (`comprobante_pago_pdf`) y `:2043` (`comprobante_alquiler_pdf`) registran la misma ruta
   `/ciclista/comprobante/{...}/pdf`. FastAPI resuelve siempre al primer handler registrado,
   dejando el segundo permanentemente inalcanzable. Preexistente al plan, encontrado durante
   la 2da ronda de fix de Important #1; no afecta ningún enlace que este plan cree o toque.

Ninguno de los 3 fue actuado unilateralmente -- corresponde a Washington decidir si y cuándo
priorizarlos como trabajo aparte.

**Estado del plan: RESUELTO.** Los 17 tasks completos, el único hallazgo con severidad de
bloqueo real de la revisión final confirmado cerrado de forma estructural (no solo probado
alrededor del caso), listo para una recomendación de fusión -- pendiente de que Washington
decida el momento/proceso (esta sesión no fusiona ni pushea por su cuenta). Los 3 puntos de
arriba quedan fuera de alcance, deliberadamente, no olvidados.

## 79. Fix real de reservas concurrentes / bypass de exclusividad -- FR-005 violado, no solo una condición de carrera fina (21-ago-2026)

Washington pidió retomar el worktree `fix-reservas-concurrentes-exclusividad`, ya creado pero
sin trabajo empezado (`git worktree list` lo mostraba en el mismo commit que `main`). El
nombre del worktree combina dos términos que en los hechos son el mismo problema:
"exclusividad" es la garantía de que una bicicleta física tiene un único ciclista activo a la
vez (**FR-005** de `specs/001-operaciones-alquiler-bicicletas/spec.md`: "El sistema DEBE
asignar una bicicleta en exclusiva a un único ciclista en el momento de reservarla... impidiendo
que cualquier otro ciclista la reserve simultáneamente"), y "reservas concurrentes" es la forma
en que esa garantía se rompe.

### Causa real -- peor de lo que ya estaba documentado

El punto 2 de la Deuda Conocida (sección 78, arriba) ya señalaba esto como "condición de
carrera preexistente". Al leer `_crear_viaje()` (`app/routers/ciclista.py`) completa, la causa
real resultó más grave: no había NINGÚN chequeo del estado real de la bicicleta antes de
escribir `estado="en_uso"` -- ni siquiera un check-then-act con ventana de carrera, una
escritura lisa y llana e incondicional. Se confirmó **sin ninguna concurrencia real**, llamando
a `_crear_viaje()` dos veces seguidas para la misma bicicleta ya `en_uso`: la versión anterior
al fix creó un segundo viaje "activo" sobre la misma bici sin ningún error (bug determinístico,
reproducible al 100%, evidencia real: viaje `w7eonu881ufbef0` creado sobre UB-008 mientras ya
tenía el viaje real `nfoduo1jwqgmi2u` activo). FR-005 nunca se cumplió en la práctica -- la nota
"confirmado contra `app/routers/ciclista.py`" en la especificación describía la intención del
código, no su comportamiento real verificado.

### Fix aplicado

`_crear_viaje()` ahora relee el estado real de la bicicleta (`pb.get_record("bicicletas",
bicicleta_id)`) justo antes de crear el viaje, y lanza `ValueError` si ya no es `"disponible"`
-- antes de escribir nada, así que no queda ningún registro huérfano que revertir en el caso de
`reservar()` (una sola bici). Toda la sección crítica (releer → crear viaje → marcar en_uso)
queda envuelta en `_lock_disponibilidad_bicicleta`, un `threading.Lock()` a nivel de módulo, para
cerrar también la ventana de carrera genuina entre dos solicitudes casi simultáneas. Es un lock
de **proceso, no distribuido** -- correcto para el despliegue real actual (un solo proceso
`uvicorn`, sin contenedor propio en `docker-compose.yml`, cliente PocketBase síncrono vía
`requests` sin `await` -- confirmado leyendo `app/db/pocketbase.py`), documentado como
limitación conocida por si el despliegue cambia a múltiples procesos/workers en el futuro. Un
solo lock global (no uno por `bicicleta_id`) es una simplificación deliberada: la escala real de
reservas simultáneas de este sistema es mínima, y un lock por bici agrega gestión de ciclo de
vida sin beneficio real a este volumen. `reservar()` y `reservar_grupo()` no necesitaron ningún
cambio -- ambos ya envuelven la llamada en `try/except`, y el mecanismo de reversión todo-o-nada
de `reservar_grupo()` (`_revertir_reserva_grupal()`) ya maneja este nuevo tipo de fallo igual que
cualquier otro fallo a mitad de lote, sin cambios.

### Verificación real, dos capas de evidencia

1. **Nivel función, antes/después, sin red ni HTTP** -- llamada directa a `_crear_viaje()` para
   una bici ya `en_uso` (UB-008): con el código *previo* al fix (`git checkout HEAD~1 --
   app/routers/ciclista.py`), tuvo éxito y creó un segundo viaje real (`w7eonu881ufbef0`,
   confirmado leyendo el registro real en PocketBase). Con el código *del fix* (`git checkout
   HEAD -- app/routers/ciclista.py`, restaurado), la misma llamada falló correctamente con
   `ValueError: UB-008 ya no está disponible -- alguien más la reservó primero.`, sin crear
   ningún registro.
2. **Nivel HTTP, concurrencia real** -- servidor real corriendo (`uvicorn`, puerto 8001, mismo
   worktree), 2 sesiones HTTP reales logueadas como `ciclista@urbanbike.com`, disparando 2 `POST
   /ciclista/reservar` simultáneos (vía `ThreadPoolExecutor`) para la misma bicicleta real
   (UB-008): exactamente 1 de 2 tuvo éxito (redirigió a `/ciclista/viaje-activo/{id}` real), la
   otra fue rechazada y redirigida a `/ciclista/alquilar` con el mensaje de error real. Confirmado
   además, consultando PocketBase directo, que solo existía 1 viaje "activo" real para esa bici
   tras la corrida.

Un primer intento de repetir la prueba de concurrencia HTTP contra el código *previo* al fix dio
un resultado ambiguo (las 2 solicitudes devolvieron el mismo `id` de viaje) -- investigado a
fondo: la cuenta de prueba `ciclista@urbanbike.com` ya estaba en el tope de `MAX_VIAJES_ACTIVOS`
(4) por deuda de sesiones **muy anteriores** (2 viajes reales en `pendiente_validacion` desde el
16 y el 18 de agosto, no de esta sesión), así que ambas solicitudes fueron rechazadas por el tope
antes de llegar siquiera a `_crear_viaje()`, enmascarando el bug real detrás de un camino de
código distinto. Por eso la evidencia decisiva del "antes" es la de nivel función (punto 1
arriba), que no depende del estado acumulado de la cuenta de prueba. Esos 2 viajes de deuda
antigua (`UB-004` desde el 18-ago, `UB-010` desde el 16-ago) **no se tocaron** -- no son de esta
sesión, quedan documentados acá para que quien los vea después sepa que ya se investigaron y no
son un hallazgo nuevo.

### Efecto colateral de la verificación -- revertido

Las reservas reales creadas durante ambas capas de verificación (`nfoduo1jwqgmi2u` y
`w7eonu881ufbef0` sobre UB-008, `52l5g5oodjpst8b` sobre UB-009) se revirtieron manualmente
-- mismo patrón que la sección 79 de la rama `main` (viajes borrados, bicicletas devueltas a
`disponible`, notificaciones de campana borradas, sin pagos generados, una entrada de auditoría
compensatoria dejada sin borrar la original). No hay forma de revertir el correo real de "Viaje
iniciado" que salió por SMTP para las 2 reservas que pasaron por el flujo HTTP completo -- mismo
caveat documentado en esa misma sección de `main`.

### Qué queda deliberadamente fuera de alcance de este fix puntual

- **El desfase ClickHouse/PocketBase (punto 14)** sigue intacto -- este fix no lo toca. Una
  bicicleta puede seguir apareciendo "disponible" en el catálogo (ClickHouse) mientras ya está
  `en_uso` en PocketBase; lo que este fix garantiza es que, aun así, **nunca se puede crear un
  segundo viaje activo real** sobre esa bici -- la petición ahora falla con un error claro en
  vez de duplicar el estado.
- **El mismo patrón de "leer cantidad, decidir, escribir" en el tope `MAX_VIAJES_ACTIVOS`**
  (`viajes_activos_actuales = _viajes_activos(user_id)` seguido de la creación, sin lock)
  tiene la misma forma de bug en teoría (2 solicitudes casi simultáneas del MISMO ciclista
  podrían ambas leer un conteo por debajo del tope y terminar superándolo) -- no incluido en
  el alcance de este fix porque no es lo que Washington pidió ("reservas concurrentes +
  exclusividad" es sobre la bici, no sobre el tope por ciclista), y el lock agregado hoy NO lo
  protege (el lock envuelve solo `_crear_viaje()`, no el chequeo del tope, que ocurre antes, en
  cada llamador). **Confirmado con Washington (21-ago-2026): se queda en la cola de deuda
  conocida, junto a los otros hallazgos postergados para después del domingo -- no se toca
  todavía.** No es tan grave como los otros dos: no permite bypasear ninguna regla de negocio
  ni duplicar el estado de una bicicleta, solo (en teoría) exceder el tope de 4 en 1 de más.

## 80. Segundo bug crítico del mismo worktree: bypass real de exclusividad vía `bicicleta_codigos` vs `bicicleta_ids` en `reservar_grupo()` (21-ago-2026)

Washington preguntó directamente, antes de revisar el worktree, si este segundo bug ya estaba
corregido -- no lo estaba (el fix de la sección 79 solo tocó disponibilidad, no exclusividad).
Mismo rigor pedido: causa real primero, sin asumir.

### Causa real -- confirmada con un exploit real, no teórico

`reservar_grupo()` recibe `bicicleta_ids: list[str]` y `bicicleta_codigos: list[str]` como **2
arrays paralelos, ambos enviados por el cliente, sin ninguna relación forzada entre ellos**.
`_validar_reserva_comun()` (el chequeo de exclusividad del punto 4) validaba contra
`bicicleta_codigos`; `_crear_viaje()` (la escritura real) siempre usó `bicicleta_ids`. Nada
obligaba a que la posición `i` de un array describiera la MISMA bicicleta que la posición `i`
del otro.

**Exploit real, reproducido con un POST directo a `/ciclista/reservar-grupo`** (cuenta de
prueba `ciclista@urbanbike.com`, membresía real `casual`, confirmada con
`membresias_repo.tipo_membresia_real()`):
- `bicicleta_ids = [id real de UB-001 (exclusiva, dentro de la ventana de 14 días), id real de
  UB-008 (normal)]`
- `bicicleta_codigos = ["UB-008", "UB-008"]` (codigo mentiroso repetido, ninguno de los 2 es
  `UB-001` -- pasa el chequeo de exclusividad limpio)

Resultado confirmado leyendo PocketBase directo: la reserva tuvo éxito, **UB-001 (la bici
exclusiva real) quedó `en_uso`** pese a que la cuenta es `casual`, y **ambos** viajes creados
quedaron con `bicicleta_codigo = "UB-008"` guardado -- el dato de auditoría/historial también
queda corrupto para el viaje que en realidad es sobre UB-001. FR-005 (exclusividad de
asignación) violado por segunda vía distinta a la de la sección 79.

### Fix aplicado

El chequeo de exclusividad se movió de `_validar_reserva_comun()` a `_crear_viaje()`, al mismo
punto donde ya se relee el registro real de la bicicleta por `bicicleta_id` (fix de la sección
79) -- `codigo_real = bici_actual.get("codigo")` sale de ESE registro, nunca del array
`bicicleta_codigos` del cliente. `reservar()` ya no recibe `bicicleta_codigo` como parámetro en
absoluto (dejó de tener ningún uso real); `reservar_grupo()` lo sigue aceptando solo para el
chequeo de longitud de arrays ya existente (`len(bicicleta_codigos) == ... == n`), nunca para
ninguna decisión de seguridad ni dato guardado. `registrar_auditoria()` y las notificaciones de
ambas rutas ahora usan `nuevo_viaje.get("bicicleta_codigo")` (el real, devuelto por
`_crear_viaje()`), cerrando de paso la corrupción del dato de auditoría que el mismo bypass
producía. `exclusivas_nuevas` (consulta a ClickHouse) y `tipo_membresia_actual` se resuelven
**una sola vez por request** (no por bicicleta del lote) y se pasan como parámetros a
`_crear_viaje()`, para no multiplicar consultas dentro del `for` de `reservar_grupo()`.

Decisión de diseño: se eliminó el chequeo de exclusividad de `_validar_reserva_comun()` en vez
de duplicarlo (uno rápido con datos del cliente + uno real dentro de `_crear_viaje()`) --
`_validar_reserva_comun()` ya lleva en su propio docstring la cicatriz de "las dos funciones
traían ~50 líneas de esta validación duplicadas, con riesgo real de que una regla cambiada en
una no se replicara en la otra" (Task C5, sección 74-77). Duplicar la lógica de exclusividad en
2 sitios hubiera sido repetir exactamente ese error. El costo real: para `reservar_grupo()`, si
la bicicleta exclusiva bloqueada es la 3ª de 3 en el lote, las 2 primeras se crean y se
revierten (en vez de nunca crearse) -- mismo mecanismo `_revertir_reserva_grupal()` ya usado
para el fallo de disponibilidad de la sección 79, sin cambios adicionales.

### Verificación real, dos capas + regresión

1. **Nivel función** -- `_crear_viaje()` llamada directamente para UB-001 (exclusiva) con
   `tipo_membresia_actual="casual"`: falló correctamente con
   `ValueError: UB-001 es una bicicleta nueva con acceso anticipado exclusivo para
   suscriptores hasta el 22/08/2026.`
2. **Nivel HTTP -- el exploit exacto reproducido arriba, contra el código YA corregido**: mismo
   POST (`bicicleta_ids=[UB-001, UB-008]`, `bicicleta_codigos=["UB-008","UB-008"]`) devolvió
   `302` a `/ciclista/alquilar` (rechazo), no a `/ciclista/viaje-activo/...`. Confirmado en
   PocketBase: UB-001 y UB-008 siguieron `disponible`, **0** viajes nuevos creados (todo-o-nada
   real, sin necesidad de rollback porque UB-001 era la primera del lote).
3. **Regresión -- reserva grupal legítima** (UB-009 + UB-010, `bicicleta_ids` y
   `bicicleta_codigos` correctamente emparejados, ninguna exclusiva): tuvo éxito, `302` a
   `/ciclista/viaje-activo/...`, y los 2 viajes reales quedaron con el `bicicleta_codigo`
   correcto (`UB-009`/`UB-010` respectivamente, confirmado leyendo los registros reales) --
   el fix no rompe el camino honesto.

### Efecto colateral de la verificación -- revertido

Igual que en la sección 79: los viajes reales creados durante el PoC del exploit (antes del
fix) y durante la prueba de regresión (después del fix) se revirtieron manualmente -- viajes
borrados, bicicletas restauradas a `disponible`, notificaciones de campana borradas, sin pagos
generados, 2 entradas de auditoría compensatorias dejadas sin borrar las originales.

### Revisión independiente (Opus, `git diff 01e14ed..8490f33`, high effort)

Confirmó como sólidos ambos fixes (79 y 80): `codigo_real` sale siempre de una lectura fresca
de PocketBase, nunca del cliente; los 2 call sites pasan los argumentos correctos con la firma
nueva; el rollback todo-o-nada de `reservar_grupo()` sigue disparando con los `ValueError`
nuevos; el JS de `alquilar.html` construye `bicicleta_ids`/`bicicleta_codigos` desde el mismo
objeto por bici en una sola iteración (no hay desincronización de índice del lado del
cliente); nada más depende del `bicicleta_codigo` que se sacó de `reservar()`. 4 hallazgos:

1. **(Real, corregido) El `threading.Lock` no protegía nada hoy.** Verificado empíricamente
   (no solo con el razonamiento del revisor): se agregó un `time.sleep(2)` temporal dentro de
   la sección crítica SIN el lock, se dispararon 2 requests HTTP reales concurrentes para 2
   bicicletas DISTINTAS (sin conflicto de disponibilidad, para aislar el efecto del lock en
   sí), y los timestamps reales mostraron que la 2ª request no entró a su propia sección
   crítica hasta que la 1ª terminó por completo (incluido el envío real de correo por SMTP,
   varios segundos) -- cero interleaving, con o sin lock. Causa real: `reservar()`/
   `reservar_grupo()` son `async def` pero llaman al cliente PocketBase (`requests`, síncrono)
   sin ningún `await` de por medio; en un solo proceso `uvicorn` sin `--workers`, eso serializa
   TODA la app en cada reserva (no solo la sección crítica), asi que la garantía real hoy la da
   el **chequeo de estado re-leído** (`bici_actual.get("estado")`), no el lock. El lock no se
   quitó -- sigue siendo defensivo y correcto para el día que alguien mueva estas llamadas a un
   threadpool (`run_in_threadpool`, patrón que `auth.py` ya usa en otras rutas) para dejar de
   bloquear la app entera durante cada reserva -- pero el commit original de la sección 79
   sobrevendía lo que hace HOY. Corregido acá, en esta sección, con la evidencia real.
2. **(Real, anotado, NO corregido) `estacion_inicio_id`/`estacion_inicio_nombre`/`latitud`/
   `longitud` siguen sin verificarse contra el registro real de la bicicleta.** Misma familia
   de problema que el bypass de exclusividad (confiar en un dato del cliente en vez de
   resolverlo del lado del servidor), pero de severidad menor: no permite bypasear ninguna
   regla de negocio ni tocar el estado de otra bicicleta, "solo" corrompe el dato de estación/
   ubicación guardado en el viaje (auditoría, `empleado/vigilancia/seguimiento.html`, mapas). No
   corregido a propósito -- mismo criterio que el punto del tope `MAX_VIAJES_ACTIVOS` de la
   sección 79: se suma a la cola de deuda conocida para después del domingo, no es tan grave
   como los 2 bugs que sí se corrigieron hoy.
3. **(Real, corregido) `tipo_membresia_real()` se consultaba siempre, incluso sin ninguna bici
   exclusiva en juego.** El código previo al fix de la sección 80 evitaba esa consulta con un
   `if any(codigo in exclusivas_nuevas ...)`. Corregido: ahora `tipo_membresia_actual` solo se
   resuelve si `exclusivas_nuevas` no está vacío (si está vacío, `_crear_viaje()` nunca lo va a
   usar, ningún código real puede estar en un dict vacío) -- mismo comportamiento, sin la
   consulta de más en el caso común (ninguna bici dentro de los 14 días de exclusividad).
4. **(Real, corregido) Quedaban 2 `<input type="hidden" name="bicicleta_codigo">` muertos** en
   `alquilar.html` (form de reserva individual) y `detalle_bicicleta.html` -- ya no los lee
   ningún parámetro de `reservar()`. Quitados junto con la línea de JS que llenaba el de
   `alquilar.html` (`detalle_bicicleta.html` los rellena con Jinja, no con JS). El de
   `reservar_grupo()` (`bicicleta_codigos`, plural, en el carrito) se dejó intacto a propósito
   -- ese sí lo sigue leyendo el backend, solo para el chequeo de longitud de arrays.

**Verificación real de los 3 fixes de esta revisión**: regresión completa de `reservar()` sin
`bicicleta_codigo` en el form (bici UB-008, viaje real creado, `bicicleta_codigo` guardado y
mensaje de auditoría ambos con el código real "UB-008", confirmado leyendo los registros
reales). Efecto colateral revertido igual que en el resto de esta sección.

**Estado: cerrado.** Los 2 bugs críticos que pidió Washington (FR-005 y el bypass de
exclusividad) están corregidos y verificados en 2 capas cada uno, con regresión del camino
legítimo, más una revisión independiente de alto esfuerzo que encontró y ya corrigió sus propios
4 hallazgos (3 arreglados, 1 anotado como deuda conocida de menor severidad, confirmado con
Washington que se queda en la cola). Sin commitear a `main` -- corresponde a Washington revisar
el worktree y decidir el momento/proceso de fusión.

## 81. Bug reportado por Washington: `alert()` nativo en `/ciclista/alquilar` para UB-004 -- causa real NO era resolución de estación, parche puntual sobre el desfase del punto 14 (21-ago-2026)

Washington reportó dos cosas juntas: un `alert()` nativo del navegador rompiendo la rúbrica
académica ("No se pudo resolver la estación actual de UB-004..."), y pidió auditar la causa
real antes de asumir nada, más una auditoría de cualquier otro `alert()`/`confirm()` nativo
que quedara en el sistema.

### Causa real -- no era un problema de nombre de estación

El mensaje del `alert()` era engañoso. Se verificó contra ambas bases directamente (no se
asumió): PocketBase (`bicicletas` real, la que `reservar-grupo` de verdad usa) tenía UB-004 en
`estado="en_uso"`; ClickHouse (`urbanbike_operativa.bicicletas`, de donde
`_catalogo_bicicletas()` lee el `estado` para decidir si mostrar la tarjeta/checkbox) seguía
devolviendo `estado="disponible"`. Es una manifestación concreta y ya reproducida del mismo
desfase documentado en la sección 0/punto 14 (`reservar()`/`finalizar()` de `ciclista.py`
escriben el estado real SOLO en PocketBase; el espejo `_espejar_pocketbase` es unidireccional
ClickHouse→PocketBase, nunca al revés). El catálogo ofrecía el checkbox de reserva grupal para
una bici que la fuente real ya no tenía libre; al hacer clic, el JS no la encontraba en
`BICICLETAS` (el array sí filtrado por PocketBase real) y disparaba el `alert()` con un motivo
que no era el real.

### Fix aplicado -- parche puntual, NO la solución de raíz del punto 14

**Importante: esto no cierra el punto 14.** La migración de fondo del flujo de reserva del
ciclista a ClickHouse (y la eliminación del espejo `_espejar_pocketbase`) sigue pendiente,
íntegra, como ya estaba. Lo que se aplicó hoy es un parche acotado sobre una manifestación
puntual de ese mismo desfase:

1. `app/routers/ciclista.py:alquilar()` -- `catalogo_bicicletas` ahora exige, además del
   `estado == "disponible"` de ClickHouse, que el código esté en el set de bicicletas
   realmente disponibles según PocketBase (`bicicletas`, ya cargado en esa misma función con
   `filter='estado = "disponible"'`). Evita que se vuelva a ofrecer el checkbox de una bici
   que la fuente real ya no tiene libre -- pero cualquier OTRA pantalla que lea
   `_catalogo_bicicletas()`/`_catalogo_agrupado()` para decidir si una acción es posible (no
   solo para mostrarla) puede tener el mismo bug.
2. `app/templates/ciclista/alquilar.html` -- se auditaron los 2 únicos `alert()` nativos que
   quedaban en TODO el sistema (grep sin más resultados en `app/templates` y `app/static/js`;
   el componente propio `window.UB` de `notificaciones.js`, cargado global en `base.html`, ya
   existía desde antes). Ambos reemplazados por `UB.toast(...)`. El caso de carrera genuina que
   sigue existiendo (alguien más reserva entre que carga la página y el clic) ya no usa
   `alert()`: saca el código del carrito, desmarca el checkbox y avisa con el motivo real
   ("Ya no disponible: ...").

Verificado en navegador real (login como `ciclista@urbanbike.com`, servidor local): UB-004 ya
no aparece en el catálogo tras el fix; el toast de "selecciona al menos 2" renderiza con
diseño propio, sin diálogo nativo bloqueante.

### Efecto colateral de la verificación -- revertido

Un clic de prueba con 2 bicis ya seleccionadas completó una reserva grupal real
(UB-009 + UB-010, grupo `07f4076318ce4a21b5106b2ec4d1206e`) en la cuenta de prueba. Revertido
manualmente el mismo día (mismo patrón que `_revertir_reserva_grupal()` usa para un fallo
real): los 2 viajes borrados de `viajes`, las 2 bicicletas devueltas a `estado="disponible"`,
las 2 notificaciones de campana borradas. Confirmado que la reserva no había generado pagos ni
códigos de descuento (n=2, el bono de volumen del punto 0.2 exige n≥3). Se dejó una entrada de
auditoría compensatoria (`accion="eliminar"`) documentando la reversión, sin borrar la entrada
original de "crear viajes" -- la bitácora se trata como registro append-only, no se edita.
No hay forma de revertir el correo real de "Viaje iniciado" que `notificar_usuario()` ya
disparó por SMTP (Brevo) a `ciclista@urbanbike.com` -- no es recuperable, se deja documentado
acá por transparencia.

Cambios sin commitear a propósito -- Washington los revisa primero.

## 82. Punto 1.7 -- ventanas de advertencia contextual al reportar la devolución y al cambiar de modalidad a mitad de viaje (20-21-ago-2026)

Worktree aislado `plan-mejoras-v2-p1-g1` (rama `worktree-plan-mejoras-v2-p1-g1`, base
`5808d89`), plan `docs/superpowers/plans/2026-08-20-avisos-fin-viaje-cambio-modalidad.md`.
Fuente real: `.superpowers/sdd/2026-08-20-avisos-fin-viaje-cambio-modalidad/progress.md`,
dentro del worktree (no comiteado, gitignored). Implementa el punto 1.7 de
`docs/Plan_Mejoras_UrbanBike_V2.md`: dos modales `<dialog>` reales (no texto pasivo) en
`ciclista/viaje_activo.html` que interceptan el `submit` de dos formularios ya existentes --
sin tocar la lógica de negocio real de ninguno de los dos endpoints.

### Task 1 -- aviso al reportar la devolución (commit `4662c1c`)

Un `<dialog id="modal-confirmar-devolucion">` intercepta el `submit` de
`form-devolver` (`POST /ciclista/finalizar`, sin cambios): muestra la estación de destino
elegida y una advertencia explícita de que el costo se congela con la hora del reporte, con
**5 horas sin cargo adicional** para que Vigilancia confirme la entrega física antes de que
se aplique un recargo por demora aparte (la ventana de gracia real ya construida en la
sección 70). Solo al confirmar se reenvía el mismo formulario (`requestSubmit()` con un
`dataset.confirmado` como candado de una sola vía para no volver a interceptar el segundo
submit).

El implementador (Haiku) reportó DONE con el commit hecho, pero el Step 4 (E2E real) no se
había ejecutado -- el worktree no tenía `.env` (gitignored, per-checkout) y por lo tanto no
había credenciales reales para PocketBase/ClickHouse. El controlador cerró el hueco
directamente en vez de re-despachar: copió el `.env` real desde la raíz del repo, levantó el
servidor real en el puerto 8013 (`scripts/dev_reload.py`, reservado para este worktree),
inició sesión real como `ciclista@urbanbike.com`, reservó una bicicleta real (UB-009 → viaje
`fqb6wlbdrselv5u`), confirmó el marcado/texto/JS del modal en el HTML realmente renderizado,
hizo `POST /ciclista/finalizar` real, y confirmó el estado real en PocketBase
(`estado="pendiente_validacion"`). Limpieza verificada con lecturas de seguimiento: viaje
borrado, notificación `kkdzv06nxoiivw0` borrada, código de descuento `1a5lj9h9lk54u4n`
(UB-060A78) borrado, bicicleta UB-009 restaurada a `disponible` (404 en el viaje, `disponible`
en la bici, ambos confirmados con un GET posterior).

Revisión: **Approved, 0 Critical/Important**, 2 minores heredados textualmente del propio
código prescrito por el plan (no desviación del implementador), diferidos: el texto del modal
duplica una leyenda inline preexistente (cosmético); `formDevolver.dataset.confirmado` es un
candado de una sola vía sin ningún camino de falla realista en este flujo. La única duda que
dejó el revisor (la adenda de E2E no se puede verificar solo desde el diff) quedó resuelta
porque el controlador ejecutó y observó personalmente cada llamada HTTP/PocketBase de esa
adenda en la misma sesión, no que confió en un reporte ajeno.

### Task 2 -- aviso al cambiar de modalidad a mitad de viaje (commit `399b31d`)

`viaje_activo()` (`app/routers/ciclista.py`) agrega `precios_modalidad: dict[str, float |
None]` al contexto -- el precio real con promoción ya aplicada de las 3 modalidades (hora/
día/semana) para la bicicleta y membresía del viaje, reusando
`tarifas_repo.precio_modalidad_con_promocion()` sin cambios (mismo criterio que `precio_hora`,
ya existente). Un segundo `<dialog id="modal-confirmar-modalidad">` intercepta el `submit` de
`form-cambiar-modalidad` (`POST /ciclista/cambiar-modalidad`, sin cambios) mostrando el precio
real que se deja de pagar y el nuevo, tomados de `PRECIOS_MODALIDAD` (el dict de Python
serializado al template con el filtro `tojson`, no interpolación cruda). Si el ciclista
selecciona la misma modalidad que ya tiene, no hay nada que confirmar y el modal no aparece.

El implementador (Sonnet) hizo el E2E real correctamente en el primer intento: mató un
`uvicorn` plano (sin `--reload`) que había quedado huérfano en el puerto 8013 de una pasada
anterior, levantó `dev_reload.py` limpio, inició sesión real, reservó una bicicleta real
distinta (UB-008, para no chocar con el test ya limpiado de la Task 1 sobre UB-009), confirmó
el marcado del modal y `PRECIOS_MODALIDAD={"hora":3.6,"dia":28.8,"semana":144.0}` reales en el
HTML renderizado, hizo `POST /ciclista/cambiar-modalidad` real de `hora` a `dia` (302, lógica
de negocio intacta), y confirmó tanto `modalidad_actual="dia"` en PocketBase como exactamente
1 fila nueva en `urbanbike_operativa.alquileres` (`origen="segmento_modalidad"`) en
ClickHouse. Limpieza verificada con lecturas de seguimiento: viaje y notificación en 404,
bicicleta restaurada a `disponible`, fila de ClickHouse borrada vía `ALTER ... DELETE` con el
conteo sondeado hasta 0.

Revisión: **Approved, 0 Critical/Important**, 2 minores heredados textualmente del propio
código prescrito por el plan, diferidos: re-anotación redundante de tipo
(`dict[str, float | None]`) al reasignar la misma variable dentro del `try`; las variables de
bucle `_m`/`_r` no tienen type hint, consistente con otras locales sin tipar ya existentes en
la misma función.

### Revisión final de la rama completa (base `5808d89`, 3 commits, `4662c1c..7fdbd15`)

El plan no traía un task explícito de "revisión final de rama" (a diferencia de otros
worktrees hermanos de este mismo Plan de Mejoras V2). Dado el estándar de rigor ya establecido
antes de dar por cerrado cualquier worktree (ver sección 78), se despachó una revisión
independiente extra enfocada específicamente en la interacción entre los cambios de la Task 1
y la Task 2 sobre el mismo archivo (`viaje_activo.html`: dos `<dialog>` y dos bloques de JS de
interceptación de `submit` agregados secuencialmente en la misma región del
`{% block scripts %}`), no solo en cada tarea por separado (ya revisadas limpias arriba).

**Veredicto: "Ready to merge as-is."** 0 Critical/Important. Confirmó explícitamente que no
hay colisión entre los dos bloques de JS (nombres de `const` distintos en ambos lados,
`id`s de diálogo/botón distintos, cada bloque guardado por su propio
`if (form && dialog)`), que `VIAJE.modalidad_actual` (usado por el JS de la Task 2) está
definido más arriba en el mismo template (`const VIAJE = {{ viaje | tojson }}`, línea 161) y
ya se consultaba antes en el cronómetro de costo preexistente -- no es una dependencia nueva
ni frágil --, que `.modal-card`/`.modal-header` reutilizan el mismo patrón ya usado en unos 10
templates más del proyecto, que `POST /ciclista/finalizar` y `POST /ciclista/cambiar-modalidad`
quedaron intactos (el diff de `ciclista.py` cae entero dentro de la vista GET
`viaje_activo()`), que `precios_modalidad`/`PRECIOS_MODALIDAD` viaja siempre por el filtro
`tojson` (mismo patrón seguro que `VIAJE`, sin superficie XSS nueva), y que el archivo final
queda bien formado (un solo `{% endblock %}` por bloque, sin diálogo huérfano). 3 minores
nuevos, cosméticos/de rendimiento, diferidos con el mismo criterio que el resto del proyecto:
(1) `precios_modalidad` se declara dos veces -- valor por defecto antes del `try` y
reasignado dentro --, intencional, mismo patrón que `precio_hora_recargo`/
`subtotal_segmentos_cerrados` en las mismas líneas; (2) el bucle de las 3 modalidades vuelve a
pedir el precio de la modalidad actual aunque ya se había pedido antes (`resultado_precio`),
un viaje a la base de datos redundante sin impacto funcional; (3) los dos `<dialog>` nuevos se
renderizan siempre en el DOM, incluso cuando `viaje.estado == "pendiente_validacion"` (donde
los formularios que abren no existen) -- inofensivo porque el JS ya valida
`if (form && dialog)` antes de usarlos.

**Estado del plan: RESUELTO.** Los 2 tasks completos, revisados limpios individualmente (0
Critical/Important cada uno, minores heredados del propio código del plan diferidos) y la
revisión final de la rama completa también limpia (0 Critical/Important, 3 minores cosméticos
diferidos) -- listo para una recomendación de fusión, pendiente de que Washington decida el
momento/proceso (esta sesión no fusiona ni pushea por su cuenta).

## 83. Punto 1.8 (Parte 1) -- `ordenes_mant` de PocketBase, huérfana desde el 30-jul-2026,
desconectaba la certificación de Vigilancia del sistema real de órdenes (21-ago-2026)

Antes de construir el punto 1.8 (dashboard de "acciones pendientes" por rol), la auditoría
previa encontró un hallazgo ya anotado pero nunca corregido (sección Grupo 4, línea ~1899:
"`reportes` además usa la colección vieja `ordenes_mant` de PocketBase, desconectada de
`urbanbike_operativa.ordenes_mantenimiento` -- anotado aquí solo como hallazgo, no se tocó").
La auditoría de hoy encontró que el hallazgo era más grave de lo que esa nota sugería: no solo
`/mantenimiento/reportes` lee esa colección huérfana -- **`/vigilancia/mantenimiento/cerrar` y
`/vigilancia/mantenimiento/{oid}/certificar` también**, y esas sí son las pantallas reales que
Vigilancia usa para certificar que una reparación se hizo y liberar la bicicleta de vuelta a
`disponible`.

### Causa real

`ordenes_repo.py` (fuente real de las órdenes desde la migración del 30-jul-2026, ver su
docstring) nunca escribe en PocketBase -- ni `ordenes_repo.crear()` (usado por
`mnt_ordenes_crear`) ni `ordenes_repo.actualizar()` (usado por `mnt_ordenes_editar`) tocan la
colección vieja. Cerrar una orden real desde el WorkPanel de Mantenimiento (la pantalla que de
verdad se usa hoy) no movía la bicicleta a `disponible` -- solo el camino viejo de Vigilancia
lo hacía, y ese camino ya no veía las órdenes nuevas (0 filas reales desde la migración).
Confirmado leyendo el código, no solo infiriéndolo: ningún call site de `ordenes_repo`
referencia PocketBase.

### Fix

- `app/db/ordenes_repo.py`: nueva función `listar_cerradas_pendientes_certificar()` -- ordenes
  con `estado_reparacion = 'cerrada'` cuya bicicleta sigue con `estado = 'mantenimiento'` (JOIN
  real contra `urbanbike_operativa.bicicletas`, ya presente en `_SELECT_BASE`). No hace falta
  una columna nueva de "certificada": en cuanto Vigilancia certifica y la bicicleta pasa a
  `disponible`, la orden deja de cumplir el filtro y desaparece sola de la lista.
- `app/routers/empleado.py`: `vig_mantenimiento_cerrar()` y `_vig_cerrar_mantenimiento_ordenes()`
  ahora usan esa función en vez de `_pb().list_records("ordenes_mant", ...)`.
  `vig_mantenimiento_certificar()` reescrito para leer la orden real con `ordenes_repo.obtener()`
  y mover la bicicleta con `bicicletas_repo.actualizar(..., estado="disponible", ...)` (mismo
  patrón que `_mover_estado_bicicleta()` en `vig_inspeccion`) -- esto también dispara el espejo
  real hacia PocketBase y el registro en `bicicleta_eventos` que ya tiene `bicicletas_repo`, sin
  reinventar nada. `observaciones_cierre` ya no tiene una columna propia en
  `ordenes_mantenimiento` de ClickHouse (a diferencia de la vieja `ordenes_mant`) -- decisión
  deliberada de no ampliar el esquema para esto: queda en la bitácora real (`registrar_auditoria`,
  módulo `ordenes_mantenimiento`), que es donde ya se registra todo lo demás de esta acción
  (quién certificó, cuándo, con qué observaciones).
- `_vig_cerrar_mantenimiento_columnas_filas()` (export Excel/PDF) y la plantilla
  `cerrar_mantenimiento.html` ajustados a los campos reales: `diagnostico` (no `descripcion`,
  que no existe en el esquema de ClickHouse) y `fecha_cierre` en vez de `fecha_apertura` (más
  relevante ahora que la lista son órdenes ya cerradas por Mantenimiento, no en curso) -- usando
  `.strftime()` sobre el `datetime` real, mismo patrón que `mantenimiento/ordenes.html`.

**Fuera de alcance a propósito**: `/mantenimiento/reportes` (`mnt_reportes`, línea ~2700) sigue
leyendo la misma colección huérfana -- Washington pidió explícitamente solo
`vig_mantenimiento_cerrar/certificar` para esta ronda. Queda igual de anotado que antes, ahora
con la causa raíz ya documentada en detalle en vez de solo mencionada.

### Prueba real de punta a punta

Servidor real (`:8002`, `--reload` activo), sin mockear nada. Bicicleta real `UB-004`
(`0e34ecc3-2468-43fd-9f06-c2d6aaa7f698`, disponible antes de la prueba):

1. Login real `empleado@urbanbike.com` (Operación) -- `UB-004` movida a `mantenimiento` vía
   `/empleado/operacion/inventario/{bid}/editar`.
2. Login real `empleado.mant@urbanbike.com` (Mantenimiento) -- orden real `OM-0324` creada vía
   `/empleado/mantenimiento/ordenes/crear` (origen `preventivo`, técnico real "Empleado
   Mantenimiento"), luego cerrada (`estado_reparacion=cerrada`) vía
   `/empleado/mantenimiento/ordenes/{oid}/editar`.
3. Login real `empleado.vig@urbanbike.com` (Vigilancia) -- `GET /empleado/vigilancia/mantenimiento/cerrar`
   confirmó que `OM-0324`/`UB-004` aparecía en la lista (prueba de que el JOIN nuevo lee la
   fuente real). `POST /empleado/vigilancia/mantenimiento/{oid}/certificar` con observaciones
   reales -- confirmado flash "Mantenimiento certificado. Bicicleta disponible nuevamente."
4. Repetido el `GET` de la lista: `OM-0324` ya no aparece (la bicicleta salió de `mantenimiento`,
   deja de cumplir el filtro -- confirma que no hace falta columna de "certificada").
5. Verificado directo contra ClickHouse (`bicicletas_repo.obtener()`): `UB-004.estado ==
   "disponible"`. Orden `OM-0324.estado_reparacion == "cerrada"`, `fecha_cierre` real (no
   epoch).
6. Verificado en PocketBase real: entrada de auditoría real
   (`empleado.vig@urbanbike.com | editar | ordenes_mantenimiento | "Mantenimiento certificado:
   orden OM-0324 de UB-004 — Prueba E2E: verificacion fisica OK, bicicleta operativa."`) y
   notificación real a `rol_destino="empleado-operacion"` ("Bicicleta disponible").
7. Export Excel y PDF de `/vigilancia/mantenimiento/cerrar` verificados con sesión real
   autenticada: `200`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
   (5577 bytes) y `application/pdf` (24624 bytes) respectivamente.

**Estado final real**: `UB-004` terminó exactamente donde empezó (`disponible`) -- la flota no
quedó afectada. Quedan como evidencia real y permanente (no se revierten): la orden `OM-0324`
(`cerrada`, no se puede borrar por diseño -- `ordenes_repo.eliminar()` solo permite borrar
órdenes que sigan `abierta`, mismo criterio que bicicletas con alquileres reales), las 2
transiciones reales en `bicicleta_eventos` (`disponible→mantenimiento→disponible`), la entrada
de auditoría y la notificación a Operación. Mismo criterio ya usado en este proyecto para datos
de prueba que alcanzan un estado real irreversible por diseño (ver sección 79: "la bitácora se
trata como registro append-only, no se edita").

**Verificación de reload real**: el proceso `uvicorn --reload` (PID 23028, puerto 8002) llevaba
arriba desde antes de este cambio -- no se reinició manualmente (autorización previa exigida,
ver sección 72). La prueba E2E paso 3 (`OM-0324` apareciendo en la lista nueva) es en sí misma
la confirmación de que `watchfiles` sí respawneó el worker esta vez: el código viejo habría
fallado ahí (consulta a una colección PocketBase con un id de ClickHouse que no existe en ella).

**Estado del plan: RESUELTO.** Listo para construir el punto 1.8 (Parte 2) sobre la fuente real.

## 84. Punto 1.8 (Parte 2) -- panel de "acciones pendientes" en los 5 dashboards, sobre las
fuentes reales auditadas y corregidas en la Parte 1 (21-ago-2026)

Construido sobre la auditoría previa (no repetida aquí) y el fix de `ordenes_mant` de la
sección 83. Alcance confirmado por Washington: Ciclista (ya resuelto, solo homogeneizar),
Operación (solo cobros pendientes de verificar), Vigilancia (3 tarjetas), Mantenimiento (2
tarjetas, ahora con fuente real), Admin (bloqueos accionable + registros nuevos informativo,
separados).

### Componente compartido

`app/templates/componentes/panel_pendientes.html` -- recibe `pendientes`: lista de
`{titulo, conteo, enlace, color, icono}`. Reutiliza `.card`/`.card-clickeable` y la paleta ya
definida de `.badge-green/red/yellow/blue/gray` (incluidas sus variantes de tema oscuro en
`main.css`, sin CSS nuevo) -- el ícono hereda el color vía `stroke="currentColor"` dentro del
mismo div `badge-*`, así que el componente no inventa una paleta propia. Cada router sigue
resolviendo sus propios conteos (Operación consulta pagos, Mantenimiento consulta
`ordenes_repo`, etc.) -- el componente es solo la vista, no una capa de datos genérica.
Un dashboard "al día" no debe mostrar una fila de puros ceros: `{% set _visibles = pendientes |
selectattr("conteo", "gt", 0) | list %}` filtra las tarjetas en cero antes de decidir si la fila
completa se renderiza.

### Por rol

- **Ciclista**: sin cambios de lógica -- `_tarjetas_pendientes()` ya cubría esto (ver auditoría
  previa). Se agregó solo la etiqueta "Pendientes" (mismo estilo que el resto de secciones) arriba
  del bloque existente, para que se lea igual que los otros 4 dashboards sin tocar su estructura.
- **Operación**: 1 tarjeta -- "Cobros pendientes de verificar" = suma de `pagos` filtrados por
  `estado="verificacion_pendiente"` (transferencias) y `estado="pendiente_efectivo"` (efectivo),
  mismos dos filtros que ya usa `op_pagos()` -- solo un `totalItems` de cada uno, sin traer los
  registros completos. Enlaza a `/empleado/operacion/pagos`.
- **Vigilancia**: 3 tarjetas -- "Seguimientos activos" (`viajes` `estado="activo"`, nuevo conteo
  en vivo, antes el dashboard solo mostraba estadísticas históricas de Citibike del 31-oct-2023),
  "Devoluciones por validar" (mismo dato que antes vivía como banner fijo -- migrado a la tarjeta
  del panel, ya no hay dos lugares mostrando el mismo número), y "Reparaciones por certificar"
  (`ordenes_repo.listar_cerradas_pendientes_certificar()` de la Parte 1). Los bullets "daños por
  verificar" y "disponibilidad por confirmar" del documento se unificaron en esta única tarjeta,
  tal como marcó la auditoría (misma cola real, no dos números idénticos repetidos).
- **Mantenimiento**: 2 tarjetas -- "Mantenimientos activos" (bicicletas `estado="mantenimiento"`,
  igual que antes, fuente confiable) y "Órdenes por actualizar" (`ordenes_repo.listar(estado=
  "abierta")`, reemplaza el KPI `ordenes_pendientes` que leía la colección huérfana -- mismo bug
  de la sección 83, ahora corregido también aquí). El `.kpi-grid` viejo de 2 tarjetas se reemplazó
  por el panel (mismos 2 números, ahora reales, accionables y con enlace directo:
  "Órdenes por actualizar" enlaza a `/empleado/mantenimiento/ordenes?estado=abierta`,
  pre-filtrado).
- **Admin**: "Usuarios bloqueados" (`users` con `activo=false`) como tarjeta accionable del panel,
  enlazando a `/admin/usuarios`. "Registros nuevos" (últimos 7 días, por `created`) se muestra
  **aparte**, como línea informativa sin badge ni enlace de acción -- explícitamente no es una
  "acción pendiente" (el registro público ya se auto-verifica por correo, nadie tiene que
  aprobarlo). Ambos conteos se derivan de la misma lista de `users` que `/dashboard` ya traía
  para las gráficas -- ninguna consulta nueva a PocketBase.

### Prueba real en los 5 roles

Servidor real (`:8002`), 5 sesiones HTTP reales (`POST /auth/login` con las 5 cuentas de prueba
documentadas), leyendo cada dashboard tal como lo vería un usuario real. Antes de cada prueba se
calculó el número esperado consultando la base de datos real directamente (PocketBase/ClickHouse,
mismo filtro que usa el router), para comparar contra lo renderizado en el HTML real -- no se
asumió que el número mostrado fuera correcto solo porque la página cargó.

| Rol | Tarjeta | Esperado (consulta directa) | Mostrado en `/dashboard` real |
|---|---|---|---|
| Ciclista (`ciclista@urbanbike.com`) | Pendientes (viajes/pagos) | tiene pendientes reales | etiqueta "Pendientes" visible, tarjetas reales ✓ |
| Ciclista (`wacho@urbanbike.com`) | Pendientes | sin pendientes | bloque completo ausente (0 tarjetas) ✓ |
| Operación | Cobros pendientes de verificar | 0 (transf=0, efect=0) | fila ausente (0 > 0 es falso) ✓ |
| Vigilancia | Seguimientos activos | 0 | ausente ✓ |
| Vigilancia | Devoluciones por validar | 2 | **2** ✓ |
| Vigilancia | Reparaciones por certificar | 2 (`OM-0322`, `OM-0323`) | **2** ✓ |
| Mantenimiento | Mantenimientos activos | 4 (`UB-003/005/006/007`) | **4** ✓ |
| Mantenimiento | Órdenes por actualizar | 1 | **1** ✓ |
| Admin | Usuarios bloqueados | 3 | **3** ✓ |
| Admin | Registros nuevos (7 días) | 11 | **11** ✓ |

Los 10/10 conteos coinciden exactamente con la consulta directa a la base de datos en el momento
de la prueba. El caso Operación/Vigilancia-seguimientos confirma además que el filtro de "ocultar
en cero" funciona (no hay una fila vacía de tarjetas en 0, tal como se diseñó) sin que eso se
confunda con un error de carga -- se verificó el HTTP 200 y el resto del dashboard renderizado
normalmente en ambos casos.

**Nota real, no forzada**: `UB-004` (la bicicleta de la prueba E2E de la Parte 1) ya no aparece
en "Reparaciones por certificar" porque se certificó en esa misma prueba -- las 2 órdenes que sí
aparecen (`OM-0322`, `OM-0323`) son datos reales preexistentes del sistema, no generados por esta
sesión. Ninguna cuenta ni dato de prueba nuevo quedó pendiente de limpieza -- las únicas escrituras
de esta Parte 2 fueron de solo lectura (conteos), sin crear ni modificar registros.

**Estado del plan: RESUELTO.** Punto 1.8 completo en los 5 roles, sobre fuentes reales
verificadas, sin datos inventados ni simulados.

## 85. Punto 2.4 -- Chat de soporte, versión completa: agente/motivo al iniciar,
adjuntos reales, emoji, soft-delete (21-ago-2026)

Construido sobre la auditoría previa (buzón genérico confirmado, sin selección de agente/motivo/
adjuntos/borrado) y las 5 decisiones ya confirmadas por Washington. El cambio de fondo, no pedido
explícito pero necesario para que "elegir agente" tuviera sentido real: el modelo pasó de "un hilo
eterno por `ciclista_id`" a "una o más conversaciones reales por `conversacion_id`", cada una con su
propio agente y motivo.

### Esquema (`etl/21_agregar_adjunto_soporte.py`)

Campos nuevos en `mensajes_soporte`: `conversacion_id`, `agente_id`, `agente_nombre`, `motivo`
(select: infraccion/consulta_general/otro), `adjunto` (file, 1 archivo, máx 20MB, mimeTypes
imagen/PDF/video), `eliminado`/`eliminado_por`/`eliminado_en`. Ejecutado real contra PocketBase,
verificado idempotente (segunda corrida: "los campos nuevos ya existen, sin cambios"). El campo
`type: "file"` no tenía precedente en ningún script de `etl/` del proyecto (avatar/comprobante_imagen
se crearon a mano en el panel admin) -- se validó con una escritura+lectura real antes de construir
nada encima (registro de prueba, subido, descargado con 200 real, y borrado por ser solo una prueba
de esquema, no una conversación real).

**Backfill real**: los 13 mensajes reales de pruebas anteriores (2 conversaciones de sesiones previas
de Washington) no tenían `conversacion_id` -- se les asignó `conversacion_id = ciclista_id` (la misma
agrupación exacta que ya tenían) y `motivo = "otro"`, sin inventar un `agente_id` que nunca existió
en el modelo viejo (buzón de rol completo). Sin esto quedarían invisibles para siempre en la UI nueva.

### Repositorio (`app/db/mensajes_soporte_repo.py`, reescrito)

- `iniciar_conversacion()`: genera `conversacion_id` nuevo, notifica **al agente elegido puntualmente**
  (`notificar_usuario`, nunca `notificar_rol` -- ese era el cambio de comportamiento real que pedía
  el punto 2.4).
- `enviar()`: ya no recibe agente/motivo -- los relee del primer mensaje real de la conversación
  (`obtener_conversacion()`) para que nunca puedan desalinearse entre mensajes del mismo hilo. Ciclista
  → notifica al agente de esa conversación; staff → notifica al ciclista (sin cambios, ya existía).
- Adjuntos: dos pasos reales (`create_record` + `update_record_with_file`) -- PocketBase no tiene
  "crear con archivo" en un solo paso, mismo patrón ya usado por `comprobante_imagen`.
- `eliminar_mensaje()`: soft-delete, verifica que `autor_id == actor_id` antes de tocar nada -- ni el
  ciclista puede borrar lo que mandó el staff, ni al revés.
- `eliminar_conversacion()`: soft-delete de todos los mensajes de un hilo; la restricción real de
  "solo Vigilancia/Admin" no vive en el repo -- la da el propio prefijo de ruta
  (`/empleado/vigilancia/*`, `/admin/*`), restringido ya por `AuthMiddleware.ROLE_RULES`.
- `listar_hilo(incluir_eliminados=)` / `listar_conversaciones(incluir_eliminadas=)`: por defecto
  ocultan lo borrado (vista de ciclista/Vigilancia); Admin pasa `True` en ambos -- ve conversaciones
  completas borradas y mensajes individuales borrados, marcados explícitamente, nunca con el DELETE
  real que evita todo este módulo.

### Frontend

`componentes/mensaje_soporte.html` (una burbuja) separado de `hilo_soporte.html` (el hilo completo)
a propósito: `chat-soporte.js` tiene que reproducir el mismo HTML en JS puro para el sondeo de 4s, y
mantenerlos en includes distintos hace explícito qué estructura exacta hay que espejar. Adjuntos se
clasifican por extensión del nombre real (imagen/video/documento) tanto en Jinja como en JS, mismo
criterio en los dos lados. Selector de emoji: grilla estática de 24 emoji en `chat-soporte.js`, cero
librerías nuevas -- confirmado sin cambio de backend (`enviar()` solo hace `.strip()`/límite de
longitud, nunca filtra caracteres). Preview de adjunto antes de enviar: se extendió
`file-preview.js` (ya existente del punto 1.6) para reconocer también `video/*` adjuntos, en vez de
duplicar la lógica de preview.

**Decisión de diseño encontrada durante la prueba, confirmada por Washington tal cual se
implementó (21-ago-2026)**: un mensaje borrado se muestra como "Mensaje eliminado" para **todos
los que ven el hilo, incluido Admin** -- el texto/adjunto original nunca se re-muestra en ninguna
pantalla, solo queda recuperable leyendo el registro real de PocketBase directamente (rol
`superusuario`, fuera de la UI). "Admin ve todo, incluida la conversación borrada" es "Admin puede
seguir accediendo a la conversación y ver que un mensaje existió y fue borrado" -- no "Admin ve el
contenido borrado en pantalla". Confirmado explícitamente: el propósito del soft-delete es
preservar la evidencia en la base de datos, no exponerla libremente -- ni siquiera a Admin. Sin
cambios pendientes.

### Prueba real de punta a punta

Servidor real (`:8002`), sin mocks. Solo existía 1 agente de Vigilancia activo real
(`empleado.vig@urbanbike.com`, Miguel Torres) -- se creó un segundo real
(`agente2.vig.e2e@urbanbike.com`, vía `POST /admin/usuarios/crear` real) para poder probar de verdad
que 2 conversaciones con 2 agentes distintos no se mezclan; **desactivado al terminar** (`POST
.../toggle-activo`, la misma acción real que usaría Washington) para que no quede como agente
seleccionable permanente -- no se borró (conserva su conversación real asociada).

1. Selector de agentes del ciclista: Miguel Torres y Agente Dos E2E presentes, **Admin ausente**
   -- confirmado por texto real de la respuesta HTTP, no asumido.
2. `POST /ciclista/soporte/iniciar` × 2 (Miguel/infracción, Agente Dos/consulta_general) -- 2
   `conversacion_id` reales y distintos confirmados.
3. `GET /ciclista/soporte`: las 2 conversaciones listadas por separado, cada una con su agente y
   motivo reales, sin mezcla de textos entre ellas.
4. `POST .../enviar` con un PNG real (multipart) + texto con emoji real (`🚲✅`) en la conversación 1:
   respuesta HTML confirmada con `<img class="chat-adjunto-imagen">` real y el emoji intacto.
5. Ciclista borra ese mismo mensaje: desaparece del hilo visible (confirmado por texto ausente en la
   respuesta) **y** se confirmó directo contra PocketBase que el registro real sigue existiendo,
   `eliminado=True`, `eliminado_por` = id real del ciclista, y el texto original (con el emoji)
   intacto en la base -- soft-delete real, no ocultamiento de UI nada más.
6. Vigilancia (Miguel) borra la conversación 1 completa: desaparece de la lista de Vigilancia y de la
   lista del propio ciclista.
7. Admin: la conversación 1 **sí** aparece en su lista (con badge "Eliminada" real) y su detalle
   carga (200) mostrando "Mensaje eliminado" donde corresponde -- supervisión total confirmada, sin
   que la conversación se vuelva inaccesible.
8. Re-confirmado que Admin sigue sin aparecer en el selector de agentes del ciclista después de todo
   lo anterior.
9. Extra no pedido explícito, verificado igual por consistencia del diseño: la conversación 2 (con el
   agente ahora desactivado) sigue siendo visible y accesible para Miguel desde el WorkPanel de
   Vigilancia -- ninguna conversación queda huérfana si su agente original deja de estar activo.

**Estado del plan: RESUELTO.** Punto 2.4 completo, probado de punta a punta con cuentas y datos
reales, incluida la confirmación de Washington sobre el matiz de "qué ve Admin exactamente" -- sin
nada pendiente.

## 86. Punto 2.1 -- categoría eléctrica exclusiva para suscriptores (RESUELTO, Washington
18-ago-2026), implementada sobre el mismo mecanismo real del punto 4 (21-ago-2026)

### Auditoría previa

1. `_catalogo_bicicletas()` y `_catalogo_agrupado()` (`app/routers/ciclista.py`) ya controlan por
   completo qué bicicletas ve el ciclista, y ambas ya reciben `tipo_membresia` resuelto por el
   llamador vía `membresias_repo.tipo_membresia_real()` -- no hacía falta ningún dato nuevo, solo
   una nueva condición sobre `es_electrica` (ya presente en cada fila).
2. `membresias_repo.esta_activa(id_usuario)` ya existe y ya está en uso real
   (`tipo_membresia_real()` la envuelve, resolviendo primero el `id_usuario` de ClickHouse desde el
   email de la sesión vía `resolver_id_usuario_por_email()`).
3. Hallazgo clave de la auditoría: el punto 4 ("acceso anticipado a bicicletas nuevas") ya
   resuelve exactamente el mismo tipo de problema -- una restricción "exclusiva para
   suscriptores" sobre bicicletas puntuales, con bloqueo real en 3 capas (catálogo, ficha de
   detalle, y dentro del lock de `_crear_viaje()` contra bypass por POST directo). Se implementó el
   punto 2.1 como una variante de ese mismo mecanismo ya probado, no como algo nuevo.

### Implementación

- `_catalogo_bicicletas()`: nuevo campo `bloqueada_electrica` = `es_electrica and not es_member`
  (mismo criterio que `bloqueada_exclusiva`, la bici se sigue mostrando, no se oculta).
- `_catalogo_agrupado()`: nuevo `disponibles_bloqueadas_no_member` en la consulta SQL (unión real
  de "nueva en ventana" O "eléctrica", sin contar dos veces una bici que fuera ambas cosas) para
  que el conteo de "disponibles" de la vista agrupada por categoría sea honesto para un no-miembro.
- `bicicleta_detalle()`: nuevo `bloqueada_electrica` en el contexto, mismo patrón que
  `bloqueada_exclusiva` ya existente.
- **`_crear_viaje()` (el punto real de aplicación, dentro del lock de concurrencia)**: nuevo
  chequeo `bici_actual.get("tipo") == "electric_bike" and tipo_membresia_actual != "member"` ->
  `ValueError`, inmediatamente después del chequeo de exclusividad existente. `tipo` sale del mismo
  registro de PocketBase ya leído para el chequeo de exclusividad -- no se confía en nada enviado
  por el cliente, mismo criterio anti-bypass que ya cerró el hallazgo real de la sección 79/80.
- **Fix necesario en los llamadores** (`reservar()` y `reservar_grupo()`): ambos tenían un atajo
  real ("`tipo_membresia_actual` solo se consulta si `exclusivas_nuevas` no está vacío") que dejaba
  de ser seguro en cuanto `_crear_viaje()` empezó a usar ese mismo valor para un segundo chequeo
  independiente -- si no había ninguna bici en ventana de acceso anticipado ese día, el atajo
  fijaba `tipo_membresia_actual = "member"` sin consultar nada, lo que habría dejado pasar
  cualquier bicicleta eléctrica a un no-miembro. Se quitó el atajo en los dos lugares: ahora
  siempre se resuelve la membresía real antes de crear el viaje.
- `tarjeta_bicicleta.html` / `detalle_bicicleta.html`: mismo patrón visual que `bloqueada_exclusiva`
  (no se oculta la tarjeta, se reemplaza el botón "Alquilar" por un aviso), pero con un enlace real
  a `/ciclista/membresia` -- a diferencia del bloqueo por exclusividad (que solo informa una fecha),
  este sí tiene una acción real disponible ahora mismo.
- `catalogo.html`: nueva nota "N eléctricas -- exclusivas para suscriptores" cuando corresponde,
  mismo patrón que la nota de "acceso anticipado" ya existente.

### Prueba real de punta a punta (antes/después con membresía, mismo patrón que promociones)

Servidor real (`:8002`), sin mocks, con las 3 capas de bloqueo verificadas por separado:

**ANTES (ciclista sin membresía activa, confirmado real en ClickHouse antes de probar):**
- `/ciclista/alquilar`: la bicicleta eléctrica real disponible aparece en el catálogo con el aviso
  "Eléctrica — solo para miembros. Activar membresía" en vez del botón normal de alquilar.
- `/ciclista/bicicleta/{id}`: mismo aviso, con enlace real a `/ciclista/membresia`, **sin** el
  formulario de reserva (`id="form-reservar"` ausente del HTML).
- **Bypass real por `POST /ciclista/reservar` directo** (sin pasar por la UI, con el id real de la
  bicicleta): rechazado con el mensaje real "UB-005 es una bicicleta eléctrica -- exclusiva para
  ciclistas con membresía activa." (confirmado vía `UB.toast()`, el mecanismo real de flash de este
  proyecto -- no un `<div class="flash">` estático, hallazgo de la propia prueba). La bicicleta
  permaneció `disponible` en PocketBase, verificado directo.

**Activación real de membresía** (`wacho@urbanbike.com`, vía `POST /ciclista/membresia/activar`,
tarjeta de pruebas 4242 4242 4242 4242, pago simulado real) -- confirmado `esta_activa() == True`
contra ClickHouse.

**DESPUÉS (mismo ciclista, con membresía activa):**
- `/ciclista/alquilar`: la misma bicicleta ahora muestra el botón normal "Alquilar esta bicicleta".
- `/ciclista/bicicleta/{id}`: formulario de reserva presente.
- **Reserva real completada por `POST /ciclista/reservar`**: viaje real creado, la bicicleta pasó a
  `en_uso` en PocketBase -- confirmado directo, no asumido por el código de estado HTTP.

**Nota real, no forzada**: la prueba de bypass se hizo con una segunda bicicleta eléctrica real
(`UB-005`) puesta `disponible` temporalmente desde Operación (estaba en `mantenimiento`) solo para
tener una unidad disponible con la que probar el rechazo sin afectar la reserva real de la primera
prueba -- **restaurada a `mantenimiento` al terminar**, mismo estado real en el que estaba antes,
vía la misma ruta administrativa real que usaría Operación. La reserva real de `UB-010` (la primera
prueba, con membresía activa) se dejó tal cual -- viaje activo real de `wacho@urbanbike.com`,
membresía real activa -- como evidencia real de que el flujo funciona de punta a punta, mismo
criterio de no revertir evidencia real ya usado en el resto de esta sesión.

**Hallazgo real de la propia prueba, no relacionado al punto 2.1**: los mensajes de error/éxito de
este sistema se muestran vía `UB.toast()` (JavaScript), no como un bloque HTML estático -- cualquier
prueba futura que busque un `<div class="flash">` en el HTML de respuesta no lo va a encontrar
aunque el mensaje se haya mostrado correctamente en el navegador real.

**Estado del plan: RESUELTO.** Punto 2.1 completo en las 3 capas (catálogo, ficha de detalle,
servidor), probado antes/después con membresía real, sin bypass posible confirmado.

## 87. Hallazgo pendiente, prioridad alta -- `/mantenimiento/reportes` muestra un dato real
incorrecto: 6 órdenes cuando la fuente real tiene 13 (encontrado durante la auditoría del
punto 2.6, 21-ago-2026)

Durante la auditoría de reportes "pobres" del punto 2.6 (documento completo en
`docs/superpowers/plans/2026-08-21-punto-2.6-auditoria-diseno.md`, sin comitear a propósito,
mismo criterio que el resto de esa carpeta) se reconfirmó y agravó un hallazgo que ya estaba
anotado desde la sección 83: `/mantenimiento/reportes` (`mnt_reportes`, `app/routers/empleado.py`,
línea ~2758) sigue leyendo la colección `ordenes_mant` de PocketBase, huérfana desde el
30-jul-2026 y explícitamente dejada fuera de alcance en la sección 83 ("Washington pidió
explícitamente solo `vig_mantenimiento_cerrar/certificar` para esta ronda").

### Por qué esto ya no es solo un hallazgo anotado, sino un pendiente de prioridad alta

Verificado en vivo contra el servidor real (puerto 8007, sesión real `empleado.mant@urbanbike.com`)
y confirmado independientemente por un segundo revisor con lectura directa a PocketBase/ClickHouse:
la tarjeta "Total de órdenes" de esa pantalla muestra **6** (conteo real de `ordenes_mant`),
mientras que `ordenes_repo.listar()` -- la fuente real que usa el resto de Mantenimiento, incluida
`/mantenimiento/ordenes` -- tiene **13** órdenes reales hoy. El reporte le falta más de la mitad de
los datos reales del negocio, sin ningún aviso al usuario de que la cifra está desactualizada. A
diferencia de la sección 83 (donde el hueco era sobre una acción operativa, certificar una
reparación), acá el hueco es sobre un número que Mantenimiento puede estar usando para decidir algo
real (carga de trabajo, planificación) creyendo que es el total real.

### Fix propuesto (del propio documento de la auditoría 2.6, no implementado en esta sesión)

Migrar la fuente de datos de `mnt_reportes` de `ordenes_mant` (PocketBase) a `ordenes_repo`
(ClickHouse) -- mismo patrón que ya usan `/mantenimiento/ordenes` y `/mantenimiento/dashboard`.
Esfuerzo estimado: **chico** solo para el fix de la fuente (no opcional, dato activamente
engañoso); si además se agrega filtro de fecha/prioridad y export Excel/PDF (hoy es la única
pantalla de reportes de todo el sistema sin ninguna opción de exportar), el esfuerzo total sube a
**mediano**.

**Estado del plan: PENDIENTE, prioridad alta.** No se corrige en esta sesión (fuera del alcance de
2.3/2.6/2.7/2.8 despachados hoy) -- queda documentado para que Washington decida cuándo priorizarlo,
mismo criterio de la sección 83.

## 88. Punto 2.7 -- fecha límite de reparación (Mantenimiento) (21-ago-2026)

**Causa/motivación**: el punto 2.7 del plan de mejoras pide que cada orden de mantenimiento real
tenga una fecha límite establecida, dado que una bicicleta en mantenimiento representa pérdida de
ingresos para el negocio mientras no esté disponible. Antes de este punto, `ordenes_mantenimiento`
solo tenía `fecha_apertura`/`fecha_cierre`, sin ningún plazo esperado ni forma de detectar una orden
que llevara demasiado tiempo abierta.

**Diseño**: columna nueva `fecha_limite` (ClickHouse, `urbanbike_operativa.ordenes_mantenimiento`),
mismo patrón sentinel `DateTime DEFAULT toDateTime('1970-01-01 00:00:00')` que ya usa `fecha_cierre`
en esa misma tabla. Se calcula sola dentro de `ordenes_repo.crear()` (único punto real de creación
de órdenes -- cubre tanto el alta manual desde Mantenimiento como la generación automática desde la
inspección de devolución reprobada en Vigilancia, sin tocar ese segundo call site) según
`PLAZO_DIAS_POR_PRIORIDAD = {"alta": 2, "media": 5, "baja": 10}` (valores de negocio razonables, no
confirmados formalmente por Washington todavía). Editable solo desde el formulario de edición
(`modo=editar`), interpretada como fin del día del plazo (23:59:59). "Vencida" se calcula en Python
en el router (`_marcar_vencidas`, mismo patrón que `o["foto_url"]`), nunca en Jinja, y una orden
`cerrada` nunca es vencida sin importar su `fecha_limite`.

**Migración de datos reales** (`etl/22_agregar_fecha_limite_ordenes.py`, idempotente en ambas
partes): `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + backfill (`ALTER TABLE ... UPDATE`) de las 13
órdenes reales que ya existían, calculando `fecha_limite = fecha_apertura + días según prioridad`
para que ninguna orden histórica quedara invisible al filtro de vencidas. Verificado directo contra
ClickHouse: columna existe, 13 órdenes totales, 0 pendientes del sentinel tras el backfill (2
filas comprobadas a mano: `OM-0324` prioridad=baja, +10 días exactos; `OM-0323` prioridad=media, +5
días exactos).

**Prueba real de punta a punta** (servidor real puerto 8005, cuenta `empleado.mant@urbanbike.com`):

| Paso | Esperado | Resultado real |
|---|---|---|
| Crear orden real prioridad=alta (`OM-0327`) | `fecha_limite` = `fecha_apertura` + 2 días, calculada por el código | Confirmado contra ClickHouse directo: `fecha_apertura` 2026-08-21 21:19:55 → `fecha_limite` 2026-08-23 21:19:55 |
| Orden recién creada | Sin badge "Vencida" en la lista | Confirmado, ausente |
| Editar `fecha_limite` a ayer vía `POST /mantenimiento/ordenes/{oid}/editar` (form real) | `fecha_limite` actualizada, fin del día (23:59:59) | Confirmado contra ClickHouse directo: `2026-08-20 23:59:59` |
| Lista general (`/mantenimiento/ordenes`) | Badge "Vencida" visible | Confirmado |
| Filtro `?vencida=1` | Orden editada aparece; orden de control (`OM-0328`, prioridad=baja, sin editar) NO aparece | Confirmado (evita falso positivo del filtro) |
| Dashboard de Mantenimiento | Tarjeta "Órdenes vencidas" con conteo real | `listar_vencidas()` directo = 3, mismo número visible en el HTML del dashboard |
| Vigilancia (`/vigilancia/mantenimiento/cerrar`, certificación, punto 1.8 Parte 1) | Sigue respondiendo 200 sin romperse | Confirmado, 200 |
| Export Excel (`?vencida=1`) | 200, `content-type` de xlsx real | Confirmado, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, 5850 bytes |
| Export PDF (`?vencida=1`) | 200, `content-type` de pdf real | Confirmado, `application/pdf`, 24983 bytes |

**Limpieza de datos de prueba**: se crearon 4 órdenes reales de prueba (`OM-0325`/`OM-0327`
prioridad alta -- forzadas a vencidas; `OM-0326`/`OM-0328` prioridad baja -- control, sin editar).
Las 4 quedaron `estado_reparacion="abierta"` sin repuestos reales consumidos, así que las 4 se
borraron con el endpoint real `POST /mantenimiento/ordenes/{oid}/eliminar` (mismo endpoint que
usaría un técnico) y se confirmó `ordenes_repo.obtener(oid) is None` para las 4. El conteo total de
`ordenes_mantenimiento` volvió a 13, igual que antes de la prueba.

**Revisión de fresh-eyes antes de cerrar** (ver nota de proceso en el reporte de esta sesión: se
hizo como pase de auditoría propio, no con un sub-agente delegado): (a) `ordenes_repo.actualizar()`
tiene un único call site en toda la app (`mnt_ordenes_editar`, ya actualizado) -- confirmado con
grep antes y después de los cambios, ningún otro caller se rompió; (b) los índices corregidos de
`fila_total` en Excel/PDF (`[None] * 8` + sumas en `f[9]`/`f[10]`) coinciden con el orden real de
columnas (`Fecha límite` insertada en la posición 7, costos corridos a 9/10) -- confirmado
exportando de verdad con datos reales (tamaños de archivo > 0, sin traceback); (c) `_marcar_vencidas`
se aplica en los 2 lugares que renderizan una orden individual o en lista (`mnt_ordenes`,
`mnt_ordenes_detalle`) -- confirmado por lectura del código, no falta ninguno.

**Hallazgo de alcance MENOR, no corregido, señalado para que Washington decida**: (d) el sentinel
`1970-01-01` no se oculta explícitamente en el renderizado de `fecha_limite` en los 3 templates
(`ordenes.html`, `ordenes_form.html`, export Excel/PDF) -- todos usan `{% if o.fecha_limite %}` para
decidir mostrar "—", que es `True` incluso para el sentinel (un `datetime` no-None es siempre
verdadero), a diferencia de `fecha_cierre` que sí se guarda explícitamente contra
`estado_reparacion == 'cerrada'`. En la práctica esto es inofensivo HOY: `crear()` siempre calcula
una `fecha_limite` real (nunca inserta el sentinel) y las 13 órdenes existentes ya fueron
backfilleadas -- no hay ninguna fila real en estado sentinel para mostrar. Es el mismo patrón
literal que ya traía el plan aprobado (Task 3 Step 3, Task 4 Steps 2/4), así que no se modificó
unilateralmente; queda documentado como mejora defensiva opcional, no como bug activo.

**Decisión de negocio pendiente de confirmar por Washington**: los plazos por defecto
(`alta`=2 días, `media`=5 días, `baja`=10 días) son un valor razonable propuesto en el plan, no una
cifra de negocio ya aprobada -- fácil de ajustar (un solo dict, `PLAZO_DIAS_POR_PRIORIDAD` en
`ordenes_repo.py`) si Washington define otros valores.

## 89. Punto 2.8 (mitad infracciones) -- trazabilidad de infracciones y alertas (21-ago-2026)

Cubre solo la mitad de "infracciones y alertas" del punto 2.8 del plan de mejoras. La mitad de
"mantenimiento" (poder confirmar que una reparación reportada se hizo de verdad) ya estaba
resuelta por el punto 1.8 Parte 1 (sección 83, `vig_mantenimiento_certificar` sobre la fuente
real de `ordenes_repo`) -- no se duplicó nada de eso aquí.

### Auditoría previa

Confirmado leyendo código real antes de tocar nada: `infracciones` (PocketBase) ya tenía
`resuelta`/`resolucion`/`resuelta_por`/`fecha_resolucion` escritos por `vig_infracciones_resolver()`
desde hace tiempo, pero invisibles en las 2 pantallas que los deberían mostrar (Vigilancia y
Ciclista) y en sus 4 exports Excel/PDF -- pura visibilidad, cero cambio de esquema. `alertas`
(viajes con `duracion_minutos > 120`) en cambio no tenía ningún dato de quién/cuándo/qué se hizo
(solo el booleano `alerta_atendida`), `vig_alertas_atender()` no llamaba a `registrar_auditoria`
(a diferencia de `vig_infracciones_resolver`, que sí), y `_vig_alertas_data()` solo consultaba
`estado = "activo"` -- una alerta desaparecía para siempre en cuanto el viaje terminaba, sin dejar
ningún historial consultable.

### Alertas -- gap real corregido

- `etl/22_agregar_trazabilidad_alertas.py`: agrega 3 campos `text` a la colección `viajes`
  (`alerta_atendida_por`, `alerta_fecha_atencion`, `alerta_nota`). El script ya estaba escrito de
  una ejecución anterior que se cortó antes de correrlo -- confirmado íntegro contra el plan, se
  corrió recién en esta sesión: primera corrida agregó los 3 campos (`viajes: agregados
  ['alerta_atendida_por', 'alerta_fecha_atencion', 'alerta_nota'].`), segunda corrida confirmó
  idempotencia (`los campos nuevos ya existen, sin cambios.`). Sin backfill intencional (no hay
  forma real de reconstruir quién atendió una alerta ya marcada `alerta_atendida=true` antes de
  este cambio -- se deja vacío, mismo criterio que `agente_id` en la sección 85).
- `_vig_alertas_data()` ampliada: antes solo miraba `estado = "activo"`; ahora
  `estado = "activo" || duracion_minutos > 120`, para que el historial sobreviva al cierre del
  viaje. `vig_alertas_atender()` ahora exige `nota` no vacía (rechaza con flash de error si viene
  vacía, sin escribir nada en PocketBase) y llama a `registrar_auditoria(..., modulo="viajes",
  accion="editar", ...)`, algo que antes no existía para este flujo.
- **Prueba E2E real (puerto 8006, cuenta `empleado.vig@urbanbike.com` = Miguel Torres)**: la
  pantalla ya mostraba 7 alertas reales (3 activas pendientes, 4 finalizadas ya marcadas
  `atendida` de sesiones anteriores sin atribución -- confirma que el "sin backfill" no rompe
  nada, se ven como "Atendida" con los campos de atribución en blanco). Se reutilizó un viaje real
  preexistente y finalizado (`au9bf8weq0uyp1p`, ciclista `Test Ciclista`, `duracion_minutos=995`,
  `alerta_atendida=false`) para ejercitar el flujo de escritura -- no se fabricó ningún registro
  nuevo:
  1. `POST /empleado/vigilancia/alertas/au9bf8weq0uyp1p/atender` sin `nota` -> flash de error real
     ("Indica qué acción se tomó..."), confirmado vía `UB.toast()` en la respuesta (no un
     `<div class="flash">` estático -- mismo mecanismo ya documentado en la sección 86). Verificado
     directo contra PocketBase: `alerta_atendida` seguía `False`.
  2. `POST` con `nota="Prueba E2E punto 2.8 -- se contacto al ciclista, confirmo devolucion en
     camino."` -> éxito. Verificado directo contra PocketBase: `alerta_atendida=True`,
     `alerta_atendida_por="Miguel Torres"`, `alerta_fecha_atencion="2026-08-22T02:18:43Z"`,
     `alerta_nota` con el texto exacto.
  3. Entrada real nueva en `auditoria` confirmada (`modulo="viajes"`, `accion="editar"`,
     `usuario_nombre="Miguel Torres"`, `detalle="Alerta de viaje atendida (id:
     au9bf8weq0uyp1p): Prueba E2E punto 2.8 -- ..."`, `fecha="2026-08-22T02:18:43Z"`) -- esta
     llamada no existía antes de este cambio.
  4. `GET /empleado/vigilancia/alertas` de nuevo: la fila de `au9bf8weq0uyp1p` (viaje
     `completado`) sigue apareciendo, columna "Viaje" = Finalizado, con la nota y "Miguel Torres —
     2026-08-22 02:18:43" en vez del botón -- prueba directa de que el historial ya no depende de
     que el viaje siga activo.
  5. Export real: `/empleado/vigilancia/alertas/excel` (200, `.xlsx`, 6038 bytes) y `/pdf` (200,
     `application/pdf`, 25245 bytes) -- abierto el Excel con `openpyxl`: 10 columnas, 7 filas de
     datos + fila de total, la fila de la prueba con los 3 campos de atribución reales.
  - **Sin cleanup necesario**: `au9bf8weq0uyp1p` era un viaje real preexistente, no uno fabricado
    para esta prueba -- su `alerta_atendida=True` queda como evidencia real permanente, no se
    revierte (mismo criterio ya usado en el resto del proyecto).

### Infracciones -- visibilidad corregida (sin cambio de esquema)

- Columnas nuevas "Resolución"/"Resuelta por"/"Fecha resolución" agregadas a
  `_vig_infracciones_columnas_filas()` (Vigilancia) y `_mis_infracciones_columnas_filas()`
  (Ciclista), y a sus 4 exports Excel/PDF (`fila_total` actualizado de 6→9 elementos en
  Vigilancia, de 5→8 en Ciclista).
- **Prueba E2E real (puerto 8006)**: ya existían 9 infracciones reales resueltas en el sistema
  (ninguna pendiente) -- no hizo falta resolver ninguna nueva. Verificado en Vigilancia
  (`empleado.vig@urbanbike.com`): la columna nueva muestra, p. ej., para la infracción
  `mgefixubigentog` (ciclista `3r2d6eihy391toz`), el texto real `"Todo de acuerdo."` +
  `"Empleado Vigilancia — 2026-07-05 14:46:28"`, coincidiendo exacto con lo leído directo de
  PocketBase antes de mirar el HTML. Export Excel verificado con `openpyxl`: 9 columnas, 9 filas
  reales + total, con `resolucion`/`resuelta_por`/`fecha_resolucion` reales en todas (ninguna
  vacía). Del lado Ciclista, login real como `ciclista@urbanbike.com` (dueño real de la
  infracción `mgefixubigentog`, confirmado por `ciclista_id`): `/ciclista/infracciones` muestra
  el mismo texto/nombre/fecha exactos vistos desde Vigilancia; exports Excel (200, 6175 bytes) y
  PDF (200, 25567 bytes) reales.

### Revisión independiente (antes de cerrar)

Repasado con ojo fresco después de terminar la implementación: (a) los 3 nombres de campo
coinciden exactos entre el ETL y `empleado.py` (`alerta_atendida_por`/`alerta_fecha_atencion`/
`alerta_nota`); (b) el filtro ampliado de `_vig_alertas_data()` no rompió el flujo de alertas
activas (las 3 alertas activas reales se siguieron viendo con el badge "Activo" y el botón
"Marcar atendida" intacto); (c) los 3 `fila_total` tienen el conteo correcto (alertas=10,
infracciones-Vigilancia=9, infracciones-Ciclista=8), confirmado no solo leyendo el código sino
abriendo los 3 Excel reales con `openpyxl` y contando columnas; (d) ningún template nuevo usa
`alert()`/`confirm()` nativo (grep limpio en los 3 archivos tocados); (e) el único dato de prueba
"tocado" (`au9bf8weq0uyp1p`) era un registro real preexistente, no uno fabricado -- no había nada
que limpiar. No se encontró ningún hallazgo que corregir.

### Prueba real de punta a punta -- resumen

| Verificación | Esperado | Resultado real |
|---|---|---|
| ETL corrido + idempotencia | Campos agregados 1ra vez, "sin cambios" 2da vez | Confirmado, ambas corridas |
| Rechazo sin nota | Flash de error, sin escritura en PocketBase | Confirmado (`alerta_atendida` siguió `False`) |
| Atender con nota real | `alerta_atendida_por`/`fecha_atencion`/`nota` reales | Confirmado, valores exactos verificados directo en PocketBase |
| Entrada de auditoría nueva | `modulo="viajes"`, `accion="editar"` | Confirmado, con el `viaje_id` y la nota en el `detalle` |
| Historial sobrevive al cierre del viaje | Viaje `completado` sigue en la lista | Confirmado, columna "Viaje" = Finalizado |
| Exports Alertas (Excel/PDF) | 200, 10 columnas, datos reales | Confirmado con `openpyxl` |
| Infracciones -- Vigilancia y Ciclista | Mismo texto/nombre/fecha en ambos lados | Confirmado, coincidencia exacta |
| Exports Infracciones x2 (Excel/PDF) | 200, 9 y 8 columnas respectivamente | Confirmado con `openpyxl` |
| Sin `alert()`/`confirm()` nativos | Solo `<dialog>` + `UB.toast` | Confirmado |
| Datos de prueba huérfanos | Ninguno fabricado, nada que limpiar | Confirmado (todo evidencia real reutilizada) |

**Estado del plan: RESUELTO.**

## 90. Punto 2.3 -- detalle de viaje ampliado ("Mis Viajes") (22-ago-2026)

**Auditoría previa (confirmada leyendo código real):** `/ciclista/historial` ya mostraba bicicleta,
estaciones, fecha/duración y monto/estado de pago por viaje -- bastante más que un "historial
simple". Lo que no existía en ningún lugar alcanzable desde ahí era el desglose de CÓMO se llegó a
ese monto (segmentos de modalidad, recargo por demora, descuento, IVA): ese desglose ya lo calculaba
`_construir_factura_pago()`, pero solo era visible en `/ciclista/comprobante/{pago_id}`, alcanzable
únicamente desde Historial de Pagos y solo si el pago ya estaba `pagado`. Un viaje sin pago, con pago
pendiente o rechazado no tenía ninguna vista de detalle propia.

**Refactor puro (Task 1):** la consulta SQL inline de segmentos de modalidad (`ch.query(...)` dentro
de `_construir_factura_pago()`) se extrajo a `alquileres_repo.segmentos_modalidad(viaje_id)` para
reusarla sin duplicar SQL. Verificado antes/después con el servidor real (puerto 8004): se capturó el
HTML de `/ciclista/comprobante/g8zd0jug0bnojkt` con el código viejo (`git stash`), se aplicó el
refactor y se volvió a capturar -- **idéntico byte a byte** (Subtotal $196.52, IVA $29.48, TOTAL
$226.00 en ambos casos). Sin cambio de comportamiento.

**Construido:** `_viaje_detalle_data(viaje_id, user_id)` (bicicleta, estación fin, pagos, segmentos,
factura si hay pago), con el mismo criterio de propiedad que `viaje_activo()`/`pago()`/`comprobante()`
(`viaje.ciclista_id == user_id`, si no coincide devuelve `None` -> flash + redirect, nunca expone el
viaje de otro ciclista). Ruta `GET /ciclista/historial/{viaje_id}`, insertada después de
`historial_pdf()` (no después de `historial()`) para que FastAPI no intente resolver `excel`/`pdf`
como si fueran un `viaje_id` -- confirmado leyendo el archivo real antes de insertar, no asumiendo el
orden. Plantilla `historial_detalle.html` (bicicleta, tiempos hh:mm:ss, segmentos de modalidad si
los hay, líneas de cobro + total + estado + acción según el estado del pago). Enlace "Ver detalle →"
agregado a cada fila de `historial.html`.

**Prueba E2E real (servidor real, puerto 8004, sin mocks, 100% lectura sobre datos ya existentes --
no se generó ningún dato de prueba nuevo):**

| Caso | Resultado |
|---|---|
| `/ciclista/historial` (ciclista@) | 200, enlaces "Ver detalle" presentes en todas las filas |
| Detalle propio de un viaje pagado con segmentos (`mt4599qngz92az2`) | 200, Total $226.00 -- coincide exacto con el $226.00 de la fila de Historial, 4 segmentos de modalidad reales mostrados |
| Detalle de viaje sin cobro (6 viajes reales de la cuenta sin ningún pago) | mensaje "Este viaje todavía no generó ningún cobro.", sin excepción |
| Detalle de viaje con pago `pendiente_efectivo` (`cg9k0pv9jkyllcv`) | badge correcto + botón "Pagar" (no "Ver comprobante") |
| Bypass de propiedad: `ciclista@` pidiendo un `viaje_id` real de `wacho@` (`znluw6ybwsjk1z1`) | 302 a `/ciclista/historial` (bloqueado) |
| `viaje_id` inexistente (UUID random) | 302 a `/ciclista/historial` (mismo bloqueo) |
| `/ciclista/historial/excel` y `/ciclista/historial/pdf` (regresión -- no interceptados por la ruta nueva) | 200, `application/vnd.openxmlformats...`/`application/pdf`, tamaños reales (8174/32077 bytes) |

**Sin hallazgos de alcance mayor** al punto 2.3 del plan.

**Estado del plan: RESUELTO.** Las 4 tareas de código completas y comiteadas, refactor de Task 1
verificado byte-idéntico antes/después, bypass de propiedad confirmado bloqueado, exports existentes
sin regresión.
