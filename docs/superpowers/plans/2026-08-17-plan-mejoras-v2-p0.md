# Plan de Mejoras V2 — Prioridad 0 (sin decisiones de negocio pendientes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar los puntos 0.1 (auditoría + fix de copy), 0.3 (factura única para reservas de varias bicicletas a la vez) y 0.4 (8 ganchos de notificación reales que faltan) de `docs/Plan_Mejoras_UrbanBike_V2.md`, dejando fuera 0.2, 2.1, 2.5, 2.6 y "Simulación académica" (pendientes de decisión de Washington).

**Architecture:** Sin cambios de arquitectura. Se reutiliza el patrón ya establecido: PocketBase (OLTP) para `viajes`/`pagos`/`notificaciones`, `notificaciones_repo.notificar_usuario()`/`notificar_rol()` como único punto de disparo de avisos, scripts `etl/NN_*.py` idempotentes para cambios de schema (PocketBase no permite agregar un valor a un select o un campo nuevo sin PATCH completo de la colección), y `DatosFactura`/`LineaFactura` (`app/reportes/factura.py`) reutilizados para la factura de grupo.

**Tech Stack:** FastAPI, PocketBase (colecciones `viajes`, `pagos`, `notificaciones`), Jinja2, JS vanilla (sin framework).

**Spec:** `docs/Plan_Mejoras_UrbanBike_V2.md` (puntos 0.1, 0.3, 0.4) + `docs/HOJA_DE_RUTA.md` sección 70 (contexto de 0.1) y catálogo de 22 tipos de notificación auditado (contexto de 0.4).

## Global Constraints

- **Sin suite de pytest en este proyecto.** La verificación establecida en todo `docs/HOJA_DE_RUTA.md` es E2E real: servidor `uvicorn` real, PocketBase y ClickHouse reales, cuentas reales, requests HTTP autenticados con CSRF real -- nunca mocks. Cada paso de "test" de este plan sigue ese mismo criterio, no pytest.
- **Datos reales, nunca simulados.** Cualquier dato de prueba creado durante la verificación de una tarea se limpia al final de esa tarea (borrar registros creados, revertir estado de bicicletas), igual que documenta cada sección de `docs/HOJA_DE_RUTA.md`.
- **Cambios de schema de PocketBase van en `etl/NN_*.py` idempotentes**, seguiendo exactamente el patrón de `etl/12`, `etl/14`, `etl/15` (PATCH del schema completo de la colección vía `pb._session.patch`). Nunca se edita el schema a mano desde el admin de PocketBase.
- **`notificaciones_repo.notificar_usuario()`/`notificar_rol()` son el único punto de disparo** de avisos -- nunca crear un registro en `notificaciones` a mano desde un router.
- Nunca tocar 0.2 (código de descuento por volumen), 2.1 (bicicletas exclusivas de suscriptores), 2.5 (filtro dataset académico/real) ni el texto de "Simulación académica" -- pendientes de decisión de Washington.
- Commits frecuentes: un commit por tarea completada y verificada, no al final de todo el plan.

---

## Grupo A — 0.1: restaurar el congelamiento del subtotal en `fecha_fin`

**Contexto real (auditado hoy, con evidencia de ejecución real, no solo lectura de código):** la Tarea 7 del plan `docs/superpowers/plans/2026-08-16-modalidad-tarifa-real.md` (`vig_devolver()`) y su Tarea 9 (`costo-en-vivo.js`) cambiaron el subtotal de un viaje en modalidad `hora` para que, mientras el viaje espera validación de Vigilancia, siga corriendo contra `ahora` (el momento real de confirmación) en vez de quedarse fijo en `fecha_fin` (el momento en que el ciclista reportó la devolución). Se confirmó con una prueba real de ejecución (no solo el texto del código): se tomó un viaje real que sigue `pendiente_validacion` en la base (`UB-009`, `inicio_segmento_actual = 2026-08-16T18:03:16Z`) y se corrió la fórmula real de `vig_devolver()` dos veces, con 2 minutos reales de diferencia -- el subtotal calculado subió de **$144.82 a $144.98**, y se confirmó que el servidor real sirve ahora mismo el mismo cálculo en `costo-en-vivo.js` (`curl` directo al archivo estático real). El cambio fue deliberado (documentado en `docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md:102`, "mismo criterio de siempre") pero revirtió, sin volver a confirmarlo explícitamente con Washington, la decisión de la sección 70 de `docs/HOJA_DE_RUTA.md` (congelar el subtotal en `fecha_fin`, solo el recargo por demora corre tras las 5h de gracia). **Decisión reconfirmada con Washington el 17-ago-2026: restaurar el congelamiento en `fecha_fin`.** Esto es un cambio real de lógica de cobro (backend + vista en vivo), no una corrección de copy -- el texto de `viaje_activo.html:112` ("el costo se congela con la hora de este reporte") ya es correcto con este diseño y NO se toca.

### Task A1: Restaurar el congelamiento del subtotal en `fecha_fin` (backend + vista en vivo)

**Files:**
- Modify: `app/routers/empleado.py` (`vig_devolver()`, bloque de cálculo del segmento `hora`, líneas ~1586-1599)
- Modify: `app/static/js/costo-en-vivo.js` (`costoDetallado()`, líneas 19-58)
- Modify: `app/templates/empleado/vigilancia/devoluciones.html` (comentario desactualizado, líneas ~234-236)
- Modify: `app/routers/ciclista.py` (docstring de `finalizar()`, líneas ~800-806)

**Interfaces:** ninguna cambia de firma -- `costoDetallado()` conserva los mismos 6 parámetros, `vig_devolver()` conserva el mismo contrato con `pagos`/`alquileres_repo.cerrar_segmento()`.

- [ ] **Step 1: `empleado.py` -- congelar `minutos_ultimo_segmento` en `fecha_fin`, no en `ahora`**

Reemplazar el bloque `if modalidad_final == "hora":` (líneas ~1586-1599) por:

```python
            if modalidad_final == "hora":
                # Gracia de 5h desde que el ciclista reporto la devolucion
                # (fecha_fin del viaje), NO desde el inicio del segmento.
                fecha_fin_reportada = viaje.get("fecha_fin", "")
                fin_dt = (datetime.fromisoformat(fecha_fin_reportada.replace("Z", "+00:00"))
                          if fecha_fin_reportada else ahora)

                # El subtotal del segmento abierto se CONGELA en fecha_fin
                # (el momento en que el ciclista reporto la devolucion) --
                # decision de negocio reconfirmada con Washington 17-ago-2026:
                # la espera hasta que Vigilancia confirme NO es tiempo de uso
                # real, es tiempo de espera -- solo el recargo por demora
                # (tras 5h de gracia) cobra por esa espera, nunca el
                # subtotal. Restaura el diseno original de la seccion 70 de
                # docs/HOJA_DE_RUTA.md, que la Tarea 7 del plan
                # "modalidad-tarifa-real" habia revertido sin reconfirmar.
                # Si el viaje no fue reportado antes (Vigilancia cierra un
                # viaje todavia 'activo'), fecha_fin_reportada esta vacio y
                # fin_dt = ahora -- mismo resultado que antes de este cambio,
                # porque no hubo espera que congelar.
                # Piso de 1 minuto (mismo criterio de siempre).
                minutos_ultimo_segmento = max(1, int((fin_dt - inicio_dt).total_seconds() / 60))
                subtotal_ultimo_segmento = round(minutos_ultimo_segmento / 60 * precio_modalidad_final_con_promo, 2)

                retraso_min = max(0.0, (ahora - fin_dt).total_seconds() / 60 - 300) if fecha_fin_reportada else 0.0
                precio_hora_display = precio_modalidad_final  # SIN promo -- multiplicador del recargo
```

(El campo `duracion_minutos` del viaje, unas líneas más abajo, sigue calculándose contra `ahora` como hasta ahora -- es un dato informativo de cuánto tiempo estuvo la bicicleta fuera de servicio, no el monto cobrado, y no forma parte de esta decisión de negocio.)

- [ ] **Step 2: `costo-en-vivo.js` -- mismo congelamiento en la vista en vivo**

Reemplazar el bloque `if (modalidad === 'hora') { ... }` dentro de `costoDetallado()` (líneas ~52-57) por:

```javascript
  let subtotalSegmentoAbierto;
  if (modalidad === 'hora') {
    // El subtotal se congela en fechaFinISO (el momento en que el
    // ciclista reporto la devolucion) -- decision de negocio
    // reconfirmada con Washington 17-ago-2026, ver
    // empleado.py:vig_devolver(). Mientras el viaje sigue 'activo'
    // (fechaFinISO vacio), sigue el reloj real contra 'ahora'.
    const finSegmento = fechaFinISO ? new Date(fechaFinISO) : ahora;
    const horas = Math.max(0, (finSegmento - inicioSegmento) / 3600000);
    subtotalSegmentoAbierto = horas * precioModalidad;
  } else {
    subtotalSegmentoAbierto = precioModalidad; // tarifa plana, ya se cobra completa
  }
```

Y corregir el bloque de comentario grande de arriba (líneas 19-45) para que ya no diga que el segmento "hora" *"sigue el reloj REAL hasta 'ahora' -- incluso después de que el ciclista reportó la devolución... ya NO se congela"* -- reemplazar ese párrafo por una descripción del comportamiento restaurado (se congela en `fechaFinISO` si ya existe).

- [ ] **Step 3: Corregir el comentario desactualizado en `devoluciones.html`**

En `app/templates/empleado/vigilancia/devoluciones.html` (líneas ~234-236), el comentario que documenta *"ya no se congela"* queda desactualizado con este cambio -- corregirlo para reflejar que el monto en vivo vuelve a congelarse en `fecha_fin` (la lógica de la celda no cambia, solo llama a la misma `costoDetallado()` ya corregida en el Step 2).

- [ ] **Step 4: Corregir el docstring de `finalizar()` en `ciclista.py`**

En `app/routers/ciclista.py`, líneas ~800-806, el docstring de `finalizar()` dice *"el costo sigue corriendo a la tarifa normal ... El monto real se congela recién cuando Vigilancia confirma"* -- esto vuelve a ser falso con este cambio. Corregir para que diga que el monto se congela con la hora real de este reporte (`fecha_fin`), y que solo el recargo por demora (tras 5h de gracia) sigue corriendo hasta que Vigilancia confirme.

- [ ] **Step 5: Verificación E2E real -- replicar el mismo método de prueba que descubrió el problema**

