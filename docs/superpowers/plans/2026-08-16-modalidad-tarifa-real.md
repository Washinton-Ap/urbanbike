# Modalidad de tarifa real (hora/día/semana) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que la modalidad de tarifa (hora/día/semana) que el ciclista elige en la ficha de una bicicleta afecte de verdad el cobro real — hoy solo se muestra, nunca se cobra (auditoría real, ver spec).

**Architecture:** Estado del segmento ABIERTO (en vivo, mientras el viaje sigue `activo`) vive en PocketBase como 2 campos nuevos de `viajes` (`modalidad_actual`, `inicio_segmento_actual`). Segmentos CERRADOS (historial ya con costo resuelto) se insertan append-only en `urbanbike_operativa.alquileres` (ClickHouse), reusando sus columnas existentes — nunca `UPDATE`. La fuente única de precios pasa a ser `urbanbike_operativa.tarifas`, eliminando la colección vieja de PocketBase `tarifas`.

**Tech Stack:** FastAPI, Jinja2, PocketBase (`PocketBaseClient`/`get_admin_client()`), ClickHouse (`app.db.clickhouse`, `clickhouse-connect`). Sin test runner instalado (no hay pytest en `app/requirements.txt`) — cada tarea se verifica manualmente contra `uvicorn app.main:app --reload` real, con `curl`/PocketBase admin API/ClickHouse HTTP, mismo criterio que el resto del proyecto (ver `docs/superpowers/plans/2026-08-15-fase1-validaciones-export-logout.md`).

**Spec:** `docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md`

## Global Constraints

- Nunca `ALTER TABLE ... UPDATE` sobre `urbanbike_operativa.alquileres` para los segmentos nuevos — solo `INSERT` de filas ya completas (probado en el spec: el patrón `UPDATE` es una mutación asíncrona no apta para escrituras frecuentes, y el patrón append-only sin esto tiene riesgo de duplicados en lecturas sin `FINAL`).
- Nunca crear una colección/tabla nueva para segmentos — reusar `viajes` (PocketBase, 2 campos) y `alquileres` (ClickHouse, columnas existentes).
- `_tarifa_hora()` (ambas copias) y la colección PocketBase `tarifas` se retiran solo después de migrar TODOS sus consumidores reales (Tarea 4) — nunca borrar la colección antes de confirmar que nada la referencia.
- Todas las pruebas contra datos reales (cuentas reales, servidor real, PocketBase/ClickHouse reales) — nunca simuladas — y limpieza de cualquier dato de prueba generado, al cerrar cada tarea, mismo criterio que el resto del proyecto.
- `recargo_demora` siempre se calcula a la tarifa `hora` de la categoría/membresía correspondiente, nunca una tarifa plana adicional (spec, punto 4).
- Cambios de modalidad sin límite de cantidad por viaje, cada segmento cerrado se cobra completo sin prorratear (spec, Prioridad 4).

---

## File Structure

- `etl/15_agregar_campos_modalidad.py` (nuevo): agrega `modalidad_actual`/`inicio_segmento_actual` a `viajes` (PocketBase), idempotente, mismo patrón que `etl/12_crear_colecciones_flujo.py`.
- `app/db/clickhouse.py` (modificar): agregar `command()` (passthrough a `client.command()`, para `INSERT`/DDL sin resultado).
- `app/db/tarifas_repo.py` (modificar): nueva función compartida `precio_modalidad()` — reemplaza `_tarifa_hora()`/`_tarifas_por_categoria()` duplicadas en `ciclista.py`/`empleado.py`.
- `app/db/alquileres_repo.py` (modificar): nueva función `cerrar_segmento()` (insert append-only) y `total_segmentos_cerrados()` (suma real por viaje).
- `app/routers/ciclista.py` (modificar): `reservar()` (campo `modalidad`), nuevo endpoint `cambiar_modalidad()`, `alquilar()` (fuente única + fix del panel de mapa, sección 71), `_construir_factura_pago()` (líneas por segmento).
- `app/routers/empleado.py` (modificar): `vig_devolver()` (cierre de último segmento + suma real + recargo con nueva regla), `gerente.py:informe()` en realidad vive en `gerente.py`, no `empleado.py` — ver abajo.
- `app/routers/gerente.py` (modificar): `informe()` (fuente única de precios para `ingresos_estimados`).
- `app/templates/ciclista/detalle_bicicleta.html` (modificar): desplegable de modalidad en vez de 3 tarjetas.
- `app/templates/ciclista/viaje_activo.html` (modificar): control para cambiar modalidad, JS actualizado.
- `app/templates/empleado/vigilancia/devoluciones.html` (modificar): JS actualizado para leer segmentos.
- `app/templates/ciclista/alquilar.html` (modificar): panel de mapa usa `catalogo_bicicletas` en vez de `tarifaPara()`/`TARIFAS`.
- `app/static/js/costo-en-vivo.js` (modificar): `costoDetallado()` recibe segmentos cerrados + segmento abierto.
- `etl/16_backfill_modalidad_viajes_en_curso.py` (nuevo): migración retroactiva, un solo uso.
- `etl/17_eliminar_tarifas_pocketbase.py` (nuevo): borra la colección vieja, un solo uso, al final.

---

### Task 1: Campos nuevos en `viajes` (PocketBase) — segmento abierto

**Files:**
- Create: `etl/15_agregar_campos_modalidad.py`

**Interfaces:**
- Produces: campos reales `viajes.modalidad_actual` (select `hora`/`dia`/`semana`, `maxSelect: 1`) y `viajes.inicio_segmento_actual` (text) en el esquema real de PocketBase.

- [ ] **Step 1: Escribir el script idempotente**

