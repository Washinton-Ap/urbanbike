# Plan de Mejoras UrbanBike — Tercera Ronda
*35 observaciones de un compañero de curso + observaciones propias de Washington, tras prueba funcional del sistema.*

**Instrucción para Claude Code al empezar:** lee `docs/HOJA_DE_RUTA.md` y `Plan_Mejoras_UrbanBike_V2.md` antes de tocar cualquier punto. Varios puntos de esta ronda describen algo que **ya se construyó en sesiones anteriores** — la prioridad 0 de este documento existe exactamente para confirmar eso antes de reconstruir o, peor, contradecir una decisión ya probada.

---

## PRIORIDAD 0 — Auditar antes de tocar nada (posible choque con trabajo ya hecho)

### 0.1 Restricción de dirección en cambio de modalidad (punto 9 del compañero)
Pide que no se pueda retroceder de modalidad (de semana a día, de día a hora). **Esto toca directamente el flujo de cambio de modalidad que se construyó y probó hoy mismo** (selector en la ficha, corrección del panel de mapa, aplicación de promociones). Auditar el código real antes de agregar la restricción, para no romper lo ya verificado.
**Aclarar con Washington:** ¿la restricción es "nunca bajar de modalidad" en cualquier momento, o solo aplica una vez que el viaje ya está en curso?

### 0.2 Ruta al finalizar + límite de 30 minutos con recargo (punto 11 del compañero)
Esto **puede ser la misma regla del recargo por demora de 5 horas que ya construimos hoy**, o una regla completamente distinta (tiempo de traslado entre estación de inicio y estación de entrega, no tiempo de espera hasta que Vigilancia valide). Son dos momentos diferentes del ciclo de un viaje — no asumir que es lo mismo sin confirmarlo.
**Aclarar con Washington:** ¿este límite de 30 minutos es sobre el trayecto físico entre estaciones, y el recargo de 5 horas sigue existiendo aparte para la validación de Vigilancia? ¿O el compañero está describiendo (con otras palabras) la misma regla que ya existe?

### 0.3 Chat: restricciones de rol (puntos 31 y 32 del compañero)
El chat construido hoy ya limita al ciclista a elegir solo agentes de Vigilancia, y Admin ya tiene una vista de supervisión sin poder ser destinatario. **Falta verificar** si Admin puede escribir mensajes hoy (el punto 32 exige que no pueda) y si existe algún mecanismo de censura/moderación de mensajes inapropiados (no existe hoy, es una pieza nueva).

### 0.4 Filtros automáticos (punto 18 del compañero)
Ya se pidió esto en la ronda anterior (punto 1.2 del documento V2) y se marcó como implementado. Auditar el alcance real: ¿se aplicó a todas las pantallas de filtro del sistema, o solo a algunas?

### 0.5 Guía de uso con acceso directo (punto 19 del compañero)
La guía de uso por rol ya se construyó en la ronda anterior (punto 1.9 del documento V2). Falta verificar si existe un botón directo y visible desde la pantalla de inicio, o si hoy solo se accede por un menú.

### 0.6 Quitar "Bicicletas" del usuario Mecánico (punto 28 del compañero)
**No borrar a ciegas.** Antes de eliminar la sección, confirmar si de verdad no hace nada (en cuyo caso es candidato a borrar) o si es una función real con un bug que la deja sin efecto (en cuyo caso el fix es corregirla, no eliminarla) — mismo criterio que ya se aplicó varias veces en sesiones anteriores ante afirmaciones de "esto no sirve".

---

## PRIORIDAD 1 — Correcciones e integridad de datos (rápidas, alto valor, sin depender de la auditoría anterior)

