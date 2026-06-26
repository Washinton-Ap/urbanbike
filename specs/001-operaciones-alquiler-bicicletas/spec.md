# Feature Specification: Operaciones de Alquiler de Bicicletas (Nivel Operativo)
 
**Feature Branch**: `001-operaciones-alquiler-bicicletas`

**Created**: 2026-06-20

**Status**: Draft

**Input**: User description: "Especificación del Sistema Operativo de UrbanBike S.A. — Nivel empresarial Operativo (ejecución diaria del servicio de alquiler de bicicletas), cubriendo los paquetes Gestión de Clientes y Reservas, Gestión de Viajes y Pagos, Gestión de Flota e Inspección, y Monitoreo y Devoluciones, con los actores Ciclista, Empleado de Operación, Empleado de Mantenimiento, Empleado de Vigilancia, Pasarela de Pago (sistema externo) y Sistema (automático), y los 17 casos de uso CU-O01 a CU-O17 detallados por el usuario."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Registro y reserva de bicicleta (Priority: P1)

Como ciclista nuevo, quiero registrarme con mis datos personales y luego ver y reservar una
bicicleta disponible en una estación cercana mediante un mapa interactivo, para asegurar su
disponibilidad antes de llegar a la estación.

**Casos de uso cubiertos**: CU-O01 (Registrar cliente), CU-O02 (Reservar bicicleta), CU-O03
(Verificar disponibilidad).

**Why this priority**: Sin un ciclista registrado y sin la capacidad de localizar y asegurar una
bicicleta, ningún otro caso de uso del sistema puede ejecutarse. Es el punto de entrada
obligatorio de todo el flujo de negocio.

**Independent Test**: Puede probarse de forma aislada registrando un ciclista nuevo, consultando
la disponibilidad en una estación y reservando una bicicleta, verificando que queda apartada
exclusivamente para ese ciclista.

**Acceptance Scenarios**:

1. **Given** una persona sin cuenta, **When** completa el registro con sus datos personales
   válidos, **Then** el sistema crea una cuenta de ciclista activa (CU-O01).
2. **Given** un ciclista registrado consultando una estación, **When** abre el mapa interactivo,
   **Then** ve en tiempo real las bicicletas disponibles en esa estación y en estaciones cercanas
   (CU-O03).
3. **Given** una bicicleta disponible en una estación, **When** el ciclista la reserva, **Then**
   el sistema inicia el viaje en el mismo instante (mismo evento técnico que CU-O04 — no existe un
   estado "reservado" intermedio ni expiración por tiempo), la bicicleta pasa a "en uso"
   exclusivamente para ese ciclista y deja de aparecer como disponible para otros (CU-O02).
4. **Given** una bicicleta en uso por un ciclista, **When** otro ciclista intenta reservar la misma
   bicicleta, **Then** el sistema rechaza la solicitud al no estar disponible (CU-O02).

---

### User Story 2 - Viaje completo y pago (Priority: P1)

Como ciclista, quiero que mi viaje inicie en el mismo instante en que reservo una bicicleta,
finalizarlo al devolverla, conocer el costo calculado automáticamente, pagarlo con el método de mi
preferencia, recibir un comprobante y poder consultar mi historial.

**Casos de uso cubiertos**: CU-O04 (Iniciar viaje), CU-O05 (Finalizar viaje), CU-O06 (Calcular
costo del viaje), CU-O07 (Procesar pago), CU-O10 (Generar comprobante), CU-O11 (Consultar
historial).

**Why this priority**: Es el ciclo de valor central del negocio: sin esta historia no existe
ingreso ni servicio prestado. Junto con la Historia 1, constituye el MVP mínimo operable.

**Independent Test**: Puede probarse de forma aislada llevando una bicicleta reservada a través
de inicio de viaje, fin de viaje, cálculo de costo, pago (en cualquiera de los tres métodos) y
verificando que el comprobante y el historial reflejan la transacción.

**Acceptance Scenarios**:

1. **Given** un ciclista que reserva una bicicleta disponible, **When** confirma la reserva,
   **Then** el sistema marca el inicio del viaje en ese mismo instante y comienza a medir tiempo
   (CU-O02, CU-O04 — mismo evento técnico, sin paso de "retiro" separado).
