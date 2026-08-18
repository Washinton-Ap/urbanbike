# Modalidad de tarifa real (hora/día/semana) — diseño

**Estado**: spec resuelto, sin puntos abiertos (16 de agosto de 2026). Siguiente paso: plan de implementación (`writing-plans`).
**Contexto original**: pedido como "cambiar las 3 tarjetas de tarifa apiladas por un desplegable" (tarea 2 de la sesión). La auditoría reveló que el problema es mucho más profundo que la UI — ver "Auditoría" abajo.

## Decisión de arquitectura — dónde vive el estado de segmentos (resuelto)

El diseño original proponía una colección PocketBase nueva (`viaje_segmentos`) para todo el historial. Washington señaló que esto amplía justo lo que después hay que migrar de PocketBase (pendiente #14), y pidió probar con datos reales si ClickHouse podía sostener el patrón de "abrir/cerrar" antes de descartarlo.

**Prueba real ejecutada** (tabla `urbanbike_operativa.viaje_segmentos_test_temporal`, mismo motor `ReplacingMergeTree(version)` que ya usan `tarifas`/`alquileres`, creada, probada y **eliminada** al terminar): `ALTER TABLE ... UPDATE` "funcionó" en una tabla de 1 fila, pero es una mutación asíncrona que reescribe partes completas -- no es el patrón para escrituras frecuentes por-viaje. El patrón append-only (insertar fila nueva con `version` más reciente en vez de `UPDATE`) evita eso, pero un `SELECT` sin `FINAL` ejecutado justo después de insertar la fila de cierre devolvió **las dos filas duplicadas** -- solo `FINAL`/`argMax` daban el estado correcto.

**Decisión final (Washington), híbrida -- evita los dos problemas de raíz en vez de elegir un lado**:

- **Estado del segmento ABIERTO (en vivo, mientras el viaje sigue `activo`)**: vive en **PocketBase**, como 2 campos nuevos y ligeros en la propia colección `viajes` -- `modalidad_actual` (select `hora`/`dia`/`semana`) e `inicio_segmento_actual` (fecha/hora ISO). Es estado transitorio de un viaje en curso, coherente con lo que PocketBase ya sostiene hoy (`fecha_inicio`, `fecha_fin`, `estado`) -- no le suma ninguna responsabilidad transaccional nueva, solo 2 campos más en una colección que ya existe.
- **Segmentos CERRADOS (historial, ya con costo resuelto)**: se insertan en **`urbanbike_operativa.alquileres`** (ClickHouse) -- reutilizando sus columnas ya existentes (`modalidad`, `fecha_inicio`, `fecha_fin`, `subtotal`, `recargo`, `total`, `estado='completado'`, `id_origen_pocketbase = viaje_id`), sin tabla nueva. **Append-only puro**: cada fila se inserta ya completa (inicio y fin resueltos, costo calculado) -- nunca se hace `UPDATE` sobre una fila ya insertada, así que el riesgo de duplicados de la prueba de arriba **no puede ocurrir**: no hay ninguna fila "a medio cerrar" en ClickHouse en ningún momento.

Este diseño evita las dos mutaciones point-write que ClickHouse desaconseja (nunca hay `ALTER UPDATE` ni una fila que se reescribe) y evita ampliar la superficie transaccional de PocketBase más allá de 2 campos sobre una colección que ya es el corazón del flujo del ciclista.

## Auditoría — por qué esto no es un cambio de UI

Evidencia real recogida el 16 de agosto de 2026 contra el código y los esquemas reales de PocketBase/ClickHouse:

1. **La ficha (`ciclista/detalle_bicicleta.html:184-235`) ya muestra 3 modalidades reales y correctas** — precio por categoría, con promociones, desde `_catalogo_bicicletas()` (`ciclista.py:165-292`), que lee `urbanbike_operativa.tarifas` (ClickHouse). Esto es solo presentación, está bien construido.
2. **No existe ningún mecanismo de selección real, en ningún punto del sistema**:
   - `POST /ciclista/reservar` no tiene parámetro `modalidad`.
   - La colección `viajes` de PocketBase no tiene campo `modalidad` (confirmado contra el esquema real vía API admin).
   - El toggle de modalidad en `ciclista/alquilar.html` (`#catalogo-modalidad`) es un swap puramente client-side de qué precio se muestra por tarjeta — no viaja a ningún lado al hacer clic en "Alquilar esta bicicleta".
3. **El cobro real (`_tarifa_hora()`, duplicada en `ciclista.py:295` y `empleado.py:53`) lee una colección DISTINTA y más pobre**: PocketBase `tarifas` (`tipo_bicicleta` classic/electric × `tipo_usuario` casual/member × un único `precio_hora`, sin categoría, sin día, sin semana — confirmado contra el esquema real). Es la misma duplicación que la sección 21 de la hoja de ruta ya documentó y arregló solo del lado del editor del Gerente, nunca del lado del cobro.
4. **Conclusión**: hoy, sin importar qué modalidad se muestre o se "elija" en cualquier pantalla, el sistema siempre cobra por hora, medido de forma continua. Día y semana son precios decorativos.
5. **Coincidencia frágil detectada**: los precios "hora" de ambas fuentes coinciden hoy numéricamente (Premium/Estándar/Montaña todas cobran igual por hora en ClickHouse, igual que `classic_bike` en PocketBase) — pero son tablas independientes sin sincronización; cualquier edición futura del Gerente sobre una categoría específica divergiría en silencio.

## Decisiones de negocio (confirmadas con Washington)

| Pregunta | Decisión |
|---|---|
| ¿Qué significa cobrar por día/semana? | Tarifa **plana** por ventana fija (ej. pase de 24h/7 días desde que empieza ese tramo), no metered por hora. |
| ¿Qué pasa si se excede la ventana comprada sin reportar devolución? | Se trata **igual que el recargo por demora de la tarea 1** (gracia de 5h + recargo aparte) — mismo mecanismo, cambia el punto de referencia. |
| ¿Se puede cambiar de modalidad a mitad de viaje? | **Sí**, mientras el viaje sigue `activo`. |
| ¿Cómo se cobra el tramo anterior al cambiar? | Se **cierra y cobra como un segmento propio** (como si el viaje terminara y empezara uno nuevo en ese instante) — nunca se recalcula el viaje completo con la modalidad nueva. |
| ¿Una sola fuente de precios? | **Sí** — se elimina la colección vieja de PocketBase `tarifas`; todo el cobro real pasa a leer `urbanbike_operativa.tarifas` (ClickHouse), la misma tabla que ya edita el Gerente. Cierra la duplicación de la sección 21. |
| ¿Modalidad por defecto al abrir la ficha? | **Hora** — la más simple y la única real hoy. |

## Diseño

### 1. Fuente única de precios

`_tarifa_hora()` (ambas copias, `ciclista.py` y `empleado.py`) se reemplaza por una función que resuelve `id_categoria` a partir del código/id de la bicicleta (join `bicicletas` → `modelos_bicicleta` → `categorias`, mismo patrón que ya usa `_catalogo_bicicletas()`) y reutiliza `_tarifas_por_categoria()` (ya existe, `ciclista.py:54-74`, hoy usada solo para el catálogo) para obtener el precio de la modalidad pedida. Se extrae `_tarifas_por_categoria()` a un módulo compartido (ej. `app/db/tarifas_repo.py`, que ya existe para el editor del Gerente) para que `empleado.py` no la duplique.

**Migración de la colección vieja -- corregido tras auditoría real (Prioridad 3)**: la premisa original ("nada depende de conservarla") era incorrecta. Auditado con grep completo de `app/` + esquema real de `pagos` (que guarda el precio ya resuelto, nunca un id de tarifa -- **sin riesgo de facturas históricas rotas**, eso sí estaba bien). Pero hay **2 dependencias de código vivo, reales, que rompen si se borra la colección sin tocarlas antes**:

1. `gerente.py` (~línea 1554, pantalla `gerente/informe.html` -- "Informe General"): `precio_promedio`/`ingresos_estimados` se calculan promediando `precio_hora` de esta colección. Hay que migrar este cálculo a `urbanbike_operativa.tarifas` (mismo criterio que `_tarifa_hora()` nueva) antes de borrar.
2. `ciclista.py:alquilar()` (línea 492) pasa esta colección como `tarifas_json` al template; `ciclista/alquilar.html` la usa en `tarifaPara()` (JS, línea 189) para el panel de bicicletas que aparece al hacer clic en una estación del mapa. **Hallazgo aparte, real, no relacionado con el borrado**: ese panel hoy ya muestra un precio distinto (solo por hora, sin modalidad, sin promoción, solo tarifa member) al que muestra la tarjeta principal del catálogo para la misma bicicleta -- es la misma clase de bug de "dos fuentes de verdad" que esta tarea ya está resolviendo en otro lado, sin resolver todavía en este panel del mapa. Se corrige de paso: ese panel pasa a usar `catalogo_bicicletas`/`_catalogo_bicicletas()` como el resto de la página, en vez de `tarifaPara()`.

Con ambos puntos corregidos, sí se puede eliminar la colección PocketBase `tarifas` (hoy 5 filas) sin dejar nada roto.

### 2. Modelo de datos — segmentos de modalidad

**Campos nuevos en `viajes` (PocketBase)** -- el segmento abierto/en vivo:

| Campo | Tipo | Nota |
|---|---|---|
| `modalidad_actual` | select (`hora`/`dia`/`semana`) | modalidad del segmento en curso |
| `inicio_segmento_actual` | text (ISO) | cuándo empezó ESTE segmento (no necesariamente igual a `viajes.fecha_inicio`, si ya hubo cambios de modalidad antes) |

**Filas nuevas en `urbanbike_operativa.alquileres` (ClickHouse)** -- el historial de segmentos ya cerrados, reusando columnas existentes, nunca `UPDATE`:

| Columna existente reusada | Contenido |
|---|---|
| `id_origen_pocketbase` | `viaje_id` (PocketBase) -- así se agrupan todos los segmentos de un mismo viaje |
| `modalidad` | modalidad de ese segmento |
| `fecha_inicio` | `inicio_segmento_actual` del segmento que se está cerrando |
| `fecha_fin` | momento real del cierre (cambio de modalidad, o fin de viaje) |
| `subtotal`/`recargo`/`total` | costo resuelto de ESE segmento (ver fórmula, punto 4) -- ya congelado, nunca se vuelve a tocar esta fila |
| `estado` | `'facturado'` siempre (reusa un valor real ya existente en el vocabulario de `alquileres.estado` -- `reservado`/`en_curso`/`cancelado`/`facturado`/`devuelto`, nunca se inventa uno nuevo como `'completado'`) -- nunca se inserta una fila a medio resolver |
| `id_bicicleta`/`id_usuario`/`id_estacion_inicio` | se dejan en su valor por defecto (no hay una forma real de resolverlos sin un join innecesario) -- **verificado con datos reales** que esto excluye las filas de segmento del `INNER JOIN` que usa `app/db/alquileres_repo.py` (el repo real del WorkPanel de Operación, ya existente, `listar()`/`obtener()`), así que no contaminan esa pantalla (ver plan de implementación, Tarea 6) |
| `id_tarifa` | id real de la fila de `urbanbike_operativa.tarifas` usada para ese segmento (categoría/membresía/modalidad) |

Un viaje puede tener 0 filas en `alquileres` (todavía no cerró ningún segmento -- sigue en su primer y único segmento) hasta N filas (una por cada cambio de modalidad + la del cierre final del viaje).

### 2.1 Viajes ya en curso al momento del deploy (Prioridad 2, resuelto -- confirmado por Washington, son datos reales suyos)

**Dato real, auditado el 16 de agosto de 2026**: hay **3 viajes reales `activo`** en el sistema en este momento (0 en `pendiente_validacion`), confirmados por Washington como pruebas reales propias.

Con el modelo híbrido, la migración retroactiva es más simple que en el diseño anterior -- no hace falta insertar nada en ClickHouse (esos viajes todavía no cerraron ningún segmento), solo **backfillear los 2 campos nuevos de PocketBase**: para todo viaje con `estado in ('activo', 'pendiente_validacion')` al momento del deploy, `modalidad_actual = 'hora'` (la única modalidad que existió antes de este cambio) e `inicio_segmento_actual = viajes.fecha_inicio` (su propio inicio real, porque nunca hubo un cambio de modalidad antes de existir este campo). Sin esto, `vig_devolver()` no tendría de dónde leer la modalidad al intentar finalizar esos 3 viajes reales -- **decisión confirmada: se hace la migración retroactiva**, agregada como tarea explícita del plan de implementación.

### 3. Endpoint nuevo: cambiar modalidad a mitad de viaje

`POST /ciclista/cambiar-modalidad` (nuevo, `ciclista.py`): recibe `viaje_id` + `modalidad_nueva`. Válido solo si el viaje está `activo` (no `pendiente_validacion` ni `completado`).

1. Lee `viajes.modalidad_actual` + `inicio_segmento_actual` (PocketBase) -- el segmento que se está cerrando.
2. Calcula su costo con la fórmula del punto 4 (`hora` metered, `dia`/`semana` plano).
3. **Inserta la fila cerrada en `urbanbike_operativa.alquileres`** (append-only, ver punto 2) -- nunca `UPDATE`.
4. **Actualiza `viajes`** (PocketBase, `UPDATE` normal, sin ningún problema porque es su rol real): `modalidad_actual = modalidad_nueva`, `inicio_segmento_actual = ahora`.

### 4. Fórmula de cobro (reemplaza el cálculo de `subtotal` en `vig_devolver()`)

Por cada segmento del viaje:
- `modalidad == 'hora'`: `duración_del_segmento_en_horas × precio_hora_del_segmento` (igual que hoy).
- `modalidad in ('dia', 'semana')`: el `precio` congelado del segmento, completo, sin prorratear — se cobra aunque el segmento dure menos que la ventana.

`vig_devolver()` hace 2 cosas nuevas antes de armar el pago:
1. Cierra el ÚLTIMO segmento (el que estaba abierto en `viajes.modalidad_actual`/`inicio_segmento_actual`) con la hora real de confirmación de Vigilancia -- mismo criterio de siempre (nunca con la hora que reportó el ciclista) -- e inserta esa fila en `alquileres` (append-only, igual que un cambio de modalidad, punto 3).
2. Lee **todos** los segmentos cerrados de ese viaje desde `alquileres` (`WHERE id_origen_pocketbase = viaje_id`, sin necesidad de `FINAL` porque nunca hay más de una fila por segmento -- cada fila se escribe una sola vez y no se vuelve a tocar) y suma sus `total` -> `subtotal_viaje = Σ total de cada segmento`.

**Recargo por demora (reutiliza el mecanismo de la tarea 1, sección 70, sin duplicar la lógica de gracia/recargo)**: se aplica sobre el ÚLTIMO segmento únicamente.
- Si el último segmento es `hora`: igual que hoy — gracia de 5h desde `viaje.fecha_fin` (cuando el ciclista reportó la devolución).
- Si el último segmento es `dia`/`semana`: la gracia de 5h empieza a contar desde que termina la ventana comprada de ese segmento (`viajes.inicio_segmento_actual + 24h` para día, `+7d` para semana), **no** desde `fecha_fin` reportada — porque con tarifa plana, "demora" significa exceder lo que se pagó, no la validación en sí.
- El recargo, en ambos casos, se sigue calculando a la tarifa **hora** de la misma categoría/membresía (no existe un "recargo por día" — sería una tarifa plana adicional injustificada por unos minutos de más).

Ejemplo numérico (categoría Estándar, casual, `precio_hora=$4.5`, `precio_dia=$22.4`):
- Ciclista reserva con modalidad `día` a las 09:00. Reporta devolución a las 09:00 del día siguiente (24h exactas, dentro de ventana): `subtotal = $22.40`, `recargo = $0`.
- Mismo caso, pero reporta a las 15:30 del día siguiente (6.5h después de cerrarse la ventana de 24h, ya pasadas las 5h de gracia): `recargo = 1.5h × $4.5 = $6.75`. Factura: "Tarifa día" $22.40 + "Recargo por demora (>5h)" $6.75.
- Ciclista reserva por `hora`, a las 20h de viaje cambia a `día`: segmento 1 (`hora`, 20h) = `20 × $4.5 = $90`; segmento 2 (`día`, se cobra completo aunque dure 3h) = `$22.40`. `subtotal = $112.40`. (Nota: este caso puede dar un total más caro que quedarse en una sola modalidad — es una decisión del ciclista, el sistema no optimiza por él.)

**Cambios múltiples de modalidad en el mismo viaje (Prioridad 4, declarado explícitamente)**: **sí están permitidos, sin límite de cantidad**, y **cada segmento cerrado se cobra completo según la fórmula de arriba**, sin excepción ni tope acumulado. Ejemplo: `día` → `hora` → `semana` en un mismo viaje genera 3 segmentos, cada uno cobrado íntegro (el de `día` completo aunque haya durado 10 minutos antes de cambiar). Esto es una consecuencia directa y aceptada de la Decisión de negocio "el sistema no optimiza por el ciclista" -- no hay protección contra que alguien encadene cambios de forma poco conveniente para sí mismo; si en el futuro se quiere limitar (ej. máximo 1 cambio por viaje, o un cooldown entre cambios), es una decisión de negocio nueva, fuera de este spec.

### 5. UI

- `detalle_bicicleta.html`: las 3 tarjetas apiladas se reemplazan por un `<select>` con la modalidad (default `hora`) y su precio actualizándose al cambiar — mismo patrón visual que ya existe en `alquilar.html` para el toggle, pero como selección real que viaja en el form de "Reservar".
- `viaje_activo.html`: nuevo control (mientras `estado == 'activo'`, no en `pendiente_validacion`) para cambiar de modalidad, que llama al endpoint nuevo y refresca la página con el segmento nuevo activo.
- `empleado/vigilancia/devoluciones.html`: sin cambios de layout — el "monto en vivo" ya está pensado para desglose (tarea 1), solo cambia qué segmento(s) lee.

### 6. `costo-en-vivo.js`

`costoDetallado()` deja de recibir un único `precioHora` global. El router (`ciclista.py`/`empleado.py`) resuelve server-side, en cada render, la suma de segmentos ya cerrados (`SELECT sum(total) FROM alquileres WHERE id_origen_pocketbase = viaje_id` -- un número fijo, ya congelado, sin necesidad de `FINAL`) y la pasa al template como `subtotal_segmentos_cerrados`. El JS solo necesita seguir "metered" en tiempo real el segmento **abierto** (`modalidad_actual`, `inicio_segmento_actual`, precio de esa modalidad) y sumarle ese fijo -- nunca recalcula los segmentos cerrados. Mismo patrón que ya establece la tarea 1: el frontend nunca decide el monto final, solo refleja lo que `vig_devolver()` calculará con la misma fórmula.

## Fuera de alcance (explícitamente, para no repetir la disciplina de la tarea 1)

- Conectar `minutos_gracia`/`recargo_minuto` (columnas ya existentes en `urbanbike_operativa.tarifas`, sin usar) para reemplazar el `MINUTOS_GRACIA_DEMORA = 300` hardcodeado — sería natural hacerlo en esta misma tarea, pero es una ampliación de alcance aparte; se deja anotado como oportunidad, no se resuelve aquí.
- Migrar el flujo del ciclista de PocketBase a ClickHouse (pendiente #14, ya documentado desde antes) — este diseño sigue viviendo en PocketBase para `viajes` (con los 2 campos nuevos del segmento abierto); el historial de segmentos cerrados va a `alquileres` (ClickHouse) desde ya, pero el viaje en sí y su estado en vivo siguen 100% en PocketBase, sin cambiar el alcance de la migración pendiente #14.
- Forzar el cierre de un viaje que nunca se reporta (ni hoy ni con este diseño hay un timeout real de un viaje `activo` abandonado) — preexistente, no es un hueco nuevo de día/semana.
- Reportes de ClickHouse (`resumen_viajes_diario`, informes tácticos): sin impacto, porque el flujo real del ciclista no escribe ahí hoy (pendiente #14).
- **Verificación de cobertura de tiempo entre segmentos, riesgo aceptado documentado (16 de agosto de 2026)**: `POST /ciclista/cambiar-modalidad` escribe primero en PocketBase y después inserta el segmento cerrado en ClickHouse (orden decidido a propósito, ver Tarea 6 del plan) -- si el `INSERT` de ClickHouse falla justo después de que PocketBase ya confirmó el cambio, ese tramo específico queda sin registrar en el historial, y `alquileres_repo.total_segmentos_cerrados()` (usada por `vig_devolver()`, Tarea 7) solo suma lo que existe, no lo que debería existir -- el cobro final quedaría incompleto **en silencio**, sin ningún aviso. Es detectable en teoría (sumar la duración real de los segmentos existentes y compararla contra el tiempo total real del viaje revelaría el hueco), pero **no se construye ahora**: decidido con Washington no agregarlo, porque abre decisiones de negocio nuevas sin resolver (¿bloquea el pago si hay un hueco? ¿solo avisa a Vigilancia? ¿qué tolerancia de segundos es razonable?) que amplían el alcance real de la Tarea 7. Riesgo evaluado como bajo en la práctica: cero fallas reales de ClickHouse/PocketBase observadas en las Tareas 1-6 (docenas de operaciones reales, ambos servicios locales en Docker, sin salto de red). Nota agravante: `cambiar_modalidad()` tampoco deja rastro en `registrar_auditoria()` cuando esto falla -- ni Vigilancia ni Admin tendrían forma de reconstruirlo después, más allá del mensaje que vio el ciclista una sola vez. Queda como oportunidad para otra sesión, no como pendiente de esta.

## Pruebas previstas (mismo criterio de todo el proyecto: datos reales, sin simular, limpieza al terminar)

1. Viaje completo en modalidad `hora`, dentro de gracia y fuera de gracia — confirmar que el comportamiento de la tarea 1 no cambió (regresión).
2. Viaje completo en modalidad `día`: reportar dentro de la ventana (recargo $0) y después de la ventana + 5h (recargo > 0, calculado a precio_hora).
3. Viaje con cambio de modalidad a mitad de camino: confirmar 1 fila real nueva en `alquileres` (el segmento cerrado) justo después de `POST /ciclista/cambiar-modalidad`, `viajes.modalidad_actual`/`inicio_segmento_actual` actualizados al segmento nuevo, y al finalizar, factura con 2 líneas (una por segmento) cuyo total coincide con la suma real de `alquileres.total` para ese `viaje_id` + el segmento final.
4. Confirmar que `_tarifa_hora()` nueva (leyendo ClickHouse) devuelve el mismo precio que ve el ciclista en la ficha para la misma categoría/membresía/modalidad — cierra el hallazgo de "dos fuentes de verdad".
5. Confirmar que `gerente/informe.html` y el panel de mapa de `ciclista/alquilar.html` (Prioridad 3) siguen funcionando y muestran precios consistentes con el resto del sistema después de migrarlos.
6. Confirmar la migración retroactiva (Prioridad 2) contra los viajes reales `activo`/`pendiente_validacion` existentes al momento del deploy -- cada uno debe terminar con `modalidad_actual = 'hora'` e `inicio_segmento_actual` poblado correctamente (sin ninguna fila nueva en `alquileres` todavía, porque ese primer segmento sigue abierto hasta que el viaje real cierre o cambie de modalidad).
7. Confirmar que tras eliminar la colección PocketBase `tarifas`, ningún código vivo la referencia (grep completo de `app/`).
