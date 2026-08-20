# Descuento de volumen/frecuencia (punto 0.2) + Simulación académica discreta -- Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir las 2 decisiones de negocio de Prioridad 0 que quedaron resueltas pero sin implementar tras el cierre del plan anterior: el código de descuento por volumen/frecuencia (punto 0.2) y la versión discreta de "Simulación académica" (ícono + tooltip en vez del texto grande y repetido).

**Architecture:** Reutiliza al 100% la infraestructura ya construida y probada de `codigos_descuento_repo.py` (generar/obtener_valido/marcar_usado/revertir_uso) -- ningún campo ni colección nuevos. Task 1 redefine la ventana de medición del descuento por buena conducta que YA EXISTE (de "todo el historial" a "últimos 30 días"), en vez de crear un mecanismo paralelo -- ver la decisión explícita de Washington más abajo. Task 2 agrega un segundo disparador (volumen) al mismo repo, en `reservar_grupo()`. Task 3 es puramente de UI (templates), sin tocar routers de negocio salvo un `subtitulo` de PDF que se deja intacto a propósito (ver Task 3).

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, PocketBase (colección `codigos_descuento` ya existente).

**Spec:** `docs/Plan_Mejoras_UrbanBike_V2.md` (secciones 0.2 y el punto de decisión de "Simulación académica" al inicio del documento) + este plan.

## Contexto real, auditado antes de escribir este plan (19/20-ago-2026)

**Hallazgo real que cambia el alcance de 0.2**: ya existe un mecanismo de descuento por "buena conducta" en producción, construido y probado el 16-ago-2026 (ver `docs/HOJA_DE_RUTA.md` sección 70), que **no estaba a la vista** cuando Washington resolvió el punto 0.2 el 18-ago-2026:

- `app/routers/ciclista.py:finalizar()` (líneas 1076-1090): al reportar la devolución, si el ciclista tiene **0 infracciones activas**, genera un código vía `codigos_descuento_repo.generar()` -- **10% si tiene menos de `_UMBRAL_RECURRENTE` (5) viajes `estado="completado"` en TODO su historial, 20% si tiene 5 o más.**
- La decisión de 0.2 (18-ago) pedía: "cliente frecuente = 5+ viajes en los últimos 30 días -> 10%", sin mencionar la condición de infracciones ni el escalón de 20%.

**Decisión de Washington (20-ago-2026, tras mostrarle este hallazgo): "Redefinir el existente"** -- el mecanismo de buena-conducta pasa a medir viajes completados en los **últimos 30 días** en vez de todo el historial, **mantiene el escalón 10%/20%** (no colapsa a un 10% fijo) y **mantiene la condición de 0 infracciones activas**. Regla final, explícita, para que no haya ambigüedad al implementar:

> Al reportar una devolución sin infracciones activas: si el ciclista tiene **menos de 5** viajes `estado="completado"` con `fecha_fin` en los **últimos 30 días**, genera un código del **10%**. Si tiene **5 o más**, genera un código del **20%**. (Antes: el conteo era sobre todo el historial, sin ventana de tiempo.)

Esto **cierra por completo** la parte "cliente frecuente" de 0.2 -- no se crea un código ni un disparador nuevo para eso, se corrige el umbral del que ya existe (Task 1).

**Hallazgo real, sin conflicto**: la parte "volumen" de 0.2 (15% para 3+ bicicletas simultáneas) **no tiene ningún mecanismo previo** -- `reservar_grupo()` (`ciclista.py:738`) usa `n = len(bicicleta_ids)` solo para validaciones, nunca para calcular un descuento. Es trabajo neto nuevo (Task 2). Diseño elegido (mismo patrón que el código de buena-conducta: se **genera** un código para uso en una reserva **futura**, no se aplica automáticamente a la reserva de 3+ que lo disparó -- consistente con el texto de la spec, "código de descuento real, aplicable por el ciclista mismo en el flujo de reserva", y con el precedente ya construido): al confirmarse una reserva grupal con **3 o más** bicicletas, generar un código del **15%** para ese ciclista. **No** se exige 0 infracciones activas para este disparador (es un premio al volumen de la reserva, no a la conducta) -- si Washington prefiere lo contrario, es un cambio de una línea en el fix, se avisa en la review.