2. **Given** un viaje en curso, **When** el ciclista devuelve la bicicleta en una estación,
   **Then** el sistema marca el fin del viaje y calcula su duración (CU-O05).
3. **Given** un viaje recién finalizado, **When** el sistema procesa su cierre, **Then** calcula
   el costo según la duración y el tipo de bicicleta, sin intervención manual (CU-O06).
4. **Given** un costo de viaje calculado, **When** el ciclista elige pagar con tarjeta, efectivo o
   transferencia, **Then** el sistema registra el intento de pago con el método elegido (CU-O07).
5. **Given** un pago confirmado (por cualquier método), **When** se completa la confirmación,
   **Then** el sistema genera un comprobante imprimible asociado a ese pago y a ese viaje
   (CU-O10).
6. **Given** un ciclista con viajes y pagos previos, **When** consulta su historial, **Then** ve
   la lista completa de sus viajes, costos, métodos de pago y comprobantes (CU-O11).
7. **Given** un ciclista con un pago pendiente de confirmación o en disputa, **When** intenta
   iniciar un nuevo viaje, **Then** el sistema lo bloquea hasta que ese pago se resuelva.

---

### User Story 3 - Conciliación de pagos manuales (Priority: P2)

Como empleado de operación, quiero confirmar manualmente los pagos en efectivo y validar los
comprobantes de transferencia subidos por el ciclista, para mantener la trazabilidad financiera
exigida por la empresa.

**Casos de uso cubiertos**: CU-O08 (Confirmar pago en efectivo), CU-O09 (Verificar comprobante de
transferencia).

**Why this priority**: Es indispensable para cerrar el ciclo financiero de los pagos no
electrónicos, pero el negocio puede operar de forma limitada (solo pagos con tarjeta) mientras
esta historia no esté disponible, por lo que es secundaria frente al ciclo de viaje y pago
electrónico.

**Independent Test**: Puede probarse de forma aislada generando un pago en efectivo y un pago por
transferencia con comprobante adjunto, y verificando que un empleado de operación puede
confirmarlos o rechazarlos de forma independiente del resto del sistema.

**Acceptance Scenarios**:

1. **Given** un pago en efectivo pendiente, **When** un empleado de operación confirma su
   recepción, **Then** el pago queda marcado como confirmado y auditado con el responsable y la
   fecha (CU-O08).
2. **Given** un comprobante de transferencia subido por el ciclista, **When** un empleado de
   operación lo revisa, **Then** puede aprobarlo (confirmando el pago) o rechazarlo (dejándolo
   pendiente para que el ciclista lo corrija) (CU-O09).

---

### User Story 4 - Gestión de flota e inspección (Priority: P2)

Como empleado de mantenimiento, quiero registrar órdenes de mantenimiento cuando una bicicleta
presenta una falla y completar un checklist de inspección de 7 puntos, para garantizar que solo
circulen bicicletas en condiciones óptimas.

**Casos de uso cubiertos**: CU-O12 (Registrar orden de mantenimiento), CU-O13 (Ejecutar checklist
de inspección), CU-O14 (Actualizar estado de bicicleta).

**Why this priority**: Protege la calidad y seguridad de la flota, pero una ciudad puede iniciar
operaciones con un proceso de mantenimiento más manual mientras esta historia no esté disponible,
por lo que no bloquea el MVP del ciclo de viaje y pago.

**Independent Test**: Puede probarse de forma aislada registrando una orden de mantenimiento para
una bicicleta, completando su checklist de inspección y verificando que el estado de la bicicleta
cambia de forma consistente con el resultado.

**Acceptance Scenarios**:

1. **Given** una bicicleta con una falla reportada, **When** un empleado de mantenimiento registra
   una orden, **Then** la bicicleta pasa a estado "mantenimiento" y queda fuera de disponibilidad
   para reserva (CU-O12).
