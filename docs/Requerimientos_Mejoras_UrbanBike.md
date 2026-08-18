# Requerimientos de Mejora — Sistema UrbanBike
*Desarrollado a partir de apuntes de revisión funcional*

## 1. Validaciones de formularios

| Campo | Regla actual (falla) | Regla requerida |
|---|---|---|
| N.° de tarjeta | Acepta "0000000000" como válido | Validar longitud exacta según tipo de tarjeta (13-19 dígitos) + algoritmo de Luhn para descartar números inválidos/rellenos de ceros |
| Teléfono | Sin validar | Exactamente 10 dígitos numéricos |
| Cédula | Sin validar en algunos formularios | Exactamente 10 dígitos numéricos |
| Campos numéricos en general | Sin validar tipo | Rechazar caracteres no numéricos en todo campo declarado como número |
| Fecha de caducidad (al registrar membresía) | Sin validar | Debe ser **posterior a la fecha actual + 1 mes como mínimo** (si la tarjeta caduca antes de ese margen, no se debe permitir la suscripción) |

**Aclaración importante (input, no solo validación al enviar):** en todo campo numérico (teléfono, cédula, tarjeta, capacidad, precio, etc.) el campo debe **restringir lo que el usuario puede escribir** — es decir, si intenta teclear una letra o símbolo, el campo **no debe ni siquiera aceptar esa tecla** (usar `inputmode="numeric"` + `pattern`, y un filtro JS que bloquee el keypress no numérico), además de la validación server-side de longitud/formato al enviar. No basta con rechazar el formulario después de escrito — hay que impedir el carácter inválido desde que se teclea.

**Aplica de forma transversal:** cualquier campo del sistema (no solo membresía) debe validar tipo de dato y formato antes de aceptar el registro.

## 2. Historial y trazabilidad de pagos

- Agregar módulo de **historial de pagos por ciclista**: fecha, monto, método, estado (aprobado/rechazado), y **motivo de rechazo** en caso de impago.
- Debe soportar **filtro** (por fecha, estado, método) y **paginado**.

## 3. Alquiler activo — visualización y seguimiento

- Si el ciclista tiene un alquiler activo, mostrarle en el inicio el **flujo de pago paso a paso con íconos** (ej. reservado → en curso → devolución → pago → completado).
- Un ciclista **puede tener más de una bicicleta alquilada simultáneamente** — el sistema debe permitirlo y reflejarlo correctamente en el flujo activo (no asumir alquiler único).

> **Nota:** se descarta la idea de mostrar un recorrido/ruta del viaje, porque implicaría datos simulados/falsos (no hay GPS real de las bicicletas). Todo lo que muestre el sistema debe ser funcional y basado en datos reales, nunca simulado.

## 4. Membresía / Suscripción — beneficios diferenciados

Un suscriptor debe tener una experiencia distinta a un ciclista normal:
- Tarifa preferencial (ej. mitad de precio en todas las bicicletas).
- Acceso anticipado a bicicletas.
- Promociones exclusivas, descuentos especiales y obsequios por fidelidad de uso.

## 5. Exportación de reportes (PDF / Excel)

- **Regla global:** si el conjunto de datos a exportar está vacío (sin viajes, sin pagos, sin registros), el botón de exportar PDF/Excel debe **deshabilitarse o rechazar la acción**, no generar un archivo en blanco.
- Aplica a todos los módulos del sistema que exporten reportes, no solo viajes.

## 6. Administración de cuentas

- Al **eliminar una cuenta**, el admin debe además **forzar el cierre de sesión** del usuario afectado (invalidar su sesión/token activo).
- **Adicional (acción independiente):** el admin debe tener una opción para **cerrar la sesión de cualquier usuario que esté actualmente conectado/navegando en el sistema**, sin necesidad de eliminar su cuenta — por ejemplo un botón "Cerrar sesión" junto a cada usuario activo en el panel de administración.
- El cierre debe ser **en tiempo real**: al usuario afectado se le debe cortar la sesión inmediatamente (no esperar a que haga clic o navegue), y se le debe mostrar una **ventana flotante** con el mensaje "[Nombre del administrador] cerró tu sesión", que **desaparece automáticamente a los 5 segundos**.

## 7. Catálogo visible al ciclista

