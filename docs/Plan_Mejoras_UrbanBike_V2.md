# Plan de Mejoras UrbanBike — Segunda Ronda
*Estructurado a partir de observaciones directas de Washington Apunte, tras revisión funcional del sistema ya construido.*

**Instrucción para Claude Code al empezar:** lee `docs/HOJA_DE_RUTA.md` completo antes de tocar cualquier punto de este documento. Varias de las observaciones de abajo pueden coincidir con trabajo ya hecho en sesiones anteriores (marcado explícitamente donde aplica) — confirma el estado real antes de reconstruir. Mantén la misma disciplina de todo el proyecto: auditar antes de construir, probar con datos reales, revertir datos de prueba al terminar, preguntar antes de decisiones de negocio ambiguas.

---

## ⚠️ Punto que requiere tu decisión antes de implementar nada

**Quitar "Simulación académica" / "simulado" de la interfaz.**

**RESUELTO (Washington, 17-ago-2026): versión discreta — ícono pequeño con tooltip, no eliminarla.** Pendiente de implementar (no forma parte del plan ejecutable de Prioridad 0, ver `docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md`).

Este texto se agregó a propósito en sesiones anteriores porque el sistema no tiene ninguna pasarela de pago real conectada (Stripe, PayPal, etc.) — es un mecanismo simulado por decisión explícita. Quitarlo por completo podría dar la impresión de que hay procesamiento de pago real donde no lo hay.

~~**Recomendación:** en vez de eliminarlo, hacerlo menos intrusivo — un ícono pequeño con tooltip en vez de una banda de texto grande y repetida, o una sola mención discreta en el pie de página de esas pantallas, no en cada paso del flujo. Esto resuelve el problema de "se ve como prototipo" sin dejar de ser honesto sobre qué hace el sistema realmente.~~ (adoptada tal cual, ver resuelto arriba)

~~Decide antes de que Claude Code toque esto: ¿aplicar la versión discreta, o quitarlo por completo asumiendo el riesgo de que alguien lo confunda con un cobro real?~~

---

## PRIORIDAD 0 — Integridad financiera y confianza (implementar primero)

Estos puntos afectan directamente si el sistema cobra correctamente o si lo que se muestra coincide con lo que se cobra. Son los más graves porque socavan la confianza en todo lo demás.

### 0.1 Contador que no se detiene al finalizar viaje
**Estado:** posiblemente YA RESUELTO en una sesión anterior (rediseño con ventana de gracia de 5 horas + recargo por demora separado). **Verificar primero en pantalla real antes de reconstruir** — puede que solo falte confirmación visual, no código nuevo.

### 0.2 Código de descuento para clientes de alto volumen / frecuentes
Un ciclista que alquila 3+ bicicletas simultáneas, o que es cliente frecuente, debe recibir un código de descuento real, aplicable por el ciclista mismo en el flujo de reserva.

**RESUELTO (Washington, 18-ago-2026):**
- **Volumen:** 15% de descuento para 3+ bicicletas alquiladas simultáneamente en una misma reserva.
- **Cliente frecuente:** 10% de descuento, definido como 5+ viajes en los últimos 30 días.

Pendiente de implementar (no forma parte del plan ejecutable de Prioridad 0, ver `docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md`).

~~**Falta definir antes de construir:** ¿qué porcentaje de descuento? ¿"cliente frecuente" se mide por cuántos viajes en qué período de tiempo? Sin esto, no se puede implementar sin inventar un criterio.~~

### 0.3 Factura única para múltiples bicicletas alquiladas a la vez
Si un ciclista reserva más de una bicicleta, debe emitirse **una sola factura** con el detalle de todas, no una factura por bicicleta.

### 0.4 Notificaciones incompletas por rol
Ya existe un catálogo auditado de 22 tipos de notificación posibles, de los cuales solo 5-7 tienen gancho real hoy (ver sección más reciente de `docs/HOJA_DE_RUTA.md` antes de esta ronda). Washington pide específicamente que **todos los movimientos y transacciones reales notifiquen al usuario correspondiente**. Usar esa auditoría ya hecha como punto de partida — no repetirla desde cero, solo construir los ganchos que faltan.

