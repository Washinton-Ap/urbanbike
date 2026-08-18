# Rediseño de identidad visual — UrbanBike

Este documento complementa a `docs/design-system.md`, no lo reemplaza. La paleta
azul con acento cian, la tipografía Sora / IBM Plex Sans / IBM Plex Mono y el tema
claro/oscuro ya definidos se mantienen intactos. Lo que agrega este documento es
el elemento distintivo que faltaba y la especificación de los tres componentes
que la revisión del docente pidió mejorar: el catálogo con identidad de bicicleta
(observación 3, 4 y 5), el flujo visual del alquiler (observación 8) y el
checklist de devolución (observación 10).

## Por qué hacía falta un elemento distintivo

Un sistema puede tener buena paleta y buena tipografía y aun así sentirse
genérico si no tiene ningún componente que solo podría pertenecer a él. La
revisión del docente lo señaló con otras palabras: "que se vea que es de
bicicleta". Ese es exactamente el problema que resuelve un elemento distintivo.

## El elemento distintivo: la línea de ruta

El dataset que alimenta el proyecto es CitiBike, un sistema real de bicicletas
compartidas cuyo lenguaje visual universal es el mapa de ruta: estaciones
representadas como nodos, conectadas por un trayecto. Ese lenguaje no es una
decoración tomada de cualquier lado, es el vocabulario visual propio del dominio
del proyecto, y por eso se convierte en el elemento distintivo del sistema.

La línea de ruta se usa en tres lugares, y solo en esos tres, para que siga
siendo un signo reconocible y no un adorno repetido sin sentido:

1. El flujo del alquiler, donde cada nodo es un estado real de la tabla
   `alquileres` y cada segmento es un registro de `alquiler_eventos`.
2. El checklist de devolución, donde cada nodo es una categoría del
   inventario `checklist_items`.
3. Un divisor de sección discreto en los dashboards, más adelante, en lugar
   de una línea horizontal genérica.

No se usa como fondo decorativo, ni en la portada, ni en botones. Un elemento
distintivo pierde su fuerza si aparece en todas partes.

## Componente 1: flujo visual del alquiler (observación 8)

Ver `signature_flujo_alquiler.png`.

Sustituye cualquier badge de estado aislado por una línea de tiempo horizontal
con seis nodos: reservado, en curso, devuelta, inspeccionada, facturada, cerrada.
Cada nodo lleva el icono de Material Design Outlined que ya se usa en el resto
del sistema para esa acción, así el icono no es decorativo sino funcional y
consistente con el resto de la interfaz.

Reglas de estado visual:

- Nodo completado: relleno en azul primario, ícono en blanco, hora del evento
  debajo en IBM Plex Mono.
- Nodo pendiente: contorno gris, ícono gris, sin hora.
- Segmento entre dos nodos completados: línea sólida en azul primario.
- Segmento con algún nodo pendiente: línea punteada gris.
- El nodo del paso actual lleva un anillo exterior en el acento cian y una
  etiqueta pequeña "Paso actual".

Fuente de datos: una consulta a `alquiler_eventos` ordenada por `secuencia`,
más el estado actual de `alquileres.estado` para saber cuál nodo resaltar.

Dónde va: en la vista de detalle de un alquiler, tanto para el ciclista como
para Operación y Vigilancia. Reemplaza al texto plano de estado que hubiera
en esa vista hoy.

## Componente 2: checklist de devolución por categoría (observación 10)

Ver `signature_checklist.png`.

El checklist deja de ser una lista plana de doce casillas y se organiza en dos
partes que comparten la pantalla:

**Columna izquierda: mapa de categorías.** Las seis categorías del checklist
(frenos, transmisión, ruedas, luces, cuadro, accesorios) se muestran como una
línea de ruta vertical, igual lenguaje que el componente anterior. Cada
categoría es un nodo: verde si todos sus ítems están en `ok`, ámbar si está en
revisión, gris si aún no se abrió. Encima, un anillo de progreso muestra el
avance total (ítems revisados sobre ítems totales), tomado directamente de
`inspecciones.items_revisados` e `inspecciones.items_totales`.

**Columna derecha: lista de ítems de la categoría activa.** Cada fila muestra
el nombre del ítem y su resultado como una píldora de color, no como una casilla
de verificación genérica, porque el dominio real tiene cuatro resultados
posibles y no dos: correcto, daño leve, daño grave, faltante. Estos cuatro
valores son exactamente el enum de `inspeccion_detalle.resultado`, así que la
interfaz no inventa estados nuevos, solo los visualiza con más criterio.

Reglas de color: correcto en verde, daño leve en ámbar, daño grave y faltante
en rojo. La combinación de color más palabra evita depender solo del color,
igual que en los dashboards.

## Componente 3: catálogo con identidad de bicicleta (observaciones 3, 4 y 5)

Ver `signature_catalogo.png`.

Cada tarjeta de bicicleta tiene:

- Zona de foto con una marca de agua de rueda de radios cuando no hay
  fotografía cargada en `bicicleta_fotos`. No es un ícono de imagen genérico
  roto, es un motivo propio del dominio que refuerza que esto es un sistema
  de bicicletas incluso antes de que exista una foto real.
- Una píldora "Premium" en la esquina cuando `categorias.es_premium = 1`,
  resuelve directamente la observación 5 del catálogo premium.
- Nombre de marca y modelo en Sora, categoría y enfoque en IBM Plex Sans.
- Tres especificaciones con ícono funcional: marchas, tipo de frenos y rodado,
  tomadas de `modelos_bicicleta`. Estas son exactamente las características
  que la observación 4 pidió mostrar.
- Precio en IBM Plex Mono, porque es una cifra y las cifras se leen mejor en
  fuente monoespaciada, igual que en los dashboards.
- Una píldora de estado (disponible, en uso) con los mismos colores semánticos
  del resto del sistema.

El filtro por marca y enfoque de la observación 1 se aplica arriba de la
cuadrícula de tarjetas, como una barra de filtros con selectores, no como un
formulario largo. La consulta que alimenta esto ya existe: es el informe S08.

## Verificación contra el sistema en producción

La paleta usada en los tres mockups no es una paleta nueva inventada para este
documento: es la misma que ya corre en el sistema real, verificada por muestreo
de color sobre una captura de pantalla de tu propio dashboard. Fondo de barra
lateral `#0F1629`, azul primario `#1E85BD`, acento cian `#34A9D1`, verde de
éxito `#10B981`, ámbar de advertencia `#F59F0C`. Nada de esto cambia respecto a
lo que ya está implementado; el rediseño agrega componentes, no reemplaza la
paleta ni la tipografía existentes.

## Qué no cambia

Todo lo que ya define `docs/design-system.md` sigue vigente: la paleta, la
tipografía, el tema claro y oscuro, y las convenciones de espaciado. Este
documento solo agrega el elemento distintivo y especifica tres componentes
puntuales. No es una propuesta de rediseño total de la interfaz.

## Orden sugerido de implementación

Dado el volumen de cambios pendiente, se sugiere abordar un componente por
sesión con Claude Code, en este orden:

1. Flujo visual del alquiler, porque es el que más depende de datos que ya
   existen (`alquiler_eventos`) y no requiere tocar el catálogo todavía.
2. Checklist de devolución, porque depende de `inspeccion_detalle`, ya
   implementado en la fase 1.
3. Catálogo con identidad de bicicleta, porque conviene hacerlo después de
   tener fotos reales cargadas en `bicicleta_fotos`.