**Hallazgo real, sin conflicto**: "Simulación académica" sigue con el texto grande y repetido tal como lo describe el punto de decisión del documento madre -- confirmado en 3 templates + 1 backend string (ver Task 3 para el detalle exacto, incluida una duplicación real encontrada: `membresia_comprobante.html` muestra el aviso DOS veces en la misma pantalla, una vez como banner y otra vez dentro de la factura incluida).

## Global Constraints

- No hay suite de pytest en este proyecto -- verificación real contra PocketBase/ClickHouse corriendo, no mocks, siguiendo el mismo criterio de todo el proyecto (ver `docs/HOJA_DE_RUTA.md`).
- **Nunca matar/reiniciar un proceso por iniciativa propia sin autorización explícita de Washington** -- si el auto-reload de `uvicorn --reload` no respawnea el worker (bug conocido, ver `scripts/dev_reload.py` y `docs/HOJA_DE_RUTA.md` sección 72), reportar con evidencia y esperar autorización, o usar `python scripts/dev_reload.py <puerto>` desde el arranque para evitarlo.
- Todo dato de prueba (usuarios, viajes, pagos, códigos de descuento, notificaciones) se crea contra las instancias reales y se borra al terminar, confirmado por re-lectura, no asumido.
- Cada tarea completa con evidencia E2E real (qué se probó, contra qué servicio, qué se confirmó, cómo se limpió) y revisor independiente antes de marcarse completa.
- Nombres de tablas/columnas en español (excepto lo que ya viene del CSV de Citibike, no aplica aquí). Type hints en código Python nuevo.
- Este worktree parte de `main` en el commit `83c784a` (post-fusión del Plan V2 P0) -- confirmar al crear el worktree.

---

### Task 1: Redefinir el descuento de buena conducta a ventana de 30 días

**Files:**
- Modify: `app/routers/ciclista.py:376-388` (constante `_UMBRAL_RECURRENTE` y función `_viajes_completados`)
- Modify: `app/routers/ciclista.py:1076-1090` (comentario y llamada dentro de `finalizar()`)

**Interfaces:**
- Consumes: `codigos_descuento_repo.generar(ciclista_id, porcentaje, viaje_id_origen)` (ya existe, sin cambios -- ver `app/db/codigos_descuento_repo.py`).
- Produces: función renombrada `_viajes_completados_ultimos_30_dias(user_id: str) -> int`, usada únicamente dentro de `finalizar()`. Ningún otro archivo la consume (confirmado por grep antes de este plan).

- [ ] **Step 1: Confirmar que no hay otros consumidores de `_viajes_completados`**

Run: `grep -rn "_viajes_completados\b" app/`
Expected: solo 2 resultados, ambos en `ciclista.py` (la definición en línea 379 y el uso en línea 1085). Si aparece un tercero, DETENER y avisar al controlador antes de continuar -- el alcance de este plan asume que es privada a `finalizar()`.

- [ ] **Step 2: Renombrar y reescribir la función con la ventana de 30 días**

Reemplazar el bloque actual (líneas 376-388):

```python
_UMBRAL_RECURRENTE = 5  # viajes completados para el 20% en vez de 10%, ver finalizar()


def _viajes_completados(user_id: str) -> int:
    try:
        res = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = {filter_literal(user_id)} && estado = "completado"',
            per_page=1,
        )
        return res.get("totalItems", 0)
    except Exception:
        return 0
```

por:

```python
_UMBRAL_RECURRENTE = 5  # viajes completados en los ultimos 30 dias para el 20% en vez de 10%, ver finalizar()
_VENTANA_CLIENTE_FRECUENTE_DIAS = 30  # punto 0.2, redefinicion del 20-ago-2026 -- antes era "todo el historial"


def _viajes_completados_ultimos_30_dias(user_id: str) -> int:
    """Cuenta viajes 'completado' cuyo fecha_fin cae dentro de los
    ultimos _VENTANA_CLIENTE_FRECUENTE_DIAS dias. Redefinicion del punto
    0.2 (20-ago-2026): antes contaba TODO el historial sin ventana de
    tiempo -- ver docs/HOJA_DE_RUTA.md, decision explicita de Washington
    tras encontrar que este mecanismo ya cubria (con otro criterio) lo
    que 0.2 pedia como "cliente frecuente"."""
    try:
        hace_30_dias = (datetime.now(timezone.utc) - timedelta(days=_VENTANA_CLIENTE_FRECUENTE_DIAS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = _pb().list_records(
            "viajes",
            filter=f'ciclista_id = {filter_literal(user_id)} && estado = "completado" && '
                    f'fecha_fin >= {filter_literal(hace_30_dias)}',
            per_page=1,
        )
        return res.get("totalItems", 0)
    except Exception:
        return 0
```

- [ ] **Step 3: Actualizar el único punto de llamada y su comentario**

En `finalizar()`, reemplazar (dentro del bloque que ya existe, líneas ~1076-1090):

```python
        # Código de descuento por buena conducta (punto 13): se genera acá,
        # al reportar la devolución, si el ciclista no tiene infracciones
        # activas EN ESTE MOMENTO (no depende del resultado de la
        # inspección de Vigilancia de ESTE viaje, que todavía no pasó --
        # es un premio a su historial limpio hasta ahora, no a este viaje
        # en particular). 20% si ya completó _UMBRAL_RECURRENTE viajes o
        # más, si no 10%.
        mensaje_extra = ""
        if _infracciones_activas(user.get("id", "")) == 0:
            porcentaje = 20 if _viajes_completados(user.get("id", "")) >= _UMBRAL_RECURRENTE else 10
```

por:

```python
        # Código de descuento por buena conducta + cliente frecuente
        # (puntos 13 y 0.2, unificados el 20-ago-2026): se genera acá, al
        # reportar la devolución, si el ciclista no tiene infracciones
        # activas EN ESTE MOMENTO (no depende del resultado de la
        # inspección de Vigilancia de ESTE viaje, que todavía no pasó --
        # es un premio a su historial limpio hasta ahora, no a este viaje
        # en particular). 20% si completó _UMBRAL_RECURRENTE viajes o más
        # en los ULTIMOS 30 DIAS (antes era todo el historial, sin
        # ventana -- ver docs/HOJA_DE_RUTA.md), si no 10%.
        mensaje_extra = ""
        if _infracciones_activas(user.get("id", "")) == 0:
            porcentaje = 20 if _viajes_completados_ultimos_30_dias(user.get("id", "")) >= _UMBRAL_RECURRENTE else 10
```

- [ ] **Step 4: Verificación E2E real -- caso 10% (menos de 5 viajes en 30 días)**

Contra el servidor real (nunca tocar un proceso preexistente -- arrancar uno propio con `python scripts/dev_reload.py <puerto libre>` si hace falta), con una cuenta de prueba nueva o una cuenta real con menos de 5 viajes completados en los últimos 30 días:
1. Reservar y finalizar (`POST /ciclista/reservar` -> `POST /ciclista/finalizar`) con 0 infracciones activas confirmadas (`GET` admin a `infracciones` filtrando por el usuario, `resuelta=false`, debe dar 0).
2. Confirmar por admin client que se creó un registro real en `codigos_descuento` con `porcentaje=10`.
3. Confirmar el flash message real muestra "Ganaste un código de descuento del 10%: ...".

- [ ] **Step 5: Verificación E2E real -- caso 20% (5+ viajes en 30 días, ninguno más viejo)**

Con la misma cuenta u otra de prueba: crear y completar (vía flujo real, no solo PocketBase directo salvo para ajustar `fecha_fin` hacia atrás dentro de la ventana de 30 días, mismo criterio ya usado en sesiones anteriores para simular paso de tiempo -- ver `docs/HOJA_DE_RUTA.md` sección 65/70) 5 viajes `completado` con `fecha_fin` real dentro de los últimos 30 días. Finalizar un 6to viaje real y confirmar que el código generado tiene `porcentaje=20`.

- [ ] **Step 6: Verificación E2E real -- caso borde, viaje viejo NO cuenta**