---

## PRIORIDAD 1 — Usabilidad que afecta el uso diario

### 1.1 Exportación PDF/Excel: campos largos rompen la presentación
Auditar todas las plantillas de exportación y aplicar truncamiento/ajuste de texto consistente (ellipsis, wrap controlado, o ancho de columna dinámico según contenido) para que ningún campo desborde su celda o su línea.

### 1.2 Búsqueda con filtro automático al escribir
Hoy, según describe Washington, los filtros de búsqueda requieren una acción explícita (botón "Buscar"). Cambiar a filtrado en vivo mientras se escribe (con un pequeño retraso/debounce para no golpear el servidor en cada tecla).

### 1.3 Admin — foto de perfil se sobrepone en "Ver perfil"
Bug visual real de superposición/desborde. Corregir el layout del modal o sección de foto.

### 1.4 Admin — interfaz de Roles y Permisos poco clara
- Agregar botón "Aplicar todo" y botón "Restablecer a configuración predeterminada" en la matriz de permisos por rol.
- Mismo criterio para la pantalla de excepciones por usuario.
- Agregar texto de ayuda breve por sección explicando qué hace cada apartado (tooltips o descripciones inline), para que no dependa de que alguien ya sepa cómo funciona.

### 1.5 Admin — respaldo completo de la base de datos con un clic
Hoy el respaldo permite seleccionar tablas específicas con filtro de fecha. Agregar una opción explícita de "Respaldo completo" que traiga todo sin tener que seleccionar tabla por tabla.

### 1.6 Preview de imagen al subir un archivo
En cualquier formulario que suba una foto (bicicletas, perfil, etc.), mostrar una vista previa de la imagen seleccionada antes de confirmar el envío.

### 1.7 Ventanas de advertencia contextual para el ciclista
- Al finalizar un viaje: aviso de que debe devolver la bicicleta, con la advertencia explícita de que pasar 5 horas genera un cargo adicional.
- Al cambiar de modalidad de tarifa mientras el viaje está activo: aviso de que el precio cambiará y de que deberá pagar un monto distinto.

### 1.8 Dashboard con "acciones pendientes" visibles, para todos los roles
No solo el resumen general — cada rol debe ver de inmediato qué tiene pendiente de hacer:
- Ciclista: alquileres en curso.
- Operación: cobros pendientes de verificar, bicicletas a rebalancear, inventario por actualizar.
- Vigilancia: seguimientos activos, devoluciones por validar, daños por verificar, disponibilidad por confirmar.
- Mantenimiento: mantenimientos activos, bicicletas por actualizar a disponible.
- Admin: lo que corresponda según lo que ya se maneja hoy (bloqueos, registros nuevos, etc.)

### 1.9 Guía de uso por rol ("qué puedo hacer, cómo, qué no debo hacer")
Un apartado de ayuda dentro del sistema, específico para cada tipo de usuario, para reducir confusión y errores de uso — sobre todo mencionado para Operación, Mantenimiento y Vigilancia.

---

## PRIORIDAD 2 — Funcionalidad de negocio nueva o expandida

### 2.1 Catálogo del ciclista — distinguir alquiler directo vs. solo bajo suscripción
Algunas bicicletas (probablemente las premium o de mayor demanda) deberían mostrarse como exclusivas para miembros con membresía activa, no alquilables directamente por cualquiera.

**RESUELTO (Washington, 18-ago-2026): categoría eléctrica exclusiva para suscriptores.** Pendiente de implementar (no forma parte del plan ejecutable de Prioridad 0, ver `docs/superpowers/plans/2026-08-17-plan-mejoras-v2-p0.md`).

~~**Falta definir:** ¿qué categoría(s) de bicicleta quedan restringidas a solo-suscriptores? Confirmar antes de implementar.~~

### 2.2 Imagen representativa por categoría en el catálogo
Cada categoría (Estándar, Premium, Eléctrica, etc.) debería mostrar una imagen ilustrativa que represente ese tipo de bicicleta, no solo el nombre de la categoría.