```python
"""
ETL paso 15 (unico, NO forma parte del DAG horario): agrega los 2
campos nuevos que necesita el segmento ABIERTO de un viaje (modalidad
de tarifa real, ver docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md):

  - modalidad_actual: modalidad del segmento en curso (hora/dia/semana).
  - inicio_segmento_actual: cuando empezo ESE segmento (no siempre
    igual a viajes.fecha_inicio, si ya hubo cambios de modalidad antes).

Mismo patron que etl/12_crear_colecciones_flujo.py (PATCH del schema
completo -- PocketBase no permite agregar un campo suelto). Idempotente:
correrlo dos veces no falla ni duplica nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402

_CAMPOS_NUEVOS_VIAJES = [
    {"name": "modalidad_actual", "type": "select", "required": False, "maxSelect": 1,
     "values": ["hora", "dia", "semana"]},
    {"name": "inicio_segmento_actual", "type": "text", "required": False},
]


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
    print("Agregando campos de modalidad a viajes...")
    _agregar_campos_si_faltan(pb, "viajes", _CAMPOS_NUEVOS_VIAJES)
    print("Listo.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Correrlo contra PocketBase real**

Run: `python etl/15_agregar_campos_modalidad.py`
Expected: `viajes: agregados ['modalidad_actual', 'inicio_segmento_actual'].`

- [ ] **Step 3: Confirmar contra el esquema real (no solo el mensaje del script)**

Run:
```bash
PB_TOKEN=$(curl -s -X POST http://127.0.0.1:8090/api/collections/_superusers/auth-with-password -H "Content-Type: application/json" -d '{"identity":"admin@urbanbike.com","password":"secret_pocketbase"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s "http://127.0.0.1:8090/api/collections/viajes" -H "Authorization: $PB_TOKEN" | python -c "import sys,json;d=json.load(sys.stdin);[print(f['name'],f['type']) for f in d['fields']]" | grep modalidad_actual
```
Expected: `modalidad_actual select`

- [ ] **Step 4: Correrlo una segunda vez para confirmar idempotencia**

Run: `python etl/15_agregar_campos_modalidad.py`
Expected: `viajes: los campos nuevos ya existen, sin cambios.`

- [ ] **Step 5: Commit**

```bash
git add etl/15_agregar_campos_modalidad.py
git commit -m "feat: agregar modalidad_actual/inicio_segmento_actual a viajes (PocketBase)"
```

---

### Task 2: Columna `origen` en `alquileres` (ClickHouse) — separar segmentos nuevos de la migración histórica

**Contexto real, encontrado auditando antes de escribir este plan**: `ch.mapa_alquiler_por_viaje_pocketbase()` (`app/db/clickhouse.py:48`) ya se usa en 4 sitios reales (`ciclista.py:1196`, `ciclista.py:1511`, `empleado.py:403`, `inspecciones_repo.py:58`) asumiendo que solo existe **un** `alquileres` por `viaje_id` -- los 38 alquileres reales de la migración histórica de `etl/07_migrar_viajes_pagos.py`. Si los segmentos nuevos usan el mismo `id_origen_pocketbase` sin distinguirse, ese mapa quedaría ambiguo (varios `alquileres` por `viaje_id`) para viajes nuevos, y `inspecciones_repo.resolver_alquiler_id()` (que depende explícitamente de que un viaje "no migrado" devuelva su sentinela) dejaría de funcionar como está documentado. Se agrega una columna liviana para separarlos sin tocar el comportamiento de los 38 reales.

**Files:**
- Modify: `app/db/clickhouse.py`

**Interfaces:**
- Produces: `ch.command(sql: str, params: dict | None = None) -> None` en `app/db/clickhouse.py`.
- Produces: columna real `urbanbike_operativa.alquileres.origen` (`LowCardinality(String) DEFAULT 'migracion_historica'`).

- [ ] **Step 1: Agregar la columna real vía ALTER (ejecución directa, sin script -- mismo criterio que los ALTER anteriores de este proyecto, p.ej. `minutos_gracia`/`recargo_minuto` en `tarifas`)**

```bash
CH_PASS=$(grep CLICKHOUSE_PASSWORD .env | cut -d= -f2)
curl -s "http://127.0.0.1:8123/" --data-binary "ALTER TABLE urbanbike_operativa.alquileres ADD COLUMN IF NOT EXISTS origen LowCardinality(String) DEFAULT 'migracion_historica'" --user "admin:$CH_PASS"
```

- [ ] **Step 2: Confirmar que las 38 filas reales existentes quedaron con el valor por defecto**

```bash
curl -s "http://127.0.0.1:8123/" --data-binary "SELECT origen, count() FROM urbanbike_operativa.alquileres FINAL GROUP BY origen FORMAT TSVRaw" --user "admin:$CH_PASS"
```
Expected: `migracion_historica	38` (o el conteo real actual)

- [ ] **Step 3: Agregar `command()` a `app/db/clickhouse.py`, después de `scalar()`**

```python
def command(sql: str, params: dict | None = None) -> None:
    """INSERT / DDL sin resultado -- para las filas de segmento nuevas
    (ver docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md),
    nunca UPDATE."""
    get_client().command(sql, parameters=params or {})
```

- [ ] **Step 4: Actualizar `mapa_alquiler_por_viaje_pocketbase()` para que siga devolviendo EXACTAMENTE lo mismo que antes (solo la migración histórica)**

En `app/db/clickhouse.py`, reemplazar el cuerpo de `mapa_alquiler_por_viaje_pocketbase()`:

```python
def mapa_alquiler_por_viaje_pocketbase() -> dict[str, str]:
    """{viaje_id_pocketbase: id_alquiler} SOLO para los 38 alquileres
    reales de la migracion historica (etl/07_migrar_viajes_pagos.py) --
    origen='migracion_historica' filtra los segmentos de modalidad
    nuevos (origen='segmento_modalidad', ver
    docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md),
    que tambien usan id_origen_pocketbase pero NO deben aparecer aca:
    los 4 consumidores reales de este mapa (ciclista.py, empleado.py,
    inspecciones_repo.py) asumen un solo alquiler por viaje, exactamente
    el contrato que tenian antes de este cambio."""
    filas = query(
        "SELECT id, id_origen_pocketbase FROM urbanbike_operativa.alquileres FINAL "
        "WHERE id_origen_pocketbase != '' AND origen = 'migracion_historica'"
    )
    return {f["id_origen_pocketbase"]: str(f["id"]) for f in filas}
```

- [ ] **Step 5: Verificar en vivo que los 4 consumidores reales no cambiaron de comportamiento**

Run: `uvicorn app.main:app --reload` (si no está corriendo) y, autenticado como `empleado.vig@urbanbike.com`:
```bash
curl -s -b cookies_vig.txt http://127.0.0.1:8000/empleado/operacion/alquileres/<viaje_id_real_migrado>/flujo | grep -o "codigo.*A-[0-9]*" | head -1
```
Expected: el mismo `codigo` (`A-0XXXXX`) que mostraba antes de este cambio, para un viaje real de los 38 migrados.

- [ ] **Step 6: Commit**

```bash
git add app/db/clickhouse.py
git commit -m "feat: agregar ch.command() y columna origen en alquileres para separar segmentos de modalidad de la migracion historica"
```

---

### Task 3: Fuente única de precios — `precio_modalidad()` en `tarifas_repo.py`

**Files:**
- Modify: `app/db/tarifas_repo.py`
- Modify: `app/routers/ciclista.py:54-74` (mover `_tarifas_por_categoria()`), `app/routers/ciclista.py:295-307` (reemplazar `_tarifa_hora()`)
- Modify: `app/routers/empleado.py:53` (reemplazar `_tarifa_hora()` duplicada)

**Interfaces:**
- Produces: `tarifas_repo.categoria_de_bicicleta(codigo: str) -> str | None` (id de categoría real, o `None` si el código no existe).
- Produces: `tarifas_repo.precio_modalidad(id_categoria: str, tipo_membresia: str, modalidad: str) -> tuple[float, str] | None` — `(precio, id_tarifa)`, o `None` si no hay tarifa vigente para esa combinación.
- Consumes: `app.db.clickhouse as ch` (ya existe).

- [ ] **Step 1: Agregar las 2 funciones a `app/db/tarifas_repo.py`**

```python
def categoria_de_bicicleta(codigo: str) -> str | None:
    """id_categoria real (UUID de ClickHouse) para una bicicleta por su
    codigo -- mismo join que ya usa _catalogo_bicicletas() en
    ciclista.py, extraido aca para que _tarifa_hora() (el camino de
    cobro real) tambien pueda resolverlo, en vez de solo tipo_bicicleta
    classic/electric como hacia la coleccion vieja de PocketBase (ver
    docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md)."""
    fila = ch.query_one("""
        SELECT m.id_categoria AS id_categoria
        FROM urbanbike_operativa.bicicletas b FINAL
        INNER JOIN urbanbike_operativa.modelos_bicicleta m FINAL ON m.id = b.id_modelo
        WHERE b.codigo = %(codigo)s
    """, {"codigo": codigo})
    return str(fila["id_categoria"]) if fila else None


def precio_modalidad(id_categoria: str, tipo_membresia: str, modalidad: str) -> tuple[float, str] | None:
    """Precio real vigente + id de la fila de tarifa usada, para una
    categoria/membresia/modalidad -- fuente unica real de precios
    (reemplaza _tarifa_hora(), que leia la coleccion vieja de
    PocketBase tarifas, sin categoria ni dia/semana). None si no hay
    tarifa vigente para ese combo -- nunca se inventa un precio."""
    fila = ch.query_one("""
        SELECT id, precio FROM urbanbike_operativa.tarifas FINAL
        WHERE id_categoria = %(id_categoria)s AND tipo_membresia = %(tipo_membresia)s
          AND modalidad = %(modalidad)s AND estado = 'vigente'
          AND today() BETWEEN vigente_desde AND vigente_hasta
    """, {"id_categoria": id_categoria, "tipo_membresia": tipo_membresia, "modalidad": modalidad})
    return (float(fila["precio"]), str(fila["id"])) if fila else None
```

- [ ] **Step 2: Verificar contra datos reales antes de tocar los call sites**

Run:
```bash
python -c "
from app.db import tarifas_repo
cat = tarifas_repo.categoria_de_bicicleta('UB-001')
print('categoria UB-001:', cat)
print('precio hora casual:', tarifas_repo.precio_modalidad(cat, 'casual', 'hora'))
print('precio dia member:', tarifas_repo.precio_modalidad(cat, 'member', 'dia'))
"
```
Expected: una categoría real (UUID), y precios reales que coincidan con lo que hoy muestra `/ciclista/bicicleta/{id}` para UB-001.

- [ ] **Step 3: Reemplazar `_tarifa_hora()` en `ciclista.py:295-307`**

```python
def _tarifa_hora(bicicleta_codigo: str, tipo_membresia: str = "casual") -> float:
    """Compatibilidad temporal para los call sites que todavia solo
    piden 'hora' -- usa la fuente unica real (tarifas_repo), nunca la
    coleccion vieja de PocketBase. Devuelve 0.0 si no hay tarifa
    vigente, mismo comportamiento que antes (nunca levanta excepcion
    hacia el llamador)."""
    id_categoria = tarifas_repo.categoria_de_bicicleta(bicicleta_codigo)
    if not id_categoria:
        return 0.0
    resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, "hora")
    return resultado[0] if resultado else 0.0
