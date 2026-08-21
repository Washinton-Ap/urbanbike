# Avisos contextuales: fin de viaje y cambio de modalidad — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar dos ventanas de advertencia contextual reales (modales `<dialog>`, no texto pasivo) en `ciclista/viaje_activo.html`: una al reportar la devolución de la bicicleta (advertencia explícita de las 5h de gracia antes del recargo por demora) y otra al cambiar de modalidad de tarifa a mitad de viaje (advertencia explícita de que el precio cambia y se pagará un monto distinto).

**Architecture:** Ambos avisos son modales `<dialog>` nativos que interceptan el `submit` de un formulario ya existente (`/ciclista/finalizar` y `/ciclista/cambiar-modalidad`, ambos sin cambios en su lógica de negocio real) vía JS: se previene el envío, se muestra el modal con el texto/monto real, y solo al confirmar se reenvía el mismo formulario. El modal de cambio de modalidad necesita datos nuevos del backend (precio real de las 3 modalidades para la bicicleta/membresía del viaje) — se agregan al contexto ya existente de `GET /ciclista/viaje-activo/{id}`, sin tocar `POST /ciclista/cambiar-modalidad` ni `POST /ciclista/finalizar`.

**Tech Stack:** FastAPI, Jinja2, PocketBase (`PocketBaseClient`), ClickHouse (`app.db.tarifas_repo`). Sin test runner instalado (no hay pytest en `app/requirements.txt`) — cada tarea se verifica manualmente contra `python scripts/dev_reload.py 8013` real, con `curl`/PocketBase admin API, mismo criterio que el resto del proyecto (ver `docs/superpowers/plans/2026-08-16-modalidad-tarifa-real.md`, Tasks 3-9).

**Spec:** `docs/Plan_Mejoras_UrbanBike_V2.md` (PRIORIDAD 1, punto 1.7 — "Ventanas de advertencia contextual para el ciclista"). Contexto de negocio ya construido y probado: `docs/HOJA_DE_RUTA.md` sección 70 (ventana de gracia de 5h, backend + vista en vivo) y sección 21/`docs/superpowers/plans/2026-08-16-modalidad-tarifa-real.md` (cambio de modalidad real, Task 6).

## Global Constraints

- Reutilizar el patrón `<dialog>`/`.modal-card`/`.modal-header` ya definido en `app/static/css/main.css:1484-1514` y ya usado en `app/templates/gerente/tarifas.html` — no crear CSS ni componente nuevo.
- Textos en español, sin emojis, minimalistas (ver CLAUDE.md — sin decoraciones superfluas).
- Colores: solo `var(--text)`, `var(--text-muted)`, `var(--primary)`, `#EF4444` (ya usado en este mismo archivo para el recargo) — nunca Inter ni gradientes morados.
- No tocar la lógica de negocio real de gracia/recargo/cambio de modalidad (ya construida y probada, secciones 70 y 21 de `docs/HOJA_DE_RUTA.md`) — cambios acotados a la capa de presentación (un modal de confirmación antes de un submit que ya existía).
- Toda prueba contra PocketBase/ClickHouse reales (cuenta real, servidor real en el puerto 8013 reservado de este worktree) — nunca simulada — con limpieza documentada de cualquier dato de prueba generado, mismo criterio que el resto del proyecto.
- Type hints en todo código Python nuevo.

---

## File Structure

- `app/templates/ciclista/viaje_activo.html` (modificar): 2 `<dialog>` nuevos + JS de interceptación de submit para ambos formularios ya existentes.
- `app/routers/ciclista.py` (modificar): `viaje_activo()` (línea 986) agrega `precios_modalidad` al contexto — precio real de las 3 modalidades para la bicicleta/membresía del viaje, reusando `tarifas_repo.precio_modalidad_con_promocion()` (ya existe, sin cambios).

---

### Task 1: Ventana de advertencia al reportar la devolución (fin de viaje)