2. **Given** una bicicleta en mantenimiento, **When** un empleado de mantenimiento completa el
   checklist de 7 puntos, **Then** el resultado agregado de la inspección determina el nuevo
   estado de la bicicleta; el checklist se evalúa al vuelo y no se persiste punto por punto
   (CU-O13).
3. **Given** un checklist completado con todos los puntos aprobados, **When** se cierra la
   inspección, **Then** la bicicleta vuelve a estado "disponible" (CU-O13, CU-O14).
4. **Given** un checklist completado con al menos un punto reprobado, **When** se cierra la
   inspección, **Then** la bicicleta permanece en estado "mantenimiento" (CU-O13, CU-O14).
5. **Given** cualquier evento que afecte a una bicicleta (reserva, inicio/fin de viaje, orden de
   mantenimiento, resultado de checklist, devolución confirmada), **When** dicho evento ocurre,
   **Then** el sistema actualiza automáticamente el estado de la bicicleta sin intervención manual
   (CU-O14).

---

### User Story 5 - Monitoreo y devoluciones (Priority: P3)

Como empleado de vigilancia, quiero visualizar los viajes activos en tiempo real, recibir alertas
de retraso y confirmar la devolución física de las bicicletas, para detectar anomalías y cerrar
correctamente el ciclo del viaje.

**Casos de uso cubiertos**: CU-O15 (Monitorear viaje activo), CU-O16 (Generar alerta de retraso),
CU-O17 (Registrar devolución).

**Why this priority**: Es una capa de supervisión y control adicional sobre un ciclo de viaje que
ya funciona de forma autónoma (Historia 2); aporta seguridad operativa pero no es indispensable
para que un viaje individual se complete y se cobre.

**Independent Test**: Puede probarse de forma aislada con uno o más viajes activos simulados,
verificando que aparecen en el panel de monitoreo, que se genera una alerta al superar 120 minutos,
y que un empleado de vigilancia puede registrar la devolución física de una bicicleta.

**Acceptance Scenarios**:

1. **Given** uno o más viajes en curso, **When** un empleado de vigilancia abre el panel de
   monitoreo, **Then** ve la lista de viajes activos con su tiempo transcurrido y estación de
   origen (CU-O15).
2. **Given** un viaje activo, **When** su tiempo transcurrido supera 120 minutos, **Then** el
   sistema genera una alerta dirigida al personal de vigilancia (CU-O16).
3. **Given** una alerta de retraso generada, **When** el personal de vigilancia la atiende,
   **Then** el viaje permanece activo y abierto hasta que se resuelva manualmente (contacto con el
   ciclista o reporte de pérdida); el sistema no cobra ni cierra el viaje de forma automática
   (CU-O16).
4. **Given** una bicicleta físicamente devuelta en una estación, **When** un empleado de
   vigilancia confirma la devolución, **Then** el sistema registra dicha confirmación como cierre
   del ciclo de viaje (CU-O17).

---

### Edge Cases

- ¿Qué ocurre si dos ciclistas intentan reservar la misma bicicleta al mismo tiempo? Solo la
  primera solicitud se confirma; la segunda es rechazada porque la bicicleta ya pasó a "en uso" en
  el mismo instante de la primera reserva (no existe una ventana de espera entre reservar y usar).
- ¿Qué ocurre si la estación de destino no tiene espacio físico para anclar la bicicleta al
  finalizar el viaje? El ciclista debe finalizar el viaje en otra estación con espacio disponible;
  el viaje permanece activo hasta que se complete una devolución válida.
- ¿Qué ocurre si el pago con tarjeta es rechazado o la pasarela de pago no responde? El sistema
  conserva el viaje con el pago en estado pendiente y permite reintentar el pago o usar otro
  método; el ciclista queda bloqueado para nuevos viajes mientras el pago no se resuelva.
- ¿Qué ocurre si un ciclista con un pago pendiente o en disputa intenta iniciar un nuevo viaje? El
  sistema lo bloquea hasta que el pago pendiente se confirme o se rechace.
- ¿Qué ocurre si un comprobante de transferencia es ilegible o inválido? El empleado de operación
  lo rechaza y el pago queda pendiente para que el ciclista suba un nuevo comprobante.