Usando el mismo viaje real `UB-009` (`pendiente_validacion` desde el 16-ago), correr la fórmula corregida de `vig_devolver()` dos veces con 2+ minutos reales de diferencia y confirmar que el subtotal calculado **ya no cambia** entre ambas mediciones (a diferencia de la prueba que motivó este hallazgo, que subió de $144.82 a $144.98). Luego hacer un ciclo E2E nuevo y limpio: reservar una bicicleta real, reportar devolución, esperar ~2 minutos reales, y validar como Vigilancia -- confirmar que `pago.subtotal` refleja la duración hasta el reporte (no hasta la validación) y que `pago.recargo_demora = 0` (sigue dentro de las 5h de gracia). Confirmar visualmente (HTML servido) que `viaje_activo.html` y `devoluciones.html` muestran el mismo subtotal congelado.

- [ ] **Step 6: Limpieza**

Con el viaje de prueba nuevo del Step 5: validar la devolución si no se hizo, borrar el pago, el viaje y las notificaciones generados; restaurar la bicicleta a `disponible`. El viaje `UB-009` usado para la medición de fórmula (Step 5, primera parte) no se modificó -- se leyó, no se escribió -- así que no requiere limpieza, pero queda pendiente de que una futura sesión decida si es dato real o limpieza vieja de otra sesión (igual que ya señala la sección 70 sobre `UB-004`).

- [ ] **Step 7: Commit**

```bash
git add app/routers/empleado.py app/static/js/costo-en-vivo.js app/templates/empleado/vigilancia/devoluciones.html app/routers/ciclista.py
git commit -m "fix: restaurar el congelamiento del subtotal en fecha_fin (revierte Tarea 7/9 de modalidad-tarifa-real, reconfirmado con Washington)"
```

---

## Grupo B — 0.4: ganchos de notificación reales que faltan

8 ganchos reales identificados en la auditoría de hoy (de los 13 originalmente sin gancho en `docs/HOJA_DE_RUTA.md`; los otros 5 quedan fuera porque el evento/concepto que deberían disparar no existe todavía en el código -- inventario/repuestos, "crítico" en auditoría, bloqueo automático pendiente de decisión, rebalanceo, y reporte de falla por Vigilancia que no aplica).

### Task B1: Agregar los 8 tipos de notificación nuevos al select `notificaciones.tipo`

**Files:**
- Create: `etl/17_ampliar_tipos_notificacion_ronda2.py`

**Interfaces:**
- Produce: valores de select `notificaciones.tipo` disponibles para las Tasks B2-B9: `viaje_iniciado`, `pago_rechazado`, `promocion_nueva`, `devolucion_validada`, `cobro_pendiente`, `devolucion_pendiente_validar`, `bici_disponible`, `registro_nuevo`.

- [ ] **Step 1: Crear el script, mismo patrón exacto de `etl/14_ampliar_tipos_notificacion.py`**

```python
"""
ETL paso 17 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/13/14): agrega los 8 tipos de notificacion nuevos que cierran los
ganchos reales identificados en el punto 0.4 de
docs/Plan_Mejoras_UrbanBike_V2.md (auditoria completa del catalogo de 22
tipos de notificacion en docs/HOJA_DE_RUTA.md):

  - viaje_iniciado               -- ciclista.py:reservar()
  - pago_rechazado               -- empleado.py:op_pagos_rechazar_transferencia()
  - promocion_nueva              -- gerente.py:promociones_crear()
  - devolucion_validada          -- empleado.py:vig_devolver()
  - cobro_pendiente              -- ciclista.py:pago_confirmar(), empleado.py (transferencia presencial)
  - devolucion_pendiente_validar -- ciclista.py:finalizar()
  - bici_disponible              -- empleado.py:vig_mantenimiento_certificar()
  - registro_nuevo               -- auth.py:registro_post()

Mismo mecanismo ya usado en etl/12/13/14: PATCH del schema completo de la
coleccion (la API de PocketBase no permite agregar un valor suelto a un
select existente). Idempotente: correrlo dos veces no falla ni duplica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402


def _agregar_valores_select_si_faltan(pb, nombre_coleccion: str, nombre_campo: str, valores_nuevos: list[str]) -> None:
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == nombre_coleccion), None)
    if not coleccion:
        print(f"  {nombre_coleccion}.{nombre_campo}: coleccion no encontrada, se omite.")
        return
    campo = next((f for f in coleccion["fields"] if f["name"] == nombre_campo), None)
    if not campo:
        print(f"  {nombre_coleccion}.{nombre_campo}: campo no encontrado, se omite.")
        return
    faltantes = [v for v in valores_nuevos if v not in campo["values"]]
    if not faltantes:
        print(f"  {nombre_coleccion}.{nombre_campo}: los valores nuevos ya existen, sin cambios.")
        return
    campo["values"] = campo["values"] + faltantes
    pb._session.patch(f"{pb.base_url}/api/collections/{coleccion['id']}", json=coleccion).raise_for_status()
    print(f"  {nombre_coleccion}.{nombre_campo}: agregados valores {faltantes}.")


def main() -> None:
    pb = get_admin_client()
    print("Agregando tipos de notificacion nuevos (ronda 2)...")
    _agregar_valores_select_si_faltan(
        pb, "notificaciones", "tipo",
        ["viaje_iniciado", "pago_rechazado", "promocion_nueva", "devolucion_validada",
         "cobro_pendiente", "devolucion_pendiente_validar", "bici_disponible", "registro_nuevo"],
    )
    print("Listo.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Ejecutar contra PocketBase real**

Run: `python etl/17_ampliar_tipos_notificacion_ronda2.py`
Expected: imprime `agregados valores [...]` con los 8 tipos la primera vez.

- [ ] **Step 3: Verificar idempotencia**

Run de nuevo: `python etl/17_ampliar_tipos_notificacion_ronda2.py`
Expected: imprime `los valores nuevos ya existen, sin cambios.`

- [ ] **Step 4: Commit**

```bash
git add etl/17_ampliar_tipos_notificacion_ronda2.py
git commit -m "feat: agregar 8 tipos de notificacion nuevos para los ganchos reales del punto 0.4"
```

### Task B2: Gancho #1 -- Ciclista, viaje iniciado

**Files:**
- Modify: `app/routers/ciclista.py` (función `reservar()`, dentro del bloque `try` que crea el viaje, líneas ~621-636)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_usuario(pb, usuario_id, *, tipo, titulo, mensaje, enlace="")` (ya existe, `app/db/notificaciones_repo.py:99`). `notificaciones_repo` ya está importado en `ciclista.py`.

- [ ] **Step 1: Agregar la llamada, justo antes del flash de éxito**

En `ciclista.py`, dentro de `reservar()`, después de `registrar_auditoria(...)` (línea ~633) y antes de `request.session["flash"] = {"type": "success", ...}` (línea ~635):

```python
        notificaciones_repo.notificar_usuario(
            pb, user_id, tipo="viaje_iniciado",
            titulo="Viaje iniciado",
            mensaje=f"Iniciaste un viaje con la bicicleta {bicicleta_codigo} desde {estacion_inicio_nombre}.",
            enlace=f"/ciclista/viaje-activo/{nuevo_viaje['id']}",
        )

        request.session["flash"] = {"type": "success", "msg": f"Viaje iniciado en {estacion_inicio_nombre}. Buen viaje."}
```

- [ ] **Step 2: Verificación E2E real**

Reservar una bicicleta real con una cuenta ciclista real. Consultar en PocketBase (admin UI o `pb.list_records("notificaciones", filter='usuario_id = "<id>" && tipo = "viaje_iniciado"')`) que se creó la notificación con el mensaje correcto. Confirmar también en la campana de la UI (`GET /ciclista/notificaciones` o el badge de no leídas en `base.html`).

- [ ] **Step 3: Limpieza**

Finalizar y validar el viaje de prueba (igual que Task A1, Step 4). Borrar la notificación, el pago y el viaje generados. Restaurar la bicicleta a `disponible`.

- [ ] **Step 4: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: notificar al ciclista cuando inicia un viaje"
```

### Task B3: Gancho #2 -- Ciclista, pago rechazado

**Files:**
- Modify: `app/routers/empleado.py` (función `op_pagos_rechazar_transferencia()`, líneas 891-917)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_usuario(...)` (ya importado en `empleado.py`).

**Nota:** esto también corrige un hallazgo real de la auditoría -- la línea 915 devuelve el flash *"Transferencia rechazada. Se notificó al ciclista."* pero hoy nadie notifica nada. Con este cambio el mensaje deja de ser falso.

- [ ] **Step 1: Agregar la llamada antes del flash final**

En `empleado.py`, dentro de `op_pagos_rechazar_transferencia()`, después de `registrar_auditoria(...)` (línea ~914) y antes de `return _flash(...)` (línea 915):

```python
        notificaciones_repo.notificar_usuario(
            pb, registro.get("ciclista_id", ""), tipo="pago_rechazado",
            titulo="Transferencia rechazada",
            mensaje=f"Tu comprobante de transferencia fue rechazado. Motivo: {motivo.strip()}. "
                    "Puedes intentar de nuevo desde Historial de Pagos.",
            enlace="/ciclista/pagos",
        )
        return _flash(request, "/empleado/operacion/pagos", "success", "Transferencia rechazada. Se notificó al ciclista.")
```

- [ ] **Step 2: Verificación E2E real**

Con una cuenta ciclista real, generar un pago por transferencia con comprobante (`POST /ciclista/pago/{id}/confirmar` con `metodo_pago=transferencia`), quedando en `verificacion_pendiente`. Con una cuenta de Operación real, rechazarlo (`POST /empleado/operacion/pagos/{id}/rechazar-transferencia`). Confirmar la notificación real creada para el ciclista con el motivo correcto.

- [ ] **Step 3: Limpieza**

Borrar la notificación, el pago y el viaje de prueba usados; restaurar la bicicleta.

- [ ] **Step 4: Commit**

```bash
git add app/routers/empleado.py
git commit -m "feat: notificar al ciclista cuando se rechaza su transferencia (corrige flash que mentia)"
```

### Task B4: Gancho #3 -- Ciclista, promoción nueva activa

**Files:**
- Modify: `app/routers/gerente.py` (imports, y función `promociones_crear()`, líneas 1830-1855)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_rol(rol_destino, *, tipo, titulo, mensaje, enlace="")` (`app/db/notificaciones_repo.py:124`). Difusión a `"ciclista"` como `rol_destino` -- confirmado que es el mismo slug real que usa el resto del código (`app/routers/ciclista.py` usa `para_rol="ciclista"`/`autor_rol="ciclista"` en varios lugares) y que `notificaciones_repo._filtro_destinatario()` compara `rol_destino` contra el `rol_slug` real de la sesión, así que llega a todos los ciclistas logueados igual que hoy llega a todo un rol de empleado.

- [ ] **Step 1: Agregar el import**

En `app/routers/gerente.py` línea 11, cambiar:
```python
from app.db import bicicletas_repo, estaciones_repo, promociones_repo, tarifas_repo, clickhouse as ch
```
por:
```python
from app.db import bicicletas_repo, estaciones_repo, notificaciones_repo, promociones_repo, tarifas_repo, clickhouse as ch
```

- [ ] **Step 2: Agregar la llamada en `promociones_crear()`**

Después de `_log(request, "Crear promoción", ...)` (línea ~1852) y antes del `return _flash(...)` (línea 1853):

```python
        notificaciones_repo.notificar_rol(
            "ciclista", tipo="promocion_nueva",
            titulo="Nueva promoción disponible",
            mensaje=f"Hay una nueva promoción activa: {promo['nombre']} ({promo['codigo']}).",
            enlace="/ciclista/promociones",
        )
        return _flash(request, "/gerente/promociones", "success", f"Promoción {promo['codigo']} creada correctamente.")