**Files:**
- Modify: `app/templates/ciclista/viaje_activo.html:102-127` (form "Devolver bicicleta"), agregar `<dialog>` nuevo después de la línea 127, agregar JS en `{% block scripts %}`.

**Interfaces:**
- Consumes: nada nuevo — el formulario ya existente (`action="/ciclista/finalizar"`) y `selectFin` (ya definido en el JS existente, línea ~161).
- Produces: nada que otra tarea consuma (independiente de la Task 2).

- [ ] **Step 1: Agregar `id="form-devolver"` al formulario existente**

En `app/templates/ciclista/viaje_activo.html`, reemplazar:

```html
  <form method="post" action="/ciclista/finalizar" style="padding:20px;">
      <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
    <input type="hidden" name="viaje_id" value="{{ viaje.id }}">
```

por:

```html
  <form method="post" action="/ciclista/finalizar" id="form-devolver" style="padding:20px;">
      <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
    <input type="hidden" name="viaje_id" value="{{ viaje.id }}">
```

- [ ] **Step 2: Agregar el `<dialog>` de confirmación, inmediatamente después del `{% endif %}` que cierra el bloque de las dos tarjetas (línea 128 actual, antes de `{% endblock %}` de `content`)**

Reemplazar:

```html
</div>
{% endif %}

{% endblock %}
```

por:

```html
</div>
{% endif %}

<dialog id="modal-confirmar-devolucion">
  <div class="modal-card">
    <div class="modal-header"><span class="card-title">Confirmar devolución</span>
      <button class="btn btn-ghost" style="padding:4px 10px;" onclick="document.getElementById('modal-confirmar-devolucion').close()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>
    <p style="color:var(--text);margin-bottom:8px;">Vas a reportar que dejaste <strong>{{ viaje.bicicleta_codigo }}</strong> en <strong id="modal-devolucion-estacion"></strong>.</p>
    <p style="color:var(--text-muted);margin-bottom:20px;">El costo se congela con la hora de este reporte. Tienes <strong>5 horas sin cargo adicional</strong> para que Vigilancia confirme la entrega física -- pasado ese tiempo se aplica un <strong>recargo por demora</strong> aparte.</p>
    <div class="flex gap-2" style="justify-content:flex-end;">
      <button type="button" class="btn btn-ghost" onclick="document.getElementById('modal-confirmar-devolucion').close()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="btn-confirmar-devolucion">Confirmar devolución</button>
    </div>
  </div>
</dialog>

{% endblock %}
```

- [ ] **Step 3: Interceptar el submit en JS -- agregar después del bloque `if (selectFin) { ... }` ya existente (línea ~168), antes del comentario "Cronómetro y costo en tiempo real"**

Reemplazar:

```javascript
if (selectFin) {
  selectFin.addEventListener('change', () => {
    const opt = selectFin.options[selectFin.selectedIndex];
    inputFinNombre.value = opt.dataset.nombre || '';
  });
}
```

por:

```javascript
if (selectFin) {
  selectFin.addEventListener('change', () => {
    const opt = selectFin.options[selectFin.selectedIndex];
    inputFinNombre.value = opt.dataset.nombre || '';
  });
}

// Ventana de advertencia contextual (punto 1.7): antes de reportar la
// devolución, el ciclista confirma en un modal explícito con la
// advertencia de las 5h de gracia -- el 'submit' del navegador solo
// dispara despues de que la validacion nativa de 'required' del select
// ya paso, asi que no hace falta revalidar aca.
const formDevolver = document.getElementById('form-devolver');
const modalDevolucion = document.getElementById('modal-confirmar-devolucion');
if (formDevolver && modalDevolucion) {
  const elModalEstacion = document.getElementById('modal-devolucion-estacion');
  formDevolver.addEventListener('submit', function (e) {
    if (formDevolver.dataset.confirmado === '1') return;
    e.preventDefault();
    const opt = selectFin.options[selectFin.selectedIndex];
    elModalEstacion.textContent = (opt && opt.value) ? (opt.dataset.nombre || '') : '';
    modalDevolucion.showModal();
  });
  document.getElementById('btn-confirmar-devolucion').addEventListener('click', function () {
    modalDevolucion.close();
    formDevolver.dataset.confirmado = '1';
    formDevolver.requestSubmit();
  });
}
```