- ¿Qué ocurre si se necesita poner una bicicleta en mantenimiento mientras está en uso por un
  ciclista? El cambio de estado por mantenimiento se aplica solo cuando el viaje asociado finaliza
  o se cancela; no interrumpe un viaje en curso.
- ¿Qué ocurre si un viaje supera los 120 minutos y la bicicleta nunca se devuelve? El sistema
  mantiene el viaje activo y alerta a vigilancia; la resolución (contacto con el ciclista, reporte
  de pérdida, eventual cobro) es siempre una decisión manual del personal, nunca automática.
- ¿Qué ocurre si una bicicleta reprueba uno o más puntos del checklist de inspección? Permanece en
  estado "mantenimiento" y no puede reservarse hasta aprobar una nueva inspección completa.

## Requirements *(mandatory)*

### Functional Requirements

**Gestión de Clientes y Reservas**

- **FR-001**: El sistema DEBE permitir que una persona nueva se registre como ciclista
  proporcionando nombre, datos de contacto, contraseña, identificación nacional y fecha de
  nacimiento, creando una cuenta activa al validarse correctamente (CU-O01).
- **FR-002**: El sistema DEBE exigir que el ciclista tenga al menos 18 años para completar el
  registro, rechazando solicitudes que no cumplan este requisito (CU-O01).
- **FR-003**: El sistema DEBE mostrar, para cualquier estación seleccionada en el mapa
  interactivo, el conteo e identificación de bicicletas disponibles en tiempo real, reflejando los
  eventos de reserva, viaje y mantenimiento más recientes (CU-O03).
- **FR-004**: El sistema DEBE permitir que un ciclista registrado reserve una bicicleta disponible
  en una estación mediante un mapa interactivo de estaciones cercanas (CU-O02).
- **FR-005**: El sistema DEBE asignar una bicicleta en exclusiva a un único ciclista en el momento
  de reservarla, cambiando su estado a "en uso" de inmediato, impidiendo que cualquier otro
  ciclista la reserve simultáneamente (CU-O02; confirmado contra `app/routers/ciclista.py`).
- **FR-006**: El sistema NO mantiene un estado de reserva independiente ni una expiración por
  tiempo: reservar una bicicleta es el mismo evento técnico que iniciar el viaje (ver FR-007), sin
  paso intermedio (CU-O02; confirmado contra `app/routers/ciclista.py`).

**Gestión de Viajes y Pagos**

- **FR-007**: El sistema DEBE iniciar el viaje en el mismo instante en que el ciclista reserva la
  bicicleta (mismo evento técnico que FR-004–FR-006, sin paso de "retiro" separado), registrando
  la hora de inicio y cambiando el estado de la bicicleta a "en uso" (CU-O02, CU-O04; confirmado
  contra `app/routers/ciclista.py`).
- **FR-008**: El sistema DEBE bloquear una nueva reserva/viaje para cualquier ciclista que (a)
  tenga al menos un pago en `pagos` con `estado="pendiente_efectivo"` o
  `estado="verificacion_pendiente"`, o (b) tenga más de 2 pagos con `estado="rechazado"`. El
  bloqueo se calcula en tiempo de ejecución en cada intento de reserva (`POST /ciclista/reservar`);
  no existe ningún campo persistido de "bloqueado" en `users` (CU-O02, CU-O04; confirmado contra la
  función `reservar()` en `app/routers/ciclista.py`; Principio IV de la constitución del proyecto).
- **FR-009**: El sistema DEBE permitir finalizar un viaje cuando el ciclista devuelve la bicicleta
  en una estación, registrando la hora y la estación de devolución (CU-O05).
- **FR-010**: El sistema DEBE calcular automáticamente, al finalizar cada viaje, el costo según la
  duración del viaje y la tarifa correspondiente al tipo de bicicleta utilizada (CU-O06).
- **FR-011**: El sistema DEBE permitir que el ciclista pague el costo calculado mediante tarjeta,
  efectivo o transferencia bancaria (CU-O07).
- **FR-012**: El sistema DEBE enviar los pagos con tarjeta a la pasarela de pago externa y
  registrar la confirmación o el rechazo que esta devuelva (CU-O07).