Con una cuenta que tenga un viaje `completado` real con `fecha_fin` de hace más de 30 días (ajustado vía PocketBase directo, documentado igual que el paso anterior) y menos de 5 dentro de la ventana: confirmar que el código generado es `10%`, no `20%` -- prueba directa de que la ventana de 30 días realmente excluye lo viejo (no solo que el número total coincide por casualidad).

- [ ] **Step 7: Limpieza confirmada**

Borrar todos los viajes, códigos de descuento y notificaciones de prueba creados en los Steps 4-6 vía admin client; confirmar por re-lectura (0 restantes) antes de marcar la tarea lista para revisión. Restaurar cualquier bicicleta usada a `disponible`.

- [ ] **Step 8: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "fix: redefinir el descuento de buena conducta/cliente frecuente a ventana de 30 dias (punto 0.2)"
```

---

### Task 2: Descuento de volumen (15% para 3+ bicicletas en una reserva grupal)

**Files:**
- Modify: `app/routers/ciclista.py:reservar_grupo()` (líneas ~738-845)

**Interfaces:**
- Consumes: `codigos_descuento_repo.generar(ciclista_id, porcentaje, viaje_id_origen)` (ya existe, sin cambios). `n = len(bicicleta_ids)`, ya calculado en la función (línea 759).
- Produces: nada que otras tareas de este plan consuman -- es la última pieza de 0.2.

- [ ] **Step 1: Insertar la generación del código de volumen tras confirmar el grupo completo**

En `reservar_grupo()`, insertar el bloque nuevo **después** del `for viaje in viajes_creados: notificaciones_repo.notificar_usuario(...)` (ya existe, línea ~834-841) y **antes** de armar el `flash` de éxito (línea ~843), para no generar el código si el todo-o-nada del bloque `try` termina fallando más abajo (aunque en la práctica no hay más pasos después de las notificaciones, mantener el orden es lo que ya hace este mismo bloque para las notificaciones, por la razón documentada en el comentario que ya existe ahí: "con el grupo entero ya confirmado"):

```python
        # Descuento de volumen (punto 0.2, 20-ago-2026): un codigo nuevo,
        # de un solo uso, para una reserva FUTURA -- igual que el codigo
        # de buena conducta, no se autoaplica a esta misma reserva (ya
        # esta confirmada y notificada arriba). No exige 0 infracciones
        # activas (es un premio al volumen de esta reserva, no a la
        # conducta general -- distinto del codigo de finalizar()).
        mensaje_volumen = ""
        if n >= 3:
            try:
                codigo_volumen = codigos_descuento_repo.generar(user_id, 15, viajes_creados[0]["id"])
                mensaje_volumen = f" Por reservar {n} bicicletas a la vez, ganaste un código de descuento del 15%: {codigo_volumen['codigo']}."
            except Exception:
                pass

        request.session["flash"] = {"type": "success", "msg":
            f"Reserva grupal de {n} bicicletas iniciada. Al devolver y pagar todas, recibirás una sola factura." + mensaje_volumen}
```

(Esto reemplaza únicamente la línea del `request.session["flash"] = {...}` de éxito que ya existe -- el resto de la función, incluido el `return RedirectResponse(...)` que sigue, no cambia.)

- [ ] **Step 2: Verificación E2E real -- 3 bicicletas, código generado**

Contra el servidor real, cuenta de prueba real: `POST /ciclista/reservar-grupo` con 3 `bicicleta_ids` reales y disponibles (no exclusivas de membresía si la cuenta es casual -- ver el hallazgo real de la Task C6 sobre `DIAS_EXCLUSIVA_NUEVA` antes de elegir bicicletas). Confirmar:
1. 3 viajes reales creados con el mismo `grupo_reserva_id`.
2. Un registro real nuevo en `codigos_descuento` con `porcentaje=15`, `usado=False`, `viaje_id_origen` = el id del primer viaje del grupo.
3. El flash real (leer el HTML de la siguiente página, no solo el código de estado) contiene el texto "ganaste un código de descuento del 15%".

- [ ] **Step 3: Verificación E2E real -- 2 bicicletas, SIN código**

Mismo flujo con exactamente 2 bicicletas (el mínimo que acepta `reservar_grupo()`, ver la validación `if n < 2` que ya existe). Confirmar que **no** se crea ningún registro nuevo en `codigos_descuento` para ese ciclista en esta corrida.

- [ ] **Step 4: Verificación E2E real -- el código de volumen se puede canjear en una reserva posterior**

Usando el código generado en el Step 2, hacer una reserva individual nueva (`POST /ciclista/reservar`) pasando ese código en `codigo_descuento`. Confirmar que `obtener_valido()` lo encuentra, que el pago resultante refleja el 15% de descuento, y que tras usarlo `obtener_valido()` ya no lo encuentra (queda `usado=True`) -- prueba de que reutiliza el flujo de canje ya existente sin ningún cambio ahí.

- [ ] **Step 5: Limpieza confirmada**

Borrar viajes, pagos, códigos de descuento y notificaciones de prueba; confirmar por re-lectura. Restaurar bicicletas a `disponible`.

- [ ] **Step 6: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: generar codigo de descuento del 15% al reservar 3+ bicicletas simultaneas (punto 0.2)"
```

