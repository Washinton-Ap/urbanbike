# TODO

Pendientes detectados durante el desarrollo, no resueltos a propósito
(fuera de alcance de la tarea en curso cuando se encontraron). Revisar
antes de dar por cerrado el proyecto.

## Desfase de disponibilidad: ClickHouse vs. PocketBase (detectado 16-ago-2026)

**Síntoma:** el catálogo del ciclista (`/ciclista/catalogo` y el wizard
`/ciclista/alquilar`) puede mostrar una bicicleta como "disponible"
justo después de que un ciclista la alquiló, o viceversa.

**Causa real:** dos fuentes de verdad para `bicicletas.estado`, sincronizadas
en un solo sentido:
- El flujo de reserva del ciclista (`reservar()`/`finalizar()` en
  `app/routers/ciclista.py`, y `vig_devolver()` en `app/routers/empleado.py`)
  escribe el estado real de la bicicleta **solo en PocketBase**.
- El catálogo que ve el ciclista (`_catalogo_agrupado()` y
  `_catalogo_bicicletas()` en `app/routers/ciclista.py`) lee el estado
  **desde ClickHouse** (`urbanbike_operativa.bicicletas`).
- El espejo entre ambas (`app/db/bicicletas_repo.py:_espejar_pocketbase`)
  es **unidireccional: ClickHouse → PocketBase, nunca al revés** (decisión
  ya documentada ahí mismo). Un alquiler hecho por un ciclista nunca vuelve
  a ClickHouse hasta que alguien edite esa bicicleta desde Admin/Gerente.

**Reproducido:** alquilar una bicicleta como ciclista (`ciclista@urbanbike.com`)
y recargar `/ciclista/catalogo` — la bicicleta recién alquilada sigue
contando como disponible.

**No se corrigió** porque implica una decisión de arquitectura, no un
fix puntual — dos caminos posibles:
1. Espejar también en sentido inverso (PocketBase → ClickHouse) cuando
   cambia el estado de una bicicleta vía el flujo de ciclista/vigilancia.
2. Migrar el flujo de reserva del ciclista a ClickHouse por completo (ya
   era un pendiente de antes, ver `app/db/bicicletas_repo.py`) y eliminar
   el espejo entero.

Ver también `docs/HOJA_DE_RUTA.md` (sección sobre el puente PocketBase)
y la memoria de sesión `bicicletas_repo_y_bug_order_by` para el contexto
completo de por qué existe el espejo en primer lugar.
