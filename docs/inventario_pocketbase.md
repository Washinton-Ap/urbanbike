# Inventario de PocketBase — urbanbike_pocketbase

Generado por inspección en vivo contra la instancia de PocketBase corriendo en Docker, antes de diseñar la migración hacia `urbanbike_operativa` en ClickHouse (ver `db/01_operativa_schema.sql`). No incluye las colecciones internas de PocketBase (`_mfas`, `_otps`, `_externalAuths`, `_authOrigins`, `_superusers`).

## auditoria
- Tipo: `base`
- Registros: 530
- Campos:
  - `id` (text, required=True)
  - `usuario_id` (text, required=False)
  - `usuario_nombre` (text, required=False)
  - `usuario_email` (text, required=False)
  - `accion` (select, required=True) — opciones: crear, editar, eliminar, login, logout
  - `modulo` (text, required=False)
  - `detalle` (text, required=False)
  - `ip_cliente` (text, required=False)
  - `fecha` (text, required=False)
  - `usuario_rol` (text, required=False)

## bicicletas
- Tipo: `base`
- Registros: 11
- Campos:
  - `id` (text, required=True)
  - `codigo` (text, required=True)
  - `tipo` (select, required=False) — opciones: classic_bike, electric_bike
  - `estado` (select, required=False) — opciones: disponible, en_uso, mantenimiento, retirada
  - `estacion` (text, required=False)
  - `notas` (text, required=False)
  - `foto` (file, required=False)

## bitacora_cambios
- Tipo: `base`
- Registros: 37
- Campos:
  - `id` (text, required=True)
  - `usuario_nombre` (text, required=True)
  - `accion` (text, required=True)
  - `detalle` (text, required=False)
  - `fecha` (date, required=True)

## cuentas_bancarias
- Tipo: `base`
- Registros: 3
- Campos:
  - `id` (text, required=True)
  - `banco` (text, required=True)
  - `tipo_cuenta` (text, required=False)
  - `numero_cuenta` (text, required=True)
  - `titular` (text, required=False)
  - `activa` (bool, required=False)

## estaciones
- Tipo: `base`
- Registros: 9
- Campos:
  - `id` (text, required=True)
  - `nombre` (text, required=True)
  - `codigo` (text, required=False)
  - `capacidad` (number, required=False)
  - `latitud` (number, required=False)
  - `longitud` (number, required=False)
  - `activa` (bool, required=False)

## estaciones_op
- Tipo: `base`
- Registros: 3
- Campos:
  - `id` (text, required=True)
  - `nombre` (text, required=True)
  - `id_clickhouse` (text, required=False)
  - `latitud` (number, required=False)
  - `longitud` (number, required=False)
  - `capacidad` (number, required=False)
  - `activa` (bool, required=False)

## infracciones
- Tipo: `base`
- Registros: 2
- Campos:
  - `id` (text, required=True)
  - `ciclista_id` (text, required=False)
  - `tipo` (text, required=False)
  - `descripcion` (text, required=False)
  - `bicicleta_id` (text, required=False)
  - `bicicleta_codigo` (text, required=False)
  - `resuelta` (bool, required=False)
  - `resolucion` (text, required=False)
  - `fecha` (text, required=False)
  - `fecha_resolucion` (text, required=False)
  - `resuelta_por` (text, required=False)
  - `notificada_por` (text, required=False)

## ordenes_mant
- Tipo: `base`
- Registros: 4
- Campos:
  - `id` (text, required=True)
  - `bicicleta_id` (text, required=False)
  - `bicicleta_codigo` (text, required=False)
  - `tipo` (select, required=False) — opciones: preventivo, correctivo, urgente
  - `descripcion` (text, required=False)
  - `estado` (select, required=False) — opciones: pendiente, en_proceso, completado
  - `tecnico_nombre` (text, required=False)
  - `fecha_apertura` (text, required=False)
  - `fecha_cierre` (text, required=False)
  - `notificada_por` (text, required=False)
  - `origen` (text, required=False)
  - `certificada_por` (text, required=False)
  - `observaciones_cierre` (text, required=False)
  - `observaciones` (text, required=False)
  - `fecha_inicio_trabajo` (text, required=False)