```

Nota real: la firma cambia de `_tarifa_hora(pb, tipo_bicicleta, tipo_membresia)` a `_tarifa_hora(bicicleta_codigo, tipo_membresia)` -- ya no necesita `pb` (no lee PocketBase) ni `tipo_bicicleta` (usa categoría real, más preciso). Los call sites existentes (`ciclista.py:664`, `742`) tienen `bici`/`bicicleta_codigo` disponible en ese punto -- se ajustan en este mismo paso.

- [ ] **Step 4: Mismo reemplazo en `empleado.py:53`, y ajustar sus 2 call sites (`empleado.py:1482`, `1590`) para pasar `bicicleta_codigo` en vez de `tipo_bicicleta`**

(mismo código del Step 3, importando `tarifas_repo` en `empleado.py` si no está ya importado)

- [ ] **Step 5: Prueba real de regresión -- confirmar que un viaje por hora normal (sin modalidad todavía, tarea de esta sección) sigue cobrando exactamente igual que antes**

Repetir el Escenario A de la sección 70 de `docs/HOJA_DE_RUTA.md` (reservar `UB-006`, finalizar, validar de inmediato con Vigilancia) y confirmar que `pago.subtotal`/`precio_hora` coinciden con lo que mostraba la ficha del ciclista para esa bicicleta/categoría antes de este cambio. Limpiar el viaje/pago de prueba al terminar.

- [ ] **Step 6: Commit**

```bash
git add app/db/tarifas_repo.py app/routers/ciclista.py app/routers/empleado.py
git commit -m "feat: _tarifa_hora() lee la fuente unica de precios (ClickHouse) en vez de la coleccion vieja de PocketBase"
```

---

### Task 4: Migrar los 2 consumidores reales de la colección vieja antes de poder borrarla (Prioridad 3)

**Files:**
- Modify: `app/routers/gerente.py:1552-1559` (`informe()`)
- Modify: `app/routers/ciclista.py:492-493, 507-515` (`alquilar()`)
- Modify: `app/templates/ciclista/alquilar.html:171,189-192,242` (panel de mapa)

**Interfaces:**
- Consumes: `tarifas_repo.precio_modalidad()` (Task 3).

- [ ] **Step 1: `gerente.py:informe()` -- reemplazar el cálculo de `precio_promedio`**

Reemplazar (líneas 1552-1559):
```python
    try:
        precios = ch.query("""
            SELECT precio FROM urbanbike_operativa.tarifas FINAL
            WHERE modalidad = 'hora' AND estado = 'vigente'
              AND today() BETWEEN vigente_desde AND vigente_hasta
        """)
        precios_validos = [float(p["precio"]) for p in precios]
        if precios_validos:
            precio_promedio = sum(precios_validos) / len(precios_validos)
    except Exception:
        pass
```

- [ ] **Step 2: Verificar en vivo (login real como `gerente@urbanbike.com`)**

```bash
curl -s -b cookies_gerente.txt http://127.0.0.1:8000/gerente/informe | grep -o "ingresos_estimados[^<]*" 
```
Expected: un número real, no `0` ni un error 500.

- [ ] **Step 3: `ciclista.py:alquilar()` -- quitar la consulta a la colección vieja**

Eliminar las líneas 492-493 (`res_t = pb.list_records("tarifas"...)`) y `tarifas_json=json.dumps(tarifas)` del `TemplateResponse` (línea ~512).

- [ ] **Step 4: `alquilar.html` -- el panel de mapa usa el precio real del catálogo (cierra también el hallazgo de la sección 71 de la hoja de ruta)**

Reemplazar (líneas 171, 189-192):
```javascript
const CATALOGO   = {{ catalogo_bicicletas | tojson }};

function tarifaPara(codigoBici) {
  const b = CATALOGO.find(x => x.codigo === codigoBici);
  return b ? Number(b.precio_hora_member) : 0;
}
```

Y en `bicicletaCard()` (línea 242), cambiar `tarifaPara(bici.tipo)` por `tarifaPara(bici.codigo)`.

- [ ] **Step 5: Prueba real -- confirmar que el panel de mapa y la tarjeta principal ahora muestran EL MISMO precio para la misma bicicleta**

```bash
curl -s -b cookies_wacho.txt http://127.0.0.1:8000/ciclista/alquilar > /tmp/alquilar_check.html
grep -o "precio_hora_member[^,]*" /tmp/alquilar_check.html | head -1
```
Y comparar visualmente en Chrome (o con el HTML) que el precio del panel del mapa para `UB-001` coincide con el de su tarjeta en el catálogo principal.

- [ ] **Step 6: Actualizar la sección 71 de `docs/HOJA_DE_RUTA.md`** -- agregar una nota al final de esa sección: "Corregido como parte de la Tarea 4 del plan de modalidad de tarifa real, `<fecha>`."

- [ ] **Step 7: Commit**

```bash
git add app/routers/gerente.py app/routers/ciclista.py app/templates/ciclista/alquilar.html docs/HOJA_DE_RUTA.md
git commit -m "fix: migrar informe.html y el panel de mapa de alquilar.html a la fuente unica de precios"
```

---

### Task 5: Reservar con modalidad real + desplegable en la ficha

**Files:**
- Modify: `app/routers/ciclista.py` (`reservar()`, línea 519 en adelante)
- Modify: `app/templates/ciclista/detalle_bicicleta.html:184-235`

**Interfaces:**
- Consumes: `tarifas_repo.categoria_de_bicicleta()`, `tarifas_repo.precio_modalidad()` (Task 3).
- Produces: `viajes.modalidad_actual`/`inicio_segmento_actual` poblados al crear un viaje.

- [ ] **Step 1: Agregar el parámetro `modalidad` a `reservar()`**

```python
async def reservar(
    request: Request,
    bicicleta_id:          str = Form(...),
    bicicleta_codigo:      str = Form(...),
    estacion_inicio_id:    str = Form(...),
    estacion_inicio_nombre: str = Form(...),
    modalidad:              str = Form("hora"),
    latitud:               str = Form("0"),
    longitud:               str = Form("0"),
    codigo_descuento:      str = Form(""),
):
```

- [ ] **Step 2: Validar la modalidad recibida (nunca confiar en el valor del form directo)**

Justo después de resolver `user_id`:
```python
    if modalidad not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse("/ciclista/alquilar", status_code=302)
```

- [ ] **Step 3: Poblar los 2 campos nuevos al crear el viaje (dentro del `pb.create_record("viajes", {...})` ya existente)**

Agregar al diccionario que ya arma `reservar()`:
```python
            "modalidad_actual":       modalidad,
            "inicio_segmento_actual": _ahora(),
