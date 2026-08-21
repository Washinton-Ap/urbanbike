# Fix: Reservas Concurrentes Bypasean la Exclusividad de una Bicicleta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el hueco real que permite que una misma bicicleta física quede con dos (o más)
"viajes" activos simultáneos, violando FR-005 de la especificación formal.

**Architecture:** `_crear_viaje()` (compartida por `reservar()` y `reservar_grupo()` en
`app/routers/ciclista.py`) hoy escribe `bicicletas.estado = "en_uso"` sin comprobar antes el
estado real de esa bicicleta en PocketBase -- no hay ni siquiera un check-then-act, es una
escritura incondicional. Se agrega una relectura del estado real justo antes de crear el viaje,
envuelta en un lock de proceso que serializa la sección crítica completa (leer estado real →
crear viaje → marcar en_uso) para que dos solicitudes casi simultáneas no puedan pasar ambas la
validación antes de que cualquiera escriba.

**Tech Stack:** Python 3.11 / FastAPI, `threading.Lock` (el cliente PocketBase
(`app/db/pocketbase.py`) usa `requests` síncrono, sin `await` -- confirmado leyendo el archivo),
PocketBase 0.39 vía REST (sin soporte nativo de update condicional/optimistic concurrency, así
que la atomicidad real se logra en la capa de aplicación, no en la de PocketBase).

**Spec:** `specs/001-operaciones-alquiler-bicicletas/spec.md` -- **FR-005**: "El sistema DEBE
asignar una bicicleta en exclusiva a un único ciclista en el momento de reservarla, cambiando su
estado a 'en uso' de inmediato, impidiendo que cualquier otro ciclista la reserve simultáneamente
(CU-O02; confirmado contra `app/routers/ciclista.py`)." Ese "confirmado contra..." describe la
INTENCIÓN del código, no su comportamiento real verificado -- este plan es la primera
verificación real de FR-005 contra el sistema corriendo, y encontró que el requisito no se
cumplía (ver Deuda conocida #2 en `docs/HOJA_DE_RUTA.md` sección 78, ya lo señalaba como
condición de carrera preexistente, sin corregir).

## Global Constraints

- No introducir dependencias nuevas -- `threading` es de librería estándar.
- No tocar el desfase ClickHouse/PocketBase (punto 14) -- eso sigue fuera de alcance, ya
  documentado.
- La verificación es E2E real contra PocketBase/ClickHouse reales corriendo en Docker (mismo
  criterio que el resto de `docs/HOJA_DE_RUTA.md` -- "sin mockear la base de datos"), no tests
  unitarios con mocks. El proyecto no tiene suite pytest para `app/` (solo `etl/test_app.py`,
  de otro subsistema) -- no se introduce una a mitad de un fix de bug.
- Cualquier bicicleta/viaje de prueba real creado durante la verificación se limpia antes de
  cerrar la tarea (mismo criterio aplicado hoy mismo en `docs/HOJA_DE_RUTA.md` sección 79).
- No commitear en `main` -- este trabajo vive en la rama
  `worktree-fix-reservas-concurrentes-exclusividad`, aislada en su propio worktree.

---

### Task 1: Chequeo real de disponibilidad + lock en `_crear_viaje()`

**Files:**
- Modify: `app/routers/ciclista.py:1-24` (import de `threading`)
- Modify: `app/routers/ciclista.py:539-570` (`_crear_viaje()`)

**Interfaces:**
- Consumes: `pb.get_record(collection: str, record_id: str) -> dict` (ya existe en
  `app/db/pocketbase.py`, usado en otras rutas de este mismo archivo, p.ej.
  `bicicleta_detalle()`).
- Produces: `_crear_viaje(...)` sigue con la misma firma y valor de retorno (`dict` del viaje
  creado) -- `reservar()` y `reservar_grupo()` (los únicos 2 llamadores) no cambian. Si la
  bicicleta ya no está disponible, `_crear_viaje()` ahora lanza `ValueError` con un mensaje
  para el ciclista ANTES de crear ningún registro -- ambos llamadores ya envuelven la llamada
  en `try/except Exception`, así que el mensaje llega tal cual al flash de error existente sin
  cambios adicionales.

- [ ] **Step 1: Agregar el import de `threading` y el lock a nivel de módulo**

En `app/routers/ciclista.py`, después de los imports existentes (línea 22, antes de
`router = APIRouter(...)`):

```python
import threading
```

(agregar junto a `import uuid` en el bloque de imports de arriba del archivo, línea 4).

Justo antes de `def _ctx(request: Request, **extra) -> dict:` (línea 27), agregar:

```python
# Lock de proceso (no distribuido -- ver Tech Stack del plan de este fix) que serializa la
# seccion critica de _crear_viaje(): releer el estado real de la bicicleta, crear el viaje, y
# marcarla en_uso. Sin esto, dos solicitudes casi simultaneas para la MISMA bicicleta podian
# pasar ambas la lectura antes de que cualquiera escribiera, dejando 2 viajes "activo" sobre la
# misma bici fisica (bug real, FR-005 de specs/001-operaciones-alquiler-bicicletas/spec.md).
# Un solo lock global (no uno por bicicleta_id) es intencional: la escala real de reservas
# simultaneas de este sistema es minima, y un lock por bici agrega gestion de ciclo de vida
# (cuando liberar/limpiar cada lock) sin beneficio real a este volumen.
_lock_disponibilidad_bicicleta = threading.Lock()
```

- [ ] **Step 2: Agregar la relectura real + el lock dentro de `_crear_viaje()`**

Reemplazar el cuerpo actual de `_crear_viaje()` (líneas 550-570):

```python
def _crear_viaje(
    pb, user: dict, user_id: str, bicicleta_id: str, bicicleta_codigo: str,
    estacion_inicio_id: str, estacion_inicio_nombre: str, modalidad: str,
    lat: float, lng: float, codigo_valido: dict | None, grupo_reserva_id: str = "",
) -> dict:
    """Crea UN viaje real + marca la bicicleta en_uso -- la auditoria la
    registra cada LLAMADOR (reservar()/reservar_grupo()), no esta funcion.
    Logica compartida entre reservar() (una bicicleta) y reservar_grupo()
    (varias a la vez, Tarea C2 del plan de factura unica). El codigo de
    descuento, si viene, solo se marca usado por el LLAMADOR (una sola vez
    por reserva, nunca una vez por bicicleta del grupo).

    FR-005 (specs/001-operaciones-alquiler-bicicletas/spec.md): antes de
    este fix, esta funcion escribia bicicletas.estado="en_uso" sin
    comprobar el estado real -- un POST directo a /ciclista/reservar con
    el id de una bici ya en_uso tenia exito igual, sin necesitar
    concurrencia real. Ahora relee el estado real justo antes de escribir,
    dentro del lock de modulo (ver _lock_disponibilidad_bicicleta), asi
    dos solicitudes casi simultaneas no pueden pasar ambas la
    verificacion antes de que cualquiera marque la bici en_uso."""
    with _lock_disponibilidad_bicicleta:
        bici_actual = pb.get_record("bicicletas", bicicleta_id)
        if bici_actual.get("estado") != "disponible":
            raise ValueError(
                f"{bicicleta_codigo} ya no está disponible -- alguien más la reservó primero."
            )
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

- [ ] **Step 3: Confirmar que `reservar()` y `reservar_grupo()` no necesitan cambios**

Leer `app/routers/ciclista.py:667-698` (`reservar()`) y `app/routers/ciclista.py:820-918`
(`reservar_grupo()`) y confirmar:
- `reservar()`: la llamada a `_crear_viaje()` (línea ~672) ya está dentro de un
  `try: ... except Exception as e: flash error`. Un `ValueError` de disponibilidad cae ahí sin
  cambios, y como el `raise` ahora ocurre ANTES de `pb.create_record`, no queda ningún viaje
  huérfano que limpiar para este caso (a diferencia de otros fallos de `reservar_grupo()`).
- `reservar_grupo()`: la llamada a `_crear_viaje()` dentro del `for i in range(n)` (línea
  ~826) ya está dentro del mismo bloque `try` que dispara `_revertir_reserva_grupal(...)` en
  el `except`. Si la bici #2 de 3 ya no está disponible, la #1 (ya creada en la iteración
  anterior) se revierte igual que cualquier otro fallo a mitad de lote -- mecanismo ya
  existente, sin cambios.

No se necesita ninguna edición en estas dos funciones -- este paso es de verificación de
lectura, no de escritura.

- [ ] **Step 4: Levantar el servidor y confirmar arranque limpio**

```bash
cd "C:\Users\Washington Apunte\Desktop\urbanbike\.claude\worktrees\fix-reservas-concurrentes-exclusividad"
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8001
```

(usa el puerto 8001, no 8000, para no chocar con ninguna otra instancia que pueda estar
corriendo desde el worktree principal). Confirmar en el log: `Application startup complete.`
sin tracebacks.

- [ ] **Step 5: Commit**

```bash
git add app/routers/ciclista.py
git commit -m "fix: relee estado real de la bicicleta antes de crear el viaje (FR-005)"
```

---

### Task 2: Verificación E2E real -- doble reserva concurrente de la misma bici

**Files:**
- Create: `docs/superpowers/plans/verificacion_2026-08-21_concurrencia.py` (script desechable
  de verificación, NO parte del código de producción -- se borra en el Task 3 tras confirmar,
  mismo criterio que las verificaciones E2E ya documentadas en `docs/HOJA_DE_RUTA.md`, que se
  ejecutan una vez y quedan documentadas en prosa, no como test permanente).

**Interfaces:**
- Consumes: servidor real corriendo en `http://127.0.0.1:8001` (Task 1, Step 4), credenciales
  reales `ciclista@urbanbike.com` / `Urbanbike123!` (mismas usadas en la verificación de la
  sección 79 de `docs/HOJA_DE_RUTA.md`), API REST real de PocketBase en
  `http://127.0.0.1:8090` con superusuario `admin@urbanbike.com` / `secret_pocketbase` (de
  `.env`) para preparar/inspeccionar/limpiar el estado real antes y después.