- Mostrar al ciclista el **catálogo de bicicletas** (el "producto" del sistema) disponible para alquilar.

## 8. Apartado institucional (Gerente / Empleados)

- Agregar sección con **Misión y Visión** de la empresa, visible para el rol Gerente y para Empleados.

## 9. UI de alquiler — simplificación

- Al ver el detalle de una tarifa, mostrar **solo la tarifa seleccionada**, sin ventanas emergentes (modales) — aplicar este criterio en todo el sistema, no solo en alquiler.
- El estado del pago debe aparecerle directamente al ciclista, sin pasos intermedios innecesarios.

## 10. Penalización por demora

- Si han transcurrido **más de 5 horas** desde la finalización del viaje sin completarse el proceso, aplicar penalización por demora.
- Al finalizar el viaje debe aparecer automáticamente un apartado de **Pago** indicando el estado (pendiente/aprobado/rechazado) — el proceso debe ser automático, no manual.

## 11. Promociones y factura

- Soportar aplicación de promociones: descuentos generales, descuentos especiales para suscriptores, y **código de descuento**.
- **Formato de factura mejorado** (combinando los dos ejemplos de referencia adjuntos, con marca UrbanBike):
  - **Encabezado:** logo UrbanBike (esquina superior derecha) + datos de la empresa (razón social, dirección, RUC) a la izquierda, en los colores corporativos de UrbanBike.
  - **Bloque de identificación:** N° de factura, fecha de emisión, N° de pedido/viaje, fecha de vencimiento (alineado a la derecha, como en el ejemplo 1).
  - **Datos del cliente:** "Facturar a" (ciclista: nombre, dirección, cédula/RUC) — no aplica "Enviar a" al ser un servicio, se puede omitir o reemplazar por "Estación de retiro / devolución".
  - **Tabla de detalle** con columnas: Cant. — Descripción — Precio unitario — Importe. Debe incluir como líneas independientes: tarifa base del viaje, recargos por demora (si aplica), cargos por daño/falla (si aplica), y descuentos/promociones aplicados (como línea negativa o columna aparte).
  - **Totales:** Subtotal, IVA (12% Ecuador, ya implementado), Descuento aplicado (si hay código), **TOTAL** destacado.
  - **Pie:** condiciones de pago (método usado: efectivo/transferencia/tarjeta), y datos de contacto/soporte de UrbanBike.

## 11.1 Notificaciones (dependencia del flujo, ver punto 13)
- Notificación por correo y por campana en el sistema, para todos los actores (ciclistas y empleados), disparadas por: fallas reportadas en devolución, aprobación de pago, y penalizaciones aplicadas.


## 12. Soporte al cliente

- El empleado de **Vigilancia** también brinda soporte a los ciclistas.
- Agregar canal de **correo** (`sistemasoftwaredev@gmail.com`) y **chat dentro del sistema** para soporte.

## 13. Flujo de alquiler/devolución — rediseño completo

Flujo objetivo (reemplaza el actual, considerado lento y poco automatizado):

1. **Inicio de viaje:** ciclista selecciona bicicleta → selecciona tarifa → aplica descuento/promoción si corresponde → inicia viaje.
2. **Fin de viaje:** ciclista selecciona la estación de devolución → sistema muestra el estado de pago.
   - Si pasaron **más de 5 horas** desde la finalización, se reanuda/extiende el contador de tiempo transcurrido y se refleja como recargo detallado en la factura.
   - Si **no** hay infracciones, se recompensa al ciclista con código de descuento: **10%** para uso normal, **20%** si es usuario recurrente.
3. **Validación de devolución (Empleado de Vigilancia):**
   - Sin fallas → aprueba la devolución directamente.
   - Con fallas → se cobra un monto adicional según el tipo de falla, y se genera automáticamente:
     - Notificación por **correo** y por la **campana de notificaciones** (para todos los actores: empleados y ciclistas).
     - Asignación de la falla al **Empleado de Mantenimiento**, quien la repara; una vez reparada, la bicicleta vuelve a estar disponible.
4. **Pago posterior a la devolución:**
   - Métodos válidos: efectivo, transferencia, tarjeta.
   - Recargo adicional si hubo infracción (demora o daño).
   - **Efectivo/transferencia:** requiere verificación manual del **Empleado de Operación**.
   - **Tarjeta:** proceso automático.