```

- [ ] **Step 4: Reemplazar las 3 tarjetas de `detalle_bicicleta.html` por un `<select>`**

Reemplazar el bloque `.tarjeta-tarifas-grid` (líneas 184-235) por:
```html
{% if catalogo_bici %}
<div class="card" style="padding:20px;background:var(--primary-light);">
  <div class="form-group" style="margin-bottom:0;">
    <label class="form-label">Modalidad</label>
    <select class="form-input" name="modalidad" id="select-modalidad" form="form-reservar">
      <option value="hora" selected data-precio="{{ catalogo_bici.precio_hora_member }}">Por hora — ${{ "%.2f" | format(catalogo_bici.precio_hora_member) }}</option>
      <option value="dia" data-precio="{{ catalogo_bici.precio_dia_member }}">Por día — ${{ "%.2f" | format(catalogo_bici.precio_dia_member) }}</option>
      <option value="semana" data-precio="{{ catalogo_bici.precio_semana_member }}">Por semana — ${{ "%.2f" | format(catalogo_bici.precio_semana_member) }}</option>
    </select>
    <div style="font-family:'Sora',sans-serif;font-weight:800;font-size:1.6rem;color:var(--primary);margin-top:10px;" id="precio-modalidad-seleccionada">${{ "%.2f" | format(catalogo_bici.precio_hora_member) }}</div>
  </div>
</div>
{% endif %}
```

- [ ] **Step 5: `id="form-reservar"` en el form de "Reservar esta bicicleta" (línea 244) para que el `<select>` de fuera del form (`form="form-reservar"`) se envíe con él**

```html
<form method="post" action="/ciclista/reservar" id="form-reservar">
```

- [ ] **Step 6: JS que actualiza el precio mostrado al cambiar el `<select>`, en `{% block scripts %}`**

```html
<script>
document.getElementById('select-modalidad').addEventListener('change', function () {
  const precio = this.options[this.selectedIndex].dataset.precio;
  document.getElementById('precio-modalidad-seleccionada').textContent = `$${parseFloat(precio).toFixed(2)}`;
});
</script>
```

- [ ] **Step 7: Prueba real de punta a punta**

Reservar una bicicleta real con `modalidad=dia` vía `curl` (cuenta `wacho@urbanbike.com`), y confirmar en PocketBase (API admin) que el viaje creado tiene `modalidad_actual="dia"` e `inicio_segmento_actual` poblado con la hora real. Limpiar el viaje de prueba al terminar (sin pago creado todavía, solo borrar el viaje y devolver la bicicleta a `disponible`).

- [ ] **Step 8: Commit**

```bash
git add app/routers/ciclista.py app/templates/ciclista/detalle_bicicleta.html
git commit -m "feat: seleccion real de modalidad al reservar, desplegable en la ficha"
```

---

### Task 6: Cambiar de modalidad a mitad de viaje

**Files:**
- Modify: `app/db/alquileres_repo.py` (crear si no existe con ese nombre exacto — repo dedicado a `urbanbike_operativa.alquileres`)
- Modify: `app/routers/ciclista.py` (nuevo endpoint)
- Modify: `app/templates/ciclista/viaje_activo.html`

**Interfaces:**
- Produces: `alquileres_repo.cerrar_segmento(viaje_id: str, ciclista_id: str, bicicleta_codigo: str, modalidad: str, id_tarifa: str, fecha_inicio: str, fecha_fin: str, subtotal: float, recargo: float) -> None`.
- Consumes: `tarifas_repo.categoria_de_bicicleta()`, `tarifas_repo.precio_modalidad()`, `ch.command()` (Tasks 2-3).

- [ ] **Step 1: `cerrar_segmento()` en `app/db/alquileres_repo.py`**

```python
"""Historial real de segmentos de modalidad, en
urbanbike_operativa.alquileres -- ver
docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md.
Append-only puro: cada fila se inserta ya completa, nunca se hace
UPDATE sobre una fila ya insertada."""

from __future__ import annotations

import uuid

from app.db import clickhouse as ch


def cerrar_segmento(*, viaje_id: str, ciclista_id: str, bicicleta_codigo: str,
                     modalidad: str, id_tarifa: str, fecha_inicio: str, fecha_fin: str,
                     subtotal: float, recargo: float) -> None:
    ch.command("""
        INSERT INTO urbanbike_operativa.alquileres
            (id, id_origen_pocketbase, id_tarifa, modalidad,
             fecha_inicio, fecha_fin, estado, subtotal, recargo, total, origen)
        VALUES
            (%(id)s, %(viaje_id)s, %(id_tarifa)s, %(modalidad)s,
             %(fecha_inicio)s, %(fecha_fin)s, 'facturado', %(subtotal)s, %(recargo)s,
             %(total)s, 'segmento_modalidad')
    """, {
        "id": str(uuid.uuid4()), "viaje_id": viaje_id, "id_tarifa": id_tarifa,
        "modalidad": modalidad, "fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin,
        "subtotal": round(subtotal, 2), "recargo": round(recargo, 2),
        "total": round(subtotal + recargo, 2),
    })


def total_segmentos_cerrados(viaje_id: str) -> float:
    """Suma real de todos los segmentos ya cerrados de un viaje -- sin
    FINAL porque cada fila se escribe una sola vez y nunca se vuelve a
    tocar (append-only puro, no hay nada que fusionar)."""
    fila = ch.query_one(
        "SELECT sum(total) AS total FROM urbanbike_operativa.alquileres "
        "WHERE id_origen_pocketbase = %(viaje_id)s AND origen = 'segmento_modalidad'",
        {"viaje_id": viaje_id},
    )
    return float(fila["total"] or 0) if fila else 0.0
