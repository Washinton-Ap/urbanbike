# Cómo continuar con Claude Code

## Paso 1. Guarda estos archivos en tu proyecto

Copia dentro de `docs/`:

- `REDISENO_UI.md`
- `signature_flujo_alquiler.png`
- `signature_checklist.png`
- `signature_catalogo.png`

Estas tres imágenes son la referencia visual exacta que Claude Code debe seguir,
no una idea aproximada. Son mockups pixel por pixel de cómo debe verse cada
componente, generados con la paleta y tipografía reales de tu sistema.

## Paso 2. Prompt para hoy: solo el flujo visual del alquiler

Como acordamos ayer, los cambios son grandes y conviene avanzar de a uno. Pega
esto en Claude Code:

```
Lee docs/design-system.md y docs/REDISENO_UI.md antes de escribir nada.

Contexto: el docente pidió un flujo visual del alquiler (mostrar el trayecto
reservado -> en_curso -> devuelto -> inspeccionado -> facturado -> cerrado
como una línea de tiempo, no como texto plano). Ya existe la tabla
alquiler_eventos en ClickHouse con esa secuencia.

Tarea de hoy, solo esto:
1. Revisa docs/signature_flujo_alquiler.png: es la referencia visual exacta.
2. Crea un componente de plantilla Jinja2 (parcial reutilizable, por ejemplo
   templates/componentes/flujo_alquiler.html) que reciba una lista de eventos
   de alquiler_eventos y el estado actual, y dibuje la línea de tiempo con
   nodos y segmentos como en la imagen de referencia.
3. Usa exactamente los tokens de color de docs/design-system.md, no inventes
   colores nuevos.
4. Los iconos deben ser los mismos que ya usa el resto del sistema (Material
   Icons Outlined), mapeados así: reservado=schedule, en_curso=directions_bike,
   devuelto=assignment_turned_in, inspeccionado=fact_check,
   facturado=receipt_long, cerrado=task_alt.
5. Intégralo en la vista de detalle de un alquiler que ya exista en el
   sistema (busca la ruta actual antes de crear una nueva).
6. No toques el catálogo ni el checklist todavía, eso queda para otra sesión.
7. Cuando termines, muéstrame una captura o descríbeme dónde probarlo.

Antes de escribir código, dime en dos líneas tu plan y qué archivo vas a tocar.
```

## Qué sigue después de esto

Cuando el flujo del alquiler esté funcionando y lo hayas revisado, seguimos con
el checklist de devolución (componente 2) y después el catálogo (componente 3),
en sesiones separadas, tal como quedó especificado en `REDISENO_UI.md`.