- **FR-013**: El sistema DEBE permitir que un empleado de operación confirme manualmente un pago
  en efectivo, registrando quién lo confirmó y en qué momento (CU-O08).
- **FR-014**: El sistema DEBE permitir que un ciclista adjunte un comprobante de transferencia a un
  pago, y que un empleado de operación lo apruebe o lo rechace (CU-O09).
- **FR-015**: El sistema DEBE generar un comprobante imprimible para todo pago confirmado,
  independientemente del método utilizado (CU-O10).
- **FR-016**: Todo registro de pago, una vez creado, DEBE ser inmutable; cualquier corrección DEBE
  realizarse mediante un nuevo registro de ajuste vinculado, nunca editando o eliminando el
  original (Principio IV de la constitución del proyecto).
- **FR-017**: El sistema DEBE permitir que un ciclista consulte su propio historial completo de
  viajes y pagos, incluyendo fechas, costos, método de pago y comprobante asociado (CU-O11).

**Gestión de Flota e Inspección**

- **FR-018**: El sistema DEBE permitir que un empleado de mantenimiento registre una orden de
  mantenimiento para una bicicleta con falla reportada (tipo correctivo o preventivo, descripción
  y técnico responsable), cambiando su estado a "mantenimiento" (CU-O12; confirmado contra
  `POST /mantenimiento/ordenes/crear`, función `mnt_ordenes_crear`, en `app/routers/empleado.py`).
  Esta vía manual coexiste con la creación automática de órdenes descrita en FR-020 cuando el
  checklist de inspección reprueba.
- **FR-019**: El sistema DEBE proveer un checklist de inspección de 7 puntos (frenos, llantas,
  cadena, luces, estructura, manubrio, sillín) que el empleado de mantenimiento DEBE completar en
  cada inspección; el checklist se evalúa al vuelo y no se persiste punto por punto (CU-O13;
  confirmado contra la constante `_CHECKLIST_ITEMS` en `app/routers/empleado.py`).
- **FR-020**: Una bicicleta NO DEBE volver a estado "disponible" a menos que los 7 puntos de su
  checklist de inspección más reciente hayan sido aprobados; si al menos uno falla, se crea
  automáticamente una orden en `ordenes_mant` (tipo "correctivo" fijo, descripción autogenerada con
  las fallas) y la bicicleta queda en "mantenimiento" (CU-O13).
- **FR-021**: El sistema DEBE actualizar automáticamente el estado de una bicicleta (disponible,
  en uso, mantenimiento; un cuarto estado, "retirada", existe en el esquema real pero su
  disparador queda fuera del alcance operativo CU-O01–CU-O17 de este spec — ver Key Entities)
  inmediatamente después de cada evento que lo afecte: reserva/inicio de viaje (mismo evento), fin
  de viaje, resultado de checklist o devolución confirmada (CU-O14).
- **FR-022**: El sistema NO DEBE permitir que una orden de mantenimiento o un checklist modifiquen
  el estado de una bicicleta que tenga un viaje activo en curso; el cambio de estado solo se aplica
  una vez que el viaje finaliza (CU-O12, CU-O14).

**Monitoreo y Devoluciones**

- **FR-023**: El sistema DEBE permitir que un empleado de vigilancia visualice todos los viajes
  actualmente activos en tiempo real, incluyendo tiempo transcurrido y estación de origen
  (CU-O15).
- **FR-024**: El sistema DEBE generar una alerta dirigida al personal de vigilancia cuando el
  tiempo transcurrido de cualquier viaje activo supere los 120 minutos (CU-O16).
- **FR-025**: El sistema NO DEBE aplicar ningún cargo automático ni cerrar automáticamente un
  viaje por haber superado el umbral de 120 minutos; el viaje DEBE permanecer activo y su
  resolución (contacto con el ciclista o reporte de pérdida) DEBE quedar siempre a cargo de una
  acción manual del personal de vigilancia u operación (CU-O16).
- **FR-026**: El sistema DEBE permitir que un empleado de vigilancia registre la confirmación de
  devolución física de una bicicleta en una estación (CU-O17).