```

Nota real: `id_usuario`/`id_bicicleta`/`id_estacion_inicio` (columnas UUID de `alquileres` que referencian dimensiones de ClickHouse, no ids de PocketBase) se dejan con su valor `DEFAULT` -- no hay una forma real de resolverlos sin otro join innecesario para este propósito (el vínculo real es `id_origen_pocketbase`, que sí es preciso). `cantidad_contratada`/`minutos_contratados` tampoco se completan -- no aportan nada al cálculo real de esta tarea.

- [ ] **Step 2: Endpoint nuevo `POST /ciclista/cambiar-modalidad` en `ciclista.py`**

```python
@router.post("/cambiar-modalidad")
async def cambiar_modalidad(
    request: Request,
    viaje_id:        str = Form(...),
    modalidad_nueva: str = Form(...),
):
    if modalidad_nueva not in ("hora", "dia", "semana"):
        request.session["flash"] = {"type": "error", "msg": "Modalidad no válida."}
        return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

    user = getattr(request.state, "user", {})
    try:
        pb = _pb()
        viaje = pb.get_record("viajes", viaje_id)
        if viaje.get("estado") != "activo":
            request.session["flash"] = {"type": "error", "msg":
                "Solo puedes cambiar la modalidad mientras el viaje sigue activo."}
            return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

        bici = pb.get_record("bicicletas", viaje.get("bicicleta_id", ""))
        bicicleta_codigo = bici.get("codigo", viaje.get("bicicleta_codigo", ""))
        tipo_membresia = membresias_repo.tipo_membresia_real(user.get("email", ""))
        id_categoria = tarifas_repo.categoria_de_bicicleta(bicicleta_codigo)

        modalidad_actual = viaje.get("modalidad_actual") or "hora"
        inicio_actual = viaje.get("inicio_segmento_actual") or viaje.get("fecha_inicio")
        ahora = _ahora()

        # Se resuelve el precio del segmento SALIENTE antes de escribir nada
        # en ninguna base -- si esto falla, el viaje queda exactamente
        # como estaba.
        resultado_actual = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, modalidad_actual)
        subtotal_segmento = None
        id_tarifa_actual = None
        if resultado_actual:
            precio_actual, id_tarifa_actual = resultado_actual
            if modalidad_actual == "hora":
                # Piso de 1 minuto (decidido con Washington, 16-ago-2026,
                # tras encontrar la discrepancia real en la Tarea 7):
                # mismo criterio que el codigo original (duracion = max(1,
                # int(...))) -- nunca cobra menos de 1 minuto por segmento,
                # ni siquiera si el cambio de modalidad fue casi instantaneo.
                minutos_segmento = max(1, int((datetime.now(timezone.utc) - datetime.fromisoformat(
                    inicio_actual.replace("Z", "+00:00"))).total_seconds() / 60))
                subtotal_segmento = round(minutos_segmento / 60 * precio_actual, 2)
            else:
                subtotal_segmento = precio_actual

        # PocketBase PRIMERO -- es la fuente real del estado del viaje. Si
        # esto falla, no se llega a tocar ClickHouse: el viaje queda
        # exactamente como estaba, sin inconsistencia posible (decisión
        # confirmada con Washington: entre "cobrar de más" y "no cobrar
        # ese tramo" ante un fallo a mitad de camino, se prefiere lo
        # segundo -- más seguro para el ciclista que para UrbanBike, pero
        # nunca duplica un cobro).
        pb.update_record("viajes", viaje_id, {
            "modalidad_actual": modalidad_nueva,
            "inicio_segmento_actual": ahora,
        })

        # ClickHouse DESPUES: si esto falla, la modalidad YA cambió (el
        # paso anterior ya se comiteó) -- se avisa con un mensaje que
        # refleja la realidad, no un "no se pudo cambiar la modalidad"
        # generico que sugeriria que nada pasó cuando sí pasó.
        if subtotal_segmento is not None:
            try:
                alquileres_repo.cerrar_segmento(
                    viaje_id=viaje_id, ciclista_id=viaje.get("ciclista_id", ""),
                    bicicleta_codigo=bicicleta_codigo, modalidad=modalidad_actual,
                    id_tarifa=id_tarifa_actual, fecha_inicio=inicio_actual, fecha_fin=ahora,
                    subtotal=subtotal_segmento, recargo=0.0,
                )
            except Exception:
                request.session["flash"] = {"type": "info", "msg":
                    f"Modalidad cambiada a {modalidad_nueva}, pero hubo un problema registrando "
                    "el cobro del tramo anterior -- contacta a soporte si el monto final no coincide."}
                return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)

        request.session["flash"] = {"type": "success", "msg":
            f"Modalidad cambiada a {modalidad_nueva}. El tramo anterior ya quedó cobrado."}
    except Exception as e:
        request.session["flash"] = {"type": "error", "msg": f"No se pudo cambiar la modalidad: {e}"}
    return RedirectResponse(f"/ciclista/viaje-activo/{viaje_id}", status_code=302)
```

**Nota real sobre fallo parcial (pedido explícito de Washington, no asumido)**: este endpoint escribe en dos bases sin transacción que las una. Se decidió con Washington: PocketBase se actualiza primero (fuente real del estado del viaje); si el `INSERT` del segmento cerrado en ClickHouse falla DESPUÉS de eso, el resultado es que ese tramo específico queda sin cobrar (no se duplica nunca un cobro) -- riesgo aceptado a propósito, más seguro para el ciclista que para UrbanBike. El mensaje de error en ese caso específico es distinto (`type: "info"`, no `"error"`) porque la modalidad sí cambió de verdad -- un mensaje genérico de error ahí sería falso. Este mismo criterio de orden (PocketBase primero, ClickHouse después) debe aplicarse también en la Tarea 7 (`vig_devolver()`), que tiene el mismo patrón de dos escrituras -- ver nota en esa tarea.

- [ ] **Step 3: Control en `viaje_activo.html`, solo visible mientras `estado == 'activo'`**

Agregar antes del formulario de "Devolver bicicleta" (línea ~74, dentro del mismo `{% if viaje.estado != 'pendiente_validacion' %}`):
```html
<div class="card" style="margin-bottom:20px;padding:20px;">
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
</div>
```

- [ ] **Step 4: Prueba real de punta a punta**

Reservar una bicicleta real en modalidad `hora`, esperar ~30s reales, cambiar a `dia` vía el endpoint. Confirmar en ClickHouse (`SELECT * FROM urbanbike_operativa.alquileres WHERE id_origen_pocketbase = '<viaje_id>'`) que hay exactamente 1 fila nueva con `modalidad='hora'`, `origen='segmento_modalidad'`, `subtotal` pequeño y real (proporcional a los ~30s). Confirmar en PocketBase que `viajes.modalidad_actual = 'dia'`. Limpiar: finalizar y borrar el viaje/pago de prueba, borrar la fila de `alquileres` insertada, restaurar la bicicleta a `disponible`.

- [ ] **Step 5: Confirmar con datos reales que esta fila nueva NO contamina el WorkPanel de Operación (`app/db/alquileres_repo.py`, real, ya existente, `listar()`/`obtener()`) -- ese repo hace `INNER JOIN` sobre `id_bicicleta`/`id_usuario` reales, y las filas de segmento se insertan sin esos campos (quedan en su UUID por defecto); confirmar con la base real que eso las excluye del `INNER JOIN`, no asumirlo**

```bash
CH_PASS=$(grep CLICKHOUSE_PASSWORD .env | cut -d= -f2)
curl -s "http://127.0.0.1:8123/" --data-binary "SELECT count() FROM urbanbike_operativa.alquileres a FINAL JOIN urbanbike_operativa.bicicletas b FINAL ON b.id = a.id_bicicleta WHERE a.origen = 'segmento_modalidad' FORMAT TSVRaw" --user "admin:$CH_PASS"
```
Expected: `0` (ninguna fila de segmento hace match real con una bicicleta -- confirma que `alquileres_repo.listar()` nunca las va a mostrar). Si el resultado no es `0`, hay que agregar un filtro explícito `a.origen != 'segmento_modalidad'` a `listar()`/`obtener()` en `app/db/alquileres_repo.py` antes de seguir -- no dejarlo pasar.

- [ ] **Step 6: Commit**

```bash
git add app/db/alquileres_repo.py app/routers/ciclista.py app/templates/ciclista/viaje_activo.html
git commit -m "feat: endpoint para cambiar de modalidad a mitad de viaje, con cierre de segmento real"
```

---

### Task 7: `vig_devolver()` — cerrar el último segmento y sumar todo el viaje

**Files:**
- Modify: `app/routers/empleado.py:1490-1643` (`vig_devolver()`)

**Interfaces:**
- Consumes: `alquileres_repo.cerrar_segmento()`, `alquileres_repo.total_segmentos_cerrados()` (Task 6), `tarifas_repo.categoria_de_bicicleta()`/`precio_modalidad()` (Task 3).

**Nota real -- ordenamiento resuelto (mismo criterio que la Tarea 6, decidido con Washington)**: `vig_devolver()` también escribe en dos bases sin transacción. A diferencia de la Tarea 6, acá el monto del pago NO depende de releer ClickHouse después de insertar -- `subtotal_ultimo_segmento` ya se calcula en Python antes de escribir nada, así que el `pago` puede armarse con el monto correcto sin importar si el `INSERT` del último segmento en ClickHouse después tiene éxito o no. Por eso el diseño es: **todas las escrituras de PocketBase primero** (viaje → completado, bici → mantenimiento, pago creado con el monto correcto, notificaciones) **y el `INSERT` del último segmento en ClickHouse al final, envuelto en su propio `try/except` que nunca bloquea el resto** -- si falla, todo lo demás ya sucedió correctamente (el ciclista fue cobrado bien), solo falta esa fila en el historial de `alquileres`. Se aprovecha para dejar un rastro real en `registrar_auditoria()` cuando esto pasa -- mitiga en parte el hallazgo de que `cambiar_modalidad()` (Tarea 6) no deja ningún rastro cuando le pasa lo mismo (ver spec, sección "Fuera de alcance").

- [ ] **Step 1: Agregar los imports que le faltan a `empleado.py`**

```python
from datetime import timedelta  # sumado al import ya existente "from datetime import datetime, timezone"
from app.db import alquileres_repo, tarifas_repo  # nuevos, junto a los demas imports de app.db ya presentes
```

- [ ] **Step 2: Calcular el costo del último segmento (líneas 1519-1540 aprox., antes de tocar cualquier base) -- reemplaza el cálculo original de `duracion`/`retraso_min`**

```python
        # Cierre del ULTIMO segmento (punto 4 del spec) -- con la hora
        # REAL de confirmacion de Vigilancia, nunca con la hora que
        # reporto el ciclista (mismo criterio de siempre). Todo esto es
        # solo calculo en Python, sin escribir nada todavia -- si algo
        # falla aca, el viaje queda exactamente como estaba.
        ahora = datetime.now(timezone.utc)
        ahora_str = _ahora()
        modalidad_final = viaje.get("modalidad_actual") or "hora"
        inicio_segmento_final = viaje.get("inicio_segmento_actual") or viaje.get("fecha_inicio", "")

        tipo_membresia = "casual"
        try:
            ciclista_pb = pb.get_record("users", viaje.get("ciclista_id", ""))
            tipo_membresia = membresias_repo.tipo_membresia_real(ciclista_pb.get("email", ""))
        except Exception:
            pass

        bici_codigo_para_tarifa = viaje.get("bicicleta_codigo", "")
        id_categoria = tarifas_repo.categoria_de_bicicleta(bici_codigo_para_tarifa)
        resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, modalidad_final) if id_categoria else None
        precio_hora_display = 0.0  # para el campo precio_hora de 'pagos', compatibilidad con facturas viejas
        id_tarifa_final = None

        retraso_min = 0.0
        subtotal_ultimo_segmento = 0.0
        if resultado:
            precio_modalidad_final, id_tarifa_final = resultado
            inicio_dt = datetime.fromisoformat(inicio_segmento_final.replace("Z", "+00:00"))

            if modalidad_final == "hora":
                # Piso de 1 minuto (decidido con Washington, 16-ago-2026):
                # mismo criterio que el codigo original (duracion = max(1,
                # int(...))) -- restaura la paridad exacta con la seccion 70.
                minutos_ultimo_segmento = max(1, int((ahora - inicio_dt).total_seconds() / 60))
                subtotal_ultimo_segmento = round(minutos_ultimo_segmento / 60 * precio_modalidad_final, 2)
                # Gracia de 5h desde que el ciclista reporto la devolucion
                # (fecha_fin del viaje), NO desde el inicio del segmento --
                # igual que antes de este cambio (ver seccion 70).
                fecha_fin_reportada = viaje.get("fecha_fin", "")
                if fecha_fin_reportada:
                    fin_dt = datetime.fromisoformat(fecha_fin_reportada.replace("Z", "+00:00"))
                    retraso_min = max(0.0, (ahora - fin_dt).total_seconds() / 60 - 300)
                precio_hora_display = precio_modalidad_final
            else:
                subtotal_ultimo_segmento = precio_modalidad_final
                # Gracia de 5h desde que TERMINA la ventana comprada
                # (dia=24h, semana=7d), no desde el reporte -- con
                # tarifa plana, "demora" es exceder lo pagado (spec).
                horas_ventana = 24 if modalidad_final == "dia" else 24 * 7
                fin_ventana = inicio_dt + timedelta(hours=horas_ventana)
                retraso_min = max(0.0, (ahora - fin_ventana).total_seconds() / 60 - 300)
                precio_hora_resultado = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, "hora")
                precio_hora_display = precio_hora_resultado[0] if precio_hora_resultado else 0.0

            recargo_demora = round(retraso_min / 60 * precio_hora_display, 2)
        else:
            recargo_demora = 0.0

        duracion = max(1, int((ahora - datetime.fromisoformat(
            viaje.get("fecha_inicio", "").replace("Z", "+00:00"))).total_seconds() / 60))

        actualizar_viaje = {
            "estado":           "completado",
            "estacion_fin_id":  estacion_fin_id,
            "duracion_minutos": duracion,
        }
        if not origen_pendiente_validacion:
            actualizar_viaje["fecha_fin"] = ahora_str
        pb.update_record("viajes", viaje_id, actualizar_viaje)
