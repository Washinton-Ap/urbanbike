# Resumen — Patrón de navegación aplicado a todo el sistema

Fecha: 30 de julio de 2026. Corresponde a la tarea "patrón de navegación
consistente en todo el sistema" (título de módulo, botón de volver, logo
al dashboard, cero emojis, lightbox de imágenes, tamaño mínimo de letra).
Ver `docs/HOJA_DE_RUTA.md` sección 3 para el pedido original del docente.

No se tocó el patrón visual Z/F de dashboards ni el WorkPanel — quedan
para otra sesión, tal como se pidió.

## Piezas compartidas (Parte 2 — una sola vez, no repetidas por pantalla)

- `app/templating.py`: nuevo global de Jinja `dashboard_url(user)` — 
  resuelve el dashboard de inicio según `rol_slug` (admin, gerente,
  ciclista, empleado-operacion, empleado-mantenimiento,
  empleado-vigilancia). Es el destino por defecto del logo y del botón
  "Volver".
- `app/templates/base.html`:
  - El logo/nombre "UrbanBike" del sidebar pasó de `<div>` a `<a href="{{ dashboard_url(user) }}">` — antes no era clickeable.
  - Botón "Volver" nuevo en el topbar. Su destino se define con
    `{% block back_url %}{% endblock %}`, que cada plantilla puede
    sobrescribir; si el bloque queda vacío, el botón no se muestra
    (usado en las 7 pantallas de dashboard, donde no aplica "volver").
    Por defecto, si una plantilla no dice nada, apunta al dashboard del
    rol actual.
  - Se agregó `<script src="/static/js/lightbox.js">`.
- `app/static/js/lightbox.js` (nuevo): overlay compartido por
  delegación de eventos sobre `img[data-lightbox]` — funciona con
  imágenes ya presentes en la página y con las que se insertan después
  por JavaScript (catálogos, previews), sin necesidad de "reescanear".
- `app/static/css/main.css`:
  - Estilos nuevos: `.topbar-back`, `.topbar-left`, `.lightbox-overlay`,
    `.lightbox-img`, `.lightbox-close`, `img[data-lightbox]`.
  - **18 reglas CSS** con tamaño de letra por debajo de 12px
    (`0.68rem`, `0.7rem`, `0.72rem`, `0.75rem`, `0.78rem` — entre 10.2px
    y 11.7px reales, con la base del sistema en `15px`) subidas a
    `0.8rem` (12px exacto). Afectaba, entre otros, los encabezados `th`
    de **todas** las tablas del sistema, los badges de estado, y
    `.text-xs` (clase reutilizada en varias plantillas).

Verificación: las 52 plantillas compilan sin errores de sintaxis Jinja
(`templates.env.get_template()` sobre cada archivo), y se probó en vivo
contra la app corriendo, logueado como ciclista, admin y gerente —
confirmando que el botón "Volver" aparece/desaparece según corresponda
y que el logo enlaza al dashboard correcto en cada rol.

Nota aparte: durante la auditoría (Parte 1) también se encontraron
**76 estilos inline** (`style="font-size:0.XXrem"`) por debajo de 12px
repartidos en 32 plantillas — no estaban en el pedido original pero caían
directamente bajo la misma regla ("ningún texto por debajo de un tamaño
legible"), así que se corrigieron también, con el mismo criterio (subir
a `0.8rem`).

## Los 4 emojis reales encontrados (todos en un solo archivo)

Se auditó todo `app/templates/` con un patrón amplio de rangos Unicode
de emoji. Resultado: **los únicos 4 emojis reales de todo el sistema
estaban en `app/templates/ciclista/historial.html`** (ningún otro rol
tenía emojis). Detalle exacto:

| # | Emoji | Línea original | Contexto | Reemplazo |
|---|-------|-----------------|----------|-----------|
| 1 | 📍 (pin de mapa) | línea 74 | Delante del texto "estación de inicio → estación de fin" de cada viaje en la lista del historial | SVG de pin de ubicación (`<svg>` circle+path, 13×13, `stroke-width="2"`), mismo ícono que ya se usaba en el sidebar para "Estaciones" |
| 2 | ⏱ (cronómetro) | línea 77 | Delante de la fecha/hora de inicio de cada viaje, en la misma lista | SVG de reloj (círculo + manecillas, 12×12) |
| 3 | ⚡ (rayo) | línea 184 (dentro de un `<script>`, string `typeHtml`) | Dentro del badge verde "Bicicleta Eléctrica" del modal de detalle que se abre al hacer clic en la foto de una bicicleta | SVG de rayo (`<svg fill="currentColor">`, polígono de rayo, 12×12), insertado como variable `svgRayo` antes del badge |
| 4 | 🚲 (bicicleta) | línea 187 (mismo `<script>`, string `typeHtml`) | Dentro del badge azul "Bicicleta Clásica", en el mismo modal que el punto 3 | SVG de bicicleta (dos círculos + cuadro, `stroke-width="2.2"`, 12×12), variable `svgBici`, mismo ícono que ya se usaba en otras partes del sistema para "bicicleta" |

Los emojis 1 y 2 estaban directo en el HTML de la plantilla (Jinja); los
emojis 3 y 4 estaban dentro de un `<script>`, generados dinámicamente en
la función `abrirModalBici()` que arma el contenido del modal de detalle
de bicicleta — se resolvieron definiendo los SVG como constantes
(`svgRayo`, `svgBici`) y concatenándolos al HTML del badge en vez del
carácter emoji.

Nota: el modal de detalle de bicicleta de este archivo (`biciModal`) es
más que un simple "ampliar imagen" — también muestra tipo de bicicleta y
una descripción persuasiva. Por eso se dejó como está (no se fusionó con
el lightbox compartido); sí cumple igualmente con "imagen clickeable
para ampliarse", solo que con contenido adicional propio.

Aparte de los emojis, se encontró el símbolo de texto **✕** (glifo de
cerrar, no es emoji) repetido en **29 botones de cerrar modal, en 16
plantillas**. No era parte del pedido original, pero era inconsistente
con el resto del sistema (que usa SVG para todos los íconos) — se
reemplazó por el mismo ícono SVG de X que ya usa el resto del sistema
(por ejemplo, el botón de cerrar del panel de accesibilidad).

## Aplicación por rol

Todas las pantallas reciben gratis el título de módulo y el botón
"Volver" por heredar de `base.html` — no hizo falta tocar cada archivo
para eso. Lo que sigue es **solo lo que necesitó un cambio puntual**
(tamaño de letra, emoji/✕, lightbox, o un destino de "volver" distinto
al dashboard por defecto).

### Admin
- `admin/bicicletas.html` — fuente + ✕→SVG (2) + lightbox en la foto de
  la tabla.
- `admin/estaciones.html` — fuente + ✕→SVG (2).
- `admin/tarifas.html` — fuente + ✕→SVG (2).
- `admin/usuarios.html` — fuente + ✕→SVG (3).
- `dashboard.html` (dashboard de admin) — `back_url` vacío (sin botón
  volver, es la pantalla de inicio).
- Sin cambios: `admin/auditoria.html`, `admin/bitacora.html`,
  `admin/reportes.html` (no tenían nada que corregir; heredan el patrón
  igual).

### Gerente
- `gerente/dashboard.html` — `back_url` vacío.
- `gerente/bicicletas.html` — fuente + ✕→SVG (2) + lightbox en la foto
  de la tabla.
- `gerente/empleados.html` — fuente + ✕→SVG (2).
- `gerente/estaciones.html` — fuente + ✕→SVG (2).
- `gerente/tarifas.html` — fuente + ✕→SVG (2).
- `gerente/informe.html` — solo fuente.
- `gerente/reportes.html` — solo fuente.
- Sin cambios: `gerente/reportes_pagos.html`.

### Ciclista
- `ciclista/dashboard.html` — `back_url` vacío.
- `ciclista/detalle_bicicleta.html` — `back_url` → `/ciclista/alquilar`
  (viene del catálogo); se reemplazó su `<dialog id="modal-zoom">`
  propio (imagen sola, sin contenido extra) por el lightbox compartido,
  y se limpió el CSS/JS que ya no se usaba; fuente corregida.
- `ciclista/pago.html` — `back_url` → `/ciclista/historial` (de ahí se
  llega al pago); fuente corregida.
- `ciclista/historial.html` — los 4 emojis reales del sistema (ver
  tabla arriba) + fuente corregida.