- [ ] **Step 4: Prueba real de punta a punta (servidor real en el puerto 8013 de este worktree, cuenta real, PocketBase/ClickHouse reales -- no mocks)**

```bash
cd "C:\Users\Washington Apunte\Desktop\urbanbike\.claude\worktrees\plan-mejoras-v2-p1-g1"
python scripts/dev_reload.py 8013
```

Con el servidor corriendo, en otra terminal: reservar una bicicleta real de prueba (cuenta `wacho@urbanbike.com`), abrir `GET /ciclista/viaje-activo/{viaje_id}` autenticado y confirmar en el HTML devuelto:
- `id="modal-confirmar-devolucion"` presente en el DOM.
- El texto `5 horas sin cargo adicional` y `recargo por demora` presentes dentro del modal.
- `id="form-devolver"` presente en el formulario.

```bash
curl -s -b cookies_wacho.txt http://127.0.0.1:8013/ciclista/viaje-activo/<viaje_id> | grep -o "modal-confirmar-devolucion\|form-devolver\|5 horas sin cargo adicional"
```

Expected: las 3 coincidencias.

Luego, confirmar que `POST /ciclista/finalizar` (el endpoint real, sin cambios) sigue funcionando exactamente igual que antes -- reportar la devolución real vía `curl` (simulando el submit ya confirmado del modal) y confirmar que el viaje pasa a `pendiente_validacion`:

```bash
curl -s -b cookies_wacho.txt -X POST http://127.0.0.1:8013/ciclista/finalizar \
  -d "csrf_token=<token_real>&viaje_id=<viaje_id>&estacion_fin_id=<id_estacion_real>&estacion_fin_nombre=<nombre_estacion>"
```

Expected: redirect 302 a `/ciclista/viaje-activo/<viaje_id>`, y el registro real en PocketBase (`GET /api/collections/viajes/records/<viaje_id>`) con `estado="pendiente_validacion"`.

Limpiar el viaje/bicicleta de prueba generado (restaurar bicicleta a `disponible`, borrar el viaje si no aporta nada al historial real), documentando qué se limpió.

- [ ] **Step 5: Commit**

```bash
git add app/templates/ciclista/viaje_activo.html
git commit -m "feat: ventana de advertencia contextual al reportar la devolucion (punto 1.7)"
```

---

### Task 2: Ventana de advertencia al cambiar de modalidad a mitad de viaje

**Files:**
- Modify: `app/routers/ciclista.py:1000-1044` (`viaje_activo()`), agregar cómputo de `precios_modalidad`.
- Modify: `app/templates/ciclista/viaje_activo.html:88-101` (form "Cambiar modalidad"), agregar `<dialog>` nuevo, agregar JS.

**Interfaces:**
- Consumes: `tarifas_repo.precio_modalidad_con_promocion(bicicleta_codigo: str, tipo_membresia: str, modalidad: str) -> tuple[float, str] | None` (ya existe, `app/db/tarifas_repo.py:155`, sin cambios).
- Produces: `precios_modalidad: dict[str, float | None]` en el contexto de `ciclista/viaje_activo.html` — `{"hora": precio_o_None, "dia": ..., "semana": ...}`, precio real con promoción aplicada, mismo criterio que `precio_hora` (línea 1029 ya existente).

- [ ] **Step 1: Agregar el cómputo de `precios_modalidad` en `viaje_activo()` (`app/routers/ciclista.py`)**

Reemplazar (dentro del `try` existente, líneas 1028-1031):

```python
        resultado_precio = tarifas_repo.precio_modalidad_con_promocion(codigo_bici_viaje, tipo_membresia, modalidad_actual)
        precio_hora = resultado_precio[0] if resultado_precio else 0.0
        precio_hora_recargo = _tarifa_hora(codigo_bici_viaje, tipo_membresia)
        subtotal_segmentos_cerrados = alquileres_repo.total_segmentos_cerrados(viaje_id)
```