```

**Nota real**: este bloque reemplaza tanto el cálculo de `duracion`/`retraso_min` original (líneas 1531-1545) como el de `precio_hora`/`subtotal`/`recargo_demora` (líneas 1590-1592) -- se fusionan porque ahora dependen de la modalidad del último segmento. Ya NO llama a `alquileres_repo.cerrar_segmento()` acá (se mueve al final, ver Step 5) -- este bloque termina con el `pb.update_record("viajes", ...)` de siempre, ahora la primera escritura real de la función. `bici_codigo_para_tarifa` usa `viaje.get("bicicleta_codigo")` directo (mismo criterio que la Tarea 3, no depende de la variable `bici` que se resuelve más abajo en la función).

- [ ] **Step 3: Ajustar el `subtotal` que se guarda en `pagos` para que sea la suma real de TODOS los segmentos, no solo el último**

Donde antes decía `subtotal = round(duracion / 60 * precio_hora, 2)` (línea 1591), reemplazar por:
```python
            subtotal = round(alquileres_repo.total_segmentos_cerrados(viaje_id) + subtotal_ultimo_segmento, 2)
```
Esta suma es segura de leer en cualquier momento: `total_segmentos_cerrados()` solo trae los segmentos que YA se cerraron antes (de cambios de modalidad previos reales), y `subtotal_ultimo_segmento` es el valor ya calculado en Python en el Step 2 -- deliberadamente NO depende de que el `INSERT` del último segmento (Step 5, al final de la función) haya sucedido todavía, que es justamente lo que permite crear el pago con el monto correcto sin importar si ese `INSERT` tiene éxito o no.

- [ ] **Step 4: `precio_hora` guardado en `pagos` pasa a ser `precio_hora_display`** (para que la factura/reportes viejos que leen ese campo sigan teniendo un número real, aunque el último segmento no haya sido `hora`)

- [ ] **Step 5: Insertar el último segmento en ClickHouse AL FINAL de la función -- después de crear el pago, junto a `registrar_auditoria()` (línea ~1643 actual), antes del `return RedirectResponse(...)` -- envuelto en su propio `try/except` que nunca bloquea el resto**

Reemplazar el bloque de `detalle`/`registrar_auditoria()` existente por:
```python
        detalle = f"Devolución {motivo} en {estacion_fin_nombre} (duración real: {duracion} min) — bicicleta retenida para inspección"
        if observaciones:
            detalle += f" — {observaciones}"

        # INSERT del ultimo segmento en ClickHouse -- al final a proposito
        # (ver nota de ordenamiento arriba): si esto falla, el viaje ya
        # esta completado, la bici ya esta en mantenimiento y el pago ya
        # se creo con el monto correcto (subtotal_ultimo_segmento no
        # depende de que este INSERT tenga exito). Solo faltaria esa fila
        # en el historial de alquileres -- se deja rastro real en la
        # auditoria para que no quede invisible del todo.
        if resultado:
            try:
                alquileres_repo.cerrar_segmento(
                    viaje_id=viaje_id, ciclista_id=viaje.get("ciclista_id", ""),
                    bicicleta_codigo=bici_codigo_para_tarifa, modalidad=modalidad_final,
                    id_tarifa=id_tarifa_final, fecha_inicio=inicio_segmento_final,
                    fecha_fin=ahora_str, subtotal=subtotal_ultimo_segmento, recargo=recargo_demora,
                )
            except Exception as e:
                detalle += f" — AVISO: no se pudo registrar el último segmento en el historial ({e})"

        registrar_auditoria(
            user.get("pb_token", ""), user.get("id", ""), user.get("name") or user.get("email", ""),
            user.get("email", ""), "editar", "viajes", detalle, request,
            usuario_rol=user.get("rol_nombre") or user.get("rol_slug", ""),
        )

        return RedirectResponse(f"/empleado/vigilancia/inspeccion/{bici_id}", status_code=302)