- Produces: evidencia real (impresa a stdout) de que, al disparar 2 POSTs simultáneos a
  `/ciclista/reservar` para la MISMA bicicleta, como máximo 1 crea un viaje "activo" -- no hay
  interfaz de código consumida por otras tareas.

- [ ] **Step 1: Elegir una bicicleta de prueba real y confirmar su estado**

```bash
TOKEN=$(curl -s -X POST "http://localhost:8090/api/collections/_superusers/auth-with-password" \
  -H "Content-Type: application/json" \
  -d '{"identity":"admin@urbanbike.com","password":"secret_pocketbase"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s "http://localhost:8090/api/collections/bicicletas/records?filter=estado%3D%22disponible%22&perPage=1" \
  -H "Authorization: $TOKEN" | python3 -m json.tool
```

Anotar el `id` y `codigo` de la bicicleta devuelta (ej. `UB-00X` / `abc123...`) -- se usa en
los pasos siguientes. Confirmar que su `estacion` tiene un registro real en la colección
`estaciones` (necesario para el form de `/ciclista/reservar`) -- si la bici elegida no tiene
estación resuelta, elegir otra de la misma lista.

- [ ] **Step 2: Escribir el script de verificación**

Crear `docs/superpowers/plans/verificacion_2026-08-21_concurrencia.py`:

```python
"""Verificacion E2E desechable (Task 2 del plan de reservas concurrentes,
21-ago-2026): dispara 2 POST reales y simultaneos a /ciclista/reservar
para la MISMA bicicleta y confirma que como maximo 1 tiene exito.
Requiere el servidor real corriendo en el puerto 8001 (ver Task 1 Step 4)
y PocketBase real en 8090. Se borra al final del Task 3."""
import concurrent.futures
import sys

import requests

BASE = "http://127.0.0.1:8001"
PB = "http://127.0.0.1:8090"
EMAIL = "ciclista@urbanbike.com"
PASSWORD = "Urbanbike123!"

# Completar con lo obtenido en el Step 1:
BICICLETA_ID = sys.argv[1]
BICICLETA_CODIGO = sys.argv[2]
ESTACION_ID = sys.argv[3]
ESTACION_NOMBRE = sys.argv[4]


def login_sesion() -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", data={"email": EMAIL, "password": PASSWORD}, allow_redirects=True)
    assert r.status_code == 200, f"login fallo: {r.status_code} {r.text[:300]}"
    return s


def reservar(s: requests.Session) -> requests.Response:
    return s.post(
        f"{BASE}/ciclista/reservar",
        data={
            "bicicleta_id": BICICLETA_ID,
            "bicicleta_codigo": BICICLETA_CODIGO,
            "estacion_inicio_id": ESTACION_ID,
            "estacion_inicio_nombre": ESTACION_NOMBRE,
            "modalidad": "hora",
            "latitud": "0",
            "longitud": "0",
        },
        allow_redirects=False,
    )


def main() -> None:
    # 2 sesiones logueadas independientes (misma cuenta, mismo criterio que
    # "2 pestañas del mismo usuario" o "2 usuarios distintos" -- lo que
    # importa es que sean 2 requests HTTP concurrentes reales, no 2 hilos
    # compartiendo el mismo objeto Session).
    s1, s2 = login_sesion(), login_sesion()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(reservar, s1)
        f2 = ex.submit(reservar, s2)
        r1, r2 = f1.result(), f2.result()

    print("Request 1:", r1.status_code, r1.headers.get("location"))
    print("Request 2:", r2.status_code, r2.headers.get("location"))

    exitosos = [r for r in (r1, r2) if r.status_code == 302 and "/ciclista/viaje-activo/" in (r.headers.get("location") or "")]
    print(f"Exitosos: {len(exitosos)} de 2 (debe ser exactamente 1 si el fix funciona)")

    if len(exitosos) == 1:
        print("PASS: exactamente 1 de las 2 solicitudes concurrentes reservo la bici.")
    elif len(exitosos) == 0:
        print("FALLO: ninguna reservo -- revisar si la bici de prueba ya estaba en_uso antes de correr esto.")
        sys.exit(1)
    else:
        print("FALLO REAL DEL BUG: las 2 solicitudes concurrentes reservaron la MISMA bici.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Correr el script CONTRA el código ya arreglado (Task 1) y confirmar PASS**

```bash
cd "C:\Users\Washington Apunte\Desktop\urbanbike\.claude\worktrees\fix-reservas-concurrentes-exclusividad"
.venv/Scripts/python.exe docs/superpowers/plans/verificacion_2026-08-21_concurrencia.py \
  <BICICLETA_ID> <BICICLETA_CODIGO> <ESTACION_ID> "<ESTACION_NOMBRE>"
