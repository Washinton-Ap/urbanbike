# Fase 1 — Validaciones, exportación condicionada, cierre de sesión forzado

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar los puntos 1, 5 y 6 de `docs/Requerimientos_Mejoras_UrbanBike.md`: validaciones de formularios (tarjeta con Luhn, fecha de caducidad de tarjeta al registrar membresía, campos numéricos), exportación PDF/Excel condicionada a que el conjunto de datos no esté vacío, y cierre de sesión forzado cuando el admin elimina una cuenta.

**Architecture:** Cambios quirúrgicos y locales, siguiendo los patrones ya existentes en cada archivo (funciones `_privadas` a nivel de módulo, `_flash()`/`request.session["flash"]`, sin abstracciones nuevas tipo `validators.py` compartido — el proyecto ya valida así, por módulo). La exportación condicionada se centraliza en `app/reportes/comun.py` (una excepción) más un exception handler en `main.py`, porque ahí conviven ~25 endpoints de exportación en 4 routers distintos y es el único punto que los toca a todos sin editar cada uno.

**Tech Stack:** FastAPI, Jinja2, PocketBase (vía `PocketBaseClient`), ClickHouse (vía `app.db.clickhouse`). Sin test runner instalado para `app/` (no hay pytest en `app/requirements.txt`) — la verificación de cada tarea es manual, arrancando `uvicorn app.main:app --reload` y probando con curl o el navegador.

**Spec:** `docs/Requerimientos_Mejoras_UrbanBike.md` (secciones 1, 5, 6 — "Orden de implementación sugerido", fase 1).

## Global Constraints

- No tocar el flujo de negocio de alquiler/devolución/pagos (eso es fase 3).
- No introducir un módulo `validators.py` compartido: seguir el patrón existente de funciones `_privadas` locales por router (ver `_luhn_valido`/`_marca_tarjeta` en `ciclista.py`, `_validar_estacion_form` en `gerente.py`, `_CEDULA_PATTERN` en `auth.py`).
- Mensajes de error siempre en español, mismo tono que los ya existentes (`_flash(request, url, "error", "mensaje")` o `request.session["flash"] = {...}`).
- No añadir dependencias nuevas a `requirements.txt`.
- Los ~25 call sites de `generar_excel_reporte`/`generar_pdf_reporte` en `admin.py`, `gerente.py`, `empleado.py`, `ciclista.py` NO se tocan individualmente — el fix vive en `comun.py`/`excel.py`/`pdf.py`/`main.py`.

---

### Task 1: Exportación condicionada a dataset no vacío (punto 5)

**Files:**
- Modify: `app/reportes/comun.py`
- Modify: `app/reportes/excel.py`
- Modify: `app/reportes/pdf.py`
- Modify: `app/main.py`

**Interfaces:**
- Produces: `ReporteVacioError(Exception)` en `app.reportes.comun` — se lanza desde `generar_excel_reporte()` y `generar_pdf_reporte()` cuando `filas` está vacío. `main.py` la captura con un exception handler global.

- [ ] **Step 1: Añadir la excepción compartida**

En `app/reportes/comun.py`, después de los imports y antes de `BLUE = "1E86BD"`:

```python
class ReporteVacioError(Exception):
    """Se lanza cuando no hay filas que exportar -- ver
    generar_excel_reporte()/generar_pdf_reporte(). Capturada centralmente
    en app/main.py para redirigir con un flash en vez de generar un
    archivo en blanco (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 5)."""
```

- [ ] **Step 2: Lanzarla en `generar_excel_reporte`**

En `app/reportes/excel.py`, importar `ReporteVacioError` junto a los demás nombres de `comun`:

```python
from app.reportes.comun import ALT, BLUE, GRID, MUTED, WHITE, ColumnaReporte, ReporteVacioError
```

Al inicio del cuerpo de `generar_excel_reporte` (primera línea después del docstring, antes de `wb = openpyxl.Workbook()`):

```python
    if not filas:
        raise ReporteVacioError("No hay datos para exportar.")

    wb = openpyxl.Workbook()
```