### Diagrama de estados simplificado
```
Ciclista: Selecciona bici → Selecciona tarifa → Aplica promo/descuento → Inicia viaje
                                                                              ↓
Ciclista: Finaliza viaje → Selecciona estación devolución → Ve estado de pago
   (si >5h desde fin → recargo por demora, detallado en factura)
   (si sin infracciones → código descuento 10%/20% recurrente)
                                                                              ↓
Vigilancia: Revisa bicicleta devuelta
   ├─ Sin fallas → Aprueba devolución
   └─ Con fallas → Cobra monto según falla → Notifica (correo + campana) → Asigna a Mantenimiento → Repara → Bici disponible
                                                                              ↓
Pago: Efectivo/Transferencia (verifica Empleado Operación) | Tarjeta (automático)
```

## 14. Sistema de notificaciones flotantes personalizado (requisito transversal, exigido por el docente)

- **Todo** mensaje del sistema — alerta, confirmación, error, éxito, aviso — debe usar un componente **propio y personalizado** (estilo UrbanBike), nunca los diálogos nativos del navegador (`alert()`, `confirm()`, `window.prompt`) ni el estilo por defecto de flash messages sin diseñar.
- Tipos a cubrir:
  - **Flotante/toast** (ej. "el administrador cerró tu sesión"): aparece, y se **auto-cierra a los 5 segundos**.
  - **Emergente/modal de confirmación** (ej. "¿seguro que deseas eliminar esta cuenta?"): requiere acción del usuario, con botones estilizados.
  - **Mensajes de éxito/error** de formularios y acciones (ej. tras exportar, pagar, aplicar promoción).
- Debe ser **un solo componente reutilizable** (JS + CSS, o un partial de plantilla) que se invoque desde cualquier vista, para no duplicar estilos por módulo.
- Aplica a los 3 actores (admin, empleados, ciclistas) y a todos los módulos ya cubiertos en este documento (pagos, membresía, flujo de alquiler, notificaciones de fallas, etc.).

## Orden de implementación sugerido (fases para Claude Code)

1. **Sistema de notificaciones flotantes personalizado** (punto 14) — hazlo primero: es la base de UI que van a usar el resto de fases (confirmaciones, avisos, cierre de sesión en tiempo real).
2. **Validaciones + exportación condicionada + cierre de sesión forzado (incluye tiempo real)** (puntos 1, 5, 6) — bajo riesgo, sin tocar flujo de negocio.
3. **Historial de pagos con filtro/paginado** (punto 2) — base de datos para todo lo demás.
4. **Rediseño del flujo alquiler/devolución + notificaciones** (puntos 3, 10, 13) — el núcleo del sistema, hacerlo en su propia sesión.
5. **Factura mejorada con marca UrbanBike** (punto 11) — depende de que el historial de pagos y el flujo ya generen los datos a mostrar.
6. **Beneficios de membresía / tarifas diferenciadas / promociones** (puntos 4, 11-código descuento).
7. **UX general:** catálogo visible, misión/visión, seguimiento de recorrido (puntos 7, 8, 3-sugerencia).
8. **Soporte:** correo + chat interno (punto 12).

## 15. Datos fiscales de la empresa (ficticios, coherentes con Ecuador)

Mientras no se definan los datos reales, usar estos como placeholder definitivo del proyecto:

- **Razón social:** UrbanBike S.A.
- **RUC:** 1293456786001 *(provincia 12 = Los Ríos, tercer dígito 9 = sociedad privada, dígito verificador calculado con el algoritmo módulo 11 real de Ecuador)*
- **Dirección:** Av. Walter Andrade y Séptima Etapa, Quevedo, Los Ríos, Ecuador
- **Teléfono:** 05 275 0000
- **Correo:** sistemasoftwaredev@gmail.com

## 16. Uso del isotipo vs. logo completo

- **Logo completo (bicis + wordmark "UrbanBike"):** encabezados con espacio horizontal — factura, comprobantes, correo, página de login.
- **Isotipo solo (bicis formando la "U", sin texto):** espacios pequeños o cuadrados — ícono de la campana/favicon, avatar del sistema, marca de agua sutil, spinner de carga. Usar el isotipo **recortado del lockup real** (`logo-urbanbike.png`), no el render 3D de Drive (ese es solo mockup de presentación, no un asset para incrustar).