```

- [ ] **Step 6: Prueba real de regresión completa -- repetir LOS DOS escenarios de la sección 70 de la hoja de ruta (dentro y fuera de gracia, modalidad hora) y confirmar que los montos no cambiaron ni un centavo respecto a lo ya probado ahí.**

- [ ] **Step 7: Prueba real nueva -- modalidad `dia`, dentro y fuera de la ventana de 24h + 5h de gracia (mismo criterio de simular tiempo adelantando `fecha_inicio`/`inicio_segmento_actual` en PocketBase, igual que la sección 70)**

Confirmar `pago.subtotal`, `pago.recargo_demora` contra el ejemplo numérico del spec (categoría/precio reales de la base, no necesariamente los mismos $ del ejemplo).

- [ ] **Step 8: Limpieza de todos los datos de prueba generados en los Steps 6-7 (pagos, viajes, filas de `alquileres`, bicicletas restauradas)**

- [ ] **Step 9: Commit**

```bash
git add app/routers/empleado.py
git commit -m "feat: vig_devolver() cierra el ultimo segmento y suma todos los segmentos del viaje"
```

---

### Task 8: Factura con una línea por segmento

**Files:**
- Modify: `app/routers/ciclista.py` (`_construir_factura_pago()`, línea 1019)

**Interfaces:**
- Consumes: nada nuevo -- lee `alquileres` directo por simplicidad (la factura ya es de solo lectura, no participa del cobro).

- [ ] **Step 1: Agregar la consulta de segmentos y las líneas por segmento**

Dentro de `_construir_factura_pago()`, antes de armar `lineas`:
```python
    segmentos = ch.query(
        "SELECT modalidad, subtotal FROM urbanbike_operativa.alquileres "
        "WHERE id_origen_pocketbase = %(viaje_id)s AND origen = 'segmento_modalidad' "
        "ORDER BY fecha_inicio",
        {"viaje_id": viaje.get("id", "")},
    )
```

Reemplazar el `if registro.get("tipo") == "cargo_danos": ... else: lineas = [LineaFactura("Tarifa base...")]` por:
```python
    if registro.get("tipo") == "cargo_danos":
        lineas = [LineaFactura(registro.get("descripcion_cargo") or "Cargo por daños", 1, subtotal_base, subtotal_base)]
    elif segmentos:
        etiquetas = {"hora": "Tarifa por hora", "dia": "Tarifa por día", "semana": "Tarifa por semana"}
        lineas = [
            LineaFactura(etiquetas.get(s["modalidad"], "Tarifa"), 1, float(s["subtotal"]), float(s["subtotal"]))
            for s in segmentos
        ]
    else:
        # Pago anterior a este cambio, sin segmentos en alquileres -- mismo
        # comportamiento de siempre.
        lineas = [LineaFactura("Tarifa base (alquiler de bicicleta)", 1, subtotal_base, subtotal_base)]
```

- [ ] **Step 2: Prueba real -- factura de un viaje con 2 segmentos (reusar el viaje de prueba de la Tarea 6 o generar uno nuevo), confirmar 2 líneas de tarifa reales + recargo si aplica, TOTAL correcto**

- [ ] **Step 3: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "feat: factura con una linea por segmento de modalidad"
```

---

### Task 9: `costo-en-vivo.js` y las 2 pantallas en vivo reflejan segmentos

**Files:**
- Modify: `app/static/js/costo-en-vivo.js`
- Modify: `app/templates/ciclista/viaje_activo.html`
- Modify: `app/templates/empleado/vigilancia/devoluciones.html`
- Modify: `app/routers/ciclista.py` (pasar `subtotal_segmentos_cerrados` al template de `viaje_activo`)
- Modify: `app/routers/empleado.py` (mismo, por fila, en `devoluciones()`)

**Interfaces:**
- Consumes: `alquileres_repo.total_segmentos_cerrados()` (Task 6).

- [ ] **Step 1: `costoDetallado()` recibe el fijo de segmentos cerrados y replica la MISMA referencia de gracia que `vig_devolver()` (Tarea 7) según la modalidad del segmento abierto -- nunca "simplificado", el número en vivo debe coincidir con lo que se cobrará de verdad**

En `costo-en-vivo.js`, cambiar la firma:
```javascript
function costoDetallado(fechaInicioSegmentoISO, fechaFinISO, precioModalidad, modalidad, subtotalCerrados) {
  const ahora = new Date();
  const inicioSegmento = new Date(fechaInicioSegmentoISO);

  let subtotalSegmentoAbierto;
  if (modalidad === 'hora') {
    const horas = Math.max(0, (ahora - inicioSegmento) / 3600000);
    subtotalSegmentoAbierto = horas * precioModalidad;
  } else {
    subtotalSegmentoAbierto = precioModalidad; // tarifa plana, ya se cobra completa
  }
  const subtotal = subtotalCerrados + subtotalSegmentoAbierto;

  if (!fechaFinISO) {
    // Viaje todavia 'activo' (no reportado) -- la gracia por demora no
    // aplica todavia en ningun caso, igual que antes de este cambio.
    return { subtotal, recargoDemora: 0, enGracia: false, minutosParaRecargo: 0 };
  }

  // Punto de referencia de la gracia -- IDENTICO al que usa
  // vig_devolver() (Tarea 7): 'hora' cuenta desde que se reporto la
  // devolucion (fechaFinISO); 'dia'/'semana' cuentan desde que termina
  // la ventana comprada de ESE segmento, no desde el reporte.
  let referenciaGracia;
  if (modalidad === 'hora') {
    referenciaGracia = new Date(fechaFinISO);
  } else {
    const horasVentana = modalidad === 'dia' ? 24 : 24 * 7;
    referenciaGracia = new Date(inicioSegmento.getTime() + horasVentana * 3600000);
  }

  const minutosEspera = Math.max(0, (ahora - referenciaGracia) / 60000);
  const minutosRecargo = Math.max(0, minutosEspera - MINUTOS_GRACIA_DEMORA);
  return {
    subtotal,
    recargoDemora: (minutosRecargo / 60) * precioModalidad,
    enGracia: minutosEspera < MINUTOS_GRACIA_DEMORA,
    minutosParaRecargo: Math.max(0, MINUTOS_GRACIA_DEMORA - minutosEspera),
  };
}
```

- [ ] **Step 2: `ciclista.py` pasa el precio de la modalidad ACTUAL (no siempre "hora") y el fijo de segmentos cerrados al template de `viaje_activo`**

En la función que renderiza `viaje_activo.html`, reemplazar la resolución de `precio_hora` (que hoy siempre pide modalidad `hora`) por la modalidad real del viaje:
```python
    modalidad_actual = viaje.get("modalidad_actual") or "hora"
    id_categoria = tarifas_repo.categoria_de_bicicleta(viaje.get("bicicleta_codigo", ""))
    resultado_precio = tarifas_repo.precio_modalidad(id_categoria, tipo_membresia, modalidad_actual) if id_categoria else None
    precio_modalidad_actual = resultado_precio[0] if resultado_precio else 0.0
```

Y en el contexto del template:
```python
        precio_hora=precio_modalidad_actual,  # nombre de variable existente en el template, ahora es el precio de la modalidad actual del viaje
        subtotal_segmentos_cerrados=alquileres_repo.total_segmentos_cerrados(viaje_id),
```

En el template, `const PRECIO_MODALIDAD = {{ precio_hora }};` y `const SUBTOTAL_CERRADOS = {{ subtotal_segmentos_cerrados }};`, usados en `costoDetallado(VIAJE.inicio_segmento_actual || VIAJE.fecha_inicio, VIAJE.fecha_fin, PRECIO_MODALIDAD, VIAJE.modalidad_actual || 'hora', SUBTOTAL_CERRADOS)`.