---

### Task 3: "Simulación académica" -- versión discreta (ícono + tooltip)

**Files:**
- Modify: `app/templates/ciclista/membresia_pagar.html:8-11`
- Modify: `app/templates/ciclista/membresia_comprobante.html:24-27`
- Modify: `app/templates/ciclista/membresia.html:51-53,63-65`

**No modificar** (decisión explícita, documentar en el report por qué se dejó afuera): `app/routers/ciclista.py:2260` (`subtitulo` del PDF de factura de membresía, ya es una sola línea discreta dentro de un documento formal, no un banner de interfaz) ni `app/routers/ciclista.py:2407` (`nota` de la factura HTML de membresía, mismo criterio -- ya se renderiza como una sola línea pequeña dentro de `componentes/factura.html:80`, no repetida).

**Interfaces:** ninguna -- cambios de template puros, sin tocar routers ni el contrato de ningún endpoint.

- [ ] **Step 1: Reemplazar el banner de `membresia_pagar.html`**

Reemplazar (líneas 8-11):

```html
<div class="flash info" style="max-width:560px;margin:0 auto 20px;font-weight:700;font-size:0.95rem;padding:14px 16px;">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
  MODO DEMOSTRACIÓN — Ningún cargo real se procesa
</div>
```

por:

```html
<div style="max-width:560px;margin:0 auto 12px;display:flex;justify-content:flex-end;">
  <span title="Simulación académica: este sistema no tiene una pasarela de pago real conectada (Stripe, PayPal, etc.). Ningún cargo real se procesa." style="display:inline-flex;align-items:center;gap:5px;color:var(--text-muted);font-size:0.75rem;cursor:help;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
    Simulado
  </span>
</div>
```

- [ ] **Step 2: Reemplazar el banner de `membresia_comprobante.html`**

Reemplazar (líneas 24-27) -- nota: este archivo incluye `componentes/factura.html` justo debajo (línea 30), que YA repite un aviso equivalente en su `factura.nota` (`ciclista.py:2407`); ese segundo aviso se deja intacto (es parte del documento formal), así que este cambio además elimina la duplicación literal del mismo mensaje dos veces en la misma pantalla:

```html
<div class="flash info" style="max-width:680px;margin:0 auto 16px;font-size:0.85rem;">
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
  MODO DEMOSTRACIÓN — este comprobante es simulado, ningún cargo real se procesó.
</div>
```

por:

```html
<div style="max-width:680px;margin:0 auto 10px;display:flex;justify-content:flex-end;">
  <span title="Simulación académica: este comprobante es simulado, ningún cargo real se procesó." style="display:inline-flex;align-items:center;gap:5px;color:var(--text-muted);font-size:0.75rem;cursor:help;">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
    Simulado
  </span>
</div>
```

- [ ] **Step 3: Reemplazar las 2 menciones condicionales de `membresia.html`**

Reemplazar (líneas 51-53):

```html
  <div style="font-size:0.8125rem;color:var(--text-muted);margin-top:10px;text-align:center;">
    Sistema de pago simulado con fines académicos — ningún cargo real se procesa.
  </div>
```