```

- [ ] **Step 3: Verificación E2E real**

Con una cuenta Gerente real, crear una promoción real (`POST /gerente/promociones/nueva`). Confirmar que se crea una notificación con `rol_destino = "ciclista"` y `tipo = "promocion_nueva"`, y que una cuenta ciclista real la ve en su campana.

- [ ] **Step 4: Limpieza**

Borrar la notificación y la promoción de prueba.

- [ ] **Step 5: Commit**

```bash
git add app/routers/gerente.py
git commit -m "feat: notificar a todos los ciclistas cuando el gerente activa una promocion nueva"
```

### Task B5: Gancho #4 -- Ciclista, devolución validada

**Files:**
- Modify: `app/routers/empleado.py` (función `vig_devolver()`, dentro del bloque `if not existentes:`, después de las notificaciones de `pago_pendiente`/`penalizacion`, líneas ~1684-1705)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_usuario(...)` (ya importado en `empleado.py`).

- [ ] **Step 1: Agregar la llamada, siempre (no condicional a recargo)**

Después del bloque `if recargo_demora > 0:` que notifica `penalizacion` (línea ~1704), agregar, todavía dentro del `if not existentes:`:

```python
            notificaciones_repo.notificar_usuario(
                pb, viaje.get("ciclista_id", ""), tipo="devolucion_validada",
                titulo="Devolución confirmada",
                mensaje=f"Vigilancia confirmó la devolución de {viaje.get('bicicleta_codigo', '—')}. "
                        f"Duración real: {duracion} min.",
                enlace="/ciclista/historial",
            )
```

- [ ] **Step 2: Verificación E2E real**

Reservar, reportar devolución y validar como Vigilancia con datos reales. Confirmar que se crean 2 o 3 notificaciones para el ciclista según corresponda (`pago_pendiente` siempre, `penalizacion` solo si hubo recargo, `devolucion_validada` siempre) -- las tres con datos reales coherentes con el pago creado.

- [ ] **Step 3: Limpieza**

Borrar las notificaciones, el pago y el viaje de prueba; restaurar la bicicleta.

- [ ] **Step 4: Commit**

```bash
git add app/routers/empleado.py
git commit -m "feat: notificar al ciclista cuando Vigilancia confirma la devolucion (independiente del pago)"
```

### Task B6: Gancho #5 -- Operación, cobro pendiente de verificar

**Files:**
- Modify: `app/routers/ciclista.py` (función que procesa `pago_confirmar` / `POST /ciclista/pago/{id}/confirmar`, ramas `efectivo` ~línea 1010-1026 y `transferencia` ~línea 1064-1090)
- Modify: `app/routers/empleado.py` (rama de transferencia presencial dentro del endpoint de cobro presencial, líneas ~795-823)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_rol("empleado-operacion", ...)`. Confirmado que `"empleado-operacion"` es el mismo `rol_destino` que ya usa `empleado.py:1999` para `orden_asignada` -- mismo patrón, sin inventar un slug nuevo.

**Nota de alcance:** el cobro presencial con tarjeta (`empleado.py`, líneas ~750-793) paga de inmediato (`estado: "pagado"`) y ya notifica `pago_aprobado` -- no necesita este gancho. Solo los 3 caminos que dejan el pago en un estado "pendiente de que Operación lo revise" (`pendiente_efectivo`, `verificacion_pendiente` en cualquiera de sus dos orígenes) lo necesitan.

- [ ] **Step 1: `ciclista.py`, rama efectivo**

Después de `registrar_auditoria(...)` (línea ~1023) y antes del `request.session["flash"]` (línea ~1024), dentro del bloque `if metodo_pago == "efectivo":`:

```python
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Cobro en efectivo pendiente",
                mensaje=f"Un ciclista se acercará a pagar en efectivo con el código {comprobante}.",
                enlace="/empleado/operacion/pagos",
            )
            request.session["flash"] = {"type": "info", "msg":
                f"Dirígete al empleado de operación más cercano con el código de pago: {comprobante} para completar el pago."}
```

- [ ] **Step 2: `ciclista.py`, rama transferencia**

Dentro del bloque `if metodo_pago == "transferencia":`, después de `registrar_auditoria(...)` (unas líneas después de 1090), agregar antes de retornar:

```python
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Transferencia pendiente de verificar",
                mensaje=f"Un ciclista subió un comprobante de transferencia (código {comprobante}) que espera verificación.",
                enlace="/empleado/operacion/pagos",
            )
```

- [ ] **Step 3: `empleado.py`, transferencia presencial**

En `empleado.py`, después de `registrar_auditoria(...)` (línea ~821), dentro del bloque `if metodo_pago == "transferencia":` del cobro presencial:

```python
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="cobro_pendiente",
                titulo="Transferencia presencial pendiente de verificar",
                mensaje=f"Se subió un comprobante de transferencia presencial (código {comprobante}) que espera verificación.",
                enlace="/empleado/operacion/pagos",
            )
            return _flash(request, "/empleado/operacion/pagos", "info",
                          "Comprobante recibido. Queda pendiente de verificación.")
```

- [ ] **Step 4: Verificación E2E real**

Probar los 3 caminos con datos reales: (a) un ciclista marca un pago para efectivo, (b) un ciclista sube un comprobante de transferencia, (c) un empleado de Operación cobra presencial por transferencia. Confirmar en cada caso una notificación real con `rol_destino = "empleado-operacion"` y `tipo = "cobro_pendiente"`, visible para una cuenta de Operación real.

- [ ] **Step 5: Limpieza**

Borrar notificaciones, pagos y viajes de prueba; restaurar bicicletas a `disponible`.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ciclista.py app/routers/empleado.py
git commit -m "feat: notificar a Operacion cuando un cobro queda pendiente de verificar (efectivo o transferencia)"
```

### Task B7: Gancho #7 -- Vigilancia, devolución pendiente de validar

**Files:**
- Modify: `app/routers/ciclista.py` (función `finalizar()`, líneas 783-847)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_rol("empleado-vigilancia", ...)`.

- [ ] **Step 1: Agregar la llamada después de la auditoría**

Después de `registrar_auditoria(...)` (línea ~823) y antes del bloque del código de descuento por buena conducta (línea ~825):

```python
        notificaciones_repo.notificar_rol(
            "empleado-vigilancia", tipo="devolucion_pendiente_validar",
            titulo="Devolución por validar",
            mensaje=f"{user.get('name') or user.get('email', '')} reportó la devolución en "
                    f"{estacion_fin_nombre} -- pendiente de confirmar la entrega física.",
            enlace="/empleado/vigilancia/devoluciones",
        )
```

- [ ] **Step 2: Verificación E2E real**

Reservar y reportar devolución con una cuenta ciclista real. Confirmar una notificación real con `rol_destino = "empleado-vigilancia"`, visible para una cuenta de Vigilancia real.

- [ ] **Step 3: Limpieza**

Validar la devolución como Vigilancia para cerrar el viaje; borrar notificaciones, pago y viaje de prueba; restaurar la bicicleta.

- [ ] **Step 4: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: notificar a Vigilancia cuando un ciclista reporta una devolucion pendiente de validar"
```

### Task B8: Gancho #9 -- Operación, bicicleta disponible tras mantenimiento

**Files:**
- Modify: `app/routers/empleado.py` (función `vig_mantenimiento_certificar()`, líneas 2235-2263)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_rol("empleado-operacion", ...)`.

- [ ] **Step 1: Agregar la llamada después de marcar la bici disponible**

Después de `pb.update_record("bicicletas", bici_id, {"estado": "disponible"})` (línea ~2252):

```python
        bici_id = orden.get("bicicleta_id", "")
        if bici_id:
            pb.update_record("bicicletas", bici_id, {"estado": "disponible"})
            notificaciones_repo.notificar_rol(
                "empleado-operacion", tipo="bici_disponible",
                titulo="Bicicleta disponible",
                mensaje=f"{orden.get('bicicleta_codigo', oid)} completó mantenimiento y está disponible nuevamente.",
                enlace="/empleado/operacion/bicicletas",
            )
```

- [ ] **Step 2: Verificación E2E real**

Certificar el cierre de una orden de mantenimiento real (`POST /empleado/vigilancia/mantenimiento/{oid}/certificar`). Confirmar la notificación real con `rol_destino = "empleado-operacion"`, visible para una cuenta de Operación real.

- [ ] **Step 3: Limpieza**

Restaurar el estado de la bicicleta y la orden de mantenimiento de prueba a como estaban antes (si se usó una orden real existente, revertir su `estado` y `fecha_cierre`; si se creó una orden nueva para la prueba, borrarla). Borrar la notificación generada.

- [ ] **Step 4: Commit**

```bash
git add app/routers/empleado.py
git commit -m "feat: notificar a Operacion cuando una bicicleta queda disponible tras mantenimiento"
```

### Task B9: Gancho #12 -- Admin, registro público nuevo

**Files:**
- Modify: `app/routers/auth.py` (función `registro_post()`, líneas 182-278)

**Interfaces:**
- Consumes: `notificaciones_repo.notificar_rol("admin", ...)`. `notificaciones_repo` ya está importado en `auth.py` (línea 21).

- [x] **Step 1: Agregar la llamada después de la auditoría**

Después de `registrar_auditoria(...)` (línea ~268) y antes de `request.session["verificar_email"] = email` (línea ~270):

```python
    notificaciones_repo.notificar_rol(
        "admin", tipo="registro_nuevo",
        titulo="Nuevo registro de ciclista",
        mensaje=f"{nombre_completo} ({email}) se registró como ciclista.",
        enlace="/admin/usuarios",
    )