### 2.3 Detalle de viaje ampliado en "Mis Viajes"
Además del historial simple, agregar una vista de detalle por viaje: qué bicicleta se usó, cuánto se pagó, cuántas horas se usó, etc.

### 2.4 Chat de soporte — versión completa
Expandir el chat construido en la sesión anterior:
- El ciclista debe poder **elegir con qué empleado de Vigilancia específico** quiere hablar (no un buzón genérico, y nunca con Admin ni otros roles).
- Soporte para emojis.
- Adjuntar documentos, imágenes y videos (no solo fotos).
- Opción de borrar mensajes individuales o la conversación completa.
- Iniciar el chat seleccionando primero el motivo (relacionado con una infracción, consulta general, etc.).

### 2.5 Separar datos del dataset académico de los datos de prueba reales
Hoy existe una sección aparte para el dataset de CitiBike (ya bien identificada). Washington pide que, en los filtros de los reportes que sí mezclan ambos orígenes, se pueda elegir explícitamente "solo dataset académico" / "solo datos reales de prueba" en vez de tenerlos completamente separados en pantallas distintas.

**RESUELTO (Washington, 18-ago-2026): descartado por ahora.** Según la auditoría ya realizada, ninguna pantalla mezcla hoy ambas fuentes: `/gerente/dashboard` y `/gerente/analisis-citibike` son 100% Citibike; `/gerente/informe` y `/gerente/reportes` son 100% datos reales. No hay nada que construir para este punto salvo que aparezca una pantalla nueva que sí las mezcle.

~~**Aclarar con Washington:** ¿esto aplica a qué reportes específicamente? El dataset de CitiBike y los datos operativos reales viven en bases separadas (`urbanbike` vs `urbanbike_operativa`/`urbanbike_tactica`) — confirmar el alcance real antes de mezclar filtros entre bases distintas.~~

### 2.6 Reportes "pobres" — no aportan valor real al negocio
Queja general y repetida en varias secciones del documento (Ciclista, y transversal). Se necesita una auditoría de qué información de negocio real debería mostrar cada reporte para ser útil a la operación de UrbanBike (tendencias, comparativas, indicadores accionables), no solo listados planos. Esto es un punto grande — probablemente merece su propia sesión de diseño antes de implementar.

### 2.7 Mantenimiento — fecha límite de reparación
Cada orden de mantenimiento debería tener una fecha límite establecida, dado que una bicicleta en mantenimiento representa pérdida de ingresos para el negocio mientras no esté disponible.

### 2.8 Vigilancia — trazabilidad de mantenimiento e infracciones
Vigilancia necesita poder confirmar que un mantenimiento reportado efectivamente se realizó, y mayor trazabilidad sobre infracciones y alertas (historial claro de qué pasó y cuándo).

---

## Resumen de puntos que necesitaban una decisión tuya antes de construir

**Los 4 quedaron resueltos el 18-ago-2026 (el primero, el 17-ago-2026). Ya no hay ningún punto de este documento bloqueado por decisión de negocio.**

1. ~~Simulación académica: ¿discreta o eliminada?~~ — **Resuelto (17-ago-2026): discreta (ícono + tooltip).** Pendiente de implementar.
2. ~~Código de descuento por volumen/frecuencia: ¿qué porcentaje, qué umbral exacto de "cliente frecuente"?~~ — **Resuelto: 15% para 3+ bicicletas simultáneas; 10% para cliente frecuente (5+ viajes en 30 días).** Pendiente de implementar.
3. ~~Bicicletas exclusivas de suscriptores: ¿cuáles categorías quedan restringidas?~~ — **Resuelto: categoría eléctrica.** Pendiente de implementar.
4. ~~Filtro dataset académico vs. datos reales: ¿en qué reportes específicos aplica?~~ — **Resuelto: descartado por ahora, ninguna pantalla actual mezcla ambos orígenes.** Sin trabajo pendiente, salvo que aparezca una pantalla nueva que sí los mezcle.