por:

```html
  <div style="margin-top:10px;text-align:center;">
    <span title="Sistema de pago simulado con fines académicos — ningún cargo real se procesa." style="display:inline-flex;align-items:center;gap:5px;color:var(--text-muted);font-size:0.75rem;cursor:help;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      Simulado
    </span>
  </div>
```

Y reemplazar (líneas 63-65):

```html
  <div style="font-size:0.8125rem;color:var(--text-muted);margin-top:10px;text-align:center;">
    Reembolso simulado solo si cancelas dentro de las 48 horas desde el cobro.
  </div>
```

por:

```html
  <div style="margin-top:10px;text-align:center;">
    <span title="Reembolso simulado solo si cancelas dentro de las 48 horas desde el cobro (simulación académica, ningún cargo real se procesa)." style="display:inline-flex;align-items:center;gap:5px;color:var(--text-muted);font-size:0.75rem;cursor:help;">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
      Simulado
    </span>
  </div>
```

- [ ] **Step 4: Verificación E2E real -- las 3 pantallas, autenticado, HTML real**

Contra el servidor real, sesión real de un ciclista: `GET /ciclista/membresia` (ambos estados -- sin membresía activa y con membresía activa, esta última puede requerir activar una de prueba primero), `GET /ciclista/membresia/pagar`, y llegar a `GET /ciclista/membresia/comprobante/<id>` (activando una membresía de prueba real con tarjeta Luhn-válida). Para cada HTML real devuelto, confirmar por texto:
1. El texto largo viejo (`"MODO DEMOSTRACIÓN — Ningún cargo real se procesa"`, `"MODO DEMOSTRACIÓN — este comprobante es simulado"`, `"Sistema de pago simulado con fines académicos — ningún cargo real se procesa."` como bloque de texto visible fuera de un `title=`) **ya no aparece como texto visible** en el cuerpo renderizado.
2. La palabra `Simulado` aparece exactamente una vez por pantalla (no repetida).
3. El atributo `title="..."` con el texto completo está presente en el HTML (confirma que la explicación completa sigue disponible, solo que ahora vía tooltip).

- [ ] **Step 5: Limpieza confirmada**

Si se activó una membresía de prueba real para probar el comprobante: cancelarla o eliminarla vía admin client, confirmar por re-lectura que la cuenta de prueba queda sin membresía activa (o en el estado que tenía antes de la prueba).

- [ ] **Step 6: Commit**

```bash
git add app/templates/ciclista/membresia_pagar.html app/templates/ciclista/membresia_comprobante.html app/templates/ciclista/membresia.html
git commit -m "feat: version discreta de Simulacion academica -- icono + tooltip en vez de banner repetido"
```

---

## Self-Review (hecho antes de guardar este plan)

- **Cobertura de la spec**: 0.2 volumen -> Task 2. 0.2 cliente frecuente -> Task 1 (redefinición, no código nuevo, por la decisión explícita de Washington). Simulación académica discreta -> Task 3. Los 2 puntos de "PRIMERO" quedan cubiertos.
- **Placeholders**: ninguno -- cada step tiene el código real a insertar/reemplazar, con líneas exactas.
- **Consistencia de tipos/nombres**: `_viajes_completados` -> `_viajes_completados_ultimos_30_dias` (Task 1) no se usa en ningún otro lugar (confirmado por grep en el Step 1 de la Task 1). `codigos_descuento_repo.generar()` se usa con la misma firma en Task 1 (ya existente) y Task 2 (nueva, mismo repo). Task 3 no interactúa con Tasks 1-2.
- **Orden**: Task 1 y Task 2 son independientes entre sí (tocan la misma función `ciclista.py` pero regiones no solapadas -- `_viajes_completados`/`finalizar()` vs. `reservar_grupo()`); Task 3 es independiente de ambas (solo templates). Pueden ejecutarse en cualquier orden o en paralelo si se despachan a implementadores distintos, pero **no simultáneamente sobre el mismo archivo** (`ciclista.py`) sin coordinar el orden de los commits -- ejecutar Task 1 antes que Task 2 evita cualquier necesidad de fusionar diffs a mano.