- `ciclista/alquilar.html` — fuente + ✕→SVG (1) + lightbox en las fotos
  del catálogo (agregado vía JS, `data-lightbox`/`data-full` en el
  template string `fotoBici()`).
- `ciclista/comprobante.html` — solo fuente.
- `ciclista/viaje_activo.html` — solo fuente.
- Sin cambios: `ciclista/infracciones.html`, `ciclista/reportes.html`.
- `app/templates/componentes/tarjeta_bicicleta.html` (componente
  reutilizado en `alquilar.html`) — lightbox agregado a la foto.

### Empleado — Operación
- `empleado/operacion/dashboard.html` — `back_url` vacío + fuente.
- `empleado/operacion/alquiler_flujo.html` — `back_url` →
  `/empleado/operacion/alquileres` (se llega ahí con el botón "Ver
  flujo" de cada alquiler).
- `empleado/operacion/cobrar_presencial.html` — `back_url` →
  `/empleado/operacion/alquileres` (mismo origen, confirmado en el
  router: todos los redirects de este flujo vuelven a `alquileres`);
  fuente corregida.
- `empleado/operacion/alquileres.html` — fuente + ✕→SVG (2).
- `empleado/operacion/inventario.html` — fuente + ✕→SVG (2).
- `empleado/operacion/pagos.html` — fuente + ✕→SVG (3); se reemplazó su
  `<dialog id="modal-imagen">` propio (zoom del comprobante de pago,
  sin contenido extra) por el lightbox compartido, y se limpió el JS
  (`thumb-comprobante` listener) que ya no se usaba.
- Sin cambios: `empleado/operacion/rebalanceo.html`,
  `empleado/operacion/reportes.html`.

### Empleado — Mantenimiento
- `empleado/mantenimiento/dashboard.html` — `back_url` vacío.
- `empleado/mantenimiento/ordenes.html` — fuente + ✕→SVG (1).
- Sin cambios: `empleado/mantenimiento/bicicletas.html`,
  `empleado/mantenimiento/reportes.html`.

### Empleado — Vigilancia
- `empleado/vigilancia/dashboard.html` — `back_url` vacío + fuente.
- `empleado/vigilancia/cerrar_mantenimiento.html` — fuente + ✕→SVG (1).
- `empleado/vigilancia/devoluciones.html` — fuente + ✕→SVG (1).
- `empleado/vigilancia/infracciones.html` — fuente + ✕→SVG (1).
- `empleado/vigilancia/alertas.html` — solo fuente.
- `empleado/vigilancia/inspeccion.html` — solo fuente (no se le asignó
  un `back_url` específico: no hay ningún link directo hacia esta
  pantalla en el resto de las plantillas hoy, así que se dejó el
  destino por defecto — dashboard de vigilancia — en vez de adivinar un
  origen).
- Sin cambios: `empleado/vigilancia/seguimiento.html`,
  `empleado/vigilancia/reportes.html`.

### Cuenta (todos los roles)
- `perfil.html` — solo fuente. Los avatares de usuario (aquí y en
  `admin/usuarios.html`) quedaron **fuera del lightbox** a propósito:
  se decidió que son identidad visual/chrome de la interfaz, no
  contenido para inspeccionar en grande, a diferencia de fotos de
  bicicletas o comprobantes de pago.
- `roles/dashboard.html` — `back_url` vacío (plantilla de dashboard
  genérico; hoy no está enlazada desde ningún router, se dejó
  consistente por si se usa más adelante).

## Decisiones que no estaban en el pedido original (documentadas al pasar)

- `docs/design-system.md` sigue sin existir en el repo (ya confirmado
  en una sesión anterior) — se usó `app/static/css/main.css` como
  fuente real de tokens de color/tipografía, sin volver a preguntar.
- Las imágenes dentro de un `<dialog>` (por ejemplo, la vista previa de
  foto en los formularios de editar bicicleta de `admin/bicicletas.html`
  y `gerente/bicicletas.html`) **no** se conectaron al lightbox
  compartido: un `<dialog>` abierto con `showModal()` se renderiza en la
  "top layer" del navegador, por encima de cualquier overlay normal
  como el lightbox, así que hubiera quedado invisible/inutilizable. Se
  dejaron sin lightbox por esa razón técnica, no por descuido.