| # | Observación | Origen |
|---|---|---|
| 1.1 | El botón "Volver" debe regresar a la página anterior real del usuario, no siempre al inicio | Compañero #2 |
| 1.2 | Color del botón de cambio de modalidad debe distinguirse a simple vista | Compañero #8 |
| 1.3 | Al cambiar de modalidad, mostrar el costo total del cambio como aviso explícito (términos y condiciones) | Compañero #10 |
| 1.4 | Filtro por nombre de ciclista en las pantallas de devolución de Vigilancia | Compañero #12 |
| 1.5 | Botón "Seleccionar todo" (OK / Daño) en el checklist de inspección | Compañero #13 |
| 1.6 | El mecánico no puede guardar costo de repuesto o mano de obra en cero o negativo | Compañero #16 |
| 1.7 | Una orden de mantenimiento cerrada no se puede editar; los estados no retroceden | Compañero #17 |
| 1.8 | Bloquear el campo de monto por daño si la inspección no registró ningún daño | Compañero #22 |
| 1.9 | Pago en efectivo: el monto a pagar es fijo (no editable), se ingresa lo recibido y el sistema calcula el vuelto | Compañero #24 |
| 1.10 | Alquiler manual: al elegir la bicicleta, autocompletar su estación real | Compañero #26 |
| 1.11 | Fecha de inicio de una promoción no puede ser anterior a hoy; revisar validación de fechas en general, caso por caso | Compañero #29 |
| 1.12 | Cambiar el ícono de accesibilidad (hoy una tuerca) por uno que represente accesibilidad/usabilidad | Compañero #30 |
| 1.13 | Agregar género y fecha de nacimiento al registro | Compañero #35 |
| 1.14 | Investigar la lentitud reportada en la confirmación de pago por transferencia | Compañero #23 — **requiere diagnóstico, no solo "hacerlo más rápido"** |

---

## PRIORIDAD 2 — Funcionalidad nueva de negocio

| # | Observación | Origen | Nota |
|---|---|---|---|
| 2.1 | Pantalla informativa antes de iniciar sesión, explicando de qué trata el sistema | Compañero #1 | |
| 2.2 | Promociones más llamativas visualmente dentro de la reserva de bicicletas | Compañero #3 | |
| 2.3 | Historial de uso de esa bicicleta específica, visible al momento de reservarla | Compañero #4 | |
| 2.4 | Más características técnicas de la bicicleta: en el registro, en la flota y en el detalle | Compañero #5, #25, #27 | Tres puntos duplicados, una sola tarea |
| 2.5 | Filtro de tiempo en el mapa de seguimiento de Vigilancia, para no saturar el mapa con todos los alquileres activos | Compañero #6 | |
| 2.6 | PDF de comprobantes con más detalle (fecha, hora) y mejor diseño | Compañero #7 | |
| 2.7 | Evidencia fotográfica de daños en la devolución (foto del daño + foto final de recepción), con detalle estructurado por daño (motivo, costo, observación) | Compañero #14, #15 | |
| 2.8 | Aviso explicando el motivo de una infracción y cómo resolverla; mostrar el nombre del ciclista en la lista de infracciones | Compañero #20 | |
| 2.9 | Detallar en la factura cada cobro por daño de forma individual | Compañero #21 | |
| 2.10 | Chat interno entre personal: Gerente-Empleados, Admin-Gerente-Empleados (separado del chat de soporte ciclista-Vigilancia) | Compañero #33 | Sistema nuevo, no una extensión del chat existente |
| 2.11 | Encuesta de satisfacción opcional al finalizar un alquiler (escala 1-5 + observaciones), para apoyo a decisiones de Gerencia | Compañero #34 | |

---

## PRIORIDAD 3 — Calidad transversal

La nota general del compañero ("revisar todo el programa, todo validado y sin errores, capturar excepciones, velocidad de respuesta rápida") no es una tarea puntual — es una auditoría de manejo de excepciones en todo el sistema, similar a la que ya se hizo hoy en `admin.py` (donde se encontraron 6 rutas sin ningún `try/except`). Vale la pena repetir ese mismo ejercicio sobre el resto de routers (`gerente.py`, `ciclista.py`) antes de cerrar esta ronda.

---

## Resumen de decisiones que Washington debe tomar antes de construir

1. **0.1** — ¿la restricción de modalidad aplica siempre, o solo con el viaje en curso?
2. **0.2** — ¿el límite de 30 minutos es un concepto nuevo (traslado entre estaciones) o el compañero describe la regla de 5 horas ya existente con otras palabras?
3. **2.10** — confirmar que el chat interno de personal es un sistema aparte del chat de soporte, no una fusión con él.