**Requisitos transversales**

- **FR-027**: Todo endpoint o funcionalidad descrita arriba DEBE validar que el usuario
  autenticado posee el rol específico requerido para esa acción (Administrador, Gerente,
  Ciclista, Empleado de Operación, Empleado de Mantenimiento o Empleado de Vigilancia, según
  corresponda); cualquier usuario sin el rol requerido DEBE recibir acceso denegado (Principio III
  de la constitución del proyecto).

### Key Entities *(include if feature involves data)*

- **Ciclista**: Cliente final que alquila bicicletas. Atributos clave: datos personales,
  identificación, historial de viajes y pagos. El bloqueo para nuevas reservas no es un atributo
  persistido del ciclista: se calcula en tiempo de ejecución sobre sus registros en `pagos` (ver
  FR-008 y `data-model.md`).
- **Empleado**: Usuario interno con un rol operativo (Operación, Mantenimiento o Vigilancia),
  asociado a una ciudad y, opcionalmente, a una estación.
- **Estación**: Ubicación física de anclaje con capacidad, ciudad y la lista de bicicletas
  presentes en un momento dado.
- **Bicicleta**: Unidad física de la flota con un tipo (p. ej. estándar o eléctrica) y un estado.
  Estados confirmados directamente contra el esquema real (`select` de 4 opciones en la colección
  `bicicletas` de PocketBase): disponible, en uso, mantenimiento, retirada. El valor "reservada"
  quedó **confirmado que no existe** (no hay paso de reserva separado del inicio de viaje). El
  estado "retirada" se usa para dar de baja una bicicleta de forma permanente (p. ej. robo, daño
  irreparable, fin de vida útil); su disparador no forma parte del alcance operativo de este spec
  (CU-O01–CU-O17) — probablemente se asigna desde funciones de nivel Administrador/Gerente (ver
  `data-model.md`).
- **Reserva**: No existe como entidad independiente. Reservar una bicicleta crea directamente un
  viaje en estado "activo" y la bicicleta pasa a "en uso" en el mismo instante, sin paso
  intermedio ni expiración por tiempo (confirmado contra `app/routers/ciclista.py`; ver
  `data-model.md`).
- **Viaje**: Registro de un alquiler concreto: ciclista, bicicleta, estación de origen y destino,
  hora de inicio y fin, duración y costo calculado. Su estado (activo, completado, cancelado)
  cubre también lo que conceptualmente sería la "reserva" (ver arriba).
- **Pago**: Intento o confirmación de cobro de un viaje, con monto, método (tarjeta, efectivo,
  transferencia) y el viaje al que pertenece. Valores de `estado` confirmados en el mecanismo de
  bloqueo de FR-008: `pendiente_efectivo`, `verificacion_pendiente`, `rechazado` (más
  `confirmado`); "en disputa" no fue confirmado como un valor real de este campo — ver
  `data-model.md`.
- **Comprobante**: No es un archivo persistido. Es el campo `comprobante_numero` (formato
  `UB-YYYYMMDD-XXXX`) dentro del registro de pago confirmado, a partir del cual se renderiza
  dinámicamente una vista HTML imprimible en cada consulta (confirmado contra
  `app/routers/ciclista.py`; ver `data-model.md`).
- **Orden de Mantenimiento**: Registro de una falla sobre una bicicleta (tipo correctivo o
  preventivo, descripción en texto libre, técnico responsable). Se crea por dos vías confirmadas:
  manualmente por un empleado de mantenimiento (CU-O12, `POST /mantenimiento/ordenes/crear`) o
  automáticamente cuando el checklist de inspección reprueba (CU-O13, tipo "correctivo" fijo y
  descripción autogenerada) (confirmado contra `app/routers/empleado.py`; ver `data-model.md`).
- **Checklist de Inspección**: Conjunto de 7 puntos (frenos, llantas, cadena, luces, estructura,
  manubrio, sillín) evaluados al vuelo sobre una bicicleta en cada inspección; el resultado no se
  persiste punto por punto, solo su efecto (cambio de estado de la bicicleta y, si reprueba, una
  nueva Orden de Mantenimiento) (confirmado contra `app/routers/empleado.py`; ver
  `data-model.md`).
