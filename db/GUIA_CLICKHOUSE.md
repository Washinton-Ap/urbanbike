# Guía de ClickHouse para UrbanBike

## 1. Dónde está la base de datos

ClickHouse corre en un contenedor Docker, no es un archivo que puedas abrir como SQLite. Los datos viven dentro del contenedor (o en un volumen de Docker), y tú te conectas por red.

Dos puertos importan:

| Puerto | Para qué sirve |
|---|---|
| 8123 | HTTP. Lo usan el navegador, `curl`, Python (`clickhouse-connect`) y el generador de ERD |
| 9000 | Protocolo nativo. Lo usa `clickhouse-client` |

Para ver si está corriendo:

```bash
docker ps
```

Busca una línea con imagen `clickhouse/clickhouse-server`. Si no aparece, levántalo:

```bash
docker start clickhouse
```

Si nunca lo creaste, este comando lo crea con volumen persistente:

```bash
docker run -d --name clickhouse ^
  -p 8123:8123 -p 9000:9000 ^
  -v urbanbike_ch_data:/var/lib/clickhouse ^
  --ulimit nofile=262144:262144 ^
  clickhouse/clickhouse-server
```

En PowerShell usa acento grave en lugar de `^` para los saltos de línea, o escríbelo todo en una sola línea.

Prueba rápida de que responde:

```bash
curl "http://localhost:8123/?query=SELECT%20version()"
```

## 2. Cómo ver la base de datos

### Opción A: la interfaz web incluida (la más cómoda)

Abre en el navegador:

```
http://localhost:8123/play
```

Es un editor de consultas que viene dentro de ClickHouse. Escribes SQL, presionas Ctrl+Enter y ves el resultado en tabla. No necesitas instalar nada.

### Opción B: consola dentro del contenedor

```bash
docker exec -it clickhouse clickhouse-client
```

Te deja en un prompt donde escribes SQL directamente.

### Opción C: desde tu terminal con curl

```bash
curl "http://localhost:8123/?query=SHOW%20DATABASES"
```

## 3. Comandos para explorar el esquema

```sql
-- Qué bases existen
SHOW DATABASES;

-- Qué tablas tiene la base operativa
SHOW TABLES FROM urbanbike_operativa;

-- Estructura de una tabla
DESCRIBE TABLE urbanbike_operativa.bicicletas;

-- El CREATE TABLE completo, con motor y clave de ordenamiento
SHOW CREATE TABLE urbanbike_operativa.bicicletas;

-- Resumen de todas las tablas con su motor y cuántas filas tienen
SELECT name, engine, total_rows, formatReadableSize(total_bytes) AS tamano
FROM system.tables
WHERE database = 'urbanbike_operativa'
ORDER BY name;

-- Todas las columnas de la base, útil para revisar tipos
SELECT table, name, type
FROM system.columns
WHERE database = 'urbanbike_operativa'
ORDER BY table, position;
```

## 4. Cómo ver el diagrama ERD

ClickHouse no tiene diagrama entidad relación nativo, porque no guarda claves foráneas: las relaciones existen por convención, no por restricción del motor. Por eso el proyecto incluye un generador propio.

```bash
python db/erd_clickhouse.py --db urbanbike_operativa --salida erd_operativa.mmd
```

Imprime en consola un resumen de tablas, motores y claves de ordenamiento, y escribe un archivo `.mmd`. Para verlo como diagrama, copia el contenido del archivo y pégalo en https://mermaid.live

También puedes verlo dentro de VS Code instalando la extensión "Markdown Preview Mermaid Support" y pegando el contenido dentro de un bloque de código con la etiqueta `mermaid`.

Si quieres un diagrama menos cargado, omite las tablas sueltas:

```bash
python db/erd_clickhouse.py --db urbanbike_operativa --solo-relacionadas --salida erd_resumen.mmd
```

## 5. Cargar el esquema de esta fase

```bash
# Crear las tablas
docker exec -i clickhouse clickhouse-client --multiquery < db/01_operativa_schema.sql

# Cargar datos de prueba
docker exec -i clickhouse clickhouse-client --multiquery < db/02_operativa_seed.sql

# Comprobar
docker exec -it clickhouse clickhouse-client --query "
SELECT name, total_rows FROM system.tables
WHERE database='urbanbike_operativa' AND total_rows > 0 ORDER BY name"
```

## 6. Tres cosas de ClickHouse que cambian tu forma de programar

**No hay UPDATE fila por fila.** Las tablas de entidades usan el motor `ReplacingMergeTree(version)`. Para "actualizar" un registro, insertas otra fila con el mismo `id` y un `version` mayor. El motor conserva la última al fusionar sus partes internas.

```sql
-- Cambiar el estado de una bicicleta: no es UPDATE, es INSERT
INSERT INTO urbanbike_operativa.bicicletas
SELECT id, codigo, id_modelo, id_estacion, numero_serie,
       'en_uso' AS estado,                      -- el campo que cambia
       fecha_adquisicion, km_acumulados, minutos_uso,
       fecha_ultimo_mantenimiento, observacion,
       now() AS version                          -- versión nueva
FROM urbanbike_operativa.bicicletas FINAL
WHERE id = '55555555-0000-0000-0000-000000000001';
```

**Para leer el estado vigente usa FINAL, y el alias va antes.** Esta es la sintaxis correcta:

```sql
FROM urbanbike_operativa.bicicletas AS b FINAL     -- correcto
FROM urbanbike_operativa.bicicletas FINAL AS b     -- error de sintaxis
```

Las tablas de eventos (`auditoria`, `gastos`, `alquiler_eventos`, `movimientos_repuesto`) nunca llevan `FINAL`, porque sus filas no cambian.

**No hay claves foráneas ni integridad referencial.** Si insertas un `id_bicicleta` que no existe, ClickHouse lo acepta sin protestar. La validación tiene que hacerla tu aplicación FastAPI antes de escribir.

## 7. Conectar FastAPI a ClickHouse

```bash
pip install clickhouse-connect
```

```python
import clickhouse_connect

cliente = clickhouse_connect.get_client(
    host='localhost', port=8123,
    username='default', password='',
    database='urbanbike_operativa'
)

# Consulta que devuelve filas
filas = cliente.query(
    "SELECT codigo, estado FROM bicicletas AS b FINAL WHERE estado = {est:String}",
    parameters={'est': 'disponible'}
).result_rows

# Inserción
cliente.insert('repuestos',
    [['R-0005', 'Manubrio', 'cuadro', 10, 5, 18.50]],
    column_names=['codigo', 'nombre', 'categoria',
                  'stock_actual', 'stock_minimo', 'costo_unitario'])
```