por:

```python
        resultado_precio = tarifas_repo.precio_modalidad_con_promocion(codigo_bici_viaje, tipo_membresia, modalidad_actual)
        precio_hora = resultado_precio[0] if resultado_precio else 0.0
        precio_hora_recargo = _tarifa_hora(codigo_bici_viaje, tipo_membresia)
        subtotal_segmentos_cerrados = alquileres_repo.total_segmentos_cerrados(viaje_id)

        # Precio real de las 3 modalidades para esta bicicleta/membresia
        # (punto 1.7 -- ventana de advertencia al cambiar de modalidad):
        # con promocion ya aplicada, mismo criterio que precio_hora arriba,
        # para que el aviso muestre el monto real que se cobraria, no uno
        # generico. None si no hay tarifa vigente para esa combinacion --
        # el template no inventa un precio.
        precios_modalidad: dict[str, float | None] = {}
        for _m in ("hora", "dia", "semana"):
            _r = tarifas_repo.precio_modalidad_con_promocion(codigo_bici_viaje, tipo_membresia, _m)
            precios_modalidad[_m] = _r[0] if _r else None
```

Y añadir la variable por defecto antes del `try` (junto a las otras variables por defecto ya presentes, líneas 1009-1010):

```python
    precio_hora_recargo = 0.0
    subtotal_segmentos_cerrados = 0.0
    precios_modalidad: dict[str, float | None] = {"hora": None, "dia": None, "semana": None}
```

- [ ] **Step 2: Pasar `precios_modalidad` al `TemplateResponse` (línea 1035-1044)**

Reemplazar:

```python
        precio_hora=precio_hora,  # precio de la modalidad actual del viaje (nombre de variable ya existente en el template)
        precio_hora_recargo=precio_hora_recargo,
        subtotal_segmentos_cerrados=subtotal_segmentos_cerrados,
    ))
```

por:

```python
        precio_hora=precio_hora,  # precio de la modalidad actual del viaje (nombre de variable ya existente en el template)
        precio_hora_recargo=precio_hora_recargo,
        subtotal_segmentos_cerrados=subtotal_segmentos_cerrados,
        precios_modalidad=precios_modalidad,
    ))
```

- [ ] **Step 3: Prueba real del cómputo antes de tocar el template**

Con el servidor real corriendo (puerto 8013) y un viaje activo real:

```bash
curl -s -b cookies_wacho.txt http://127.0.0.1:8013/ciclista/viaje-activo/<viaje_id_activo> > /tmp/viaje_activo_check.html
```

(No hay `precios_modalidad` renderizado visible todavía en el HTML -- este paso solo confirma que la ruta no rompe con el 500 antes de seguir. Confirmar código 200.)

- [ ] **Step 4: Agregar `id="select-modalidad-nueva"` y `id="form-cambiar-modalidad"` al formulario existente**

Reemplazar:

```html
  <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:10px;">Modalidad actual: <strong>{{ viaje.modalidad_actual or "hora" }}</strong></div>
  <form method="post" action="/ciclista/cambiar-modalidad" style="display:flex;gap:8px;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
    <input type="hidden" name="viaje_id" value="{{ viaje.id }}">
    <select class="form-input" name="modalidad_nueva">
      <option value="hora" {{ "selected" if viaje.modalidad_actual == "hora" or not viaje.modalidad_actual }}>Por hora</option>
      <option value="dia" {{ "selected" if viaje.modalidad_actual == "dia" }}>Por día</option>
      <option value="semana" {{ "selected" if viaje.modalidad_actual == "semana" }}>Por semana</option>
    </select>
    <button type="submit" class="btn btn-ghost">Cambiar modalidad</button>
  </form>
```

por:

```html
  <div style="font-size:0.85rem;color:var(--text-muted);margin-bottom:10px;">Modalidad actual: <strong>{{ viaje.modalidad_actual or "hora" }}</strong></div>
  <form method="post" action="/ciclista/cambiar-modalidad" id="form-cambiar-modalidad" style="display:flex;gap:8px;">
    <input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">
    <input type="hidden" name="viaje_id" value="{{ viaje.id }}">
    <select class="form-input" name="modalidad_nueva" id="select-modalidad-nueva">
      <option value="hora" {{ "selected" if viaje.modalidad_actual == "hora" or not viaje.modalidad_actual }}>Por hora</option>
      <option value="dia" {{ "selected" if viaje.modalidad_actual == "dia" }}>Por día</option>
      <option value="semana" {{ "selected" if viaje.modalidad_actual == "semana" }}>Por semana</option>
    </select>
    <button type="submit" class="btn btn-ghost">Cambiar modalidad</button>
  </form>
```

- [ ] **Step 5: Agregar el `<dialog>` de confirmación, junto al de la Task 1 (después del `</dialog>` de `modal-confirmar-devolucion`, antes de `{% endblock %}`)**

Reemplazar:

```html
</dialog>

{% endblock %}
```

por:

```html
</dialog>

<dialog id="modal-confirmar-modalidad">
  <div class="modal-card">
    <div class="modal-header"><span class="card-title">Confirmar cambio de modalidad</span>
      <button class="btn btn-ghost" style="padding:4px 10px;" onclick="document.getElementById('modal-confirmar-modalidad').close()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>
    <p style="color:var(--text);margin-bottom:8px;">El precio va a cambiar: dejarás de pagar <strong id="modal-modalidad-precio-actual"></strong> y desde ahora se te cobrará <strong id="modal-modalidad-precio-nuevo"></strong>.</p>
    <p style="color:var(--text-muted);margin-bottom:20px;">El tramo que ya recorriste en la modalidad actual se cobra aparte, con su propia tarifa -- vas a pagar un <strong>monto distinto</strong> al que verías si mantuvieras la modalidad original.</p>
    <div class="flex gap-2" style="justify-content:flex-end;">
      <button type="button" class="btn btn-ghost" onclick="document.getElementById('modal-confirmar-modalidad').close()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="btn-confirmar-modalidad">Confirmar cambio</button>
    </div>
  </div>
</dialog>

{% endblock %}
```

- [ ] **Step 6: JS de interceptación -- agregar en el mismo bloque de la Task 1, después del bloque de `formDevolver`**

Reemplazar (el cierre del bloque agregado en la Task 1, Step 3):

```javascript
  document.getElementById('btn-confirmar-devolucion').addEventListener('click', function () {
    modalDevolucion.close();
    formDevolver.dataset.confirmado = '1';
    formDevolver.requestSubmit();
  });
}
```

por:

```javascript
  document.getElementById('btn-confirmar-devolucion').addEventListener('click', function () {
    modalDevolucion.close();
    formDevolver.dataset.confirmado = '1';
    formDevolver.requestSubmit();
  });
}

// Mismo criterio (punto 1.7): antes de cambiar de modalidad a mitad de
// viaje, confirmar en un modal con el precio real de ambas modalidades
// -- PRECIOS_MODALIDAD viene del backend (viaje_activo(), Task 2 Step 1),
// mismo precio con promocion que ya usa el KPI "Costo del viaje" de esta
// misma pantalla. Si el ciclista no cambia realmente de modalidad
// (selecciona la misma que ya tiene), se deja pasar sin aviso -- no hay
// nada que confirmar.
const ETIQUETA_MODALIDAD = { hora: 'por hora', dia: 'por día', semana: 'por semana' };
const PRECIOS_MODALIDAD = {{ precios_modalidad | tojson }};
const formModalidad = document.getElementById('form-cambiar-modalidad');
const modalModalidad = document.getElementById('modal-confirmar-modalidad');
if (formModalidad && modalModalidad) {
  const selectModalidadNueva = document.getElementById('select-modalidad-nueva');
  const elPrecioActual = document.getElementById('modal-modalidad-precio-actual');
  const elPrecioNuevo  = document.getElementById('modal-modalidad-precio-nuevo');
  formModalidad.addEventListener('submit', function (e) {
    if (formModalidad.dataset.confirmado === '1') return;
    const modalidadActual = VIAJE.modalidad_actual || 'hora';
    const modalidadNueva  = selectModalidadNueva.value;
    if (modalidadNueva === modalidadActual) return; // sin cambio real, nada que confirmar
    e.preventDefault();
    const precioActual = PRECIOS_MODALIDAD[modalidadActual];
    const precioNuevo  = PRECIOS_MODALIDAD[modalidadNueva];
    elPrecioActual.textContent = (precioActual != null)
      ? `$${precioActual.toFixed(2)} ${ETIQUETA_MODALIDAD[modalidadActual]}` : ETIQUETA_MODALIDAD[modalidadActual];
    elPrecioNuevo.textContent = (precioNuevo != null)
      ? `$${precioNuevo.toFixed(2)} ${ETIQUETA_MODALIDAD[modalidadNueva]}` : ETIQUETA_MODALIDAD[modalidadNueva];
    modalModalidad.showModal();
  });
  document.getElementById('btn-confirmar-modalidad').addEventListener('click', function () {
    modalModalidad.close();
    formModalidad.dataset.confirmado = '1';
    formModalidad.requestSubmit();
  });
}
```

- [ ] **Step 7: Prueba real de punta a punta (servidor real puerto 8013, cuenta real, PocketBase/ClickHouse reales)**

Con un viaje real activo (modalidad `hora`):

```bash
curl -s -b cookies_wacho.txt http://127.0.0.1:8013/ciclista/viaje-activo/<viaje_id> | grep -o "modal-confirmar-modalidad\|select-modalidad-nueva\|PRECIOS_MODALIDAD = {[^}]*}"
```

Expected: las 3 coincidencias, con `PRECIOS_MODALIDAD` mostrando 3 números reales (o `null` si esa categoría/membresía no tiene tarifa vigente en alguna modalidad -- no debe romper el render).

Confirmar que el endpoint real `POST /ciclista/cambiar-modalidad` (sin cambios de esta tarea) sigue funcionando exactamente igual que antes de agregar el modal -- repetir el Step 4 de la Task 6 de `docs/superpowers/plans/2026-08-16-modalidad-tarifa-real.md` (cambiar modalidad de `hora` a `dia` en un viaje real, confirmar 1 fila nueva en `urbanbike_operativa.alquileres` con `origen='segmento_modalidad'` y `viajes.modalidad_actual` actualizado en PocketBase).

Limpiar todo dato de prueba generado (viaje, fila de `alquileres`, pago si se llegó a crear, bicicleta restaurada a `disponible`), documentando qué se limpió.

- [ ] **Step 8: Commit**

```bash
git add app/routers/ciclista.py app/templates/ciclista/viaje_activo.html
git commit -m "feat: ventana de advertencia contextual al cambiar de modalidad a mitad de viaje (punto 1.7)"
```

---

## Self-Review

**Cobertura del spec (punto 1.7):**
- "Al finalizar un viaje: aviso de que debe devolver la bicicleta, con advertencia explícita de que pasar 5 horas genera un cargo adicional" → Task 1.
- "Al cambiar de modalidad de tarifa mientras el viaje está activo: aviso de que el precio cambiará y de que deberá pagar un monto distinto" → Task 2.

**Sin placeholders:** todos los steps tienen el código real completo (HTML/JS/Python), no descripciones.

**Consistencia de tipos/nombres:** `precios_modalidad` se define igual en Python (`dict[str, float | None]`) que en el `tojson` del template; `id`s de los `<dialog>` (`modal-confirmar-devolucion`, `modal-confirmar-modalidad`) y de los botones/forms coinciden entre los steps que los crean y los que los consumen en JS.