- [ ] **Step 3: Mismo ajuste en `empleado.py:devoluciones()`, por cada fila de `viajes_pendientes` -- reemplaza la línea existente `v["precio_hora"] = _tarifa_hora(...)` (siempre pedía modalidad hora)**

```python
        modalidad_v = v.get("modalidad_actual") or "hora"
        id_categoria_v = tarifas_repo.categoria_de_bicicleta(v.get("bicicleta_codigo", ""))
        resultado_v = tarifas_repo.precio_modalidad(id_categoria_v, tipo_membresia, modalidad_v) if id_categoria_v else None
        v["precio_hora"] = resultado_v[0] if resultado_v else 0.0
        v["subtotal_segmentos_cerrados"] = alquileres_repo.total_segmentos_cerrados(v["id"])
```

Y en `devoluciones.html`, agregar `data-subtotal-cerrados="{{ v.subtotal_segmentos_cerrados }}"` `data-modalidad="{{ v.modalidad_actual or 'hora' }}"` `data-inicio-segmento="{{ v.inicio_segmento_actual or v.fecha_inicio }}"` a la celda `.monto-en-vivo-celda` (junto al `data-precio-hora` que ya existe, que ahora representa el precio de la modalidad actual, no siempre por hora), y actualizar `actualizarMontosEnVivo()` para pasar los 5 argumentos nuevos a `costoDetallado()`.

- [ ] **Step 4: Prueba real -- confirmar visualmente (HTML real, mismo criterio que la sección 70 dado que no hay navegador disponible) que el número en vivo de `viaje_activo.html` y `devoluciones.html` coincide con lo que `vig_devolver()` termina cobrando, para un viaje con 1 y con 2 segmentos**

- [ ] **Step 5: Commit**

```bash
git add app/static/js/costo-en-vivo.js app/templates/ciclista/viaje_activo.html app/templates/empleado/vigilancia/devoluciones.html app/routers/ciclista.py app/routers/empleado.py
git commit -m "feat: vista en vivo refleja segmentos de modalidad cerrados + el segmento abierto actual"
```

---

### Task 10: Migración retroactiva de los viajes reales en curso (Prioridad 2)

**Files:**
- Create: `etl/16_backfill_modalidad_viajes_en_curso.py`

- [ ] **Step 1: Escribir el script, un solo uso, idempotente por construcción (solo toca viajes sin `modalidad_actual` todavía)**

```python
"""
ETL paso 16 (unico uso, NO forma parte del DAG horario): backfillea
modalidad_actual='hora' e inicio_segmento_actual=fecha_inicio para los
viajes reales que ya estaban 'activo'/'pendiente_validacion' antes de
que existieran estos 2 campos (ver
docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md,
Prioridad 2 -- 3 viajes reales confirmados el 16-ago-2026). Sin esto,
vig_devolver() no tendria de donde leer la modalidad al finalizarlos.

Idempotente: solo toca viajes donde modalidad_actual todavia esta
vacio -- correrlo de nuevo no pisa nada.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import filter_literal, get_admin_client  # noqa: E402


def main() -> None:
    pb = get_admin_client()
    viajes = pb.list_records(
        "viajes",
        filter=f'(estado = "activo" || estado = "pendiente_validacion") && modalidad_actual = ""',
        per_page=200,
    ).get("items", [])
    print(f"{len(viajes)} viajes reales sin modalidad_actual, backfilleando...")
    for v in viajes:
        pb.update_record("viajes", v["id"], {
            "modalidad_actual": "hora",
            "inicio_segmento_actual": v.get("fecha_inicio", ""),
        })
        print(f"  {v['id']} ({v.get('bicicleta_codigo')}): modalidad_actual='hora'")
    print("Listo.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Correrlo contra los datos reales**

Run: `python etl/16_backfill_modalidad_viajes_en_curso.py`
Expected: lista los viajes reales encontrados (3 al momento de escribir este plan, puede haber cambiado) con su `modalidad_actual='hora'` aplicado.

- [ ] **Step 3: Confirmar contra PocketBase real que ya no quedan viajes activos sin `modalidad_actual`**

```bash
curl -s -G "http://127.0.0.1:8090/api/collections/viajes/records" --data-urlencode "filter=(estado='activo'||estado='pendiente_validacion')&&modalidad_actual=''" -H "Authorization: $PB_TOKEN" | python -c "import sys,json;print(json.load(sys.stdin)['totalItems'])"
```
Expected: `0`

- [ ] **Step 4: Confirmar que uno de esos viajes reales se puede finalizar sin errores tras el backfill (con Vigilancia real, NO cancelar el viaje real de Washington -- solo confirmar que `vig_devolver()` no truena si se probara; si no se puede probar sin afectar un viaje real, dejar esta verificación como pendiente explícito para cuando ese viaje se cierre naturalmente)**

- [ ] **Step 5: Commit**

```bash
git add etl/16_backfill_modalidad_viajes_en_curso.py
git commit -m "feat: backfill retroactivo de modalidad_actual para viajes reales en curso"
```

---

### Task 11: Eliminar la colección vieja de PocketBase `tarifas`

**Files:**
- Create: `etl/17_eliminar_tarifas_pocketbase.py`

**Interfaces:**
- Consumes: confirma que Tasks 3-4 ya migraron los 4 usos reales encontrados (`ciclista.py:295`, `empleado.py:53`, `gerente.py:1554`, `ciclista.py:492`).

- [ ] **Step 1: Grep final de todo `app/` -- confirmar cero referencias vivas**

```bash
grep -rn 'list_records("tarifas"\|get_record("tarifas"' app/ --include="*.py"
```
Expected: sin resultados.

- [ ] **Step 2: Escribir el script de borrado, un solo uso**

```python
"""
ETL paso 17 (unico uso, NO forma parte del DAG horario): elimina la
coleccion vieja de PocketBase 'tarifas' (tipo_bicicleta/tipo_usuario/
precio_hora, sin categoria ni dia/semana) -- reemplazada por completo
por urbanbike_operativa.tarifas (ClickHouse), ver
docs/superpowers/specs/2026-08-16-modalidad-tarifa-real-design.md.

Correr SOLO despues de confirmar (grep real de app/) que ningun codigo
vivo la referencia -- ver Task 11, Step 1 del plan.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app.db.pocketbase import get_admin_client  # noqa: E402


def main() -> None:
    pb = get_admin_client()
    existentes = pb._get("/api/collections", params={"perPage": 200}).get("items", [])
    coleccion = next((c for c in existentes if c["name"] == "tarifas"), None)
    if not coleccion:
        print("tarifas: ya no existe, sin cambios.")
        return
    pb._session.delete(f"{pb.base_url}/api/collections/{coleccion['id']}").raise_for_status()
    print("tarifas: eliminada.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Correrlo**

Run: `python etl/17_eliminar_tarifas_pocketbase.py`
Expected: `tarifas: eliminada.`

- [ ] **Step 4: Prueba real completa de regresión -- servidor real, confirmar que reservar/finalizar/cambiar modalidad/validar con Vigilancia siguen funcionando de punta a punta sin esa colección**

- [ ] **Step 5: Commit**

```bash
git add etl/17_eliminar_tarifas_pocketbase.py
git commit -m "chore: eliminar coleccion vieja de PocketBase tarifas, reemplazada por ClickHouse"
```

---

## Documentación final (fuera de las tareas de código)

Al cerrar todas las tareas: agregar una sección nueva a `docs/HOJA_DE_RUTA.md` documentando el trabajo real hecho (mismo criterio de honestidad de toda la hoja de ruta), incluyendo qué se probó con datos reales en cada tarea y qué limpieza se hizo. No es parte de las tareas de código de arriba porque se escribe al final, con el resultado real completo, no tarea por tarea.
