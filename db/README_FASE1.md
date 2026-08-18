# Fase 1: base de datos operativa en ClickHouse

## Qué contiene esta entrega

| Archivo | Para qué sirve |
|---|---|
| `01_operativa_schema.sql` | Crea la base `urbanbike_operativa` con 29 tablas |
| `02_operativa_seed.sql` | Datos de prueba para verificar que todo funciona |
| `03_informes_simples.sql` | Las 21 consultas de los informes S01 a S18, verificadas |
| `erd_clickhouse.py` | Genera el diagrama ERD desde las tablas del sistema |
| `GUIA_CLICKHOUSE.md` | Dónde está la base, cómo verla y cómo trabajar con ella |

Todo fue ejecutado y verificado contra ClickHouse 26.8 antes de entregarlo.

## Cómo aplicarlo

```bash
# 1. Verifica que ClickHouse esté corriendo
docker ps

# 2. Crea las tablas
docker exec -i clickhouse clickhouse-client --multiquery < db/01_operativa_schema.sql

# 3. Carga datos de prueba
docker exec -i clickhouse clickhouse-client --multiquery < db/02_operativa_seed.sql

# 4. Comprueba
docker exec -it clickhouse clickhouse-client --query "SELECT name, total_rows FROM system.tables WHERE database='urbanbike_operativa' ORDER BY name"

# 5. Genera el diagrama
python db/erd_clickhouse.py --db urbanbike_operativa --salida erd_operativa.mmd
```

## Qué observación del docente cubre cada tabla

| Observación | Tablas que la resuelven |
|---|---|
| 1. Alquiler por día, promoción y descuento | `tarifas` (modalidad hora, día, semana, por bicicleta), `promociones` |
| 2. Control de repuestos | `repuestos`, `movimientos_repuesto`, `orden_repuesto` |
| 3. Diseño e identidad de bicicleta | Corresponde al frontend, se aborda en la fase 3 |
| 4. Información completa de bicicletas | `marcas`, `modelos_bicicleta` (marchas, frenos, suspensión, rodado, material), `bicicleta_fotos` |
| 5. Catálogo premium y categorías | `categorias` con la bandera `es_premium` |
| 6. Garantía con tarjeta y cobro automático | `metodos_pago`, `garantias`, `cobros_automaticos` |
| 7. Facturación | `facturas`, `factura_detalle`, `pagos`, `gastos` |
| 8. Flujo visual del alquiler | `alquileres` con siete estados y `alquiler_eventos` como línea de tiempo |
| 9. Mantenimiento no solo en la devolución | `planes_mantenimiento`, `mantenimientos_programados`, `ordenes_mantenimiento` con campo `origen` |
| 10. Checklist de devolución más completo | `checklist_items` con doce puntos, `inspecciones`, `inspeccion_detalle` |
| Verificación de ganancia | `pagos` como entradas y `gastos` como salidas, consulta S01b |

## Prompt para Claude Code

Pega esto en Claude Code dentro de la carpeta del proyecto:

```
Contexto: el proyecto UrbanBike migra de PocketBase a ClickHouse. La base operativa
nueva se llama urbanbike_operativa y su esquema está en db/01_operativa_schema.sql.

Tarea de esta sesión:
1. Crea el módulo app/db/clickhouse.py con un cliente único usando clickhouse-connect,
   leyendo host, puerto, usuario y clave desde variables de entorno con valores por
   defecto localhost, 8123, default y vacío.
2. Crea app/repos/ con un repositorio por área: flota.py, tarifas.py, alquiler.py,
   pagos.py, mantenimiento.py, inspeccion.py.
3. En cada repositorio implementa las consultas de db/03_informes_simples.sql que le
   correspondan, como funciones que reciban los parámetros y devuelvan listas de
   diccionarios.
4. Respeta estas reglas de ClickHouse:
   - Para leer el estado vigente de una entidad, el alias va antes de FINAL:
     FROM tabla AS x FINAL. Nunca escribas FROM tabla FINAL AS x, es error de sintaxis.
   - Las tablas de eventos (auditoria, gastos, alquiler_eventos, movimientos_repuesto)
     nunca llevan FINAL.
   - No existe UPDATE: para cambiar un registro inserta una fila nueva con el mismo id
     y version igual a now().
   - No hay claves foráneas: valida en la aplicación antes de insertar.
5. No toques todavía las plantillas ni las rutas. Solo la capa de datos.
```

## Qué sigue

| Fase | Contenido |
|---|---|
| 2 | Base analítica `urbanbike_analitica` con zona táctica y estratégica, esquema estrella y el ETL de Airflow cada quince minutos |
| 3 | Refactor de la capa de datos de FastAPI y migración de los datos actuales |
| 4 | Rediseño de la interfaz con identidad de bicicleta, catálogo con filtros, flujo visual del alquiler y checklist ampliado |