- [ ] **Step 3: Lanzarla en `generar_pdf_reporte`**

En `app/reportes/pdf.py`, actualizar el import:

```python
from app.reportes.comun import ALT, BLUE, GRID, MUTED, ColumnaReporte, ReporteVacioError, formatear_valor
```

Al inicio del cuerpo de `generar_pdf_reporte` (primera línea después del docstring, antes de `_registrar_fuentes()`):

```python
    if not filas:
        raise ReporteVacioError("No hay datos para exportar.")

    _registrar_fuentes()
```

- [ ] **Step 4: Exception handler global en `main.py`**

En `app/main.py`, junto al import existente de `PermisoDenegadoError`:

```python
from app.middleware.permisos import PermisoDenegadoError
from app.reportes.comun import ReporteVacioError
```

Después del handler existente `permiso_denegado_handler` (antes de `app.include_router(auth_router.router)`):

```python
@app.exception_handler(ReporteVacioError)
async def reporte_vacio_handler(request: Request, exc: ReporteVacioError):
    """Mismo patrón que permiso_denegado_handler: flash + redirect en vez
    de dejar que el StreamingResponse se genere vacío. El redirect vuelve
    a la página desde la que se pidió el export (Referer) -- solo si es
    del mismo origen, para no abrir un open-redirect con un Referer
    falsificado."""
    import urllib.parse
    request.session["flash"] = {"type": "error", "msg": "No hay datos para exportar. El reporte está vacío."}
    referer = request.headers.get("referer", "")
    destino = "/dashboard"
    if referer:
        partes = urllib.parse.urlparse(referer)
        if partes.netloc == request.url.netloc:
            destino = partes.path or "/dashboard"
            if partes.query:
                destino += f"?{partes.query}"
    return RedirectResponse(destino, status_code=302)
```

- [ ] **Step 5: Verificación manual**

Arrancar el server: `uvicorn app.main:app --reload` (requiere PocketBase/ClickHouse levantados vía `docker compose up -d`, y sesión de admin logueada en el navegador).

Casos a probar a mano:
1. Un módulo con datos (ej. `/admin/usuarios/pdf` con usuarios existentes) → descarga el archivo normalmente, sin cambios de comportamiento.
2. Forzar un dataset vacío — el más simple es `/admin/auditoria/pdf?accion=zzz_no_existe` (filtro que no matchea nada) → debe redirigir de vuelta a `/admin/auditoria` con flash de error "No hay datos para exportar. El reporte está vacío.", **no** debe descargar ningún archivo.
3. Repetir el caso 2 con `/admin/auditoria/excel?accion=zzz_no_existe`.

- [ ] **Step 6: Commit**

```bash
git add app/reportes/comun.py app/reportes/excel.py app/reportes/pdf.py app/main.py
git commit -m "feat: rechazar exportacion PDF/Excel cuando el dataset esta vacio"
```

---

### Task 2: Validación de campos numéricos en admin.py (punto 1)

**Files:**
- Modify: `app/routers/admin.py`

**Interfaces:**
- Consumes: nada nuevo de otros módulos.
- Produces: nada consumido por otras tareas.

Bugs reales encontrados en la exploración:
- `usuarios_crear`/`usuarios_editar`: la cédula se guarda tal cual llega, sin validar que sean 10 dígitos (a diferencia de `auth.py:registro_post`, que sí lo hace).
- `estaciones_crear`/`estaciones_editar`: `capacidad`/`latitud`/`longitud` usan `try: payload["x"] = int(...)/float(...) except ValueError: pass` — un valor no numérico se **descarta en silencio** en vez de rechazar la acción (viola el punto 1: "Rechazar caracteres no numéricos... en todo campo declarado como número").
- `tarifas_crear`: `precio_hora` se convierte con `float(precio_hora)` sin try/except — un valor inválido produce un `ValueError` sin capturar que cae en el `except Exception as e: ... str(e)` genérico, mostrando un mensaje de error de Python en vez de uno claro.
- `tarifas_editar`: mismo patrón de silenciar con `try/except: pass` que `estaciones_editar`.

- [ ] **Step 1: Validar cédula en `usuarios_crear`**