## pagos
- Tipo: `base`
- Registros: 22
- Campos:
  - `id` (text, required=True)
  - `viaje_id` (text, required=False)
  - `ciclista_id` (text, required=False)
  - `ciclista_nombre` (text, required=False)
  - `duracion_minutos` (number, required=False)
  - `tipo_bicicleta` (text, required=False)
  - `tipo_membresia` (text, required=False)
  - `precio_hora` (number, required=False)
  - `monto_total` (number, required=False)
  - `estado` (select, required=False) — opciones: cancelado, pagado, pendiente, pendiente_efectivo, rechazado, verificacion_pendiente
  - `metodo_pago` (select, required=False) — opciones: efectivo, tarjeta, transferencia
  - `fecha_pago` (text, required=False)
  - `comprobante_numero` (text, required=False)
  - `comprobante_imagen` (file, required=False)
  - `numero_cuenta_origen` (text, required=False)
  - `numero_tarjeta_ultimos4` (text, required=False)
  - `confirmado_por_empleado_id` (text, required=False)
  - `confirmado_por_empleado_nombre` (text, required=False)
  - `fecha_confirmacion` (text, required=False)
  - `observaciones_pago` (text, required=False)
  - `intento_numero` (number, required=False)
  - `es_presencial` (bool, required=False)
  - `empleado_id` (text, required=False)
  - `tipo` (text, required=False)
  - `descripcion_cargo` (text, required=False)

## roles
- Tipo: `base`
- Registros: 6
- Campos:
  - `id` (text, required=True)
  - `nombre` (text, required=True)
  - `slug` (text, required=True)
  - `descripcion` (text, required=False)

## tarifas
- Tipo: `base`
- Registros: 5
- Campos:
  - `id` (text, required=True)
  - `tipo_bicicleta` (select, required=True) — opciones: classic_bike, electric_bike
  - `tipo_usuario` (select, required=True) — opciones: member, casual
  - `precio_hora` (number, required=True)
  - `activa` (bool, required=False)

## users
- Tipo: `auth`
- Registros: 10
- Campos:
  - `id` (text, required=True)
  - `password` (password, required=True)
  - `tokenKey` (text, required=True)
  - `email` (email, required=True)
  - `emailVisibility` (bool, required=False)
  - `verified` (bool, required=False)
  - `name` (text, required=False)
  - `avatar` (file, required=False)
  - `created` (autodate, required=None)
  - `updated` (autodate, required=None)
  - `rol` (relation, required=False) — relation -> collectionId `pbc_2105053228`
  - `activo` (bool, required=False)

## viajes
- Tipo: `base`
- Registros: 26
- Campos:
  - `id` (text, required=True)
  - `ciclista_id` (text, required=False)
  - `ciclista_nombre` (text, required=False)
  - `bicicleta_id` (text, required=False)
  - `bicicleta_codigo` (text, required=False)
  - `estacion_inicio_id` (text, required=False)
  - `estacion_inicio_nombre` (text, required=False)
  - `estacion_fin_id` (text, required=False)
  - `latitud_inicio` (number, required=False)
  - `longitud_inicio` (number, required=False)
  - `latitud_actual` (number, required=False)
  - `longitud_actual` (number, required=False)
  - `estado` (select, required=False) — opciones: activo, completado, cancelado
  - `fecha_inicio` (text, required=False)
  - `fecha_fin` (text, required=False)
  - `duracion_minutos` (number, required=False)
  - `alerta_atendida` (bool, required=False)
  - `es_presencial` (bool, required=False)
  - `ciclista_contacto` (text, required=False)

## viajes_activos
- Tipo: `base`
- Registros: 0
- Campos:
  - `id` (text, required=True)
  - `started_at` (autodate, required=None)
  - `lat_inicio` (number, required=False)
  - `lng_inicio` (number, required=False)
  - `usuario` (relation, required=True) — relation -> collectionId `_pb_users_auth_`
  - `bicicleta` (relation, required=True) — relation -> collectionId `pbc_1089097567`
  - `estacion_inicio` (relation, required=True) — relation -> collectionId `pbc_3456418756`