```

Esperado: `PASS: exactamente 1 de las 2 solicitudes concurrentes reservo la bici.`

- [ ] **Step 4: (Opcional pero recomendado) Confirmar el bug real ANTES del fix**

Si se quiere evidencia directa de que el bug era real (no solo teórico): hacer
`git stash` de los cambios del Task 1 dentro del worktree, reiniciar el servidor del Step 4
del Task 1, correr el mismo script contra OTRA bicicleta disponible, confirmar que imprime
`FALLO REAL DEL BUG: las 2 solicitudes concurrentes reservaron la MISMA bici.`, y luego
`git stash pop` para restaurar el fix y volver a levantar el servidor. Documentar el resultado
(PASS/FALLO de cada corrida) en el Task 3.

- [ ] **Step 5: Limpiar el/los viaje(s) de prueba creados**

Usando el mismo patrón aplicado hoy en `docs/HOJA_DE_RUTA.md` sección 79 (reversión manual,
mismo orden que `_revertir_reserva_grupal()`: notificaciones → bicicleta a disponible → borrar
viaje(s) → una entrada de auditoría compensatoria `accion="eliminar"` explicando que fue una
verificación de este plan, nunca borrar la entrada de auditoría original de "crear viajes").
Confirmar con `curl` que la bicicleta de prueba volvió a `estado="disponible"` y que no quedó
ningún viaje "activo" huérfano de esta verificación.

---

### Task 3: Documentar el hallazgo y cerrar la deuda conocida

**Files:**
- Modify: `docs/HOJA_DE_RUTA.md` (nueva sección numerada, siguiente a la última existente en
  este worktree -- releer el archivo para confirmar el número real antes de escribir, puede
  haber cambiado si `main` se actualizó)
- Modify: `docs/HOJA_DE_RUTA.md` sección 78, "Deuda conocida -- 3 seguimientos..." -- el punto
  2 ("Condición de carrera al marcar una bicicleta 'en uso'") se marca resuelto con un enlace
  a la nueva sección, sin borrar el texto original (mismo criterio ya usado en el punto 14 de
  la sección 0 esta misma sesión: se anota "Sigue abierto"/"Resuelto", nunca se reescribe la
  entrada vieja).
- Delete: `docs/superpowers/plans/verificacion_2026-08-21_concurrencia.py` (script desechable
  del Task 2, ya cumplió su propósito).

**Interfaces:** N/A -- solo documentación y limpieza de un archivo temporal.

- [ ] **Step 1: Agregar la sección nueva a `docs/HOJA_DE_RUTA.md`**

Con el número de sección correcto (siguiente al último existente), documentar en el mismo
estilo que el resto del archivo: qué se reportó, la causa real encontrada (ausencia total de
chequeo de disponibilidad en `_crear_viaje()`, no solo una ventana de carrera fina), el fix
exacto (relectura real + `threading.Lock` de módulo, con la limitación explícita de que es un
lock de proceso, no distribuido -- documentar esto igual que se documentan otras limitaciones
conocidas en este archivo), y el resultado real de la verificación del Task 2 (con o sin la
corrida "antes del fix" del Step 4 opcional).

- [ ] **Step 2: Actualizar el punto 2 de la Deuda Conocida (sección 78)**

Agregar una frase al final del punto 2 existente: "**Resuelto el 21-ago-2026** (ver sección
[N] del worktree `fix-reservas-concurrentes-exclusividad`) -- `_crear_viaje()` ahora relee el
estado real antes de escribir, dentro de un lock de proceso." Sin borrar el análisis original.

- [ ] **Step 3: Borrar el script desechable de verificación**

```bash
git rm docs/superpowers/plans/verificacion_2026-08-21_concurrencia.py
```

- [ ] **Step 4: Commit**

```bash
git add docs/HOJA_DE_RUTA.md
git commit -m "docs: documentar fix real de reservas concurrentes (FR-005) y cerrar deuda conocida"
```

No hacer merge a `main` ni push -- este worktree queda listo para que Washington lo revise y
decida el momento/proceso de fusión, mismo criterio que el resto de los worktrees de este
proyecto.