En `app/routers/admin.py`, después de `_ACCION_TIPO`/`_MODULO_PLURAL` (línea ~44), añadir constante reutilizada por los dos endpoints de usuarios (mismo patrón que `auth.py`):

```python
import re

_CEDULA_PATTERN = re.compile(r"^[0-9]{10}$")
```

(añadir `import re` junto a los imports existentes al inicio del archivo, junto a `import json`).

En `usuarios_crear`, antes de `payload: dict = {...}` (dentro del `try`, justo después de la validación de avatar):

```python
    if cedula and not _CEDULA_PATTERN.match(cedula.strip()):
        return _flash(request, "/admin/usuarios", "error", "La cédula debe tener exactamente 10 dígitos numéricos.")
```

- [ ] **Step 2: Validar cédula en `usuarios_editar`**

Mismo chequeo, antes del `try:` de `usuarios_editar`:

```python
    if cedula and not _CEDULA_PATTERN.match(cedula.strip()):
        return _flash(request, next, "error", "La cédula debe tener exactamente 10 dígitos numéricos.")
```

- [ ] **Step 3: Validar capacidad/latitud/longitud en `estaciones_crear`**

Reemplazar el cuerpo del `try` de `estaciones_crear` (líneas 545-562 aprox.) — quitar los `try/except ValueError: pass` silenciosos y validar antes de construir el payload:

```python
@router.post("/estaciones/crear", dependencies=[Depends(requiere_permiso("estaciones:crear"))])
def estaciones_crear(
    request: Request,
    nombre: str = Form(...),
    capacidad: str = Form(""),
    latitud: str = Form(""),
    longitud: str = Form(""),
    activa: str = Form("true"),
):
    if capacidad and not capacidad.strip().isdigit():
        return _flash(request, "/admin/estaciones", "error", "La capacidad debe ser un número entero.")
    for campo, valor in (("latitud", latitud), ("longitud", longitud)):
        if valor:
            try:
                float(valor)
            except ValueError:
                return _flash(request, "/admin/estaciones", "error", f"La {campo} debe ser un número.")
    try:
        pb = _pb()
        codigo = _siguiente_codigo_estacion(pb)
        payload: dict = {"nombre": nombre, "codigo": codigo, "activa": activa == "true"}
        if capacidad:
            payload["capacidad"] = int(capacidad)
        if latitud:
            payload["latitud"] = float(latitud)
        if longitud:
            payload["longitud"] = float(longitud)
        pb.create_record("estaciones", payload)
        _log(request, "Crear estación", f"Estación creada: {nombre} ({codigo})")
        return _flash(request, "/admin/estaciones", "success", f"Estación {codigo} creada.")
    except Exception as e:
        return _flash(request, "/admin/estaciones", "error", str(e))
```

- [ ] **Step 4: Mismo fix en `estaciones_editar`**

```python
@router.post("/estaciones/{eid}/editar", dependencies=[Depends(requiere_permiso("estaciones:actualizar"))])
def estaciones_editar(
    request: Request, eid: str,
    nombre: str = Form(""), codigo: str = Form(""),
    capacidad: str = Form(""), latitud: str = Form(""),
    longitud: str = Form(""), activa: str = Form("true"),
):
    if capacidad and not capacidad.strip().isdigit():
        return _flash(request, "/admin/estaciones", "error", "La capacidad debe ser un número entero.")
    for campo, valor in (("latitud", latitud), ("longitud", longitud)):
        if valor:
            try:
                float(valor)
            except ValueError:
                return _flash(request, "/admin/estaciones", "error", f"La {campo} debe ser un número.")
    try:
        payload: dict = {"activa": activa == "true"}
        if nombre: payload["nombre"] = nombre
        if codigo: payload["codigo"] = codigo
        if capacidad:
            payload["capacidad"] = int(capacidad)
        if latitud:
            payload["latitud"] = float(latitud)
        if longitud:
            payload["longitud"] = float(longitud)
        _pb().update_record("estaciones", eid, payload)
        _log(request, "Editar estación", f"Estación actualizada: {nombre or eid}")
        return _flash(request, "/admin/estaciones", "success", "Estación actualizada.")
    except Exception as e:
        return _flash(request, "/admin/estaciones", "error", str(e))
```