```

- [x] **Step 2: Verificación E2E real**

Completar un registro público real (`POST /auth/registro`). Confirmar la notificación real con `rol_destino = "admin"`, visible para una cuenta Admin real.

**Verificado dos veces con datos reales** (18-ago-2026 por el implementador SDD, y de nuevo el 19-ago-2026 en esta sesión a pedido explícito de Washington): `POST /auth/registro` real → `notificaciones` real con `rol_destino="admin"`, `tipo="registro_nuevo"` → confirmado visible en `GET /notificaciones` con sesión real de `admin@urbanbike.com`. Detalle completo en `docs/HOJA_DE_RUTA.md` sección 73.

- [x] **Step 3: Limpieza**

Borrar la notificación y el usuario de prueba creado (o, si se reutiliza una cuenta de prueba ya existente para no crear usuarios nuevos, omitir este sub-paso y anotarlo).

Limpieza confirmada ambas veces (404 al releer notificación y usuario de prueba borrados).

- [x] **Step 4: Commit**

```bash
git add app/routers/auth.py
git commit -m "feat: notificar a Admin cuando se completa un registro publico de ciclista"
```

Commit real: `54c725c` (rama `worktree-plan-mejoras-v2-p0`, worktree `.claude/worktrees/plan-mejoras-v2-p0` -- **no está en `main`**). Revisor independiente: sí, verdicto "review clean" registrado en `.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/progress.md` línea 80.

---

## Grupo C — 0.3: factura única para múltiples bicicletas alquiladas a la vez

**Diseño acordado con Washington:** hoy no existe ninguna forma de reservar varias bicicletas en una sola acción (cada `POST /ciclista/reservar` crea un viaje independiente), y el pago se genera por bicicleta, en el momento en que Vigilancia valida CADA devolución -- que puede no coincidir en el tiempo entre bicicletas del mismo "grupo". El alcance real de esta tarea:

1. Selección múltiple real en el catálogo (`/ciclista/alquilar`) que crea N viajes de una sola vez, todos con el mismo `grupo_reserva_id` nuevo.
2. Cada bicicleta se sigue cobrando individualmente al devolverse (sin cambiar `vig_devolver()`), pero cuando la ÚLTIMA bicicleta del grupo queda pagada, se puede emitir **una sola factura** con el detalle de todas.
3. Mientras el grupo no esté completo, no se ofrece una factura combinada -- se indica que está pendiente de que se devuelvan/paguen las demás bicicletas del grupo.

### Task C1: Campo `grupo_reserva_id` en `viajes` y `pagos`

**Files:**
- Create: `etl/18_agregar_grupo_reserva.py`

**Interfaces:**
- Produce: campo de texto `grupo_reserva_id` (no requerido) en las colecciones `viajes` y `pagos`, disponible para las Tasks C2-C6.

- [ ] **Step 1: Crear el script, mismo patrón de `etl/15_agregar_campos_modalidad.py`**

```python
"""
ETL paso 18 (unico, NO forma parte del DAG horario -- mismo patron que
etl/12/14/15): agrega 'grupo_reserva_id' a 'viajes' y 'pagos' -- soporte
real para el punto 0.3 de docs/Plan_Mejoras_UrbanBike_V2.md (factura
unica para varias bicicletas reservadas a la vez).

'viajes.grupo_reserva_id' se llena al crear el viaje (ver
ciclista.py:reservar_grupo()) cuando la reserva vino de una seleccion
multiple -- vacio para reservas individuales (compatibilidad con viajes
existentes). 'pagos.grupo_reserva_id' se copia del viaje al crear el
pago (ver empleado.py:vig_devolver()) para no tener que hacer join con
'viajes' en las pantallas que listan pagos (historial.html, pagos.html).

Mismo mecanismo que etl/15: PATCH del schema completo de la coleccion.
Idempotente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPO_GRUPO = [{"name": "grupo_reserva_id", "type": "text", "required": False}]


def _agregar_campos_si_faltan(pb, nombre_coleccion: str, campos_nuevos: list[dict]) -> None:
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == nombre_coleccion), None)
    if not coleccion:
        print(f"  {nombre_coleccion}: coleccion no encontrada, se omite.")
        return
    nombres_actuales = {f["name"] for f in coleccion["fields"]}
    faltantes = [c for c in campos_nuevos if c["name"] not in nombres_actuales]
    if not faltantes:
        print(f"  {nombre_coleccion}: los campos nuevos ya existen, sin cambios.")
        return
    coleccion["fields"] = coleccion["fields"] + faltantes
    pb._session.patch(f"{pb.base_url}/api/collections/{coleccion['id']}", json=coleccion).raise_for_status()
    print(f"  {nombre_coleccion}: agregados {[c['name'] for c in faltantes]}.")


def main() -> None:
    pb = get_admin_client()
    print("Agregando grupo_reserva_id a viajes y pagos...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPO_GRUPO)
    _agregar_campos_si_faltan(pb, "pagos", _CAMPO_GRUPO)
    print("Listo.")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Ejecutar y verificar idempotencia**

Run: `python etl/18_agregar_grupo_reserva.py` (dos veces, igual que Task B1 Steps 2-3).

**Verificado 3 veces contra PocketBase real**: corrida 1 (18-ago-2026, implementador SDD) agregó el campo (`agregados ['grupo_reserva_id']` en ambas colecciones); corrida 2 (mismo día) confirmó no-op (`ya existen, sin cambios`); corrida 3 (19-ago-2026, esta sesión, a pedido explícito de Washington) repitió el mismo no-op y se confirmó por schema que el campo aparece exactamente 1 vez en cada colección (sin duplicados). Detalle en `docs/HOJA_DE_RUTA.md` sección 73.

- [x] **Step 3: Commit**

```bash
git add etl/18_agregar_grupo_reserva.py
git commit -m "feat: agregar campo grupo_reserva_id a viajes y pagos para soportar factura unica por grupo"
```

Commit real: `d57922f` (rama `worktree-plan-mejoras-v2-p0`, **no está en `main`**). Revisor independiente: sí, verdicto "review clean" registrado en `.superpowers/sdd/2026-08-17-plan-mejoras-v2-p0/progress.md` línea 84.

### Task C2: Endpoint de reserva múltiple `POST /ciclista/reservar-grupo`

**Files:**
- Modify: `app/routers/ciclista.py` (agregar `import uuid`, factorizar `reservar()`, agregar `reservar_grupo()`)

**Interfaces:**
- Produce: `POST /ciclista/reservar-grupo` -- crea N viajes reales con el mismo `grupo_reserva_id`, todo-o-nada (si cualquier validación falla para cualquier bicicleta del lote, no se crea ninguno).
- Produce: helper interno `_crear_viaje(pb, user, user_id, bicicleta_id, bicicleta_codigo, estacion_inicio_id, estacion_inicio_nombre, modalidad, lat, lng, codigo_valido, grupo_reserva_id="") -> dict` -- reutilizado por `reservar()` (single) y `reservar_grupo()` (loop).
- Consumes: `codigos_descuento_repo.obtener_valido()`/`marcar_usado()`, `_bicicletas_exclusivas_nuevas()`, `_infracciones_activas()`, `MAX_VIAJES_ACTIVOS`, `_viajes_activos()` -- todo ya existente en `ciclista.py`.

- [ ] **Step 1: Agregar `import uuid` al inicio del archivo**

En `app/routers/ciclista.py` línea 3, agregar antes de `import json`:
```python
import json
import uuid
```

- [ ] **Step 2: Factorizar la creación del viaje individual**

Extraer el bloque de creación (líneas 598-636 de `reservar()`, desde `try:` hasta el `return RedirectResponse` de éxito) en un helper reutilizable, colocado justo antes de la función `reservar()`:

```python
def _crear_viaje(
    pb, user: dict, user_id: str, bicicleta_id: str, bicicleta_codigo: str,
    estacion_inicio_id: str, estacion_inicio_nombre: str, modalidad: str,
    lat: float, lng: float, codigo_valido: dict | None, grupo_reserva_id: str = "",
) -> dict:
    """Crea UN viaje real + marca la bicicleta en_uso + registra auditoria --
    logica compartida entre reservar() (una bicicleta) y reservar_grupo()
    (varias a la vez, Tarea C2 del plan de factura unica). El codigo de
    descuento, si viene, solo se marca usado por el LLAMADOR (una sola vez
    por reserva, nunca una vez por bicicleta del grupo)."""
    nuevo_viaje = pb.create_record("viajes", {
        "ciclista_id":            user_id,
        "ciclista_nombre":        user.get("name") or user.get("email", ""),
        "bicicleta_id":           bicicleta_id,
        "bicicleta_codigo":       bicicleta_codigo,
        "estacion_inicio_id":     estacion_inicio_id,
        "estacion_inicio_nombre": estacion_inicio_nombre,
        "latitud_inicio":         lat,
        "longitud_inicio":        lng,
        "latitud_actual":         lat,
        "longitud_actual":        lng,
        "estado":                 "activo",
        "fecha_inicio":           _ahora(),
        "descuento_codigo":       codigo_valido["codigo"] if codigo_valido else "",
        "descuento_porcentaje":   codigo_valido["porcentaje"] if codigo_valido else 0,
        "modalidad_actual":       modalidad,
        "inicio_segmento_actual": _ahora(),
        "grupo_reserva_id":       grupo_reserva_id,
    })
    pb.update_record("bicicletas", bicicleta_id, {"estado": "en_uso"})
    return nuevo_viaje
```

- [ ] **Step 3: Reescribir `reservar()` para usar el helper**

Reemplazar el bloque `try:` original de `reservar()` (líneas 598-636) por:

```python
    try:
        pb = _pb()
        lat = float(latitud)
        lng = float(longitud)

        nuevo_viaje = _crear_viaje(
            pb, user, user_id, bicicleta_id, bicicleta_codigo,
            estacion_inicio_id, estacion_inicio_nombre, modalidad, lat, lng, codigo_valido,
        )
        if codigo_valido:
            codigos_descuento_repo.marcar_usado(codigo_valido["id"], nuevo_viaje["id"])

        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Viaje iniciado: {bicicleta_codigo} desde {estacion_inicio_nombre}", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )
        notificaciones_repo.notificar_usuario(
            pb, user_id, tipo="viaje_iniciado",
            titulo="Viaje iniciado",
            mensaje=f"Iniciaste un viaje con la bicicleta {bicicleta_codigo} desde {estacion_inicio_nombre}.",
            enlace=f"/ciclista/viaje-activo/{nuevo_viaje['id']}",
        )

        request.session["flash"] = {"type": "success", "msg": f"Viaje iniciado en {estacion_inicio_nombre}. Buen viaje."}
        return RedirectResponse(f"/ciclista/viaje-activo/{nuevo_viaje['id']}", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al iniciar viaje: {e}"}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
```

(Nota: este step incluye el gancho de notificación de la Task B2 -- si B2 ya se implementó antes que C2, no duplicar la llamada, solo confirmar que sigue presente tras la reescritura.)

- [ ] **Step 4: Agregar `reservar_grupo()` después de `reservar()`**

```python
@router.post("/reservar-grupo")
async def reservar_grupo(
    request: Request,
    bicicleta_ids:          list[str] = Form(...),
    bicicleta_codigos:      list[str] = Form(...),
    estaciones_ids:         list[str] = Form(...),
    estaciones_nombres:     list[str] = Form(...),
    latitudes:              list[str] = Form(...),
    longitudes:             list[str] = Form(...),
    modalidad:              str = Form("hora"),
    codigo_descuento:       str = Form(""),
):
    """Reserva de varias bicicletas en una sola accion (punto 0.3): crea N
    viajes reales, todos con el mismo grupo_reserva_id, todo-o-nada -- si
    cualquier validacion falla para cualquier bicicleta del lote, no se
    crea ninguno (mismo criterio que el codigo de descuento en reservar():
    "sin dejar un viaje a medias"). El codigo de descuento, si viene, se
    aplica y se marca usado en el PRIMER viaje del grupo unicamente (es de
    un solo uso, no tiene sentido duplicarlo N veces)."""
    user = getattr(request.state, "user", {})
    user_id = user.get("id", "")

    n = len(bicicleta_ids)
    if n < 2:
        request.session["flash"] = {"type": "error", "msg": "Selecciona al menos 2 bicicletas para una reserva grupal."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
    if not (len(bicicleta_codigos) == len(estaciones_ids) == len(estaciones_nombres) == len(latitudes) == len(longitudes) == n):
        request.session["flash"] = {"type": "error", "msg": "Datos de la reserva grupal incompletos."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    if modalidad not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    viajes_activos_actuales = _viajes_activos(user_id)
    if len(viajes_activos_actuales) + n > MAX_VIAJES_ACTIVOS:
        request.session["flash"] = {"type": "error", "msg":
            f"No puedes tener más de {MAX_VIAJES_ACTIVOS} bicicletas alquiladas a la vez "
            f"(ya tienes {len(viajes_activos_actuales)}, intentas agregar {n})."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    exclusivas_nuevas = _bicicletas_exclusivas_nuevas()
    tipo_membresia_actual = membresias_repo.tipo_membresia_real(user.get("email", ""))
    for codigo in bicicleta_codigos:
        if codigo in exclusivas_nuevas and tipo_membresia_actual != "member":
            fecha_liberacion = exclusivas_nuevas[codigo].strftime("%d/%m/%Y")
            request.session["flash"] = {"type": "error", "msg":
                f"{codigo} es una bicicleta nueva con acceso anticipado exclusivo para "
                f"suscriptores hasta el {fecha_liberacion}."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

    if _infracciones_activas(user_id) > 0:
        request.session["flash"] = {"type": "error", "msg":
            "Tienes infracciones pendientes de resolución. No puedes reservar hasta que sean resueltas."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)

    try:
        pb_check = _pb()
        pendientes = pb_check.list_records(
            "pagos",
            filter=f'ciclista_id = {filter_literal(user_id)} && (estado = "pendiente_efectivo" || estado = "verificacion_pendiente")',
            per_page=1,
        )
        if pendientes.get("totalItems", 0) > 0:
            request.session["flash"] = {"type": "error", "msg":
                "Tienes pagos pendientes. Regula tu situación antes de hacer una nueva reserva."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

        rechazados = pb_check.list_records(
            "pagos", filter=f'ciclista_id = {filter_literal(user_id)} && estado = "rechazado"', per_page=1,
        )
        if rechazados.get("totalItems", 0) > 2:
            request.session["flash"] = {"type": "error", "msg":
                "Tu cuenta ha sido bloqueada temporalmente por pagos rechazados. Contacta a soporte."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)
    except Exception:
        pass

    codigo_valido = None
    if codigo_descuento.strip():
        codigo_valido = codigos_descuento_repo.obtener_valido(codigo_descuento, user_id)
        if not codigo_valido:
            request.session["flash"] = {"type": "error", "msg":
                "El código de descuento no es válido, ya fue usado, o no te pertenece."}
            return RedirectResponse("/ciclista/alquilar", status_code=302)

    grupo_reserva_id = uuid.uuid4().hex
    try:
        pb = _pb()
        viajes_creados = []
        for i in range(n):
            viaje = _crear_viaje(
                pb, user, user_id, bicicleta_ids[i], bicicleta_codigos[i],
                estaciones_ids[i], estaciones_nombres[i], modalidad,
                float(latitudes[i]), float(longitudes[i]),
                codigo_valido if i == 0 else None,
                grupo_reserva_id=grupo_reserva_id,
            )
            viajes_creados.append(viaje)
            notificaciones_repo.notificar_usuario(
                pb, user_id, tipo="viaje_iniciado",
                titulo="Viaje iniciado",
                mensaje=f"Iniciaste un viaje con la bicicleta {bicicleta_codigos[i]} "
                        f"(reserva grupal de {n} bicicletas).",
                enlace=f"/ciclista/viaje-activo/{viaje['id']}",
            )

        if codigo_valido:
            codigos_descuento_repo.marcar_usado(codigo_valido["id"], viajes_creados[0]["id"])

        registrar_auditoria(
            user.get("pb_token", ""), user_id, user.get("name") or user.get("email", ""),
            user.get("email", ""), "crear", "viajes",
            f"Reserva grupal de {n} bicicletas iniciada: {', '.join(bicicleta_codigos)} "
            f"(grupo {grupo_reserva_id})", request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        request.session["flash"] = {"type": "success", "msg":
            f"Reserva grupal de {n} bicicletas iniciada. Al devolver y pagar todas, recibirás una sola factura."}
        return RedirectResponse(f"/ciclista/viaje-activo/{viajes_creados[0]['id']}", status_code=302)

    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"Error al iniciar la reserva grupal: {e}"}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
```

- [ ] **Step 5: Verificación E2E real**

Con una cuenta ciclista real y 2-3 bicicletas reales disponibles, hacer `POST /ciclista/reservar-grupo` con los arrays correspondientes (vía `curl`/`requests` con CSRF real, ya que la UI todavía no existe -- eso es la Task C3). Confirmar: N viajes creados con el mismo `grupo_reserva_id` no vacío, N bicicletas marcadas `en_uso`, N notificaciones `viaje_iniciado`, 1 sola entrada de auditoría. Probar también el caso de error (ej. una de las bicicletas con infracción activa del ciclista) y confirmar que NO se crea ningún viaje (todo-o-nada).

- [ ] **Step 6: Limpieza**

Finalizar y validar cada viaje del grupo de prueba; borrar pagos, viajes, notificaciones; restaurar las bicicletas a `disponible`.

- [ ] **Step 7: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: agregar POST /ciclista/reservar-grupo para reservar varias bicicletas a la vez"
```

**Nota posterior (19-ago-2026):** la 3ª ronda de revisión independiente de la
Task C5 encontró 3 huecos reales en `reservar_grupo()`/`_revertir_reserva_grupal()`
(notificaciones/correos no recuperables en un rollback a mitad de lote,
validación duplicada con `reservar()`, y el código de descuento que quedaba
quemado si el rollback ocurría justo después de `marcar_usado()` -- este último
ya señalado sin resolver en el fix round 1 de arriba). Los 3 se cerraron en una
ronda de fix dedicada, commit `940be8c`, revisor independiente con 0 hallazgos.
Ver `docs/HOJA_DE_RUTA.md` sección 77 para el detalle completo y la evidencia.

### Task C3: UI de selección múltiple en el catálogo

**Files:**
- Modify: `app/templates/componentes/tarjeta_bicicleta.html`
- Modify: `app/templates/ciclista/alquilar.html`

**Interfaces:**
- Consumes: `POST /ciclista/reservar-grupo` (Task C2).

- [ ] **Step 1: Agregar checkbox y data attributes a la tarjeta**

En `tarjeta_bicicleta.html`, agregar los data attributes que necesita el carrito al `<div class="tarjeta-bicicleta" ...>` (línea 58) y un checkbox visible solo si la bicicleta está disponible y no bloqueada:

```html
<div class="tarjeta-bicicleta" data-marca="{{ bici.marca }}" data-enfoque="{{ bici.enfoque }}"
     data-id="{{ bici.id }}" data-codigo="{{ bici.codigo }}"
     data-estacion-id="{{ bici.estacion_id or '' }}" data-estacion-nombre="{{ bici.estacion or '' }}"
     data-lat="{{ bici.lat or 0 }}" data-lng="{{ bici.lng or 0 }}">

  {% if bici.estado == "disponible" and not bici.bloqueada_exclusiva %}
  <label class="tarjeta-bicicleta-seleccion" style="position:absolute;top:10px;right:10px;z-index:2;background:var(--bg);border-radius:6px;padding:4px;display:flex;align-items:center;">
    <input type="checkbox" class="chk-seleccion-grupo" data-codigo="{{ bici.codigo }}" title="Seleccionar para reserva grupal">
  </label>
  {% endif %}

  <div class="tarjeta-bicicleta-foto">
```

**Nota para quien implemente:** confirmar los nombres reales de campo `estacion_id`/`estacion`/`lat`/`lng` (o equivalentes) que ya devuelve `_catalogo_bicicletas()` en `ciclista.py` -- si los nombres no coinciden exactamente, usar los reales en vez de inventar campos nuevos en el dict que ya arma esa función.

- [ ] **Step 2: Agregar la barra flotante de carrito en `alquilar.html`**

Después del `</div>` que cierra `#catalogo-grid` (línea ~38) y antes del siguiente `<div class="card"` (Estaciones disponibles, línea 41):

```html
<div id="barra-carrito" style="display:none;position:sticky;bottom:16px;z-index:5;margin:0 0 20px;padding:14px 20px;border-radius:var(--radius);background:var(--primary);color:#fff;display:flex;align-items:center;justify-content:space-between;gap:12px;">
  <span id="barra-carrito-texto">0 bicicletas seleccionadas</span>
  <div style="display:flex;gap:8px;">
    <button type="button" class="btn btn-ghost" id="btn-limpiar-carrito" style="color:#fff;border-color:#fff;">Limpiar</button>
    <button type="button" class="btn" style="background:#fff;color:var(--primary);" id="btn-reservar-carrito">Reservar seleccionadas</button>
  </div>
</div>

<form id="form-reservar-grupo" method="post" action="/ciclista/reservar-grupo" style="display:none;">
  <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
  <input type="hidden" name="modalidad" id="rg-modalidad">
  <div id="rg-campos"></div>
</form>
```

- [ ] **Step 3: Agregar la lógica JS del carrito**

Al final del bloque `{% block scripts %}` de `alquilar.html`, antes de `</script>` (línea ~208, justo antes del cierre del último `<script>`):

```javascript
const seleccionGrupo = new Set();
const barraCarrito = document.getElementById('barra-carrito');
const barraCarritoTexto = document.getElementById('barra-carrito-texto');

function actualizarBarraCarrito() {
  if (seleccionGrupo.size === 0) {
    barraCarrito.style.display = 'none';
    return;
  }
  barraCarrito.style.display = 'flex';
  barraCarritoTexto.textContent = `${seleccionGrupo.size} bicicleta${seleccionGrupo.size !== 1 ? 's' : ''} seleccionada${seleccionGrupo.size !== 1 ? 's' : ''}`;
}

document.querySelectorAll('.chk-seleccion-grupo').forEach(function (chk) {
  chk.addEventListener('change', function () {
    if (chk.checked) seleccionGrupo.add(chk.dataset.codigo);
    else seleccionGrupo.delete(chk.dataset.codigo);
    actualizarBarraCarrito();
  });
});

document.getElementById('btn-limpiar-carrito').addEventListener('click', function () {
  seleccionGrupo.clear();
  document.querySelectorAll('.chk-seleccion-grupo').forEach(function (chk) { chk.checked = false; });
  actualizarBarraCarrito();
});

document.getElementById('btn-reservar-carrito').addEventListener('click', function () {
  if (seleccionGrupo.size < 2) {
    alert('Selecciona al menos 2 bicicletas para una reserva grupal.');
    return;
  }
  const modalidadActiva = document.querySelector('#catalogo-modalidad .modalidad-btn.activo').dataset.modalidad;
  const campos = document.getElementById('rg-campos');
  campos.innerHTML = '';
  seleccionGrupo.forEach(function (codigo) {
    const tarjeta = document.querySelector(`.tarjeta-bicicleta[data-codigo="${codigo}"]`);
    if (!tarjeta) return;
    ['id', 'codigo', 'estacion-id', 'estacion-nombre', 'lat', 'lng'].forEach(function (campo) {
      const input = document.createElement('input');
      input.type = 'hidden';
      const nombreCampo = {
        'id': 'bicicleta_ids', 'codigo': 'bicicleta_codigos',
        'estacion-id': 'estaciones_ids', 'estacion-nombre': 'estaciones_nombres',
        'lat': 'latitudes', 'lng': 'longitudes',
      }[campo];
      input.name = nombreCampo;
      input.value = tarjeta.dataset[campo.replace('-', '')] || '';
      campos.appendChild(input);
    });
  });
  document.getElementById('rg-modalidad').value = modalidadActiva;
  document.getElementById('form-reservar-grupo').submit();
});
```

**Nota para quien implemente:** `tarjeta.dataset[campo.replace('-', '')]` asume que `estacion-id`/`estacion-nombre` se acceden como `dataset.estacionId`/`dataset.estacionNombre` (conversión automática kebab-case → camelCase de `dataset` en JS) -- ajustar el mapeo si al probarlo en el navegador real no coincide.

- [x] **Step 4: Verificación E2E real**

Con la app corriendo, iniciar sesión con una cuenta ciclista real, seleccionar 2+ bicicletas reales con los checkboxes, click en "Reservar seleccionadas", confirmar que redirige a `/ciclista/viaje-activo/{id}` de la primera bicicleta y que las N bicicletas quedan `en_uso` (mismo criterio de verificación que Task C2 Step 5, pero ahora disparado desde la UI real en vez de un request directo).

**Verificado 19-ago-2026, en dos partes** (ver `docs/HOJA_DE_RUTA.md` sección 74 para el detalle completo): (1) checkboxes, barra de carrito y resolución de datos por bicicleta verificados en un navegador real (Chrome vía automatización) contra el servidor real; (2) el submit final del formulario se disparó como un evento de clic real de DOM (`element.click()`) en vez de un clic de mouse sintetizado por el SO, porque el clic de mouse real dejó de entregarse de forma fiable a mitad de esta verificación (3 intentos fallidos con coordenadas y con `ref`, uno de ellos disparó un `alert()` real del navegador que congeló la pestaña -- se cerró la pestaña y se documentó, no se reintentó indefinidamente). El clic de DOM real confirmó que el handler de submit corre y llega al backend real: `POST /ciclista/reservar-grupo` real, 2 viajes creados (`UB-010`/`UB-008`) con el mismo `grupo_reserva_id`, ambas bicicletas `en_uso`, 2 notificaciones `viaje_iniciado` reales, redirect real a `/ciclista/viaje-activo/{id}` de la primera bicicleta. Se usó una cuenta ciclista de prueba desechable (no `ciclista@urbanbike.com`, que ya tenía 3 viajes activos/pendientes de sesiones anteriores y hubiera chocado con el tope `MAX_VIAJES_ACTIVOS=4`).

Durante esta verificación se encontraron y corrigieron 2 bugs reales de la implementación original (no parte del brief, hallazgos de la revisión + de la prueba en navegador real):
1. El checkbox de selección era invisible/inutilizable en la práctica: `.tarjeta-bicicleta` no tenía `position:relative` en `main.css`, así que el `position:absolute` del checkbox escapaba a un ancestro lejano en vez de anclarse a la tarjeta. Corregido agregando `position:relative` a `.tarjeta-bicicleta` (`app/static/css/main.css`), y reposicionado el checkbox de `top:10px` a `top:44px` para no chocar visualmente con el badge de estado ("Disponible"/etc) que ya ocupa esa esquina.
2. `#barra-carrito` tenía `display:none` y `display:flex` en el mismo atributo `style` -- la última declaración gana, así que la barra aparecía visible desde la carga de la página (con "0 bicicletas seleccionadas") en vez de solo cuando hay algo seleccionado. Corregido quitando el `display:flex` duplicado; el JS ya controla `style.display` directamente vía `actualizarBarraCarrito()`.

**Revisor independiente**: sí, `code-review` (nivel medium) sobre el diff antes de comitear -- encontró los 2 bugs de arriba. Ambos corregidos y reverificados contra el HTML real servido antes del commit.

- [x] **Step 5: Limpieza**

Igual que Task C2 Step 6. Limpieza confirmada: 2 viajes borrados, 2 bicicletas restauradas a `disponible`, 2 notificaciones `viaje_iniciado` borradas, además de la notificación `registro_nuevo` que generó el registro de la cuenta de prueba desechable (efecto colateral esperado del gancho de la Task B9) y el usuario de prueba borrado. 0 rastros confirmados en `viajes`, `notificaciones`, `users` y `auditoria` tras la limpieza.

- [x] **Step 6: Commit**

```bash
git add app/templates/componentes/tarjeta_bicicleta.html app/templates/ciclista/alquilar.html app/static/css/main.css
git commit -m "feat: agregar seleccion multiple (carrito) al catalogo para reservar varias bicicletas a la vez"
```

Commit real: `a992af6` (rama `worktree-plan-mejoras-v2-p0`, **no en `main`**).

Además, la revisión independiente encontró y se corrigió un tercer punto (no un bug de comportamiento, sino código muerto y engañoso): los 5 `data-*` nuevos en `.tarjeta-bicicleta` (`data-id`, `data-estacion-id`, `data-estacion-nombre`, `data-lat`, `data-lng`) que proponía el brief original nunca se llenan (`_catalogo_bicicletas()` no trae esos campos por unidad, confirmado leyendo la función) y el JS del carrito nunca los lee -- usa `BICICLETAS`/`ESTACIONES` (el mismo JSON que ya alimenta el mapa) en su lugar, con el mismo criterio de match por nombre normalizado que usa `bicicleta_detalle()` en el backend. Se eliminaron esos 5 atributos vacíos y el comentario del docstring que afirmaba, incorrectamente, que se "enriquecían" en `ciclista.alquilar()` -- quedó solo `data-codigo`, que sí se usa.

### Task C4: Factura de grupo -- `_construir_factura_grupo()` y vista HTML

**Files:**
- Modify: `app/routers/empleado.py` (denormalizar `grupo_reserva_id` al crear el pago en `vig_devolver()`)
- Modify: `app/routers/ciclista.py` (nueva función `_construir_factura_grupo()` y endpoint `GET /ciclista/comprobante-grupo/{grupo_reserva_id}`)

**Interfaces:**
- Consumes: `DatosFactura`, `LineaFactura` (`app/reportes/factura.py`), `_construir_factura_pago()` (reutilizar su lógica de líneas por viaje, no reescribirla).
- Produce: `_construir_factura_grupo(pagos: list[dict], viajes_por_id: dict, user: dict) -> DatosFactura`, `GET /ciclista/comprobante-grupo/{grupo_reserva_id}`.

- [x] **Step 1: Denormalizar `grupo_reserva_id` en `vig_devolver()`**

En `empleado.py`, dentro del `pb.create_record("pagos", {...})` (líneas 1663-1682), agregar el campo:

```python
            pb.create_record("pagos", {
                "viaje_id":          viaje_id,
                "ciclista_id":       viaje.get("ciclista_id", ""),
                "ciclista_nombre":   viaje.get("ciclista_nombre") or "—",
                "duracion_minutos":  duracion,
                "tipo_bicicleta":    tipo_bicicleta,
                "tipo_membresia":    tipo_membresia,
                "precio_hora":       precio_hora_display,
                "subtotal":          subtotal,
                "recargo_demora":    recargo_demora,
                "cargo_danos":       0,
                "descuento_codigo":  descuento_codigo,
                "descuento_monto":   descuento_monto,
                "monto_total":       monto_total,
                "estado":            "pendiente",
                "metodo_pago":       "",
                "fecha_pago":        "",
                "fecha_generado":    _ahora(),
                "comprobante_numero": "",
                "grupo_reserva_id":  viaje.get("grupo_reserva_id") or "",
            })
```

- [x] **Step 2: Agregar `_construir_factura_grupo()` en `ciclista.py`, después de `_construir_factura_pago()`**

**Desviación real respecto al código de abajo (aplicada, no solo propuesta):** el `iva` de la factura de grupo se acumula desde `factura_individual.iva` (ya calculado una vez por `_construir_factura_pago()` dentro del mismo loop) en vez de recalcularlo aparte con un segundo `facturas_repo.desglosar_iva(p.get("monto_total"))` -- mismo resultado matemático (mismo IVA_TASA sobre el mismo monto_total), una sola fuente de verdad, sin el cálculo redundante que traía el bloque de abajo.

```python
def _construir_factura_grupo(pagos: list[dict], viajes_por_id: dict, user: dict) -> DatosFactura:
    """Factura unica para un grupo de bicicletas reservadas a la vez (punto
    0.3): agrega las lineas de CADA pago del grupo (reusa la misma
    _construir_factura_pago() por pago para no duplicar el desglose de
    segmentos/recargo/danos/descuento, solo le antepone el codigo de la
    bicicleta a cada linea) y suma los totales. Solo se llama cuando YA
    se confirmo que todos los pagos del grupo estan 'pagado' (ver
    comprobante_grupo() mas abajo) -- no valida eso aca."""
    todas_las_lineas: list[LineaFactura] = []
    total_grupo = 0.0
    subtotal_grupo = 0.0
    descuento_grupo = 0.0
    bicicletas_desc = []

    for registro in pagos:
        viaje = viajes_por_id.get(registro.get("viaje_id", ""), {})
        factura_individual = _construir_factura_pago(registro, viaje, user)
        prefijo = f"{viaje.get('bicicleta_codigo', '—')} — "
        for linea in factura_individual.lineas:
            todas_las_lineas.append(LineaFactura(
                prefijo + linea.descripcion, linea.cantidad, linea.precio_unitario, linea.importe,
            ))
        total_grupo += factura_individual.total
        subtotal_grupo += factura_individual.subtotal
        descuento_grupo += factura_individual.descuento
        bicicletas_desc.append(viaje.get("bicicleta_codigo", "—"))

    primer_pago = pagos[0]
    fecha_pago = max(
        (p.get("fecha_pago") or p.get("fecha_generado") or "")[:19].replace("T", " ") for p in pagos
    )
    grupo_reserva_id = primer_pago.get("grupo_reserva_id", "")

    return DatosFactura(
        numero=f"GRUPO-{grupo_reserva_id[:8]}",
        fecha_emision=fecha_pago,
        fecha_vencimiento=fecha_pago,
        numero_pedido=grupo_reserva_id,
        cliente_nombre=primer_pago.get("ciclista_nombre") or user.get("name") or user.get("email", ""),
        cliente_cedula=user.get("cedula", ""),
        cliente_extra=f"Reserva grupal de {len(pagos)} bicicletas: {', '.join(bicicletas_desc)}",
        metodo_pago="Varios" if len({p.get("metodo_pago") for p in pagos}) > 1 else (primer_pago.get("metodo_pago") or "—").capitalize(),
        lineas=todas_las_lineas,
        subtotal=subtotal_grupo,
        iva=sum(facturas_repo.desglosar_iva(p.get("monto_total") or 0)[1] for p in pagos),
        descuento=descuento_grupo,
        total=total_grupo,
    )
```

- [x] **Step 3: Agregar el endpoint `GET /ciclista/comprobante-grupo/{grupo_reserva_id}`, después de `comprobante()`**

```python
@router.get("/comprobante-grupo/{grupo_reserva_id}", response_class=HTMLResponse)
async def comprobante_grupo(request: Request, grupo_reserva_id: str):
    user = getattr(request.state, "user", {})
    pb = _pb()
    try:
        viajes_grupo = pb.list_records(
            "viajes", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        viajes_grupo = []

    if not viajes_grupo or any(v.get("ciclista_id") != user.get("id", "") for v in viajes_grupo):
        request.session["flash"] = {"type": "error", "msg": "Reserva grupal no encontrada."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    viajes_por_id = {v["id"]: v for v in viajes_grupo}
    try:
        pagos_grupo = pb.list_records(
            "pagos", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        pagos_grupo = []

    if len(pagos_grupo) < len(viajes_grupo) or any(p.get("estado") != "pagado" for p in pagos_grupo):
        request.session["flash"] = {"type": "info", "msg":
            "La factura de esta reserva grupal todavía no está lista: faltan bicicletas del grupo "
            "por devolver o pagar."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    datos = _construir_factura_grupo(pagos_grupo, viajes_por_id, user)
    return templates.TemplateResponse(request, "ciclista/comprobante.html", _ctx(request,
        title="Factura de reserva grupal", pago={"id": grupo_reserva_id}, factura=datos, es_grupo=True,
    ))
```

**Nota para quien implemente:** confirmar el nombre exacto de la variable de contexto que usa `ciclista/comprobante.html` para renderizar `DatosFactura` (revisar ese template antes de este paso) -- el ejemplo de arriba asume `factura`, ajustar si el nombre real es otro. El flag `es_grupo=True` es para que el template pueda ocultar el enlace a `/pdf` individual si la Task C5 (PDF de grupo) todavía no está implementada cuando se ejecute esta tarea.

**Confirmado real:** el nombre de la variable sí es `factura` (verificado leyendo `componentes/factura.html`). Pero `es_grupo` **no estaba conectado a nada** en `comprobante.html` -- el template no lo leía en ningún lado, así que el enlace a `/ciclista/comprobante/{{ pago.id }}/pdf` seguía apareciendo siempre, incluso en la vista de grupo, apuntando a un `pago.id` que en realidad es el `grupo_reserva_id` (no un id de `pagos` real -- ese enlace hubiera dado 404). Corregido en `comprobante.html`: el enlace ahora está envuelto en `{% if not es_grupo %}`, y el título de la página (`{% block title %}`/`{% block page_title %}`, antes fijo en "Comprobante de Pago") ahora es condicional también, para que la vista de grupo muestre "Factura de reserva grupal" tal como el endpoint ya lo pasaba en `title=` (ese parámetro no hacía nada antes porque los blocks del template lo ignoraban por completo). También se agregó `soporte_email=settings.support_email` al contexto de `comprobante_grupo()` -- el brief no lo incluía, pero `componentes/factura.html` lo usa en el pie de página (mismo patrón que ya usa `comprobante()`); sin esto, el pie de la factura de grupo hubiera quedado con el contacto de soporte vacío.

- [x] **Step 4: Verificación E2E real**

Completar un ciclo real de reserva grupal (Task C3) de 2 bicicletas, devolver y validar AMBAS (con Vigilancia) y pagar AMBOS pagos (tarjeta de pruebas real). Confirmar que `GET /ciclista/comprobante-grupo/{grupo_reserva_id}` muestra una sola factura con las líneas de las 2 bicicletas y el total correcto (suma de ambos `monto_total`). Confirmar también que, si se visita esa URL ANTES de pagar la segunda bicicleta, redirige con el mensaje de "todavía no está lista".

**Verificado 19-ago-2026, ciclo real completo de punta a punta** (ver `docs/HOJA_DE_RUTA.md` sección 75 para el detalle): cuenta ciclista de prueba desechable → reserva grupal real de UB-010 + UB-008 (`POST /ciclista/reservar-grupo`) → ambos viajes finalizados (`POST /ciclista/finalizar`) → ambas devoluciones validadas con una cuenta Vigilancia real (`empleado.vig@urbanbike.com`, `POST /empleado/vigilancia/devolver/{id}`) → 2 pagos reales creados, ambos con `grupo_reserva_id` denormalizado correctamente → verificado que `GET /ciclista/comprobante-grupo/{id}` redirige a `/ciclista/historial` con solo 0 de 2 pagados → pagado el primer pago (tarjeta de pruebas real `4242 4242 4242 4242`) → verificado que la factura de grupo SIGUE redirigiendo (todavía no está lista) con 1 de 2 pagados → pagado el segundo pago → `GET /ciclista/comprobante-grupo/{id}` ahora sí devuelve `200` con la factura real: título "Factura de reserva grupal", ambas líneas (`UB-010 — Tarifa por día`, `UB-008 — Tarifa por día`), enlace de PDF individual correctamente oculto, subtotal $55.65 + IVA $8.35 = TOTAL $64.00 (verificado a mano contra los 2 `monto_total` reales: $35.20 + $28.80).

**Revisor independiente:** sí, `code-review` (nivel medium) sobre el diff completo antes de comitear -- encontró 1 hallazgo real (N+1 de ClickHouse, ver abajo), **diferido explícitamente**, no corregido en este commit.

- [x] **Step 5: Limpieza**

Borrar los pagos, viajes y notificaciones del grupo de prueba; restaurar ambas bicicletas a `disponible`. Limpieza confirmada: 2 pagos borrados, 2 viajes borrados, 2 bicicletas restauradas a `disponible`, 9 notificaciones reales borradas (registro_nuevo ×1, viaje_iniciado ×2, devolucion_pendiente_validar ×2, devolucion_validada ×2, pago_aprobado ×2 -- las 9 disparadas por los ganchos reales de B2/B5/B7/B9 a lo largo del ciclo completo), usuario de prueba borrado. 0 rastros confirmados en `viajes`, `pagos`, `notificaciones`, `users` y `auditoria` tras la limpieza.

- [x] **Step 6: Commit**

```bash
git add app/routers/empleado.py app/routers/ciclista.py
git commit -m "feat: emitir una sola factura para una reserva grupal cuando todas sus bicicletas estan pagadas"
```

Commit real: `865a176` (agrega también `app/templates/ciclista/comprobante.html`, no listado en el brief original -- necesario para los fixes de `es_grupo`/título de arriba), rama `worktree-plan-mejoras-v2-p0`, **no en `main`**.

**Hallazgo diferido de la revisión independiente (no corregido, documentado explícitamente):** `_construir_factura_grupo()` hace una consulta a ClickHouse por cada pago del grupo (vía `_construir_factura_pago()` → segmentos de `urbanbike_operativa.alquileres`), en vez de una sola consulta con `IN (...)` para todo el grupo -- patrón N+1. Acotado en la práctica: el tope real es `MAX_VIAJES_ACTIVOS=4` en `ciclista.py`, así que el peor caso es 4 consultas secuenciales a ClickHouse en una vista que no es de uso frecuente (se visita una vez por grupo, después de pagar todo). Se decidió NO corregirlo ahora porque arreglarlo bien requeriría tocar `_construir_factura_pago()` -- la función que ya reutiliza `comprobante()` (pago individual) y que el propio plan pide explícitamente "reutilizar su lógica de líneas por viaje, no reescribirla" (Task C4, Interfaces) -- con el riesgo real de introducir un bug en su lógica de reconciliación de segmentos (Important #1/#2 documentados en su propio docstring) a cambio de un ahorro de a lo sumo 3 consultas extra en una pantalla de bajo tráfico. Queda anotado para una futura sesión de optimización si el tamaño de grupo real llega a crecer más allá de 4.

### Task C5: PDF de la factura de grupo

**Files:**
- Modify: `app/routers/ciclista.py` (nuevo endpoint `GET /ciclista/comprobante-grupo/{grupo_reserva_id}/pdf`)

**Interfaces:**
- Consumes: `_construir_factura_grupo()` (Task C4), `generar_factura_pdf()` (`app/reportes/factura.py`, ya usado por `comprobante_pago_pdf()`).

- [x] **Step 1: Agregar el endpoint, después de `comprobante_grupo()`**

**Desviaciones reales aplicadas** (encontradas antes/durante la implementación, no solo propuestas): (1) `nombre_archivo` pasado al brief (`f"factura-grupo-{grupo_reserva_id[:8]}"`) no tenía extensión `.pdf`, inconsistente con los dos otros llamadores reales de `generar_factura_pdf()` (`comprobante_pago_pdf()`, `membresia_comprobante_pdf()`), que sí usan `.pdf` y el prefijo `urbanbike_`. Corregido a `f"urbanbike_factura_grupo_{grupo_reserva_id[:8]}.pdf"`. (2) La validación completa (fetch de viajes/pagos, ownership, "todos pagados") quedó duplicada verbatim entre `comprobante_grupo()` (Task C4) y este endpoint -- extraída a un helper compartido `_grupo_reserva_facturable()` (hallazgo de la revisión independiente, ver abajo).

```python
@router.get("/comprobante-grupo/{grupo_reserva_id}/pdf")
async def comprobante_grupo_pdf(request: Request, grupo_reserva_id: str):
    user = getattr(request.state, "user", {})
    pb = _pb()
    try:
        viajes_grupo = pb.list_records(
            "viajes", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
        ).get("items", [])
    except Exception:
        viajes_grupo = []

    if not viajes_grupo or any(v.get("ciclista_id") != user.get("id", "") for v in viajes_grupo):
        request.session["flash"] = {"type": "error", "msg": "Reserva grupal no encontrada."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    viajes_por_id = {v["id"]: v for v in viajes_grupo}
    pagos_grupo = pb.list_records(
        "pagos", filter=f'grupo_reserva_id = {filter_literal(grupo_reserva_id)}', per_page=50,
    ).get("items", [])

    if len(pagos_grupo) < len(viajes_grupo) or any(p.get("estado") != "pagado" for p in pagos_grupo):
        request.session["flash"] = {"type": "info", "msg":
            "La factura de esta reserva grupal todavía no está lista."}
        return RedirectResponse("/ciclista/historial", status_code=302)

    datos = _construir_factura_grupo(pagos_grupo, viajes_por_id, user)
    return generar_factura_pdf(datos, f"factura-grupo-{grupo_reserva_id[:8]}")
```

- [x] **Step 2: Verificación E2E real**

Con el mismo grupo de prueba pagado de la Task C4, descargar `GET /ciclista/comprobante-grupo/{grupo_reserva_id}/pdf` y confirmar que el PDF real se genera sin error, con las líneas de ambas bicicletas.

**Verificado 19-ago-2026 con 3 ciclos E2E reales completos** (ver `docs/HOJA_DE_RUTA.md` sección 76 para el detalle): (1) ciclo inicial -- reserva + devolución + 2 pagos reales + descarga directa del PDF (`GET .../pdf`), confirmado con `pdftotext` real: ambas líneas de bicicleta, TOTAL correcto, nombre de archivo con extensión `.pdf` (confirma el fix de la desviación de arriba); (2) segundo ciclo, después de que la revisión independiente encontró que el botón "Descargar PDF" de `comprobante.html` seguía oculto para `es_grupo` (dead code -- el endpoint nuevo no era alcanzable desde la UI) -- corregido el template, reverificado siguiendo el `href` real del botón hasta la descarga real; (3) tercer ciclo, después de extraer `_grupo_reserva_facturable()`, probando explícitamente el caso que no se había probado antes: acceso al PDF con 0 de 2 y con 1 de 2 pagos pagados -- ambas veces redirige correctamente con el mensaje de "todavía no está lista", igual que ya se confirmó para la vista HTML en la Task C4.

**Revisor independiente:** sí, `code-review` (nivel medium), 3 rondas sobre el diff acumulado -- ronda 1 encontró el botón "Descargar PDF" desconectado (corregido), ronda 2 encontró la duplicación de validación entre `comprobante_grupo()`/`comprobante_grupo_pdf()` (corregido con `_grupo_reserva_facturable()`), ronda 3 no encontró nada nuevo dentro del diff real de esta tarea -- amplió el alcance por su cuenta hacia `reservar_grupo()` (Task C2, ya comiteada), ver nota aparte en `docs/HOJA_DE_RUTA.md` sección 76.

- [x] **Step 3: Limpieza**

Si se reutiliza el mismo grupo de prueba de C4 dentro de la misma sesión de verificación, la limpieza ya se hizo en C4 Step 5 -- no crear datos nuevos para esta tarea si no es necesario. (En la práctica se crearon 3 grupos de prueba nuevos y desechables, uno por cada ciclo E2E de arriba -- limpieza completa confirmada las 3 veces: pagos, viajes, notificaciones -- 11 por ciclo, ver criterio de la sección 75 -- bicicletas y usuario de prueba, 0 rastros cada vez.)

- [x] **Step 4: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: agregar descarga PDF de la factura de reserva grupal"
```

Commit real: `ec73bde` (incluye también `app/templates/ciclista/comprobante.html`, no listado en el brief original -- necesario para el fix del botón desconectado), rama `worktree-plan-mejoras-v2-p0`, **no en `main`**.

### Task C6: Enlazar la factura de grupo desde `pagos.html` e `historial.html`

**Files:**
- Modify: `app/templates/ciclista/pagos.html` (línea ~97)

**Interfaces:**
- Consumes: campo `grupo_reserva_id` en cada `p` (pago) del contexto ya pasado a la plantilla (disponible tras Task C1 + C4 Step 1).

- [ ] **Step 1: Leer el contexto real de `pagos.html`**

Confirmar en `app/routers/ciclista.py` (función que renderiza `pagos.html`) que la lista de pagos pasada a la plantilla ya trae el campo `grupo_reserva_id` tal cual viene de PocketBase (no debería requerir cambios de router, solo que el campo exista en el registro -- ya cubierto por Task C1/C4).

- [ ] **Step 2: Cambiar el enlace de comprobante para pagos agrupados**

En `pagos.html` línea ~97, reemplazar:
```html
<a href="/ciclista/comprobante/{{ p.id }}/pdf" style="color:var(--primary);font-weight:600;" title="Descargar comprobante en PDF">{{ p.comprobante_numero }}</a>
```
por:
```html
{% if p.grupo_reserva_id %}
  {% if p.estado == "pagado" %}
  <a href="/ciclista/comprobante-grupo/{{ p.grupo_reserva_id }}/pdf" style="color:var(--primary);font-weight:600;" title="Descargar factura de la reserva grupal (varias bicicletas)">{{ p.comprobante_numero }} <span class="badge badge-blue" style="font-size:0.7rem;">Grupal</span></a>
  {% else %}
  <span style="color:var(--text-muted);" title="La factura grupal se emite cuando todas las bicicletas del grupo estén pagadas">{{ p.comprobante_numero }} <span class="badge badge-yellow" style="font-size:0.7rem;">Grupal, pendiente</span></span>
  {% endif %}
{% else %}
<a href="/ciclista/comprobante/{{ p.id }}/pdf" style="color:var(--primary);font-weight:600;" title="Descargar comprobante en PDF">{{ p.comprobante_numero }}</a>
{% endif %}
```

- [ ] **Step 3: Verificación E2E real**

Con el grupo de prueba de la Task C4 (o uno nuevo), confirmar en `GET /ciclista/pagos` que: mientras solo una de las 2 bicicletas está pagada, esa fila muestra el badge "Grupal, pendiente" sin enlace de descarga; una vez pagadas ambas, ambas filas muestran el enlace a la factura grupal con badge "Grupal".

- [ ] **Step 4: Limpieza**

Igual que Task C4 Step 5, si se generaron datos nuevos.

- [ ] **Step 5: Commit**

```bash
git add app/templates/ciclista/pagos.html
git commit -m "feat: enlazar la factura grupal desde el historial de pagos cuando un pago pertenece a un grupo"
```

### Task C7: Indicar en `viaje_activo.html` que el viaje es parte de una reserva grupal

**Files:**
- Modify: `app/templates/ciclista/viaje_activo.html`

**Interfaces:** ninguna nueva -- solo lectura de `viaje.grupo_reserva_id` (ya disponible en el contexto `viaje` existente tras Task C1/C2).

- [ ] **Step 1: Agregar un aviso distinto al banner genérico de "otros viajes activos"**

En `viaje_activo.html`, después del bloque `{% if otros_viajes_activos %}` (líneas 11-18), agregar uno nuevo específico para el grupo:

```html
{% if viaje.grupo_reserva_id %}
<div class="flash info" style="margin-bottom:16px;">
  Esta bicicleta es parte de una reserva grupal. Cuando devuelvas y pagues todas las bicicletas del grupo, recibirás
  <strong>una sola factura</strong> con el detalle de todas, disponible en
  <a href="/ciclista/pagos">Historial de Pagos</a>.
</div>
{% endif %}
```

- [ ] **Step 2: Verificación E2E real**

Con un viaje real que tenga `grupo_reserva_id` (de una reserva grupal de prueba), confirmar que `GET /ciclista/viaje-activo/{id}` muestra el aviso nuevo. Confirmar que un viaje individual (sin `grupo_reserva_id`) NO lo muestra.

- [ ] **Step 3: Limpieza**

Igual que tareas anteriores del Grupo C.

- [ ] **Step 4: Commit**

```bash
git add app/templates/ciclista/viaje_activo.html
git commit -m "feat: avisar en viaje activo que la bicicleta es parte de una reserva grupal"
```

---

## Self-Review (completado durante la escritura de este plan)

- **Cobertura del spec:** Task A1 cierra 0.1 -- alcance revisado tras evidencia de ejecución real (subtotal calculado con la fórmula real de `vig_devolver()` contra un viaje real, dos mediciones con 2 min reales de diferencia: $144.82 → $144.98): no era una corrección de copy, era restaurar una decisión de negocio (congelar en `fecha_fin`) que la Tarea 7/9 de "modalidad-tarifa-real" había revertido sin reconfirmar, reconfirmada de nuevo con Washington el 17-ago-2026. Tasks B1-B9 cierran los 8 ganchos reales de 0.4 identificados en la auditoría (los otros 5 quedan explícitamente fuera de alcance, documentados en el encabezado del Grupo B). Tasks C1-C7 cierran 0.3 con el diseño acordado (selección múltiple real + factura única al completar el grupo).
- **Tipos consistentes:** `grupo_reserva_id` se usa con el mismo nombre en `viajes`, `pagos`, el helper `_crear_viaje()`, `reservar_grupo()`, `_construir_factura_grupo()`, y los templates -- verificado en la escritura de cada task.
- **Sin placeholders:** cada task tiene código real basado en el código actual leído en esta sesión (archivo:línea citados), no pseudocódigo. Las dos "notas para quien implemente" (Task C3 Step 1, Task C4 Step 3) señalan explícitamente un dato que debe confirmarse contra el código real al momento de implementar (nombres exactos de campos de estación en `_catalogo_bicicletas()`, y el nombre de la variable de contexto en `comprobante.html`) -- no son placeholders de lógica, son puntos de verificación honestos donde esta sesión no leyó el archivo completo.