- **Alerta de Retraso**: Cálculo en tiempo de ejecución (no persistido como entidad propia) para
  todo viaje activo que supera los 120 minutos; solo se persiste su estado de atención manual
  (confirmado contra `app/routers/empleado.py`; ver `data-model.md`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Una persona nueva puede completar su registro y obtener una cuenta de ciclista
  activa en menos de 3 minutos.
- **SC-002**: La disponibilidad de bicicletas mostrada a los ciclistas coincide con el inventario
  real en al menos el 99% de las consultas realizadas inmediatamente después de un evento de
  reserva o viaje.
- **SC-003**: El 100% de los viajes finalizados muestran al ciclista un costo calculado dentro de
  los 10 segundos posteriores a la devolución de la bicicleta.
- **SC-004**: El 100% de los pagos confirmados (de cualquier método) cuentan con un comprobante
  asociado y recuperable.
- **SC-005**: El 100% de los ciclistas con un pago pendiente o en disputa quedan efectivamente
  impedidos de iniciar un nuevo viaje hasta resolverlo, sin excepciones registradas en auditoría.
- **SC-006**: El 95% de los pagos en efectivo o por transferencia pendientes son revisados
  (confirmados o rechazados) por el personal de operación dentro de las 24 horas siguientes a su
  registro.
- **SC-007**: El 100% de las bicicletas que vuelven a estado "disponible" tras mantenimiento
  cuentan con un checklist de 7 puntos completamente aprobado al momento de la inspección (el
  resultado del checklist se evalúa al vuelo y no se persiste; ver `data-model.md`).
- **SC-008**: El personal de vigilancia recibe una alerta de retraso para el 100% de los viajes
  activos dentro de 1 minuto de superar los 120 minutos de duración.
- **SC-009**: Un ciclista puede recuperar, en una sola consulta, al menos los últimos 12 meses de
  su historial de viajes y pagos.

## Assumptions

- Reservar una bicicleta no tiene tiempo de espera ni expiración: es el mismo evento técnico que
  iniciar el viaje (confirmado contra `app/routers/ciclista.py`; ver FR-006, FR-007 y
  `data-model.md`).
- La edad mínima de registro es 18 años (mayoría de edad legal en Ecuador); no se incluye en este
  alcance un flujo de consentimiento para menores de edad.
- Una misma cuenta de ciclista es válida en las cinco ciudades de operación (Quito, Guayaquil,
  Cuenca, Riobamba y Ambato), conforme al modelo de datos compartido establecido en la
  constitución del proyecto.
- Los 7 puntos del checklist de inspección son: frenos, llantas, cadena, luces, estructura,
  manubrio y sillín (confirmado contra la constante `_CHECKLIST_ITEMS` en
  `app/routers/empleado.py`).
- Las tarifas por tipo de bicicleta (p. ej. estándar vs. eléctrica) son datos de configuración
  operativa administrados por Gerente/Administrador; los valores concretos de tarifa quedan fuera
  del alcance de esta especificación.
- Una "falla" que origina una orden de mantenimiento (CU-O12) es detectada o reportada por
  personal de mantenimiento u operación, no autorreportada por el ciclista durante un viaje en
  curso; el autorreporte de fallas por el ciclista queda fuera de alcance de esta especificación.
- Los pagos se procesan después del viaje (modelo postpago); no existe depósito o retención previa
  al inicio del viaje. La pasarela de pago confirma o rechaza cada transacción de forma asíncrona.
- Un ciclista con un pago pendiente queda bloqueado para iniciar nuevos viajes hasta resolverlo
  (decisión de negocio confirmada por el usuario del producto); el mecanismo técnico exacto
  (consulta en tiempo de ejecución sobre `pagos`, sin campo persistido en `users`) está confirmado
  contra el código real — ver FR-008 y `data-model.md`.
- Cuando un viaje supera el umbral de alerta de 120 minutos sin devolución, el sistema no aplica
  ningún cargo ni cierre automático; la resolución es siempre manual (decisión confirmada por el
  usuario del producto).