- [ ] **Step 5: Validar `precio_hora` en `tarifas_crear` y `tarifas_editar`**

En `tarifas_crear`, antes del `try:`:

```python
    try:
        precio = float(precio_hora)
    except ValueError:
        return _flash(request, "/admin/tarifas", "error", "El precio por hora debe ser un número.")
    if precio < 0:
        return _flash(request, "/admin/tarifas", "error", "El precio por hora no puede ser negativo.")
    try:
        _pb().create_record("tarifas", {
            "tipo_bicicleta": tipo_bicicleta,
            "tipo_usuario":   tipo_usuario,
            "precio_hora":    precio,
            "activa":         activa == "true",
        })
        _log(request, "Crear tarifa", f"Tarifa creada: {tipo_bicicleta} / {tipo_usuario}")
        return _flash(request, "/admin/tarifas", "success", "Tarifa creada.")
    except Exception as e:
        return _flash(request, "/admin/tarifas", "error", str(e))
```

En `tarifas_editar`, reemplazar el `try/except ValueError: pass` silencioso:

```python
    if precio_hora:
        try:
            precio_val = float(precio_hora)
        except ValueError:
            return _flash(request, "/admin/tarifas", "error", "El precio por hora debe ser un número.")
        if precio_val < 0:
            return _flash(request, "/admin/tarifas", "error", "El precio por hora no puede ser negativo.")
        payload["precio_hora"] = precio_val
```

(esta validación va **antes** del `try:` que llama a `_pb().update_record`, igual que en `tarifas_crear`; el resto del cuerpo de `tarifas_editar` no cambia).

- [ ] **Step 6: Verificación manual**

Con el server corriendo y sesión de admin:
1. `POST /admin/usuarios/crear` con `cedula=abc` → flash de error, usuario NO creado.
2. `POST /admin/estaciones/crear` con `capacidad=diez` → flash de error, estación NO creada (antes: se creaba sin capacidad, en silencio).
3. `POST /admin/estaciones/crear` con `latitud=norte` → flash de error.
4. `POST /admin/tarifas/crear` con `precio_hora=gratis` → flash "El precio por hora debe ser un número." (antes: página de error genérica de Python).
5. Confirmar que los casos válidos (cédula real de 10 dígitos, capacidad/latitud/longitud/precio numéricos) siguen funcionando exactamente igual que antes.

- [ ] **Step 7: Commit**

```bash
git add app/routers/admin.py
git commit -m "fix: validar cedula, capacidad/latitud/longitud y precio_hora en admin"
```

---

### Task 3: Validación de tarjeta (Luhn + longitud) y fecha de caducidad al registrar membresía (punto 1)

**Files:**
- Modify: `app/routers/ciclista.py`

**Interfaces:**
- Consumes: `_luhn_valido()` y `_marca_tarjeta()`, ya definidas en el mismo archivo (líneas ~1067 y ~1085) — se reutilizan en `confirmar_pago` sin cambiar su firma.
- Produces: `_expiracion_valida(mes: str, anio: str) -> tuple[bool, int, int]` y `_margen_minimo_expiracion() -> tuple[int, int]`, nuevas funciones en este archivo, usadas por `membresia_activar` (y `_expiracion_valida` también por `confirmar_pago`).

Bug real encontrado: `confirmar_pago` (rama `metodo_pago == "tarjeta"`, línea ~634) solo exige `len(digitos) >= 4` — un número como `"0000000000"` (10 ceros) pasa esa validación sin problema. `_luhn_valido()` ya existe en el mismo archivo (usada hoy solo por `membresia_activar`) y ya exige 12-19 dígitos + algoritmo de Luhn; el requerimiento pide 13-19 dígitos exactos, así que también se ajusta el rango.

`membresia_activar` no valida que la fecha de caducidad tenga al menos 1 mes de margen desde hoy (solo valida que mes/año no vengan vacíos) — el requerimiento pide explícitamente rechazar la suscripción si la tarjeta caduca antes de ese margen.

- [ ] **Step 1: Añadir `date` al import de datetime**

En `app/routers/ciclista.py` línea 4, cambiar:

```python
from datetime import datetime, timezone
```

por:

```python
from datetime import date, datetime, timezone
```

- [ ] **Step 2: Ajustar el rango de `_luhn_valido` a 13-19 dígitos**

En `_luhn_valido` (línea ~1073), cambiar:

```python
    if not (12 <= len(digitos) <= 19):
        return False
```

por:

```python
    if not (13 <= len(digitos) <= 19):
        return False
```

- [ ] **Step 3: Añadir `_expiracion_valida` y `_margen_minimo_expiracion`**

Justo después de `_marca_tarjeta` (antes de la sección `# ── Membresia`, o inmediatamente después de esa función — usar el mismo bloque donde viven `_luhn_valido`/`_marca_tarjeta`):

```python
def _expiracion_valida(mes: str, anio: str) -> tuple[bool, int, int]:
    """Valida que mes/anio sean un mes de calendario real (1-12) y un
    anio de 4 digitos razonable. Devuelve (ok, mes_int, anio_int) --
    mes_int/anio_int solo son validos si ok es True."""
    if not mes.isdigit() or not anio.isdigit():
        return False, 0, 0
    m, a = int(mes), int(anio)
    if not (1 <= m <= 12) or not (2000 <= a <= 2999):
        return False, 0, 0
    return True, m, a


def _margen_minimo_expiracion() -> tuple[int, int]:
    """(anio, mes) del primer mes de calendario que cumple el margen
    minimo de 1 mes desde hoy -- una tarjeta cuyo (anio, mes) de
    caducidad sea anterior a este par no alcanza para registrar una
    membresia (ver docs/Requerimientos_Mejoras_UrbanBike.md, punto 1)."""
    hoy = date.today()
    total_meses = hoy.year * 12 + (hoy.month - 1) + 1
    return total_meses // 12, total_meses % 12 + 1
```

- [ ] **Step 4: Usar `_luhn_valido` en `confirmar_pago` (rama tarjeta)**

Reemplazar el bloque actual (línea ~634-654):

```python
        # ── Tarjeta (simulado) ────────────────────────────────────────────────
        if metodo_pago == "tarjeta":
            digitos = "".join(ch for ch in numero_tarjeta if ch.isdigit())
            if len(digitos) < 4 or not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
                request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            ultimos4 = digitos[-4:]
```

por:

```python
        # ── Tarjeta (simulado) ────────────────────────────────────────────────
        if metodo_pago == "tarjeta":
            if not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
                request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if not _luhn_valido(numero_tarjeta):
                request.session["flash"] = {"type": "error", "msg":
                    "El número de tarjeta no es válido. Prueba con 4242 4242 4242 4242, la tarjeta de pruebas estándar."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            if not _expiracion_valida(mes_expiracion, anio_expiracion)[0]:
                request.session["flash"] = {"type": "error", "msg": "La fecha de expiración de la tarjeta no es válida."}
                return RedirectResponse(f"/ciclista/pago/{pago_id}", status_code=302)
            digitos = "".join(ch for ch in numero_tarjeta if ch.isdigit())
            ultimos4 = digitos[-4:]
```

(el resto de la rama, desde `pb.update_record("pagos", ...)`, no cambia).

- [ ] **Step 5: Aplicar el margen mínimo de 1 mes en `membresia_activar`**

Reemplazar el bloque de validación actual (línea ~1220-1226):

```python
    if not _luhn_valido(numero_tarjeta):
        request.session["flash"] = {"type": "error", "msg":
            "El número de tarjeta no es válido (falló la verificación de formato). Prueba con 4242 4242 4242 4242, la tarjeta de pruebas estándar."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
    if not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
        request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta simulada."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
```

por:

```python
    if not _luhn_valido(numero_tarjeta):
        request.session["flash"] = {"type": "error", "msg":
            "El número de tarjeta no es válido (falló la verificación de formato). Prueba con 4242 4242 4242 4242, la tarjeta de pruebas estándar."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
    if not nombre_titular.strip() or not mes_expiracion or not anio_expiracion:
        request.session["flash"] = {"type": "error", "msg": "Completa todos los datos de la tarjeta simulada."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)

    exp_ok, mes_exp, anio_exp = _expiracion_valida(mes_expiracion, anio_expiracion)
    if not exp_ok:
        request.session["flash"] = {"type": "error", "msg": "La fecha de expiración de la tarjeta no es válida."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
    anio_margen, mes_margen = _margen_minimo_expiracion()
    if (anio_exp, mes_exp) < (anio_margen, mes_margen):
        request.session["flash"] = {"type": "error", "msg":
            "La tarjeta debe tener al menos 1 mes de vigencia desde hoy para poder suscribirte."}
        return RedirectResponse("/ciclista/membresia/pagar", status_code=302)
```

- [ ] **Step 6: Verificación manual**

Con el server corriendo y sesión de ciclista:
1. En `/ciclista/pago/{id}` (un pago pendiente real), pagar con tarjeta `0000000000` (10 ceros) → debe rechazar con "El número de tarjeta no es válido..." (antes: se aceptaba).
2. Pagar con `4242424242424242` (16 dígitos, Luhn válido) → debe aceptar igual que antes.
3. En `/ciclista/membresia/pagar`, elegir mes/año de expiración que caiga **antes** del margen de 1 mes (ej. si hoy es 15/08/2026, elegir 08/2026 si el select lo permitiera, o el mes actual) → debe rechazar con "La tarjeta debe tener al menos 1 mes de vigencia...".
4. Elegir un mes/año con margen suficiente (ej. 12/2027) → debe activar la membresía normalmente.

- [ ] **Step 7: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "fix: validar Luhn en pago con tarjeta y margen minimo de caducidad al registrar membresia"
```

---

### Task 4: Cierre de sesión forzado al eliminar una cuenta (punto 6)

**Files:**
- Modify: `app/middleware/auth.py`
- Modify: `app/routers/admin.py`

**Interfaces:**
- Produces: `revocar_sesion(user_id: str) -> None` en `app.middleware.auth`, llamada desde `admin.py:usuarios_eliminar`.

Contexto real: las sesiones de este proyecto son cookies firmadas del lado del cliente (`SessionMiddleware` de Starlette, `ub_session`), no hay sesión guardada del lado del servidor -- por eso "invalidar el token" no puede ser un simple borrado en una tabla de sesiones. La app corre como un solo proceso (`uvicorn app.main:app --reload`, sin `workers=N` en ningún lado del repo), así que un set en memoria a nivel de módulo es suficiente y no necesita Redis ni una colección nueva en PocketBase.

- [ ] **Step 1: Set de revocación + función pública en `app/middleware/auth.py`**

Después de `HISTORIAL_BLOQUEADO_PATH = "/ciclista/historial"` (línea ~49), añadir:

```python
# Revocacion de sesion en memoria de proceso (ver docs/Requerimientos_Mejoras_UrbanBike.md,
# punto 6): las sesiones son cookies firmadas del lado del cliente (SessionMiddleware),
# sin tabla de sesiones en el servidor -- este set es el unico lugar donde "eliminar una
# cuenta" puede dejar rastro para que la siguiente request de ese usuario deje de pasar,
# aunque su cookie de sesion siga siendo valida. Vive en memoria porque la app corre en
# un solo proceso (sin workers=N en ningun lado del repo); si eso cambia, este mecanismo
# necesita moverse a un almacen compartido.
_SESIONES_REVOCADAS: set[str] = set()


def revocar_sesion(user_id: str) -> None:
    """Fuerza que la proxima request de este usuario (si tenia sesion activa)
    sea tratada como no autenticada. Llamada por admin.py al eliminar una cuenta."""
    if user_id:
        _SESIONES_REVOCADAS.add(user_id)
```

- [ ] **Step 2: Chequear el set en `AuthMiddleware.dispatch`**

En el método `dispatch`, justo después de `user = request.session.get("user")` y antes del `if not user:` (línea ~59-60):

```python
        user = request.session.get("user")
        if user and user.get("id") in _SESIONES_REVOCADAS:
            request.session.clear()
            user = None
        if not user:
```

- [ ] **Step 3: Llamar `revocar_sesion` al eliminar el usuario**

En `app/routers/admin.py`, importar la función junto a los demás imports de `app.middleware`:

```python
from app.middleware.auth import revocar_sesion
from app.middleware.permisos import requiere_permiso
```

En `usuarios_eliminar` (línea ~267-274), después de borrar el registro:

```python
@router.post("/usuarios/{uid}/eliminar")
def usuarios_eliminar(request: Request, uid: str):
    try:
        _pb().delete_record("users", uid)
        revocar_sesion(uid)
        _log(request, "Eliminar usuario", f"Usuario eliminado (id: {uid})")
        return _flash(request, "/admin/usuarios", "success", "Usuario eliminado.")
    except Exception as e:
        return _flash(request, "/admin/usuarios", "error", str(e))
```

- [ ] **Step 4: Verificación manual**

1. Abrir dos sesiones de navegador distintas (o una normal + una de incógnito): una como admin, otra logueada como un ciclista de prueba (crear uno nuevo si hace falta).
2. Con la sesión del ciclista activa y navegando con normalidad, desde la sesión de admin ir a `/admin/usuarios` y eliminar exactamente esa cuenta.
3. En la sesión del ciclista, hacer clic en cualquier link interno (ej. ir a `/ciclista/dashboard`) → debe redirigir a `/auth/login`, no debe poder seguir navegando como si la sesión siguiera activa.
4. Confirmar que el flujo normal de logout (`/auth/logout`) sigue funcionando igual que antes para cuentas que no fueron eliminadas.

- [ ] **Step 5: Commit**

```bash
git add app/middleware/auth.py app/routers/admin.py
git commit -m "feat: forzar cierre de sesion al eliminar una cuenta desde admin"
```

---

### Task 5 (adición pedida por el usuario): Cerrar sesión de un usuario conectado sin eliminar su cuenta

**Files:**
- Modify: `app/middleware/auth.py`
- Modify: `app/routers/auth.py`
- Modify: `app/routers/admin.py`
- Modify: `app/templates/admin/usuarios.html`

El admin pidió una acción independiente en el panel para cerrar la sesión de cualquier usuario conectado sin eliminar su cuenta, reutilizando `_SESIONES_REVOCADAS`. Encontrado durante el diseño: el set de Task 4 nunca se vaciaba, así que una vez revocado un usuario quedaba bloqueado **para siempre** (cada login exitoso volvía a caer en el mismo chequeo). Eso es aceptable para "eliminar cuenta" (nunca debería volver a entrar) pero rompe "cerrar sesión" (debe poder loguearse de nuevo con normalidad). Fix: `limpiar_revocacion(user_id)` nueva, llamada en cada login exitoso (`auth.py:login()`), que saca al usuario del set. La entrada no se borra sola al consumirse en el middleware — se queda hasta el próximo login exitoso, para tumbar todas las sesiones activas del usuario (varios dispositivos), no solo la primera que haga una request.

- [x] Añadir `limpiar_revocacion()` en `app/middleware/auth.py` y actualizar el comentario del set.
- [x] Llamar `limpiar_revocacion(user["id"])` en `auth.py:login()`, antes de `request.session["user"] = user`.
- [x] Nuevo endpoint `POST /admin/usuarios/{uid}/cerrar-sesion` en `admin.py` (llama `revocar_sesion(uid)` sin borrar el registro).
- [x] Botón "Cerrar sesión" en `admin/usuarios.html`, junto a Activar/Desactivar.
- [x] Verificado: compila, la app importa (213 rutas), y `revocar_sesion`/`limpiar_revocacion` se comportan como se espera en una prueba de humo directa.

Pendiente de verificación manual (dos sesiones de navegador, una admin + una del usuario objetivo): confirmar que "Cerrar sesión" tumba la sesión activa del usuario y que ese mismo usuario puede loguearse de nuevo sin quedar bloqueado.
